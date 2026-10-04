"""Reference feeds (fbi.ingestion.reference): the endpoints the contract audit found missing, written
change-only from their RAW answers, asked on their cadence, never into the live reserve. Shapes are the
provider's, as the contract probe of 4 Oct 2026 stored them (batched /sidelined and /trophies answer one
block per person: ``{"id": .., "sidelined": [..]}`` - a shape the documentation does not show)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ingestion import reference as ref
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime = T0, endpoint: str = "/x") -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, %s, '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING",
               (h, seed.run_id, endpoint, at, h))
    return h


@pytest.fixture()
def committed(db: psycopg.Connection) -> Any:
    """A run commits (it is a worker job): what it wrote is removed after the test."""
    yield db
    db.rollback()
    db.execute("DELETE FROM core.countries WHERE payload_hash LIKE 'fk%%'")
    db.execute("DELETE FROM core.person_trophies WHERE payload_hash LIKE 'pp%%'")
    db.execute("DELETE FROM core.reference_checks WHERE feed IN ('countries', 'trophies_players')")
    db.execute("DELETE FROM raw.ingestion_payloads WHERE hash LIKE 'fk%%' OR hash LIKE 'pp%%'")
    db.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'reference_refresh'")
    db.commit()


def target(**context: Any) -> ref.Target:
    return ref.Target("k", dict(context.pop("params", {})), timedelta(days=1), context)


PREDICTION: dict[str, Any] = {"predictions": {"winner": {"id": 33, "name": "Manchester United", "comment": "Win or draw"},
                              "win_or_draw": True, "under_over": None, "goals": {"home": "-2.5", "away": "-2.5"},
                              "advice": "Double chance : Manchester United or draw",
                              "percent": {"home": "45%", "draw": "45%", "away": "10%"}},
              "comparison": {"form": {"home": "70%", "away": "30%"}, "total": {"home": "59.0%", "away": "41.0%"}},
              "teams": {"home": {"id": 33}, "away": {"id": 40}}, "h2h": []}


def test_a_prediction_is_kept_change_only_and_labelled_as_the_providers(db: psycopg.Connection, seed: Seed) -> None:
    t = target(fixture_id=seed.fixture_id)
    for i in range(4):
        payload(db, seed, f"pr{i}", T0 + timedelta(hours=i))
    assert ref.apply_predictions(db, t, {"response": [PREDICTION]}, "pr0", T0) == 1
    assert ref.apply_predictions(db, t, {"response": [PREDICTION]}, "pr1", T0 + timedelta(hours=1)) == 0
    base: dict[str, Any] = dict(PREDICTION["predictions"])
    moved = {**PREDICTION, "predictions": {**base, "percent": {"home": "50%", "draw": "40%", "away": "10%"}}}
    assert ref.apply_predictions(db, t, {"response": [moved]}, "pr2", T0 + timedelta(hours=2)) == 1
    assert ref.apply_predictions(db, t, {"response": [PREDICTION]}, "pr0", T0) == 0, "older than the newest row"
    assert ref.apply_predictions(db, t, {"response": []}, "pr3", T0 + timedelta(hours=3)) == 0
    row = db.execute("SELECT winner_team_id, win_or_draw, under_over, percent_home, percent_draw, comparison->'total', "
                     "payload_hash FROM core.provider_predictions_latest WHERE fixture_id = %s",
                     (seed.fixture_id,)).fetchone()
    assert row == (33, True, None, Decimal("50.00"), Decimal("40.00"), {"home": "59.0%", "away": "41.0%"}, "pr2")
    comment = db.execute("SELECT obj_description('core.provider_predictions'::regclass)").fetchone()
    assert comment is not None and "never a model input" in comment[0]


def test_percentages_are_read_never_guessed() -> None:
    assert ref._percent("45%") == Decimal("45") and ref._percent("59.0%") == Decimal("59.0")
    assert ref._percent(None) is None and ref._percent("n/a") is None and ref._percent("120%") is None


def test_rounds_are_snapshots_and_the_latest_view_gives_the_newest(db: psycopg.Connection, seed: Seed) -> None:
    t = target(cs_id=seed.season_id)
    for i in range(3):
        payload(db, seed, f"ro{i}", T0 + timedelta(days=i))
    body = {"response": [{"round": "Apertura - 1", "dates": ["2026-01-16", "2026-01-17"]},
                         {"round": "Apertura - 2", "dates": ["2026-01-23"]}]}
    assert ref.apply_rounds(db, t, body, "ro0", T0) == 2
    assert ref.apply_rounds(db, t, body, "ro1", T0 + timedelta(days=1)) == 0
    body["response"].append({"round": "Clausura - 1", "dates": ["2026-07-10"]})
    assert ref.apply_rounds(db, t, body, "ro2", T0 + timedelta(days=2)) == 3
    latest = db.execute("SELECT ordinal, round, dates FROM core.season_rounds_latest WHERE competition_season_id = %s "
                        "ORDER BY ordinal", (seed.season_id,)).fetchall()
    assert [r[1] for r in latest] == ["Apertura - 1", "Apertura - 2", "Clausura - 1"]
    assert str(latest[0][2][1]) == "2026-01-17"
    payload(db, seed, "cr0")
    assert ref.apply_current_round(db, t, {"response": ["Clausura - 13", "Clausura - 17"]}, "cr0", T0) == 1


LEADER = {"player": {"id": 13491, "name": "Y. Guzmán", "photo": "https://media.api-sports.io/football/players/13491.png"},
          "statistics": [{"team": {"id": 1138, "name": "America de Cali"}, "league": {"id": 239, "season": 2026},
                          "games": {"appearences": 29, "minutes": 2397, "rating": "7.55"},
                          "goals": {"total": 18, "assists": 4}, "cards": {"yellow": 4, "yellowred": 0, "red": 0},
                          "penalty": {"scored": 3}}]}


def test_leaders_keep_the_providers_order_and_its_rating(db: psycopg.Connection, seed: Seed) -> None:
    t = ref.Target("k", {"league": 239, "season": 2026}, timedelta(days=1), {"cs_id": seed.season_id,
                                                                              "list": "topscorers"})
    payload(db, seed, "ld0")
    second = {**LEADER, "player": {"id": 7, "name": "B"}}
    assert ref.apply_leaders(db, t, {"response": [LEADER, second, {"player": {"id": 0}}]}, "ld0", T0) == 2
    rows = db.execute("SELECT ordinal, provider_player_id, provider_team_id, goals, minutes, rating, statistics->>'games' "
                      "IS NOT NULL FROM core.season_leaders WHERE competition_season_id = %s ORDER BY ordinal",
                      (seed.season_id,)).fetchall()
    assert rows[0] == (0, 13491, 1138, 18, 2397, Decimal("7.5500"), True) and rows[1][1] == 7


def test_a_coach_profile_and_career_are_kept(db: psycopg.Connection, seed: Seed) -> None:
    payload(db, seed, "co0")
    body = {"response": [{"id": 2172, "name": "J. González", "age": 50, "birth": {"date": "1975-02-16"},
                          "nationality": "Colombia", "photo": "https://media.api-sports.io/football/coachs/2172.png",
                          "team": {"id": 1126}, "career": [
                              {"team": {"id": 1126, "name": "Deportivo Pasto"}, "start": "2023-11-01", "end": None},
                              {"team": {"id": 1464, "name": "Llaneros"}, "start": "2022-04-01", "end": "2023-11-01"}]}]}
    assert ref.apply_coachs(db, target(), body, "co0", T0) == 3
    assert db.execute("SELECT birth_date::text, photo_url IS NOT NULL FROM core.coach_profiles_latest "
                      "WHERE provider_coach_id = 2172").fetchone() == ("1975-02-16", True)
    assert db.execute("SELECT count(*) FROM core.coach_careers_latest WHERE provider_coach_id = 2172 "
                      "AND end_date IS NULL").fetchone() == (1,)


def test_batched_people_answers_are_attributed_by_the_id_in_each_block(db: psycopg.Connection, seed: Seed) -> None:
    payload(db, seed, "sd0")
    payload(db, seed, "tr0")
    batch = ref.Target("k", {"players": "5179-6000"}, timedelta(days=7),
                       {"kind": "player", "ids": [5179, 6000], "list_key": "sidelined"})
    body = {"response": [{"id": 5179, "sidelined": [{"type": "Injury", "start": "2021-07-25", "end": "2021-07-31"}]}]}
    assert ref.apply_sidelined(db, batch, body, "sd0", T0) == 1
    single = ref.Target("k", {"coach": 3470}, timedelta(days=7), {"kind": "coach", "ids": [3470],
                                                                  "list_key": "trophies"})
    tro = {"response": [{"league": "Primera B", "country": "Colombia", "season": "2022", "place": "Winner"},
                        {"league": "Primera B", "country": "Colombia", "season": None, "place": "Winner"}]}
    assert ref.apply_trophies(db, single, tro, "tr0", T0) == 2
    nameless = ref.Target("k", {"players": "1-2"}, timedelta(days=7), {"kind": "player", "ids": [1, 2],
                                                                        "list_key": "trophies"})
    assert ref.apply_trophies(db, nameless, tro, "tr0", T0) == 0, "a batched answer without ids is not guessed"
    assert db.execute("SELECT person_kind, provider_person_id, type FROM core.person_sidelined_latest").fetchall() \
        == [("player", 5179, "Injury")]


def test_transfers_mapping_countries_and_a_renamed_bet(db: psycopg.Connection, seed: Seed) -> None:
    for h in ("tf0", "om0", "om1", "cn0", "bt0"):
        payload(db, seed, h)
    tf = {"response": [{"player": {"id": 79186, "name": "F. Álvarez"}, "update": "2023-09-07T01:32:47+00:00",
                        "transfers": [{"date": "2016-06-30", "type": "N/A", "teams": {"in": {"id": 1132, "name": "Chico"},
                                                                                     "out": {"id": 1126}}}]}]}
    assert ref.apply_transfers(db, target(), tf, "tf0", T0) == 1
    om = {"response": [{"league": {"id": 850, "season": 2027}, "fixture": {"id": 1350168, "timestamp": 1790613000},
                        "update": "2026-09-28T12:00:19+00:00"}]}
    assert ref.apply_odds_mapping(db, target(), om, "om0", T0) == 1
    assert ref.apply_odds_mapping(db, target(), om, "om1", T0 + timedelta(days=1)) == 0, "first sighting only"
    assert ref.apply_countries(db, target(), {"response": [{"name": "Albania", "code": "AL", "flag": "x.svg"}]},
                               "cn0", T0) == 1
    db.execute("INSERT INTO market.provider_markets (provider, scope, provider_bet_id, name, source) "
               "VALUES ('api-football', 'prematch', 999, 'Old Name', 'catalogue') ON CONFLICT DO NOTHING")
    body = {"response": [{"id": 999, "name": "New Name"}, {"id": 998, "name": "Brand New"}]}
    assert ref.apply_catalogue(db, target(catalogue="prematch"), body, "bt0", T0) == 1
    assert db.execute("SELECT old_name, new_name FROM market.provider_catalogue_changes WHERE provider_id = 999"
                      ).fetchone() == ("Old Name", "New Name")


class FakeProvider:
    def __init__(self, db: psycopg.Connection, seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        self.calls.append((endpoint, params))
        h = f"fk{len(self.calls)}"
        body: dict[str, Any] = {"response": [{"name": f"C{len(self.calls)}", "code": "XX", "flag": None}],
                                "paging": {"current": 1, "total": 1}}
        return RawResponse(endpoint=endpoint, params=params, fetched_at=T0, http_status=200, results_count=1,
                           payload_hash=h, file_path=h, bytes_written=1, body=body)


@pytest.mark.asyncio
async def test_a_run_asks_what_is_due_within_its_allowance_and_records_every_check(
        committed: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    db = committed
    import fbi.ingestion.backfill as backfill
    import fbi.providers.quota as quota

    class Usage:
        remaining = 1000

    monkeypatch.setattr(backfill, "live_reserve", lambda *a, **k: 0)
    monkeypatch.setattr(quota, "read_usage", lambda *a, **k: Usage())
    feed = ref.Feed("countries", "/countries", ref.single_target(ref.WEEK), ref.apply_countries, max_per_run=1)
    provider = FakeProvider(db, seed)
    report = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0)
    assert report.asked == {"countries": 1} and provider.calls == [("/countries", {})]
    assert db.execute("SELECT results, rows_added FROM core.reference_checks WHERE feed = 'countries'").fetchone() \
        == (1, 1)
    again = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0 + timedelta(days=1))
    assert again.deferred_reason == "nothing due" and len(provider.calls) == 1, "fresh for a week"
    Usage.remaining = 5
    monkeypatch.setattr(backfill, "live_reserve", lambda *a, **k: 100)
    late = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0 + timedelta(days=8))
    assert late.allowance == 0 and late.deferred_reason and "reserve" in late.deferred_reason


def test_prediction_targets_open_one_window_at_a_time(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_group = 'scheduled' WHERE id = %s",
               (T0 + timedelta(hours=30), seed.fixture_id))
    keys = [t.key for t in ref.prediction_targets(db, T0)]
    assert keys == ["fixture:1001:48h"]
    assert [t.key for t in ref.prediction_targets(db, T0 + timedelta(hours=28))] == ["fixture:1001:3h"]
    assert ref.prediction_targets(db, T0 + timedelta(hours=31)) == [], "kicked off: no prediction asked"


class PeopleProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        self.calls.append(params)
        ids = [int(x) for x in str(params["players"]).split("-")]
        body: dict[str, Any] = {"response": [{"id": i, "trophies": [{"league": "L", "country": "C", "season": "2024",
                                                      "place": "Winner"}]} for i in ids if i != 3]}
        h = f"pp{len(self.calls)}"
        return RawResponse(endpoint=endpoint, params=params, fetched_at=T0, http_status=200, results_count=len(ids),
                           payload_hash=h, file_path=h, bytes_written=1, body=body)


@pytest.mark.asyncio
async def test_people_due_are_asked_in_batches_and_checked_one_by_one(
        committed: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    db = committed
    import fbi.ingestion.backfill as backfill
    import fbi.providers.quota as quota

    class Usage:
        remaining = 1000

    monkeypatch.setattr(backfill, "live_reserve", lambda *a, **k: 0)
    monkeypatch.setattr(quota, "read_usage", lambda *a, **k: Usage())

    def three(conn: psycopg.Connection, at: datetime) -> list[ref.Target]:
        return [ref.Target(f"player:{i}", {"players": str(i)}, ref.WEEK,
                           {"kind": "player", "ids": [i], "list_key": "trophies"}) for i in (1, 2, 3)]

    feed = ref.Feed("trophies_players", "/trophies", three, ref.apply_trophies, max_per_run=5, batch=2,
                    batch_param="players")
    provider = PeopleProvider()
    await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0)
    assert provider.calls == [{"players": "1-2"}, {"players": "3"}]
    checks = db.execute("SELECT target, results FROM core.reference_checks WHERE feed = 'trophies_players' "
                        "ORDER BY target").fetchall()
    assert checks == [("player:1", 1), ("player:2", 1), ("player:3", 0)], "asked and empty is recorded as such"
    assert db.execute("SELECT count(DISTINCT provider_person_id) FROM core.person_trophies").fetchone() == (2,)
    again = await ref.refresh_reference(db, provider, daily_budget=60000, feeds=[feed], at=T0 + timedelta(days=2))
    assert again.deferred_reason == "nothing due" and len(provider.calls) == 2

"""What the product reads from the reference feeds: a player's transfers, periods out and trophies, a
competition's top lists and round calendar, the coach's photo on a line-up, and (admin only) the provider's
own prediction - each with the payload it comes from, and "not read yet" kept apart from "nothing"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg

from fbi.api.envelope import DataStatus
from fbi.api.services import center
from fbi.ingestion import reference as ref
from tests.integration.conftest import Seed

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def payload(db: psycopg.Connection, seed: Seed, h: str) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/x', '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING", (h, seed.run_id, T0, h))
    return h


def a_player(db: psycopg.Connection) -> int:
    row = db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (13491, 'Y. Guzmán') "
                     "RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def test_a_player_page_says_not_read_yet_then_shows_the_lists_with_their_source(db: psycopg.Connection,
                                                                               seed: Seed) -> None:
    pid = a_player(db)
    first = center.player(db, pid).data
    assert first is not None and first.transfers is not None and first.transfers.status is DataStatus.EMPTY
    assert first.transfers.reason and "not been read" in first.transfers.reason and first.provenance == {}
    payload(db, seed, "rp-t")
    payload(db, seed, "rp-s")
    t = ref.Target("k", {}, timedelta(days=7), {})
    ref.apply_transfers(db, t, {"response": [{"player": {"id": 13491}, "update": "2026-08-01T00:00:00+00:00",
                                              "transfers": [{"date": "2025-07-01", "type": "Loan",
                                                             "teams": {"in": {"id": 33, "name": "Manchester United"},
                                                                       "out": {"id": 1138, "name": "America"}}}]}]},
                        "rp-t", T0)
    batch = ref.Target("k", {}, timedelta(days=7), {"kind": "player", "ids": [13491], "list_key": "sidelined"})
    ref.apply_sidelined(db, batch, {"response": [{"type": "Knee Injury", "start": "2026-02-01", "end": "2026-03-01"}]},
                        "rp-s", T0)
    ref.record_check(db, "trophies_players", "player:13491", checked_at=T0, payload_hash=None, results=0,
                     rows_added=0)
    detail = center.player(db, pid).data
    assert detail is not None and detail.transfers is not None and detail.transfers.data[0].type == "Loan"
    assert detail.transfers.data[0].team_in_id == seed.home_team_id, "our team id when we hold the club"
    assert detail.sidelined is not None and detail.sidelined.data[0].type == "Knee Injury"
    assert detail.trophies is not None and detail.trophies.reason == "The provider lists no trophy for this player."
    assert detail.provenance["transfers"].payload_hash == "rp-t"
    assert detail.provenance["trophies"].checked_at == T0 and detail.provenance["trophies"].payload_hash is None


def test_a_competition_reference_shows_the_lists_rounds_and_the_current_round(db: psycopg.Connection,
                                                                             seed: Seed) -> None:
    empty = center.competition_reference(db, seed.competition_id)
    assert empty.data is not None and empty.data.leaders.status is DataStatus.EMPTY
    for h in ("cr-l", "cr-r", "cr-c"):
        payload(db, seed, h)
    t = ref.Target("k", {"league": 39, "season": 2025}, timedelta(days=1), {"cs_id": seed.season_id,
                                                                             "list": "topscorers"})
    ref.apply_leaders(db, t, {"response": [{"player": {"id": 13491, "name": "Y. Guzmán"}, "statistics": [
        {"team": {"id": 33, "name": "Manchester United"}, "league": {"id": 39, "season": 2025},
         "games": {"appearences": 9, "minutes": 800, "rating": "7.20"}, "goals": {"total": 8}}]}]}, "cr-l", T0)
    rt = ref.Target("k", {}, timedelta(days=1), {"cs_id": seed.season_id})
    ref.apply_rounds(db, rt, {"response": [{"round": "Regular Season - 1", "dates": ["2025-08-16"]},
                                           {"round": "Regular Season - 2", "dates": ["2025-08-23"]}]}, "cr-r", T0)
    ref.apply_current_round(db, rt, {"response": ["Regular Season - 2"]}, "cr-c", T0)
    data = center.competition_reference(db, seed.competition_id, season=2025).data
    assert data is not None and data.season == 2025
    top = data.leaders.data[0]
    assert top.kind == "topscorers" and top.rows[0].goals == 8 and top.rows[0].rating == Decimal("7.2000")
    assert top.rows[0].team_id == seed.home_team_id and top.provenance.payload_hash == "cr-l"
    assert [(r.round, r.stage, r.is_current) for r in data.rounds.data] == [
        ("Regular Season - 1", "Regular Season", False), ("Regular Season - 2", "Regular Season", True)]
    assert data.current_rounds == ["Regular Season - 2"]


def test_the_providers_prediction_is_an_admin_view_labelled_as_the_providers(db: psycopg.Connection,
                                                                            seed: Seed) -> None:
    none = center.provider_prediction(db, seed.fixture_id)
    assert none.status is DataStatus.EMPTY and none.reason and "not been read" in none.reason
    payload(db, seed, "pp-1")
    t = ref.Target("k", {}, timedelta(days=1), {"fixture_id": seed.fixture_id})
    ref.apply_predictions(db, t, {"response": [{"predictions": {"winner": {"id": 33, "name": "Manchester United"},
                                                                "percent": {"home": "45%", "draw": "45%",
                                                                            "away": "10%"}}}]}, "pp-1", T0)
    view = center.provider_prediction(db, seed.fixture_id).data
    assert view is not None and len(view.history) == 1 and view.history[0].percent_home == Decimal("45.00")
    assert "not PrediGol's model" in view.label and "never a model input" in view.label


def test_a_line_up_carries_the_coachs_stored_photo(db: psycopg.Connection, seed: Seed) -> None:
    payload(db, seed, "co-1")
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, provider_coach_id, "
               "coach_name, payload_hash, fetched_at) VALUES (%s, 'home', 'api-football', '4-3-3', 2172, "
               "'J. González', %s, %s)", (seed.fixture_id, seed.payload_hash, T0))
    ref.apply_coachs(db, ref.Target("k", {}, timedelta(days=1), {}),
                     {"response": [{"id": 2172, "name": "J. González", "photo": "https://media/coachs/2172.png"}]},
                     "co-1", T0)
    mc = center.match_center(db, seed.fixture_id).data
    assert mc is not None and mc.lineups.data is not None
    home = next(lu for lu in mc.lineups.data if lu.side == "home")
    assert (home.coach_provider_id, home.coach_photo_url) == (2172, "https://media/coachs/2172.png")

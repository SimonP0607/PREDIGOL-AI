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


def test_the_match_audit_names_the_payloads_of_the_facts_extras_and_the_providers_prediction(
        db: psycopg.Connection, seed: Seed) -> None:
    from fbi.api.services.audit import match_audit
    from fbi.ingestion.fixture_facts import apply_fixture_facts
    from fbi.providers.api_football.details import iter_fixture_facts

    payload(db, seed, "au-f")
    payload(db, seed, "au-p")
    body = {"response": [{"fixture": {"id": 1001, "referee": "M. Oliver, England", "periods": {}},
                          "teams": {"home": {"id": 33, "winner": None}, "away": {"id": 40, "winner": None}}}]}
    assert apply_fixture_facts(db, iter_fixture_facts(body), payload_hash="au-f", observed_at=T0) == 1
    ref.apply_predictions(db, ref.Target("k", {}, timedelta(days=1), {"fixture_id": seed.fixture_id}),
                          {"response": [{"predictions": {"advice": "x"}}]}, "au-p", T0)
    audit = match_audit(db, seed.fixture_id).data
    assert audit is not None
    raw = next(s for s in audit.steps if s.key == "raw")
    roles = {i.ref: i.facts.get("roles") for i in raw.items}
    assert roles["au-f"] == "facts" and roles["au-p"] == "provider_prediction (auxiliary)"
    normalized = next(s for s in audit.steps if s.key == "normalized")
    assert any(i.kind == "facts" and "payload:au-f" in i.links for i in normalized.items)


def test_the_providers_season_less_group_row_is_not_shown_as_another_trophy(db: psycopg.Connection,
                                                                           seed: Seed) -> None:
    """A. Morata, 4 Oct 2026: 70 entries, 28 of them a null-season row after the dated ones of the same
    competition and place. Stored as sent; the page lists 42 trophies."""
    pid = a_player(db)
    payload(db, seed, "tg-1")
    t = ref.Target("k", {}, timedelta(days=7), {"kind": "player", "ids": [13491], "list_key": "trophies"})
    body = {"response": [{"league": "Copa del Rey", "country": "Spain", "season": "2013/2014", "place": "Winner"},
                         {"league": "Copa del Rey", "country": "Spain", "season": "2010/2011", "place": "Winner"},
                         {"league": "Copa del Rey", "country": "Spain", "season": None, "place": "Winner"},
                         {"league": "Copa del Rey", "country": "Spain", "season": None, "place": "2nd Place"},
                         {"league": "Trofeo X", "country": "World", "season": None, "place": "Winner"}]}
    assert ref.apply_trophies(db, t, body, "tg-1", T0) == 5, "every entry is stored as the provider sent it"
    detail = center.player(db, pid).data
    assert detail is not None and detail.trophies is not None
    shown = [(x.league, x.season, x.place) for x in detail.trophies.data]
    assert shown == [("Copa del Rey", "2013/2014", "Winner"), ("Copa del Rey", "2010/2011", "Winner"),
                     ("Copa del Rey", None, "2nd Place"), ("Trofeo X", None, "Winner")], \
        "the group row is hidden only where dated entries of the same competition and place exist"


def test_a_rating_of_0_is_not_a_rating_and_the_providers_season_average_says_it_counts_one(
        db: psycopg.Connection, seed: Seed) -> None:
    """Reinaldo, UEFA Champions League 2026: two qualifiers rated 0 (67 and 75 minutes) and three rated; the
    provider's season rating 3.98 is (0 + 0 + 7.3 + 6.3 + 6.3) / 5. The page shows no rating for a 0, averages
    real ratings only, and says how many unrated matches the provider's figure counts."""
    db.execute("UPDATE core.fixtures SET kickoff_at = now() - interval '3 days', status_group = 'finished' "
               "WHERE id = %s", (seed.fixture_id,))
    player = db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (9650, 'Reinaldo') RETURNING id"
                        ).fetchone()
    assert player is not None
    second = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at, status_group) VALUES (8101, %s, %s, %s, now() - interval '10 days', "
                        "'finished') RETURNING id", (seed.season_id, seed.away_team_id, seed.home_team_id)).fetchone()
    assert second is not None
    for fx, minutes, rating in ((seed.fixture_id, 83, "7.3"), (second[0], 67, "0")):
        db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                   "rating, payload_hash, fetched_at) VALUES (%s, 'api-football', 9650, 'home', %s, %s, %s, now())",
                   (fx, minutes, rating, seed.payload_hash))
    detail = center.player(db, int(player[0])).data
    assert detail is not None and detail.player.avg_rating == Decimal("7.30"), "the 0 is not averaged in"
    assert [m.rating for m in detail.matches.data] == [Decimal("7.30"), None]
    payload(db, seed, "rz-1")
    t = ref.Target("k", {"league": 39, "season": 2025}, timedelta(days=1), {"cs_id": seed.season_id,
                                                                             "list": "topscorers"})
    ref.apply_leaders(db, t, {"response": [
        {"player": {"id": 9650, "name": "Reinaldo"}, "statistics": [
            {"team": {"id": 33}, "league": {"id": 39, "season": 2025}, "games": {"appearences": 2, "rating": "3.65"},
             "goals": {"total": 3}}]},
        {"player": {"id": 44850, "name": "V. Slivka"}, "statistics": [
            {"team": {"id": 33}, "league": {"id": 39, "season": 2025}, "games": {"appearences": 6, "rating": "0"},
             "goals": {"total": 2}}]}]}, "rz-1", T0)
    data = center.competition_reference(db, seed.competition_id, season=2025).data
    assert data is not None
    rows = data.leaders.data[0].rows
    assert (rows[0].rating, rows[0].unrated_matches) == (Decimal("3.6500"), 1)
    assert (rows[1].rating, rows[1].unrated_matches) == (None, 0), "the provider's 0 is not shown as a rating"
    stored = db.execute("SELECT rating FROM core.season_leaders WHERE payload_hash = 'rz-1' ORDER BY ordinal"
                        ).fetchall()
    assert stored == [(Decimal("3.6500"),), (Decimal("0.0000"),)], "stored as sent"

"""The selection of the reference by competition (plan PM, PM-04-04; BE-063), against the database: off, every feed asks what it
asked; on, a competition's level in the matrix and its priority decide what its teams and people are asked for.

The seed is provider league 39 (P2 in ``config/coverage/prioridad_editorial.yaml``), teams 33 and 40. A second competition, league
239 (P0), shares team 33."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

import fbi.ingestion.people as people
import fbi.ingestion.reference as ref
from fbi.coverage import depth, levels
from tests.integration.conftest import Seed

AT = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
PEOPLE_FEEDS = ("transfers", "coachs", "trophies_players", "sidelined_players", "players_teams", "profiles_players",
                "coachs_by_id")


@pytest.fixture()
def tracked(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    depth.clear_cache()
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    db.execute("UPDATE core.fixtures SET status_group = 'finished', kickoff_at = %s WHERE id = %s",
               (AT - timedelta(days=3), seed.fixture_id))
    for side, player in (("home", 901), ("away", 902)):
        db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, minutes, "
                   "is_substitute, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, 'J. Ejemplo', 90, false, %s, %s) "
                   "ON CONFLICT DO NOTHING", (seed.fixture_id, player, side, seed.payload_hash, AT - timedelta(days=3)))
    yield db
    depth.clear_cache()


def _grade(db: psycopg.Connection, season_id: int, level: str) -> None:
    """The season graded so its summary is ``level`` (what the nightly pass writes, reduced to what the summary reads): every datum
    and market at ``level``, except for C, which is data B and markets C (a summary C needs base B or more)."""
    market_level = level
    if level == "C":
        level = "B"
    for d in levels.DATA:
        db.execute("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, level, "
                   "measured_level, rules_version, measured_at) VALUES (%s, 'todas', %s, 40, 40, %s, %s, %s, %s) "
                   "ON CONFLICT (competition_season_id, phase_key, datum) DO UPDATE SET level = EXCLUDED.level",
                   (season_id, d, level, level, levels.RULES_VERSION, AT))
    for m in levels.MARKETS:
        db.execute("INSERT INTO analytics.market_availability (competition_season_id, market_key, window_start, window_days, n_window, "
                   "n_priced, level, measured_level, rules_version, measured_at) VALUES (%s, %s, '2026-10-05', 47, 40, 40, %s, %s, %s, %s) "
                   "ON CONFLICT (competition_season_id, market_key) DO UPDATE SET level = EXCLUDED.level",
                   (season_id, m, market_level, market_level, levels.RULES_VERSION, AT))


def _selected(db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, switch: str) -> dict[str, set[str]]:
    monkeypatch.setenv(ref.DEPTH_SWITCH, switch)
    depth.clear_cache()
    view = ref.depth_view(db, AT, depth.current)
    feeds = {f.name: f for f in ref.FEEDS}
    return {name: {t.key for t in ref.due_targets(db, feeds[name], AT, view)} for name in PEOPLE_FEEDS}


def _counts(sel: dict[str, set[str]]) -> dict[str, int]:
    return {k: len(v) for k, v in sel.items()}


def test_the_map_reads_level_and_priority(tracked: psycopg.Connection, seed: Seed) -> None:
    db = tracked
    m = depth.build(db)
    assert m.priority[39] == "P2" and m.level[39] is None and m.by_league[39] == "minima", "P2 not measured yet: minima"
    _grade(db, seed.season_id, "C")
    m = depth.build(db)
    assert m.level[39] == "C" and m.by_league[39] == "media"
    _grade(db, seed.season_id, "B")
    assert depth.build(db).by_league[39] == "completa"
    m = depth.build(db, prio={})
    assert m.priority[39] is None and m.by_league[39] == "completa"


def test_off_selects_what_it_did(tracked: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    monkeypatch.delenv(ref.DEPTH_SWITCH, raising=False)
    feeds = {f.name: f for f in ref.FEEDS}
    before = {name: {t.key for t in ref.due_targets(db, feeds[name], AT)} for name in PEOPLE_FEEDS}
    assert _selected(db, monkeypatch, "off") == before
    assert before["transfers"] == {"team:33", "team:40"} and before["trophies_players"] == {"player:901", "player:902"}


def test_selection_by_depth_of_the_competition(tracked: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    full = _selected(db, monkeypatch, "off")
    minima = _selected(db, monkeypatch, "on")  # P2, not measured: squad and coach only
    assert minima["coachs"] == full["coachs"] == {"team:33", "team:40"}
    assert not minima["transfers"] and not minima["trophies_players"] and not minima["sidelined_players"]
    assert not minima["players_teams"]
    _grade(db, seed.season_id, "C")
    media = _selected(db, monkeypatch, "on")
    assert media["transfers"] == full["transfers"] and media["coachs"] == full["coachs"]
    assert not media["trophies_players"] and not media["sidelined_players"] and not media["players_teams"]
    _grade(db, seed.season_id, "A")
    assert _selected(db, monkeypatch, "on") == full


def test_a_team_in_a_p0_competition_keeps_everything(tracked: psycopg.Connection, seed: Seed,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Team 33 also plays a current season of league 239 (P0): it takes the deepest; team 40 stays minima."""
    db = tracked
    comp = db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                      "VALUES (239, 'Primera A', 'league', 'club', 'domestic_league', true) RETURNING id").fetchone()
    assert comp is not None
    season = db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                        "RETURNING id", (comp[0],)).fetchone()
    assert season is not None
    other = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1137, 'Millonarios') RETURNING id").fetchone()
    assert other is not None
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
               "status_group) VALUES (5001, %s, %s, %s, %s, 'scheduled')",
               (season[0], seed.home_team_id, other[0], AT + timedelta(days=2)))
    sel = _selected(db, monkeypatch, "on")
    assert sel["transfers"] == {"team:33", "team:1137"}, "40 plays only the P2 league not measured yet"


def test_player_seasons_with_the_depth(tracked: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """/players: league 39 is P2, so it is swept when it is not minima. The seed commits (a worker step): put back after."""
    db = tracked
    db.commit()
    monkeypatch.delenv(ref.TRIMS_SWITCH, raising=False)
    try:
        monkeypatch.setenv(ref.DEPTH_SWITCH, "on")
        depth.clear_cache()
        assert people.seed_player_seasons(db, at=AT, depths=depth.current) == 0, "P2 not measured yet: minima"
        monkeypatch.setenv(ref.DEPTH_SWITCH, "off")
        assert people.seed_player_seasons(db, at=AT, depths=depth.current) == 1, "off: as before"
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind = 'players_season'")
        _grade(db, seed.season_id, "C")
        db.commit()
        monkeypatch.setenv(ref.DEPTH_SWITCH, "on")
        depth.clear_cache()
        assert people.seed_player_seasons(db, at=AT, depths=depth.current) == 1, "P2 at level C: media, swept"
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind = 'players_season'")
        db.execute("DELETE FROM analytics.coverage_cells WHERE competition_season_id = %s", (seed.season_id,))
        db.execute("DELETE FROM analytics.market_availability WHERE competition_season_id = %s", (seed.season_id,))
        db.execute("DELETE FROM core.fixture_player_stats WHERE fixture_id = %s", (seed.fixture_id,))
        db.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
        db.execute("UPDATE core.competition_seasons SET is_current = false WHERE id = %s", (seed.season_id,))
        db.commit()


def test_a_d_team_spends_under_five_requests_on_its_first_fill(tracked: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance (field 17): a new D team of a batch, never asked. With the depth on, of the people feeds only the coach is asked
    for it (and the squad, in the backfill): 2 requests, against one a person on the others."""
    db = tracked
    on = _counts(_selected(db, monkeypatch, "on"))
    off = _counts(_selected(db, monkeypatch, "off"))
    teams = 2
    assert (sum(on.values()) + teams) / teams < 5
    assert sum(off.values()) > sum(on.values())

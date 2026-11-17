"""The estimated starters (IA-094, AD-D04) against the real schema, on the player engine's own scene (twelve played rounds of two teams):
the job estimates both sides of a tracked match at E1 and at E4 and keeps one row per player, a confirmed absence never starts, the
official sheet replaces the estimate once read, nothing is estimated twice, every figure says ``sin_calibrar``, the table refuses UPDATE
and DELETE, and nothing else of the database moves. The pass runs inside the test's transaction (``commit=False``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.players import lineup_estimate as le
from fbi.shadowjobs import lineup_estimate as job

from .conftest import Seed
from .test_players_cli import World

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    w = World(db, seed)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = (SELECT competition_id FROM core.competition_seasons WHERE id = %s)",
               (seed.season_id,))
    return w


def rows(db: psycopg.Connection[Any], fixture: int) -> list[dict[str, Any]]:
    cur = db.execute("SELECT * FROM intel.lineup_estimates WHERE fixture_id = %s ORDER BY evaluation, team_id, p_start DESC", (fixture,))
    names = [c.name for c in cur.description or ()]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_e1_keeps_both_sides_once_and_a_confirmed_absence_never_starts(world: World) -> None:
    db = world.db
    world.absence(world.home, 9, world.kickoff - timedelta(days=2))
    before = db.execute("SELECT count(*) FROM intel.decisions").fetchone()
    at = world.kickoff - timedelta(hours=13)
    rep = job.run_pass(db, now=at, code_version="test", commit=False)
    assert not rep.errors and rep.due == {"E1": 1} and rep.fixtures == 1 and rep.sides == 2, rep.as_json()
    kept = rows(db, world.target)
    assert len(kept) == rep.rows == 28 and {r["evaluation"] for r in kept} == {"E1"}
    assert {r["seal"] for r in kept} == {le.SIN_CALIBRAR} and {r["version"] for r in kept} == {le.VERSION}
    assert all(r["known_at"] == at and r["kickoff_at"] == world.kickoff and not r["lineup_confirmed"] for r in kept)
    striker = next(r for r in kept if r["provider_player_id"] == world.man(world.home, 9))
    assert (striker["basis"], float(striker["p_start"]), float(striker["p_play"]), striker["absence_status"], striker["absence_basis"]) == (
        le.BASE_CONFIRMED_OUT, 0.0, 0.0, "baja", "proveedor")
    keeper = next(r for r in kept if r["provider_player_id"] == world.man(world.home, 0))
    assert keeper["basis"] == le.BASE_MINUTES and float(keeper["p_start"]) > 0.8 and keeper["sample"] == 10
    assert sum(float(r["p_start"]) for r in kept if r["team_id"] == world.away) == pytest.approx(11, abs=2.5)
    again = job.run_pass(db, now=at + timedelta(minutes=30), commit=False)
    assert again.due == {} and len(rows(db, world.target)) == 28, "an evaluation is kept once"
    assert db.execute("SELECT count(*) FROM intel.decisions").fetchone() == before
    for sql in ("UPDATE intel.lineup_estimates SET p_start = 1", "DELETE FROM intel.lineup_estimates"):
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(sql)


def test_e4_reads_the_official_sheet_once_it_was_fetched(world: World) -> None:
    db = world.db
    fetched = world.kickoff - timedelta(minutes=40)
    world.lineup("home", world.home, fetched, starters=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12], bench=[10, 11])
    at = world.kickoff - timedelta(minutes=15)
    rep = job.run_pass(db, now=at, commit=False)
    assert not rep.errors and rep.due == {"E4": 1} and rep.confirmed_sides == 1, rep.as_json()
    home = {r["provider_player_id"]: r for r in rows(db, world.target) if r["team_id"] == world.home}
    assert set(home) == {world.man(world.home, j) for j in range(13)}
    assert home[world.man(world.home, 12)]["basis"] == "confirmed_starter" and float(home[world.man(world.home, 12)]["p_start"]) == 1.0
    assert home[world.man(world.home, 10)]["basis"] == "confirmed_bench" and float(home[world.man(world.home, 10)]["p_start"]) == 0.0
    away = [r for r in rows(db, world.target) if r["team_id"] == world.away]
    assert away and not any(r["lineup_confirmed"] for r in away)


def test_nothing_is_estimated_outside_the_windows_or_after_kick_off(world: World) -> None:
    db = world.db
    for at in (world.kickoff - timedelta(hours=30), world.kickoff - timedelta(hours=6), world.kickoff - timedelta(minutes=5)):
        assert job.run_pass(db, now=at, commit=False).due == {}
    assert rows(db, world.target) == []
    assert job.estimate_fixture(db, world.target, at=world.kickoff, typed=False) is None


def test_the_command_measures_the_estimate_against_the_official_sheets_read_only(world: World) -> None:
    from scripts import ia_players as cli

    from .test_players_cli import T0

    db = world.db
    writes = db.execute("SELECT COALESCE(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_xact_user_tables").fetchone()
    doc, code = cli.lineups(db, T0 + timedelta(days=42), T0 + timedelta(days=84))
    assert code == cli.OK and doc["version"] == le.VERSION and doc["matches"] == 6
    t = doc["total"]
    assert t["sides"] == 12 and t["starters"] == 132 and t["unseen_starters"] == 0 and 0 <= t["brier"] <= 0.05 and t["brier_baseline"] == 0, "the same XI every round: the baseline is exact"
    assert doc["competitions"]["min_sides"] == le.MIN_SIDES and doc["competitions"]["with_sample"] == 0, "12 sides: no verdict"
    assert db.execute("SELECT COALESCE(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_xact_user_tables").fetchone() == writes

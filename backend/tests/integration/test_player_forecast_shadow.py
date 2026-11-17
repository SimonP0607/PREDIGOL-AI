"""``player-engine-v2`` (IA-129, AD-B08) against the real schema, on the player engine's own scene (twelve played rounds of two teams):
the job forecasts every player market of both sides of a tracked match at E1 and keeps one row per player, family and line with the
start probability of ``lineup-estimate-v1``; a confirmed absence has probability 0; the official sheet makes the start 0 or 1 at E4;
nothing is forecast twice; the table refuses UPDATE and DELETE; and nothing else of the database moves. The pass runs inside the test's
transaction (``commit=False``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.players import v2
from fbi.shadowjobs import lineup_estimate as les
from fbi.shadowjobs import player_forecast as job

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
    cur = db.execute("SELECT * FROM intel.player_forecasts WHERE fixture_id = %s ORDER BY evaluation, team_id, provider_player_id, family, "
                     "line", (fixture,))
    names = [c.name for c in cur.description or ()]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_e1_keeps_every_market_of_every_estimated_man_once(world: World) -> None:
    db = world.db
    world.absence(world.home, 9, world.kickoff - timedelta(days=2))
    before = db.execute("SELECT count(*) FROM intel.decisions").fetchone()
    at = world.kickoff - timedelta(hours=13)
    rep = job.run_pass(db, now=at, code_version="test", commit=False)
    assert not rep.errors and rep.due == {"E1": 1} and rep.fixtures == 1, rep.as_json()
    kept = rows(db, world.target)
    assert kept and len(kept) == rep.rows and {r["evaluation"] for r in kept} == {"E1"}
    assert {r["version"] for r in kept} == {v2.VERSION} and {r["estimate_version"] for r in kept} == {"lineup-estimate-v1"}
    assert all(r["known_at"] == at and r["minutes_start"] is not None and r["nineties"] is not None for r in kept)
    estimated = les.estimate_fixture(db, world.target, at=at, typed=False)
    assert estimated is not None
    p_start = {e.provider_player_id: e.p_start for s in estimated["sides"].values() for e in s["estimates"]}
    assert all(float(r["p_start"]) == pytest.approx(round(p_start[r["provider_player_id"]], 4)) for r in kept), "AD-D04's start"
    striker = [r for r in kept if r["provider_player_id"] == world.man(world.home, 9)]
    assert striker and all(float(r["p_over"]) == 0 and r["p_over_if_plays"] is None for r in striker)
    again = job.run_pass(db, now=at + timedelta(minutes=30), commit=False)
    assert again.due == {} and len(rows(db, world.target)) == len(kept), "an evaluation is kept once"
    assert db.execute("SELECT count(*) FROM intel.decisions").fetchone() == before
    for sql in ("UPDATE intel.player_forecasts SET p_over = 1", "DELETE FROM intel.player_forecasts"):
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(sql)


def test_e4_with_the_official_sheet_the_start_is_zero_or_one(world: World) -> None:
    db = world.db
    world.lineup("home", world.home, world.kickoff - timedelta(minutes=40), starters=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12], bench=[10, 11])
    rep = job.run_pass(db, now=world.kickoff - timedelta(minutes=15), commit=False)
    assert not rep.errors and rep.due == {"E4": 1} and rep.confirmed_sides == 1, rep.as_json()
    home = [r for r in rows(db, world.target) if r["team_id"] == world.home]
    assert home and all(float(r["p_start"]) in (0.0, 1.0) and r["lineup_confirmed"] for r in home)
    assert {r["start_basis"] for r in home} <= {"confirmed_starter", "confirmed_bench"}

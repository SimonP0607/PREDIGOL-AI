"""The match page on a built competition season (plan F2): ``/matches/{id}/center`` carries the stage of the match and, for a leg of a
tie, the tie told from the side that hosts it - and only says who went through once the match is over."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from fbi.api.contracts.center import MatchCenter
from fbi.api.services import center
from fbi.competitions import builder
from tests.integration.conftest import Seed
from tests.integration.test_competition_builder import NOW, champions_league, make_world
from tests.integration.test_competition_context import built

pytestmark = pytest.mark.integration


def page(db: psycopg.Connection[Any], fixture_id: int) -> MatchCenter:
    body = center.match_center(db, fixture_id).data
    assert body is not None
    return body


def test_the_page_of_a_finished_second_leg_tells_the_tie_from_the_side_that_hosted_it(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    _w, f = built(db, seed, 99940)

    body = page(db, f["r2"])  # team 4 at home against team 1, 0-0 after a 1-0 first leg for team 1

    assert body.stage is not None
    assert (body.stage.name, body.stage.kind, body.stage.role, body.stage.round_key, body.stage.is_replay) == (
        "Round of 16", "knockout", "knockout", "round_of_16", False)
    tie = body.tie
    assert tie is not None
    assert (tie.format, tie.state, tie.leg, tie.legs, tie.played) == ("two_legged", "decided", 2, 2, 2)
    assert tie.aggregate_before is not None and (tie.aggregate_before.home, tie.aggregate_before.away) == (0, 1)
    assert tie.aggregate is not None and (tie.aggregate.home, tie.aggregate.away) == (0, 1)
    assert tie.outcome is not None and (tie.outcome.winner, tie.outcome.decided_by) == ("away", "aggregate")
    assert [(x.fixture_id, x.leg, x.is_this) for x in tie.legs_list] == [(f["r1"], 1, False), (f["r2"], 2, True)]
    assert (tie.legs_list[0].goals_home, tie.legs_list[0].goals_away) == (1, 0)


def test_the_page_of_the_first_leg_of_the_same_tie_is_told_from_its_own_home_side(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    _w, f = built(db, seed, 99941)

    tie = page(db, f["r1"]).tie

    assert tie is not None and (tie.leg, tie.aggregate_before) == (1, None)
    assert tie.aggregate is not None and (tie.aggregate.home, tie.aggregate.away) == (1, 0)
    assert tie.outcome is not None and tie.outcome.winner == "home"


def test_a_final_decided_on_penalties_says_so_with_the_shoot_out(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99942)

    body = page(db, f["fin"])

    assert body.stage is not None and (body.stage.round_key, body.stage.role) == ("final", "final")
    tie = body.tie
    assert tie is not None and (tie.format, tie.legs, tie.aggregate, tie.aggregate_before) == ("single", 1, None, None)
    assert tie.outcome is not None and (tie.outcome.winner, tie.outcome.decided_by) == ("home", "penalties")
    assert tie.outcome.shootout is not None and (tie.outcome.shootout.home, tie.outcome.shootout.away) == (4, 3)


def test_a_group_match_has_a_stage_and_no_tie(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99943)

    body = page(db, f["g1"])

    assert body.stage is not None and (body.stage.name, body.stage.role, body.stage.kind) == (
        "Group Stage", "group", "league")
    assert body.tie is None


def test_a_season_the_worker_has_not_built_has_neither(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99944)
    f = champions_league(w)

    body = page(db, f["r2"])

    assert body.stage is None and body.tie is None


def test_the_page_of_a_match_that_is_not_over_does_not_carry_what_the_tie_decided(db: psycopg.Connection[Any],
                                                                                  seed: Seed) -> None:
    """The match is put back after the tie was stored as decided (a stale row, until the worker's next pass): the page keeps what
    is known - the first leg - and nothing of the verdict."""
    w, f = built(db, seed, 99945)
    db.execute("DELETE FROM core.fixture_results WHERE fixture_id = %s", (f["r2"],))
    db.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s", (f["r2"],))
    stored = w.one("SELECT t.status FROM core.fixtures x JOIN core.ties t ON t.id = x.tie_id WHERE x.id = %s", f["r2"])
    assert stored == "decided", "the row the page must not trust"

    stale = page(db, f["r2"]).tie

    assert stale is not None and stale.outcome is None and stale.played == 1
    assert stale.aggregate_before is not None and (stale.aggregate_before.home, stale.aggregate_before.away) == (0, 1)

    builder.build_one(db, w.season, now=NOW)  # the worker's next pass (the quarter-finals still witness who went through)
    fresh = page(db, f["r2"]).tie

    assert fresh is not None and fresh.outcome is None, "a match not over: no verdict on its page, whatever the row says"
    assert fresh.aggregate_before == stale.aggregate_before


def test_the_stage_and_the_tie_go_out_in_the_json_the_web_reads(db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99946)

    out = center.match_center(db, f["r2"]).model_dump(mode="json")["data"]

    assert out["stage"]["name"] == "Round of 16" and out["stage"]["round_key"] == "round_of_16"
    assert out["tie"]["format"] == "two_legged" and out["tie"]["aggregate"] == {"home": 0, "away": 1}
    assert out["tie"]["outcome"] == {"winner": "away", "decided_by": "aggregate", "shootout": None, "contradicted": False}
    assert out["tie"]["legs_list"][1]["is_this"] is True
    assert set(out["tie"]) == {"format", "state", "leg", "legs", "played", "aggregate_before", "aggregate", "outcome",
                               "legs_list"}

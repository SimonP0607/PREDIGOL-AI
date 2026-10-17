"""REVIEW PREDIGOL P5 (B2 and the states regression): every way a match can end, through the production code.

For each, the provider (a fake /fixtures?ids= answering as API-Football does) says what happens to F1 of the
``test_daily_records`` world - a pick of the day on 1X2 Home at 2.30, kick-off at AT + 2 h - and the test checks
the three things a user sees: the match's phase in the day's set and in the started list, the pick's result and
its basis, and the item of the day. The special formats are the ones that broke before: extra time, penalties
straight after 90 minutes (a second leg), penalties after extra time; and the matches with no normal result:
postponed, cancelled, abandoned, awarded, walkover, suspended, interrupted. 1X2 and every 90-minute market
settle on the 90-minute score, never on extra time or a shoot-out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, NamedTuple

import psycopg
import pytest

from fbi.api.services.product import started_board
from fbi.api.services.records import daily_board
from fbi.ingestion.live_match import capture_live_matches
from fbi.picks.daily import build_daily_sets
from fbi.picks.fast_settlement import settle_fixtures

from .conftest import Seed
from .test_ai_decision_layer import Savepoints
from .test_daily_records import AT, World
from .test_e2e_match_cycle import KO, Provider, _body

Pair = tuple[int | None, int | None]


class Say(NamedTuple):
    """One answer of the provider: status, minute, goals and the score blocks API-Football sends."""

    short: str
    minute: int | None
    goals: Pair
    fulltime: Pair = (None, None)
    extratime: Pair = (None, None)
    penalty: Pair = (None, None)


class Case(NamedTuple):
    says: tuple[Say, ...]
    phase: str  # what the day's set and the started list show
    result: str  # picks.pick_results.result_status
    basis: str | None  # settlement_basis
    review: str | None  # the start of review_reason, for a pick that waits with a reason
    item: str  # the item of the day


CASES: dict[str, Case] = {
    "FT: full time": Case(
        (Say("1H", 12, (1, 0)), Say("FT", 90, (2, 0), fulltime=(2, 0))),
        "finished", "win", "regulation_90", None, "WIN"),
    "AET: 1-1 at 90 minutes, 2-1 after extra time - the 1X2 is a draw": Case(
        (Say("2H", 80, (1, 1)), Say("AET", 120, (2, 1), fulltime=(1, 1), extratime=(1, 0))),
        "finished", "loss", "regulation_90", None, "LOSS"),
    "PEN straight after 90 minutes (a second leg): won 1-0, out on penalties": Case(
        (Say("2H", 80, (1, 0)), Say("PEN", 90, (1, 0), fulltime=(1, 0), penalty=(4, 5))),
        "finished", "win", "regulation_90", None, "WIN"),
    "PEN after extra time: 0-0, the shoot-out does not count": Case(
        (Say("ET", 105, (0, 0)), Say("PEN", 120, (0, 0), fulltime=(0, 0), extratime=(0, 0), penalty=(5, 4))),
        "finished", "loss", "regulation_90", None, "LOSS"),
    "CANC: cancelled before kick-off": Case(
        (Say("CANC", None, (None, None)),),
        "cancelled", "void", "not_played", None, "VOID"),
    "PST: postponed": Case(
        (Say("PST", None, (None, None)),),
        "postponed", "pending", None, "postponed", "PENDING"),
    "ABD: abandoned at 60 minutes": Case(
        (Say("1H", 30, (1, 0)), Say("ABD", 60, (1, 0))),
        "abandoned", "pending", None, "abandoned", "PENDING"),
    "AWD: awarded 3-0 by the competition": Case(
        (Say("AWD", None, (3, 0)),),
        "not_played", "pending", None, "awarded", "PENDING"),
    "WO: walkover": Case(
        (Say("WO", None, (3, 0)),),
        "not_played", "pending", None, "walkover", "PENDING"),
    "SUSP: suspended at 55 minutes": Case(
        (Say("1H", 30, (0, 0)), Say("SUSP", 55, (0, 0))),
        "suspended", "pending", None, "suspended", "PENDING"),
}


def _answer(db: psycopg.Connection[Any], fixture: int, say: Say) -> dict[str, Any]:
    body = _body(db, fixture, short=say.short, minute=say.minute, home=0, away=0)
    entry = body["response"][0]
    entry["goals"] = {"home": say.goals[0], "away": say.goals[1]}
    entry["score"] = {"halftime": {"home": None, "away": None},
                      **{k: {"home": v[0], "away": v[1]} for k, v in
                         (("fulltime", say.fulltime), ("extratime", say.extratime), ("penalty", say.penalty))}}
    return body


def _world(db: psycopg.Connection[Any], seed: Seed) -> tuple[World, int, int]:
    w = World(db, seed)
    f1 = w.fixtures["F1"]
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id IN (SELECT cs.competition_id FROM "
               "core.competition_seasons cs JOIN core.fixtures f ON f.competition_season_id = cs.id WHERE f.id = %s)",
               (f1,))
    # As the pick pipeline creates every pick: with its pending result row, where a waiting reason is written.
    db.execute("INSERT INTO picks.pick_results (pick_id, result_status) VALUES (%s, 'pending') "
               "ON CONFLICT (pick_id) DO NOTHING", (w.picks["F1"],))
    w.review_all()
    build_daily_sets(db, at=AT)
    return w, f1, w.picks["F1"]


def _shown(db: psycopg.Connection[Any], f1: int, pick: int, at: Any) -> tuple[str, str, str]:
    day = daily_board(db, day=None, include_shadow=False, at=at).data
    assert day is not None and day.set is not None
    item = next(i for i in day.set.items if i.match.fixture_id == f1)
    started = started_board(db, include_shadow=False, at=at).data
    assert started is not None
    s = next(s for s in started if s.pick_id == pick)
    return item.match.phase, s.phase, item.status


@pytest.mark.parametrize("name", list(CASES))
async def test_every_way_a_match_ends(db: psycopg.Connection[Any], seed: Seed, name: str) -> None:
    case = CASES[name]
    _, f1, pick = _world(db, seed)
    provider = Provider([_answer(db, f1, say) for say in case.says])
    conn: Any = Savepoints(db)
    ended: list[int] = []
    for n, _say in enumerate(case.says):
        report = await capture_live_matches(conn, provider, at=KO + timedelta(minutes=12 + 100 * n))
        ended = report.ended
    assert ended == [f1], "the live follow hands every ending over to settlement at once"
    at = KO + timedelta(minutes=12 + 100 * len(case.says))
    settle_fixtures(db, ended, path="live_follow", at=at)

    row = db.execute("SELECT result_status, settlement_basis, review_reason FROM picks.pick_results "
                     "WHERE pick_id = %s", (pick,)).fetchone()
    assert row is not None
    result, basis, review = row
    assert (result, basis) == (case.result, case.basis)
    assert (review or "").startswith(case.review or ""), review
    if case.review is None:
        assert review is None
    phase, started_phase, item = _shown(db, f1, pick, at)
    assert (phase, started_phase, item) == (case.phase, case.phase, case.item)


async def test_an_interrupted_match_is_still_in_play_and_waits(db: psycopg.Connection[Any], seed: Seed) -> None:
    """INT is a pause, not an ending: nothing is settled and every screen keeps it in play."""
    _, f1, pick = _world(db, seed)
    provider = Provider([_answer(db, f1, Say("1H", 30, (0, 0))), _answer(db, f1, Say("INT", 40, (0, 0)))])
    conn: Any = Savepoints(db)
    await capture_live_matches(conn, provider, at=KO + timedelta(minutes=30))
    report = await capture_live_matches(conn, provider, at=KO + timedelta(minutes=45))
    assert report.ended == []
    assert _shown(db, f1, pick, KO + timedelta(minutes=46)) == ("live", "live", "PENDING")


async def test_a_match_with_no_official_result_72_hours_on_is_void(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Postponed and never played: the pick waits with its reason, then is void 72 h after kick-off (the
    longest delay books use), on the pipeline's own pass - never left "esperando resultado" for ever."""
    _, f1, pick = _world(db, seed)
    provider = Provider([_answer(db, f1, Say("PST", None, (None, None)))])
    report = await capture_live_matches(Savepoints(db), provider, at=KO + timedelta(minutes=12))
    settle_fixtures(db, report.ended, path="live_follow", at=KO + timedelta(minutes=13))
    assert db.execute("SELECT result_status FROM picks.pick_results WHERE pick_id = %s", (pick,)).fetchone() == (
        "pending",)
    settle_fixtures(db, [f1], path="pipeline", at=KO + timedelta(hours=72, minutes=5))
    assert db.execute("SELECT result_status, settlement_basis FROM picks.pick_results WHERE pick_id = %s",
                      (pick,)).fetchone() == ("void", "no_result_72h")

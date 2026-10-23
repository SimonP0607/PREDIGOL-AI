"""The weighted head-to-head (``fbi.intel.h2h``, plan F6) on a built world: which meetings are read, which are not, and what each
weighs for the match - at the moment asked, never later."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg

from .conftest import Seed
from .h2h_world import AT, KICKOFF, World


def test_the_meetings_read_are_the_finished_ones_known_at_the_moment_asked(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    ko = lambda days: AT - timedelta(days=days)  # noqa: E731
    league = w.fixture("league", 0, 1, ko(30), result=(2, 1))
    cup = w.fixture("cup", 1, 0, ko(200), "AET", result=(2, 1), extra=(1, 0))
    friendly = w.fixture("friendly", 0, 1, ko(400), neutral=True, result=(0, 3))
    w.fixture("league", 1, 0, ko(60), "AWD", result=(3, 0))  # awarded: not a played result
    w.fixture("league", 0, 1, ko(5), result=(1, 0), settled=AT + timedelta(hours=1))  # recorded after the moment asked
    w.fixture("league", 0, 1, KICKOFF + timedelta(days=30), result=(4, 4))  # played AFTER the match being described
    w.fixture("league", 0, 2, ko(20), result=(5, 0))  # another pair
    w.fixture("league", 0, 1, ko(15), "PST")  # postponed, no result row

    got = w.h2h()
    assert [r.meeting.fixture_id for r in got.rows] == [league, cup, friendly], "newest first, played, known at AT"
    assert got.n == 3
    later = w.h2h(at=AT + timedelta(hours=2))
    assert later.n == 4, "the result recorded at AT+1h is known at AT+2h"
    assert [r.meeting.fixture_id for r in later.rows][1:] == [league, cup, friendly]


def test_each_meeting_is_weighed_against_the_match(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    league = w.fixture("league", 0, 1, AT - timedelta(days=30), result=(2, 1))
    cup = w.fixture("cup", 1, 0, AT - timedelta(days=200), "AET", result=(2, 1), extra=(1, 0), pens=None)
    friendly = w.fixture("friendly", 0, 1, AT - timedelta(days=400), neutral=True, result=(0, 3))
    by = {r.meeting.fixture_id: r for r in w.h2h().rows}

    a = by[league]
    assert (a.scope, a.ground, a.home_side_was, a.result) == ("same_competition", "same", "home", "W")
    assert (a.goals_home_side, a.goals_away_side) == (2, 1)
    b = by[cup]
    assert (b.scope, b.ground, b.home_side_was) == ("other_official", "reversed", "away")
    assert b.meeting.extra_time is True and (b.meeting.goals_home, b.meeting.goals_away) == (2, 1)
    assert (b.meeting.reg_goals_home, b.meeting.reg_goals_away) == (1, 1), "decided in extra time: 1-1 at 90 minutes"
    assert (b.goals_home_side, b.goals_away_side, b.result) == (1, 1, "D")
    c = by[friendly]
    assert (c.scope, c.ground, c.home_side_was, c.result) == ("friendly", "neutral", "neutral", "L")
    assert c.w_scope == 0.25 and c.w_ground == 0.9
    assert a.weight > b.weight > c.weight


def test_a_penalty_shootout_is_a_draw_in_regulation_time_and_says_so(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid = w.fixture("cup", 0, 1, AT - timedelta(days=50), "PEN", result=(2, 2), extra=(0, 0), pens=(4, 3))
    got = w.h2h()
    (row,) = got.as_api()
    assert row["fixture_id"] == fid
    assert (row["regulation_goals_home"], row["regulation_goals_away"]) == (2, 2)
    assert (row["penalties_home"], row["penalties_away"]) == (4, 3) and row["after_extra_time"] is True
    assert got.record() == {"n": 1, "home_side_wins": 0, "draws": 1, "away_side_wins": 0}


def test_the_coach_on_each_bench_then_and_now_and_only_from_sheets_fetched_by_the_moment_asked(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    m1 = w.fixture("league", 0, 1, AT - timedelta(days=30), result=(2, 1))
    m2 = w.fixture("league", 1, 0, AT - timedelta(days=200), result=(1, 1))
    m3 = w.fixture("league", 0, 1, AT - timedelta(days=400), result=(0, 3))
    for fid, home, away in ((m1, (11, "A. Coach"), (22, "B. Coach")),
                            (m2, (99, "Old Boss"), (11, "Anibal Coach")),  # side 1 had another coach; side 0's, by id
                            ):
        w.bench(fid, "home", home[0], home[1], AT - timedelta(days=1000))
        w.bench(fid, "away", away[0], away[1], AT - timedelta(days=1000))
    # a sheet for the third meeting fetched only AFTER the moment asked: not read at AT
    w.bench(m3, "home", 11, "A. Coach", AT + timedelta(hours=1))
    w.bench(m3, "away", 22, "B. Coach", AT + timedelta(hours=1))
    # the benches NOW: the newest sheet of each side before the match is the first meeting's (same men)
    got = w.h2h()
    by = {r.meeting.fixture_id: r for r in got.rows}
    assert (by[m1].coach_changed_home, by[m1].coach_changed_away, by[m1].w_coach) == (False, False, 1.0)
    assert (by[m2].coach_changed_home, by[m2].coach_changed_away, by[m2].w_coach) == (False, True, 0.75)
    assert (by[m3].coach_changed_home, by[m3].coach_changed_away, by[m3].w_coach) == (None, None, 0.81)
    assert got.coaches() == {"both_same": 1, "some_changed": 1, "unknown": 1}
    late = w.h2h(at=AT + timedelta(hours=2))
    by = {r.meeting.fixture_id: r for r in late.rows}
    assert (by[m3].coach_changed_home, by[m3].coach_changed_away) == (False, False), "the sheet is known once it is fetched"


def test_the_coach_now_is_the_one_on_the_newest_sheet_within_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    old = w.fixture("league", 0, 1, AT - timedelta(days=500), result=(1, 0))  # older than the window of "now"
    newest = w.fixture("league", 0, 2, AT - timedelta(days=10), result=(0, 0))
    w.bench(old, "home", 11, "A. Coach", AT - timedelta(days=500))
    w.bench(old, "away", 22, "B. Coach", AT - timedelta(days=500))
    w.bench(newest, "home", 12, "New Man", AT - timedelta(days=10))  # side 0 changed coach since the meeting
    got = w.h2h()
    (r,) = got.rows
    assert r.meeting.fixture_id == old
    assert r.coach_changed_home is True, "the coach NOW (newest sheet) is not the one of the meeting"
    assert r.coach_changed_away is None, "side 1 has no sheet inside the window before the match: not guessed"
    assert got.situation.coach_home is not None and got.situation.coach_home.provider_id == 12
    assert got.situation.coach_away is None


def test_on_neutral_ground_there_is_no_home_to_mirror(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.fixture("league", 1, 0, AT - timedelta(days=30), result=(2, 1))
    got = w.h2h(neutral=True)
    assert got.rows[0].ground == "same" and got.rows[0].w_ground == 1.0
    assert got.same_venue() is None and got.as_packet()["same_venue"] is None


def test_no_meetings_is_an_empty_block_and_not_an_error(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    got = w.h2h()
    assert got.n == 0 and got.relevance == "nula"
    assert got.as_packet()["n"] == 0 and got.as_api() == []

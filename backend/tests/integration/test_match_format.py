"""RP-3.2 on the real schema: the format of a match as one fact, read before it is played, and how many tracked matches have it."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.competitions import builder
from fbi.competitions import match_format as mf
from tests.integration.conftest import Seed
from tests.integration.test_competition_builder import D0, NOW, champions_league, make_world

pytestmark = pytest.mark.integration


def at(day: int) -> Any:
    return D0 + timedelta(days=day)


def test_each_match_of_a_champions_league_says_what_it_is(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99911)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    got = {k: mf.read_one(db, v, at=at(300)) for k, v in f.items()}
    assert all(m is not None for m in got.values())
    formats = {k: m.format for k, m in got.items() if m is not None}
    assert formats["g1"] == formats["g2"] == mf.GROUP
    assert formats["q1"] == formats["q2"] == mf.KNOCKOUT_TWO_LEGGED
    assert formats["r1"] == formats["r2"] == mf.KNOCKOUT_TWO_LEGGED
    assert formats["k1"] == formats["k2"] == mf.KNOCKOUT_TWO_LEGGED
    assert formats["fin"] == mf.FINAL and got["fin"] is not None and got["fin"].legs == 1


def test_the_second_leg_carries_the_first_leg_as_recorded_at_the_cut_off(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99912)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    first = mf.read_one(db, f["r1"], at=at(100))
    assert first is not None and first.leg == 1 and first.first_leg is None, "the first leg has nothing before it"
    second = mf.read_one(db, f["r2"], at=at(106))
    assert second is not None and second.leg == 2 and second.legs == 2 and second.first_leg is not None
    # team 1 won the first leg 1-0 at home; seen from the second leg's home side (team 4) it is 0-1
    assert (second.first_leg["goals_home_side"], second.first_leg["goals_away_side"]) == (0, 1)
    # before the first leg's result was recorded the second leg cannot know it (no look-ahead)
    early = mf.read_one(db, f["r2"], at=at(100) + timedelta(hours=1))
    assert early is not None and early.first_leg is None


def test_a_cup_of_single_matches_and_a_league_are_told_apart(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99913)
    cup = [w.fixture("Round of 16", 1, 2, 10, (1, 0)), w.fixture("Round of 16", 3, 4, 10, (0, 2)),
           w.fixture("Round of 16", 5, 6, 10, (1, 1)), w.fixture("Round of 16", 7, 8, 10, (2, 2)),
           w.fixture("Quarter-finals", 1, 4, 20, (1, 0)), w.fixture("Quarter-finals", 6, 7, 20, (3, 1))]
    builder.build_one(db, w.season, now=NOW)
    got = mf.read_many(db, cup, at=at(60))
    assert [m.format for m in got] == [mf.KNOCKOUT_SINGLE] * len(cup)
    assert all(m.legs == 1 and m.first_leg is None for m in got)

    league = make_world(db, seed, 99914)
    games = [league.fixture(f"Regular Season - {n}", 1 + n % 4, 5 + n % 4, n, (1, 0)) for n in range(1, 5)]
    builder.build_one(db, league.season, now=NOW)
    assert {m.format for m in mf.read_many(db, games, at=at(60))} == {mf.LEAGUE}


def test_a_match_of_a_season_never_built_has_no_format_and_says_so(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99915)
    fid = w.fixture("Round of 16", 1, 2, 5, (1, 0))
    m = mf.read_one(db, fid, at=at(60))
    assert m is not None and m.format == mf.UNKNOWN and not m.known and m.stage is None


def test_the_neutral_ground_travels_with_the_format(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99916)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    db.execute("UPDATE core.fixtures SET is_neutral = true WHERE id = %s", (f["fin"],))
    fin = mf.read_one(db, f["fin"], at=at(300))
    r1 = mf.read_one(db, f["r1"], at=at(300))
    assert fin is not None and fin.neutral and r1 is not None and not r1.neutral


def test_the_coverage_counts_the_tracked_matches_of_the_last_days(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = make_world(db, seed, 99917)
    f = champions_league(w)
    builder.build_one(db, w.season, now=NOW)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (w.competition,))
    stray = w.fixture("Round of 32", 1, 8, 190, (2, 0))  # in the window and in a season built before it existed: no stage
    cov = mf.coverage(db, at=at(205), days=30)
    assert cov["matches"] == 2 and cov["known"] == 1 and cov["known_pct"] == 0.5
    assert cov["by_format"] == {mf.FINAL: 1, mf.UNKNOWN: 1} and cov["unknown_fixtures"] == [stray]
    assert f["fin"] not in cov["unknown_fixtures"]
    assert mf.coverage(db, at=at(900), days=30)["known_pct"] is None, "no matches in the window: no percentage invented"

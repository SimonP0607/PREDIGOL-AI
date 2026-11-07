"""«Últimos resultados» of Inicio's general layer (plan de Inicio, 3.1): the matches that ended in the last 24 hours, the most
recent first, six at most - read from the match feed's results or, the moment it says so, from the fixture feed's final, so a
match the live board dropped is never in neither block. Every test runs in a transaction that is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import home_board, product
from tests.integration.conftest import Seed
from tests.integration.neutral_world import World, add_fixture, make_world

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
TEAMS = ("Blues", "Reds", "Greens", "Yellows")


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    w = make_world(db)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = "
               "(SELECT competition_id FROM core.competition_seasons WHERE id = %s)", (w.league_season,))
    return w


def over(db: psycopg.Connection[Any], world: World, home: str, away: str, hours_ago: float,
         score: tuple[int, int] = (1, 0)) -> int:
    return add_fixture(db, world, world.league_season, home, away, NOW - timedelta(hours=hours_ago),
                       round_="Regular Season - 30", venue=None, score=score)



def shown(db: psycopg.Connection[Any]) -> list[int]:
    return [r.fixture_id for r in home_board.results(db, at=NOW)]


def test_the_last_24_hours_newest_first(db: psycopg.Connection[Any], world: World) -> None:
    old = over(db, world, "Blues", "Reds", 30)
    first = over(db, world, "Greens", "Yellows", 20)
    last = over(db, world, "Blues", "Greens", 3)
    middle = over(db, world, "Reds", "Yellows", 9)
    assert shown(db) == [last, middle, first]
    assert old not in shown(db)


def test_six_at_most_the_most_recent_six(db: psycopg.Connection[Any], world: World) -> None:
    made = [over(db, world, TEAMS[i % 4], TEAMS[(i + 1) % 4], 2 + i) for i in range(8)]
    assert shown(db) == made[:6]


def test_a_match_not_over_is_not_a_result(db: psycopg.Connection[Any], world: World) -> None:
    ahead = add_fixture(db, world, world.league_season, "Blues", "Reds", NOW + timedelta(hours=2),
                        round_="Regular Season - 30", venue=None, score=None)
    cancelled = add_fixture(db, world, world.league_season, "Greens", "Yellows", NOW - timedelta(hours=5),
                            round_="Regular Season - 30", venue=None, score=None)
    db.execute("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s", (cancelled,))
    abandoned = over(db, world, "Blues", "Greens", 4)
    db.execute("UPDATE core.fixtures SET status_short = 'ABD' WHERE id = %s", (abandoned,))
    assert shown(db) == []
    assert ahead not in shown(db)


def test_the_fixture_feeds_final_is_a_result_before_the_match_feed_has_it(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = add_fixture(db, world, world.league_season, "Blues", "Reds", NOW - timedelta(minutes=110),
                      round_="Regular Season - 30", venue=None, score=None)
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
               "goals_away, payload_hash) VALUES (%s, %s, 'FT', 90, 2, 1, %s)",
               (fid, NOW - timedelta(minutes=1), seed.payload_hash))
    [r] = home_board.results(db, at=NOW)
    assert (r.fixture_id, r.status, r.goals_home, r.goals_away) == (fid, "FT", 2, 1)


def test_a_match_still_in_play_for_the_fixture_feed_is_not_a_result(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = add_fixture(db, world, world.league_season, "Blues", "Reds", NOW - timedelta(minutes=70),
                      round_="Regular Season - 30", venue=None, score=None)
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
               "goals_away, payload_hash) VALUES (%s, %s, '2H', 70, 1, 0, %s)",
               (fid, NOW - timedelta(minutes=1), seed.payload_hash))
    assert shown(db) == []


def test_extra_time_and_a_shootout_say_how_it_ended(db: psycopg.Connection[Any], world: World) -> None:
    aet = over(db, world, "Blues", "Reds", 6, (2, 2))
    pen = over(db, world, "Greens", "Yellows", 4, (1, 1))
    db.execute("UPDATE core.fixtures SET status_short = 'AET' WHERE id = %s", (aet,))
    db.execute("UPDATE core.fixtures SET status_short = 'PEN' WHERE id = %s", (pen,))
    db.execute("UPDATE core.fixture_results SET pen_home = 4, pen_away = 3 WHERE fixture_id = %s", (pen,))
    by = {r.fixture_id: r for r in home_board.results(db, at=NOW)}
    assert by[aet].status == "AET" and by[aet].pens_home is None
    assert (by[pen].status, by[pen].pens_home, by[pen].pens_away) == ("PEN", 4, 3)


def test_a_competition_nobody_follows_has_no_results_here(db: psycopg.Connection[Any], world: World) -> None:
    over(db, world, "Blues", "Reds", 3)
    db.execute("UPDATE core.competitions SET is_tracked = false")
    assert shown(db) == []


def test_home_carries_the_results_and_says_when_there_are_none(db: psycopg.Connection[Any], world: World) -> None:
    empty = product.home(db, include_shadow=False, at=NOW).data
    assert empty is not None and empty.results.data == []
    assert empty.results.reason == "no_recent_results"
    fid = over(db, world, "Blues", "Reds", 3, (3, 1))
    full = product.home(db, include_shadow=False, at=NOW + timedelta(seconds=45)).data
    assert full is not None
    assert [(r.fixture_id, r.goals_home, r.goals_away) for r in full.results.data] == [(fid, 3, 1)]

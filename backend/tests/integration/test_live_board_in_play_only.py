"""The live board lists the matches being played, and only those (plan Inicio, step 1.1, UX-028).

Two real cases put a match that was not in play on the board: a match the fixture feed had already closed (FT) while
the odds feed still listed it for a few minutes, and a match the odds feed listed as "Not Started" before its kick-off.
Both read as "En vivo" on Inicio. The fixture feed's final word wins, and an odds-feed-only row needs a kick-off that
has already come. Every test runs in a transaction that is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import center
from tests.integration.conftest import Seed
from tests.integration.neutral_world import World, add_fixture, make_world

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    return make_world(db)


def fixture_at(db: psycopg.Connection[Any], world: World, home: str, away: str, kickoff: datetime) -> int:
    fid = add_fixture(db, world, world.league_season, home, away, kickoff, round_="Regular Season - 30",
                      venue=None, score=None)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = "
               "(SELECT competition_id FROM core.competition_seasons WHERE id = %s)", (world.league_season,))
    return fid


def feed_says(db: psycopg.Connection[Any], seed: Seed, fid: int, status: str, minute: int | None,
              goals: tuple[int, int], *, minutes_ago: float = 1) -> None:
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
               "goals_away, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (fid, NOW - timedelta(minutes=minutes_ago), status, minute, goals[0], goals[1], seed.payload_hash))


def odds_say(db: psycopg.Connection[Any], seed: Seed, fid: int, status_long: str, *, finished: bool = False,
             minute: int | None = None, minutes_ago: float = 1) -> None:
    at = NOW - timedelta(minutes=minutes_ago)
    db.execute("INSERT INTO market.live_fixture_current (fixture_id, first_seen_at, captured_at, elapsed_minute, "
               "score_home, score_away, status_long, is_finished, markets_offered, payload_hash) "
               "VALUES (%s, %s, %s, %s, 0, 0, %s, %s, 12, %s)",
               (fid, at - timedelta(minutes=5), at, minute, status_long, finished, seed.payload_hash))


def on_the_board(db: psycopg.Connection[Any]) -> set[int]:
    board = center.live_board(db, at=NOW).data
    return set() if board is None else {m.fixture_id for m in board.matches}


def test_a_match_in_play_for_both_feeds_is_on_the_board(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Blues", "Reds", NOW - timedelta(minutes=55))
    feed_says(db, seed, fid, "2H", 55, (1, 0))
    odds_say(db, seed, fid, "Second Half", minute=55)
    assert on_the_board(db) == {fid}


def test_a_match_the_fixture_feed_closed_is_off_the_board_though_the_odds_feed_still_lists_it(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Blues", "Reds", NOW - timedelta(minutes=110))
    feed_says(db, seed, fid, "FT", 90, (2, 1), minutes_ago=2)
    odds_say(db, seed, fid, "Second Half", finished=False, minute=90, minutes_ago=1)
    assert on_the_board(db) == set(), "the final whistle from the fixture feed wins over a lagging odds feed"


@pytest.mark.parametrize("status", ["AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"])
def test_no_closed_status_of_the_fixture_feed_keeps_a_match_on_the_board(
        db: psycopg.Connection[Any], world: World, seed: Seed, status: str) -> None:
    fid = fixture_at(db, world, "Greens", "Yellows", NOW - timedelta(minutes=125))
    feed_says(db, seed, fid, status, None, (0, 0), minutes_ago=2)
    odds_say(db, seed, fid, "Second Half", minute=80)
    assert on_the_board(db) == set()


def test_a_match_the_odds_feed_lists_as_not_started_is_off_the_board_before_its_kickoff(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Blues", "Greens", NOW + timedelta(minutes=45))
    odds_say(db, seed, fid, "Not Started")
    assert on_the_board(db) == set(), "an odds-feed-only row needs a kick-off that has come"


def test_a_match_only_the_odds_feed_sees_in_play_is_on_the_board_once_it_kicked_off(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Reds", "Yellows", NOW - timedelta(minutes=30))
    odds_say(db, seed, fid, "First Half", minute=30)
    assert on_the_board(db) == {fid}


def test_a_match_the_fixture_feed_still_calls_not_started_but_the_odds_feed_prices_in_play_is_on_the_board(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Reds", "Greens", NOW - timedelta(minutes=1))
    feed_says(db, seed, fid, "NS", None, (0, 0), minutes_ago=0.5)
    odds_say(db, seed, fid, "First Half", minute=1, minutes_ago=0.2)
    assert on_the_board(db) == {fid}


def test_a_match_the_odds_feed_marks_finished_is_off_the_board(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = fixture_at(db, world, "Blues", "Yellows", NOW - timedelta(minutes=100))
    odds_say(db, seed, fid, "Finished", finished=True, minute=90)
    assert on_the_board(db) == set()

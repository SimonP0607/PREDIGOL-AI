"""«Partidos relevantes» and «Qué se juega» of Inicio (plan de Inicio, 3.1b): which matches in play have a reason, which matches
of the next 36 hours have something at stake, and how ``/home`` splits what is in play between the two blocks and «En vivo».
Every test runs in a transaction that is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.api.contracts.product import HomeRelevant
from fbi.api.services import center, home_board, product
from tests.integration.conftest import Seed
from tests.integration.neutral_world import World, add_fixture, make_world

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    w = make_world(db)
    db.execute("UPDATE core.competitions SET is_tracked = true, tier = CASE WHEN id = (SELECT competition_id FROM "
               "core.competition_seasons WHERE id = %s) THEN 2 ELSE 1 END WHERE id IN (SELECT competition_id FROM "
               "core.competition_seasons WHERE id IN (%s, %s))", (w.league_season, w.league_season, w.cup_season))
    return w


def match(db: psycopg.Connection[Any], seed: Seed, world: World, home: str, away: str, *, minutes_in: int = 55,
          goals: tuple[int, int] = (0, 0), season: int | None = None) -> int:
    fid = add_fixture(db, world, season or world.league_season, home, away, NOW - timedelta(minutes=minutes_in),
                      round_="Regular Season - 30", venue=None, score=None)
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, goals_away, "
               "payload_hash) VALUES (%s, %s, '2H', %s, %s, %s, %s)",
               (fid, NOW - timedelta(minutes=1), minutes_in, goals[0], goals[1], seed.payload_hash))
    return fid


def earlier_score(db: psycopg.Connection[Any], seed: Seed, fid: int, goals: tuple[int, int], minutes_ago: float) -> None:
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, goals_away, "
               "payload_hash) VALUES (%s, %s, '1H', 20, %s, %s, %s)",
               (fid, NOW - timedelta(minutes=minutes_ago), goals[0], goals[1], seed.payload_hash))


def packet(db: psycopg.Connection[Any], fid: int, *, final: bool = False, first_leg: tuple[int, int] | None = None,
           home: str | None = None, away: str | None = None, home_name: str = "Blues", away_name: str = "Reds") -> None:
    ctx: dict[str, Any] = {}
    if final:
        ctx["final"] = True
    if first_leg is not None:
        ctx["second_leg"] = {"first_leg_score_home_side": first_leg[0], "first_leg_score_away_side": first_leg[1]}
    content = {"fixture": {"home": {"name": home_name}, "away": {"name": away_name}},
               "stakes": {"home": {"pressure": home} if home else {}, "away": {"pressure": away} if away else {}},
               "dossier": {"context": ctx}}
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
               (fid, NOW - timedelta(hours=1), NOW - timedelta(minutes=59), "a" * 64, Jsonb(content), []))


def relevant(db: psycopg.Connection[Any]) -> list[HomeRelevant]:
    board = center.live_board(db, at=NOW).data
    return [] if board is None else home_board.relevant(db, list(board.matches), at=NOW)


def ids(found: list[HomeRelevant]) -> list[int]:
    return [x.match.fixture_id for x in found]


def test_a_match_in_play_with_no_reason_is_not_relevant(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    quiet = match(db, seed, world, "Blues", "Reds")
    settled = match(db, seed, world, "Greens", "Yellows")
    packet(db, settled, home="settled", away="settled")
    assert relevant(db) == []
    assert quiet not in ids(relevant(db))


def test_a_live_final_and_a_tie_with_its_aggregate(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    final = match(db, seed, world, "Blues", "Reds", goals=(1, 0))
    packet(db, final, final=True)
    tie = match(db, seed, world, "Greens", "Yellows", goals=(1, 0))
    packet(db, tie, first_leg=(0, 2), home_name="Greens", away_name="Yellows")
    found = {x.match.fixture_id: x.reasons for x in relevant(db)}
    assert [r.code for r in found[final]] == ["final"]
    (reason,) = found[tie]
    assert reason.code == "tie"
    assert (reason.params["agg_home"], reason.params["agg_away"]) == (1, 2)


def test_a_fight_for_the_table_and_how_it_goes(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    fid = match(db, seed, world, "Blues", "Reds", goals=(0, 1))
    packet(db, fid, home="relegation")
    (found,) = relevant(db)
    (reason,) = found.reasons
    assert (reason.code, reason.params["team"], reason.params["pressure"], reason.params["state"]) == (
        "stakes", "Blues", "relegation", "behind")


def test_a_comeback_is_read_from_the_states_the_feed_gave(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    came_back = match(db, seed, world, "Blues", "Reds", goals=(1, 1))
    earlier_score(db, seed, came_back, (0, 1), 25)
    still_behind = match(db, seed, world, "Greens", "Yellows", goals=(0, 1))
    earlier_score(db, seed, still_behind, (0, 1), 25)
    never_behind = match(db, seed, world, "Blues", "Greens", goals=(0, 0))
    earlier_score(db, seed, never_behind, (0, 0), 25)
    found = {x.match.fixture_id: x.reasons for x in relevant(db)}
    assert set(found) == {came_back}
    (reason,) = found[came_back]
    assert (reason.code, reason.params["team"], reason.params["down_by"], reason.params["state"]) == (
        "comeback", "Blues", 1, "level")


def test_by_competition_priority_then_kickoff_and_four_at_most(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    league = [match(db, seed, world, "Blues", "Reds", minutes_in=80 - i * 5) for i in range(4)]
    for fid in league:
        packet(db, fid, final=True)
    cup = match(db, seed, world, "Greens", "Yellows", minutes_in=10, season=world.cup_season)
    packet(db, cup, final=True, home_name="Greens", away_name="Yellows")
    found = ids(relevant(db))
    assert found[0] == cup, "the better tier first, though it kicked off last"
    assert found[1:] == league[:3], "then by kick-off; four at most"
    assert len(found) == 4


def test_home_does_not_repeat_the_relevant_in_the_live_block(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    flagged = match(db, seed, world, "Blues", "Reds")
    packet(db, flagged, final=True)
    other = match(db, seed, world, "Greens", "Yellows")
    body = product.home(db, include_shadow=False, at=NOW).data
    assert body is not None
    assert [x.match.fixture_id for x in body.relevant.data] == [flagged]
    assert [m.fixture_id for m in body.live.data] == [other]


def test_home_with_nothing_relevant_says_so_and_keeps_live(db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    other = match(db, seed, world, "Greens", "Yellows")
    body = product.home(db, include_shadow=False, at=NOW).data
    assert body is not None
    assert body.relevant.status.value == "empty" and body.relevant.reason == "no_relevant_matches"
    assert [m.fixture_id for m in body.live.data] == [other]


# ── «Qué se juega» ──────────────────────────────────────────────────────────────────────────────────────────────────

def upcoming(db: psycopg.Connection[Any], world: World, home: str, away: str, hours: float, *, season: int | None = None) -> int:
    return add_fixture(db, world, season or world.league_season, home, away, NOW + timedelta(hours=hours),
                       round_="Regular Season - 30", venue=None, score=None)


def test_what_is_at_stake_in_the_next_36_hours(db: psycopg.Connection[Any], world: World) -> None:
    title = upcoming(db, world, "Blues", "Reds", 5)
    packet(db, title, home="title")
    quiet = upcoming(db, world, "Greens", "Yellows", 6)
    packet(db, quiet, home="settled", away="settled")
    nopacket = upcoming(db, world, "Blues", "Greens", 7)
    far = upcoming(db, world, "Reds", "Yellows", 40)
    packet(db, far, final=True)
    found = home_board.at_stake(db, at=NOW)
    assert [x.fixture_id for x in found] == [title]
    assert quiet not in [x.fixture_id for x in found] and nopacket not in [x.fixture_id for x in found]
    assert found[0].reason.code == "stakes" and found[0].reason.params == {"team": "Blues", "pressure": "title"}


def test_a_second_leg_to_play_carries_the_first_legs_result(db: psycopg.Connection[Any], world: World) -> None:
    fid = upcoming(db, world, "Greens", "Yellows", 3, season=world.cup_season)
    packet(db, fid, first_leg=(2, 2), home_name="Greens", away_name="Yellows")
    (found,) = home_board.at_stake(db, at=NOW)
    assert found.reason.code == "first_leg" and found.reason.params["first_home"] == 2


def test_at_stake_is_by_priority_and_four_at_most_and_not_for_matches_already_started(
        db: psycopg.Connection[Any], world: World, seed: Seed) -> None:
    league = [upcoming(db, world, "Blues", "Reds", 2 + i) for i in range(5)]
    for fid in league:
        packet(db, fid, final=True)
    cup = upcoming(db, world, "Greens", "Yellows", 20, season=world.cup_season)
    packet(db, cup, final=True, home_name="Greens", away_name="Yellows")
    started = match(db, seed, world, "Reds", "Greens")
    packet(db, started, final=True)
    found = [x.fixture_id for x in home_board.at_stake(db, at=NOW)]
    assert found == [cup, *league[:3]]
    assert started not in found

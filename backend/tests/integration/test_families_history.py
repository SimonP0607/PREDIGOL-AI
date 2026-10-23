"""Plan F10 - the door through which a family reads how finished matches ended: the right numbers, in the right competition, and nothing whose
result is not known yet."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import history
from fbi.families.fit import OUTCOME_KNOWN_AFTER

from .knowledge_world import KICKOFF
from .test_market_catalogue import w, world  # noqa: F401  (the hand-built world and its ids)

pytestmark = pytest.mark.integration

LATER = KICKOFF + timedelta(days=30)
EARLIER = KICKOFF - timedelta(days=1)


def flat(by_competition: dict[int, list[Any]]) -> list[Any]:
    return [m for ms in by_competition.values() for m in ms]


def test_the_columns_are_those_of_the_rule_that_grades_the_bet() -> None:
    assert history.columns_of("corners_ft") == ("corners_ft_home", "corners_ft_away")
    assert history.columns_of("goals_1h") == ("goals_1h_home", "goals_1h_away")
    for bad in ("not_a_measure", "goals_halves", "corners_1h"):
        with pytest.raises(history.UnknownMeasureError):
            history.columns_of(bad)


def test_the_goals_of_a_half_come_through_with_their_teams(db: psycopg.Connection[Any], world: dict[str, int]) -> None:  # noqa: F811
    got = {m.fixture_id: m for m in flat(history.load(db, "goals_1h", since=EARLIER, cutoff=LATER))}
    assert set(got) == {world["plain"], world["extra_time"], world["dismissals"], world["stats_only"]}, (
        "no break score (no_break) or an impossible one (bad_break) is not a half: they are not returned, and not returned as 0-0")
    plain = got[world["plain"]]
    assert (plain.home, plain.away) == (1, 0)
    home_id, away_id = db.execute("SELECT home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (world["plain"],)).fetchone() or (0, 0)
    assert (plain.home_id, plain.away_id) == (home_id, away_id) and plain.neutral is False
    second = {m.fixture_id: m for m in flat(history.load(db, "goals_2h", since=EARLIER, cutoff=LATER))}
    assert (second[world["plain"]].home, second[world["plain"]].away) == (1, 1)


def test_a_count_nobody_gave_is_not_returned_as_zero(db: psycopg.Connection[Any], world: dict[str, int]) -> None:  # noqa: F811
    corners = flat(history.load(db, "corners_ft", since=EARLIER, cutoff=LATER))
    assert {m.fixture_id for m in corners} == {world["plain"], world["dismissals"]}, (
        "extra time makes the statistics unknown and two matches have none: only two matches have corners")
    assert {(m.home, m.away) for m in corners} == {(7, 4), (5, 6)}


def test_a_match_whose_result_is_not_known_yet_does_not_come_through(db: psycopg.Connection[Any], world: dict[str, int]) -> None:  # noqa: F811
    just_before = KICKOFF + OUTCOME_KNOWN_AFTER - timedelta(minutes=1)
    assert history.load(db, "goals_ft", since=EARLIER, cutoff=just_before) == {}, "the first match kicked off less than six hours before"
    at_the_limit = KICKOFF + OUTCOME_KNOWN_AFTER
    assert {m.fixture_id for m in flat(history.load(db, "goals_ft", since=EARLIER, cutoff=at_the_limit))} == {world["plain"]}
    half_way = KICKOFF + OUTCOME_KNOWN_AFTER + timedelta(hours=2, minutes=30)
    assert {m.fixture_id for m in flat(history.load(db, "goals_ft", since=EARLIER, cutoff=half_way))} == {
        world["plain"], world["extra_time"], world["no_break"]}, "the matches that kicked off up to six hours before the cutoff, no more"


def test_the_start_of_the_window_is_respected(db: psycopg.Connection[Any], world: dict[str, int]) -> None:  # noqa: F811
    after_the_first_two = KICKOFF + timedelta(hours=1, minutes=30)
    got = {m.fixture_id for m in flat(history.load(db, "goals_ft", since=after_the_first_two, cutoff=LATER))}
    assert world["plain"] not in got and world["extra_time"] not in got and world["no_break"] in got

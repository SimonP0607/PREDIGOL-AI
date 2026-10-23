"""Plan F10 - the door through which a family reads how finished matches ended: the right numbers, in the right competition, and nothing whose
result is not known yet."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
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


def test_the_copy_statement_reads_exactly_what_the_door_reads(db: psycopg.Connection[Any], world: dict[str, int], tmp_path: Path) -> None:  # noqa: F811
    """The statement that brings a history out with ``psql`` (where Python is not at hand) is the same read as ``load``: same matches, same
    teams, same counts, same order, and the same wait for the result."""
    from scripts import families as cli

    for measure in ("goals_1h", "goals_2h", "goals_ft", "corners_ft", "cards_lines_ft"):
        for cutoff in (LATER, KICKOFF + OUTCOME_KNOWN_AFTER + timedelta(hours=2, minutes=30)):
            sql = history.export_statement(measure, since=EARLIER, cutoff=cutoff)
            with db.cursor() as cur, cur.copy(sql) as copy:
                data = b"".join(bytes(block) for block in copy)
            path = tmp_path / f"{measure}.csv"
            path.write_bytes(data)
            assert cli.read_csv(path) == history.load(db, measure, since=EARLIER, cutoff=cutoff), (measure, cutoff)
    assert history.load(db, "goals_1h", since=EARLIER, cutoff=LATER), "and the comparison is not between two empty histories"
    with pytest.raises(history.UnknownMeasureError):
        history.export_statement("corners_1h", since=EARLIER, cutoff=LATER)


def test_a_count_of_cards_comes_through_only_when_it_is_complete(db: psycopg.Connection[Any], w: Any, world: dict[str, int]) -> None:  # noqa: F811
    """Cards from events alone are incomplete where no statistics back them (23 Oct 2026: 3.7 a match against 5.1-5.9, and 83 % of the clubs'
    friendlies at zero), and asking for a red card to be REPORTED is a selection: the provider leaves it empty when there was none (the events
    show a red in 0.0 % of 15,427 matches whose statistics left both reds empty), so only the matches that had one would be kept. A family reads
    cards from the statistics - an empty red being none - or from events whose yellow cards agree with the statistics, team by team."""
    from .test_market_catalogue import _kind, _stats

    kick = KICKOFF + timedelta(days=2)
    events_only = w.match(kick, 0, 1, (1, 0), ht=(0, 0))  # events say one yellow; no team statistics at all
    _kind(w, events_only, 1, "yellow", "1H", "home")
    disagree = w.match(kick + timedelta(hours=1), 1, 2, (1, 0), ht=(0, 0))  # events say one yellow, the statistics say three
    _stats(w, disagree, {"yellow_cards": 2, "red_cards": 0}, {"yellow_cards": 1, "red_cards": 0})
    _kind(w, disagree, 1, "yellow", "1H", "home")
    swapped = w.match(kick + timedelta(hours=2), 2, 3, (1, 0), ht=(0, 0))  # the same total of yellows, but not team by team
    _stats(w, swapped, {"yellow_cards": 0, "red_cards": None}, {"yellow_cards": 1, "red_cards": None})
    _kind(w, swapped, 1, "yellow", "1H", "home")
    quiet = w.match(kick + timedelta(hours=3), 3, 0, (0, 0), ht=(0, 0))  # statistics only, the reds left empty: none
    _stats(w, quiet, {"yellow_cards": 2, "red_cards": None}, {"yellow_cards": 0, "red_cards": None})
    agree = w.match(kick + timedelta(hours=4), 0, 2, (0, 0), ht=(0, 0))  # events and statistics agree on the yellows; the reds are empty
    _stats(w, agree, {"yellow_cards": 1, "red_cards": None}, {"yellow_cards": 1, "red_cards": None})
    _kind(w, agree, 1, "yellow", "1H", "home")
    _kind(w, agree, 2, "yellow", "2H", "away")
    lines = {m.fixture_id: (m.home, m.away) for m in flat(history.load(db, "cards_lines_ft", since=EARLIER, cutoff=LATER))}
    assert set(lines) == {world["plain"], world["dismissals"], world["stats_only"], quiet, agree}, (
        "the events that agree with the statistics, and the statistics alone; not the events alone, not the events that disagree")
    assert lines[world["plain"]] == (2, 1) and lines[world["dismissals"]] == (2, 1), "from the events: yellows and reds are lines"
    assert lines[world["stats_only"]] == (3, 3), "from the statistics: yellow cards plus red cards (0 + 3, 1 + 2)"
    assert lines[quiet] == (2, 0) and lines[agree] == (1, 1), "a red left empty is none, not unknown"
    yellow = {m.fixture_id: (m.home, m.away) for m in flat(history.load(db, "yellow_ft", since=EARLIER, cutoff=LATER))}
    assert set(yellow) == set(lines) and yellow[world["stats_only"]] == (3, 2) and yellow[world["dismissals"]] == (1, 0)
    goals = {m.fixture_id for m in flat(history.load(db, "goals_ft", since=EARLIER, cutoff=LATER))}
    assert {events_only, disagree, swapped} <= goals, "the goals of those matches are fine: the rule is about cards"
    assert history.needs_corroboration("cards_lines_ft") and history.needs_corroboration("red_ft") and not history.needs_corroboration("corners_ft")
    assert "fixture_team_stats" in history.export_statement("cards_lines_ft", since=EARLIER, cutoff=LATER)
    assert "fixture_team_stats" not in history.export_statement("corners_ft", since=EARLIER, cutoff=LATER)


def test_the_referee_of_a_match_comes_through_when_asked_and_not_otherwise(db: psycopg.Connection[Any], w: Any, world: dict[str, int]) -> None:  # noqa: F811
    referee_id = db.execute("INSERT INTO core.referees (name, name_key, origin, version) VALUES ('A. Referee', 'a referee', 'rules', 'test') "
                            "RETURNING id").fetchall()[0][0]
    alias = db.execute("INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                       "VALUES (%s, 'a referee', 'germany', 'A. Referee', 'identity', 'rules', 'test') RETURNING id", (referee_id,)).fetchall()[0][0]
    for observed in (KICKOFF - timedelta(days=1), KICKOFF + timedelta(days=1)):  # seen before the match and again after it: one referee
        db.execute("INSERT INTO core.fixture_officials (fixture_id, role, observed_at, alias_id) VALUES (%s, 'referee', %s, %s)",
                   (world["plain"], observed, alias))
    plain = {m.fixture_id: m.referee_id for m in flat(history.load(db, "corners_ft", since=EARLIER, cutoff=LATER))}
    assert set(plain.values()) == {None}, "without asking, no referee is read"
    asked = {m.fixture_id: m.referee_id for m in flat(history.load(db, "corners_ft", since=EARLIER, cutoff=LATER, with_referee=True))}
    assert set(asked) == set(plain), "asking for the referee does not change which matches come through"
    assert asked[world["plain"]] == referee_id and asked[world["dismissals"]] is None, "the match he whistled, and one nobody recorded"
    assert "fr.referee_id AS referee_id" in history.export_statement("corners_ft", since=EARLIER, cutoff=LATER, with_referee=True)
    assert "referee_id" not in history.export_statement("corners_ft", since=EARLIER, cutoff=LATER)

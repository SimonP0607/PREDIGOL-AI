"""Rest and congestion as they really were (plan F4.4, definitions ``rest-v1``): the numbers a team's calendar gives for one match, and when
that calendar is whole for a match already played. Pure: the calendars here are built by hand, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.competitions.team_calendar import Match, TeamCalendar
from fbi.research.rest_features import VERSION, side_rest

KICKOFF = datetime(2032, 10, 5, 19, tzinfo=UTC)
AFTER = KICKOFF + timedelta(days=1)
_ids = iter(range(1, 10_000))


def game(days: float, *, followed: bool, status: str = "finished", competition: str | None = None, kind: str | None = None) -> Match:
    """A match ``days`` before KICKOFF (negative: after it)."""
    return Match(
        provider_fixture_id=next(_ids), kickoff_at=KICKOFF - timedelta(days=days), status_group=status, followed=followed, home=True,
        opponent="Rival FC", competition=competition or ("League" if followed else "Cup"), country="Spain",
        competition_type=kind or ("domestic_league" if followed else "domestic_cup"), season=2026, round=None,
        goals_for=1 if status == "finished" else None, goals_against=0 if status == "finished" else None)


def calendar(matches: list[Match], *, read: datetime | None = AFTER, at: datetime = AFTER) -> TeamCalendar:
    return TeamCalendar(team_id=1, at=at, matches=tuple(sorted(matches, key=lambda m: m.kickoff_at)), fetched_at=read)


def test_the_real_rest_counts_the_cup_tie_the_followed_competitions_do_not_know() -> None:
    side = side_rest(calendar([game(8, followed=True), game(2, followed=False)]), KICKOFF)
    assert side.rest_days == 2.0, "the cup tie two days ago is the last match"
    assert side.rest_days_tracked == 8.0, "what production counted: the last match of a competition it follows"
    assert side.rest_days_outside == 2.0
    assert side.whole and side.reason is None


def test_the_load_of_the_last_fortnight_and_how_much_of_it_the_followed_competitions_would_not_have_seen() -> None:
    cal = calendar([game(40, followed=True), game(20, followed=True), game(12, followed=True), game(9, followed=False),
                    game(6, followed=True), game(3, followed=False), game(1.5, followed=False, competition="Champions League",
                                                                         kind="continental")])
    side = side_rest(cal, KICKOFF)
    assert (side.played_7d, side.played_14d, side.played_30d) == (3, 5, 6)
    assert side.outside_14d == 3
    assert side.rest_days == 1.5 and side.rest_days_tracked == 6.0 and side.rest_days_outside == 1.5


def test_a_match_that_was_not_played_is_not_rest_and_one_after_the_kickoff_is_not_known() -> None:
    cal = calendar([game(9, followed=True), game(2, followed=False, status="postponed"), game(1, followed=False, status="cancelled"),
                    game(-1, followed=False)])
    side = side_rest(cal, KICKOFF)
    assert side.rest_days == 9.0 and side.rest_days_outside is None, "a postponed or cancelled match is no rest"
    assert side.played_14d == 1


def test_only_the_sixty_days_before_the_match_are_looked_at() -> None:
    side = side_rest(calendar([game(70, followed=True)]), KICKOFF)
    assert side.rest_days is None and side.reason == "no_previous_match" and not side.whole


def test_the_next_match_within_the_week_is_context_with_its_competition() -> None:
    cal = calendar([game(5, followed=True), game(-3, followed=False, status="scheduled", competition="Champions League",
                                                  kind="continental"), game(-20, followed=False, status="scheduled")])
    side = side_rest(cal, KICKOFF)
    assert side.next_gap_days == 3.0 and side.next_competition_type == "continental"
    assert side_rest(calendar([game(5, followed=True)]), KICKOFF).next_gap_days is None


def test_a_calendar_is_whole_for_a_played_match_only_if_the_list_was_read_after_it() -> None:
    cal = calendar([game(5, followed=True)], read=KICKOFF - timedelta(days=1), at=AFTER)
    side = side_rest(cal, KICKOFF)
    assert not side.whole and side.reason == "not_read_after_the_match"
    assert side_rest(calendar([game(5, followed=True)], read=None), KICKOFF).reason == "not_read_after_the_match", "never read"
    assert side_rest(calendar([game(5, followed=True)], read=KICKOFF), KICKOFF).whole, "read at the kick-off still shows how it ended"


def test_a_match_the_list_never_confirmed_makes_the_calendar_not_whole() -> None:
    doubt = game(4, followed=False, status="scheduled")
    side = side_rest(calendar([game(8, followed=True), doubt]), KICKOFF)
    assert not side.whole and side.reason == "unconfirmed_match"
    assert side.rest_days == 8.0, "a match nobody knows to have been played is not rest"
    followed_doubt = game(4, followed=True, status="scheduled")
    assert side_rest(calendar([game(8, followed=True), followed_doubt]), KICKOFF).whole, (
        "a followed match is kept up to date by the live pipeline: the list is not asked about it")


def test_the_definitions_have_a_version() -> None:
    assert VERSION == "rest-v1"

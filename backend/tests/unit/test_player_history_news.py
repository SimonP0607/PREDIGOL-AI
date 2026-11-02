"""What the audit of the streaks counts as "news" and what it does not (plan F3, after the first full build in production).

The audit that follows a sweep asks what a pass over everyone would still write, and that must be nothing. In a database that is being
written to it is not: the first audit in production, ninety minutes after the build, found 46 players whose stored streak differed from
the one the facts give now by exactly one match more and a last day of evidence of that very night. That is not a defect of the pass - the
match was played, or the squad list read, while the sweep was running - and the next pass folds it in. ``is_news`` is the narrow rule
that tells that case from everything else: the same streaks, the same everything, only ``matches`` and ``last_evidence`` moved forward,
and the new day of evidence is today or yesterday."""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial

from fbi.people import player_history as ph

TODAY = date(2026, 10, 23)
YESTERDAY = TODAY - timedelta(days=1)
LAST = date(2026, 10, 20)


def row(*, ordinal: int = 0, club: int = 70_001, name: str | None = "Alpha FC", valid_from: date | None = date(2026, 1, 1),
        valid_to: date | None = None, source: str = "lineup", matches: int = 3, last_evidence: date = LAST, via: str | None = None,
        version: str = "spells-v1", player: int = 8_000_001) -> ph.SpellRow:
    """A stored streak (by default: three matches for Alpha FC since January, the last of them on the 20th, still there)."""
    return (player, ordinal, club, name, valid_from, valid_to, source, matches, last_evidence, via, version)


def test_a_match_played_today_or_yesterday_is_news() -> None:
    stored = [row()]
    assert ph.is_news(stored, [row(matches=4, last_evidence=TODAY)], today=TODAY)
    assert ph.is_news(stored, [row(matches=4, last_evidence=YESTERDAY)], today=TODAY)


def test_a_squad_list_read_again_is_news_too() -> None:
    """Only the last day of evidence moves: the squad list that carried him was read again."""
    assert ph.is_news([row(source="squad", matches=0)], [row(source="squad", matches=0, last_evidence=TODAY)], today=TODAY)


def test_an_old_day_of_evidence_is_not_news() -> None:
    """A match that arrived late (the statistics of an old match, a backfill) is what the sweep is there to catch: not news."""
    assert not ph.is_news([row()], [row(matches=4, last_evidence=TODAY - timedelta(days=2))], today=TODAY)
    assert not ph.is_news([row()], [row(matches=4)], today=TODAY), "one match more and the same last day: it was played before"
    assert not ph.is_news([row()], [row(last_evidence=LAST + timedelta(days=1))], today=TODAY), "a day of evidence that is not recent"


def test_nothing_that_goes_back_is_news() -> None:
    assert not ph.is_news([row()], [row(matches=2, last_evidence=TODAY)], today=TODAY), "fewer matches than stored"
    assert not ph.is_news([row(last_evidence=TODAY)], [row(matches=4, last_evidence=YESTERDAY)], today=TODAY), "an earlier last day"


def test_a_different_streak_is_not_news_whatever_the_day() -> None:
    fresh = partial(row, matches=4, last_evidence=TODAY)
    different = [fresh(ordinal=1), fresh(club=70_002), fresh(name="Beta FC"), fresh(name=None), fresh(valid_from=date(2026, 2, 1)),
                 fresh(valid_from=None), fresh(valid_to=YESTERDAY), fresh(source="squad"), fresh(via="Beta FC"),
                 fresh(version="spells-v2"), fresh(player=8_000_002)]
    for other in different:
        assert not ph.is_news([row()], [other], today=TODAY), other


def test_streaks_that_come_or_go_are_not_news() -> None:
    moved = [row(valid_to=YESTERDAY), row(ordinal=1, club=70_002, valid_from=YESTERDAY, matches=1, last_evidence=TODAY)]
    assert not ph.is_news([row()], moved, today=TODAY), "he joined another club"
    assert not ph.is_news(moved, [row()], today=TODAY)
    assert not ph.is_news([], [row(matches=1, last_evidence=TODAY)], today=TODAY), "a man the table does not have yet"
    assert not ph.is_news([row()], [], today=TODAY)
    news = row(matches=4, last_evidence=TODAY)
    extra = row(ordinal=1, club=70_002, valid_from=YESTERDAY, matches=1, last_evidence=TODAY)
    assert not ph.is_news([row()], [news, extra], today=TODAY), "news on the streak he had, and a streak that is new beside it"
    assert not ph.is_news([row(), extra], [news], today=TODAY), "news on the streak he has, and a streak that is gone"


def test_equal_streaks_are_nothing_at_all() -> None:
    assert not ph.is_news([row()], [row()], today=TODAY)
    assert not ph.is_news([], [], today=TODAY)


def test_every_streak_of_the_man_has_to_be_news_or_as_stored() -> None:
    older = row(valid_to=date(2026, 9, 1), matches=7, last_evidence=date(2026, 8, 30))
    open_now = row(ordinal=1, club=70_002, valid_from=date(2026, 9, 1), matches=2, last_evidence=LAST)
    news = row(ordinal=1, club=70_002, valid_from=date(2026, 9, 1), matches=3, last_evidence=TODAY)
    assert ph.is_news([older, open_now], [older, news], today=TODAY), "the first streak is as stored, the second has the news"
    other = row(valid_to=date(2026, 9, 1), matches=7, last_evidence=date(2026, 8, 30), name="Other FC")
    assert not ph.is_news([older, open_now], [other, news], today=TODAY), "one streak of another kind spoils it"
    late = row(valid_to=date(2026, 9, 1), matches=8, last_evidence=date(2026, 8, 30))
    assert not ph.is_news([older, open_now], [late, news], today=TODAY), "a late match in the old streak is not news, even beside news"

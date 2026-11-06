"""«Para ti», the reader's layer of Home (closing plan 3.2) - the rules that need no database.

A player's state for the next match of his team is told from the data and nothing else: the published line-up is the newest word
(he is in it - a starter or on the bench), then the provider's current report (missing, or questionable), then out of a line-up that
is out, then «waiting». Which of the day's published picks are the reader's is told by a team or a league they follow or a market
they follow - and only that. The database half is ``tests/integration/test_customer_favorites.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from fbi.api.contracts.me_today import PlayerState
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.records import DailyBoard, DailyItem, DailySet, MatchRef
from fbi.api.envelope import ok
from fbi.api.services import me_today, records
from fbi.api.services.follows import Follows
from fbi.api.services.me_today import Report

MISSING = Report("Missing Fixture", "Knee Injury")
DOUBT = Report("Questionable", "Muscle Injury")


@pytest.mark.parametrize(("published", "listed", "starter", "report", "expected"), [
    (True, True, True, None, "starter"),
    (True, True, False, None, "bench"),
    (True, True, True, MISSING, "starter"),   # the line-up is newer than any report: a player named in it plays
    (True, False, False, None, "left_out"),
    (True, False, False, MISSING, "absent"),
    (True, False, False, DOUBT, "doubtful"),
    (False, False, False, MISSING, "absent"),
    (False, False, False, DOUBT, "doubtful"),
    (False, False, False, None, "waiting"),
    (False, True, True, None, "waiting"),     # a player of a line-up that is not published for his side is not «in» it
])
def test_the_state_of_a_player_is_told_from_the_lineup_then_the_report(
        published: bool, listed: bool, starter: bool, report: Report | None, expected: PlayerState) -> None:
    assert me_today.state_of(published=published, listed=listed, starter=starter, report=report) == expected


@pytest.mark.parametrize(("kind", "expected"), [
    ("Questionable", True), ("questionable", True), ("Doubtful", True),
    ("Missing Fixture", False), (None, False), ("", False), ("Inactive", False),
])
def test_a_questionable_report_is_a_doubt_and_anything_else_an_absence(kind: str | None, expected: bool) -> None:
    assert me_today.doubtful(Report(kind, None)) is expected


def match(fixture: int, home: tuple[int, str], away: tuple[int, str], league: tuple[int, str]) -> MatchRef:
    return MatchRef(
        fixture_id=fixture, kickoff_at=datetime(2026, 11, 5, 20, tzinfo=UTC), status_group="scheduled",
        competition=CompetitionBadge(id=league[0], name=league[1], country=None, logo_url=None, flag_url=None),
        home=TeamBadge(id=home[0], name=home[1], logo_url=None), away=TeamBadge(id=away[0], name=away[1], logo_url=None))


def item(rank: int, market: str, m: MatchRef) -> Any:
    return DailyItem.model_construct(rank=rank, match=m, market_key=market)


def board(*items: Any) -> Any:
    return ok(DailyBoard.model_construct(day=date(2026, 11, 5), set=DailySet.model_construct(items=list(items))))


def related_with(monkeypatch: pytest.MonkeyPatch, answer: Any, follows: Follows, markets: tuple[str, ...] = ()) -> Any:
    monkeypatch.setattr(records, "daily_board", lambda *a, **k: answer)
    return me_today.related(object(), follows, markets)  # type: ignore[arg-type]


A, B, C, D = (1, "Atlético Nacional"), (2, "Millonarios"), (3, "Junior"), (4, "Medellín")
UNO, DOS = (10, "Liga Uno"), (11, "Copa Dos")


def test_a_pick_is_the_readers_when_a_team_a_league_or_a_market_they_follow_is_in_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    day = board(item(1, "1X2", match(100, A, B, UNO)), item(2, "OU", match(101, C, D, DOS)),
                item(3, "BTTS", match(102, C, B, DOS)))
    got = related_with(monkeypatch, day, Follows(leagues=(), teams=(A[0],), suggested=False))
    assert [(p.rank, p.followed.model_dump() if p.followed else None, p.market_followed) for p in got.items] == [
        (1, {"kind": "team", "names": ["Atlético Nacional"]}, False)], "a followed team"
    assert got.published == 3 and got.day == date(2026, 11, 5)

    got = related_with(monkeypatch, day, Follows(leagues=(DOS[0],), teams=(), suggested=False))
    assert [(p.rank, p.followed.model_dump() if p.followed else None) for p in got.items] == [
        (2, {"kind": "league", "names": ["Copa Dos"]}), (3, {"kind": "league", "names": ["Copa Dos"]})], "a followed league"

    got = related_with(monkeypatch, day, Follows(leagues=(), teams=(), suggested=False), markets=("OU",))
    assert [(p.rank, p.followed, p.market_followed) for p in got.items] == [(2, None, True)], "a followed market alone"

    got = related_with(monkeypatch, day, Follows(leagues=(UNO[0],), teams=(C[0],), suggested=False), markets=("OU",))
    assert [p.rank for p in got.items] == [1, 2, 3], "the set's own order, each once"
    assert [p.market_followed for p in got.items] == [False, True, False]


def test_a_reader_whose_favourites_are_in_none_of_the_days_picks_gets_none_and_a_day_without_picks_says_so(
        monkeypatch: pytest.MonkeyPatch) -> None:
    day = board(item(1, "1X2", match(100, A, B, UNO)))
    got = related_with(monkeypatch, day, Follows(leagues=(DOS[0],), teams=(D[0],), suggested=False), markets=("AH",))
    assert (got.published, got.items) == (1, []), "none of today's picks is theirs - and it says how many there were"

    empty = ok(DailyBoard.model_construct(day=date(2026, 11, 5), set=None))
    got = related_with(monkeypatch, empty, Follows(leagues=(UNO[0],), teams=(), suggested=False))
    assert (got.published, got.items) == (0, []), "a day without a published set: nothing is theirs, whatever they follow"

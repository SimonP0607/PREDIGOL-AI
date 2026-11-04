"""The rules of what a reader's own use orders and suggests (plan UX, B2; section 38): visible, small, never a model.

* Markets: a market moves first once consulted MIN_VIEWS times, most first, the latest on a tie, the usual order last; one
  look is not a habit; nothing but the five markets of the match centre.
* Suggestions: only the matches the reader opened outside what they follow count; three different matches on two days;
  a team before its league on a tie; never one dismissed, never a team that cannot be followed, never past the limits.
* The rule of why a match is the reader's - shared by Home's matches and its news.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import get_args

from fbi.api.contracts import personal as contract
from fbi.api.routers import product as product_router
from fbi.api.services.follows import Follows, follow_reason
from fbi.customer import personal
from fbi.customer.favorites import Chosen
from fbi.customer.personal import Opened

T0 = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
D1, D2, D3 = date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 21)
SERIE, MIA, OTRA = 30, 31, 32
INTER, MILAN, JUVE, NACIONAL, MILLOS = 300, 301, 302, 310, 311


def opened(fixture: int, day: date, league: int = SERIE, home: int = INTER, away: int = MILAN) -> Opened:
    names = {SERIE: "Serie A", MIA: "Liga Mía", OTRA: "Liga Otra", INTER: "Inter", MILAN: "Milan", JUVE: "Juventus",
             NACIONAL: "Atlético Nacional", MILLOS: "Millonarios"}
    return Opened(fixture_id=fixture, day=day, competition_id=league, competition=names[league], home_id=home,
                  home=names[home], away_id=away, away=names[away])


NONE_FOLLOWED = Chosen(leagues=(MIA,), teams=(NACIONAL,))
FOLLOWABLE = (INTER, MILAN, JUVE, NACIONAL, MILLOS)
ROOM = (True, True)


def test_the_markets_are_the_match_centres_five_in_the_usual_order() -> None:
    assert personal.MARKETS == get_args(contract.MarketKey) == get_args(product_router.MarketKey)


def test_a_market_moves_first_once_consulted_twice_most_first_then_the_latest_then_the_usual_order() -> None:
    assert personal.order_markets({}) == ()
    assert personal.order_markets({"OU": (1, T0)}) == (), "one look is not a habit"
    assert personal.order_markets({"OU": (2, T0)}) == ("OU",)
    views = {"OU": (5, T0), "BTTS": (3, T0), "DC": (3, T0 + timedelta(hours=1)), "1X2": (1, T0)}
    assert personal.order_markets(views) == ("OU", "DC", "BTTS"), "most first; on a tie the latest consulted"
    tie = {"AH": (2, T0), "1X2": (2, T0)}
    assert personal.order_markets(tie) == ("1X2", "AH"), "the same times and moment: the usual order"
    assert personal.order_markets({"XX": (9, T0), "BTTS": (2, T0)}) == ("BTTS",), "only the match centre's markets"


def test_the_marks_of_the_usual_order_and_the_dismissed_suggestions() -> None:
    assert personal.marks([]) == (False, ())
    common, dismissed = personal.marks(["picks", "order:markets", "suggest:league:30", "match", "suggest:team:300"])
    assert common is True and dismissed == ("suggest:league:30", "suggest:team:300")
    assert personal.key_of("league", 30) == "suggest:league:30"


def test_a_league_opened_three_times_on_two_days_outside_what_the_reader_follows_is_suggested() -> None:
    seen = [opened(1, D1, home=INTER, away=MILAN), opened(2, D1, home=JUVE, away=INTER), opened(3, D2, home=MILAN,
                                                                                               away=JUVE)]
    found = personal.suggest(seen, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM)
    assert found == personal.Suggestion(kind="league", ref_id=SERIE, name="Serie A", matches=3, days=2), (
        "three different teams: the league, not one of them")


def test_too_few_matches_or_days_suggest_nothing_and_a_match_opened_twice_counts_once() -> None:
    one_day = [opened(1, D1), opened(2, D1, home=JUVE), opened(3, D1, home=MILAN, away=JUVE)]
    assert personal.suggest(one_day, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM) is None, (
        "three matches in one sitting is not a habit")
    twice = [opened(1, D1), opened(1, D2), opened(2, D2, home=JUVE)]
    assert personal.suggest(twice, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM) is None, (
        "the same match opened again is one match")


def test_the_matches_already_among_the_readers_own_never_count() -> None:
    mine = [opened(1, D1, league=MIA, home=INTER, away=MILAN), opened(2, D2, league=MIA, home=INTER, away=JUVE),
            opened(3, D3, league=MIA, home=MILAN, away=INTER)]
    assert personal.suggest(mine, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM) is None, (
        "in a league they follow: already in their views")
    nacional = [opened(i, day, league=OTRA, home=NACIONAL, away=MILLOS) for i, day in ((1, D1), (2, D2), (3, D3))]
    assert personal.suggest(nacional, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM) is None, (
        "a team they follow plays them: already in their views")


def test_a_team_before_its_league_on_a_tie_and_the_one_with_more_matches_first() -> None:
    inter = [opened(1, D1, home=INTER, away=MILAN), opened(2, D2, home=JUVE, away=INTER), opened(3, D3, home=INTER,
                                                                                               away=JUVE)]
    found = personal.suggest(inter, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM)
    assert found is not None and (found.kind, found.ref_id, found.name, found.matches) == ("team", INTER, "Inter", 3)
    more = [*inter, opened(4, D3, home=MILAN, away=JUVE)]
    found = personal.suggest(more, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=ROOM)
    assert found is not None and (found.kind, found.ref_id, found.matches) == ("league", SERIE, 4), "more matches first"


def test_never_one_dismissed_never_a_team_that_cannot_be_followed_never_past_the_limits() -> None:
    inter = [opened(1, D1, home=INTER, away=MILAN), opened(2, D2, home=JUVE, away=INTER), opened(3, D3, home=INTER,
                                                                                               away=JUVE)]
    found = personal.suggest(inter, NONE_FOLLOWED, dismissed=("suggest:team:300",), followable=FOLLOWABLE, room=ROOM)
    assert found is not None and (found.kind, found.ref_id) == ("league", SERIE), "the team dismissed: its league"
    assert personal.suggest(inter, NONE_FOLLOWED, dismissed=("suggest:team:300", "suggest:league:30"),
                            followable=FOLLOWABLE, room=ROOM) is None
    found = personal.suggest(inter, NONE_FOLLOWED, dismissed=(), followable=(MILAN, JUVE), room=ROOM)
    assert found is not None and found.kind == "league", "Inter cannot be followed: never suggested"
    assert personal.suggest(inter, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=(False, False)) is None
    found = personal.suggest(inter, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=(True, False))
    assert found is not None and found.kind == "league", "at the limit of teams: only a league"
    found = personal.suggest(inter, NONE_FOLLOWED, dismissed=(), followable=FOLLOWABLE, room=(False, True))
    assert found is not None and found.kind == "team", "at the limit of leagues: only a team"


def test_why_a_match_is_the_readers_names_the_team_first_both_home_first_then_the_league() -> None:
    follows = Follows(leagues=(SERIE,), teams=(MILAN, INTER), suggested=False)
    both = follow_reason((INTER, "Inter"), (MILAN, "Milan"), (SERIE, "Serie A"), follows)
    assert both is not None and (both.kind, both.names) == ("team", ["Inter", "Milan"])
    league = follow_reason((JUVE, "Juventus"), (300_000, "Otro"), (SERIE, "Serie A"), follows)
    assert league is not None and (league.kind, league.names) == ("league", ["Serie A"])
    assert follow_reason((JUVE, "Juventus"), (300_000, "Otro"), (OTRA, "Liga Otra"), follows) is None

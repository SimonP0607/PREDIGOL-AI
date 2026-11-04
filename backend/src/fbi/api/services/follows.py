"""What a reader follows, as the boards apply it on top (plan UX, A13 and B2): their favourites as ids - or, while they
chose none or personalisation is off, the ones suggested for Colombia - and why a match is theirs. Pure: built by the API's
routers from the reader's favourites; the services that use it (Home, its news) never read a reader's data."""

from __future__ import annotations

from dataclasses import dataclass

from fbi.api.contracts.today import FollowReason


@dataclass(frozen=True)
class Follows:
    """What a reader's boards follow, as ids: their favourites (in the order chosen) - or, while they chose none or
    personalisation is off, the ones suggested for Colombia (``suggested``)."""

    leagues: tuple[int, ...]
    teams: tuple[int, ...]
    suggested: bool
    personalization: bool = True


def follow_reason(home: tuple[int, str], away: tuple[int, str], competition: tuple[int, str],
                  follows: Follows) -> FollowReason | None:
    """Why a match is the reader's, from its sides and its league as (id, name): a followed team plays it - the nearer
    reason, both named when both are followed, home first - or it belongs to a followed league. None: not theirs. One rule
    for Home's matches and its news."""
    teams = set(follows.teams)
    names = [name for ref, name in (home, away) if ref in teams]
    if names:
        return FollowReason(kind="team", names=names)
    if competition[0] in set(follows.leagues):
        return FollowReason(kind="league", names=[competition[1]])
    return None

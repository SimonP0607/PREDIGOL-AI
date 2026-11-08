"""Today, for Home, over HTTP (plan UX, A9 and A13). Reading only.

* ``GET /today`` (product) - the matches from 48 hours ago to 36 hours ahead with PrediGol's result forecast labelled and one line
  of the reading, the leagues suggested until the reader picks theirs, and whether the day has published picks - or why not,
  from the published set's own funnel. The same board for every reader (kept a minute; the reason, five), with the reader's
  own leagues and teams on top (A13): why each of their matches is theirs and the next match of each favourite.
* ``GET /me/today`` (product) - «Para ti», the reader's layer of Home (closing plan 3.2): the players they follow with the state
  of his next match, which of the day's published picks are of their matches or markets, and their notices - only once they
  chose a favourite. What the leagues and teams they follow add to Home is on ``/today`` and ``/today/news``.
* ``GET /today/no-pick`` (product) - only the day's picks state and its reason, for the Picks page: the same answer as
  ``/today``'s ``no_pick``, without the list of matches.

No route here computes a probability, prices a selection or can change a pick.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from fbi.api.contracts.me_today import MeToday, Notices
from fbi.api.contracts.today import NoPick, Today
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, ok
from fbi.api.security import App
from fbi.api.services import me_today, today
from fbi.api.services.follows import Follows
from fbi.auth.roles import Role
from fbi.core.clock import now
from fbi.customer import favorites, push

router = APIRouter(tags=["today"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def follows_of(conn: psycopg.Connection[Any], user_id: int) -> Follows:
    """What the reader's Home follows: their favourites - or, while they chose none or FBI_PERSONALIZATION=0, the ones
    suggested for Colombia (labelled)."""
    on = favorites.personalization_on()
    mine = favorites.chosen(conn, user_id) if on else None
    shown = mine or favorites.suggested(conn)
    return Follows(leagues=shown.leagues, teams=shown.teams, suggested=mine is None, personalization=on)


def general_follows(conn: psycopg.Connection[Any]) -> Follows:
    """What the general layer follows whatever the reader chose: the leagues and the team suggested for Colombia."""
    shown = favorites.suggested(conn)
    return Follows(leagues=shown.leagues, teams=shown.teams, suggested=True, personalization=favorites.personalization_on())


@router.get("/today", response_model=Envelope[Today])
def get_today(conn: Db, principal: App) -> Envelope[Today]:
    """HOY: the matches around today (live, to come and the last 48 hours' results) of the followed competitions, each with
    the likely result PrediGol forecast - labelled when uncalibrated - and what the match is about; the suggested leagues;
    and the day's picks state: published, still being read («reviewing», no hour promised) or none, with the furthest stage
    the day's selections reached and its commonest reason. On top, the reader's own (``following``): their leagues and
    teams - the suggested ones while they chose none - why each of their matches is theirs (``followed``) and the next match
    of each favourite. Every reader gets the same forecasts, lines and picks state."""
    return today.for_reader(conn, today.today(conn), follows_of(conn, principal.user_id))


@router.get("/today/no-pick", response_model=Envelope[NoPick])
def get_no_pick(conn: Db, _: App) -> Envelope[NoPick]:
    """The day's picks state - published, still being read or none with its furthest stage and commonest reason - as
    ``/today`` says it, for a page that does not need the matches (Picks)."""
    reason = today.no_pick(conn)
    return ok(reason.data)


@router.get("/me/today", response_model=MeToday)
def get_me_today(conn: Db, principal: App) -> MeToday:
    """PARA TI: the reader's own layer of Home. ``chosen`` is true only when they chose a league, a team, a player or a market
    (the suggested leagues never make it so) and personalisation is on - and it is for readers: the owner's console account
    has none. Then: the players they follow with the state of the next match of his team (starter, bench, left out, missing,
    doubtful, or waiting for the line-up), which of the day's published picks are of their matches (a team, a league or the next match of a player they
    follow) or markets - or that none is - and their notices (the bells they rang and whether their devices can receive the line-ups). Every reader gets the same
    picks: only which are theirs differs."""
    on = favorites.personalization_on()
    mine = favorites.chosen(conn, principal.user_id) if on and principal.role == Role.USER else None
    more = favorites.extras(conn, principal.user_id) if on and principal.role == Role.USER else favorites.Extras()
    if mine is None and not more.players and not more.markets:
        return MeToday(personalization=on, chosen=False, players=[], markets=[], picks=None, notices=None)
    at = now()
    follows = Follows(leagues=mine.leagues if mine else (), teams=mine.teams if mine else (), suggested=False)
    watching = me_today.watched(conn, more.players, at=at)
    picks = (me_today.related(conn, follows, more.markets, me_today.player_fixtures(watching), at=at)
             if mine or more.markets or more.players else None)
    state = push.state(conn, principal.user_id)
    rung = [(b.fixture_id, int(b.minutes_before or 0)) for b in push.bells(conn, principal.user_id, at)]
    return MeToday(
        personalization=on, chosen=True, players=watching,
        markets=list(more.markets),  # type: ignore[arg-type]
        picks=picks,
        notices=Notices(available=state.available, devices=len(state.devices), lineup=state.categories["lineup"],
                        bells=me_today.bells(conn, rung)))

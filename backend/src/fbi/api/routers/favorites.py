"""A reader's favourite leagues, teams, players and markets, the welcome and the hints over HTTP (plan UX, A13 and 3.1).

* ``GET /me/favorites`` - the leagues and teams the reader follows, or the suggested ones for Colombia (labelled) while they
  have chosen none; and the players and markets they follow.
* ``PUT /me/favorites`` - they become exactly these: up to 10 leagues PrediGol follows, 20 teams that play in them, 20 players
  of their line-ups, 5 of the markets PrediGol reads and 10 of a match's catalogue (422 beyond, never trimmed). Players and
  markets left out of the body stay as they were.
* ``GET /me/favorites/options`` - every league PrediGol follows, and the teams and players whose name matches a search.
* ``GET /me/onboarding`` / ``POST /me/onboarding`` - whether the welcome is owed and its steps; done (or skipped), once.
* ``POST /me/hints`` - a first-visit hint dismissed: it never comes back.

None of these sits behind the consent or the membership gates: they are the reader's own choices, like the notification
preferences. The favourites never change a pick, a probability, a state or a price: every reader gets the same boards.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query

from fbi.api.contracts.favorites import (
    FavoriteOptions,
    FavoritesIn,
    FavoritesView,
    HintIn,
    OnboardingState,
    PlayerBadge,
)
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.auth.roles import Role
from fbi.auth.service import Principal
from fbi.core.clock import now
from fbi.customer import favorites
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me", tags=["favorites"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Search = Annotated[str | None, Query(max_length=40, description="Part of a team's name (two letters or more) or of a "
                                                                 "player's (three or more).")]

LEAGUES_SQL = """
SELECT id, name, country, logo_url, flag_url FROM core.competitions
 WHERE is_tracked AND (%(ids)s::bigint[] IS NULL OR id = ANY(%(ids)s))
 ORDER BY country NULLS LAST, name
"""

TEAMS_SQL = "SELECT id, name, logo_url FROM core.teams WHERE id = ANY(%s)"

SEARCH_SQL = """
SELECT t.id, t.name, t.logo_url FROM core.teams t
 WHERE translate(lower(t.name), %(src)s, %(dst)s) LIKE %(pattern)s
   AND EXISTS (SELECT 1 FROM core.fixtures f
                 JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                 JOIN core.competitions c ON c.id = cs.competition_id
                WHERE c.is_tracked AND (f.home_team_id = t.id OR f.away_team_id = t.id)
                  AND f.kickoff_at > now() - make_interval(days => %(days)s))
 ORDER BY translate(lower(t.name), %(src)s, %(dst)s) LIKE %(prefix)s DESC, t.is_national DESC, t.name
 LIMIT %(limit)s
"""


PLAYERS_SQL = """
SELECT p.id, p.name, p.position, latest.team
  FROM core.players p
  LEFT JOIN LATERAL (
        SELECT t.name AS team
          FROM core.fixture_lineup_players lp
          JOIN core.fixtures f ON f.id = lp.fixture_id
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          JOIN core.teams t ON t.id = CASE lp.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
         WHERE lp.provider_player_id = p.provider_player_id AND c.is_tracked
         ORDER BY f.kickoff_at DESC LIMIT 1) latest ON true
 WHERE p.id = ANY(%s)
"""
"""The reader's players, each with the team of its latest line-up (a player already followed shows even when it aged out)."""

PLAYER_SEARCH_SQL = """
SELECT p.id, p.name, p.position, latest.team
  FROM core.players p
  JOIN LATERAL (
        SELECT t.name AS team, f.kickoff_at
          FROM core.fixture_lineup_players lp
          JOIN core.fixtures f ON f.id = lp.fixture_id
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          JOIN core.teams t ON t.id = CASE lp.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
         WHERE lp.provider_player_id = p.provider_player_id AND c.is_tracked
           AND f.kickoff_at > now() - make_interval(days => %(days)s)
         ORDER BY f.kickoff_at DESC LIMIT 1) latest ON true
 WHERE translate(lower(p.name), %(src)s, %(dst)s) LIKE %(pattern)s
 ORDER BY translate(lower(p.name), %(src)s, %(dst)s) LIKE %(prefix)s DESC, latest.kickoff_at DESC, p.name
 LIMIT %(limit)s
"""


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _leagues(conn: psycopg.Connection[Any], ids: Sequence[int] | None) -> list[CompetitionBadge]:
    rows = conn.execute(LEAGUES_SQL, {"ids": None if ids is None else list(ids)}).fetchall()
    badges = {int(r[0]): CompetitionBadge(id=int(r[0]), name=r[1], country=r[2], logo_url=r[3], flag_url=r[4])
              for r in rows}
    return list(badges.values()) if ids is None else [badges[i] for i in ids if i in badges]


def _teams(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[TeamBadge]:
    if not ids:
        return []
    badges = {int(r[0]): TeamBadge(id=int(r[0]), name=r[1], logo_url=r[2])
              for r in conn.execute(TEAMS_SQL, (list(ids),)).fetchall()}
    return [badges[i] for i in ids if i in badges]


def _players(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[PlayerBadge]:
    if not ids:
        return []
    badges = {int(r[0]): PlayerBadge(id=int(r[0]), name=r[1], position=r[2], team=r[3])
              for r in conn.execute(PLAYERS_SQL, (list(ids),)).fetchall()}
    return [badges[i] for i in ids if i in badges]


def favorites_view(conn: psycopg.Connection[Any], user_id: int) -> FavoritesView:
    mine = favorites.chosen(conn, user_id)
    shown = mine or favorites.suggested(conn)
    more = favorites.extras(conn, user_id)
    return FavoritesView(leagues=_leagues(conn, shown.leagues), teams=_teams(conn, shown.teams),
                         players=_players(conn, more.players), markets=list(more.markets),  # type: ignore[arg-type]
                         catalog_markets=list(more.catalog),
                         suggested=mine is None, max_leagues=favorites.MAX_LEAGUES, max_teams=favorites.MAX_TEAMS,
                         max_players=favorites.MAX_PLAYERS, max_markets=favorites.MAX_MARKETS,
                         max_catalog_markets=favorites.MAX_CATALOG,
                         personalization=favorites.personalization_on())


def onboarding_state(conn: psycopg.Connection[Any], principal: Principal) -> OnboardingState:
    prefs = favorites.preferences(conn, principal.user_id)
    reader = principal.role == Role.USER
    return OnboardingState(
        welcome_due=favorites.welcome_due(conn, principal.user_id, reader=reader),
        welcome_steps=list(favorites.welcome_steps(conn, principal.user_id)),
        onboarded_at=prefs.onboarded_at,
        # the pages' first-visit hints only: the same list keeps the reader's dismissed suggestions and market order (B2)
        hints_seen=[h for h in prefs.hints_seen if h in favorites.HINTS])


@router.get("/favorites", response_model=FavoritesView)
def get_favorites(conn: Db, principal: App) -> FavoritesView:
    """TUS LIGAS Y EQUIPOS: what the reader follows - or, while they have chosen none, the suggested ones for Colombia."""
    return favorites_view(conn, principal.user_id)


@router.put("/favorites", response_model=FavoritesView)
def put_favorites(body: FavoritesIn, conn: Db, principal: App) -> FavoritesView:
    """The reader's favourites become exactly these (idempotent): 422 ``too_many_leagues`` / ``too_many_teams`` /
    ``too_many_players`` / ``too_many_markets`` / ``too_many_catalog_markets`` beyond the limits, ``unknown_league`` /
    ``unknown_team`` / ``unknown_player`` / ``unknown_catalog_market`` for one PrediGol does not follow. Players, markets
    and catalogue markets left out stay as they were."""
    try:
        favorites.replace(principal.user_id, body.leagues, body.teams, at=now(), players=body.players,
                          markets=body.markets, catalog=body.catalog_markets)
    except CustomerError as exc:
        raise _refused(exc) from exc
    conn.rollback()  # a fresh snapshot: written by another connection
    return favorites_view(conn, principal.user_id)


@router.get("/favorites/options", response_model=FavoriteOptions)
def favorite_options(conn: Db, _: App, q: Search = None) -> FavoriteOptions:
    """What can be followed: every league PrediGol follows, the teams of those leagues whose name matches ``q`` (two letters
    or more) and the players of their line-ups (three or more)."""
    folded = favorites.fold((q or "").strip())
    teams: list[TeamBadge] = []
    players: list[PlayerBadge] = []
    if len(folded) >= 2:
        escaped = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = {"src": favorites.ACCENTS[0], "dst": favorites.ACCENTS[1], "pattern": f"%{escaped}%",
                  "prefix": f"{escaped}%", "days": favorites.TEAM_WINDOW_DAYS, "limit": favorites.SEARCH_LIMIT}
        rows = conn.execute(SEARCH_SQL, search).fetchall()
        teams = [TeamBadge(id=int(r[0]), name=r[1], logo_url=r[2]) for r in rows]
        if len(folded) >= favorites.PLAYER_SEARCH_MIN:
            players = [PlayerBadge(id=int(r[0]), name=r[1], position=r[2], team=r[3])
                       for r in conn.execute(PLAYER_SEARCH_SQL, search).fetchall()]
    return FavoriteOptions(leagues=_leagues(conn, None), teams=teams, players=players)


@router.get("/onboarding", response_model=OnboardingState)
def get_onboarding(conn: Db, principal: App) -> OnboardingState:
    """Whether the account still owes its welcome, its steps, and the hints already dismissed."""
    return onboarding_state(conn, principal)


@router.post("/onboarding", response_model=OnboardingState)
def complete_onboarding(conn: Db, principal: App) -> OnboardingState:
    """The welcome done or skipped: recorded once, never shown again."""
    favorites.complete(principal.user_id, at=now())
    conn.rollback()
    return onboarding_state(conn, principal)


@router.post("/hints", response_model=OnboardingState)
def dismiss_hint(body: HintIn, conn: Db, principal: App) -> OnboardingState:
    """A first-visit hint dismissed with a tap: it never comes back."""
    try:
        favorites.dismiss(principal.user_id, body.hint, at=now())
    except CustomerError as exc:
        raise _refused(exc) from exc
    conn.rollback()
    return onboarding_state(conn, principal)

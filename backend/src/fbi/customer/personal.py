"""What a reader's own use orders and suggests (plan UX, B2; section 38 of the plan): visible rules, never a model.

Personalisation of the experience, never of the intelligence: nothing here reads or changes a pick, a probability, a state
or a price, and no model, decision or AI package reads what is here (tests/unit/test_user_layer_isolation.py).

    markets      the markets the reader consulted most in the last WINDOW_DAYS days come first in a match's «Mercados»:
                 their own ``market_viewed`` events - the page records one when they open a market's bookmakers or all
                 its lines, or choose one of its prices - and a market needs MIN_VIEWS of them; most first, the latest on
                 a tie, the rest in the usual order. The reader can keep the usual order instead (ORDER_KEY in
                 ``customer.preferences.hints_seen``) and come back to theirs.
    suggestion   a league PrediGol follows - or a team that plays in one - whose matches the reader keeps opening outside
                 what they follow: at least SUGGEST_MATCHES different matches on SUGGEST_DAYS different days of the last
                 WINDOW_DAYS. «¿Sigues la Serie A? Agrégala», with that reason. It is added only when the reader confirms
                 (the page saves the favourites with it), never past the limits, and never comes back once dismissed
                 (``suggest:<kind>:<id>`` in ``hints_seen``).

Both read the reader's own events only, and only while their events are being recorded now (``events.subject_now``:
FBI_PRODUCT_EVENTS on, or ``consent`` with their analytics consent granted - never the owner's, never the journey's robot).
With the events off, or the consent withdrawn, the usual order and no suggestion; FBI_PERSONALIZATION=0, neither.

Never a betting profile: what the reader opens, counted - never an amount, a stake, a result or an appetite for risk.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.customer import events, favorites
from fbi.customer.db import CustomerError, write_connection
from fbi.customer.favorites import Chosen, Kind

WINDOW_DAYS: Final = 30
"""How far back the reader's own use counts (their raw events are kept 90 days)."""
MIN_VIEWS: Final = 2
"""A market moves first once the reader consulted it this many times in the window: one look is not a habit."""
MARKETS: Final = ("1X2", "OU", "BTTS", "AH", "DC")
"""The markets a match's «Mercados» shows, in their usual order (web/src/product/shared/markets.ts)."""
SUGGEST_MATCHES: Final = 3
SUGGEST_DAYS: Final = 2
ORDER_KEY: Final = "order:markets"
"""In ``hints_seen``: the reader keeps the markets in the usual order."""
SUGGEST_PREFIX: Final = "suggest:"
MAX_DISMISSED: Final = 100
"""Dismissed suggestions kept per reader (the oldest leave first): a bound, never reached by a person."""


@dataclass(frozen=True, slots=True)
class MarketOrder:
    first: tuple[str, ...]
    """The reader's markets, most consulted first; the page shows the rest after them in the usual order."""
    views: tuple[tuple[str, int], ...]
    """Each of those markets and how many times the reader consulted it in the window - the rule, said."""
    common: bool
    """The reader keeps the usual order (``first`` is then empty; ``views`` still say what theirs would be)."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    kind: Kind
    ref_id: int
    name: str
    matches: int
    """Different matches of it the reader opened in the window, outside what they follow."""
    days: int


@dataclass(frozen=True, slots=True)
class Opened:
    """A match the reader opened (``match_opened``), with what it belongs to."""

    fixture_id: int
    day: date
    competition_id: int
    competition: str
    home_id: int
    home: str
    away_id: int
    away: str


def key_of(kind: Kind, ref_id: int) -> str:
    return f"{SUGGEST_PREFIX}{kind}:{ref_id}"


# ── the rules (pure) ──────────────────────────────────────────────────────────────────


def order_markets(views: Mapping[str, tuple[int, datetime]]) -> tuple[str, ...]:
    """The reader's markets first: each market of MARKETS consulted at least MIN_VIEWS times, most first, the latest
    consulted first on a tie, the usual order last of all. ``views``: market -> (times, last time)."""
    usual = {m: i for i, m in enumerate(MARKETS)}
    mine = [m for m, (n, _) in views.items() if m in usual and n >= MIN_VIEWS]
    return tuple(sorted(mine, key=lambda m: (-views[m][0], -views[m][1].timestamp(), usual[m])))


def in_view(o: Opened, follows: Chosen) -> bool:
    """The match is already among the reader's own: a followed team plays it or it belongs to a followed league."""
    return (o.competition_id in follows.leagues or o.home_id in follows.teams or o.away_id in follows.teams)


def suggest(opened: Iterable[Opened], follows: Chosen, *, dismissed: Iterable[str], followable: Iterable[int],
            room: tuple[bool, bool]) -> Suggestion | None:
    """The one suggestion worth making, or None: among the matches the reader opened outside what they follow, the league
    or the team with at least SUGGEST_MATCHES of them on SUGGEST_DAYS different days - most matches first, then most days,
    a team before its league on a tie (the nearer reason), then by name. Never one dismissed, never a team that cannot be
    followed, never a kind already at its limit (``room``: (leagues, teams))."""
    gone = set(dismissed)
    can_follow = set(followable)
    seen: dict[tuple[Kind, int], tuple[str, set[int], set[date]]] = {}

    def count(kind: Kind, ref: int, name: str, o: Opened) -> None:
        _, fixtures, days = seen.setdefault((kind, ref), (name, set(), set()))
        fixtures.add(o.fixture_id)
        days.add(o.day)

    for o in opened:
        if in_view(o, follows):
            continue
        if room[0]:
            count("league", o.competition_id, o.competition, o)
        if room[1]:
            for ref, name in ((o.home_id, o.home), (o.away_id, o.away)):
                if ref in can_follow:
                    count("team", ref, name, o)
    candidates = [
        Suggestion(kind=kind, ref_id=ref, name=name, matches=len(fixtures), days=len(days))
        for (kind, ref), (name, fixtures, days) in seen.items()
        if len(fixtures) >= SUGGEST_MATCHES and len(days) >= SUGGEST_DAYS and key_of(kind, ref) not in gone
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: (-s.matches, -s.days, 0 if s.kind == "team" else 1, s.name, s.ref_id))


# ── reading the reader's own use ──────────────────────────────────────────────────────

MARKET_VIEWS_SQL = """
SELECT props->>'market' AS market, count(*) AS n, max(at) AS last
  FROM customer.product_events
 WHERE subject = %(subject)s AND name = 'market_viewed' AND at >= %(since)s AND props->>'market' IS NOT NULL
 GROUP BY 1
"""

OPENED_SQL = """
SELECT f.id, (e.at AT TIME ZONE 'America/Bogota')::date AS day, c.id AS competition_id, c.name AS competition,
       f.home_team_id, th.name AS home, f.away_team_id, ta.name AS away
  FROM customer.product_events e
  JOIN core.fixtures f ON f.id = (e.props->>'match_id')::bigint
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE e.subject = %(subject)s AND e.name = 'match_opened' AND e.at >= %(since)s
   AND e.props->>'match_id' IS NOT NULL AND c.is_tracked
"""


def market_order(conn: psycopg.Connection[Any], subject: str | None, *, at: datetime, common: bool) -> MarketOrder:
    """The reader's market order from their own ``market_viewed`` events of the window (none while they are not being
    recorded: ``subject`` None)."""
    if subject is None:
        return MarketOrder(first=(), views=(), common=common)
    rows = conn.execute(MARKET_VIEWS_SQL, {"subject": subject, "since": at - timedelta(days=WINDOW_DAYS)}).fetchall()
    views = {str(r[0]): (int(r[1]), r[2]) for r in rows}
    mine = order_markets(views)
    return MarketOrder(first=() if common else mine, views=tuple((m, views[m][0]) for m in mine), common=common)


def opened(conn: psycopg.Connection[Any], subject: str, *, at: datetime) -> list[Opened]:
    rows = conn.execute(OPENED_SQL, {"subject": subject, "since": at - timedelta(days=WINDOW_DAYS)}).fetchall()
    return [Opened(fixture_id=int(r[0]), day=r[1], competition_id=int(r[2]), competition=str(r[3]), home_id=int(r[4]),
                   home=str(r[5]), away_id=int(r[6]), away=str(r[7])) for r in rows]


def followable(conn: psycopg.Connection[Any], team_ids: Sequence[int]) -> frozenset[int]:
    """The teams among these a reader may follow (a match of a followed league within favorites.TEAM_WINDOW_DAYS)."""
    if not team_ids:
        return frozenset()
    rows = conn.execute(favorites.FOLLOWABLE_TEAMS_SQL,
                        {"ids": sorted(set(team_ids)), "days": favorites.TEAM_WINDOW_DAYS}).fetchall()
    return frozenset(int(r[0]) for r in rows)


def suggestion(conn: psycopg.Connection[Any], subject: str | None, follows: Chosen, *, own: Chosen | None,
               dismissed: Iterable[str], at: datetime) -> Suggestion | None:
    """The reader's suggestion now, from their own ``match_opened`` events of the window. ``follows``: what their views
    show (their favourites, or the suggested ones while they chose none); ``own``: what they chose - accepting saves the
    suggested ones with it, so the limits count those."""
    if subject is None:
        return None
    seen = opened(conn, subject, at=at)
    if not seen:
        return None
    base = own or follows
    room = (len(base.leagues) < favorites.MAX_LEAGUES, len(base.teams) < favorites.MAX_TEAMS)
    if not any(room):
        return None
    teams = [ref for o in seen if not in_view(o, follows) for ref in (o.home_id, o.away_id)]
    return suggest(seen, follows, dismissed=dismissed, followable=followable(conn, teams) if room[1] else (),
                   room=room)


def subject_now(conn: psycopg.Connection[Any], user_id: int) -> str | None:
    """The reader's pseudonym while their events are being recorded now, else None (fbi.customer.events)."""
    row = conn.execute("SELECT email, role FROM auth.users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        return None
    return events.subject_now(conn, user_id, str(row[0]), super_admin=row[1] == "SUPER_ADMIN")


# ── what the reader decides ───────────────────────────────────────────────────────────


def _set_mark(user_id: int, mark: str, *, on: bool, at: datetime) -> tuple[str, ...]:
    """``mark`` in or out of the reader's ``hints_seen`` (idempotent, in one statement - a first-visit hint dismissed at
    the same moment is kept); past MAX_DISMISSED dismissed suggestions, the oldest leave."""
    with write_connection() as conn:
        if on:
            row = conn.execute(
                "INSERT INTO customer.preferences (user_id, hints_seen, updated_at) VALUES (%s, ARRAY[%s]::text[], %s) "
                "ON CONFLICT (user_id) DO UPDATE SET hints_seen = CASE WHEN %s = ANY(customer.preferences.hints_seen) "
                "THEN customer.preferences.hints_seen ELSE array_append(customer.preferences.hints_seen, %s) END, "
                "updated_at = EXCLUDED.updated_at RETURNING hints_seen",
                (user_id, mark, at, mark, mark)).fetchone()
        else:
            row = conn.execute(
                "UPDATE customer.preferences SET hints_seen = array_remove(hints_seen, %s), updated_at = %s "
                "WHERE user_id = %s RETURNING hints_seen", (mark, at, user_id)).fetchone()
        seen = [str(h) for h in (row[0] if row else ())]
        dismissed = [h for h in seen if h.startswith(SUGGEST_PREFIX)]
        if len(dismissed) > MAX_DISMISSED:  # the row is locked by the statement above until this commits
            drop = set(dismissed[: len(dismissed) - MAX_DISMISSED])
            seen = [h for h in seen if h not in drop]
            conn.execute("UPDATE customer.preferences SET hints_seen = %s WHERE user_id = %s", (seen, user_id))
    return tuple(seen)


def dismiss_suggestion(conn: psycopg.Connection[Any], user_id: int, kind: Kind, ref_id: int, *,
                       at: datetime) -> None:
    """«No, gracias»: this league or team is never suggested to the reader again. 422 for one PrediGol does not follow."""
    exists = (conn.execute("SELECT 1 FROM core.competitions WHERE id = %s AND is_tracked", (ref_id,)).fetchone()
              if kind == "league" else conn.execute("SELECT 1 FROM core.teams WHERE id = %s", (ref_id,)).fetchone())
    if exists is None:
        raise CustomerError(422, f"unknown_{kind}", f"not a {kind} PrediGol follows: {ref_id}")
    _set_mark(user_id, key_of(kind, ref_id), on=True, at=at)


def keep_usual_order(user_id: int, common: bool, *, at: datetime) -> None:
    """The reader keeps the markets in the usual order (``common``) or goes back to theirs."""
    _set_mark(user_id, ORDER_KEY, on=common, at=at)


def marks(hints_seen: Iterable[str]) -> tuple[bool, tuple[str, ...]]:
    """From ``hints_seen``: whether the reader keeps the usual market order, and the suggestions they dismissed."""
    seen = tuple(hints_seen)
    return ORDER_KEY in seen, tuple(h for h in seen if h.startswith(SUGGEST_PREFIX))

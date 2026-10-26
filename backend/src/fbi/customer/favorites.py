"""A reader's favourite leagues and teams, the welcome and the hints (plan UX, A13; sections 20 and 38 of the plan).

Personalisation of the experience, never of the intelligence: the favourites order and filter what a reader is shown
(Home's «Hoy en tus ligas» first); picks, probabilities, states and prices are the same for every reader - the boards stay
shared and cached, and the page applies the reader's favourites on top. Every personalised element says why it is there.

    favourites   up to MAX_LEAGUES leagues PrediGol follows and MAX_TEAMS teams that play in them (constants: they widen
                 without a migration). Until the reader chooses, the suggested ones for Colombia - the leagues and the
                 national team Home suggested since A9 (``fbi.core.suggestions``: one list for Home, its news and here) -
                 labelled as suggested.
    welcome      once per account, after the consents: «Tu fútbol» (the favourites, the suggested already ticked; skipping
                 keeps them) and «Qué es PrediGol» - then Home. ``customer.preferences.onboarded_at`` records it; existing
                 accounts see the one screen of favourites too, and never the rest again. FBI_ONBOARDING=0 sends every
                 account straight to Home (the favourites stay).
    hints        one per page (Picks, a match, the parlay slip, Mis picks), the first visit only, dismissed with a tap and
                 never again (``customer.preferences.hints_seen``).

Never a betting profile: no amounts, no bankroll, no appetite for risk - only what the reader follows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from fbi.core.env import environment
from fbi.core.suggestions import SUGGESTED_LEAGUES, SUGGESTED_TEAM
from fbi.customer.db import CustomerError, write_connection

MAX_LEAGUES: Final = 10
MAX_TEAMS: Final = 20
HINTS: Final = ("picks", "match", "parlay", "my_picks")
"""The pages with a first-visit hint (plan section 20)."""
ONBOARDING_SWITCH: Final = "FBI_ONBOARDING"
PERSONALIZATION_SWITCH: Final = "FBI_PERSONALIZATION"
TEAM_WINDOW_DAYS: Final = 400
"""A team can be followed when it played or plays a match of a followed league within this many days (a season and a bit)."""
SEARCH_LIMIT: Final = 20
_ON: Final = frozenset({"1", "on", "true", "yes"})
ACCENTS: Final = ("áàäâãéèëêíìïîóòöôõúùüûñç", "aaaaaeeeeiiiiooooouuuunc")
"""What a search folds: the accented letters and their plain ones (the same pair in Python and in SQL's translate)."""

Kind = Literal["league", "team"]


def _switch(name: str) -> bool:
    """ON while the line is absent or empty (the owner approved the plan; the line turns it off without a deploy), off
    for a value it cannot read."""
    raw = environment().get(name)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _ON


def onboarding_on() -> bool:
    """``FBI_ONBOARDING``: the welcome after the consents; =0 sends every account straight to Home."""
    return _switch(ONBOARDING_SWITCH)


def personalization_on() -> bool:
    """``FBI_PERSONALIZATION``: Home orders by the reader's favourites; =0 gives every reader the common view."""
    return _switch(PERSONALIZATION_SWITCH)


@dataclass(frozen=True)
class Chosen:
    leagues: tuple[int, ...]
    teams: tuple[int, ...]


CHOSEN_SQL = "SELECT kind, ref_id FROM customer.favorites WHERE user_id = %s ORDER BY created_at, ref_id"

SUGGESTED_SQL = """
SELECT 'league' AS kind, c.id FROM core.competitions c
 WHERE c.is_tracked AND c.provider_league_id = ANY(%(leagues)s)
UNION ALL
SELECT 'team', t.id FROM core.teams t WHERE t.is_national AND t.name = %(team)s
"""

TRACKED_LEAGUES_SQL = "SELECT id FROM core.competitions WHERE is_tracked AND id = ANY(%s)"

FOLLOWABLE_TEAMS_SQL = """
SELECT t.id FROM core.teams t
 WHERE t.id = ANY(%(ids)s)
   AND EXISTS (SELECT 1 FROM core.fixtures f
                 JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                 JOIN core.competitions c ON c.id = cs.competition_id
                WHERE c.is_tracked AND (f.home_team_id = t.id OR f.away_team_id = t.id)
                  AND f.kickoff_at > now() - make_interval(days => %(days)s))
"""

PREFERENCES_SQL = "SELECT onboarded_at, hints_seen FROM customer.preferences WHERE user_id = %s"


def chosen(conn: psycopg.Connection[Any], user_id: int) -> Chosen | None:
    """The reader's favourites, or None while they have chosen none."""
    rows = conn.execute(CHOSEN_SQL, (user_id,)).fetchall()
    if not rows:
        return None
    return Chosen(leagues=tuple(int(r[1]) for r in rows if r[0] == "league"),
                  teams=tuple(int(r[1]) for r in rows if r[0] == "team"))


def suggested(conn: psycopg.Connection[Any]) -> Chosen:
    """The suggested favourites for Colombia: the leagues PrediGol follows among SUGGESTED_LEAGUES and the national team."""
    rows = conn.execute(SUGGESTED_SQL, {"leagues": list(SUGGESTED_LEAGUES), "team": SUGGESTED_TEAM}).fetchall()
    return Chosen(leagues=tuple(sorted(int(r[1]) for r in rows if r[0] == "league")),
                  teams=tuple(sorted(int(r[1]) for r in rows if r[0] == "team")))


def _unique(ids: Sequence[int]) -> list[int]:
    seen: list[int] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def validate(conn: psycopg.Connection[Any], leagues: Sequence[int], teams: Sequence[int]) -> Chosen:
    """The favourites a reader may keep: within the limits, leagues PrediGol follows, teams that play in them. Refuses
    (422) rather than trims: the page shows the limit before the reader reaches it."""
    want_leagues, want_teams = _unique(leagues), _unique(teams)
    if len(want_leagues) > MAX_LEAGUES:
        raise CustomerError(422, "too_many_leagues", f"at most {MAX_LEAGUES} leagues")
    if len(want_teams) > MAX_TEAMS:
        raise CustomerError(422, "too_many_teams", f"at most {MAX_TEAMS} teams")
    if want_leagues:
        known = {int(r[0]) for r in conn.execute(TRACKED_LEAGUES_SQL, (want_leagues,)).fetchall()}
        if missing := [i for i in want_leagues if i not in known]:
            raise CustomerError(422, "unknown_league", f"not a league PrediGol follows: {missing[0]}")
    if want_teams:
        known = {int(r[0]) for r in conn.execute(FOLLOWABLE_TEAMS_SQL,
                                                   {"ids": want_teams, "days": TEAM_WINDOW_DAYS}).fetchall()}
        if missing := [i for i in want_teams if i not in known]:
            raise CustomerError(422, "unknown_team", f"not a team of a league PrediGol follows: {missing[0]}")
    return Chosen(leagues=tuple(want_leagues), teams=tuple(want_teams))


def replace(user_id: int, leagues: Sequence[int], teams: Sequence[int], *, at: datetime) -> tuple[Chosen, Chosen, Chosen]:
    """The reader's favourites become exactly these (idempotent). Returns what they are now, what was added and what was
    removed - the page records each as an event (favorite_added / favorite_removed)."""
    with write_connection() as conn:
        want = validate(conn, leagues, teams)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('customer.favorites'), %s)", (user_id % 2**31,))
        before = chosen(conn, user_id) or Chosen((), ())
        removed = Chosen(leagues=tuple(i for i in before.leagues if i not in want.leagues),
                         teams=tuple(i for i in before.teams if i not in want.teams))
        added = Chosen(leagues=tuple(i for i in want.leagues if i not in before.leagues),
                       teams=tuple(i for i in want.teams if i not in before.teams))
        for kind, ids in (("league", removed.leagues), ("team", removed.teams)):
            if ids:
                conn.execute("DELETE FROM customer.favorites WHERE user_id = %s AND kind = %s AND ref_id = ANY(%s)",
                             (user_id, kind, list(ids)))
        # The reader's order: a favourite is listed by when it was chosen, and the ones of one save a microsecond apart in
        # the order sent (leagues, then teams) - so the list reads back as the reader put it.
        step = 0
        for kind, ids in (("league", added.leagues), ("team", added.teams)):
            for ref in ids:
                conn.execute(
                    "INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_id, kind, ref, ref if kind == "league" else None, ref if kind == "team" else None,
                     at + timedelta(microseconds=step)))
                step += 1
    return want, added, removed


@dataclass(frozen=True)
class Preferences:
    onboarded_at: datetime | None
    hints_seen: tuple[str, ...]


def preferences(conn: psycopg.Connection[Any], user_id: int) -> Preferences:
    row = conn.execute(PREFERENCES_SQL, (user_id,)).fetchone()
    if row is None:
        return Preferences(None, ())
    return Preferences(row[0], tuple(str(h) for h in (row[1] or ())))


NEW_ACCOUNT_DAYS: Final = 14
"""An account this young sees the whole welcome («Tu fútbol» and «Qué es PrediGol»); an older one - an account from before
A13 - the favourites alone (plan section 20: «no repiten el resto»). Fourteen days: the trial's length (A8)."""


def welcome_steps(conn: psycopg.Connection[Any], user_id: int) -> tuple[Literal["football", "about"], ...]:
    row = conn.execute("SELECT created_at > now() - make_interval(days => %s) FROM auth.users WHERE id = %s",
                       (NEW_ACCOUNT_DAYS, user_id)).fetchone()
    return ("football", "about") if row is not None and row[0] else ("football",)


def welcome_due(conn: psycopg.Connection[Any], user_id: int, *, reader: bool) -> bool:
    """Whether the account still owes its welcome: readers only (never the owner's accounts), once, while the switch is on."""
    return reader and onboarding_on() and preferences(conn, user_id).onboarded_at is None


def complete(user_id: int, *, at: datetime) -> datetime:
    """The welcome done (or skipped): recorded once - a second call keeps the first moment."""
    with write_connection() as conn:
        row = conn.execute(
            "INSERT INTO customer.preferences (user_id, onboarded_at, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET onboarded_at = COALESCE(customer.preferences.onboarded_at, "
            "EXCLUDED.onboarded_at), updated_at = CASE WHEN customer.preferences.onboarded_at IS NULL "
            "THEN EXCLUDED.updated_at ELSE customer.preferences.updated_at END RETURNING onboarded_at",
            (user_id, at, at)).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def dismiss(user_id: int, hint: str, *, at: datetime) -> tuple[str, ...]:
    """A hint dismissed: it never comes back. Refuses a hint the plan does not have (422)."""
    if hint not in HINTS:
        raise CustomerError(422, "unknown_hint", f"no hint called {hint}")
    with write_connection() as conn:
        row = conn.execute(
            "INSERT INTO customer.preferences (user_id, hints_seen, updated_at) VALUES (%s, ARRAY[%s]::text[], %s) "
            "ON CONFLICT (user_id) DO UPDATE SET hints_seen = CASE WHEN %s = ANY(customer.preferences.hints_seen) "
            "THEN customer.preferences.hints_seen ELSE array_append(customer.preferences.hints_seen, %s) END, "
            "updated_at = EXCLUDED.updated_at RETURNING hints_seen",
            (user_id, hint, at, hint, hint)).fetchone()
    assert row is not None
    return tuple(str(h) for h in row[0])


def fold(text: str) -> str:
    """Lower case without accents: «Atlético» and «atletico» are the same search."""
    return text.lower().translate(str.maketrans(*ACCENTS))

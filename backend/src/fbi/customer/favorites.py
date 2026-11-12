"""A reader's favourite leagues, teams, players and markets, the welcome and the hints (plan UX, A13 and closing plan 3.1;
sections 20 and 38 of the plan).

Personalisation of the experience, never of the intelligence: the favourites order and filter what a reader is shown
(Home's «Hoy en tus ligas» first); picks, probabilities, states and prices are the same for every reader - the boards stay
shared and cached, and the page applies the reader's favourites on top. Every personalised element says why it is there.

    favourites   up to MAX_LEAGUES leagues PrediGol follows and MAX_TEAMS teams that play in them (constants: they widen
                 without a migration). Until the reader chooses, the suggested ones for Colombia - the leagues and the
                 national team Home suggested since A9 (``fbi.core.suggestions``: one list for Home, its news and here) -
                 labelled as suggested.
    players      (3.1) up to MAX_PLAYERS players who appeared in a line-up of a league PrediGol follows within
                 TEAM_WINDOW_DAYS: seen in a line-up or searched by name. One already followed stays even when it ages out.
    markets      (3.1) up to MAX_MARKETS of the markets PrediGol reads (FOLLOWABLE_MARKETS): the ones the reader reads most.
                 A market is followed for what it is - a name - never for what the reader stakes on it.
    catalog      (CUOTAS, BE-025) up to MAX_CATALOG markets of a match's catalogue («Mercados»: corners, cards, shots, the
                 halves...) by the key the catalogue gives them (``corners_over_under.FT.match``). Apart from ``markets``:
                 the five classic ones keep their own list, limit and meaning. Only the reader's order of the markets they
                 see changes; no pick, probability or price.
    welcome      once per account, after the consents: «Tu fútbol» (the favourites, the suggested already ticked; skipping
                 keeps them) and «Qué es PrediGol» - then Home. ``customer.preferences.onboarded_at`` records it; existing
                 accounts see the one screen of favourites too, and never the rest again. FBI_ONBOARDING=0 sends every
                 account straight to Home (the favourites stay).
    hints        one per page (Picks, a match, the parlay slip, Mis picks), the first visit only, dismissed with a tap and
                 never again (``customer.preferences.hints_seen``).

Never a betting profile: no amounts, no bankroll, no appetite for risk - only what the reader follows (the markets they
read, not the picks they take).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from fbi.core.env import environment
from fbi.core.suggestions import SUGGESTED_LEAGUES, SUGGESTED_TEAM
from fbi.customer.db import CustomerError, write_connection

MAX_LEAGUES: Final = 10
MAX_TEAMS: Final = 20
MAX_PLAYERS: Final = 20
MAX_MARKETS: Final = 5
MAX_CATALOG: Final = 10
"""Markets of the catalogue a reader may follow besides the five classic ones (widens without a migration)."""
FOLLOWABLE_MARKETS: Final = ("1X2", "OU", "BTTS", "AH", "DC")
"""The markets PrediGol reads and a reader may follow (the product's MarketKey: a test keeps both lists the same)."""
HINTS: Final = ("picks", "match", "parlay", "my_picks")
"""The pages with a first-visit hint (plan section 20)."""
ONBOARDING_SWITCH: Final = "FBI_ONBOARDING"
PERSONALIZATION_SWITCH: Final = "FBI_PERSONALIZATION"
TEAM_WINDOW_DAYS: Final = 400
"""A team can be followed when it played or plays a match of a followed league within this many days (a season and a bit)."""
SEARCH_LIMIT: Final = 20
PLAYER_SEARCH_MIN: Final = 3
"""A player's name is searched from three letters (two would list half the league)."""
_ON: Final = frozenset({"1", "on", "true", "yes"})
ACCENTS: Final = ("áàäâãéèëêíìïîóòöôõúùüûñç", "aaaaaeeeeiiiiooooouuuunc")
"""What a search folds: the accented letters and their plain ones (the same pair in Python and in SQL's translate)."""

Kind = Literal["league", "team"]
ExtraKind = Literal["player", "market"]


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


@dataclass(frozen=True)
class Extras:
    """The players and markets a reader follows (3.1): apart from ``Chosen`` because the suggested leagues and team stand
    in for the leagues and teams alone - a reader who follows a player still sees them as suggested."""

    players: tuple[int, ...] = ()
    markets: tuple[str, ...] = ()
    catalog: tuple[str, ...] = ()


@dataclass(frozen=True)
class Saved:
    """What a save left: the favourites now, what it added and what it removed (the page records each as an event)."""

    now: Chosen
    added: Chosen
    removed: Chosen
    extras: Extras
    extras_added: Extras
    extras_removed: Extras


CHOSEN_SQL = (
    "SELECT kind, ref_id FROM customer.favorites WHERE user_id = %s AND kind IN ('league', 'team') "
    "ORDER BY created_at, ref_id"
)

EXTRAS_SQL = (
    "SELECT kind, ref_id, COALESCE(market_key, catalog_key) FROM customer.favorites WHERE user_id = %s "
    "AND kind IN ('player', 'market', 'catalog') ORDER BY created_at, ref_id NULLS LAST, market_key, catalog_key"
)

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

APPEARANCE_SQL = """
SELECT 1 FROM core.fixture_lineup_players lp
  JOIN core.fixtures f ON f.id = lp.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE lp.provider_player_id = p.provider_player_id AND c.is_tracked
   AND f.kickoff_at > now() - make_interval(days => %(days)s)
"""
"""A player's appearance in a line-up of a league PrediGol follows within the window (p is the core.players row)."""

FOLLOWABLE_PLAYERS_SQL = f"""
SELECT p.id FROM core.players p WHERE p.id = ANY(%(ids)s) AND EXISTS ({APPEARANCE_SQL})
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


def _unique[T](ids: Sequence[T]) -> list[T]:
    seen: list[T] = []
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


def extras(conn: psycopg.Connection[Any], user_id: int) -> Extras:
    """The players and markets the reader follows, in the order chosen (none while they follow none)."""
    rows = conn.execute(EXTRAS_SQL, (user_id,)).fetchall()
    return Extras(players=tuple(int(r[1]) for r in rows if r[0] == "player"),
                  markets=tuple(str(r[2]) for r in rows if r[0] == "market"),
                  catalog=tuple(str(r[2]) for r in rows if r[0] == "catalog"))


def validate_extras(conn: psycopg.Connection[Any], players: Sequence[int], markets: Sequence[str],
                    *, already: Extras | None = None, catalog: Sequence[str] = (),
                    catalog_valid: Callable[[str], bool] | None = None) -> Extras:
    """The players and markets a reader may keep: within the limits, players who appeared in a line-up of a league
    PrediGol follows, markets PrediGol reads. One the reader already follows is kept without asking again (a player ages out
    of the window; a favourite never blocks a save). Refuses (422) rather than trims."""
    want_players, want_markets = _unique(players), _unique([str(m) for m in markets])
    want_catalog = _unique([str(k) for k in catalog])
    if len(want_catalog) > MAX_CATALOG:
        raise CustomerError(422, "too_many_catalog_markets", f"at most {MAX_CATALOG} catalogue markets")
    kept_catalog = already.catalog if already else ()
    if unknown_key := [k for k in want_catalog if k not in kept_catalog and not (catalog_valid and catalog_valid(k))]:
        raise CustomerError(422, "unknown_catalog_market", f"not a market of the catalogue: {unknown_key[0]}")
    if len(want_players) > MAX_PLAYERS:
        raise CustomerError(422, "too_many_players", f"at most {MAX_PLAYERS} players")
    if len(want_markets) > MAX_MARKETS:
        raise CustomerError(422, "too_many_markets", f"at most {MAX_MARKETS} markets")
    if unknown := [m for m in want_markets if m not in FOLLOWABLE_MARKETS]:
        raise CustomerError(422, "unknown_market", f"not a market PrediGol reads: {unknown[0]}")
    kept = already.players if already else ()
    new = [i for i in want_players if i not in kept]
    if new:
        known = {int(r[0]) for r in conn.execute(FOLLOWABLE_PLAYERS_SQL,
                                                   {"ids": new, "days": TEAM_WINDOW_DAYS}).fetchall()}
        if missing := [i for i in new if i not in known]:
            raise CustomerError(422, "unknown_player",
                                f"not a player of a league PrediGol follows: {missing[0]}")
    return Extras(players=tuple(want_players), markets=tuple(want_markets), catalog=tuple(want_catalog))


INSERT_SQL = (
    "INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id, player_id, market_key, catalog_key, "
    "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"
)


def replace(user_id: int, leagues: Sequence[int], teams: Sequence[int], *, at: datetime,
            players: Sequence[int] | None = None, markets: Sequence[str] | None = None,
            catalog: Sequence[str] | None = None, catalog_valid: Callable[[str], bool] | None = None) -> Saved:
    """The reader's favourites become exactly these (idempotent). ``players`` / ``markets`` / ``catalog`` left out (None)
    keep what the reader has - a page from before 3.1 (or from before BE-025) never clears them. ``catalog_valid`` says
    whether a NEW catalogue key is one the catalogue can show: the API passes it (the taxonomy lives in PrediGol Intelligence's
    packages, which this layer never loads); without it no new key is accepted. Returns what they are now,
    what was added and what was removed - the page records each as an event (favorite_added / favorite_removed)."""
    with write_connection() as conn:
        want = validate(conn, leagues, teams)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('customer.favorites'), %s)", (user_id % 2**31,))
        before = chosen(conn, user_id) or Chosen((), ())
        before_extras = extras(conn, user_id)
        want_extras = (before_extras if players is None and markets is None and catalog is None else
                       validate_extras(conn, before_extras.players if players is None else players,
                                       before_extras.markets if markets is None else markets,
                                       already=before_extras,
                                       catalog=before_extras.catalog if catalog is None else catalog,
                                       catalog_valid=catalog_valid))
        removed = Chosen(leagues=tuple(i for i in before.leagues if i not in want.leagues),
                         teams=tuple(i for i in before.teams if i not in want.teams))
        added = Chosen(leagues=tuple(i for i in want.leagues if i not in before.leagues),
                       teams=tuple(i for i in want.teams if i not in before.teams))
        extras_removed = Extras(players=tuple(i for i in before_extras.players if i not in want_extras.players),
                                markets=tuple(m for m in before_extras.markets if m not in want_extras.markets),
                                catalog=tuple(k for k in before_extras.catalog if k not in want_extras.catalog))
        extras_added = Extras(players=tuple(i for i in want_extras.players if i not in before_extras.players),
                              markets=tuple(m for m in want_extras.markets if m not in before_extras.markets),
                              catalog=tuple(k for k in want_extras.catalog if k not in before_extras.catalog))
        for kind, ids in (("league", removed.leagues), ("team", removed.teams), ("player", extras_removed.players)):
            if ids:
                conn.execute("DELETE FROM customer.favorites WHERE user_id = %s AND kind = %s AND ref_id = ANY(%s)",
                             (user_id, kind, list(ids)))
        if extras_removed.markets:
            conn.execute("DELETE FROM customer.favorites WHERE user_id = %s AND kind = 'market' "
                         "AND market_key = ANY(%s)", (user_id, list(extras_removed.markets)))
        if extras_removed.catalog:
            conn.execute("DELETE FROM customer.favorites WHERE user_id = %s AND kind = 'catalog' "
                         "AND catalog_key = ANY(%s)", (user_id, list(extras_removed.catalog)))
        # The reader's order: a favourite is listed by when it was chosen, and the ones of one save a microsecond apart in
        # the order sent (leagues, teams, players, then markets) - so the list reads back as the reader put it.
        step = 0
        for kind, ids in (("league", added.leagues), ("team", added.teams), ("player", extras_added.players)):
            for ref in ids:
                conn.execute(INSERT_SQL, (user_id, kind, ref, ref if kind == "league" else None,
                                          ref if kind == "team" else None, ref if kind == "player" else None, None, None,
                                          at + timedelta(microseconds=step)))
                step += 1
        for key in extras_added.markets:
            conn.execute(INSERT_SQL, (user_id, "market", None, None, None, None, key, None,
                                      at + timedelta(microseconds=step)))
            step += 1
        for key in extras_added.catalog:
            conn.execute(INSERT_SQL, (user_id, "catalog", None, None, None, None, None, key,
                                      at + timedelta(microseconds=step)))
            step += 1
    return Saved(now=want, added=added, removed=removed, extras=want_extras, extras_added=extras_added,
                 extras_removed=extras_removed)


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


# ── a followed team's bell (plan maestro UX/UI 2026, decision 8) ─────────────────────────────────────────────────────


def muted_teams(conn: psycopg.Connection[Any], user_id: int) -> tuple[int, ...]:
    """The followed teams whose bell is off: no line-up notice, out of the day's summary."""
    rows = conn.execute("SELECT ref_id FROM customer.favorites WHERE user_id = %s AND kind = 'team' AND NOT notify "
                        "ORDER BY created_at, ref_id", (user_id,)).fetchall()
    return tuple(int(r[0]) for r in rows)


def set_team_notify(user_id: int, team_id: int, notify: bool) -> None:
    """Turn a followed team's bell on or off; 404 ``not_followed`` for a team the reader does not follow."""
    with write_connection() as conn:
        done = conn.execute("UPDATE customer.favorites SET notify = %s WHERE user_id = %s AND kind = 'team' "
                            "AND ref_id = %s", (notify, user_id, team_id))
        if done.rowcount == 0:
            raise CustomerError(404, "not_followed", "the reader does not follow this team")

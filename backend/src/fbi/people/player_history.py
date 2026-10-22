"""A player's clubs and national team in the database (plan F3): reading the pieces the provider gave, folding them and writing the
difference.

``fbi.people.spells`` decides where a player was and ``fbi.people.caps`` which of his matches are national-team caps; this module
reads the facts they need from the tables the ingestion fills, asks them, and writes ``core.player_spells`` and
``core.player_national_caps``. Nothing here asks the provider for anything.

THE FACTS IT READS
------------------
* the transfers the provider lists (``core.player_transfers``, the newest snapshot of each player): a date, the club out and the club
  in; a transfer with no date cannot be placed in time and is left out;
* the squad sheets of the matches (``core.fixture_lineup_players``) and their statistics (``core.fixture_player_stats``): he was in the
  matchday squad of a club that day. Only matches that were played (live or finished) and only clubs: a national team is not where a
  man plays his football, and a team nobody has classified is not taken for a club. WHICH side of the match he was on is decided by
  ``fbi.people.sides``: the statistics win over the sheet, and a sheet the statistics turn round (the provider gave each team the
  other's, in 202 matches) is read as the other side's;
* the squad lists (``core.squad_members``): our first and last sighting of him in a club's list.

A PASS
------
Reads the facts of a batch of players, folds them, compares the answer with what is stored and writes only the difference, so a second
pass writes nothing. The scheduled pass looks at the players who appear in recent matches, transfers or squad lists (the facts that
changed); the daily sweep looks at everyone, which also catches what arrived late (statistics of an old match, a backfill). The pass is one
transaction under an advisory lock, so two never write at once, and a worker that finds the lock taken gives way.

DATES are UTC days: the kick-off of a match is the day of the evidence, a squad sighting the day it was made.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.people import caps as cp
from fbi.people import sides
from fbi.people import spells as sp

JOB: Final = "player_history"
LOCK_KEY: Final = "fbi.player_history"
VERSION: Final = f"{sp.VERSION}+{cp.VERSION}+{sides.VERSION}"
BATCH: Final = 2_000
"""Players per batch of a pass: one query per fact."""
CAP_BATCH: Final = 500
"""Matches per batch of caps."""
WINDOW: Final = timedelta(days=4)
"""How far back the scheduled pass looks for the facts that changed (the daily sweep looks at everything)."""
MANUAL_LOCK_WAIT: Final = "20s"

SCHEDULED: Final = "scheduled"
SWEEP: Final = "sweep"


# ── the teams ────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Team:
    id: int
    provider_id: int
    name: str
    national: bool | None
    """PrediGol's classification (``core.team_kind``), else the provider's flag; None: nobody has decided."""


def read_teams(conn: psycopg.Connection[Any]) -> dict[int, Team]:
    """Every team by our id."""
    with conn.cursor() as cur:
        cur.execute("SELECT t.id, t.provider_team_id, t.name, COALESCE(k.is_national, t.is_national) "
                    "FROM core.teams t LEFT JOIN core.team_kind k ON k.team_id = t.id")
        return {int(i): Team(int(i), int(p), str(n), None if f is None else bool(f)) for i, p, n, f in cur.fetchall()}


# ── which side he was on ─────────────────────────────────────────────────────────────────────────────────────────────────

SHEETS_SQL: Final = """
SELECT l.fixture_id, l.team_side, count(*) AS men, count(*) FILTER (WHERE s.team_side <> l.team_side) AS apart
  FROM core.fixture_lineup_players l
  JOIN core.fixture_player_stats s ON s.fixture_id = l.fixture_id AND s.source = l.source AND s.provider_player_id = l.provider_player_id
 WHERE l.provider_player_id > 0 AND {scope}
 GROUP BY l.fixture_id, l.team_side
HAVING count(*) FILTER (WHERE s.team_side <> l.team_side) > 0"""
"""One row per squad sheet that has a man the statistics of the same match put on the other side: the men of the sheet that are in the
statistics, and how many of them are on the other side (a sheet that agrees on every man is not listed). Keys are unique per source, so
``count(*)`` counts men."""
SHEET_SCOPES: Final = {
    "all": "true",
    "fixtures": "l.fixture_id = ANY(%(fixtures)s)",
    "players": ("l.fixture_id IN (SELECT fixture_id FROM core.fixture_lineup_players WHERE provider_player_id = ANY(%(players)s) "
                "UNION SELECT fixture_id FROM core.fixture_player_stats WHERE provider_player_id = ANY(%(players)s))"),
}


@dataclass(frozen=True, slots=True)
class Sheets:
    """What the statistics say about the squad sheets of some matches."""

    crossed: frozenset[tuple[int, str]]
    """(match, side) of the sheets that are the other side's (``fbi.people.sides.is_crossed``)."""
    doubtful: int
    """Sheets with a man the statistics put on the other side that are not crossed: one man listed in both sheets of his match, or too few
    men in the statistics to say."""


def read_sheets(conn: psycopg.Connection[Any], *, players: Sequence[int] | None = None, fixtures: Sequence[int] | None = None) -> Sheets:
    """The squad sheets of the matches of these ``players`` (or of these ``fixtures``; of every match when neither is given) that the
    statistics of the same match turn round. Looking at every match reads all the squad sheets and statistics (the order of a minute on
    the production database), which a pass over everyone needs anyway."""
    if players is not None and fixtures is not None:
        raise ValueError("a scope is the players or the matches, not both")
    scope, params = ("players", {"players": list(players)}) if players is not None else (
        ("fixtures", {"fixtures": list(fixtures)}) if fixtures is not None else ("all", {}))
    crossed: set[tuple[int, str]] = set()
    doubtful = 0
    with conn.cursor() as cur:
        cur.execute(SHEETS_SQL.format(scope=SHEET_SCOPES[scope]), params)
        for fixture, side, men, apart in cur.fetchall():
            if sides.is_crossed(int(men), int(apart)):
                crossed.add((int(fixture), str(side)))
            else:
                doubtful += 1
    return Sheets(frozenset(crossed), doubtful)


MatchRow = tuple[int, int, date, str, int, int]
"""(man, match, day, side, home team, away team): a line of a squad sheet or of the statistics of a match."""
Placed = tuple[int, int, date, int]
"""(man, match, day, team): the team a man was in for a match."""


def _by_man(rows: Iterable[MatchRow], crossed: AbstractSet[tuple[int, str]]) -> dict[tuple[int, int], tuple[date, int, int, set[str]]]:
    found: dict[tuple[int, int], tuple[date, int, int, set[str]]] = {}
    for man, match, day, side, home, away in rows:
        resolved = sides.other(side) if (match, side) in crossed else side
        found.setdefault((man, match), (day, home, away, set()))[3].add(resolved)
    return found


def placed_matches(sheet: Iterable[MatchRow], statistics: Iterable[MatchRow], crossed: AbstractSet[tuple[int, str]]) -> tuple[list[Placed], int]:
    """The team of every man in every match the facts place him in, and how many (man, match) they leave nowhere.

    The statistics win: a man they name is on the side they say, whatever his sheet says. A man only the sheet names is on the side
    of his sheet - read as the other side's when the sheet is in ``crossed`` - and nowhere when he is in both sheets of the match.
    Pure; the order of the rows does not matter."""
    by_stats = _by_man(statistics, frozenset())
    by_sheet = _by_man(sheet, crossed)
    placed: list[Placed] = []
    nowhere = 0
    for key in sorted(by_stats.keys() | by_sheet.keys()):
        day, home, away, found = by_stats[key] if key in by_stats else by_sheet[key]
        if len(found) != 1:
            nowhere += 1
            continue
        placed.append((key[0], key[1], day, home if next(iter(found)) == sides.HOME else away))
    return placed, nowhere


# ── the history of the clubs ─────────────────────────────────────────────────────────────────────────────────────────────

TRANSFERS_SQL: Final = """
SELECT provider_player_id, transfer_date, type, team_in_id, team_in_name, team_out_id, team_out_name
  FROM core.player_transfers_latest
 WHERE provider_player_id = ANY(%(players)s) AND provider_player_id > 0 AND transfer_date IS NOT NULL"""
SHEET_ROWS_SQL: Final = """
SELECT p.provider_player_id, p.fixture_id, (f.kickoff_at AT TIME ZONE 'UTC')::date, p.team_side, f.home_team_id, f.away_team_id
  FROM core.fixture_lineup_players p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE p.provider_player_id = ANY(%(players)s) AND p.provider_player_id > 0 AND f.status_group IN ('live', 'finished')"""
STAT_ROWS_SQL: Final = """
SELECT s.provider_player_id, s.fixture_id, (f.kickoff_at AT TIME ZONE 'UTC')::date, s.team_side, f.home_team_id, f.away_team_id
  FROM core.fixture_player_stats s JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.provider_player_id = ANY(%(players)s) AND s.provider_player_id > 0 AND f.status_group IN ('live', 'finished')"""
SQUADS_SQL: Final = """
SELECT provider_player_id, team_id, (first_seen_at AT TIME ZONE 'UTC')::date, (last_seen_at AT TIME ZONE 'UTC')::date
  FROM core.squad_members WHERE provider_player_id = ANY(%(players)s) AND provider_player_id > 0"""
VIA_MAX: Final = 60


@dataclass(slots=True)
class Facts:
    events: dict[int, list[sp.Event]] = field(default_factory=lambda: defaultdict(list))
    names: dict[int, str] = field(default_factory=dict)
    """Club (provider id) -> the name a transfer wrote (the name we give a club we hold wins over it, see ``_build_spells``)."""
    nowhere: int = 0
    """Men of a match the squad sheets put on both sides and the statistics do not place: no side is his, so no event."""


def _via(text: Any) -> str | None:
    value = str(text).strip()[:VIA_MAX] if text is not None else ""
    return value or None


def read_facts(conn: psycopg.Connection[Any], players: Sequence[int], teams: dict[int, Team], crossed: AbstractSet[tuple[int, str]]) -> Facts:
    """Every piece of evidence about these players, as events of ``fbi.people.spells``; ``crossed`` are the squad sheets that are the
    other side's (``read_sheets``)."""
    by_provider = {t.provider_id: t for t in teams.values()}
    facts = Facts()

    def club_of(provider_id: int | None) -> int | None:
        """The provider's id of a club, or None for a team that is not known to be one (a national team, an unclassified side)."""
        if provider_id is None or provider_id <= 0:
            return None
        team = by_provider.get(provider_id)
        return provider_id if team is None or team.national is False else None

    def club_by_our_id(team_id: int) -> int | None:
        team = teams.get(team_id)
        return team.provider_id if team is not None and team.national is False else None

    with conn.cursor() as cur:
        cur.execute(TRANSFERS_SQL, {"players": list(players)})
        for player, when, kind, team_in, name_in, team_out, name_out in cur.fetchall():
            via = _via(kind)
            for provider_id, name, event_kind in ((team_out, name_out, "left"), (team_in, name_in, "joined")):
                club = club_of(None if provider_id is None else int(provider_id))
                if club is None:
                    continue
                facts.events[int(player)].append(sp.Event(when, event_kind, club, via=via))
                if name:
                    facts.names.setdefault(club, str(name))
        cur.execute(SHEET_ROWS_SQL, {"players": list(players)})
        sheet = [(int(p), int(m), d, str(s), int(h), int(a)) for p, m, d, s, h, a in cur.fetchall()]
        cur.execute(STAT_ROWS_SQL, {"players": list(players)})
        statistics = [(int(p), int(m), d, str(s), int(h), int(a)) for p, m, d, s, h, a in cur.fetchall()]
        placed, facts.nowhere = placed_matches(sheet, statistics, crossed)
        for player, fixture, day, team_id in placed:
            club = club_by_our_id(team_id)
            if club is not None:
                facts.events[player].append(sp.Event(day, "seen", club, ref=fixture))
        cur.execute(SQUADS_SQL, {"players": list(players)})
        for player, team_id, first, last in cur.fetchall():
            club = club_by_our_id(int(team_id))
            if club is not None:
                facts.events[int(player)].append(sp.Event(first, "squad", club))
                if last != first:
                    facts.events[int(player)].append(sp.Event(last, "squad", club))
    return facts


SpellRow = tuple[int, int, int, str | None, date | None, date | None, str, int, date, str | None, str]
"""(player, ordinal, club, club name, valid_from, valid_to, source, matches, last_evidence, via, version): a row of ``core.player_spells``."""

SPELL_COLUMNS: Final = ("provider_player_id, ordinal, provider_team_id, team_name, valid_from, valid_to, source, matches, "
                        "last_evidence, via, version")


def spell_rows(player: int, built: sp.Build, names: dict[int, str | None]) -> list[SpellRow]:
    return [(player, n, s.club, names.get(s.club), s.valid_from, s.valid_to, s.source, s.matches, s.last_evidence, s.via, sp.VERSION)
            for n, s in enumerate(built.spells)]


def read_stored_spells(conn: psycopg.Connection[Any], players: Sequence[int]) -> dict[int, list[SpellRow]]:
    out: dict[int, list[SpellRow]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {SPELL_COLUMNS} FROM core.player_spells WHERE provider_player_id = ANY(%s) "
                    "ORDER BY provider_player_id, ordinal", (list(players),))
        for row in cur.fetchall():
            out[int(row[0])].append((int(row[0]), int(row[1]), int(row[2]), row[3], row[4], row[5], str(row[6]), int(row[7]), row[8],
                                     row[9], str(row[10])))
    return out


# ── the caps ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

CapRow = tuple[int, int, int, bool, bool | None, int | None, str]
"""(player, fixture, team, starter, appeared, minutes, version): a row of ``core.player_national_caps``."""


def senior_national_ids(teams: dict[int, Team]) -> list[int]:
    return sorted(t.id for t in teams.values() if cp.is_senior_national(t.name, t.national))


FIXTURES_SQL: Final = """
SELECT id, home_team_id, away_team_id, status_group = 'finished' AS finished
  FROM core.fixtures WHERE id = ANY(%(fixtures)s)"""
LINEUP_SQL: Final = """
SELECT fixture_id, team_side, provider_player_id, is_starter FROM core.fixture_lineup_players
 WHERE fixture_id = ANY(%(fixtures)s) AND provider_player_id > 0"""
STATS_SQL: Final = """
SELECT fixture_id, team_side, provider_player_id, minutes, COALESCE(is_substitute, false)
  FROM core.fixture_player_stats WHERE fixture_id = ANY(%(fixtures)s) AND provider_player_id > 0"""


def wanted_caps(conn: psycopg.Connection[Any], fixtures: Sequence[int], senior: set[int],
                crossed: AbstractSet[tuple[int, str]] | None = None) -> list[CapRow]:
    """The caps the facts of these matches give: a finished match of a senior national side, the players of its squad sheet (and
    those only the statistics name), and whether each played. The side of each man is decided as for the streaks
    (``fbi.people.sides``): the statistics win and a squad sheet in ``crossed`` is the other side's (read from the statistics of these
    matches when not given)."""
    if not fixtures:
        return []
    with conn.cursor() as cur:
        cur.execute(FIXTURES_SQL, {"fixtures": list(fixtures)})
        national: dict[tuple[int, str], int] = {}  # (match, "home" | "away") -> the national team on that side, finished matches only
        for fixture, home, away, finished in cur.fetchall():
            for side, team in ((sides.HOME, int(home)), (sides.AWAY, int(away))):
                if finished and team in senior:
                    national[(int(fixture), side)] = team
        if not national:
            return []
        played_in = list({key[0] for key in national})
        if crossed is None:
            crossed = read_sheets(conn, fixtures=played_in).crossed
        on_sheet: dict[tuple[int, int], dict[str, bool]] = defaultdict(dict)  # (match, man) -> {side his sheet puts him on: started}
        cur.execute(LINEUP_SQL, {"fixtures": played_in})
        for fixture, side, player, starter in cur.fetchall():
            turned = sides.other(str(side)) if (int(fixture), str(side)) in crossed else str(side)
            on_sheet[(int(fixture), int(player))][turned] = bool(starter)
        in_statistics: dict[tuple[int, int], dict[str, tuple[int | None, bool]]] = defaultdict(dict)  # (match, man) -> {side: (minutes, sub)}
        cur.execute(STATS_SQL, {"fixtures": played_in})
        for fixture, side, player, mins, substitute in cur.fetchall():
            in_statistics[(int(fixture), int(player))][str(side)] = (None if mins is None else int(mins), bool(substitute))
    squad: dict[tuple[int, str], dict[int, bool]] = defaultdict(dict)
    minutes: dict[tuple[int, str], dict[int, int | None]] = defaultdict(dict)
    for (fixture, player), by_side in in_statistics.items():
        if len(by_side) != 1:
            continue  # the statistics put him on both sides: nothing says which is his
        ((side, (mins, substitute)),) = by_side.items()
        minutes[(fixture, side)][player] = mins
        sheet = on_sheet.get((fixture, player), {})
        if side in sheet:
            started = sheet[side]
        elif len(sheet) == 1:
            started = next(iter(sheet.values()))  # his sheet put him on the other side; whether he started is his all the same
        else:
            started = not substitute
        squad[(fixture, side)][player] = started
    for (fixture, player), put_on in on_sheet.items():
        if (fixture, player) in in_statistics or len(put_on) != 1:
            continue  # the statistics place him, or both sheets carry him and the statistics do not say which side is his
        ((side, started),) = put_on.items()
        squad[(fixture, side)][player] = started
    out: list[CapRow] = []
    for key, team in sorted(national.items()):
        has_stats = key in minutes
        for player, starter in sorted(squad.get(key, {}).items()):
            mins = minutes.get(key, {}).get(player)
            played = cp.appeared(is_starter=starter, finished=True, has_stats=has_stats, minutes=mins)
            out.append((player, key[0], team, starter, played, mins if played else None, cp.VERSION))
    return out


CAP_COLUMNS: Final = "provider_player_id, fixture_id, team_id, is_starter, appeared, minutes, version"


def read_stored_caps(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> dict[tuple[int, int], CapRow]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {CAP_COLUMNS} FROM core.player_national_caps WHERE fixture_id = ANY(%s)", (list(fixtures),))
        return {(int(r[0]), int(r[1])): (int(r[0]), int(r[1]), int(r[2]), bool(r[3]), r[4], None if r[5] is None else int(r[5]), str(r[6]))
                for r in cur.fetchall()}


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class BuildReport:
    mode: str = SCHEDULED
    version: str = VERSION
    applied: bool = False
    skipped_locked: bool = False
    seconds: float = 0.0
    players: int = 0
    """Players looked at."""
    players_changed: int = 0
    spells: int = 0
    """Streaks the facts give for the players looked at."""
    spells_written: int = 0
    spells_deleted: int = 0
    phantoms: int = 0
    fixtures: int = 0
    """Matches looked at for caps."""
    caps: int = 0
    caps_written: int = 0
    caps_deleted: int = 0
    caps_open: int = 0
    """Caps of which it cannot be said yet whether he played."""
    sheets_crossed: int = 0
    """Squad sheets the statistics of the same match turn round (the provider gave each team the other's): read as the other side's."""
    sheets_doubtful: int = 0
    """Sheets with a man the statistics put on the other side that were NOT turned round (one man in both sheets, too few in the statistics)."""
    men_nowhere: int = 0
    """Men put on both sides by the squad sheets of a match and not placed by its statistics: no side is his, so they are not counted."""

    @property
    def changed(self) -> bool:
        return bool(self.spells_written or self.spells_deleted or self.caps_written or self.caps_deleted)

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "version": self.version, "applied": self.applied, "skipped_locked": self.skipped_locked,
                "seconds": round(self.seconds, 1), "players": self.players, "players_changed": self.players_changed,
                "spells": self.spells, "spells_written": self.spells_written, "spells_deleted": self.spells_deleted,
                "phantoms": self.phantoms, "fixtures": self.fixtures, "caps": self.caps, "caps_written": self.caps_written,
                "caps_deleted": self.caps_deleted, "caps_open": self.caps_open, "sheets_crossed": self.sheets_crossed,
                "sheets_doubtful": self.sheets_doubtful, "men_nowhere": self.men_nowhere}


def _lock(conn: psycopg.Connection[Any], *, wait: bool) -> bool:
    with conn.cursor() as cur:
        if wait:
            cur.execute(f"SET LOCAL lock_timeout = '{MANUAL_LOCK_WAIT}'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            return True
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        row = cur.fetchone()
        return bool(row and row[0])


def all_players(conn: psycopg.Connection[Any]) -> list[int]:
    """Everyone any fact is about."""
    with conn.cursor() as cur:
        cur.execute("SELECT provider_player_id FROM core.player_transfers WHERE provider_player_id > 0 "
                    "UNION SELECT provider_player_id FROM core.fixture_lineup_players WHERE provider_player_id > 0 "
                    "UNION SELECT provider_player_id FROM core.fixture_player_stats WHERE provider_player_id > 0 "
                    "UNION SELECT provider_player_id FROM core.squad_members WHERE provider_player_id > 0 ORDER BY 1")
        return [int(r[0]) for r in cur.fetchall()]


def recent_players(conn: psycopg.Connection[Any], *, now: datetime, window: timedelta = WINDOW) -> list[int]:
    """The players a fact about changed lately: in the squad sheet or the statistics of a recent match, in a transfer list read lately, or
    newly in a squad list."""
    since = now - window
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.provider_player_id FROM core.fixture_lineup_players p JOIN core.fixtures f ON f.id = p.fixture_id
             WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND p.provider_player_id > 0
            UNION SELECT s.provider_player_id FROM core.fixture_player_stats s JOIN core.fixtures f ON f.id = s.fixture_id
             WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND s.provider_player_id > 0
            UNION SELECT provider_player_id FROM core.player_transfers WHERE observed_at >= %(since)s AND provider_player_id > 0
            UNION SELECT provider_player_id FROM core.squad_members WHERE first_seen_at >= %(since)s AND provider_player_id > 0
            ORDER BY 1""", {"since": since, "until": now + timedelta(days=1)})
        return [int(r[0]) for r in cur.fetchall()]


def _batches(items: Sequence[int], size: int) -> Iterator[Sequence[int]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _build_spells(conn: psycopg.Connection[Any], players: Sequence[int], teams: dict[int, Team], crossed: AbstractSet[tuple[int, str]],
                  report: BuildReport, *, apply: bool) -> None:
    by_provider = {t.provider_id: t.name for t in teams.values()}
    for batch in _batches(players, BATCH):
        facts = read_facts(conn, batch, teams, crossed)
        report.men_nowhere += facts.nowhere
        stored = read_stored_spells(conn, batch)
        delete: list[int] = []
        insert: list[SpellRow] = []
        for player in batch:
            built = sp.build(facts.events.get(player, ()))
            names = {s.club: by_provider.get(s.club) or facts.names.get(s.club) for s in built.spells}
            wanted = spell_rows(player, built, names)
            report.spells += len(wanted)
            report.phantoms += built.phantoms
            current = stored.get(player, [])
            if wanted == current:
                continue
            report.players_changed += 1
            report.spells_deleted += len(current)
            report.spells_written += len(wanted)
            delete.append(player)
            insert.extend(wanted)
        report.players += len(batch)
        if apply and delete:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM core.player_spells WHERE provider_player_id = ANY(%s)", (delete,))
                if insert:
                    cur.executemany(f"INSERT INTO core.player_spells ({SPELL_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                    insert)


def recent_cap_fixtures(conn: psycopg.Connection[Any], senior: Sequence[int], *, now: datetime, window: timedelta = WINDOW) -> list[int]:
    """The matches of senior national sides whose caps may still change: played lately, or with a cap waiting for the statistics."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM core.fixtures
             WHERE kickoff_at >= %(since)s AND kickoff_at < %(until)s AND (home_team_id = ANY(%(senior)s) OR away_team_id = ANY(%(senior)s))
            UNION SELECT fixture_id FROM core.player_national_caps WHERE appeared IS NULL
            ORDER BY 1""", {"since": now - window, "until": now + timedelta(days=1), "senior": list(senior)})
        return [int(r[0]) for r in cur.fetchall()]


def all_cap_fixtures(conn: psycopg.Connection[Any], senior: Sequence[int]) -> list[int]:
    """Every match that has caps or could have them."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM core.fixtures WHERE status_group = 'finished' AND (home_team_id = ANY(%(senior)s) OR away_team_id = ANY(%(senior)s))
            UNION SELECT fixture_id FROM core.player_national_caps
            ORDER BY 1""", {"senior": list(senior)})
        return [int(r[0]) for r in cur.fetchall()]


def _build_caps(conn: psycopg.Connection[Any], fixtures: Sequence[int], teams: dict[int, Team], crossed: AbstractSet[tuple[int, str]],
                report: BuildReport, *, apply: bool) -> None:
    senior = senior_national_ids(teams)
    senior_set = set(senior)
    for batch in _batches(fixtures, CAP_BATCH):
        wanted = {(r[0], r[1]): r for r in wanted_caps(conn, batch, senior_set, crossed)}
        stored = read_stored_caps(conn, batch)
        gone = [k for k in stored if k not in wanted]
        changed = [r for k, r in wanted.items() if stored.get(k) != r]
        report.fixtures += len(batch)
        report.caps += len(wanted)
        report.caps_open += sum(1 for r in wanted.values() if r[4] is None)
        report.caps_written += len(changed)
        report.caps_deleted += len(gone)
        if not apply:
            continue
        with conn.cursor() as cur:
            if gone:
                cur.executemany("DELETE FROM core.player_national_caps WHERE provider_player_id = %s AND fixture_id = %s", gone)
            if changed:
                cur.executemany(
                    f"INSERT INTO core.player_national_caps ({CAP_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (provider_player_id, fixture_id) DO UPDATE SET team_id = EXCLUDED.team_id, "
                    "is_starter = EXCLUDED.is_starter, appeared = EXCLUDED.appeared, minutes = EXCLUDED.minutes, "
                    "version = EXCLUDED.version, built_at = now()", changed)


def build(conn: psycopg.Connection[Any], *, apply: bool = False, wait: bool = False, sweep: bool = False,
          players: Sequence[int] | None = None, now: datetime | None = None) -> BuildReport:
    """One pass. Without ``apply`` nothing is written and the report says what would be. ``sweep`` looks at everyone and every match;
    otherwise only at what changed lately. ``players`` restricts the streaks to those players (and skips the caps). ``wait`` takes the
    lock and waits for it (a person at the console); the worker does not wait: when another pass is writing it returns
    ``skipped_locked``."""
    started = time.monotonic()
    report = BuildReport(mode=SWEEP if sweep else SCHEDULED, applied=apply)
    moment = now or datetime.now(UTC)
    with conn.transaction():
        if apply and not _lock(conn, wait=wait):
            report.skipped_locked = True
            report.applied = False
            return report
        teams = read_teams(conn)
        if players is not None:
            who = sorted({p for p in players if p > 0})
        else:
            who = all_players(conn) if sweep else recent_players(conn, now=moment)
        # which squad sheets are the other side's is a fact about a whole match, so it is read once for the pass: for the matches of
        # the players asked for, else for every match (the players of a pass have their whole careers folded, so they need them all)
        sheets = read_sheets(conn, players=who if players is not None else None)
        report.sheets_crossed, report.sheets_doubtful = len(sheets.crossed), sheets.doubtful
        _build_spells(conn, who, teams, sheets.crossed, report, apply=apply)
        if players is None:
            senior = senior_national_ids(teams)
            fixtures = all_cap_fixtures(conn, senior) if sweep else recent_cap_fixtures(conn, senior, now=moment)
            _build_caps(conn, fixtures, teams, sheets.crossed, report, apply=apply)
    report.seconds = time.monotonic() - started
    return report


# ── reading it back ──────────────────────────────────────────────────────────────────────────────────────────────────────


def spells_of(conn: psycopg.Connection[Any], players: Sequence[int]) -> dict[int, list[sp.Spell]]:
    """The streaks of these players, oldest first."""
    out: dict[int, list[sp.Spell]] = defaultdict(list)
    for player, rows in read_stored_spells(conn, players).items():
        out[player] = [sp.Spell(club=r[2], valid_from=r[4], valid_to=r[5], source=r[6], matches=r[7], last_evidence=r[8], via=r[9])
                       for r in rows]
    return out


def spell_names(conn: psycopg.Connection[Any], players: Sequence[int]) -> dict[int, str]:
    """Club (provider id) -> the name stored with the streaks of these players."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT provider_team_id, team_name FROM core.player_spells "
                    "WHERE provider_player_id = ANY(%s) AND team_name IS NOT NULL", (list(players),))
        return {int(i): str(n) for i, n in cur.fetchall()}


def caps_of(conn: psycopg.Connection[Any], players: Sequence[int], *, before: datetime | None = None,
            settled_by: datetime | None = None) -> dict[int, list[cp.Cap]]:
    """The national-team squad entries of these players, newest first - those before ``before`` when it is given (the kick-off of the
    match a dossier is for) and, with ``settled_by``, of matches whose result was recorded by then (the moment of a packet)."""
    out: dict[int, list[cp.Cap]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT c.provider_player_id, c.fixture_id, f.kickoff_at, c.team_id, c.is_starter, c.appeared, c.minutes "
                    "FROM core.player_national_caps c JOIN core.fixtures f ON f.id = c.fixture_id "
                    "WHERE c.provider_player_id = ANY(%(players)s) AND (%(before)s::timestamptz IS NULL OR f.kickoff_at < %(before)s) "
                    "AND (%(settled)s::timestamptz IS NULL OR EXISTS (SELECT 1 FROM core.fixture_results r "
                    "WHERE r.fixture_id = c.fixture_id AND r.settled_at <= %(settled)s)) "
                    "ORDER BY c.provider_player_id, f.kickoff_at DESC, c.fixture_id DESC",
                    {"players": list(players), "before": before, "settled": settled_by})
        for player, fixture, kickoff, team, starter, played, minutes in cur.fetchall():
            out[int(player)].append(cp.Cap(fixture_id=int(fixture), kickoff=kickoff, team_id=int(team), is_starter=bool(starter),
                                           appeared=None if played is None else bool(played),
                                           minutes=None if minutes is None else int(minutes)))
    return out


# ── the figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────

COUNTS: Final = (
    ("players_with_spells", "SELECT count(DISTINCT provider_player_id) FROM core.player_spells"),
    ("spells", "SELECT count(*) FROM core.player_spells"),
    ("spells_open", "SELECT count(*) FROM core.player_spells WHERE valid_to IS NULL"),
    ("spells_out_of_order", """
        SELECT count(*) FROM (SELECT valid_to, lead(valid_from) OVER (PARTITION BY provider_player_id ORDER BY ordinal) AS nxt
                                FROM core.player_spells) x
         WHERE nxt IS NOT NULL AND (valid_to IS NULL OR valid_to > nxt)"""),
    ("spells_of_another_version", f"SELECT count(*) FROM core.player_spells WHERE version <> '{sp.VERSION}'"),
    ("caps", "SELECT count(*) FROM core.player_national_caps"),
    ("caps_players", "SELECT count(DISTINCT provider_player_id) FROM core.player_national_caps"),
    ("caps_fixtures", "SELECT count(DISTINCT fixture_id) FROM core.player_national_caps"),
    ("caps_open", "SELECT count(*) FROM core.player_national_caps WHERE appeared IS NULL"),
    ("caps_of_unfinished_matches", """
        SELECT count(*) FROM core.player_national_caps c JOIN core.fixtures f ON f.id = c.fixture_id WHERE f.status_group <> 'finished'"""),
    ("caps_of_another_version", f"SELECT count(*) FROM core.player_national_caps WHERE version <> '{cp.VERSION}'"),
    ("lone_stints", """
        SELECT count(*) FROM (SELECT source, matches, provider_team_id,
                                     lag(provider_team_id) OVER w AS club_before, lead(provider_team_id) OVER w AS club_after
                                FROM core.player_spells WINDOW w AS (PARTITION BY provider_player_id ORDER BY ordinal)) x
         WHERE source = 'lineup' AND matches = 1 AND club_before = club_after AND club_before <> provider_team_id"""),
)
"""``lone_stints`` is not an invariant but a smell: a streak that one squad sheet opened and one match filled, between two streaks at the
same club (A, B for a single match, A again). A real loan nobody recorded looks like that, and so does a match whose squad sheet the
provider gave to the wrong team and whose statistics do not exist to say so (``fbi.people.sides``): the audit counts them so that
the residue of that mistake is a number and not a suspicion."""
INVARIANTS: Final = ("spells_out_of_order", "caps_of_unfinished_matches", "caps_of_youth_sides", "caps_of_other_sides")
"""Counts that must be zero: streaks that overlap or leave a gap-less open end before another, caps of a match not played, caps of a
youth side or of a team that is not a national one."""


def counts(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """The figures of the tables, cheap: no pass is simulated (``audit`` adds what a pass would write)."""
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for name, sql in COUNTS:
            cur.execute(sql)
            row = cur.fetchone()
            out[name] = int(row[0]) if row else 0
        cur.execute("SELECT source, count(*) FROM core.player_spells GROUP BY source")
        out["spells_by_source"] = {str(s): int(n) for s, n in cur.fetchall()}
        cur.execute("SELECT c.team_id, t.name, COALESCE(k.is_national, t.is_national), count(*) FROM core.player_national_caps c "
                    "JOIN core.teams t ON t.id = c.team_id LEFT JOIN core.team_kind k ON k.team_id = t.id GROUP BY 1, 2, 3")
        youth = other = 0
        for _, name, national, n in cur.fetchall():
            if national is not True:
                other += int(n)
            elif cp.is_youth(str(name)):
                youth += int(n)
        out["caps_of_youth_sides"], out["caps_of_other_sides"] = youth, other
        # a streak whose start is unknown compares as NULL with the day of the match: it says nothing about where he was
        cur.execute("""
            SELECT count(*), count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM core.player_spells s WHERE s.provider_player_id = c.provider_player_id
                          AND s.valid_from <= (f.kickoff_at AT TIME ZONE 'UTC')::date
                          AND (s.valid_to IS NULL OR (f.kickoff_at AT TIME ZONE 'UTC')::date < s.valid_to)))
              FROM core.player_national_caps c JOIN core.fixtures f ON f.id = c.fixture_id
             WHERE f.kickoff_at >= now() - interval '365 days'""")
        row = cur.fetchone()
    out["recent_caps"], out["recent_caps_with_a_club"] = (int(row[0]), int(row[1])) if row else (0, 0)
    out["recent_club_known_share"] = round(out["recent_caps_with_a_club"] / out["recent_caps"], 4) if out["recent_caps"] else 1.0
    return out


def broken_invariants(figures: dict[str, Any]) -> list[str]:
    """The invariants that do not hold in ``figures`` (an audit or ``counts``); empty when all is well."""
    return [name for name in INVARIANTS if figures[name]]


def audit(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """The state of the tables, read from the database, and what a pass over everything would still write (it must be nothing)."""
    out = counts(conn)
    pending = build(conn, apply=False, sweep=True)
    out["pass_would_write"] = {"spells": pending.spells_written, "spells_deleted": pending.spells_deleted,
                               "caps": pending.caps_written, "caps_deleted": pending.caps_deleted}
    out["phantoms"] = pending.phantoms
    out["sheets_crossed"], out["sheets_doubtful"], out["men_nowhere"] = pending.sheets_crossed, pending.sheets_doubtful, pending.men_nowhere
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(DISTINCT p.fixture_id) FROM core.fixture_lineup_players p JOIN core.fixtures f ON f.id = p.fixture_id
             WHERE f.status_group = 'finished' AND NOT EXISTS (SELECT 1 FROM core.fixture_player_stats s WHERE s.fixture_id = p.fixture_id)""")
        row = cur.fetchone()
    out["fixtures_with_sheets_only"] = int(row[0]) if row else 0
    return out

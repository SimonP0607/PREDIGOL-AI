"""What the player engine knows at a moment: the played matches of every player, in time order, and nothing known later.

THE FACTS
---------
One ``PlayerMatch`` per man in the statistics of a played match (``core.fixture_player_stats``): his side (the statistics win over the
squad sheet, ``fbi.people.sides``), whether he started (``is_substitute`` of the statistics, else ``is_starter`` of his sheet), his
minutes (0 or NULL: on the sheet, did not play) and his counts. A match side with no statistics is not a covered match of that team: it
says nothing about who started.

WHEN A MATCH IS KNOWN (strict as-of)
------------------------------------
A played match is in the view at moment ``t`` when ``available_at <= t``, with

    available_at = max(kickoff + 3 h, min(fetched_at, kickoff + 48 h))

``fetched_at`` is the newest read of the statistics; the post-match job reads every match again about 26 hours after kick-off, which
moves it, so a read later than 48 hours after kick-off is taken as a re-read (or a backfill) of statistics that existed by then. The
statistics of a match therefore never enter before it ended, and a match read late enters when it was read, up to two days.

The confirmed line-up of a match to come counts at ``t`` only when its row was fetched by ``t`` (``core.fixture_lineups.fetched_at``):
a later re-read moves that time forward, so the rule can only hide a line-up that was known, never show one that was not. An absence
is the newest row of ``core.player_availability_obs`` with ``observed_at <= t`` (LISTED: named; CLEARED: no longer named).

``History`` is the in-memory view: matches are added when they become known and every question is asked of what has been added.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.players.families import STATS

SOURCE: Final = "api-football"
MATCH_LENGTH: Final = timedelta(hours=3)
REREAD_AFTER: Final = timedelta(hours=48)
POSITIONS: Final = ("G", "D", "M", "F")
UNKNOWN_POSITION: Final = "?"
_PLAYER_POSITIONS: Final = {"goalkeeper": "G", "defender": "D", "midfielder": "M", "attacker": "F", "forward": "F"}

_STAT_INDEX: Final = {s: i for i, s in enumerate(STATS)}
OUT: Final = "OUT"
DOUBTFUL: Final = "DOUBTFUL"
_OUT_TYPES: Final = {"missing fixture"}
"""API-Football's two absence types are ``Missing Fixture`` (out) and ``Questionable`` (doubtful); an unknown type is read as doubtful,
which only feeds a feature of the start model, never a rule."""


def position_of(sheet: str | None, profile: str | None) -> str:
    """G/D/M/F from the squad sheet (``G``, ``D``, ``M``, ``F``), else from the player's profile (``Goalkeeper``...), else unknown."""
    if sheet and sheet.strip().upper()[:1] in POSITIONS:
        return sheet.strip().upper()[:1]
    if profile:
        return _PLAYER_POSITIONS.get(profile.strip().lower(), UNKNOWN_POSITION)
    return UNKNOWN_POSITION


def absence_status(absence_type: str | None) -> str:
    return OUT if (absence_type or "").strip().lower() in _OUT_TYPES else DOUBTFUL


def available_at(kickoff: datetime, fetched_at: datetime) -> datetime:
    return max(kickoff + MATCH_LENGTH, min(fetched_at, kickoff + REREAD_AFTER))


@dataclass(frozen=True, slots=True)
class PlayerMatch:
    player_id: int
    side: str
    started: bool
    minutes: int
    """0 when he was on the sheet and did not play (the provider's NULL minutes)."""
    position: str
    counts: tuple[int | None, ...]
    """One count per ``STATS``, in that order (a tuple, not a dict: a year of every league is millions of these)."""

    @staticmethod
    def make(player_id: int, side: str, started: bool, minutes: int, position: str, stats: Mapping[str, int | None]) -> PlayerMatch:
        return PlayerMatch(player_id, side, started, minutes, position, tuple(stats.get(s) for s in STATS))

    def count(self, stat: str) -> int | None:
        return self.counts[_STAT_INDEX[stat]]

    @property
    def played(self) -> bool:
        return self.minutes > 0


@dataclass(frozen=True, slots=True)
class Match:
    fixture_id: int
    kickoff: datetime
    competition_id: int
    home_team_id: int
    away_team_id: int
    available_at: datetime
    lines: tuple[PlayerMatch, ...]

    def team(self, side: str) -> int:
        return self.home_team_id if side == "home" else self.away_team_id

    def sides(self) -> tuple[str, ...]:
        return tuple(s for s in ("home", "away") if any(p.side == s for p in self.lines))


@dataclass(slots=True)
class TeamMatch:
    """One covered match of a team: its men and its totals, for and against, with the minutes behind them by position."""

    fixture_id: int
    kickoff: datetime
    opponent_id: int
    men: dict[int, PlayerMatch]
    for_y: dict[str, int] = field(default_factory=dict)
    for_min90: dict[str, dict[str, float]] = field(default_factory=dict)
    against_y: dict[str, int] = field(default_factory=dict)
    against_min90: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Appearance:
    kickoff: datetime
    fixture_id: int
    team_id: int
    opponent_id: int
    line: PlayerMatch


def _totals(lines: Iterable[PlayerMatch]) -> tuple[dict[str, int], dict[str, dict[str, float]]]:
    y: dict[str, int] = defaultdict(int)
    m90: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in lines:
        if not p.played:
            continue
        for stat in STATS:
            v = p.count(stat)
            if v is not None:
                y[stat] += v
                m90[stat][p.position] += p.minutes / 90.0
    return dict(y), {k: dict(v) for k, v in m90.items()}


class History:
    """The played matches known so far, by team and by player, each list in kick-off order, and the running totals by position."""

    def __init__(self) -> None:
        self.team_matches: dict[int, list[TeamMatch]] = defaultdict(list)
        self.appearances: dict[int, list[Appearance]] = defaultdict(list)
        self.pos_y: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.pos_min90: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.pos_start_minutes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self.pos_sub_minutes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self.pos_bench: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        """[came on, on the bench] by position."""
        self.pos_events: dict[tuple[str, str, float], list[float]] = defaultdict(lambda: [0.0, 0.0])
        """(stat, position, line) -> [starters over the line, starters with the stat]: the naive baseline."""
        self.matches = 0
        self.latest: datetime | None = None
        self.memo: dict[tuple[str | int, ...], float] = {}
        """Answers derived from the history (position rates, team factors), forgotten whenever a match is added."""

    def add(self, match: Match, lines_by_stat: Mapping[str, Sequence[float]]) -> None:
        """Add a played match that became known. ``lines_by_stat`` are the lines the baseline counts."""
        self.matches += 1
        self.memo.clear()
        self.latest = match.available_at if self.latest is None else max(self.latest, match.available_at)
        for side in match.sides():
            team, opponent = match.team(side), match.team("away" if side == "home" else "home")
            mine = [p for p in match.lines if p.side == side]
            theirs = [p for p in match.lines if p.side != side]
            fy, fm = _totals(mine)
            ay, am = _totals(theirs)
            tm = TeamMatch(match.fixture_id, match.kickoff, opponent, {p.player_id: p for p in mine}, fy, fm, ay, am)
            bisect.insort(self.team_matches[team], tm, key=lambda x: (x.kickoff, x.fixture_id))
            for p in mine:
                bisect.insort(self.appearances[p.player_id], Appearance(match.kickoff, match.fixture_id, team, opponent, p),
                              key=lambda a: (a.kickoff, a.fixture_id))
                self._count(p, lines_by_stat)

    def _count(self, p: PlayerMatch, lines_by_stat: Mapping[str, Sequence[float]]) -> None:
        pos = p.position
        if p.played:
            for stat in STATS:
                v = p.count(stat)
                if v is not None:
                    self.pos_y[stat][pos] += v
                    self.pos_min90[stat][pos] += p.minutes / 90.0
        if p.started and p.played:
            acc = self.pos_start_minutes[pos]
            acc[0] += p.minutes
            acc[1] += 1
            for stat, lines in lines_by_stat.items():
                v = p.count(stat)
                if v is None:
                    continue
                for line in lines:
                    ev = self.pos_events[(stat, pos, line)]
                    ev[0] += 1.0 if v > line else 0.0
                    ev[1] += 1.0
        elif not p.started:
            bench = self.pos_bench[pos]
            bench[1] += 1
            if p.played:
                bench[0] += 1
                sub = self.pos_sub_minutes[pos]
                sub[0] += p.minutes
                sub[1] += 1

    def recent_team(self, team_id: int, k: int) -> list[TeamMatch]:
        """The team's last ``k`` covered matches, newest first."""
        return self.team_matches.get(team_id, [])[-k:][::-1]

    def recent_apps(self, player_id: int, k: int) -> list[Appearance]:
        """The player's last ``k`` appearances on a sheet (played or not), newest first."""
        return self.appearances.get(player_id, [])[-k:][::-1]

    def last_team(self, player_id: int) -> int | None:
        apps = self.appearances.get(player_id)
        return apps[-1].team_id if apps else None

    def position(self, player_id: int, hint: str = UNKNOWN_POSITION) -> str:
        """The position he was listed in most often in his last ten sheets; ``hint`` (today's sheet) wins when it is known."""
        if hint in POSITIONS:
            return hint
        counts: dict[str, int] = defaultdict(int)
        for a in self.recent_apps(player_id, 10):
            if a.line.position in POSITIONS:
                counts[a.line.position] += 1
        return max(counts, key=lambda p: (counts[p], p)) if counts else UNKNOWN_POSITION


# ── the reads ────────────────────────────────────────────────────────────────────────────────────────────────────────────

ROWS_SQL: Final = """
SELECT f.id, f.kickoff_at, cs.competition_id, f.home_team_id, f.away_team_id,
       s.provider_player_id, s.team_side, s.minutes, s.is_substitute, l.is_starter, l.position, p.position,
       s.goals, s.assists, s.shots_total, s.shots_on, s.fouls_committed, s.yellow_cards, s.red_cards, s.saves, s.fetched_at
  FROM core.fixture_player_stats s
  JOIN core.fixtures f ON f.id = s.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  LEFT JOIN LATERAL (SELECT lp.is_starter, lp.position FROM core.fixture_lineup_players lp
                      WHERE lp.fixture_id = s.fixture_id AND lp.source = s.source AND lp.provider_player_id = s.provider_player_id
                      ORDER BY (lp.team_side = s.team_side) DESC LIMIT 1) l ON true
  LEFT JOIN core.players p ON p.provider_player_id = s.provider_player_id
 WHERE s.source = 'api-football' AND s.provider_player_id > 0 AND f.status_group = 'finished'
   AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND {scope}
 ORDER BY f.kickoff_at, f.id"""
"""Every man in the statistics of the played matches of a window. The squad sheet of the same side is preferred (a man listed in both
sheets of his match, ``fbi.people.sides``)."""

SCOPES: Final = {
    "all": "true",
    "competitions": "cs.competition_id = ANY(%(competitions)s)",
    "around": "(cs.competition_id = ANY(%(competitions)s) OR f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s))",
}


def _count(v: Any) -> int | None:
    return None if v is None else int(v)


def load_matches(conn: psycopg.Connection[Any], start: datetime, end: datetime, *, competitions: Sequence[int] | None = None,
                 teams: Sequence[int] | None = None) -> list[Match]:
    """The played matches that kicked off in ``[start, end)`` with player statistics, in kick-off order. ``competitions`` limits them;
    with ``teams`` too, every match of those teams is read as well (their cups, their other league)."""
    scope = "all" if not competitions else ("around" if teams else "competitions")
    params: dict[str, Any] = {"start": start, "end": end, "competitions": list(competitions or ()), "teams": list(teams or ())}
    out: list[Match] = []
    current: list[Any] | None = None
    lines: list[PlayerMatch] = []
    fetched: datetime | None = None
    with conn.cursor() as cur:
        cur.execute(ROWS_SQL.format(scope=SCOPES[scope]), params)
        for r in cur:
            if current is None or current[0] != r[0]:
                if current is not None and fetched is not None:
                    out.append(_match(current, lines, fetched))
                current, lines, fetched = list(r[:5]), [], None
            (_pid, side, minutes, is_sub, is_starter, sheet_pos, profile_pos, goals, assists, shots, shots_on, fouls, yellow, red,
             saves, fetched_at) = r[5:]
            started = (not bool(is_sub)) if is_sub is not None else bool(is_starter)
            mins = int(minutes or 0)
            cards = None if yellow is None and red is None else int(yellow or 0) + int(red or 0)
            stats = {"goals": _count(goals), "assists": _count(assists), "shots": _count(shots), "shots_on": _count(shots_on),
                     "fouls": _count(fouls), "cards": cards, "saves": _count(saves)}
            lines.append(PlayerMatch.make(int(r[5]), str(side), started and mins > 0, mins, position_of(sheet_pos, profile_pos), stats))
            fetched = fetched_at if fetched is None else max(fetched, fetched_at)
    if current is not None and fetched is not None:
        out.append(_match(current, lines, fetched))
    return out


def _match(head: Sequence[Any], lines: Sequence[PlayerMatch], fetched: datetime) -> Match:
    fid, ko, comp, home, away = head
    return Match(int(fid), ko, int(comp), int(home), int(away), available_at(ko, fetched), tuple(lines))


@dataclass(frozen=True, slots=True)
class Fixture:
    fixture_id: int
    kickoff: datetime
    competition_id: int
    home_team_id: int
    away_team_id: int
    home_name: str
    away_name: str
    status_group: str


def read_fixture(conn: psycopg.Connection[Any], fixture_id: int) -> Fixture | None:
    with conn.cursor() as cur:
        cur.execute("SELECT f.id, f.kickoff_at, cs.competition_id, f.home_team_id, f.away_team_id, h.name, a.name, f.status_group "
                    "FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                    "JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id WHERE f.id = %s",
                    (fixture_id,))
        r = cur.fetchone()
    if r is None:
        return None
    return Fixture(int(r[0]), r[1], int(r[2]), int(r[3]), int(r[4]), str(r[5]), str(r[6]), str(r[7]))


@dataclass(frozen=True, slots=True)
class SheetLine:
    player_id: int
    name: str | None
    position: str
    is_starter: bool


def confirmed_lineup(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> dict[str, list[SheetLine]]:
    """The squad sheets of a match that were fetched by ``at``, by side (a side missing: not confirmed by then)."""
    out: dict[str, list[SheetLine]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT l.team_side, lp.provider_player_id, lp.player_name, lp.position, lp.is_starter, p.position "
                    "FROM core.fixture_lineups l JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id "
                    "AND lp.team_side = l.team_side AND lp.source = l.source "
                    "LEFT JOIN core.players p ON p.provider_player_id = lp.provider_player_id "
                    "WHERE l.fixture_id = %s AND l.source = %s AND l.fetched_at <= %s AND lp.provider_player_id > 0 "
                    "ORDER BY l.team_side, NOT lp.is_starter, lp.provider_player_id", (fixture_id, SOURCE, at))
        for side, pid, name, pos, starter, profile in cur.fetchall():
            out.setdefault(str(side), []).append(SheetLine(int(pid), name, position_of(pos, profile), bool(starter)))
    return out


ABSENCES_SQL: Final = """
SELECT DISTINCT ON (o.fixture_id, o.provider_player_id) o.fixture_id, o.provider_player_id, o.status, o.absence_type, o.observed_at
  FROM core.player_availability_obs o
 WHERE o.fixture_id = ANY(%(fixtures)s) AND o.source = 'api-football' AND o.observed_at <= %(at)s
 ORDER BY o.fixture_id, o.provider_player_id, o.observed_at DESC"""


def absences_as_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> dict[int, str]:
    """The players the newest answer by ``at`` named for the match: OUT or DOUBTFUL (a CLEARED one is not listed)."""
    with conn.cursor() as cur:
        cur.execute(ABSENCES_SQL, {"fixtures": [fixture_id], "at": at})
        return {int(pid): absence_status(kind) for _f, pid, status, kind, _o in cur.fetchall() if status == "LISTED"}


Observation = tuple[datetime, str, str | None]
"""(observed_at, LISTED or CLEARED, absence type)."""


def absence_history(conn: psycopg.Connection[Any], fixtures: Sequence[int]) -> dict[tuple[int, int], list[Observation]]:
    """Every recorded change of availability for these matches, by (match, player), oldest first: the backtest asks it as of a moment."""
    out: dict[tuple[int, int], list[Observation]] = defaultdict(list)
    if not fixtures:
        return out
    with conn.cursor() as cur:
        cur.execute("SELECT fixture_id, provider_player_id, observed_at, status, absence_type FROM core.player_availability_obs "
                    "WHERE fixture_id = ANY(%s) AND source = 'api-football' ORDER BY observed_at", (list(fixtures),))
        for fid, pid, at, status, kind in cur.fetchall():
            out[(int(fid), int(pid))].append((at, str(status), kind))
    return out


def absences_at(history: Mapping[tuple[int, int], Sequence[Observation]], fixture_id: int, players: Iterable[int],
                at: datetime) -> dict[int, str]:
    """``absences_as_of`` over the rows of ``absence_history``: the newest observation by ``at`` per player, the LISTED ones."""
    out: dict[int, str] = {}
    for pid in players:
        state: Observation | None = None
        for obs in history.get((fixture_id, pid), ()):
            if obs[0] <= at:
                state = obs
            else:
                break
        if state is not None and state[1] == "LISTED":
            out[pid] = absence_status(state[2])
    return out

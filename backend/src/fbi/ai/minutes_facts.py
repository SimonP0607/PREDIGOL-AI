"""The minutes of the usual starters and the probable rotation of a side, said as calculated context facts (plan RP-4.3, second tranche, ``minutes-facts-v1``).

They ride on the switch of the first tranche (``FBI_CALENDAR_FACTS``, ``fbi.ai.calendar_facts``): nothing new to turn on and no new scheduler hook. Both are
PRIVATE and enter no probability: their effect is unproven (the registry of factors holds them as descriptive, RP-4.5).

WHAT IS SAID, for a side, from the line-ups and the player statistics PrediGol holds of the matches the team played before the one under study:

* the minutes of its USUAL STARTERS in the 14 days before the match. A usual starter is a player who started at least 60 % (and never fewer than two) of the
  team's last five matches with a full line-up of eleven; the team needs at least three such matches or nothing is said. The fact gives how many usual
  starters there are, in how many matches, the average of their minutes and how many of them played 180 minutes or more: a count, never «llega cansado».
* a PROBABLE ROTATION. It is said only when the match comes 4 days or less after the previous one AND the team's own history shows the pattern: over the
  consecutive pairs of matches with a full line-up in the last 180 days, in at least three pairs 4 days or less apart and at least three more apart than
  that, it repeated on average at least 1,5 starters fewer of the previous match when the rest was short. Its calculation is in the fact. It can only ever
  be ``informacion_probable`` (``certainty = "probable"``: a regularity of the history, not an announced line-up) and never a confirmed fact.

A side with nothing to say produces no fact: the absence is counted by the caller and never filled in. Only matches with ``status_group = 'finished'`` that
kicked off before the moment asked are read, so the numbers are those of the moment (no leak). 0 requests.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "minutes-facts-v1"
TABLES: Final = ("core.fixtures", "core.fixture_lineup_players", "core.fixture_player_stats")
SOURCE_NAME: Final = "PrediGol · alineaciones y minutos registrados (minutes-facts-v1)"
FULL_LINEUP: Final = 11
RECENT_MATCHES: Final = 5
MIN_LINEUPS: Final = 3
USUAL_SHARE: Final = 0.6
FORTNIGHT: Final = timedelta(days=14)
HISTORY: Final = timedelta(days=180)
HEAVY_MINUTES: Final = 180
SHORT_REST: Final = timedelta(days=4)
MIN_PAIRS: Final = 3
DROP: Final = 1.5
"""How many starters fewer of the previous match the team repeats, on average, after a short rest for the history to count as a rotation pattern."""
MAX_CLAIM: Final = 560
RULE: Final = ("Minutos de los titulares habituales en los 14 días anteriores y rotación probable según el historial propio del equipo: hechos y "
               "regularidades calculados, no una alineación anunciada ni un juicio sobre el estado físico.")

APPEARANCES_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, lp.provider_player_id AS player, bool_or(lp.is_starter) AS starter, max(ps.minutes) AS minutes
  FROM core.fixtures f
  JOIN core.fixture_lineup_players lp ON lp.fixture_id = f.id
   AND lp.team_side = CASE WHEN f.home_team_id = %(team)s THEN 'home' ELSE 'away' END
  LEFT JOIN core.fixture_player_stats ps ON ps.fixture_id = lp.fixture_id AND ps.team_side = lp.team_side
   AND ps.provider_player_id = lp.provider_player_id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.status_group = 'finished'
   AND f.kickoff_at < %(before)s AND f.kickoff_at >= %(since)s
 GROUP BY f.id, f.kickoff_at, lp.provider_player_id
 ORDER BY f.kickoff_at, f.id
"""


@dataclass(frozen=True, slots=True)
class Game:
    """A played match of the team as its line-up and the statistics record it."""

    fixture_id: int
    kickoff_at: datetime
    starters: frozenset[int]
    minutes: Mapping[int, int]
    """The minutes of each player with a statistics row; a player with no row is absent (unknown, not zero)."""

    @property
    def full(self) -> bool:
        return len(self.starters) == FULL_LINEUP

    @property
    def has_minutes(self) -> bool:
        return bool(self.minutes)


@dataclass(frozen=True, slots=True)
class Derived:
    """One fact before it is an item of evidence: whom it is about is the caller's."""

    kind: str
    claim_type: str
    story: str
    claim: str
    calculation: Mapping[str, Any]
    certainty: str | None = None


def games_of(rows: Iterable[Mapping[str, Any]]) -> list[Game]:
    """The rows of ``APPEARANCES_SQL`` grouped by match, in kick-off order. Pure."""
    by: dict[int, tuple[datetime, set[int], dict[int, int]]] = {}
    for r in rows:
        _, starters, minutes = by.setdefault(int(r["fixture_id"]), (r["kickoff_at"], set(), {}))
        if r["starter"]:
            starters.add(int(r["player"]))
        if r["minutes"] is not None:
            minutes[int(r["player"])] = int(r["minutes"])
    return [Game(fid, k, frozenset(s), dict(m)) for fid, (k, s, m) in sorted(by.items(), key=lambda kv: (kv[1][0], kv[0]))]


def load(conn: psycopg.Connection[Any], *, team_id: int, at: datetime, kickoff: datetime) -> list[Game]:
    """The team's finished matches that kicked off in the 180 days before the match (and before the moment asked), with their line-ups."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(APPEARANCES_SQL, {"team": team_id, "before": min(at, kickoff), "since": kickoff - HISTORY}).fetchall()
    return games_of(rows)


def _comma(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def usual_starters(games: Sequence[Game], kickoff: datetime) -> tuple[frozenset[int], list[Game]] | None:
    """The usual starters and the matches that say so, or None when the team has fewer than three matches with a full line-up before the match."""
    recent = [g for g in games if g.full and g.kickoff_at < kickoff][-RECENT_MATCHES:]
    if len(recent) < MIN_LINEUPS:
        return None
    needed = max(2, math.ceil(USUAL_SHARE * len(recent)))
    starts = Counter(p for g in recent for p in g.starters)
    return frozenset(p for p, n in starts.items() if n >= needed), recent


def minutes_fact(games: Sequence[Game], kickoff: datetime, name: str) -> Derived | None:
    """The minutes of the usual starters in the 14 days before the match, or None when there is nothing to say (no usual starters, no match of the fortnight
    with statistics)."""
    usual = usual_starters(games, kickoff)
    if usual is None:
        return None
    players, recent = usual
    window = [g for g in games if kickoff - FORTNIGHT <= g.kickoff_at < kickoff and g.has_minutes]
    if not players or not window:
        return None
    totals = sorted(sum(g.minutes.get(p, 0) for g in window) for p in players)
    mean = sum(totals) / len(totals)
    heavy = sum(1 for t in totals if t >= HEAVY_MINUTES)
    claim = (f"{name}: sus {len(players)} titulares habituales (los que abrieron al menos {max(2, math.ceil(USUAL_SHARE * len(recent)))} de sus últimos "
             f"{len(recent)} partidos) sumaron {_comma(mean)} minutos de media en los 14 días anteriores, en {len(window)} partido"
             f"{'' if len(window) == 1 else 's'} con estadísticas; {heavy} de ellos jugó {HEAVY_MINUTES} minutos o más.")
    calculation = {"version": VERSION, "rule": RULE, "usual_starters": len(players), "matches_for_usual": len(recent),
                   "matches_in_14d": len(window), "mean_minutes": round(mean, 1), "max_minutes": totals[-1], "min_minutes": totals[0],
                   "heavy_180_or_more": heavy, "fixtures_in_14d": [g.fixture_id for g in window]}
    return Derived("schedule", "SCHEDULE", "minutes", claim[:MAX_CLAIM], calculation)


def rotation_fact(games: Sequence[Game], kickoff: datetime, rest_days: float | None, name: str) -> Derived | None:
    """A probable rotation, or None: the rest before the match is 4 days or less and the team's own history shows the pattern (see the module)."""
    if rest_days is None or rest_days > SHORT_REST.total_seconds() / 86400:
        return None
    full = [g for g in games if g.full and g.kickoff_at < kickoff]
    short: list[int] = []
    longer: list[int] = []
    for prev, cur in pairwise(full):
        repeated = len(prev.starters & cur.starters)
        (short if cur.kickoff_at - prev.kickoff_at <= SHORT_REST else longer).append(repeated)
    if len(short) < MIN_PAIRS or len(longer) < MIN_PAIRS:
        return None
    mean_short, mean_long = sum(short) / len(short), sum(longer) / len(longer)
    if mean_long - mean_short < DROP:
        return None
    claim = (f"{name}: rotación probable. En sus {len(short)} partidos anteriores jugados a 4 días o menos del anterior repitió de media "
             f"{_comma(mean_short)} de {FULL_LINEUP} titulares (con más descanso, {_comma(mean_long)} en {len(longer)} partidos); este partido llega "
             f"con {_comma(rest_days)} días de descanso. Es una regularidad de su historial, no una alineación anunciada.")
    calculation = {"version": VERSION, "rule": RULE, "rest_days": round(rest_days, 1), "pairs_short": len(short), "pairs_longer": len(longer),
                   "mean_repeated_short": round(mean_short, 2), "mean_repeated_longer": round(mean_long, 2),
                   "difference": round(mean_long - mean_short, 2), "threshold": DROP, "history_days": int(HISTORY.days)}
    return Derived("rotation", "OTHER", "rotation", claim[:MAX_CLAIM], calculation, certainty="probable")


def facts_of(games: Sequence[Game], kickoff: datetime, rest_days: float | None, name: str) -> list[Derived]:
    """The facts of one side, in a fixed order: the minutes, then the rotation."""
    return [f for f in (minutes_fact(games, kickoff, name), rotation_fact(games, kickoff, rest_days, name)) if f is not None]


__all__ = ["APPEARANCES_SQL", "SOURCE_NAME", "TABLES", "VERSION", "Derived", "Game", "facts_of", "games_of", "load", "minutes_fact", "rotation_fact",
           "usual_starters"]

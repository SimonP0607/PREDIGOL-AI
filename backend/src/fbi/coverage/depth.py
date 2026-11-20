"""How deep the reference goes for each competition (plan PM, PM-04-04; BE-063): its level in the availability matrix and its
editorial priority decide what the reference feeds ask for its teams and people.

* ``completa`` - P0 or P1, or level A or B: everything asked today (squad, coach, transfers, trophies, past absences, missing
  profiles, careers and the provider's season aggregates);
* ``media`` - level C: squad, coach, transfers and missing profiles; no trophies, past absences or careers;
* ``minima`` - level D, or no sample (``MI``) without P0/P1: squad and coach only.

The level of a competition is the summary (``fbi.coverage.levels.summary_level``) of its latest season with a sample, the one the
C-16 directory shows; a competition the matrix has not measured yet counts as ``MI`` (a new batch is ``minima`` until the nightly
pass measures it, unless it is P0/P1). A competition without priority and without a row is ``completa``: nothing known, nothing
lowered. A team or a person playing in several competitions takes the deepest of them.

The priorities come from ``config/coverage/prioridad_editorial.yaml`` (annex A of the plan). Pure rule + one read of the matrix per
reference pass (cached an hour): no request, no write. Used only while ``FBI_REFERENCE_DEPTH`` is on: the worker passes ``current``
to ``fbi.ingestion.reference.refresh_reference`` and ``fbi.ingestion.people.seed_player_seasons`` (ingestion never imports this
package: it would join the import cycle that tests/unit/test_architecture.py keeps from growing).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal, cast

import psycopg
import yaml
from psycopg.rows import tuple_row

from fbi.coverage import levels

Depth = Literal["completa", "media", "minima"]
Priority = Literal["P0", "P1", "P2", "P3", "P4"]

DEPTHS: Final[tuple[Depth, ...]] = ("minima", "media", "completa")
RANK: Final[Mapping[Depth, int]] = {d: i for i, d in enumerate(DEPTHS)}
PRIORITIES: Final[tuple[Priority, ...]] = ("P0", "P1", "P2", "P3", "P4")
PHASE_ALL: Final = "todas"
"""The phase the summary is read on (``fbi.coverage.job.PHASE_ALL``; repeated so this module does not import the batch)."""

PRIORITY_FILE: Final = Path(__file__).resolve().parents[3] / "config" / "coverage" / "prioridad_editorial.yaml"

FEED_FLOOR: Final[Mapping[str, Depth]] = {
    "transfers": "media",
    "profiles_players": "media",
    "sidelined_players": "completa",
    "sidelined_coachs": "completa",
    "trophies_players": "completa",
    "trophies_coachs": "completa",
    "players_teams": "completa",
}
"""The least depth a reference feed needs to ask for a team or a person. A feed not named here (squads, coaches, the season lists,
the catalogues) is asked at every depth."""

PLAYER_SEASONS_PRIORITIES: Final[frozenset[Priority]] = frozenset({"P0", "P1", "P2"})
"""``/players`` (the provider's season aggregates) only for P0 to P2 (the part of PM-04-03 that needed the priority in the code),
and never for a ``minima`` competition. A competition without priority is not lowered."""

CACHE_FOR: Final = timedelta(hours=1)


def depth_for(level: levels.Level | None, priority: Priority | None) -> Depth:
    """The rule of the task card (field 6). ``level`` None: the matrix has no row for the competition."""
    if priority in ("P0", "P1"):
        return "completa"
    if level is None:
        return "completa" if priority is None else "minima"
    if level in ("A", "B"):
        return "completa"
    if level == "C":
        return "media"
    return "minima"


def deepest(depths: Iterable[Depth]) -> Depth:
    """The deepest of ``depths``; ``completa`` when there is none (nothing known, nothing lowered)."""
    found = list(depths)
    return max(found, key=RANK.__getitem__) if found else "completa"


def reaches(depth: Depth, floor: Depth) -> bool:
    return RANK[depth] >= RANK[floor]


@lru_cache(maxsize=1)
def priorities(path: Path = PRIORITY_FILE) -> dict[int, Priority]:
    """``provider_league_id -> P0..P4`` from the editorial file. A malformed file fails loudly (a test reads it)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[int, Priority] = {}
    for league, entry in (data.get("competiciones") or {}).items():
        p = entry["prioridad"] if isinstance(entry, Mapping) else entry
        if p not in PRIORITIES:
            raise ValueError(f"{path.name}: league {league} has priority {p!r}, expected one of {PRIORITIES}")
        out[int(league)] = cast(Priority, p)
    return out


LEVELS_SQL: Final = """
SELECT c.provider_league_id, s.id, s.season, 'd', x.datum, x.level
  FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
  JOIN analytics.coverage_cells x ON x.competition_season_id = s.id AND x.phase_key = %(phase)s
 WHERE c.is_tracked
UNION ALL
SELECT c.provider_league_id, s.id, s.season, 'm', m.market_key, m.level
  FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
  JOIN analytics.market_availability m ON m.competition_season_id = s.id
 WHERE c.is_tracked
"""

TRACKED_SQL: Final = "SELECT provider_league_id, name FROM core.competitions WHERE is_tracked ORDER BY 1"


def summary_of(seasons: Mapping[int, tuple[dict[str, levels.Level], dict[str, levels.Level]]]) -> levels.Level:
    """The level the C-16 directory shows: the summary of the latest season with a sample (a season graded only in part is
    ``MI``, never guessed)."""
    graded: list[levels.Level] = []
    for season in sorted(seasons, reverse=True):
        data, markets = seasons[season]
        if set(levels.DATA) <= set(data) and set(levels.MARKETS) <= set(markets):
            graded.append(levels.summary_level(data, markets).level)
        else:
            graded.append("MI")
    return next((lv for lv in graded if lv != "MI"), graded[0] if graded else "MI")


def competition_levels(conn: psycopg.Connection[Any]) -> dict[int, levels.Level]:
    """``provider_league_id -> level`` of the tracked competitions the matrix has measured (one read)."""
    per: dict[int, dict[int, tuple[dict[str, levels.Level], dict[str, levels.Level]]]] = defaultdict(dict)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LEVELS_SQL, {"phase": PHASE_ALL})
        for league, _sid, season, kind, key, level in cur.fetchall():
            data, markets = per[int(league)].setdefault(int(season), ({}, {}))
            (data if kind == "d" else markets)[str(key)] = cast(levels.Level, level)
    return {league: summary_of(seasons) for league, seasons in per.items()}


@dataclass(frozen=True)
class DepthMap:
    """The depth of each tracked competition, and why (its level and priority)."""

    by_league: dict[int, Depth] = field(default_factory=dict)
    level: dict[int, levels.Level | None] = field(default_factory=dict)
    priority: dict[int, Priority | None] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)

    def of(self, leagues: Iterable[int | None]) -> Depth:
        """A team's or a person's depth: the deepest of its tracked competitions (one outside the tracked set, a friendly,
        does not count); ``completa`` when none is tracked."""
        return deepest(self.by_league[int(lg)] for lg in leagues if lg is not None and int(lg) in self.by_league)

    def keeps(self, feed: str, leagues: Iterable[int]) -> bool:
        """Whether reference ``feed`` asks for a team or a person of ``leagues`` (``FEED_FLOOR``)."""
        floor = FEED_FLOOR.get(feed)
        return floor is None or reaches(self.of(leagues), floor)

    def player_seasons(self, league: int) -> bool:
        """Whether ``/players`` (season aggregates) is asked for this competition."""
        p = self.priority.get(league)
        return self.by_league.get(league, "completa") != "minima" and (p is None or p in PLAYER_SEASONS_PRIORITIES)


def build(conn: psycopg.Connection[Any], prio: Mapping[int, Priority] | None = None) -> DepthMap:
    prio = priorities() if prio is None else prio
    measured = competition_levels(conn)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TRACKED_SQL)
        tracked = [(int(a), str(b)) for a, b in cur.fetchall()]
    out = DepthMap()
    for league, name in tracked:
        lv, p = measured.get(league), prio.get(league)
        out.by_league[league] = depth_for(lv, p)
        out.level[league], out.priority[league], out.names[league] = lv, p, name
    return out


_cache: tuple[datetime, DepthMap] | None = None


def current(conn: psycopg.Connection[Any], at: datetime) -> DepthMap:
    """The map for a reference pass: read once and kept ``CACHE_FOR`` (the matrix changes once a night)."""
    global _cache
    if _cache is not None and timedelta(0) <= at - _cache[0] < CACHE_FOR:
        return _cache[1]
    built = build(conn)
    _cache = (at, built)
    return built


def clear_cache() -> None:
    global _cache
    _cache = None

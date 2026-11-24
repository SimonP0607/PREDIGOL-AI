"""The nightly recalculation of the availability matrix (plan PM, section 4; PM-02-03): ``FBI_AVAILABILITY_REFRESH``.

It runs in a process of its own (``scripts.availability_refresh``), never in the worker's: the worker sits at 93 % of its 3 GiB, so the
scheduler only starts the process (``apps.worker.scheduler``, 08:00 UTC, after the statistics pass of 07:20 and away from the copies of
03:50-05:00) and the process caps its own memory (``scripts.availability_refresh``). Everything heavy is done by PostgreSQL; Python holds
one batch of matches at a time.

Two steps:

1. **Facts** (``analytics.coverage_fixture_facts``): for every finished match of the competition seasons in scope, which data it carries
   (``DATA``; rule 1: a datum counts when it is filled for BOTH teams - an empty value is not a zero), which markets its stored result
   settles (the measures of ``fbi.market.rules``) and, inside the odds window, how many houses priced each market. A played match's prices
   do not change, so they are measured once; its data again within a week (late statistics) and every Sunday.
2. **Cells** (``analytics.coverage_cells``, ``analytics.market_availability``): counted from the facts of each competition season whose
   facts are complete, graded by ``fbi.coverage.levels`` (``coverage-levels-v1``), with the rules this measurement owns:

   * rule 2: a season short of sample takes the level of the season before, provisional (``levels.grade_datum``) - only a level that
     season MEASURED: one it took from the provider's «no» (rule 5, ``no_entregado``) is not inherited (``INHERITABLE``), so the
     Sudamericana 2026 (5 matches priced, its flag «yes») is ``MI`` and not the ``D`` of 2025, whose odds the provider declared «no»
     before PrediGol's odds window opened;
   * rule 3: a one-match competition (every one of its last editions has at most ``ONE_MATCH_MAX`` matches) pools its last
     ``POOLED_EDITIONS`` editions (``levels.combine``);
   * rule 4: a level goes down only after two recalculations in a row miss it (``levels.step``);
   * rule 5: the provider's declared flag (``raw.league_coverage``) is used only when it says «no»: a cell short of sample whose flag
     says the provider does not deliver the datum is ``D`` (``no_entregado``), never inherited.

   Every change of a published level (and the first miss of one) is appended to ``analytics.coverage_changes``.

   **Phases of a cup** (PM-02-07): a cup season (``core.competitions.type = 'cup'``) with matches in at least two phases also gets the
   cells of each phase (``phase_key`` ``previa``, ``liga_o_grupos``, ``eliminatoria``; ``cup_phases``), counted from the same facts and
   graded with the same rules (2, 4 and 5; rule 3 pools whole editions, so a pooled competition is not split). The Champions League's
   qualifying rounds no longer lower its league phase. The markets stay on ``todas`` (``analytics.market_availability`` has no phase).

Scope: the incremental pass (every night) takes the tracked competitions with a match finished in the last ``RECENT_HOURS``; the full pass
(Sundays, and the next nights until one completes - ``full_due`` - or ``--full``) every tracked competition. Of each, its last ``SEASONS_KEPT`` seasons with finished matches (``POOLED_EDITIONS``
for a one-match competition). Reads stored data only: no provider, no model. Writes only the matrix's tables (and the job ledger, from the
process). Idempotent: a second pass over the same data changes nothing but the times.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.competitions import stages
from fbi.coverage import levels
from fbi.coverage.levels import Grade, Level
from fbi.market.rules import RULES
from fbi.market.settle_coverage import Coverage

SWITCH: Final = "FBI_AVAILABILITY_REFRESH"
JOB: Final = "availability_refresh"
HOUR: Final = 8
"""08:00 UTC: after the statistics pass (07:20) and the night's results; away from the copies (03:50-05:00 UTC) and the Monday 06:00
jobs. Catch-up attempts at ``RETRY_TIMES`` when the first found no room in the worker's memory."""
MINUTE: Final = 0
RETRY_TIMES: Final[tuple[tuple[int, int], ...]] = ((8, 40), (11, 20))
FULL_WEEKDAY: Final = 6
"""Sunday (``date.weekday``): the full pass."""
LOCK: Final = 0x0C0F16
PHASE_ALL: Final = "todas"
"""Every phase together: every competition season has it; a cup's phases (PM-02-07) are cells besides it."""
PHASE_PRE: Final = "previa"
"""Qualifying rounds, and the knock-out rounds played before a cup's league or group stage starts (the Champions League's play-offs)."""
PHASE_LEAGUE: Final = "liga_o_grupos"
"""The league stage or the group stage."""
PHASE_KNOCKOUT: Final = "eliminatoria"
"""The knock-out rounds after the league or group stage (all of them in a cup without one: the FA Cup's rounds proper)."""
CUP_PHASES: Final[tuple[str, ...]] = (PHASE_PRE, PHASE_LEAGUE, PHASE_KNOCKOUT)

RECENT_HOURS: Final = 48
DATA_REFRESH_DAYS: Final = 7
"""The data of a match finished in the last week is measured again every night: statistics arrive late."""
SEASONS_KEPT: Final = 2
POOLED_EDITIONS: Final = 5
ONE_MATCH_MAX: Final = 2
"""A competition whose editions have at most this many matches (a final, a two-legged super cup) pools its last editions (rule 3)."""
ODDS_WINDOW_START: Final = date(2026, 10, 5)
"""PrediGol captures prices at scale since 4-5 Oct 2026 (plan PM, annex B): before it a missing price says nothing about the market."""
BATCH: Final = 400
MAX_SECONDS: Final = 15 * 60
SHADOW_SECONDS: Final = 25 * 60
"""The shadow comparison's budget (PM-02-06, ``fbi.api.services.availability_shadow``): by hand it follows the pass in the same process;
the scheduler starts it in a process of its own (BE-094). 25 minutes (12 before BE-094): measured in production on 24-nov-2026, a match
takes 2.8 s (C-14 and the resolver, read-only), so 12 minutes stopped every day at about 260 of the 500 and no day was ever complete."""
PROCESS_TIMEOUT: Final = MAX_SECONDS + SHADOW_SECONDS + 5 * 60
"""How long the scheduler waits for the process before it stops it."""
STATEMENT_TIMEOUT: Final = "120s"

# ── what is measured ──────────────────────────────────────────────────────────────────────────────────────────────────

TEAM_STAT_COLUMNS: Final[dict[str, str]] = {
    "corners": "corners", "yellow_cards": "yellow_cards", "shots": "shots", "shots_on_target": "shots_on_target",
    "fouls": "fouls", "xg": "expected_goals",
}
"""The data read from ``core.fixture_team_stats``: the datum and its column (both teams)."""

CORE_MARKETS: Final = ("1X2", "OU", "BTTS", "AH")
"""Priced in ``market.final_prematch_odds`` / ``market.odds_snapshots`` (their ``market_key``) and in ``market.odds_quotes``."""
FAMILY_MARKETS: Final = ("goals_half", "corners", "cards", "shots", "players")
"""Priced in ``market.odds_quotes``, by the family of the bet (``market.market_definitions.family``)."""

SETTLE_MEASURE: Final[dict[str, str | None]] = {
    "1X2": "goals_ft", "OU": "goals_ft", "BTTS": "goals_ft", "AH": "goals_ft", "goals_half": "goals_1h",
    "corners": "corners_ft", "cards": "cards_lines_ft", "shots": "shots_ft", "players": None,
}
"""The rule (``fbi.market.rules``) whose data settles the main bet of each market; ``players``: none (no rule grades a player's bet)."""

CATALOGUE_KEY: Final[dict[str, str | None]] = {
    "1X2": "1X2", "OU": "OU", "BTTS": "BTTS", "AH": "AH", "goals_half": "OU_1H", "corners": "CORNERS_OU", "cards": "CARDS_OU",
    "shots": "SHOTS_OU", "players": None,
}
"""The market of the catalogue (``market_states.json``) whose state each market of the matrix carries."""

DECLARED_FLAG: Final[dict[str, str | None]] = {
    "events": "events", "lineups": "lineups", "corners": "statistics_fixtures", "yellow_cards": "statistics_fixtures",
    "shots": "statistics_fixtures", "shots_on_target": "statistics_fixtures", "fouls": "statistics_fixtures",
    "xg": "statistics_fixtures", "player_stats": "statistics_players", "referee": None,
}
"""The column of ``raw.league_coverage`` that declares each datum (rule 5); every market reads ``odds``."""

CATALOGUE_FILE: Final = Path(__file__).resolve().parents[1] / "api" / "services" / "market_states.json"
"""Read as data (``fbi.coverage`` may not import ``fbi.api``: ``tests/unit/test_architecture.py``)."""

if set(TEAM_STAT_COLUMNS) | {"events", "lineups", "player_stats", "referee"} != set(levels.DATA):  # pragma: no cover
    raise RuntimeError("every datum of the rules must be measured, and nothing else")
if set(CORE_MARKETS) | set(FAMILY_MARKETS) != set(levels.MARKETS):  # pragma: no cover
    raise RuntimeError("every market of the rules must be measured, and nothing else")
_MEASURES: Final = tuple(r.measure for r in RULES if r.liquidable)
if any(m is not None and m not in _MEASURES for m in SETTLE_MEASURE.values()):  # pragma: no cover
    raise RuntimeError("a market settles on a measure no rule has")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``on`` unless the switch says off (``0``, ``off``, ``false``, ``no``): the pass writes only the matrix's tables, which nothing a
    reader sees reads while ``FBI_AVAILABILITY`` is off (plan PM: measurement switches are on, like PM-01-02's)."""
    e = os.environ if env is None else env
    return "off" if e.get(SWITCH, "on").strip().lower() in ("0", "off", "false", "no") else "on"


def is_full_day(at: datetime) -> bool:
    return at.astimezone(UTC).weekday() == FULL_WEEKDAY


FULL_DONE_SQL: Final = (
    "SELECT 1 FROM raw.ingestion_runs WHERE job_type = %(job)s AND status = 'completed' AND started_at >= %(since)s "
    "AND (params -> 'report' ->> 'full')::boolean AND coalesce(params -> 'report' ->> 'stopped', '') <> 'tiempo_agotado' "
    "AND params ->> 'only' IS NULL LIMIT 1")
"""A full pass that ended (not stopped by its time budget, and not a manual ``--only``) since ``since``: the ledger row of
``scripts.availability_refresh``."""


def full_due(conn: psycopg.Connection[Any], at: datetime) -> bool:
    """Is tonight's pass a full one? On Sundays, and on every later night of the week until one completes: the Sunday's pass can find
    no room in the worker's memory (22-nov-2026: three attempts, 2.8-2.9 of 3 GiB) and then 120 of the 272 seasons of annex B waited a
    whole week without a cell. The week starts on Sunday at 00:00 UTC."""
    day = at.astimezone(UTC)
    if day.weekday() == FULL_WEEKDAY:
        return True
    sunday = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(days=(day.weekday() - FULL_WEEKDAY) % 7)
    row = conn.execute(FULL_DONE_SQL, {"job": JOB, "since": sunday}).fetchone()
    conn.commit()
    return row is None


CAP_MIB: Final = 512
"""The process's memory cap (plan PM, section 4)."""
HEADROOM_MIB: Final = 384
"""The memory the container must have free, page cache aside, before the process starts: the pass measured 55 MiB on a small database;
less than this and it waits for the next attempt rather than press the worker against its limit."""
CGROUP: Final = Path("/sys/fs/cgroup")


def headroom_mib(root: Path = CGROUP) -> float | None:
    """What the container (cgroup v2) can still take before its limit, not counting the page cache the kernel may reclaim:
    ``memory.max - (memory.current - file)``. None when there is no limit or nothing to read (a developer's machine)."""
    try:
        limit = (root / "memory.max").read_text().strip()
        current = int((root / "memory.current").read_text().strip())
        stat = dict(line.split() for line in (root / "memory.stat").read_text().splitlines() if line.count(" ") == 1)
    except (OSError, ValueError):
        return None
    if limit == "max":
        return None
    try:
        reclaimable = int(stat.get("file", "0"))
        return round((int(limit) - (current - reclaimable)) / (1024 * 1024), 1)
    except ValueError:
        return None


# ── pure: what one match carries ──────────────────────────────────────────────────────────────────────────────────────


def team_stat_present(sides: Mapping[str, Iterable[object | None]]) -> bool:
    """Rule 1: a datum is there when both teams have a value (an empty value is not a zero). ``sides``: the values of each side, one
    per source of the statistics."""
    return all(any(v is not None for v in sides.get(side, ())) for side in ("home", "away"))


def settled_measures(outcome: Mapping[str, object | None]) -> list[str]:
    """The measures of ``fbi.market.rules`` the stored result of a match settles: every column the rule reads is filled."""
    return [r.measure for r in RULES if r.liquidable and all(outcome.get(c) is not None for c in r.columns)]


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


# ── pure: grading a season ────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Published:
    """A cell as the table holds it now (rule 4)."""

    level: Level
    missed: bool
    provisional: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class CellResult:
    level: Level
    measured: Level
    missed: bool
    provisional: bool
    reason: str | None
    change: str | None
    """``primera_medida``, ``sube``, ``baja``, ``incumple_una_vez`` (the first miss: the level stays) or None."""
    old_level: Level | None


def apply_flag(grade: Grade, declared: bool | None, *, with_data: int) -> Grade:
    """Rule 5: the provider's flag is used only when it says «no». A cell short of sample (or inherited) whose datum the provider declares
    it does not deliver - and of which nothing has arrived - is ``D``, ``no_entregado``. Data that did arrive always wins."""
    if declared is False and with_data == 0 and (grade.level == "MI" or grade.reason == "heredado"):
        return Grade("D", False, "no_entregado")
    return grade


def publish(grade: Grade, held: Published | None) -> CellResult:
    """Rule 4 over a measured grade: up (or the same) at once; down only on the second recalculation in a row that misses it."""
    s = levels.step(held.level if held else None, grade.level, missed_before=held.missed if held else False)
    if held is None:
        change: str | None = "primera_medida"
    elif s.level != held.level:
        change = "sube" if levels.RANK[s.level] > levels.RANK[held.level] else "baja"
    elif s.missed and not held.missed:
        change = "incumple_una_vez"
    else:
        change = None
    if s.missed and held is not None:  # the level stays: so do its marks
        return CellResult(s.level, grade.level, True, held.provisional, held.reason, change, held.level)
    return CellResult(s.level, grade.level, False, grade.provisional, grade.reason, change, held.level if held else None)


def one_match(fixtures_per_edition: Iterable[int]) -> bool:
    """Rule 3: every edition seen has at most ``ONE_MATCH_MAX`` matches (and there is one)."""
    seen = list(fixtures_per_edition)
    return bool(seen) and max(seen) <= ONE_MATCH_MAX


def cup_phases(rounds: Iterable[tuple[int, str | None, datetime]]) -> dict[int, str]:
    """The phase of each match of one cup season (``fixture id -> phase key``) from its round labels, read by
    ``fbi.competitions.stages`` (the one reader of a label; nothing is re-read here): a league or group stage is ``liga_o_grupos``, a
    qualifying round ``previa``, a knock-out round ``previa`` when it started before the first league or group stage and
    ``eliminatoria`` otherwise. A friendly or an unread label has no phase (it counts only in ``todas``). Empty when the season has
    fewer than two phases: its ``todas`` already says everything."""
    seen = list(rounds)
    numbered = {stages.stage_of(r) for _, r, _ in seen if stages.match_day_of(r) is not None}
    first: dict[str, datetime] = {}
    for _, label, kickoff in seen:
        stage = stages.stage_of(label)
        if stage not in first or kickoff < first[stage]:
            first[stage] = kickoff
    kinds = {st: stages.classify(st, numbered=st in numbered).kind for st in first if st}
    league_start = min((first[st] for st, k in kinds.items() if k == "league"), default=None)

    def phase(stage: str) -> str | None:
        kind = kinds.get(stage)
        if kind == "league":
            return PHASE_LEAGUE
        if kind == "qualifying":
            return PHASE_PRE
        if kind == "knockout":
            return PHASE_PRE if league_start is not None and first[stage] < league_start else PHASE_KNOCKOUT
        return None

    out = {fid: p for fid, label, _ in seen if (p := phase(stages.stage_of(label))) is not None}
    return out if len(set(out.values())) >= 2 else {}


def share(c: Coverage) -> float | None:
    return round(c.with_data / c.finished, 4) if c.finished else None


# ── reading ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Season:
    id: int
    competition_id: int
    provider_league_id: int
    season: int
    fixtures: int
    """Every match of the season, whatever its status (rule 3)."""
    cup: bool = False
    """A cup (``core.competitions.type = 'cup'``): its phases get cells of their own (PM-02-07)."""


SCOPE_SQL: Final = """
WITH comp AS (
    SELECT c.id, c.provider_league_id, lower(coalesce(c.type, '')) = 'cup' AS cup FROM core.competitions c
     WHERE c.is_tracked
       AND (%(all)s OR EXISTS (SELECT 1 FROM core.fixtures f JOIN core.competition_seasons s ON s.id = f.competition_season_id
                                WHERE s.competition_id = c.id AND f.status_group = 'finished' AND f.kickoff_at >= %(since)s
                                  AND f.kickoff_at <= %(now)s))
)
SELECT s.id, comp.id, comp.provider_league_id, s.season,
       (SELECT count(*) FROM core.fixtures f WHERE f.competition_season_id = s.id) AS fixtures, comp.cup
  FROM comp JOIN core.competition_seasons s ON s.competition_id = comp.id
 WHERE EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id AND f.status_group = 'finished')
 ORDER BY comp.id, s.season DESC
"""


def scope(conn: psycopg.Connection[Any], *, now: datetime, full: bool, only: set[int] | None = None) -> list[Season]:
    """The competition seasons to recalculate: of each competition in scope, its last ``SEASONS_KEPT`` seasons with finished matches
    (``POOLED_EDITIONS`` when it is a one-match competition). Oldest first within a competition, so that rule 2 finds the season
    before already graded."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SCOPE_SQL, {"all": full or only is not None, "since": now - timedelta(hours=RECENT_HOURS), "now": now})
        rows = cur.fetchall()
    by_comp: dict[int, list[Season]] = {}
    for sid, cid, league, season, fixtures, cup in rows:
        by_comp.setdefault(int(cid), []).append(Season(int(sid), int(cid), int(league), int(season), int(fixtures), bool(cup)))
    out: list[Season] = []
    for seasons in by_comp.values():
        pooled = one_match(s.fixtures for s in seasons[:POOLED_EDITIONS])
        keep = seasons[:POOLED_EDITIONS if pooled else SEASONS_KEPT]
        if only is not None and not any(s.id in only for s in keep):
            continue
        out.extend(reversed(keep))
    return out


TO_MEASURE_SQL: Final = """
SELECT f.id, f.competition_season_id, f.kickoff_at,
       (x.fixture_id IS NULL OR %(full)s OR f.kickoff_at >= %(data_since)s) AS data_due,
       (f.kickoff_at >= %(window)s AND (x.fixture_id IS NULL OR x.odds_measured_at IS NULL)) AS odds_due
  FROM core.fixtures f
  LEFT JOIN analytics.coverage_fixture_facts x ON x.fixture_id = f.id
 WHERE f.competition_season_id = ANY(%(seasons)s) AND f.status_group = 'finished' AND f.kickoff_at <= %(now)s
   AND (x.fixture_id IS NULL OR %(full)s OR f.kickoff_at >= %(data_since)s
        OR (f.kickoff_at >= %(window)s AND x.odds_measured_at IS NULL))
 ORDER BY f.id
"""

EVENTS_SQL: Final = "SELECT DISTINCT fixture_id FROM core.fixture_events WHERE fixture_id = ANY(%s)"
LINEUPS_SQL: Final = ("SELECT fixture_id FROM core.fixture_lineups WHERE fixture_id = ANY(%s) GROUP BY fixture_id "
                      "HAVING count(DISTINCT team_side) = 2")
PLAYERS_SQL: Final = ("SELECT fixture_id FROM core.fixture_player_stats WHERE fixture_id = ANY(%s) GROUP BY fixture_id "
                      "HAVING count(DISTINCT team_side) = 2")
REFEREE_SQL: Final = ("SELECT fixture_id FROM core.fixture_referees WHERE fixture_id = ANY(%(ids)s) AND referee_id IS NOT NULL "
                      "UNION SELECT fixture_id FROM core.fixture_facts WHERE fixture_id = ANY(%(ids)s) AND referee IS NOT NULL")
TEAM_SQL: Final = ("SELECT fixture_id, " + ", ".join(
    f"count(DISTINCT team_side) FILTER (WHERE {col} IS NOT NULL) = 2" for col in TEAM_STAT_COLUMNS.values())
    + " FROM core.fixture_team_stats WHERE fixture_id = ANY(%s) GROUP BY fixture_id")
_OUTCOME_COLUMNS: Final = tuple(sorted({c for r in RULES if r.liquidable for c in r.columns}))
OUTCOMES_SQL: Final = ("SELECT fixture_id, " + ", ".join(_OUTCOME_COLUMNS)
                       + " FROM market.fixture_outcomes WHERE fixture_id = ANY(%s)")
CORE_BOOKS_SQL: Final = """
SELECT fixture_id, market_key, count(DISTINCT bookmaker_id) FROM (
    SELECT fixture_id, market_key, bookmaker_id FROM market.final_prematch_odds
     WHERE fixture_id = ANY(%(ids)s) AND market_key = ANY(%(keys)s)
    UNION
    SELECT fixture_id, market_key, bookmaker_id FROM market.odds_snapshots
     WHERE fixture_id = ANY(%(ids)s) AND market_key = ANY(%(keys)s) AND source = 'prematch'
    UNION
    SELECT q.fixture_id, d.market_key, q.bookmaker_id FROM market.odds_quotes q
      JOIN market.market_definitions d ON d.id = q.definition_id
     WHERE q.fixture_id = ANY(%(ids)s) AND d.market_key = ANY(%(keys)s)
) p GROUP BY fixture_id, market_key
"""
FAMILY_BOOKS_SQL: Final = """
SELECT q.fixture_id, d.family, count(DISTINCT q.bookmaker_id)
  FROM market.odds_quotes q JOIN market.market_definitions d ON d.id = q.definition_id
 WHERE q.fixture_id = ANY(%(ids)s) AND d.family = ANY(%(families)s)
 GROUP BY q.fixture_id, d.family
"""

UPSERT_FACTS_SQL: Final = """
INSERT INTO analytics.coverage_fixture_facts (fixture_id, competition_season_id, kickoff_at, present, books, settles, rules_version,
                                              measured_at, odds_measured_at)
VALUES (%(id)s, %(cs)s, %(kickoff)s, %(present)s, %(books)s, %(settles)s, %(version)s, %(at)s, %(odds_at)s)
ON CONFLICT (fixture_id) DO UPDATE SET
    competition_season_id = EXCLUDED.competition_season_id, kickoff_at = EXCLUDED.kickoff_at,
    present = CASE WHEN %(data)s THEN EXCLUDED.present ELSE analytics.coverage_fixture_facts.present END,
    settles = CASE WHEN %(data)s THEN EXCLUDED.settles ELSE analytics.coverage_fixture_facts.settles END,
    measured_at = CASE WHEN %(data)s THEN EXCLUDED.measured_at ELSE analytics.coverage_fixture_facts.measured_at END,
    books = COALESCE(EXCLUDED.books, analytics.coverage_fixture_facts.books),
    odds_measured_at = COALESCE(EXCLUDED.odds_measured_at, analytics.coverage_fixture_facts.odds_measured_at),
    rules_version = EXCLUDED.rules_version
"""


def _ids(cur: psycopg.Cursor[tuple[Any, ...]], sql: str, params: Any) -> set[int]:
    cur.execute(sql, params)
    return {int(r[0]) for r in cur.fetchall()}


def measure_data(conn: psycopg.Connection[Any], ids: list[int]) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """What each match carries (rule 1) and what its stored result settles: (present, settles) by match."""
    with conn.cursor(row_factory=tuple_row) as cur:
        present: dict[int, set[str]] = {i: set() for i in ids}
        for fid in _ids(cur, EVENTS_SQL, (ids,)):
            present[fid].add("events")
        for fid in _ids(cur, LINEUPS_SQL, (ids,)):
            present[fid].add("lineups")
        for fid in _ids(cur, PLAYERS_SQL, (ids,)):
            present[fid].add("player_stats")
        for fid in _ids(cur, REFEREE_SQL, {"ids": ids}):
            present[fid].add("referee")
        cur.execute(TEAM_SQL, (ids,))
        for row in cur.fetchall():
            for datum, ok in zip(TEAM_STAT_COLUMNS, row[1:], strict=True):
                if ok:
                    present[int(row[0])].add(datum)
        cur.execute(OUTCOMES_SQL, (ids,))
        settles: dict[int, list[str]] = {i: [] for i in ids}
        for row in cur.fetchall():
            settles[int(row[0])] = settled_measures(dict(zip(_OUTCOME_COLUMNS, row[1:], strict=True)))
    return {i: sorted(p) for i, p in present.items()}, settles


def measure_books(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, dict[str, int]]:
    """Houses per market of each match (inside the odds window): the distinct bookmakers that priced it before the match."""
    out: dict[int, dict[str, int]] = {i: {} for i in ids}
    if not ids:
        return out
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CORE_BOOKS_SQL, {"ids": ids, "keys": list(CORE_MARKETS)})
        for fid, key, n in cur.fetchall():
            out[int(fid)][str(key)] = int(n)
        cur.execute(FAMILY_BOOKS_SQL, {"ids": ids, "families": list(FAMILY_MARKETS)})
        for fid, family, n in cur.fetchall():
            out[int(fid)][str(family)] = int(n)
    return out


# ── counting and grading ──────────────────────────────────────────────────────────────────────────────────────────────

COMPLETE_SQL: Final = """
SELECT f.competition_season_id
  FROM core.fixtures f LEFT JOIN analytics.coverage_fixture_facts x ON x.fixture_id = f.id
 WHERE f.competition_season_id = ANY(%(seasons)s) AND f.status_group = 'finished' AND f.kickoff_at <= %(now)s
 GROUP BY 1
HAVING bool_and(x.fixture_id IS NOT NULL AND (f.kickoff_at < %(window)s OR x.odds_measured_at IS NOT NULL))
"""

COUNT_DATA_SQL: Final = ("SELECT x.competition_season_id, count(*), " + ", ".join(
    f"count(*) FILTER (WHERE '{d}' = ANY(x.present))" for d in levels.DATA)
    + " FROM analytics.coverage_fixture_facts x JOIN core.fixtures f ON f.id = x.fixture_id"
      " WHERE x.competition_season_id = ANY(%s) AND f.status_group = 'finished' GROUP BY 1")

ROUNDS_SQL: Final = ("SELECT competition_season_id, id, round, kickoff_at FROM core.fixtures "
                     "WHERE competition_season_id = ANY(%s) AND kickoff_at IS NOT NULL")
"""Every match of the cup seasons (played or not: a stage's start is its first kick-off), for ``cup_phases``."""

COUNT_PHASE_DATA_SQL: Final = ("SELECT x.competition_season_id, p.phase, count(*), " + ", ".join(
    f"count(*) FILTER (WHERE '{d}' = ANY(x.present))" for d in levels.DATA)
    + " FROM analytics.coverage_fixture_facts x JOIN core.fixtures f ON f.id = x.fixture_id"
      " JOIN unnest(%s::bigint[], %s::text[]) AS p(fixture_id, phase) ON p.fixture_id = x.fixture_id"
      " WHERE f.status_group = 'finished' GROUP BY 1, 2")

HELD_PHASE_CELLS_SQL: Final = ("SELECT competition_season_id, phase_key, datum, level, missed, provisional, reason "
                               "FROM analytics.coverage_cells WHERE competition_season_id = ANY(%s) AND phase_key = ANY(%s)")
NOT_MEASURED: Final = "no_entregado"
"""The reason of a level that comes from the provider's flag (rule 5), not from the matches: no season after it inherits it (rule 2)."""
INHERITABLE: Final = f"CASE WHEN c.reason = '{NOT_MEASURED}' THEN NULL ELSE c.level END"
"""The level of the season before that rule 2 may take: NULL (nothing to inherit) for a level that was not measured. The row stays, so
the season before is still the season before - an older season's level is never reached for instead."""


def inheritable(result: CellResult) -> Level | None:
    """What a later season of the same pass may inherit from ``result`` (rule 2): its level, unless the provider's «no» gave it."""
    return None if result.reason == NOT_MEASURED else result.level


PREVIOUS_PHASE_SQL: Final = """
SELECT s.competition_id, s.season, c.phase_key, c.datum, """ + INHERITABLE + """ FROM analytics.coverage_cells c
  JOIN core.competition_seasons s ON s.id = c.competition_season_id
 WHERE s.competition_id = ANY(%(comps)s) AND c.phase_key = ANY(%(phases)s)
"""

COUNT_MARKETS_SQL: Final = """
SELECT x.competition_season_id, m.key,
       count(*) FILTER (WHERE x.kickoff_at >= %(window)s AND x.books IS NOT NULL) AS n_window,
       count(*) FILTER (WHERE x.kickoff_at >= %(window)s AND COALESCE((x.books ->> m.key)::int, 0) > 0) AS n_priced,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (x.books ->> m.key)::int)
           FILTER (WHERE x.kickoff_at >= %(window)s AND COALESCE((x.books ->> m.key)::int, 0) > 0) AS books,
       count(*) AS n_settle,
       count(*) FILTER (WHERE m.measure IS NOT NULL AND m.measure = ANY(x.settles)) AS n_settleable
  FROM analytics.coverage_fixture_facts x
  JOIN core.fixtures f ON f.id = x.fixture_id
 CROSS JOIN unnest(%(keys)s::text[], %(measures)s::text[]) AS m(key, measure)
 WHERE x.competition_season_id = ANY(%(seasons)s) AND f.status_group = 'finished'
 GROUP BY 1, 2
"""

FLAGS_SQL: Final = """
SELECT DISTINCT ON (provider_league_id, season) provider_league_id, season, events, lineups, statistics_fixtures, statistics_players,
       odds
  FROM raw.league_coverage
 WHERE provider = 'api_football' AND (provider_league_id, season) IN (SELECT * FROM unnest(%(leagues)s::int[], %(seasons)s::int[]))
 ORDER BY provider_league_id, season, observed_at DESC
"""

HELD_CELLS_SQL: Final = ("SELECT competition_season_id, datum, level, missed, provisional, reason FROM analytics.coverage_cells "
                         "WHERE competition_season_id = ANY(%s) AND phase_key = %s")
HELD_MARKETS_SQL: Final = ("SELECT competition_season_id, market_key, level, missed, provisional, reason "
                           "FROM analytics.market_availability WHERE competition_season_id = ANY(%s)")
PREVIOUS_SQL: Final = """
SELECT s.competition_id, s.season, 'd:' || c.datum, """ + INHERITABLE + """ FROM analytics.coverage_cells c
  JOIN core.competition_seasons s ON s.id = c.competition_season_id
 WHERE s.competition_id = ANY(%(comps)s) AND c.phase_key = %(phase)s
UNION ALL
SELECT s.competition_id, s.season, 'm:' || m.market_key, """ + INHERITABLE.replace("c.", "m.") + """ FROM analytics.market_availability m
  JOIN core.competition_seasons s ON s.id = m.competition_season_id
 WHERE s.competition_id = ANY(%(comps)s)
"""

UPSERT_CELL_SQL: Final = """
INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, level, measured_level, missed,
                                      provisional, reason, pooled_seasons, declared_flag, rules_version, measured_at, first_measured_at)
VALUES (%(cs)s, %(phase)s, %(subject)s, %(n)s, %(k)s, %(share)s, %(level)s, %(measured)s, %(missed)s, %(provisional)s, %(reason)s,
        %(pooled)s, %(declared)s, %(version)s, %(at)s, %(at)s)
ON CONFLICT (competition_season_id, phase_key, datum) DO UPDATE SET
    n_finished = EXCLUDED.n_finished, n_with_data = EXCLUDED.n_with_data, share = EXCLUDED.share, level = EXCLUDED.level,
    measured_level = EXCLUDED.measured_level, missed = EXCLUDED.missed, provisional = EXCLUDED.provisional, reason = EXCLUDED.reason,
    pooled_seasons = EXCLUDED.pooled_seasons, declared_flag = EXCLUDED.declared_flag, rules_version = EXCLUDED.rules_version,
    measured_at = EXCLUDED.measured_at
"""
UPSERT_MARKET_SQL: Final = """
INSERT INTO analytics.market_availability (competition_season_id, market_key, window_start, window_days, n_window, n_priced, priced_share,
                                           median_books, n_settle_finished, n_settleable, settle_share, level, measured_level, missed,
                                           provisional, reason, catalogue_state, rules_version, measured_at, first_measured_at)
VALUES (%(cs)s, %(subject)s, %(window)s, %(days)s, %(n)s, %(k)s, %(share)s, %(books)s, %(n_settle)s, %(n_settleable)s, %(settle_share)s,
        %(level)s, %(measured)s, %(missed)s, %(provisional)s, %(reason)s, %(state)s, %(version)s, %(at)s, %(at)s)
ON CONFLICT (competition_season_id, market_key) DO UPDATE SET
    window_start = EXCLUDED.window_start, window_days = EXCLUDED.window_days, n_window = EXCLUDED.n_window,
    n_priced = EXCLUDED.n_priced, priced_share = EXCLUDED.priced_share, median_books = EXCLUDED.median_books,
    n_settle_finished = EXCLUDED.n_settle_finished, n_settleable = EXCLUDED.n_settleable, settle_share = EXCLUDED.settle_share,
    level = EXCLUDED.level, measured_level = EXCLUDED.measured_level, missed = EXCLUDED.missed, provisional = EXCLUDED.provisional,
    reason = EXCLUDED.reason, catalogue_state = EXCLUDED.catalogue_state, rules_version = EXCLUDED.rules_version,
    measured_at = EXCLUDED.measured_at
"""
CHANGE_SQL: Final = """
INSERT INTO analytics.coverage_changes (competition_season_id, phase_key, kind, subject, old_level, new_level, reason, n_finished, share,
                                        rules_version, changed_at)
VALUES (%(cs)s, %(phase)s, %(kind)s, %(subject)s, %(old)s, %(level)s, %(change)s, %(n)s, %(share)s, %(version)s, %(at)s)
"""


def catalogue_states(path: Path = CATALOGUE_FILE) -> dict[str, str]:
    """The state of each market of the catalogue (``evaluable``, ``en_calibracion``, ``necesita_datos``, ``no_ofrecer``) by its key."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(m["key"]): str(m["state"]) for m in doc.get("markets", []) if "key" in m and "state" in m}


@dataclass(slots=True)
class Report:
    full: bool = False
    seasons: int = 0
    graded: int = 0
    facts: int = 0
    odds_facts: int = 0
    cells: int = 0
    phase_cells: int = 0
    markets: int = 0
    changes: int = 0
    seconds: float = 0.0
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"full": self.full, "seasons": self.seasons, "graded": self.graded, "facts": self.facts, "odds_facts": self.odds_facts,
                "cells": self.cells, "phase_cells": self.phase_cells, "markets": self.markets, "changes": self.changes, "seconds": round(self.seconds, 1),
                "stopped": self.stopped, "errors": self.errors[:5]}


def _record(cur: psycopg.Cursor[Any], sql: str, kind: str, cs: int, subject: str, result: CellResult, counts: Coverage,
            base: dict[str, Any], report: Report) -> None:
    row = {**base, "cs": cs, "subject": subject, "level": result.level, "measured": result.measured, "missed": result.missed,
           "provisional": result.provisional, "reason": result.reason}
    cur.execute(sql, row)
    if result.change is not None:
        cur.execute(CHANGE_SQL, {"cs": cs, "phase": base["phase"], "kind": kind, "subject": subject, "old": result.old_level,
                                 "level": result.level, "change": result.change, "n": counts.finished, "share": share(counts),
                                 "version": levels.RULES_VERSION, "at": base["at"]})
        report.changes += 1


def grade_seasons(conn: psycopg.Connection[Any], seasons: list[Season], *, now: datetime, report: Report) -> None:
    """Count, grade and write the cells of ``seasons`` (their facts complete), in one transaction per competition."""
    if not seasons:
        return
    ids = [s.id for s in seasons]
    states = catalogue_states()
    window_days = max((now.date() - ODDS_WINDOW_START).days, 0)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COUNT_DATA_SQL, (ids,))
        data_counts = {int(r[0]): (int(r[1]), [int(v) for v in r[2:]]) for r in cur.fetchall()}
        cur.execute(COUNT_MARKETS_SQL, {"window": ODDS_WINDOW_START, "keys": list(levels.MARKETS),
                                        "measures": [SETTLE_MEASURE[m] for m in levels.MARKETS], "seasons": ids})
        market_counts: dict[tuple[int, str], tuple[int, int, float | None, int, int]] = {
            (int(r[0]), str(r[1])): (int(r[2]), int(r[3]), None if r[4] is None else float(r[4]), int(r[5]), int(r[6]))
            for r in cur.fetchall()}
        cur.execute(FLAGS_SQL, {"leagues": [s.provider_league_id for s in seasons], "seasons": [s.season for s in seasons]})
        flags = {(int(r[0]), int(r[1])): dict(zip(("events", "lineups", "statistics_fixtures", "statistics_players", "odds"), r[2:],
                                                   strict=True)) for r in cur.fetchall()}
        cur.execute(HELD_CELLS_SQL, (ids, PHASE_ALL))
        held: dict[tuple[int, str], Published] = {(int(r[0]), str(r[1])): Published(r[2], bool(r[3]), bool(r[4]), r[5])
                                                   for r in cur.fetchall()}
        cur.execute(HELD_MARKETS_SQL, (ids,))
        held.update({(int(r[0]), "m:" + str(r[1])): Published(r[2], bool(r[3]), bool(r[4]), r[5]) for r in cur.fetchall()})
        cur.execute(PREVIOUS_SQL, {"comps": sorted({s.competition_id for s in seasons}), "phase": PHASE_ALL})
        known: dict[tuple[int, int, str], Level | None] = {(int(r[0]), int(r[1]), str(r[2])): r[3] for r in cur.fetchall()}
        """(competition, season, ``d:<datum>`` or ``m:<market>``) -> published level, None when it is not inheritable (rule 2,
        ``INHERITABLE``): a datum and a market may share a name."""
        phases = _phase_inputs(cur, [s for s in seasons if s.cup])
    conn.commit()

    by_comp: dict[int, list[Season]] = {}
    for s in seasons:
        by_comp.setdefault(s.competition_id, []).append(s)
    for comp_seasons in by_comp.values():
        comp_seasons.sort(key=lambda s: s.season)
        pooled = one_match(s.fixtures for s in comp_seasons[-POOLED_EDITIONS:])
        with conn.transaction(), conn.cursor() as cur:
            for i, s in enumerate(comp_seasons):
                editions = comp_seasons[max(0, i - POOLED_EDITIONS + 1):i + 1] if pooled else [s]
                flag = flags.get((s.provider_league_id, s.season), {})
                prev_season = max((p[1] for p in known if p[0] == s.competition_id and p[1] < s.season), default=None)

                def previous(subject: str, _prev: int | None = prev_season, _cid: int = s.competition_id) -> Level | None:
                    return known.get((_cid, _prev, subject)) if _prev is not None else None

                base = {"phase": PHASE_ALL, "version": levels.RULES_VERSION, "at": now}
                for j, datum in enumerate(levels.DATA):
                    counts = levels.combine(Coverage(*_data_pair(data_counts.get(e.id), j)) for e in editions)
                    column = DECLARED_FLAG[datum]
                    declared = flag.get(column) if column else None
                    grade = apply_flag(levels.grade_datum(counts, previous=previous("d:" + datum)),
                                       declared if isinstance(declared, bool) else None, with_data=counts.with_data)
                    result = publish(grade, held.get((s.id, datum)))
                    _record(cur, UPSERT_CELL_SQL, "datum", s.id, datum, result, counts,
                            {**base, "n": counts.finished, "k": counts.with_data, "share": share(counts), "pooled": len(editions),
                             "declared": declared if isinstance(declared, bool) else None}, report)
                    known[(s.competition_id, s.season, "d:" + datum)] = inheritable(result)
                    report.cells += 1
                for market in levels.MARKETS:
                    parts = [market_counts.get((e.id, market), (0, 0, None, 0, 0)) for e in editions]
                    priced = levels.combine(Coverage(p[0], p[1]) for p in parts)
                    settle = levels.combine(Coverage(p[3], p[4]) for p in parts)
                    books = next((p[2] for p in reversed(parts) if p[2] is not None), None)
                    declared = flag.get("odds")
                    grade = levels.grade_market(priced, books, previous=previous("m:" + market))
                    if priced.finished == 0 and grade.reason == "muestra_insuficiente":
                        grade = Grade("MI", False, "sin_ventana")
                    grade = apply_flag(grade, declared if isinstance(declared, bool) else None, with_data=priced.with_data)
                    result = publish(grade, held.get((s.id, "m:" + market)))
                    catalogue = CATALOGUE_KEY[market]
                    _record(cur, UPSERT_MARKET_SQL, "market", s.id, market, result, priced,
                            {**base, "window": ODDS_WINDOW_START, "days": window_days, "n": priced.finished, "k": priced.with_data,
                             "share": share(priced), "books": None if books is None else round(books, 1),
                             "n_settle": settle.finished, "n_settleable": settle.with_data, "settle_share": share(settle),
                             "state": states.get(catalogue) if catalogue else None}, report)
                    known[(s.competition_id, s.season, "m:" + market)] = inheritable(result)
                    report.markets += 1
                if s.cup and not pooled:
                    _grade_phases(cur, s, phases, flag, base, report)
                report.graded += 1


@dataclass(slots=True)
class PhaseInputs:
    """What grading the phases of the cup seasons reads, in one go with the rest (PM-02-07)."""

    counts: dict[tuple[int, str], tuple[int, list[int]]] = field(default_factory=dict)
    """(competition season, phase) -> (finished matches, matches with each datum)."""
    held: dict[tuple[int, str, str], Published] = field(default_factory=dict)
    known: dict[tuple[int, int, str, str], Level | None] = field(default_factory=dict)
    """(competition, season, phase, datum) -> published level, None when not inheritable (rule 2 reads the season before)."""


def _phase_inputs(cur: psycopg.Cursor[Any], cups: list[Season]) -> PhaseInputs:
    out = PhaseInputs()
    if not cups:
        return out
    ids = [s.id for s in cups]
    cur.execute(ROUNDS_SQL, (ids,))
    per: dict[int, list[tuple[int, str | None, datetime]]] = {}
    for cs, fid, label, kickoff in cur.fetchall():
        per.setdefault(int(cs), []).append((int(fid), label, kickoff))
    fids: list[int] = []
    keys: list[str] = []
    for rows in per.values():
        for fid, phase in cup_phases(rows).items():
            fids.append(fid)
            keys.append(phase)
    if fids:
        cur.execute(COUNT_PHASE_DATA_SQL, (fids, keys))
        out.counts = {(int(r[0]), str(r[1])): (int(r[2]), [int(v) for v in r[3:]]) for r in cur.fetchall()}
    cur.execute(HELD_PHASE_CELLS_SQL, (ids, list(CUP_PHASES)))
    out.held = {(int(r[0]), str(r[1]), str(r[2])): Published(r[3], bool(r[4]), bool(r[5]), r[6]) for r in cur.fetchall()}
    cur.execute(PREVIOUS_PHASE_SQL, {"comps": sorted({s.competition_id for s in cups}), "phases": list(CUP_PHASES)})
    out.known = {(int(r[0]), int(r[1]), str(r[2]), str(r[3])): r[4] for r in cur.fetchall()}
    return out


def _grade_phases(cur: psycopg.Cursor[Any], s: Season, phases: PhaseInputs, flag: Mapping[str, Any], base: dict[str, Any],
                  report: Report) -> None:
    """The data cells of each phase of cup season ``s`` that has matches: the same rules as its ``todas`` (2 with the same phase of
    the season before, 4 against the phase's own published cell, 5 with the season's flag)."""
    for phase in CUP_PHASES:
        found = phases.counts.get((s.id, phase))
        if found is None:
            continue
        prev = max((k[1] for k in phases.known if k[0] == s.competition_id and k[2] == phase and k[1] < s.season), default=None)
        for j, datum in enumerate(levels.DATA):
            counts = Coverage(*_data_pair(found, j))
            column = DECLARED_FLAG[datum]
            declared = flag.get(column) if column else None
            before = phases.known.get((s.competition_id, prev, phase, datum)) if prev is not None else None
            grade = apply_flag(levels.grade_datum(counts, previous=before), declared if isinstance(declared, bool) else None,
                               with_data=counts.with_data)
            result = publish(grade, phases.held.get((s.id, phase, datum)))
            _record(cur, UPSERT_CELL_SQL, "datum", s.id, datum, result, counts,
                    {**base, "phase": phase, "n": counts.finished, "k": counts.with_data, "share": share(counts), "pooled": 1,
                     "declared": declared if isinstance(declared, bool) else None}, report)
            phases.known[(s.competition_id, s.season, phase, datum)] = inheritable(result)
            report.phase_cells += 1


def _data_pair(found: tuple[int, list[int]] | None, j: int) -> tuple[int, int]:
    if found is None:
        return 0, 0
    return found[0], found[1][j]


# ── the pass ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def measure_facts(conn: psycopg.Connection[Any], seasons: list[Season], *, now: datetime, full: bool, report: Report,
                  deadline: float) -> bool:
    """Measure the facts due of the matches of ``seasons``, one committed batch at a time. False when it stopped at the deadline."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TO_MEASURE_SQL, {"seasons": [s.id for s in seasons], "full": full, "now": now,
                                     "data_since": now - timedelta(days=DATA_REFRESH_DAYS), "window": ODDS_WINDOW_START})
        due = [(int(r[0]), int(r[1]), r[2], bool(r[3]), bool(r[4])) for r in cur.fetchall()]
    conn.commit()
    for start in range(0, len(due), BATCH):
        if time.monotonic() > deadline:
            return False
        batch = due[start:start + BATCH]
        data_ids = [b[0] for b in batch if b[3]]
        odds_ids = [b[0] for b in batch if b[4]]
        present, settles = measure_data(conn, data_ids) if data_ids else ({}, {})
        books = measure_books(conn, odds_ids)
        rows = []
        for fid, cs, kickoff, data_due, odds_due in batch:
            rows.append({"id": fid, "cs": cs, "kickoff": kickoff, "data": data_due, "present": present.get(fid, []),
                         "settles": settles.get(fid, []), "books": Jsonb(books[fid]) if odds_due else None,
                         "odds_at": now if odds_due else None, "version": levels.RULES_VERSION, "at": now})
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(UPSERT_FACTS_SQL, rows)
        report.facts += len(data_ids)
        report.odds_facts += len(odds_ids)
    return True


def complete(conn: psycopg.Connection[Any], seasons: list[Season], *, now: datetime) -> set[int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(COMPLETE_SQL, {"seasons": [s.id for s in seasons], "now": now, "window": ODDS_WINDOW_START})
        done = {int(r[0]) for r in cur.fetchall()}
    conn.commit()
    return done


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, full: bool | None = None, only: set[int] | None = None,
             max_seconds: float = MAX_SECONDS) -> Report:
    """One recalculation. ``full`` None: full on Sundays and until a full one completes that week (``full_due``). ``only``: the
    competitions of these competition seasons (manual runs)."""
    report = Report(full=full_due(conn, now) if full is None else full)
    started = time.monotonic()
    conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
    conn.commit()
    if not locked or not locked[0]:
        report.stopped = "otro_pase_en_curso"
        return report
    try:
        seasons = scope(conn, now=now, full=report.full, only=only)
        conn.commit()
        report.seasons = len(seasons)
        finished = measure_facts(conn, seasons, now=now, full=report.full, report=report, deadline=started + max_seconds)
        if not finished:
            report.stopped = "tiempo_agotado"
        done = complete(conn, seasons, now=now)
        # A competition is graded whole (rule 2 reads the season before): only when every one of its seasons in scope is complete.
        ready: list[Season] = []
        by_comp: dict[int, list[Season]] = {}
        for s in seasons:
            by_comp.setdefault(s.competition_id, []).append(s)
        for comp_seasons in by_comp.values():
            if all(s.id in done for s in comp_seasons):
                ready.extend(comp_seasons)
        grade_seasons(conn, ready, now=now, report=report)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
        report.seconds = time.monotonic() - started
    return report

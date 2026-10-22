"""Reading a competition season from the database, building its stages and ties, and writing them back (plan F2).

``fbi.competitions.seasons.build_season`` is pure: fixtures in, stages, ties and the slot of every fixture out. This module is
what runs it over the database:

* ``load_fixtures`` reads a season's fixtures with their result (``core.fixture_results``) and the provider's winner flags
  (``core.fixture_facts_latest``);
* ``build_one`` builds a season and, with ``apply``, writes it - the stages (``core.competition_stages``), the ties
  (``core.ties``) and the three columns of every fixture (``stage_id``, ``leg``, ``tie_id``) - in one transaction, under an
  advisory lock, and writes NOTHING when the digest of what it built is the one already stored (a rebuild that changes
  nothing costs one read; ``core.fixtures.updated_at`` is never touched, because other jobs read it as "this fixture changed");
* ``pending`` says which seasons are worth building now and ``refresh_pending`` builds them, a failure in one season never
  holding back the others. The worker runs it as the ``competition_structure`` job; ``python -m scripts.competition_stages``
  runs the same functions by hand (dry run by default).

The outcome columns of a tie (winner, aggregate) are post-match data. Nothing that decides or judges a pick before a match
reads them: the pre-match readers use ``fbi.competitions.context``, which answers "as of" a moment.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
import structlog
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.competitions import seasons as se
from fbi.competitions import stages as stg
from fbi.competitions import ties as tl

log = structlog.get_logger(__name__)

JOB: Final = "competition_structure"
LOCK_KEY: Final = "fbi.competition_stages"
WINDOW_BEFORE: Final = timedelta(days=4)
"""A season with a fixture this recent is read again on every pass: a result may still be corrected, and a tie still waiting for a
leg gives up after ``ties.SETTLED_AFTER_DAYS`` days - the build changes with the clock, not only with the data."""
WINDOW_AFTER: Final = timedelta(days=45)
"""... and one with a fixture this far ahead, because the provider adds, renames and reschedules the rounds to come."""

FIXTURES_SQL: Final = """
SELECT f.id AS fixture_id, f.round, f.home_team_id AS home, f.away_team_id AS away, f.kickoff_at, f.status_short AS status,
       r.goals_home, r.goals_away, r.ft_goals_home AS ft_home, r.ft_goals_away AS ft_away,
       r.et_goals_home AS et_home, r.et_goals_away AS et_away, r.pen_home, r.pen_away, w.home_winner, w.away_winner,
       r.settled_at
  FROM core.fixtures f
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN core.fixture_facts_latest w ON w.fixture_id = f.id
 WHERE f.competition_season_id = %(cs)s
 ORDER BY f.kickoff_at, f.id
"""

STORED_SQL: Final = """
SELECT id, stage,
       CASE WHEN stages_version = %(stages)s AND ties_version = %(ties)s THEN build_hash ELSE '' END AS build_hash
  FROM core.competition_stages WHERE competition_season_id = %(cs)s
"""
"""``build_hash`` reads as empty on a stage built by other versions of the rules, so that it never matches a digest."""

UPSERT_STAGES_SQL: Final = """
INSERT INTO core.competition_stages
       (competition_season_id, stage, ordinal, phase, base_stage, is_replay, kind, role, rule, numbered, round_key, teams,
        round_no, fixtures, first_kickoff_at, last_kickoff_at, tie_format, tie_reason, ties, stages_version, ties_version,
        build_hash, built_at)
SELECT %(cs)s, x.stage, x.ordinal, x.phase, x.base_stage, x.is_replay, x.kind, x.role, x.rule, x.numbered, x.round_key,
       x.teams, x.round_no, x.fixtures, x.first_kickoff_at, x.last_kickoff_at, x.tie_format, x.tie_reason, x.ties,
       x.stages_version, x.ties_version, x.build_hash, %(at)s
  FROM jsonb_to_recordset(%(rows)s) AS x(stage text, ordinal int, phase text, base_stage text, is_replay boolean, kind text,
       role text, rule text, numbered boolean, round_key text, teams int, round_no int, fixtures int,
       first_kickoff_at timestamptz, last_kickoff_at timestamptz, tie_format text, tie_reason text, ties int,
       stages_version text, ties_version text, build_hash text)
ON CONFLICT (competition_season_id, stage) DO UPDATE SET
       ordinal = EXCLUDED.ordinal, phase = EXCLUDED.phase, base_stage = EXCLUDED.base_stage,
       is_replay = EXCLUDED.is_replay, kind = EXCLUDED.kind, role = EXCLUDED.role, rule = EXCLUDED.rule,
       numbered = EXCLUDED.numbered, round_key = EXCLUDED.round_key, teams = EXCLUDED.teams,
       round_no = EXCLUDED.round_no, fixtures = EXCLUDED.fixtures, first_kickoff_at = EXCLUDED.first_kickoff_at,
       last_kickoff_at = EXCLUDED.last_kickoff_at, tie_format = EXCLUDED.tie_format, tie_reason = EXCLUDED.tie_reason,
       ties = EXCLUDED.ties, stages_version = EXCLUDED.stages_version, ties_version = EXCLUDED.ties_version,
       build_hash = EXCLUDED.build_hash, built_at = EXCLUDED.built_at
RETURNING id, stage
"""

UPSERT_TIES_SQL: Final = """
INSERT INTO core.ties
       (stage_id, team_a_id, team_b_id, format, status, legs, played, aggregate_a, aggregate_b, winner_team_id, decided_by,
        reason, decided_at, shootout_a, shootout_b, winner_check, flags, version, built_at)
SELECT x.stage_id, x.team_a_id, x.team_b_id, x.format, x.status, x.legs, x.played, x.aggregate_a, x.aggregate_b,
       x.winner_team_id, x.decided_by, x.reason, x.decided_at, x.shootout_a, x.shootout_b, x.winner_check,
       ARRAY(SELECT jsonb_array_elements_text(x.flags)), x.version, %(at)s
  FROM jsonb_to_recordset(%(rows)s) AS x(stage_id bigint, team_a_id bigint, team_b_id bigint, format text, status text,
       legs int, played int, aggregate_a int, aggregate_b int, winner_team_id bigint, decided_by text, reason text,
       decided_at timestamptz, shootout_a int, shootout_b int, winner_check text, flags jsonb, version text)
ON CONFLICT (stage_id, LEAST(team_a_id, team_b_id), GREATEST(team_a_id, team_b_id)) DO UPDATE SET
       team_a_id = EXCLUDED.team_a_id, team_b_id = EXCLUDED.team_b_id, format = EXCLUDED.format, status = EXCLUDED.status,
       legs = EXCLUDED.legs, played = EXCLUDED.played, aggregate_a = EXCLUDED.aggregate_a,
       aggregate_b = EXCLUDED.aggregate_b, winner_team_id = EXCLUDED.winner_team_id, decided_by = EXCLUDED.decided_by,
       reason = EXCLUDED.reason, decided_at = EXCLUDED.decided_at, shootout_a = EXCLUDED.shootout_a,
       shootout_b = EXCLUDED.shootout_b, winner_check = EXCLUDED.winner_check, flags = EXCLUDED.flags,
       version = EXCLUDED.version, built_at = EXCLUDED.built_at
RETURNING id, stage_id, team_a_id, team_b_id
"""

UPDATE_FIXTURES_SQL: Final = """
UPDATE core.fixtures f SET stage_id = v.stage_id, leg = v.leg, tie_id = v.tie_id
  FROM unnest(%(ids)s::bigint[], %(stages)s::bigint[], %(legs)s::smallint[], %(ties)s::bigint[])
       AS v(id, stage_id, leg, tie_id)
 WHERE f.id = v.id AND (f.stage_id, f.leg, f.tie_id) IS DISTINCT FROM (v.stage_id, v.leg, v.tie_id)
"""

DELETE_TIES_SQL: Final = """
DELETE FROM core.ties t USING core.competition_stages s
 WHERE t.stage_id = s.id AND s.competition_season_id = %(cs)s AND t.id <> ALL(%(keep)s::bigint[])
"""

DELETE_STAGES_SQL: Final = """
DELETE FROM core.competition_stages WHERE competition_season_id = %(cs)s AND id <> ALL(%(keep)s::bigint[])
"""


@dataclass(slots=True)
class SeasonReport:
    """What building one season did (or, in a dry run, would do)."""

    competition_season_id: int
    fixtures: int = 0
    stages: int = 0
    ties: int = 0
    first_build: bool = False
    changed: bool = False
    """The stored rows were rewritten (in a dry run: would be)."""
    fixtures_updated: int = 0
    stages_removed: int = 0
    ties_removed: int = 0
    ties_by_status: Counter[str] = field(default_factory=Counter)
    contradicted: int = 0
    unresolved_fixtures: int = 0
    """Fixtures in a stage whose label no rule reads."""
    digest: str = ""


@dataclass(slots=True)
class BuildReport:
    """What a pass over several seasons did."""

    seasons: int = 0
    changed: int = 0
    unchanged: int = 0
    failed: int = 0
    first_builds: int = 0
    stages: int = 0
    ties: int = 0
    """Stages and ties of every season read (the whole picture)."""
    rows_written: int = 0
    """Stage and tie rows of the seasons that were rewritten."""
    fixtures_updated: int = 0
    contradicted: int = 0
    ties_by_status: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    stopped_for_time: bool = False
    seasons_left: int = 0

    def add(self, r: SeasonReport) -> None:
        self.seasons += 1
        self.changed += r.changed
        self.unchanged += not r.changed
        self.first_builds += r.first_build
        self.stages += r.stages
        self.ties += r.ties
        self.rows_written += (r.stages + r.ties) if r.changed else 0
        self.fixtures_updated += r.fixtures_updated
        self.contradicted += r.contradicted
        self.ties_by_status.update(r.ties_by_status)

    def as_dict(self) -> dict[str, Any]:
        return {"seasons": self.seasons, "changed": self.changed, "unchanged": self.unchanged, "failed": self.failed,
                "first_builds": self.first_builds, "stages": self.stages, "ties": self.ties,
                "rows_written": self.rows_written, "fixtures_updated": self.fixtures_updated,
                "contradicted": self.contradicted,
                "ties_by_status": dict(self.ties_by_status), "stopped_for_time": self.stopped_for_time,
                "seasons_left": self.seasons_left, "errors": self.errors[:5]}


# ── reading ─────────────────────────────────────────────────────────────────


def load_fixtures(conn: psycopg.Connection[Any], competition_season_id: int) -> list[se.SeasonFixture]:
    """The fixtures of one competition season as the readers need them."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"cs": competition_season_id})
        return [se.SeasonFixture(**row) for row in cur.fetchall()]


def _stored(conn: psycopg.Connection[Any], competition_season_id: int) -> dict[str, tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute(STORED_SQL, {"cs": competition_season_id, "stages": stg.VERSION, "ties": tl.VERSION})
        return {str(stage): (int(stage_id), str(build_hash)) for stage_id, stage, build_hash in cur.fetchall()}


# ── writing ─────────────────────────────────────────────────────────────────


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.isoformat()


def stage_rows(build: se.SeasonBuild, digest: str) -> list[dict[str, Any]]:
    """The rows of ``core.competition_stages`` for a build, in the order the stages begin."""
    ordered = sorted(build.stages.items(), key=lambda kv: (kv[1].first_kickoff_at, kv[0]))
    rows: list[dict[str, Any]] = []
    for ordinal, (name, rec) in enumerate(ordered, 1):
        g = rec.reading
        rows.append({
            "stage": name, "ordinal": ordinal, "phase": g.phase, "base_stage": g.base, "is_replay": g.replay,
            "kind": g.kind, "role": g.role, "rule": g.rule, "numbered": g.numbered, "round_key": g.round_key,
            "teams": g.teams, "round_no": g.round_no, "fixtures": rec.fixtures,
            "first_kickoff_at": _iso(rec.first_kickoff_at), "last_kickoff_at": _iso(rec.last_kickoff_at),
            "tie_format": rec.tie_format, "tie_reason": rec.tie_reason, "ties": rec.ties,
            "stages_version": stg.VERSION, "ties_version": tl.VERSION, "build_hash": digest})
    return rows


def tie_row(t: tl.Tie, stage_id: int) -> dict[str, Any]:
    """One row of ``core.ties``."""
    return {
        "stage_id": stage_id, "team_a_id": t.team_a, "team_b_id": t.team_b, "format": t.format, "status": t.status,
        "legs": len(t.legs), "played": t.played, "aggregate_a": t.aggregate_a, "aggregate_b": t.aggregate_b,
        "winner_team_id": t.winner, "decided_by": t.decided_by, "reason": t.reason, "decided_at": _iso(t.decided_at),
        "shootout_a": t.shootout[0] if t.shootout else None, "shootout_b": t.shootout[1] if t.shootout else None,
        "winner_check": t.check, "flags": sorted(t.flags), "version": tl.VERSION}


def _summary(build: se.SeasonBuild, report: SeasonReport) -> None:
    report.stages = len(build.stages)
    report.ties = len(build.ties)
    report.ties_by_status = Counter(t.status for t in build.ties)
    report.contradicted = sum(1 for t in build.ties if t.check == "contradicted")
    report.unresolved_fixtures = sum(r.fixtures for r in build.stages.values() if not r.reading.resolved)


def _write(conn: psycopg.Connection[Any], cs_id: int, build: se.SeasonBuild, digest: str, at: datetime,
           report: SeasonReport) -> None:
    keys = [(t.stage, *t.key) for t in build.ties]
    if len(set(keys)) != len(keys):
        raise ValueError(f"season {cs_id}: two ties with the same stage and pair")
    with conn.cursor() as cur:
        cur.execute(UPSERT_STAGES_SQL, {"cs": cs_id, "rows": Jsonb(stage_rows(build, digest)), "at": at})
        stage_ids = {str(stage): int(stage_id) for stage_id, stage in cur.fetchall()}

        tie_ids: dict[tuple[str, int, int], int] = {}
        if build.ties:
            rows = [tie_row(t, stage_ids[t.stage]) for t in build.ties]
            cur.execute(UPSERT_TIES_SQL, {"rows": Jsonb(rows), "at": at})
            by_id = {v: k for k, v in stage_ids.items()}
            for tie_id, stage_id, a, b in cur.fetchall():
                tie_ids[(by_id[int(stage_id)], min(int(a), int(b)), max(int(a), int(b)))] = int(tie_id)

        ids = sorted(build.slots)
        stages: list[int | None] = []
        legs: list[int | None] = []
        ties: list[int | None] = []
        for fixture_id in ids:
            slot = build.slots[fixture_id]
            stages.append(stage_ids[slot.stage])
            legs.append(slot.leg)
            ties.append(tie_ids[slot.tie] if slot.tie is not None else None)
        cur.execute(UPDATE_FIXTURES_SQL, {"ids": ids, "stages": stages, "legs": legs, "ties": ties})
        report.fixtures_updated = cur.rowcount

        cur.execute(DELETE_TIES_SQL, {"cs": cs_id, "keep": list(tie_ids.values())})
        report.ties_removed = cur.rowcount
        cur.execute(DELETE_STAGES_SQL, {"cs": cs_id, "keep": list(stage_ids.values())})
        report.stages_removed = cur.rowcount


def _read(conn: psycopg.Connection[Any], competition_season_id: int, now: datetime
          ) -> tuple[se.SeasonBuild, SeasonReport, dict[str, tuple[int, str]]]:
    """Build the season in memory and say how it compares with what is stored."""
    report = SeasonReport(competition_season_id)
    rows = load_fixtures(conn, competition_season_id)
    build = se.build_season(rows, now=now)
    report.fixtures = len(rows)
    report.digest = se.fingerprint(build)
    stored = _stored(conn, competition_season_id)
    _summary(build, report)
    report.first_build = not stored and bool(build.stages)
    return build, report, stored


def _differs(build: se.SeasonBuild, report: SeasonReport, stored: dict[str, tuple[int, str]]) -> bool:
    """The stored rows are not the ones this build would write: another set of stages, or another digest."""
    return set(stored) != set(build.stages) or any(h != report.digest for _, h in stored.values())


def build_one(conn: psycopg.Connection[Any], competition_season_id: int, *, now: datetime, apply: bool = True,
              force: bool = False) -> SeasonReport:
    """Build one competition season. With ``apply`` the stored rows are brought up to date in one transaction (under an
    advisory lock, so the worker and a person at the console never write the same season at once); without it nothing is
    written and the report says what would change. ``force`` rewrites even when the stored digest is the one just computed.

    The caller commits (a connection that already holds a transaction keeps it: this runs inside a savepoint)."""
    if not apply:
        build, report, stored = _read(conn, competition_season_id, now)
        report.changed = force or _differs(build, report, stored)
        return report
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), %s::int)", (LOCK_KEY, competition_season_id))
        build, report, stored = _read(conn, competition_season_id, now)
        if not (force or _differs(build, report, stored)):
            return report
        _write(conn, competition_season_id, build, report.digest, now, report)
        report.changed = True
    return report


# ── which seasons ───────────────────────────────────────────────────────────

PENDING_SQL: Final = """
WITH recent AS (
    SELECT f.competition_season_id AS cs,
           min(abs(extract(epoch FROM f.kickoff_at - %(now)s::timestamptz)))::float8 AS distance
      FROM core.fixtures f
     WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
     GROUP BY f.competition_season_id
), never AS (
    SELECT s.id AS cs FROM core.competition_seasons s
     WHERE NOT EXISTS (SELECT 1 FROM core.competition_stages x WHERE x.competition_season_id = s.id)
       AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id)
), old_rules AS (
    SELECT DISTINCT competition_season_id AS cs FROM core.competition_stages
     WHERE stages_version <> %(stages)s OR ties_version <> %(ties)s
), everything AS (
    SELECT s.id AS cs FROM core.competition_seasons s
     WHERE %(everything)s AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id)
)
SELECT cs, 0 AS priority, 0::float8 AS distance FROM never
UNION SELECT cs, 1, 0 FROM old_rules
UNION SELECT cs, 2, distance FROM recent
UNION SELECT cs, 3, 0 FROM everything
ORDER BY 2, 3, 1
"""


def pending(conn: psycopg.Connection[Any], *, now: datetime, everything: bool = False) -> list[int]:
    """The seasons worth building now: those never built, those built by older rules, and those with a fixture near enough to
    now to have changed (see ``WINDOW_BEFORE``) - the closest to now first, so that a pass cut short by its time budget has read
    the matches that are being played - each once. ``everything`` adds, last, every other season that has a fixture: the daily
    sweep, which finds a result corrected long after its season left the window."""
    with conn.cursor() as cur:
        cur.execute(PENDING_SQL, {"now": now, "since": now - WINDOW_BEFORE, "until": now + WINDOW_AFTER,
                                  "stages": stg.VERSION, "ties": tl.VERSION, "everything": everything})
        seen: dict[int, None] = {}
        for cs, _priority, _distance in cur.fetchall():
            seen.setdefault(int(cs), None)
    return list(seen)


def _recover(conn: psycopg.Connection[Any]) -> None:
    """A season that failed inside its own transaction block was already rolled back (to its savepoint, when the caller holds
    a transaction). Only a connection left in an aborted transaction by something outside that block needs more."""
    if conn.info.transaction_status == TransactionStatus.INERROR:
        conn.rollback()


def _guarded(conn: psycopg.Connection[Any], cs_id: int, report: BuildReport, *, now: datetime, apply: bool,
             force: bool, commit: bool) -> SeasonReport | None:
    """Build one season; a failure is rolled back, logged and recorded in ``report`` (and ``None`` is returned)."""
    try:
        one = build_one(conn, cs_id, now=now, apply=apply, force=force)
        if commit and apply:
            conn.commit()
        return one
    except psycopg.Error as exc:
        if conn.closed:
            raise
        _recover(conn)
        message = f"season {cs_id}: {type(exc).__name__}: {str(exc)[:300]}"
        report.failed += 1
        report.errors.append(message)
        log.warning("competition_structure.season_failed", season=cs_id, error=message[:300])
    except ValueError as exc:  # the build refused its own output: a defect, said loudly, never a half-written season
        _recover(conn)
        report.failed += 1
        report.errors.append(f"season {cs_id}: {exc}")
        log.error("competition_structure.refused", season=cs_id, error=str(exc)[:300])
    return None


def build_many(conn: psycopg.Connection[Any], seasons: Iterable[int], *, now: datetime, apply: bool = True,
               force: bool = False, max_seconds: float | None = None, commit: bool = True,
               progress: Callable[[int, int], None] | None = None) -> BuildReport:
    """Build the seasons one after the other, each in its own transaction. A season that fails is rolled back, logged and
    reported; the others go on. ``max_seconds`` stops between seasons (``seasons_left`` says how many were not reached);
    ``progress(done, total)`` is called after each season."""
    report = BuildReport()
    started = time.monotonic()
    queue = list(seasons)
    for index, cs_id in enumerate(queue):
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            report.stopped_for_time = True
            report.seasons_left = len(queue) - index
            break
        one = _guarded(conn, cs_id, report, now=now, apply=apply, force=force, commit=commit)
        if one is not None:
            report.add(one)
            if one.changed and apply:
                log.info("competition_structure.built", season=cs_id, stages=one.stages, ties=one.ties,
                         fixtures_updated=one.fixtures_updated, first=one.first_build, contradicted=one.contradicted)
        if progress is not None:
            progress(index + 1, len(queue))
    return report


def refresh_pending(conn: psycopg.Connection[Any], *, now: datetime, max_seconds: float | None = None,
                   limit: int | None = None, commit: bool = True, everything: bool = False) -> BuildReport:
    """One pass of the worker's job: the pending seasons, up to ``limit`` of them and ``max_seconds`` of work (``everything``:
    and then all the others - see ``pending``)."""
    queue = pending(conn, now=now, everything=everything)
    if commit:
        conn.commit()
    if limit is not None:
        queue = queue[:limit]
    return build_many(conn, queue, now=now, apply=True, max_seconds=max_seconds, commit=commit)


def run_job(conn: psycopg.Connection[Any], *, now: datetime, max_seconds: float = 120.0, limit: int | None = 400,
            commit: bool = True, everything: bool = False) -> BuildReport:
    """The scheduled job: a pass of ``refresh_pending`` as a ledger run - but only when it changed or broke something, so a
    quiet hour leaves no row in the ledger. The worker runs it every few minutes with a budget, and once a day with
    ``everything`` (no limit, a longer budget): the sweep that reads every season, whatever its age."""
    from fbi.ingestion.ledger import RunCounters, RunLedger

    report = refresh_pending(conn, now=now, max_seconds=max_seconds, limit=limit, commit=commit, everything=everything)
    if commit:
        conn.commit()
    if everything:
        log.info("competition_structure.sweep", seasons=report.seasons, changed=report.changed, failed=report.failed,
                 left=report.seasons_left)
    if not (report.changed or report.failed):
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"limit": limit, "max_seconds": max_seconds, "stages": stg.VERSION, "ties": tl.VERSION,
                                      "sweep": everything})
    counters = RunCounters()
    counters.rows_inserted = report.rows_written
    counters.rows_updated = report.fixtures_updated
    counters.rows_normalized = report.seasons
    counters.errors.extend(report.errors[:5])
    if report.stopped_for_time:
        counters.stopped_early = f"time budget of {max_seconds:g} s reached: {report.seasons_left} seasons left for the next pass"
    ledger.close(run_id, counters, notes=str(report.as_dict())[:2000])
    return report


# ── what is stored, checked from the outside ────────────────────────────────

COVERAGE_SQL: Final = """
SELECT count(*) AS fixtures, count(f.stage_id) AS with_stage,
       count(*) FILTER (WHERE s.kind = 'unresolved') AS unresolved,
       count(*) FILTER (WHERE s.kind IN ('knockout', 'qualifying')) AS in_ties,
       count(f.tie_id) AS with_tie
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.competition_stages s ON s.id = f.stage_id
 WHERE (%(tracked_only)s = false OR c.is_tracked)
   AND (%(seasons)s::bigint[] IS NULL OR f.competition_season_id = ANY(%(seasons)s::bigint[]))
"""

AGGREGATE_SUMS_SQL: Final = """
WITH legs AS (
    SELECT t.id AS tie_id, t.team_a_id, t.team_b_id, t.aggregate_a, t.aggregate_b, t.flags, f.home_team_id,
           (f.status_short IN ('FT', 'AET', 'PEN', 'AWD', 'WO') AND r.goals_home IS NOT NULL
              AND r.goals_away IS NOT NULL) AS scored,
           r.goals_home, r.goals_away
      FROM core.ties t
      JOIN core.fixtures f ON f.tie_id = t.id
      LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE t.format IN ('single', 'two_legged') AND t.played >= 1
       AND (%(seasons)s::bigint[] IS NULL OR f.competition_season_id = ANY(%(seasons)s::bigint[]))
), sums AS (
    SELECT tie_id, aggregate_a, aggregate_b, flags, count(*) AS legs, count(*) FILTER (WHERE scored) AS scored,
           sum(CASE WHEN home_team_id = team_a_id THEN goals_home ELSE goals_away END) FILTER (WHERE scored) AS a,
           sum(CASE WHEN home_team_id = team_b_id THEN goals_home ELSE goals_away END) FILTER (WHERE scored) AS b
      FROM legs GROUP BY tie_id, aggregate_a, aggregate_b, flags
)
"""

_NO_AGGREGATE_BY_DESIGN: Final = (
    "(aggregate_a IS NULL AND (legs <> scored OR 'score_inconsistent_with_shootout' = ANY(flags)))")
_AGGREGATE_MISSING: Final = (
    "(aggregate_a IS NULL AND legs = scored AND NOT 'score_inconsistent_with_shootout' = ANY(flags))")
_AGGREGATE_DIFFERENT: Final = (
    "(aggregate_a IS NOT NULL AND NOT 'score_repaired' = ANY(flags) AND (a IS DISTINCT FROM aggregate_a "
    "OR b IS DISTINCT FROM aggregate_b))")

AGGREGATE_SQL: Final = AGGREGATE_SUMS_SQL + f"""
SELECT count(*) AS checked,
       count(*) FILTER (WHERE 'score_repaired' = ANY(flags)) AS repaired,
       count(*) FILTER (WHERE {_NO_AGGREGATE_BY_DESIGN}) AS unknown,
       count(*) FILTER (WHERE {_AGGREGATE_MISSING}) AS missing,
       count(*) FILTER (WHERE {_AGGREGATE_DIFFERENT}) AS different
  FROM sums
"""

AGGREGATE_DIFFERENCES_SQL: Final = AGGREGATE_SUMS_SQL + f"""
SELECT tie_id, aggregate_a AS stored_a, aggregate_b AS stored_b, a AS summed_a, b AS summed_b,
       CASE WHEN aggregate_a IS NULL THEN 'missing' ELSE 'different' END AS kind
  FROM sums WHERE {_AGGREGATE_MISSING} OR {_AGGREGATE_DIFFERENT}
 ORDER BY tie_id LIMIT %(limit)s
"""


def coverage(conn: psycopg.Connection[Any], *, tracked_only: bool = True,
             seasons: Sequence[int] | None = None) -> dict[str, int]:
    """How much of the fixtures table has a stage (and a tie where it should)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE_SQL, {"tracked_only": tracked_only, "seasons": None if seasons is None else list(seasons)})
        return {k: int(v) for k, v in (cur.fetchone() or {}).items()}


def aggregate_check(conn: psycopg.Connection[Any], *, seasons: Sequence[int] | None = None) -> dict[str, int]:
    """The stored aggregate of every single and two-legged tie against the sum of its legs' goals, recomputed in SQL from
    ``core.fixture_results`` without the builder's code. ``different``: a stored aggregate that is not that sum;
    ``missing``: no aggregate although every leg has a score; ``unknown``: no aggregate by design (a leg awarded without a
    score, or a shoot-out the goals contradict); ``repaired``: the builder repaired the provider's extra-time score, so the
    sum of the stored goals is not what it stored."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AGGREGATE_SQL, {"seasons": None if seasons is None else list(seasons)})
        return {k: int(v) for k, v in (cur.fetchone() or {}).items()}


def aggregate_differences(conn: psycopg.Connection[Any], *, seasons: Sequence[int] | None = None,
                          limit: int = 25) -> list[dict[str, Any]]:
    """The ties ``aggregate_check`` counts as different or missing: the stored aggregate and the one summed from the legs."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AGGREGATE_DIFFERENCES_SQL, {"seasons": None if seasons is None else list(seasons), "limit": limit})
        return list(cur.fetchall())


def drift(conn: psycopg.Connection[Any], seasons: Sequence[int], *, now: datetime) -> list[int]:
    """The seasons whose stored digest is not the digest of a build made now: stale rows, or never built."""
    stale: list[int] = []
    for cs_id in seasons:
        one = build_one(conn, cs_id, now=now, apply=False)
        if one.changed:
            stale.append(cs_id)
    return stale

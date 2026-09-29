"""The data-quality sweep: look for the things we know can go wrong, and record them.

Every check here reports its DENOMINATOR as well as its offenders, into
``audit.data_quality_checks``, and opens one issue per offending entity in
``audit.data_quality_issues``. Two rules follow from the mandate and shape all of
it:

  * nothing is repaired. A duplicate, an impossible value, a result that cannot
    be derived: recorded, never quietly corrected.
  * no percentage is invented. A check whose population cannot be established
    reports ``population = None``, which is not zero and is not a hundred per cent.

The checks are deliberately boring SQL over what is stored. They are cheap enough
to run nightly, and idempotent: an issue already open has its occurrence count
bumped rather than being written again.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.quality.issues import (
    EntityType,
    IssueCode,
    IssueRegistry,
    QualityIssue,
    Severity,
    issues_from,
    record_check,
)

log = structlog.get_logger(__name__)


@dataclass
class CheckOutcome:
    name: str
    scope: str
    severity: Severity
    population: int | None
    offenders: int
    issues: list[QualityIssue] = field(default_factory=list)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.offenders == 0

    @property
    def ratio(self) -> float | None:
        """Offenders over population, or None when there is no denominator."""
        if self.population in (None, 0):
            return None
        assert self.population is not None
        return self.offenders / self.population


@dataclass
class SweepReport:
    checks: list[CheckOutcome] = field(default_factory=list)
    issues_opened: int = 0
    issues_seen_again: int = 0

    @property
    def offenders(self) -> int:
        return sum(c.offenders for c in self.checks)

    @property
    def failed(self) -> list[CheckOutcome]:
        return [c for c in self.checks if not c.passed]

    def as_dict(self) -> dict[str, Any]:
        return {"checks": len(self.checks), "failed": len(self.failed), "offenders": self.offenders,
                "issues_opened": self.issues_opened, "issues_seen_again": self.issues_seen_again}


def _scalar(conn: psycopg.Connection, sql: str, params: Sequence[Any] = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _rows(conn: psycopg.Connection, sql: str, params: Sequence[Any] = (),
          limit: int = 500) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchmany(limit)]


# ── results ─────────────────────────────────────────────────────────────────

UNRESOLVED_RESULT_SQL = """
SELECT f.id AS fixture_id, f.provider_fixture_id, f.status_short,
       r.goals_home, r.goals_away, r.et_goals_home, r.pen_home, r.pen_away,
       (r.fixture_id IS NULL) AS no_result
  FROM core.fixtures f
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.status_group = 'finished'
   AND (r.fixture_id IS NULL
        OR (f.status_short IN ('AET','PEN') AND r.et_goals_home IS NULL))
 ORDER BY f.kickoff_at DESC
"""


def check_results_are_resolved(conn: psycopg.Connection) -> CheckOutcome:
    """A finished match whose regulation result cannot be derived.

    Two shapes, and neither is repairable from what we hold:

      * finished with no result row at all;
      * decided after extra time (AET) or on penalties (PEN) with no extra-time
        score. ``reg_goals_*`` is ``goals - COALESCE(et_goals, 0)``, so with the
        extra-time score missing it EQUALS the after-extra-time score. Settling a
        90-minute market on that would count extra-time goals as regulation goals.

    The score is NOT invented and the penalty shoot-out is NOT turned into a
    90-minute result. The fixture is recorded as RESULT_UNRESOLVED and left alone.
    """
    population = _scalar(conn, "SELECT count(*) FROM core.fixtures WHERE status_group = 'finished'")
    rows = _rows(conn, UNRESOLVED_RESULT_SQL)
    offenders = _scalar(conn, f"SELECT count(*) FROM ({UNRESOLVED_RESULT_SQL}) AS q")
    issues: list[QualityIssue] = []
    for r in rows:
        if r["no_result"]:
            field_name, observed, detail = "goals_home", None, (
                f"status {r['status_short']} but no row in core.fixture_results")
        else:
            field_name = "et_goals_home"
            observed = f"{r['goals_home']}-{r['goals_away']}"
            detail = (f"status {r['status_short']} with no extra-time score: the 90-minute result "
                      f"cannot be derived from {observed}, so it is not derived")
        issues.append(QualityIssue(
            code=IssueCode.RESULT_UNRESOLVED, entity_type=EntityType.FIXTURE_RESULT,
            severity=Severity.ERROR, entity_id=int(r["fixture_id"]),
            provider_entity_id=int(r["provider_fixture_id"]), field=field_name,
            observed=observed, expected="a derivable 90-minute score", detail=detail,
        ))
    return CheckOutcome("results_are_resolved", "finished_fixtures", Severity.ERROR, population,
                        offenders, issues,
                        detail=f"{offenders} of {population} finished fixtures cannot be settled")


# ── line-ups ────────────────────────────────────────────────────────────────

SHORT_LINEUP_SQL = """
SELECT l.fixture_id, l.team_side, f.provider_fixture_id, l.provider_coach_id,
       count(*) FILTER (WHERE lp.is_starter) AS starters,
       count(*) AS named
  FROM core.fixture_lineups l
  JOIN core.fixtures f ON f.id = l.fixture_id
  LEFT JOIN core.fixture_lineup_players lp
         ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.source = 'api-football'
 GROUP BY l.fixture_id, l.team_side, f.provider_fixture_id, l.provider_coach_id
HAVING count(*) FILTER (WHERE lp.is_starter) <> 11
 ORDER BY count(*) FILTER (WHERE lp.is_starter)
"""


def check_lineups_are_complete(conn: psycopg.Connection) -> CheckOutcome:
    """A line-up with anything other than eleven starters.

    Not padded and not discarded: eleven is what a line-up means, so a different
    number is a fact about the provider's payload, recorded with the count that
    actually arrived.
    """
    population = _scalar(conn, "SELECT count(*) FROM core.fixture_lineups WHERE source = 'api-football'")
    rows = _rows(conn, SHORT_LINEUP_SQL)
    offenders = _scalar(conn, f"SELECT count(*) FROM ({SHORT_LINEUP_SQL}) AS q")
    issues = [
        QualityIssue(
            code=IssueCode.INCOMPLETE_LINEUP, entity_type=EntityType.LINEUP, severity=Severity.WARNING,
            entity_id=int(r["fixture_id"]), provider_entity_id=r["provider_coach_id"],
            field="starters", observed=int(r["starters"]), expected="11",
            detail=f"the {r['team_side']} line-up names {r['named']} players, "
                   f"{r['starters']} of them starters; stored as received",
        )
        for r in rows
    ]
    return CheckOutcome("lineups_are_complete", "api_football_lineups", Severity.WARNING, population,
                        offenders, issues)


# ── detail coverage ─────────────────────────────────────────────────────────

MISSING_DETAIL_SQL = """
SELECT f.id AS fixture_id, f.provider_fixture_id, c.provider_league_id, cs.season
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.status_group = 'finished'
   AND NOT EXISTS (SELECT 1 FROM core.fixture_detail_coverage cov WHERE cov.fixture_id = f.id)
 ORDER BY f.kickoff_at DESC
"""


def check_detail_has_been_fetched(conn: psycopg.Connection) -> CheckOutcome:
    """A played fixture whose detail has never been fetched at all.

    Deliberately NOT "a fixture with no events": a league-season the provider does
    not cover for events has a coverage row saying the block was absent, and that
    is an answer, not a gap.
    """
    population = _scalar(conn, "SELECT count(*) FROM core.fixtures WHERE status_group = 'finished'")
    rows = _rows(conn, MISSING_DETAIL_SQL)
    offenders = _scalar(conn, f"SELECT count(*) FROM ({MISSING_DETAIL_SQL}) AS q")
    issues = [
        QualityIssue(
            code=IssueCode.MISSING_DETAIL, entity_type=EntityType.FIXTURE, severity=Severity.WARNING,
            entity_id=int(r["fixture_id"]), provider_entity_id=int(r["provider_fixture_id"]),
            field="detail", observed=None, expected="a detail payload",
            detail=f"league {r['provider_league_id']} season {r['season']}: played and never "
                   "asked for; one /fixtures?ids= request covers twenty of these",
        )
        for r in rows
    ]
    return CheckOutcome("detail_has_been_fetched", "finished_fixtures", Severity.WARNING, population,
                        offenders, issues)


# ── impossible and contradictory values ─────────────────────────────────────

IMPOSSIBLE_STATS_SQL = """
SELECT s.fixture_id, f.provider_fixture_id, s.team_side, s.shots, s.shots_on_target,
       s.passes, s.passes_accurate, s.possession_pct
  FROM core.fixture_team_stats s
  JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.source = 'api-football'
   AND (s.possession_pct IS NOT NULL AND (s.possession_pct < 1 OR s.possession_pct > 99))
 ORDER BY s.fixture_id
"""

TIMELINE_SQL = """
SELECT e.fixture_id, f.provider_fixture_id, max(e.minute) AS last_minute, count(*) AS events
  FROM core.fixture_events e
  JOIN core.fixtures f ON f.id = e.fixture_id
 WHERE e.source = 'api-football'
 GROUP BY e.fixture_id, f.provider_fixture_id
HAVING max(e.minute) > 130
 ORDER BY max(e.minute) DESC
"""


def check_values_are_possible(conn: psycopg.Connection) -> CheckOutcome:
    """Values that cannot be right whatever the match was.

    The contradictions the schema already refuses (a part exceeding its whole) are
    caught at the boundary and recorded there. This looks for what the schema
    allows and football does not: possession outside 1..99, an event after the
    130th minute.

    ``population`` is None on purpose. The check spans two populations - statistics
    rows and event rows - so there is no single denominator, and picking one of them
    would turn the offender count into a ratio that means nothing. NULL says "no
    denominator", which the schema distinguishes from zero.
    """
    issues: list[QualityIssue] = []
    for r in _rows(conn, IMPOSSIBLE_STATS_SQL):
        issues.append(QualityIssue(
            code=IssueCode.PROVIDER_INCONSISTENCY, entity_type=EntityType.TEAM_STATISTICS,
            severity=Severity.WARNING, entity_id=int(r["fixture_id"]),
            provider_entity_id=int(r["provider_fixture_id"]), field="possession_pct",
            observed=r["possession_pct"], expected="between 1 and 99",
            detail=f"the {r['team_side']} side is reported with {r['possession_pct']}% possession",
        ))
    for r in _rows(conn, TIMELINE_SQL):
        issues.append(QualityIssue(
            code=IssueCode.PROVIDER_INCONSISTENCY, entity_type=EntityType.MATCH_EVENT,
            severity=Severity.WARNING, entity_id=int(r["fixture_id"]),
            provider_entity_id=int(r["provider_fixture_id"]), field="minute",
            observed=int(r["last_minute"]), expected="at most 130",
            detail=f"an event is timed at minute {r['last_minute']} among {r['events']} events",
        ))
    return CheckOutcome("values_are_possible", "api_football_detail", Severity.WARNING, None,
                        len(issues), issues)


# ── stale data ──────────────────────────────────────────────────────────────

STALE_AFTER = timedelta(hours=6)
"""Long enough for extra time, penalties and a substantial delay."""

STALE_RESULT_SQL = """
SELECT f.id AS fixture_id, f.provider_fixture_id, f.kickoff_at, f.status_short
  FROM core.fixtures f
 WHERE f.status_group IN ('scheduled','live')
   AND f.kickoff_at < %s
 ORDER BY f.kickoff_at
"""


def check_results_are_not_stale(conn: psycopg.Connection) -> CheckOutcome:
    """A fixture whose kick-off is six hours past and which is still not finished.

    Ours, not the provider's: it means the result sync has not run or has not
    reached it.

    The reference instant comes from the platform's clock, not the database's, so
    a sweep is reproducible and testable - the same reason every other time-aware
    part of the system reads fbi.core.clock.
    """
    cutoff = now() - STALE_AFTER
    population = _scalar(conn, "SELECT count(*) FROM core.fixtures "
                               "WHERE status_group IN ('scheduled','live')")
    rows = _rows(conn, STALE_RESULT_SQL, (cutoff,))
    offenders = _scalar(conn, f"SELECT count(*) FROM ({STALE_RESULT_SQL}) AS q", (cutoff,))
    issues = [
        QualityIssue(
            code=IssueCode.STALE_DATA, entity_type=EntityType.FIXTURE, severity=Severity.WARNING,
            entity_id=int(r["fixture_id"]), provider_entity_id=int(r["provider_fixture_id"]),
            field="status_short", observed=r["status_short"],
            expected="a finished status six hours after kick-off",
            detail=f"kicked off at {r['kickoff_at']:%Y-%m-%d %H:%M}Z and is still {r['status_short']}",
        )
        for r in rows
    ]
    return CheckOutcome("results_are_not_stale", "unfinished_fixtures", Severity.WARNING, population,
                        offenders, issues)


# ── lineage ─────────────────────────────────────────────────────────────────

ORPHAN_NEAR_CLOSE_SQL = """
SELECT n.fixture_id, n.market_key, n.selection, n.line, n.captured_at
  FROM market.near_close_snapshots n
 WHERE NOT EXISTS (
        SELECT 1 FROM market.odds_snapshots o
         WHERE o.fixture_id = n.fixture_id AND o.bookmaker_id = n.bookmaker_id
           AND o.market_key = n.market_key AND o.selection = n.selection
           AND o.line = n.line AND o.captured_at = n.captured_at)
"""

ROW_NEWER_THAN_PAYLOAD_SQL = """
SELECT 'fixture_team_stats' AS relation, count(*) AS offenders
  FROM core.fixture_team_stats s JOIN raw.ingestion_payloads p ON p.hash = s.payload_hash
 WHERE s.fetched_at > p.fetched_at
UNION ALL
SELECT 'fixture_events', count(*) FROM core.fixture_events e
  JOIN raw.ingestion_payloads p ON p.hash = e.payload_hash WHERE e.fetched_at > p.fetched_at
UNION ALL
SELECT 'fixture_lineups', count(*) FROM core.fixture_lineups l
  JOIN raw.ingestion_payloads p ON p.hash = l.payload_hash WHERE l.fetched_at > p.fetched_at
"""


def check_lineage_holds(conn: psycopg.Connection) -> CheckOutcome:
    """Two lineage faults, both of which really happened.

      * a near-close row projecting a snapshot the series does not hold. The
        schema refuses this now; the check exists because it could have been
        created before it did.
      * a normalized row whose ``fetched_at`` is LATER than the payload it names.
        The raw store keeps identical bodies once, so a payload fetched twice is
        indexed at the first fetch while the caller holds the second - and passing
        that later time to the writers made 1,809 fixtures' detail look absent.

    ``population`` is None for the same reason as above: near-close rows and three
    detail tables are not one population, and the first version of this check said
    otherwise - the schema's own ``offenders <= population`` constraint refused the
    row, which is exactly what it is for.
    """
    issues: list[QualityIssue] = []
    for r in _rows(conn, ORPHAN_NEAR_CLOSE_SQL):
        issues.append(QualityIssue(
            code=IssueCode.LINEAGE_BROKEN, entity_type=EntityType.ODDS_SNAPSHOT,
            severity=Severity.ERROR, entity_id=int(r["fixture_id"]),
            field="captured_at", observed=str(r["captured_at"]),
            expected="a matching row in market.odds_snapshots",
            detail=f"near-close {r['market_key']} {r['selection']} {r['line']} projects a price "
                   "the series does not hold",
        ))
    drift = 0
    for r in _rows(conn, ROW_NEWER_THAN_PAYLOAD_SQL):
        if not r["offenders"]:
            continue
        drift += int(r["offenders"])
        issues.append(QualityIssue(
            code=IssueCode.LINEAGE_BROKEN, entity_type=EntityType.PAYLOAD, severity=Severity.WARNING,
            provider_entity_id=None, payload_hash=None, entity_id=0,
            field=str(r["relation"]), observed=int(r["offenders"]),
            expected="fetched_at no later than the payload's",
            detail=f"{r['offenders']} row(s) in core.{r['relation']} are dated after the payload "
                   "they name: the raw store deduplicates identical bodies and keeps the first "
                   "fetch, so writers must use the index's time",
        ))
    return CheckOutcome("lineage_holds", "market_and_detail", Severity.ERROR, None,
                        len(issues), issues, detail=f"{drift} row(s) dated after their payload")


# ── unknown provider entities ───────────────────────────────────────────────

UNMAPPED_BOOKMAKER_SQL = """
SELECT b.provider_bookmaker_id, b.name, count(o.*) AS prices
  FROM market.bookmakers b
  LEFT JOIN market.odds_snapshots o ON o.bookmaker_id = b.id
 WHERE NOT b.is_active
 GROUP BY 1, 2 HAVING count(o.*) > 0
"""


def check_prices_come_from_known_books(conn: psycopg.Connection) -> CheckOutcome:
    """Prices stored against a bookmaker we have marked inactive.

    Not an error in itself - a book can be deactivated after prices were captured -
    but worth knowing, because the consensus weights it at zero while the rows
    still exist.
    """
    population = _scalar(conn, "SELECT count(*) FROM market.bookmakers")
    rows = _rows(conn, UNMAPPED_BOOKMAKER_SQL)
    issues = [
        QualityIssue(
            code=IssueCode.UNKNOWN_PROVIDER_ENTITY, entity_type=EntityType.BOOKMAKER,
            severity=Severity.INFO, provider_entity_id=int(r["provider_bookmaker_id"]),
            entity_id=None, field="is_active", observed=False, expected="true, or no prices",
            detail=f"{r['name']} is inactive and has {r['prices']} price(s) on record",
        )
        for r in rows
    ]
    return CheckOutcome("prices_come_from_known_books", "bookmakers", Severity.INFO, population,
                        len(issues), issues)


CHECKS: tuple[Callable[[psycopg.Connection], CheckOutcome], ...] = (
    check_results_are_resolved,
    check_lineups_are_complete,
    check_detail_has_been_fetched,
    check_values_are_possible,
    check_results_are_not_stale,
    check_lineage_holds,
    check_prices_come_from_known_books,
)


def sweep(conn: psycopg.Connection, *, run_id: int, apply: bool = True) -> SweepReport:
    """Run every check, record what it found, and say what it ran against.

    ``apply=False`` computes everything and writes nothing, so a sweep can be
    inspected before it touches the registry.
    """
    report = SweepReport()
    registry = IssueRegistry(conn)
    for check in CHECKS:
        outcome = check(conn)
        report.checks.append(outcome)
        if not apply:
            continue
        result = registry.record_many(issues_from(outcome.issues))
        report.issues_opened += result.opened
        report.issues_seen_again += result.seen_again
        record_check(conn, run_id=run_id, check_name=outcome.name, scope=outcome.scope,
                     severity=outcome.severity, population=outcome.population,
                     offenders=outcome.offenders, issues_opened=result.opened,
                     expected="0 offenders", actual=str(outcome.offenders),
                     details={"detail": outcome.detail} if outcome.detail else {})
        conn.commit()
    log.info("quality.sweep_finished", **report.as_dict())
    return report

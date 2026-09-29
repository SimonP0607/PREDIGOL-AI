"""The data-quality registry: recording what we could not use, instead of fixing it.

    RAW  ->  NORMALIZED  ->  QUALITY ISSUE / TRANSFORMATION

Everything the boundary refuses, every contradiction in the provider's own data,
every entity it names that we do not know, lands here with its provenance. The
alternative - which is what the code did - is to null the awkward value and move
on, at which point "the provider sent something impossible" and "the provider
sent nothing" are indistinguishable forever.

Recording an issue is not fixing it. Nothing in this module changes a stored
value; the registry exists so that a human, or a later transformation with an
explicit rule, can decide what to do.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

log = structlog.get_logger(__name__)

MAX_TEXT = 500
"""Observed and expected values are evidence, not documents. Longer than this and
the useful part is at the front anyway."""


class IssueCode(StrEnum):
    """Must match audit.data_quality_codes, which the migration seeds."""

    PROVIDER_INCONSISTENCY = "PROVIDER_INCONSISTENCY"
    INCOMPLETE_LINEUP = "INCOMPLETE_LINEUP"
    RESULT_UNRESOLVED = "RESULT_UNRESOLVED"
    MISSING_DETAIL = "MISSING_DETAIL"
    NORMALIZATION_REJECTED = "NORMALIZATION_REJECTED"
    UNKNOWN_PROVIDER_ENTITY = "UNKNOWN_PROVIDER_ENTITY"
    STALE_DATA = "STALE_DATA"
    LINEAGE_BROKEN = "LINEAGE_BROKEN"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EntityType(StrEnum):
    """What the issue is about. Free text in the schema on purpose - a new kind of
    entity should not need a migration - but an enum here so the values we use
    stay a closed set."""

    FIXTURE = "fixture"
    FIXTURE_RESULT = "fixture_result"
    LINEUP = "lineup"
    TEAM_STATISTICS = "team_statistics"
    PLAYER_STATISTICS = "player_statistics"
    MATCH_EVENT = "match_event"
    TEAM = "team"
    PLAYER = "player"
    COACH = "coach"
    VENUE = "venue"
    LEAGUE_SEASON = "league_season"
    ODDS_SNAPSHOT = "odds_snapshot"
    BOOKMAKER = "bookmaker"
    PROVIDER_MARKET = "provider_market"
    PAYLOAD = "payload"


class IssueStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"
    SUPERSEDED = "superseded"


def _clip(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:MAX_TEXT] if text else None


def _number(value: object | None) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    return None


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One problem with one thing.

    ``entity_id`` is our internal id when the entity exists for us;
    ``provider_entity_id`` is the provider's, which is sometimes all there is -
    an unmapped bet or an unknown team has no id of ours yet. At least one of
    those or ``payload_hash`` is required: a problem without a subject cannot be
    acted on, and the schema refuses it.
    """

    code: IssueCode
    entity_type: EntityType
    severity: Severity = Severity.WARNING
    entity_id: int | None = None
    provider_entity_id: int | None = None
    provider: str = "api-football"
    payload_hash: str | None = None
    run_id: int | None = None
    field: str | None = None
    observed: object | None = None
    expected: object | None = None
    detail: str | None = None
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """What makes this the SAME issue on the next sweep.

        Deliberately excludes payload_hash, run_id and timestamps: the fifteenth
        re-detection of the same incomplete line-up is one issue seen again, not
        a new one. It DOES include the observed value, because a different wrong
        number is a different fact.
        """
        parts = [self.code.value, self.entity_type.value, self.provider,
                 str(self.entity_id or ""), str(self.provider_entity_id or ""),
                 self.field or "", _clip(self.observed) or ""]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

    def as_row(self) -> tuple[object, ...]:
        return (
            self.code.value, self.severity.value, self.entity_type.value, self.entity_id,
            self.provider, self.provider_entity_id, self.payload_hash, self.run_id, self.field,
            _clip(self.observed), _clip(self.expected), _number(self.observed), _number(self.expected),
            _clip(self.detail), Json(self.details), self.fingerprint,
        )


INSERT = """
INSERT INTO audit.data_quality_issues
    (code, severity, entity_type, entity_id, provider, provider_entity_id, payload_hash, run_id,
     field, observed, expected, observed_number, expected_number, detail, details, fingerprint)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (fingerprint) DO UPDATE SET
    occurrences  = audit.data_quality_issues.occurrences + 1,
    last_seen_at = now(),
    severity     = EXCLUDED.severity,
    payload_hash = COALESCE(EXCLUDED.payload_hash, audit.data_quality_issues.payload_hash),
    run_id       = COALESCE(EXCLUDED.run_id, audit.data_quality_issues.run_id),
    detail       = COALESCE(EXCLUDED.detail, audit.data_quality_issues.detail),
    status       = CASE WHEN audit.data_quality_issues.status IN ('resolved','superseded')
                        THEN 'open' ELSE audit.data_quality_issues.status END,
    resolved_at  = CASE WHEN audit.data_quality_issues.status IN ('resolved','superseded')
                        THEN NULL ELSE audit.data_quality_issues.resolved_at END
RETURNING id, (xmax = 0) AS was_new
"""


@dataclass
class RecordResult:
    opened: int = 0
    seen_again: int = 0
    reopened: int = 0

    @property
    def total(self) -> int:
        return self.opened + self.seen_again


class IssueRegistry:
    """Writes issues idempotently. Does not commit: the caller owns the
    transaction, so an issue is recorded in the same unit of work as the
    ingestion it came from, or not at all."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, issue: QualityIssue) -> int:
        """Returns the issue id. A repeat bumps occurrences instead of duplicating."""
        with self._conn.cursor() as cur:
            cur.execute(INSERT, issue.as_row())
            row = cur.fetchone()
        assert row is not None, "the upsert always returns the row it touched"
        return int(row[0])

    def record_many(self, issues: Iterable[QualityIssue]) -> RecordResult:
        result = RecordResult()
        with self._conn.cursor() as cur:
            for issue in issues:
                cur.execute(INSERT, issue.as_row())
                row = cur.fetchone()
                if row is None:
                    continue
                if row[1]:
                    result.opened += 1
                else:
                    result.seen_again += 1
        if result.total:
            log.info("quality.issues_recorded", opened=result.opened, seen_again=result.seen_again)
        return result

    def resolve(self, fingerprint: str, *, resolution: str,
                status: IssueStatus = IssueStatus.RESOLVED) -> bool:
        """Close an issue WITH a reason. The schema refuses it without one."""
        if not resolution.strip():
            raise ValueError("an issue cannot be closed without saying why")
        if status not in (IssueStatus.RESOLVED, IssueStatus.WONT_FIX, IssueStatus.SUPERSEDED,
                          IssueStatus.ACKNOWLEDGED):
            raise ValueError(f"{status} is not a way of closing an issue")
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE audit.data_quality_issues SET status = %s, resolution = %s, "
                "resolved_at = CASE WHEN %s IN ('resolved','superseded') THEN now() ELSE resolved_at END "
                "WHERE fingerprint = %s",
                (status.value, resolution.strip(), status.value, fingerprint),
            )
            return cur.rowcount == 1

    def open_issues(self, *, code: IssueCode | None = None, entity_type: EntityType | None = None,
                    limit: int = 100) -> list[dict[str, Any]]:
        sql = ["SELECT * FROM audit.data_quality_issues WHERE status IN ('open','acknowledged')"]
        params: list[object] = []
        if code is not None:
            sql.append("AND code = %s")
            params.append(code.value)
        if entity_type is not None:
            sql.append("AND entity_type = %s")
            params.append(entity_type.value)
        sql.append("ORDER BY severity DESC, last_seen_at DESC LIMIT %s")
        params.append(limit)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(" ".join(sql), params)
            return [dict(r) for r in cur.fetchall()]

    def summary(self) -> list[dict[str, Any]]:
        """Issues and occurrences per code, counted separately: fifteen incomplete
        line-ups seen three times each are fifteen problems, not forty-five."""
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM audit.open_quality_issues ORDER BY severity DESC, code")
            return [dict(r) for r in cur.fetchall()]


def record_check(
    conn: psycopg.Connection,
    *,
    run_id: int,
    check_name: str,
    scope: str,
    severity: Severity,
    population: int | None,
    offenders: int | None,
    issues_opened: int = 0,
    expected: str | None = None,
    actual: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    """Record that a check RAN, with the denominator it ran against.

    Separate from the issues it opened, and necessary for honesty about coverage:
    a percentage needs a population, and ``population = None`` means "could not
    be established", never zero.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit.data_quality_checks (run_id, check_name, scope, severity, expected, "
            " actual, passed, details, population, offenders, issues_opened) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (run_id, check_name, scope, severity.value, expected, actual, not offenders,
             Json(details or {}), population, offenders, issues_opened),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def inconsistency(
    *,
    entity_type: EntityType,
    entity_id: int | None,
    provider_entity_id: int | None,
    field_name: str,
    observed: object,
    expected: str,
    payload_hash: str | None = None,
    run_id: int | None = None,
    detail: str | None = None,
) -> QualityIssue:
    """The shape used wherever two of the provider's own fields contradict.

    A helper rather than a comment, because the call sites are in hot normalising
    loops and the point is that recording an inconsistency should be as short as
    nulling the value used to be.
    """
    return QualityIssue(
        code=IssueCode.PROVIDER_INCONSISTENCY,
        entity_type=entity_type,
        severity=Severity.WARNING,
        entity_id=entity_id,
        provider_entity_id=provider_entity_id,
        payload_hash=payload_hash,
        run_id=run_id,
        field=field_name,
        observed=observed,
        expected=expected,
        detail=detail,
    )


def rejected(
    *,
    entity_type: EntityType,
    field_name: str,
    observed: object,
    reason: str,
    provider_entity_id: int | None = None,
    entity_id: int | None = None,
    payload_hash: str | None = None,
    run_id: int | None = None,
) -> QualityIssue:
    """The boundary refused a value. It is dropped, and it is written down."""
    return QualityIssue(
        code=IssueCode.NORMALIZATION_REJECTED,
        entity_type=entity_type,
        severity=Severity.WARNING,
        entity_id=entity_id,
        provider_entity_id=provider_entity_id,
        payload_hash=payload_hash,
        run_id=run_id,
        field=field_name,
        observed=observed,
        expected=reason,
    )


def unknown_entity(
    *,
    entity_type: EntityType,
    name: str,
    provider_entity_id: int | None = None,
    payload_hash: str | None = None,
    run_id: int | None = None,
    detail: str | None = None,
) -> QualityIssue:
    """The provider named something we do not know. Information, not an error."""
    return QualityIssue(
        code=IssueCode.UNKNOWN_PROVIDER_ENTITY,
        entity_type=entity_type,
        severity=Severity.INFO,
        provider_entity_id=provider_entity_id,
        payload_hash=payload_hash,
        run_id=run_id,
        field="name",
        observed=name,
        detail=detail,
    )


def issues_from(sequence: Sequence[QualityIssue]) -> list[QualityIssue]:
    """De-duplicate by fingerprint while keeping order: one sweep should offer
    each distinct issue once, so occurrences counts sweeps rather than rows."""
    seen: dict[str, QualityIssue] = {}
    for issue in sequence:
        seen.setdefault(issue.fingerprint, issue)
    return list(seen.values())

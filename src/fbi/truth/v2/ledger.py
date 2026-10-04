"""The evidence ledger: every established discrepancy as an E-XXX entry with its evidence.

An entry is keyed by a stable ``key`` (``standings:39:2026:stale`` ...). Recording the same key
again refreshes its evidence, ``last_seen_at`` and ``times_seen``; it never creates a second
entry and never rewrites ``first_seen_at`` or the code. An entry marked FIXED that a later run
sees again is re-opened (the fix did not hold); only ACCEPTED (an owner's decision, e.g. a
provider limitation) survives being seen again. ``clear_unseen`` marks the entries of a
scope that a later run no longer reproduces as CLEARED (kept, with ``cleared_at``) - how a fix
is shown to have worked.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Json

ISSUE_TYPES = frozenset({
    "PROVIDER_STALE", "NORMALIZER_BUG", "MAPPING_ERROR", "MISSING_BACKFILL", "STALE_ENTITY", "SEASON_MISMATCH",
    "STANDINGS_MISMATCH", "PLAYER_STATS_MISMATCH", "TEAM_STATS_MISMATCH", "WRONG_SEASON", "MISSING_SEASON",
    "DUPLICATE_COMPETITION", "WRONG_TYPE", "WRONG_COUNTRY", "STALE_CURRENT_SEASON", "REAL_LOW_HISTORY",
    "PROVIDER_COVERAGE", "IDENTITY_MAPPING_ERROR", "SEASON_NOT_MIGRATED", "DROPPED_USEFUL_FIELD",
    "UNSUPPORTED_FIELD", "INTENTIONALLY_IGNORED", "PROVIDER_DEFINED_METRIC", "FIXTURE_MISMATCH", "RESULT_MISMATCH",
    "PROVIDER_EXTERNAL_MISMATCH", "DUPLICATE_ENTITY", "PRODUCT_SCOPE",
    # 0057: competition phases, the API contract, field coverage
    "PHASE_TABLE_MIXED", "PHASE_TABLE_UNMAPPED", "BUG_DROPPED_FIELD", "STORED_NOT_USED", "API_CONTRACT_GAP",
    "MISSING_ENDPOINT",
})
AREAS = frozenset({"baseline", "leagues", "fixtures", "standings", "teams", "team_stats", "team_history", "players",
                   "player_stats", "identity", "squads", "injuries", "coaches", "venues", "normalization", "golden",
                   "odds", "phases", "api_contract", "field_coverage", "predictions", "transfers", "trophies",
                   "sidelined", "h2h", "media", "datasets"})
SEVERITIES = ("critical", "high", "medium", "low", "info")
FAULTS = frozenset({"provider", "predigol", "none", "undetermined"})


@dataclass
class Evidence:
    key: str
    area: str
    issue_type: str
    severity: str
    at_fault: str
    claim: str
    entity: str | None = None
    api: dict[str, Any] | None = None
    db: dict[str, Any] | None = None
    external: dict[str, Any] | None = None
    root_cause: str | None = None
    fix: str | None = None
    test: str | None = None
    status: str = "OPEN"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.issue_type not in ISSUE_TYPES:
            raise ValueError(f"unknown issue type {self.issue_type}")
        if self.area not in AREAS:
            raise ValueError(f"unknown area {self.area}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity}")
        if self.at_fault not in FAULTS:
            raise ValueError(f"unknown fault {self.at_fault}")

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "area": self.area, "issue_type": self.issue_type, "severity": self.severity,
                "at_fault": self.at_fault, "claim": self.claim, "entity": self.entity, "api": self.api,
                "db": self.db, "external": self.external, "root_cause": self.root_cause, "fix": self.fix,
                "test": self.test, "status": self.status}


def _json(value: dict[str, Any] | None) -> Json | None:
    return None if value is None else Json(json.loads(json.dumps(value, default=str)))


UPSERT = """
INSERT INTO audit.evidence_ledger (key, area, issue_type, severity, at_fault, entity, claim, api_evidence,
                                   db_evidence, external_evidence, root_cause, fix, test, status, first_seen_at,
                                   last_seen_at, last_run_id)
VALUES (%(key)s, %(area)s, %(issue_type)s, %(severity)s, %(at_fault)s, %(entity)s, %(claim)s, %(api)s, %(db)s,
        %(external)s, %(root_cause)s, %(fix)s, %(test)s, %(status)s, %(at)s, %(at)s, %(run)s)
ON CONFLICT (key) DO UPDATE SET
    area = EXCLUDED.area, issue_type = EXCLUDED.issue_type, severity = EXCLUDED.severity,
    at_fault = EXCLUDED.at_fault, entity = EXCLUDED.entity, claim = EXCLUDED.claim,
    api_evidence = COALESCE(EXCLUDED.api_evidence, audit.evidence_ledger.api_evidence),
    db_evidence = COALESCE(EXCLUDED.db_evidence, audit.evidence_ledger.db_evidence),
    external_evidence = COALESCE(EXCLUDED.external_evidence, audit.evidence_ledger.external_evidence),
    root_cause = COALESCE(EXCLUDED.root_cause, audit.evidence_ledger.root_cause),
    fix = COALESCE(EXCLUDED.fix, audit.evidence_ledger.fix),
    test = COALESCE(EXCLUDED.test, audit.evidence_ledger.test),
    status = CASE WHEN audit.evidence_ledger.status = 'ACCEPTED' THEN 'ACCEPTED' ELSE EXCLUDED.status END,
    cleared_at = NULL,
    last_seen_at = GREATEST(audit.evidence_ledger.last_seen_at, EXCLUDED.last_seen_at),
    times_seen = audit.evidence_ledger.times_seen + 1,
    last_run_id = EXCLUDED.last_run_id
RETURNING code
"""


def record(conn: psycopg.Connection[Any], ev: Evidence, *, at: datetime, run_id: int | None = None) -> str:
    """Write or refresh one entry; returns its code (E-001 ...)."""
    with conn.cursor() as cur:
        cur.execute(UPSERT, {"key": ev.key, "area": ev.area, "issue_type": ev.issue_type, "severity": ev.severity,
                             "at_fault": ev.at_fault, "entity": ev.entity, "claim": ev.claim, "api": _json(ev.api),
                             "db": _json(ev.db), "external": _json(ev.external), "root_cause": ev.root_cause,
                             "fix": ev.fix, "test": ev.test, "status": ev.status, "at": at, "run": run_id})
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def record_all(conn: psycopg.Connection[Any], items: Iterable[Evidence], *, at: datetime,
               run_id: int | None = None) -> dict[str, str]:
    return {ev.key: record(conn, ev, at=at, run_id=run_id) for ev in items}


def clear_unseen(conn: psycopg.Connection[Any], *, area: str, scope_prefix: str, seen: Iterable[str],
                 at: datetime, keep_containing: str | None = None) -> int:
    """Entries of this area whose key starts with ``scope_prefix`` and that this run did not see:
    CLEARED (kept). ``keep_containing`` spares keys this run could not have seen (an official-table
    comparison when no official table was given). Returns how many."""
    keep = "" if keep_containing is None else " AND position(%(keep)s in key) = 0"
    with conn.cursor() as cur:
        cur.execute("UPDATE audit.evidence_ledger SET status = 'CLEARED', cleared_at = %(at)s "
                    "WHERE area = %(area)s AND key LIKE %(prefix)s AND NOT (key = ANY(%(seen)s)) "
                    "AND status IN ('OPEN', 'MONITOR')" + keep,
                    {"at": at, "area": area, "prefix": scope_prefix.replace("%", r"\%") + "%", "seen": list(seen),
                     "keep": keep_containing})
        return cur.rowcount


def mark(conn: psycopg.Connection[Any], code: str, *, status: str, fix: str | None = None,
         test: str | None = None) -> None:
    """The owner's (or a fix's) verdict on one entry: FIXED, ACCEPTED or MONITOR."""
    if status not in ("FIXED", "ACCEPTED", "MONITOR", "OPEN"):
        raise ValueError(status)
    with conn.cursor() as cur:
        cur.execute("UPDATE audit.evidence_ledger SET status = %s, cleared_at = NULL, fix = COALESCE(%s, fix), "
                    "test = COALESCE(%s, test) WHERE code = %s", (status, fix, test, code))

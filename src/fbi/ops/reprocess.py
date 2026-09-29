"""Re-derive normalized state from the raw payloads already on disk.

The architecture's promise is that RAW is the record and everything else is
derived from it. This is where that promise pays for itself.

``core.fixture_detail_coverage`` (revision 0028) records, per fixture and
dataset, whether the provider's payload carried the block at all. Every detail
payload we have ever fetched is still in the raw store, so that table can be
filled EXACTLY, from what the provider actually sent, without spending a single
request. The alternative - treating every fixture as never-fetched and asking
again - would have cost about 1,025 requests on Tier 1 alone and produced a worse
answer, because a re-fetch today cannot tell us what a payload contained a week
ago.

Replaying also back-fills the quality issues that the old code dropped in
silence: the contradictions it nulled, the line-ups short of eleven starters, the
statistic types it had no column for. Nothing is invented - every issue carries
the hash of the payload it was read from, and ``fetched_at`` stays the instant the
provider answered.

Idempotent by construction: every writer in ``ingestion.details`` refuses a
payload older than what is stored for that fixture, so replaying in ascending
``fetched_at`` order converges on the same state however often it runs.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.errors import FbiError
from fbi.ingestion.details import apply_fixture_details
from fbi.ingestion.payload_store import PayloadStore, body_hash
from fbi.providers.api_football.details import iter_fixture_details

log = structlog.get_logger(__name__)

DETAIL_ENDPOINT = "/fixtures"


class ReprocessError(FbiError):
    """The raw store does not hold what the index says it holds."""


@dataclass
class ReprocessReport:
    payloads_seen: int = 0
    payloads_applied: int = 0
    payloads_missing_file: int = 0
    payloads_not_rehashing: int = 0
    fixtures_touched: int = 0
    coverage_rows: int = 0
    issues_opened: int = 0
    issues_seen_again: int = 0
    skipped_stale: int = 0
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"payloads_seen": self.payloads_seen, "payloads_applied": self.payloads_applied,
                "payloads_missing_file": self.payloads_missing_file,
                "payloads_not_rehashing": self.payloads_not_rehashing,
                "fixtures_touched": self.fixtures_touched, "coverage_rows": self.coverage_rows,
                "issues_opened": self.issues_opened, "issues_seen_again": self.issues_seen_again,
                "skipped_stale": self.skipped_stale, "problems": self.problems[:20]}


def detail_payloads(conn: psycopg.Connection, *, limit: int | None = None,
                    hashes: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Every stored ``/fixtures?ids=`` payload, oldest first.

    Oldest first matters: the writers only accept a payload at least as new as
    what is stored, so replaying in fetch order reproduces the history rather
    than fighting it. ``hashes`` narrows the replay to named payloads, for when a
    single batch needs re-deriving rather than the whole store.
    """
    sql = ("SELECT hash, endpoint, params, fetched_at, file_path, results_count "
           "FROM raw.ingestion_payloads "
           "WHERE endpoint = %s AND params ? 'ids' AND http_status = 200 ")
    params: list[object] = [DETAIL_ENDPOINT]
    if hashes is not None:
        sql += "AND hash = ANY(%s) "
        params.append(list(hashes))
    sql += "ORDER BY fetched_at, hash"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _bodies(store: PayloadStore, rows: list[dict[str, Any]], report: ReprocessReport,
            *, verify: bool) -> Iterator[tuple[dict[str, Any], dict[str, Any], datetime]]:
    for row in rows:
        report.payloads_seen += 1
        file_path = str(row["file_path"])
        try:
            envelope = store.load(file_path)
        except FileNotFoundError:
            report.payloads_missing_file += 1
            report.problems.append(f"{file_path}: indexed but not in the raw store")
            continue
        body = envelope.get("body")
        if verify and body_hash(body) != row["hash"]:
            report.payloads_not_rehashing += 1
            report.problems.append(f"{file_path}: does not re-hash to {str(row['hash'])[:12]}")
            continue
        if not isinstance(body, dict):
            report.problems.append(f"{file_path}: the stored body is not an object")
            continue
        yield row, body, row["fetched_at"]


def reprocess_fixture_details(
    conn: psycopg.Connection,
    raw_root: Path,
    *,
    apply: bool,
    limit: int | None = None,
    hashes: Sequence[str] | None = None,
    verify_hashes: bool = True,
) -> ReprocessReport:
    """Re-apply every stored detail payload. No provider call is made.

    ``apply=False`` reads and verifies everything and writes nothing, so the
    report can be inspected before touching the database.
    """
    report = ReprocessReport()
    store = PayloadStore(raw_root)
    rows = detail_payloads(conn, limit=limit, hashes=hashes)
    for row, body, fetched_at in _bodies(store, rows, report, verify=verify_hashes):
        details = list(iter_fixture_details(body))
        if not details:
            continue
        if not apply:
            report.payloads_applied += 1
            report.fixtures_touched += len(details)
            continue
        rep = apply_fixture_details(conn, details, payload_hash=str(row["hash"]),
                                   fetched_at=fetched_at, run_id=None)
        report.payloads_applied += 1
        report.fixtures_touched += rep.fixtures
        report.coverage_rows += rep.coverage_rows
        report.issues_opened += rep.issues_opened
        report.issues_seen_again += rep.issues_seen_again
        report.skipped_stale += rep.stale
        conn.commit()  # a checkpoint per payload: a crash resumes, never restarts
    if report.problems:
        log.warning("reprocess.problems", count=len(report.problems), first=report.problems[:3])
    log.info("reprocess.finished", **report.as_dict())
    if not apply:
        conn.rollback()
    return report

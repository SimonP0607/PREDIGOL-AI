"""Every kick-off change, read back from the stored /fixtures payloads.

core.fixture_kickoff_changes records the changes the fixture sync applies from 4 Oct 2026 on.
The changes before it are still in the raw store: every /fixtures payload ever fetched holds
each fixture's kick-off as the provider stated it at that instant. Replaying them in fetch
order recovers when each kick-off moved, from what, to what, and on which payload's word.
No provider request; every file is verified against its indexed hash before it is read.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.ingestion.payload_store import PayloadStore, body_hash
from fbi.ingestion.replay import FIXTURE_ENDPOINTS
from fbi.providers.api_football.normalize import iter_fixtures


@dataclass(frozen=True, slots=True)
class KickoffChange:
    provider_fixture_id: int
    observed_at: datetime
    before: datetime
    after: datetime
    payload_hash: str


def kickoff_changes(payloads: Iterable[tuple[datetime, str, dict[str, Any]]]) -> list[KickoffChange]:
    """(fetched_at, hash, body) in fetch order -> every change of a fixture's stated kick-off."""
    last: dict[int, datetime] = {}
    out: list[KickoffChange] = []
    for fetched_at, payload_hash, body in payloads:
        for ref in iter_fixtures(body):
            prev = last.get(ref.provider_fixture_id)
            if prev is not None and prev != ref.kickoff_at:
                out.append(KickoffChange(ref.provider_fixture_id, fetched_at, prev, ref.kickoff_at, payload_hash))
            last[ref.provider_fixture_id] = ref.kickoff_at
    return out


@dataclass
class BackfillReport:
    payloads: int = 0
    refused: list[str] = field(default_factory=list)
    changes: int = 0
    written: int = 0


def backfill_kickoff_changes(conn: psycopg.Connection[Any], store: PayloadStore, *, since: datetime,
                             apply: bool = False) -> BackfillReport:
    report = BackfillReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads "
                    "WHERE endpoint = ANY(%s) AND http_status = 200 AND fetched_at >= %s ORDER BY fetched_at, hash",
                    (list(FIXTURE_ENDPOINTS), since))
        rows = [(str(h), str(p), at) for h, p, at in cur.fetchall()]

    def bodies() -> Iterable[tuple[datetime, str, dict[str, Any]]]:
        for payload_hash, file_path, fetched_at in rows:
            report.payloads += 1
            try:
                body = store.load(file_path).get("body")
            except (OSError, ValueError) as exc:
                report.refused.append(f"{payload_hash[:12]}: unreadable ({exc.__class__.__name__})")
                continue
            if not isinstance(body, dict) or body_hash(body) != payload_hash:
                report.refused.append(f"{payload_hash[:12]}: hash mismatch")
                continue
            yield fetched_at, payload_hash, body

    changes = kickoff_changes(bodies())
    report.changes = len(changes)
    with conn.cursor() as cur:
        for c in changes:
            cur.execute(
                "INSERT INTO core.fixture_kickoff_changes (fixture_id, observed_at, before_kickoff, after_kickoff, "
                "payload_hash) SELECT id, %s, %s, %s, %s FROM core.fixtures WHERE provider_fixture_id = %s "
                "ON CONFLICT DO NOTHING",
                (c.observed_at, c.before, c.after, c.payload_hash, c.provider_fixture_id))
            report.written += max(cur.rowcount, 0)
    if apply:
        conn.commit()
    else:
        conn.rollback()
    return report

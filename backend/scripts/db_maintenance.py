"""The owner's daily database maintenance on the server (predigol-maint.timer), run as the OWNER role (fbi):
what the least-privileged worker may not do, and the retention of operational leftovers.

    python -m scripts.db_maintenance partitions            # odds partitions three months ahead
    python -m scripts.db_maintenance retention             # dry run: what the policy would remove
    python -m scripts.db_maintenance retention --confirm   # remove it (only what is listed below)
    python -m scripts.db_maintenance all --confirm

RETENTION removes ONLY operational leftovers that nothing reads and that are not history (FASE 10):

  auth.sessions            revoked or expired more than 90 days ago (the audit trail keeps every sign-in)
  raw.provider_minute_usage  per-minute request counters older than 35 days (the daily totals stay in
                           raw.provider_quota)

It never touches fixtures, results, statistics, features, models, predictions, picks, pre-match prices,
near-close prices, RAW payloads or any audit table. Every removal is counted first, recorded in
audit.storage_cleanups with the rows removed, and refused when the newest verified backup is older than 26 hours
(--backups DIR, default /backups as mounted in the ops container).

Exit status: 0 done (or nothing to do), 1 refused or failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from fbi.core.clock import today
from fbi.core.config import settings
from fbi.core.version import code_version
from fbi.odds.partitions import ensure_partitions


@dataclass(frozen=True)
class Rule:
    table: str
    where: str
    why: str


RULES = (
    Rule("auth.sessions", "coalesce(revoked_at, expires_at) < now() - interval '90 days'",
         "sessions revoked or expired more than 90 days ago; the sign-in history is in auth.audit_events"),
    Rule("raw.provider_minute_usage", "minute < now() - interval '35 days'",
         "per-minute request counters older than 35 days; daily totals are kept"),
)
BACKUP_MAX_AGE = timedelta(hours=26)


def newest_backup(folder: Path) -> datetime | None:
    newest: datetime | None = None
    for manifest in folder.glob("predigol-*.json"):
        try:
            created = datetime.fromisoformat(json.loads(manifest.read_text())["created_at"].replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError):
            continue
        if (manifest.with_suffix(".dump")).exists() and (newest is None or created > newest):
            newest = created
    return newest


def cmd_partitions(conn: psycopg.Connection) -> int:
    created = ensure_partitions(conn, today=today(), months_ahead=3)
    print(f"partitions: {', '.join(created) if created else 'all present (3 months ahead)'}")
    return 0


def _exists(conn: psycopg.Connection, table: str, column_sql: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()
    if row is None or row[0] is None:
        return False
    try:
        conn.execute(f"SELECT 1 FROM {table} WHERE {column_sql} LIMIT 0")
    except psycopg.Error:
        conn.rollback()
        return False
    return True


def cmd_retention(conn: psycopg.Connection, *, confirm: bool, backups: Path) -> int:
    plan: list[tuple[Rule, int]] = []
    for rule in RULES:
        if not _exists(conn, rule.table, rule.where):
            print(f"retention: {rule.table} - not in this schema, skipped")
            continue
        found = conn.execute(f"SELECT count(*) FROM {rule.table} WHERE {rule.where}").fetchone()
        plan.append((rule, int(found[0]) if found else 0))
    for rule, n in plan:
        print(f"retention: {rule.table}: {n} row(s) - {rule.why}")
    if not confirm:
        print("retention: dry run, nothing removed (add --confirm)")
        return 0
    if not any(n for _, n in plan):
        print("retention: nothing to remove")
        return 0
    newest = newest_backup(backups)
    if newest is None or datetime.now(UTC) - newest > BACKUP_MAX_AGE:
        print(f"retention: REFUSED - no verified backup in the last 26 h in {backups}", file=sys.stderr)
        return 1
    removed: dict[str, int] = {}
    with conn.transaction():
        for rule, _ in plan:
            cur = conn.execute(f"DELETE FROM {rule.table} WHERE {rule.where}")
            removed[rule.table] = cur.rowcount
            conn.execute(
                "INSERT INTO audit.storage_cleanups (kind, subject, rows, backup_label, verified, details, "
                "code_version) VALUES ('retention', %s, %s, %s, true, %s, %s)",
                (rule.table, cur.rowcount, f"newest backup {newest.isoformat()}",
                 Jsonb({"where": rule.where, "why": rule.why}), code_version()))
    print(f"retention: removed {removed} (recorded in audit.storage_cleanups)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="db_maintenance", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=("partitions", "retention", "all"))
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--backups", type=Path, default=Path("/backups"))
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url, options="-c statement_timeout=600000") as conn:
        rc = 0
        if args.cmd in ("partitions", "all"):
            rc |= cmd_partitions(conn)
        if args.cmd in ("retention", "all"):
            rc |= cmd_retention(conn, confirm=args.confirm, backups=args.backups)
    return rc


if __name__ == "__main__":
    sys.exit(main())

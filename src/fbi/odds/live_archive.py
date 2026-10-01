"""Retire old live partitions to Parquet, and only then drop them.

WHY THE LIVE SERIES NEEDS THIS AND THE OTHERS DO NOT
----------------------------------------------------
Everything else in this database is bounded by the football that exists: 216,525
fixtures, 201,416 results, 5.2M player-stat rows, and the detail tables stop
growing once the backfill finishes. The live series is bounded by the clock
instead - 108 rows per fixture per instant, every 30 seconds, for as long as
matches are being played - so it is the one table that grows without a ceiling.

Change-only storage took the first 3.35x out of it. This takes the rest, by
moving months that are no longer being asked about out of Postgres.

WHY "THE CURRENT SEASON" CANNOT DEFINE THE BOUNDARY
---------------------------------------------------
It is the obvious rule and it does not work. core.competition_seasons.is_current
is the provider's answer and it is correct - one current season per tracked
competition, 124 of them - but their fixtures span 2023-09-07 to 2027-06-06,
because World Cup qualifying is a single season that runs for years. A boundary
drawn there keeps everything.

So the boundary is a number of months, which is one comprehensible thing that
covers a season in either hemisphere. Twelve by default.

WHAT IS GUARANTEED
------------------
A partition is dropped only after its archive has been written, checksummed, and
read back with a matching row count - the same discipline as the database backup
and for the same reason: an archive nobody has restored is a hope, not a backup.

ABOUT THE LOCK
--------------
DETACH PARTITION takes an ACCESS EXCLUSIVE lock on the parent, which stalls the
live writer while it is held, and a tick that cannot write is a price lost -
/odds/live keeps no history. CONCURRENTLY exists for exactly this and cannot be
used here:

    psycopg.errors.ObjectNotInPrerequisiteState: cannot detach partitions
    concurrently when a default partition exists

The default partition is not negotiable. It is there so a price arriving for a
month nobody created a partition for is still stored, because losing a row to
housekeeping is the same class of failure as losing it to a missed tick. Dropping
the default to gain CONCURRENTLY would trade a certain small cost for a rare
total one.

So the detach is plain, under a short lock_timeout. It is a catalogue operation -
milliseconds once it has the lock - and the live writer's own transactions run
in about 450 ms, so the wait is sub-second in the normal case. If the lock does
not come quickly the detach is abandoned: the archive is already written and
verified, the partition stays, and the next run tries again. Failing to tidy up
is cheap; blocking the capture is not.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg
import structlog
from psycopg import sql
from psycopg.rows import tuple_row

log = structlog.get_logger(__name__)

PARTITION_RE = re.compile(r"^live_odds_snapshots_(\d{4})_(\d{2})$")
DEFAULT_RETENTION_MONTHS = 12
MANIFEST = "manifest.json"

ARCHIVED_TABLE = "market.live_odds_snapshots"
"""The only table this module retires. The pre-match series is bounded by the
fixtures that exist and is small enough to keep for ever - 23,068 rows against
the live series' tens of millions a year - so it is deliberately not here."""


@dataclass(frozen=True, slots=True)
class Partition:
    name: str
    year: int
    month: int
    rows: int
    bytes: int

    @property
    def qualified(self) -> str:
        return f"market.{self.name}"

    @property
    def first_of_month(self) -> date:
        return date(self.year, self.month, 1)


@dataclass
class RetentionPlan:
    keep: list[Partition] = field(default_factory=list)
    retire: list[Partition] = field(default_factory=list)
    cutoff: date | None = None

    @property
    def rows_to_retire(self) -> int:
        return sum(p.rows for p in self.retire)

    @property
    def bytes_to_retire(self) -> int:
        return sum(p.bytes for p in self.retire)


def months_before(today: date, months: int) -> date:
    """The first day of the month `months` before this one."""
    total = today.year * 12 + (today.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def partitions(conn: psycopg.Connection) -> list[Partition]:
    """Every dated live partition, with its real row count and size.

    reltuples is an estimate and this decides what gets dropped, so the rows are
    counted. A partition about to be deleted is worth one sequential scan.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT c.relname, pg_total_relation_size(c.oid)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'market' AND c.relkind = 'r'
              AND c.relname ~ '^live_odds_snapshots_[0-9]{4}_[0-9]{2}$'
            ORDER BY c.relname
            """
        )
        found = [(str(name), int(size)) for name, size in cur.fetchall()]

    out: list[Partition] = []
    for name, size in found:
        m = PARTITION_RE.match(name)
        if m is None:  # pragma: no cover - the SQL pattern already filtered
            continue
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                sql.SQL("SELECT count(*) FROM market.{}").format(sql.Identifier(name))
            )
            row = cur.fetchone()
        out.append(
            Partition(name, int(m.group(1)), int(m.group(2)),
                      int(row[0]) if row else 0, size)
        )
    return out


def plan(
    conn: psycopg.Connection,
    *,
    today: date,
    retention_months: int = DEFAULT_RETENTION_MONTHS,
) -> RetentionPlan:
    """What would be retired, and what would stay. Reads nothing destructive."""
    cutoff = months_before(today, retention_months)
    result = RetentionPlan(cutoff=cutoff)
    for p in partitions(conn):
        (result.retire if p.first_of_month < cutoff else result.keep).append(p)
    return result


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class ArchiveResult:
    partition: str
    path: Path
    rows_expected: int
    rows_written: int
    rows_read_back: int
    sha256: str
    bytes: int
    dropped: bool = False

    @property
    def verified(self) -> bool:
        return (
            self.rows_expected == self.rows_written == self.rows_read_back
            and self.rows_expected > 0
        )


def archive(
    conn: psycopg.Connection,
    partition: Partition,
    out_dir: Path,
    *,
    drop: bool = False,
) -> ArchiveResult:
    """Write one partition to Parquet, verify it, and optionally drop it.

    Parquet because the series is a column store's best case: 293 bytes a row in
    Postgres, most of it repeated fixture ids, bet ids, selections and match
    state. It is also readable by duckdb without restoring anything, so an
    archived month can still be queried.

    The drop is refused unless the archive read back with the same row count.
    """
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{partition.name}.parquet"

    columns = [
        "fixture_id", "provider_bet_id", "market_key", "selection", "line",
        "odds_decimal", "is_suspended", "is_main_line", "elapsed_minute",
        "elapsed_seconds", "score_home", "score_away", "status_long",
        "is_stopped", "is_blocked", "provider_updated_at", "captured_at",
        "payload_hash",
    ]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            sql.SQL("SELECT {} FROM market.{} ORDER BY captured_at, fixture_id").format(
                sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                sql.Identifier(partition.name),
            )
        )
        rows = cur.fetchall()

    table = pa.table(
        {name: [r[i] for r in rows] for i, name in enumerate(columns)}
    )
    pq.write_table(table, path, compression="zstd")

    read_back = int(pq.read_table(path).num_rows)
    result = ArchiveResult(
        partition=partition.name,
        path=path,
        rows_expected=partition.rows,
        rows_written=table.num_rows,
        rows_read_back=read_back,
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
    )

    if not result.verified:
        log.error(
            "live_archive.verification_failed",
            partition=partition.name,
            expected=result.rows_expected,
            written=result.rows_written,
            read_back=result.rows_read_back,
            detail="the partition was NOT dropped",
        )
        return result

    _write_manifest(out_dir, result, partition)

    if drop:
        result.dropped = _detach_and_drop(conn, partition)
        if result.dropped:
            log.info(
                "live_archive.retired",
                partition=partition.name,
                rows=result.rows_written,
                parquet_bytes=result.bytes,
                postgres_bytes=partition.bytes,
            )
    return result


def _detach_and_drop(
    conn: psycopg.Connection, partition: Partition, *, lock_timeout_ms: int = 5_000
) -> bool:
    """Detach and drop, or give up quickly and leave it for next time.

    The archive is already written and verified by the time this runs, so
    abandoning the drop costs nothing but disk. Waiting for the lock would cost
    the capture its tick, and a missed in-play price cannot be re-fetched.
    """
    conn.commit()
    try:
        with conn.cursor() as cur:
            # SET takes no parameters; set_config does, and `true` scopes it
            # to this transaction so nothing else inherits the timeout.
            cur.execute("SELECT set_config('lock_timeout', %s, true)",
                        (f"{lock_timeout_ms}ms",))
            cur.execute(
                sql.SQL(
                    "ALTER TABLE market.live_odds_snapshots "
                    "DETACH PARTITION market.{}"
                ).format(sql.Identifier(partition.name))
            )
            cur.execute(
                sql.SQL("DROP TABLE market.{}").format(sql.Identifier(partition.name))
            )
        conn.commit()
        return True
    except psycopg.errors.LockNotAvailable:
        conn.rollback()
        log.warning(
            "live_archive.lock_unavailable",
            partition=partition.name,
            detail="the archive is written and verified; the partition stays and "
                   "the next run will try again rather than stall the capture",
        )
        return False


def _write_manifest(out_dir: Path, result: ArchiveResult, partition: Partition) -> None:
    manifest_path = out_dir / MANIFEST
    entries: dict[str, object] = {}
    if manifest_path.exists():
        entries = json.loads(manifest_path.read_text())
    entries[partition.name] = {
        "file": result.path.name,
        "rows": result.rows_written,
        "sha256": result.sha256,
        "bytes": result.bytes,
        "postgres_bytes": partition.bytes,
        "year": partition.year,
        "month": partition.month,
        "source_table": ARCHIVED_TABLE,
    }
    manifest_path.write_text(json.dumps(entries, indent=2, sort_keys=True))


def verify(out_dir: Path) -> list[str]:
    """Problems with what is on disk, against the manifest. Empty means sound."""
    manifest_path = out_dir / MANIFEST
    if not manifest_path.exists():
        return [f"{manifest_path} is missing"]
    problems: list[str] = []
    for name, entry in sorted(json.loads(manifest_path.read_text()).items()):
        assert isinstance(entry, dict)
        path = out_dir / str(entry["file"])
        if not path.exists():
            problems.append(f"{name}: {path.name} is gone")
            continue
        if sha256_file(path) != entry["sha256"]:
            problems.append(f"{name}: {path.name} does not match its checksum")
    return problems

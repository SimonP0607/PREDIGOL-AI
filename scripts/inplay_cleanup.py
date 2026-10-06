"""Retire the in-play HISTORY from operational storage - safely, and with the evidence (owner's decision, 6 Oct 2026).

    python -m scripts.inplay_cleanup measure                                  # rows, bytes, dependencies, RAW: no write
    python -m scripts.inplay_cleanup archive --out DIR --backup-label LABEL  # export, read back, verify, record
    python -m scripts.inplay_cleanup verify DIR                               # re-verify an archive (no write)
    python -m scripts.inplay_cleanup purge-raw --archive DIR --confirm        # after revision 0069 only

The order is the safety:

1. a verified backup of PostgreSQL and the RAW store (taken before anything here runs);
2. ``measure`` - exactly what the in-play history holds, what depends on it, and that nothing else does;
3. ``archive`` - the two history tables streamed to gzip CSV and every /odds/live payload file copied into one tar,
   OUTSIDE PostgreSQL and outside the RAW store; then everything is READ BACK and compared with the database (row
   counts, a content hash, sums and spans per table; each payload file re-hashed and its body checked against the
   payload hash the index holds). Only a verified archive is recorded in audit.storage_cleanups;
4. revision 0069 drops the history tables, and refuses to unless they are empty or a verified archive with exactly
   their row counts is recorded;
5. ``purge-raw`` removes the archived /odds/live payloads from the RAW store and their index rows - keeping every one
   a quality issue still points to - and records the rows and bytes.

Why an archive at all, when a backup exists: the archive is the proof that what is removed is readable WITHOUT
restoring a 10 GB database, and it keeps the evidence behind the provider measurements documented in
docs/api-football/13_MEASURED_BEHAVIOUR.md and docs/owner/LIVE_ODDS_STORAGE_2026-10-06.md, for about 0.2 GB
compressed. Its place in production is cold object storage, not the server.

Pre-match prices are never touched: nothing here names market.odds_snapshots, market.final_prematch_odds,
market.near_close_snapshots, market.market_consensus or market.historical_odds, and no /odds payload.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import sys
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.core.config import settings
from fbi.core.version import code_version
from fbi.ingestion.payload_store import body_hash

HISTORY_TABLES: dict[str, tuple[str, ...]] = {
    "market.live_odds_snapshots": ("fixture_id", "provider_bet_id", "selection", "line", "captured_at"),
    "market.live_fixture_states": ("fixture_id", "captured_at"),
}
"""The in-play history and its primary key - the archive's row order."""
HISTORY_VIEWS = ("market.live_market_movement", "market.live_odds_at_instant")
LIVE_ENDPOINT = "/odds/live"
RAW_SUBJECT = "raw:/odds/live"
RAW_TAR = "raw/odds-live.tar"


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(settings.database.psycopg_url.replace("postgresql+psycopg://", "postgresql://"))


def _raw_root() -> Path:
    root = Path(settings.runtime.raw_store_dir)
    return root if root.is_absolute() else Path(__file__).resolve().parents[1] / root


def _exists(conn: psycopg.Connection[Any], relation: str) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (relation,))
        row = cur.fetchone()
        return bool(row and row[0])


def _relation_bytes(conn: psycopg.Connection[Any], relation: str) -> int:
    """Heap, TOAST and indexes of a table and of every partition under it.

    pg_partition_tree() lists nothing for a table that is not partitioned (market.live_fixture_states): its size is
    then its own. Before this was handled, the archive of 6 Oct 2026 recorded 0 bytes for that table."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT coalesce((SELECT sum(pg_total_relation_size(relid)) FROM pg_partition_tree(%s::regclass)), "
                    "pg_total_relation_size(%s::regclass))", (relation, relation))
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _table_stats(conn: psycopg.Connection[Any], table: str) -> dict[str, Any]:
    """What the database says about one history table, to compare the archive with."""
    has_odds = table == "market.live_odds_snapshots"
    odds = "coalesce(sum(odds_decimal), 0)::text" if has_odds else "NULL"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("SELECT count(*) AS rows, count(DISTINCT fixture_id) AS fixtures, "
                            "min(captured_at) AS first, max(captured_at) AS last, {odds} AS odds_sum FROM {t}")
                    .format(odds=sql.SQL(odds), t=sql.SQL(table)))
        row = cur.fetchone() or {}
    return {"rows": int(row["rows"]), "fixtures": int(row["fixtures"]),
            "first": row["first"].isoformat() if row["first"] else None,
            "last": row["last"].isoformat() if row["last"] else None, "odds_sum": row["odds_sum"]}


# -- measure -------------------------------------------------------------------------------------------------------


def measure(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "code_version": code_version(), "tables": {}}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_database_size(current_database()), (SELECT version_num FROM public.alembic_version)")
        db_bytes, revision = cur.fetchone() or (0, None)
    out |= {"database_bytes": int(db_bytes), "revision": revision}
    for table in HISTORY_TABLES:
        if not _exists(conn, table):
            out["tables"][table] = {"exists": False}
            continue
        out["tables"][table] = {"exists": True, "bytes": _relation_bytes(conn, table), **_table_stats(conn, table)}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT DISTINCT v.oid::regclass::text, src.oid::regclass::text FROM pg_depend d "
            "JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class v ON v.oid = r.ev_class "
            "JOIN pg_class src ON src.oid = d.refobjid WHERE d.classid = 'pg_rewrite'::regclass "
            "AND src.oid::regclass::text = ANY(%s) AND v.oid <> src.oid ORDER BY 1, 2",
            ([t for t in HISTORY_TABLES if _exists(conn, t)],))
        out["dependent_views"] = [{"view": v, "on": s} for v, s in cur.fetchall()]
        cur.execute(
            "SELECT conname, conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint WHERE contype = 'f' "
            "AND confrelid::regclass::text = ANY(%s)", ([t for t in HISTORY_TABLES if _exists(conn, t)],))
        out["foreign_keys_into_history"] = [{"name": n, "from": f, "to": t} for n, f, t in cur.fetchall()]
        cur.execute(
            "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND (p.prosrc ILIKE '%%live_odds_snapshots%%' "
            "OR p.prosrc ILIKE '%%live_fixture_states%%')")
        out["functions_naming_history"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT count(*), coalesce(sum(bytes), 0), min(fetched_at), max(fetched_at), "
            "count(*) FILTER (WHERE hash IN (SELECT payload_hash FROM audit.data_quality_issues "
            "WHERE payload_hash IS NOT NULL)) FROM raw.ingestion_payloads WHERE endpoint = %s", (LIVE_ENDPOINT,))
        n, size, first, last, evidence = cur.fetchone() or (0, 0, None, None, 0)
    out["raw"] = {"index_rows": int(n), "bytes": int(size), "first": first.isoformat() if first else None,
                  "last": last.isoformat() if last else None, "named_by_quality_issues": int(evidence)}
    return out


# -- archive -------------------------------------------------------------------------------------------------------


@dataclass
class ArchivedTable:
    table: str
    file: str
    rows: int
    content_sha256: str
    file_sha256: str
    file_bytes: int


def _export_table(conn: psycopg.Connection[Any], table: str, dest: Path) -> ArchivedTable:
    order = ", ".join(HISTORY_TABLES[table])
    query = sql.SQL("COPY (SELECT * FROM {t} ORDER BY {o}) TO STDOUT WITH (FORMAT csv, HEADER true)").format(
        t=sql.SQL(table), o=sql.SQL(order))
    content = hashlib.sha256()
    with gzip.open(dest, "wb", compresslevel=6) as gz, conn.cursor() as cur, cur.copy(query) as copy:
        for chunk in copy:
            data = bytes(chunk)
            gz.write(data)
            content.update(data)
    # The row count is the database's (same snapshot); the read-back must find exactly that many CSV records.
    rows = _table_stats(conn, table)["rows"]
    return ArchivedTable(table, dest.name, rows, content.hexdigest(), _sha256_file(dest), dest.stat().st_size)


def _read_back_table(path: Path, table: str) -> dict[str, Any]:
    """Decompress and parse the CSV: rows, content hash, fixtures, span, and the odds sum, as the database counts."""
    content = hashlib.sha256()
    with gzip.open(path, "rb") as gz:
        for block in iter(lambda: gz.read(1 << 20), b""):
            content.update(block)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as text:
        return _tally(csv.DictReader(text), table, content.hexdigest())


def _tally(reader: csv.DictReader[str], table: str, content_sha256: str) -> dict[str, Any]:
    rows = 0
    fixtures: set[str] = set()
    first: str | None = None
    last: str | None = None
    odds_sum = Decimal(0)
    for rec in reader:
        rows += 1
        fixtures.add(rec["fixture_id"])
        at = rec["captured_at"]
        first = at if first is None or at < first else first
        last = at if last is None or at > last else last
        if table == "market.live_odds_snapshots" and rec["odds_decimal"]:
            odds_sum += Decimal(rec["odds_decimal"])
    return {"rows": rows, "content_sha256": content_sha256, "fixtures": len(fixtures),
            "odds_sum": str(odds_sum) if table == "market.live_odds_snapshots" else None, "first": first,
            "last": last}


def _same_instant(text: str | None, iso: str | None) -> bool:
    if text is None or iso is None:
        return text is None and iso is None
    return datetime.fromisoformat(text.replace(" ", "T")) == datetime.fromisoformat(iso)


def _archive_raw(conn: psycopg.Connection[Any], out: Path) -> dict[str, Any]:
    root = _raw_root()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT hash, file_path, bytes FROM raw.ingestion_payloads WHERE endpoint = %s ORDER BY fetched_at",
                    (LIVE_ENDPOINT,))
        index = [(str(h), str(p), int(b or 0)) for h, p, b in cur.fetchall()]
    tar_path = out / RAW_TAR
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []
    with tarfile.open(tar_path, "w") as tar:
        for digest, rel, recorded in index:
            src = root / rel
            if not src.is_file():
                # Indexed, and not in the store: a gap the RAW integrity audit already reports (the 4 Oct 2026
                # 02:57 UTC stop). Nothing to copy; named in the manifest so the gap is not mistaken for ours.
                missing.append({"file_path": rel, "payload_hash": digest})
                continue
            tar.add(src, arcname=rel, recursive=False)
            files[rel] = {"payload_hash": digest, "sha256": _sha256_file(src), "bytes": src.stat().st_size,
                          "recorded_bytes": recorded, "readable": _readable_as(src.read_bytes(), digest)}
    damaged = sorted(name for name, f in files.items() if not f["readable"])
    return {"tar": RAW_TAR, "index_rows": len(index), "files": files, "missing": missing,
            "damaged_at_source": damaged, "tar_sha256": _sha256_file(tar_path), "tar_bytes": tar_path.stat().st_size}


def _readable_as(data: bytes, payload_hash: str) -> bool:
    """Whether these bytes are the payload: gzip JSON whose body hashes to the index's hash. A file damaged in the
    store (the 4 Oct 2026 02:57 UTC stop left a few empty or truncated) is archived byte for byte all the same, and
    marked: the archive reproduces the store exactly, it does not repair it."""
    try:
        envelope = json.loads(gzip.decompress(data))
    except (OSError, EOFError, ValueError):
        return False
    return isinstance(envelope, dict) and body_hash(envelope.get("body")) == payload_hash


def _verify_raw(out: Path, raw: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    tar_path = out / raw["tar"]
    if _sha256_file(tar_path) != raw["tar_sha256"]:
        return [f"{raw['tar']}: sha256 differs from the manifest"]
    seen: set[str] = set()
    with tarfile.open(tar_path, "r") as tar:
        for member in tar:
            fh = tar.extractfile(member)
            if fh is None:
                continue
            data = fh.read()
            expect = raw["files"].get(member.name)
            if expect is None:
                problems.append(f"{member.name}: in the tar, not in the manifest")
                continue
            seen.add(member.name)
            if hashlib.sha256(data).hexdigest() != expect["sha256"]:
                problems.append(f"{member.name}: sha256 differs")
                continue
            if _readable_as(data, expect["payload_hash"]) != expect.get("readable", True):
                problems.append(f"{member.name}: its body is not payload {expect['payload_hash'][:12]} "
                                "(or a file recorded as damaged now reads)")
    absent = set(raw["files"]) - seen
    problems += [f"{name}: in the manifest, not in the tar" for name in sorted(absent)[:20]]
    return problems


def _verify_tables(out: Path, manifest: dict[str, Any], db: dict[str, dict[str, Any]] | None) -> list[str]:
    problems: list[str] = []
    for table, entry in manifest["tables"].items():
        path = out / "db" / entry["file"]
        if _sha256_file(path) != entry["file_sha256"]:
            problems.append(f"{table}: archive file sha256 differs")
            continue
        back = _read_back_table(path, table)
        if back["rows"] != entry["rows"] or back["content_sha256"] != entry["content_sha256"]:
            problems.append(f"{table}: read back {back['rows']} rows / content {back['content_sha256'][:12]}, "
                            f"manifest {entry['rows']} / {entry['content_sha256'][:12]}")
        expected = db[table] if db is not None else entry["database"]
        if back["rows"] != expected["rows"] or back["fixtures"] != expected["fixtures"]:
            problems.append(f"{table}: {back['rows']} rows, {back['fixtures']} fixtures in the archive; "
                            f"{expected['rows']} / {expected['fixtures']} in the database")
        if not (_same_instant(back["first"], expected["first"]) and _same_instant(back["last"], expected["last"])):
            problems.append(f"{table}: span {back['first']}..{back['last']} differs from the database's")
        if expected.get("odds_sum") is not None and Decimal(back["odds_sum"]) != Decimal(expected["odds_sum"]):
            problems.append(f"{table}: odds sum {back['odds_sum']} differs from the database's {expected['odds_sum']}")
    return problems


def archive(out: Path, backup_label: str) -> int:
    out.mkdir(parents=True, exist_ok=False)
    (out / "db").mkdir()
    with _connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ  # one snapshot for the export and its stats
        present = [t for t in HISTORY_TABLES if _exists(conn, t)]
        if not present:
            print("nothing to archive: the in-play history tables do not exist (revision 0069 already applied)")
            return 1
        manifest: dict[str, Any] = {"created_at": datetime.now(UTC).isoformat(), "code_version": code_version(),
                                    "backup_label": backup_label, "tables": {}, "purpose": __doc__.split("\n\n")[0]}
        db: dict[str, dict[str, Any]] = {}
        for table in present:
            exported = _export_table(conn, table, out / "db" / f"{table}.csv.gz")
            db[table] = _table_stats(conn, table)
            db[table]["bytes"] = _relation_bytes(conn, table)
            manifest["tables"][table] = {**exported.__dict__, "database": db[table]}
        raw = _archive_raw(conn, out)
        conn.commit()
    manifest["raw"] = raw
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    sums = {f"db/{e['file']}": e["file_sha256"] for e in manifest["tables"].values()}
    sums[raw["tar"]] = raw["tar_sha256"]
    sums["manifest.json"] = _sha256_file(out / "manifest.json")
    (out / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in sorted(sums.items())))

    problems = _verify_tables(out, manifest, db) + _verify_raw(out, raw)
    if problems:
        print("ARCHIVE NOT VERIFIED - nothing recorded:\n  " + "\n  ".join(problems[:30]))
        return 1

    with _connect() as conn, conn.cursor() as cur:
        manifest_sha = sums["manifest.json"]
        for table, entry in manifest["tables"].items():
            cur.execute(
                "INSERT INTO audit.storage_cleanups (kind, subject, rows, bytes, archive_path, archive_sha256, "
                "backup_label, verified, details, code_version) VALUES ('inplay_archive', %s, %s, %s, %s, %s, %s, "
                "true, %s, %s)",
                (table, entry["rows"], entry["database"]["bytes"], str(out), manifest_sha, backup_label,
                 Jsonb({"file": f"db/{entry['file']}", "file_sha256": entry["file_sha256"],
                        "content_sha256": entry["content_sha256"], "fixtures": entry["database"]["fixtures"],
                        "first": entry["database"]["first"], "last": entry["database"]["last"]}), code_version()))
        cur.execute(
            "INSERT INTO audit.storage_cleanups (kind, subject, rows, bytes, archive_path, archive_sha256, backup_label, "
            "verified, details, code_version) VALUES ('inplay_archive', %s, %s, %s, %s, %s, %s, true, %s, %s)",
            (RAW_SUBJECT, len(raw["files"]), sum(f["bytes"] for f in raw["files"].values()), str(out), manifest_sha,
             backup_label, Jsonb({"tar": raw["tar"], "tar_sha256": raw["tar_sha256"], "index_rows": raw["index_rows"],
                                  "damaged_at_source": raw["damaged_at_source"],
                                  "missing_at_source": raw["missing"]}),
             code_version()))
        conn.commit()
    total = sum(e["file_bytes"] for e in manifest["tables"].values()) + raw["tar_bytes"]
    print(f"archive VERIFIED and recorded: {out}")
    for table, entry in manifest["tables"].items():
        print(f"  {table}: {entry['rows']:,} rows ({entry['database']['bytes']:,} bytes in PostgreSQL) -> "
              f"{entry['file_bytes']:,} bytes gzip CSV")
    print(f"  /odds/live payloads: {len(raw['files']):,} files ({sum(f['bytes'] for f in raw['files'].values()):,} "
          f"bytes) -> {raw['tar']}; damaged in the store before (archived as they are): "
          f"{len(raw['damaged_at_source'])}; indexed but absent from the store before: {len(raw['missing'])} "
          f"{[m['file_path'] for m in raw['missing']]}")
    print(f"  archive total {total:,} bytes; manifest sha256 {manifest_sha}")
    return 0


def verify(out: Path) -> int:
    manifest = json.loads((out / "manifest.json").read_text())
    sums = {line.split("  ", 1)[1].strip(): line.split("  ", 1)[0]
            for line in (out / "SHA256SUMS").read_text().splitlines() if line.strip()}
    problems = [f"{name}: sha256 differs" for name, digest in sums.items() if _sha256_file(out / name) != digest]
    problems += _verify_tables(out, manifest, None) + _verify_raw(out, manifest["raw"])
    if problems:
        print("ARCHIVE PROBLEMS:\n  " + "\n  ".join(problems[:30]))
        return 1
    print(f"archive verified: {out} ({sum(e['rows'] for e in manifest['tables'].values()):,} rows, "
          f"{len(manifest['raw']['files']):,} payload files)")
    return 0


# -- purge the RAW store ---------------------------------------------------------------------------------------------


def purge_raw(out: Path, *, confirm: bool) -> int:
    manifest = json.loads((out / "manifest.json").read_text())
    with _connect() as conn:
        if any(_exists(conn, t) for t in HISTORY_TABLES):
            print("refused: the in-play history tables still exist - revision 0069 drops them first")
            return 2
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT archive_sha256 FROM audit.storage_cleanups WHERE kind = 'inplay_archive' "
                        "AND subject = %s AND verified AND archive_path = %s ORDER BY id DESC LIMIT 1",
                        (RAW_SUBJECT, str(out)))
            row = cur.fetchone()
        if row is None or row[0] != _sha256_file(out / "manifest.json"):
            print("refused: no verified archive of the /odds/live payloads is recorded for this folder")
            return 2
        problems = _verify_raw(out, manifest["raw"])
        if problems:
            print("refused: the archive no longer verifies:\n  " + "\n  ".join(problems[:20]))
            return 2
        archived = {f["payload_hash"]: (name, f) for name, f in manifest["raw"]["files"].items()}
        absent = {m["payload_hash"]: m["file_path"] for m in manifest["raw"].get("missing", [])
                  if isinstance(m, dict)}
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT conrelid::regclass::text, a.attname FROM pg_constraint c JOIN pg_attribute a "
                        "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] WHERE c.contype = 'f' "
                        "AND c.confrelid = 'raw.ingestion_payloads'::regclass")
            referencing = cur.fetchall()
            named: set[str] = set()
            for table, column in referencing:
                cur.execute(sql.SQL("SELECT DISTINCT {c} FROM {t} WHERE {c} = ANY(%s)").format(
                    c=sql.Identifier(column), t=sql.SQL(table)), (list(archived) + list(absent),))
                named |= {str(r[0]) for r in cur.fetchall()}
            cur.execute("SELECT hash FROM raw.ingestion_payloads WHERE endpoint = %s AND hash = ANY(%s)",
                        (LIVE_ENDPOINT, list(archived) + list(absent)))
            indexed = {str(r[0]) for r in cur.fetchall()}
        root = _raw_root()
        targets = []
        for digest in sorted(indexed - named):
            if digest in absent:
                if (root / absent[digest]).exists():
                    print(f"refused: {absent[digest]} was absent when archived and is on disk now - archive again")
                    return 2
                targets.append((digest, root / absent[digest], 0))  # no file to remove: only its index row
                continue
            name, f = archived[digest]
            path = root / name
            if path.is_file() and _sha256_file(path) != f["sha256"]:
                print(f"refused: {name} on disk differs from the archived copy")
                return 2
            targets.append((digest, path, f["bytes"]))
        kept = sorted(indexed & named)
        freed = sum(b for _, p, b in targets if p.is_file())
        print(f"/odds/live payloads archived and indexed: {len(indexed):,}; kept as evidence of quality issues or other "
              f"references: {len(kept)}; to purge: {len(targets):,} ({freed:,} bytes)")
        if not confirm:
            print("dry run: pass --confirm to purge")
            return 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_payloads WHERE endpoint = %s AND hash = ANY(%s)",
                        (LIVE_ENDPOINT, [d for d, _, _ in targets]))
            deleted = cur.rowcount or 0
            cur.execute(
                "INSERT INTO audit.storage_cleanups (kind, subject, rows, bytes, archive_path, archive_sha256, "
                "backup_label, verified, details, code_version) VALUES ('inplay_raw_purge', %s, %s, %s, %s, %s, %s, "
                "true, %s, %s)",
                (RAW_SUBJECT, deleted, freed, str(out), _sha256_file(out / "manifest.json"), manifest["backup_label"],
                 Jsonb({"kept_as_evidence": kept, "index_rows_deleted": deleted}), code_version()))
        conn.commit()
    removed = failed = 0
    for _, path, _ in targets:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed += 1
            print(f"could not remove {path}: {exc}")
    print(f"purged: {deleted:,} index rows, {removed:,} files ({freed:,} bytes); {failed} files could not be removed; "
          f"{len(kept)} kept as evidence")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="inplay_cleanup", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("measure")
    a = sub.add_parser("archive")
    a.add_argument("--out", required=True)
    a.add_argument("--backup-label", required=True, help="the verified backup taken before (required)")
    v = sub.add_parser("verify")
    v.add_argument("folder")
    p = sub.add_parser("purge-raw")
    p.add_argument("--archive", required=True)
    p.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.cmd == "measure":
        with _connect() as conn:
            conn.read_only = True
            print(json.dumps(measure(conn), indent=1, default=str))
        return 0
    if args.cmd == "archive":
        return archive(Path(os.path.expanduser(args.out)), args.backup_label)
    if args.cmd == "verify":
        return verify(Path(os.path.expanduser(args.folder)))
    return purge_raw(Path(os.path.expanduser(args.archive)), confirm=args.confirm)


if __name__ == "__main__":
    sys.exit(main())

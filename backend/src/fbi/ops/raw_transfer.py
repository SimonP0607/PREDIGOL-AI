"""Move raw payloads between two installations without losing their lineage.

A payload fetched by one installation (the cloud replica, say) can be needed by
another (the machine) that cannot fetch it itself - Football-Data.co.uk is
unreachable from the machine's network. Copying the files by hand would leave
the receiving index without rows, or with rows that claim a fetch that never
happened there. This does it the auditable way:

``export``  the index rows of one provider and their files, each file checked
            against its recorded hash, into one tar with a manifest (sha256 of
            every file, the rows as they are).
``import``  verifies every file (sha256 AND the body hash the row names) before
            anything is written, extracts to the same relative paths, and
            inserts the rows under a NEW ledger run of type ``raw_transfer``
            whose params say where the payloads came from. ``fetched_at`` stays
            the time the provider actually answered - the transfer is a
            separate, dated event in the ledger, never a rewrite of the fetch.

An identical file already present is left alone; a different file at the same
path, or any hash that does not verify, refuses the whole import.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.core.errors import FbiError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.ingestion.payload_store import PayloadStore, body_hash

MANIFEST = "transfer_manifest.json"
FORMAT = 1


class TransferError(FbiError):
    """The archive does not verify: nothing was written."""


@dataclass
class ExportReport:
    path: Path
    rows: int
    bytes: int


@dataclass
class ImportReport:
    rows_in_archive: int
    files_written: int = 0
    files_already_present: int = 0
    rows_inserted: int = 0
    rows_already_indexed: int = 0
    run_id: int | None = None
    problems: list[str] = field(default_factory=list)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_payloads(conn: psycopg.Connection, raw_root: Path, out: Path, *, provider: str,
                    origin: str) -> ExportReport:
    """Write every indexed payload of ``provider`` into ``out`` (a tar)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT hash, provider, endpoint, params, fetched_at, http_status, results_count, file_path, "
                    "bytes FROM raw.ingestion_payloads WHERE provider = %s ORDER BY fetched_at, hash", (provider,))
        rows = cur.fetchall()
    if not rows:
        raise TransferError(f"no indexed payloads for provider {provider!r}")
    store = PayloadStore(raw_root)
    entries: list[dict[str, Any]] = []
    blobs: list[tuple[str, bytes]] = []
    for r in rows:
        path = raw_root / str(r["file_path"])
        if not path.is_file():
            raise TransferError(f"{r['file_path']}: indexed but not in the raw store")
        if body_hash(store.load(str(r["file_path"]))["body"]) != r["hash"]:
            raise TransferError(f"{r['file_path']}: does not re-hash to {r['hash'][:12]}")
        data = path.read_bytes()
        blobs.append((str(r["file_path"]), data))
        entries.append({**{k: r[k] for k in ("hash", "provider", "endpoint", "params", "http_status",
                                              "results_count", "file_path", "bytes")},
                        "fetched_at": r["fetched_at"].isoformat(), "sha256": _sha256(data)})
    manifest = {"format": FORMAT, "origin": origin, "provider": provider,
                "exported_at": datetime.now(UTC).isoformat(), "rows": entries}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w") as tar:
        for name, data in [(MANIFEST, json.dumps(manifest, indent=1).encode()), *blobs]:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    return ExportReport(out, len(entries), out.stat().st_size)


def _read_archive(archive: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    files: dict[str, bytes] = {}
    manifest: dict[str, Any] | None = None
    with tarfile.open(archive, "r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                raise TransferError(f"{member.name}: not a regular file")
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise TransferError(f"{name}: unsafe path")
            fh = tar.extractfile(member)
            assert fh is not None
            data = fh.read()
            if name == MANIFEST:
                manifest = json.loads(data)
            else:
                files[name] = data
    if manifest is None or manifest.get("format") != FORMAT:
        raise TransferError(f"{archive}: no {MANIFEST} of format {FORMAT}")
    return manifest, files


def import_payloads(conn: psycopg.Connection, raw_root: Path, archive: Path, *, reason: str,
                    apply: bool) -> ImportReport:
    """Verify everything, then (``apply``) write files and index rows under a new ledger run."""
    manifest, files = _read_archive(archive)
    rows: list[dict[str, Any]] = manifest["rows"]
    report = ImportReport(rows_in_archive=len(rows))
    to_write: list[tuple[Path, bytes]] = []
    for r in rows:
        data = files.get(r["file_path"])
        if data is None:
            report.problems.append(f"{r['file_path']}: listed in the manifest, missing from the archive")
            continue
        if _sha256(data) != r["sha256"]:
            report.problems.append(f"{r['file_path']}: sha256 differs from the manifest")
            continue
        if body_hash(json.loads(gzip.decompress(data))["body"]) != r["hash"]:
            report.problems.append(f"{r['file_path']}: body does not hash to {r['hash'][:12]}")
            continue
        target = raw_root / r["file_path"]
        if target.exists():
            if _sha256(target.read_bytes()) != r["sha256"]:
                report.problems.append(f"{r['file_path']}: a DIFFERENT file already exists at this path")
            else:
                report.files_already_present += 1
            continue
        to_write.append((target, data))
    extra = sorted(set(files) - {r["file_path"] for r in rows})
    report.problems.extend(f"{name}: in the archive but not in the manifest" for name in extra)
    if report.problems:
        raise TransferError("; ".join(report.problems[:5]))
    if not apply:
        report.files_written = len(to_write)
        return report

    ledger = RunLedger(conn)
    run_id = ledger.open("raw_transfer", params={"origin": manifest["origin"], "provider": manifest["provider"],
                                                  "exported_at": manifest["exported_at"], "reason": reason,
                                                  "archive_sha256": _sha256(archive.read_bytes())})
    report.run_id = run_id
    counters = RunCounters()
    for target, data in to_write:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        report.files_written += 1
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                "INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, "
                "http_status, results_count, file_path, bytes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (hash) DO NOTHING RETURNING hash",
                (r["hash"], run_id, r["provider"], r["endpoint"], Json(r["params"]),
                 datetime.fromisoformat(r["fetched_at"]), r["http_status"], r["results_count"], r["file_path"],
                 r["bytes"]))
            if cur.fetchone() is None:
                report.rows_already_indexed += 1
            else:
                report.rows_inserted += 1
    counters.payloads_stored = report.rows_inserted
    counters.rows_inserted = report.rows_inserted
    ledger.close(run_id, counters, notes=f"{report.rows_inserted} payload(s) of {manifest['provider']} fetched by "
                                         f"{manifest['origin']}; {report.files_written} file(s) written, "
                                         f"{report.files_already_present} already present")
    conn.commit()
    return report

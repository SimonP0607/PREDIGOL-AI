"""RAW integrity: every indexed payload is on disk, whole, and still the body its hash names.

    python -m scripts.audit_raw_integrity                    # every payload, in parallel
    python -m scripts.audit_raw_integrity --since 2026-10-01
    python -m scripts.audit_raw_integrity --no-hash          # existence, size and decoding only (faster)

For each row of raw.ingestion_payloads: the file exists, its size is the size recorded when it was
written, it decompresses and parses, and sha256 of the canonical body equals the row's hash. Nothing is
repaired: RAW is evidence. A damaged payload is reported - evidence ledger area ``raw_integrity``, with
its endpoint, parameters, time, recorded and actual size, and the normalized rows that name it - so the
decision about it is made by a person. Report: data/truth/<stamp>-raw_integrity/.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.ingestion.payload_store import body_hash
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
REPO = Path(__file__).resolve().parents[1]

PAYLOADS_SQL = """
SELECT hash, file_path, bytes, endpoint, params::text AS params, fetched_at FROM raw.ingestion_payloads
 WHERE (%(since)s::date IS NULL OR fetched_at >= %(since)s::date) ORDER BY fetched_at
"""

REFERENCING_SQL = """
SELECT n.nspname, c.relname, a.attname FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE a.attname IN ('payload_hash', 'source_payload_hash') AND NOT a.attisdropped
   AND n.nspname IN ('core', 'market', 'analytics') AND c.relkind IN ('r', 'p') AND NOT c.relispartition
"""
"""Tables (a partitioned table once, not each partition again) with a column naming a payload."""


def check(root: str, rows: list[tuple[str, str, int | None]], with_hash: bool) -> list[dict[str, Any]]:
    """Problems among ``rows`` ((hash, file, recorded bytes)); runs in a worker process. A file that reads
    whole and hashes right is sound even if its recorded size differs (``size_recorded_differs``: noted,
    not damage)."""
    out: list[dict[str, Any]] = []
    for h, file_path, recorded in rows:
        f = Path(file_path) if os.path.isabs(file_path) else Path(root) / file_path
        try:
            size = f.stat().st_size
        except OSError:
            out.append({"hash": h, "problem": "missing", "size": None})
            continue
        if size == 0:
            out.append({"hash": h, "problem": "empty", "size": 0})
            continue
        try:
            envelope = json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, EOFError, ValueError) as exc:
            out.append({"hash": h, "problem": "unreadable", "size": size, "why": type(exc).__name__})
            continue
        if with_hash:
            body = envelope.get("body") if isinstance(envelope, dict) else None
            if body_hash(body) != h:
                out.append({"hash": h, "problem": "hash_mismatch", "size": size})
                continue
        if recorded is not None and size != recorded:
            out.append({"hash": h, "problem": "size_recorded_differs", "size": size})
    return out


DAMAGE = ("missing", "empty", "unreadable", "hash_mismatch")

STORE_SYNCED_SINCE = datetime(2026, 10, 4, 18, 35, 44, tzinfo=UTC)
"""Since this commit (e4385bc) the store syncs each payload before renaming it into place, and the directory after.
Damage to a payload written later means the fix did not hold: HIGH. Damage written before it is the bounded
residue of the 4 Oct 2026 02:57 UTC stop - three files; its severity follows what the rows naming it feed."""

NO_MODEL_TABLES = frozenset({"market.live_odds_snapshots", "market.live_fixture_states", "core.fixture_live_states",
                             "market.live_odds_current", "market.live_fixture_current"})
"""In-play tables: shown on the live page, never a model or backtest input (``fbi.odds.live_capture``). The first two
held the in-play history until revision 0069 dropped it; the current book (0068) keeps no RAW link of its own."""


def severity_of(fetched_at: datetime, rows_naming_it: dict[str, int]) -> str:
    """HIGH for damage the fixed store let through; before the fix, LOW when every row naming the payload is in-play
    data no model reads, MEDIUM otherwise (rows a model may read that can no longer be re-derived)."""
    if fetched_at >= STORE_SYNCED_SINCE:
        return "high"
    return "low" if set(rows_naming_it) <= NO_MODEL_TABLES else "medium"


def scan(rows: list[dict[str, Any]], *, root: str, with_hash: bool, workers: int) -> list[dict[str, Any]]:
    items = [(str(r["hash"]), str(r["file_path"]), r["bytes"]) for r in rows]
    chunks = [items[i:i + 500] for i in range(0, len(items), 500)]
    problems: list[dict[str, Any]] = []
    if workers <= 1:
        for c in chunks:
            problems += check(root, c, with_hash)
        return problems
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for found in pool.map(check, [root] * len(chunks), chunks, [with_hash] * len(chunks)):
            problems += found
    return problems


def referencing(conn: psycopg.Connection[Any], hashes: list[str]) -> dict[str, dict[str, int]]:
    """Normalized rows that name each damaged payload (rows whose source cannot be re-read)."""
    out: dict[str, dict[str, int]] = {h: {} for h in hashes}
    if not hashes:
        return out
    with conn.cursor() as cur:
        cur.execute(REFERENCING_SQL)
        cols = cur.fetchall()
        for schema, table, column in cols:
            cur.execute(f"SELECT {column}, count(*) FROM {schema}.{table} WHERE {column} = ANY(%s) GROUP BY 1",
                        (hashes,))
            for h, n in cur.fetchall():
                out[str(h)][f"{schema}.{table}"] = int(n)
    return out


def evidence(problems: list[dict[str, Any]], meta: dict[str, dict[str, Any]],
             refs: dict[str, dict[str, int]]) -> list[Evidence]:
    items = []
    for p in problems:
        m = meta[p["hash"]]
        naming = refs.get(p["hash"], {})
        severity = severity_of(m["fetched_at_dt"], naming)
        bounded = "" if severity == "high" else (
            "; written before the store synced its files (e4385bc, 4 Oct 2026 18:35 UTC): the cause is fixed and the "
            "damage bounded" + (", and every row naming it is in-play data no model reads" if severity == "low"
                                else ""))
        items.append(Evidence(
            key=f"raw_integrity:{p['hash']}", area="raw_integrity", issue_type="RAW_PAYLOAD_DAMAGED",
            severity=severity, at_fault="predigol", entity=f"{m['endpoint']} {m['params']}",
            claim=(f"RAW payload {p['hash'][:12]} ({m['endpoint']} {m['params']}, fetched {m['fetched_at']}) is "
                   f"{p['problem'].replace('_', ' ')}: {p['size']} bytes on disk, {m['bytes']} recorded; "
                   f"{sum(naming.values())} normalized rows name it and cannot be re-derived from it{bounded}"),
            db={"file": m["file_path"], "recorded_bytes": m["bytes"], "on_disk": p["size"],
                "problem": p["problem"], "rows_naming_it": refs.get(p["hash"], {})},
            root_cause="the payload was renamed into place before its bytes reached the disk, and the machine "
                       "stopped (every damaged payload of 4 Oct 2026 was written between 02:57:16 and 02:57:46 UTC)",
            fix="the store syncs each payload before the rename and the directory after it, and rewrites an empty "
                "file from the same body (be-58); the damaged file itself cannot be repaired - RAW is evidence - and "
                "the rows written from it at the time are kept",
            test="tests/unit/test_payload_store.py::test_an_empty_file_left_by_a_crash_is_not_taken_as_the_payload",
            status="MONITOR" if severity != "high" else "OPEN"))
    return items


def markdown(summary: dict[str, Any], problems: list[dict[str, Any]], meta: dict[str, dict[str, Any]],
             refs: dict[str, dict[str, int]]) -> str:
    lines = ["# RAW integrity audit", "",
             f"{summary['payloads']} payloads checked ({'body hash included' if summary['hash_checked'] else 'no hash'}"
             f"): {summary['damaged']} damaged — " + (", ".join(f"{k} {v}" for k, v in summary["problems"].items())
                                                    or "none") + ".", ""]
    if problems:
        lines += ["| Payload | Endpoint | Params | Fetched | Problem | On disk / recorded | Rows naming it |",
                  "|---|---|---|---|---|---|---|"]
        for p in problems:
            m = meta[p["hash"]]
            lines.append(f"| `{p['hash'][:12]}` | `{m['endpoint']}` | `{m['params']}` | {m['fetched_at']} | "
                         f"{p['problem']} | {p['size']} / {m['bytes']} | "
                         f"{', '.join(f'{k} {v}' for k, v in refs.get(p['hash'], {}).items()) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, help="only payloads fetched on or after this date")
    ap.add_argument("--no-hash", action="store_true", help="skip the body hash (existence, size, decoding only)")
    ap.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1))
    args = ap.parse_args(argv)
    root = Path(settings.runtime.raw_store_dir)
    root = root if root.is_absolute() else REPO / root
    at = now()
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '600s'")
        run = V2Run(conn, None, "raw_integrity", at, params={"since": str(args.since) if args.since else None,
                                                             "hash": not args.no_hash})
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PAYLOADS_SQL, {"since": args.since})
            rows = cur.fetchall()
        found = scan(rows, root=str(root), with_hash=not args.no_hash, workers=args.workers)
        problems = [p for p in found if p["problem"] in DAMAGE]
        noted = Counter(p["problem"] for p in found if p["problem"] not in DAMAGE)
        meta = {str(r["hash"]): {**r, "fetched_at": str(r["fetched_at"]), "fetched_at_dt": r["fetched_at"]}
                for r in rows}
        refs = referencing(conn, [p["hash"] for p in problems])
        items = evidence(problems, meta, refs)
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        if args.since is None:
            clear_unseen(conn, area="raw_integrity", scope_prefix="raw_integrity:", seen=[e.key for e in items], at=at)
        summary = {"payloads": len(rows), "hash_checked": not args.no_hash, "damaged": len(problems),
                   "problems": dict(Counter(p["problem"] for p in problems)),
                   "by_endpoint": dict(Counter(meta[p["hash"]]["endpoint"] for p in problems)), "noted": dict(noted),
                   "evidence": len(codes)}
        folder = write_report(REPORTS, "raw_integrity", at,
                              {"summary": summary, "damaged": [{**p, **{k: str(v) for k, v in meta[p["hash"]].items()},
                                                                "rows_naming_it": refs.get(p["hash"], {})}
                                                               for p in problems]},
                              markdown(summary, problems, meta, refs))
        status = run.finish(summary, report_dir=folder)
    print(json.dumps({**summary, "report": str(folder), "status": status}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

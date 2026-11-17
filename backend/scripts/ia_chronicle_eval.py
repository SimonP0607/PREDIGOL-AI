"""The factual evaluation of the single chronicle and the comparison for the retirement of the duplicated texts (IA-118, IA-119).

    python -m scripts.ia_chronicle_eval protocol                    # the preregistered protocol and whether it is signed (read-only)
    python -m scripts.ia_chronicle_eval sample --out sheet.csv      # the deterministic sample of chronicle-review-v2 (read-only)
    python -m scripts.ia_chronicle_eval score sheet.csv             # the filled sheet against the protocol (read-only)
    python -m scripts.ia_chronicle_eval compare --days 14           # retire-compare-v1 on the same matches (read-only)

Everything here reads or computes: nothing is written, switched or signed. «signed» is the owner's signature of AD-F06 (or, for ``compare``,
of AD-F05) in its fingerprint of now, read from ``ai.protocol_signatures`` (IA-143; signed with ``scripts/ia_protocols.py``); where the
database cannot be reached ``protocol`` and ``score`` still answer, with «signed» false and ``signature_read`` false. Exit 0 when it ran, 2
when it cannot run.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.chronicle import plan as cp
from fbi.chronicle import protocol, retire, review_v2
from fbi.core.clock import now
from fbi.protosign import store as signatures

OK, CANNOT = 0, 2
COLUMNS = ("review_id", "chronicle_id", "fixture_id", "part", "section", "index", "text", "cited", "double", "label", "label_second", "note")
REVIEWS_SQL = """
SELECT r.id, r.chronicle_id, r.fixture_id, r.items, c.plan
  FROM ai.chronicle_reviews r JOIN ai.chronicles c ON c.id = r.chronicle_id
 WHERE r.version = %(version)s AND r.chronicle_id IS NOT NULL AND r.created_at >= %(since)s
 ORDER BY r.id
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_chronicle_eval", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("protocol", "sample", "score", "compare"))
    ap.add_argument("sheet", nargs="?", help="score: the filled sheet (CSV)")
    ap.add_argument("--out", help="sample: where to write the sheet (CSV)")
    ap.add_argument("--days", type=int, default=30, help="sample and compare: the window, in days (default 30)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _connect(dsn: str | None) -> psycopg.Connection[Any]:
    from fbi.core.config import settings as platform

    conn = psycopg.connect(dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c statement_timeout=95000")
    conn.read_only = True
    return conn


def sample_rows(conn: psycopg.Connection[Any], *, days: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REVIEWS_SQL, {"version": review_v2.VERSION, "since": now() - timedelta(days=days)})
        found = [dict(r) for r in cur.fetchall()]
    chosen, double = protocol.sample(int(r["id"]) for r in found)
    by = {int(r["id"]): r for r in found}
    reviews = []
    for rid in chosen:
        r = by[rid]
        facts = {f.id: {"kind": f.kind, "params": dict(f.params)} for f in cp.from_json(r["plan"]).facts}
        reviews.append({**r, "facts": facts})
    return protocol.sheet(reviews, double=double)


def write_sheet(rows: Sequence[dict[str, Any]], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r.get(k) for k in COLUMNS}, "cited": json.dumps(r.get("cited"), ensure_ascii=False)})


def read_sheet(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [{**r, "review_id": int(r["review_id"])} for r in csv.DictReader(fh)]


def signature_of(dsn: str | None, key: str) -> tuple[dict[str, Any] | None, bool]:
    """The owner's signature of ``key`` in force, and whether it could be read at all (a database that cannot be reached: None, False)."""
    try:
        with _connect(dsn) as conn:
            found = signatures.in_force(conn, key)
            conn.rollback()
    except psycopg.Error:
        return None, False
    return found, True


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "protocol":
        found, read = signature_of(args.dsn, protocol.KEY)
        doc = {**protocol.status(found), "signature_read": read}
        sys.stdout.write(json.dumps(doc, indent=1, ensure_ascii=False, default=str) + "\n")
        return OK
    if args.command == "score":
        if not args.sheet:
            sys.stderr.write("score needs the filled sheet\n")
            return CANNOT
        rows = read_sheet(Path(args.sheet))
        found, read = signature_of(args.dsn, protocol.KEY)
        doc = {**protocol.score(rows, signed=found is not None), "signature_read": read}
        sys.stdout.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        return OK
    if args.command == "sample" and not args.out:
        sys.stderr.write("sample needs --out\n")
        return CANNOT
    with _connect(args.dsn) as conn:
        if args.command == "sample":
            rows = sample_rows(conn, days=args.days)
            signed = signatures.is_signed(conn, protocol.KEY)
            conn.rollback()
            write_sheet(rows, Path(args.out))
            sys.stdout.write(json.dumps({"sentences": len(rows), "out": args.out, "signed": signed}) + "\n")
            return OK
        until = now()
        since = until - timedelta(days=args.days)
        matches, found = retire.rows_for(conn, since=since, until=until)
        signed = signatures.is_signed(conn, retire.KEY)
        conn.rollback()
    doc = retire.report(matches, found, since=since, until=until, signed=signed)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())

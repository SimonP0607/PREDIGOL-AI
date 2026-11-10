"""The labelled bank of the claim extractor and of the chronicle's sentences (``label-bank-v1``, IA-030), from the command line.

    python -m scripts.ia_label_bank sample --bank claims --since 2026-10-26 --out /tmp/bank      # read only: writes the sheet files
    python -m scripts.ia_label_bank sample --bank sentences --since 2026-11-07 --out /tmp/bank
    python -m scripts.ia_label_bank score --sheet /tmp/bank/claims.csv                           # no database

``sample`` reads the database in a read-only transaction and writes two files under ``--out``: ``<bank>.json`` (the rows, the label sets
and what each label means) and ``<bank>.csv`` (the same rows to fill in a spreadsheet). The files hold the text of the evidence and of the
chronicle, the pages they cite and the names of the players: no key, no secret, no user. ``score`` reads a filled sheet (CSV or JSON) and
prints the score: agreement between labellers, the share of correct claims, the matrices of the system against the people. It decides
nothing. Exit 0 when it ran, 2 when it cannot run (an empty window, a sheet that cannot be read).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import psycopg

from fbi.ai import label_bank, label_bank_readers

OK, CANNOT = 0, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_label_bank", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="write the sheet of a bank (read-only database)")
    s.add_argument("--bank", choices=label_bank.BANKS, required=True)
    s.add_argument("--since", type=date.fromisoformat, required=True, help="first day of the window (UTC, YYYY-MM-DD)")
    s.add_argument("--until", type=date.fromisoformat, default=None, help="the day after the last one (UTC); now by default")
    s.add_argument("--quota", type=int, default=None, help="rows of the sheet (default: 150 claims, 60 sentences)")
    s.add_argument("--seed", default=label_bank.SEED, help="the seed of the order (the same seed, the same sheet)")
    s.add_argument("--versions", nargs="*", default=None, help="claims: only these extractor versions (extract-v1 extract-v2 extract-v3)")
    s.add_argument("--out", required=True, help="the folder the sheet is written to")
    s.add_argument("--dsn", help="the database (default: the worker's own)")
    c = sub.add_parser("score", help="score a filled sheet (no database)")
    c.add_argument("--sheet", required=True, help="the filled sheet, .csv or .json")
    c.add_argument("--json", action="store_true", help="print only the JSON")
    return ap


def window(since: date, until: date | None, *, now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(since, time(0), tzinfo=UTC)
    end = now if until is None else datetime.combine(until, time(0), tzinfo=UTC)
    if end <= start:
        raise ValueError(f"the window is empty ({start.isoformat()} to {end.isoformat()})")
    return start, end


def story_facts(conn: psycopg.Connection[Any], **kw: Any) -> Mapping[str, Mapping[str, Any]]:
    """The facts of a packet by reference, as the chronicle was written from them (``fbi.api.services.story.story_of``)."""
    from fbi.api.services import story

    return {f.ref: {"code": f.code, "params": dict(f.params)} for f in story.story_of(conn, **kw).facts}


def sample(args: argparse.Namespace) -> int:
    try:
        start, end = window(args.since, args.until, now=datetime.now(UTC))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    quota = args.quota if args.quota is not None else label_bank.QUOTA[args.bank]
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        conn.read_only = True
        if args.bank == label_bank.CLAIMS:
            candidates = label_bank_readers.claims(conn, since=start, until=end, versions=args.versions)
        else:
            candidates = label_bank_readers.sentences(conn, since=start, until=end)
        rows = label_bank.sample(candidates, quota=quota, seed=args.seed)
        if args.bank == label_bank.SENTENCES:
            label_bank_readers.cite(conn, rows, story_facts)
        conn.rollback()
    if not rows:
        sys.stderr.write(f"no candidate of the bank {args.bank} in the window\n")
        return CANNOT
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    doc = label_bank.sheet(rows, bank=args.bank, seed=args.seed, window={"since": start.isoformat(), "until": end.isoformat()})
    (out / f"{args.bank}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (out / f"{args.bank}.csv").write_text(label_bank.to_csv(rows, bank=args.bank), encoding="utf-8")
    sys.stdout.write(json.dumps({"bank": args.bank, "candidates": len({c.id for c in candidates}), "rows": len(rows),
                                 "double": sum(1 for r in rows if r["double"]), "strata": doc["strata"],
                                 "files": [str(out / f"{args.bank}.json"), str(out / f"{args.bank}.csv")]}, ensure_ascii=False) + "\n")
    return OK


def score(args: argparse.Namespace) -> int:
    try:
        rows = label_bank.read_sheet(Path(args.sheet).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"the sheet cannot be read: {exc}\n")
        return CANNOT
    rep = label_bank.score(rows)
    sys.stdout.write(json.dumps(rep, indent=1, ensure_ascii=False, default=str) + "\n")
    if not args.json:
        sys.stdout.write("\n".join(label_bank.lines(rep)) + "\n")
    return OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return sample(args) if args.command == "sample" else score(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""The bank of pages labelled by people and the gate of the extraction (IA-127, AD-C09, protocol ``AD-C09`` = ``extract-protocol-v1``).

    python -m scripts.ia_page_bank sample --days 14 --out banco.json [--labels etiquetas.csv]   the bank and its empty label sheet (READ ONLY)
    python -m scripts.ia_page_bank score --bank banco.json --labels etiquetas.csv --arms brazos.json   the measurement (no database)
    python -m scripts.ia_page_bank sign --reason "..." [--confirm-owner]   THE OWNER'S ACTION: the protocol signed before the first measurement
    python -m scripts.ia_page_bank record --report medida.json             one row of the gate extract_protocol (refused without the signature)
    python -m scripts.ia_page_bank status                                  the signature and the newest verdict (READ ONLY)

The bank holds third-party text: untrusted data, never published, never given to a model from here. The labels train nothing. Nothing
here reads or writes the gate research_v2: row 17 stays as it is.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from fbi.ai import extract_protocol, page_bank, page_bank_readers, source_policy
from fbi.core.config import settings

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ia_page_bank", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("sample", "score", "sign", "record", "status"))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--bank", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--arms", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--reason", default="")
    parser.add_argument("--confirm-owner", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "score":
        if not (args.bank and args.labels and args.arms):
            parser.error("score needs --bank, --labels and --arms")
        rows = json.loads(args.bank.read_text(encoding="utf-8"))["pages"]
        labels, bad_labels = page_bank.read_labels(args.labels.read_text(encoding="utf-8"))
        arms, bad_arms = page_bank.read_arms(args.arms.read_text(encoding="utf-8"))
        print(json.dumps(page_bank.score(rows, labels, arms, invalid=[*bad_labels, *bad_arms]), ensure_ascii=False, indent=2))
        return 0
    if args.command in ("sign", "record"):
        with psycopg.connect(settings.database.psycopg_url) as conn:
            if args.command == "sign":
                out = extract_protocol.sign(conn, reason=args.reason, confirm_owner=args.confirm_owner, at=now)
            else:
                if not args.report:
                    parser.error("record needs --report")
                out = extract_protocol.record(conn, json.loads(args.report.read_text(encoding="utf-8")), at=now)
            conn.commit()
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        conn.read_only = True
        if args.command == "status":
            print(json.dumps(extract_protocol.status(conn), ensure_ascii=False, indent=2, default=str))
            return 0
        start = now - timedelta(days=max(1, min(30, args.days)))
        pages, counts = page_bank_readers.candidates(conn, start=start, end=now, policy=source_policy.load(conn))
    rows = page_bank.sample(pages)
    doc = page_bank.sheet(rows, window=page_bank_readers.window_of(start, now))
    if args.out:
        args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        if args.labels:
            args.labels.write_text(page_bank.labels_template(rows), encoding="utf-8")
    print(json.dumps({"candidates": len(pages), "counts": counts, "sampled": len(rows), "double": sum(1 for r in rows if r["double"]),
                      "strata": doc["strata"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

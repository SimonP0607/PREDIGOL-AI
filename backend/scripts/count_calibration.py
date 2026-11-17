"""Corners and cards: the calibrator of the counts (IA-095, AD-B07) and their private evaluation (IA-096, AD-E03). SHADOW.

    python -m scripts.count_calibration sql --dir /tmp/lab        # the read-only COPY statements of the LAB, one file each
    python -m scripts.count_calibration lab --dir /tmp/lab --out report.json   # the protocol AD-B07 over the exported files
    python -m scripts.count_calibration fit --report report.json  # the current calibrator of each family (dry run: prints)
    FBI_COUNT_CALIBRATION=shadow python -m scripts.count_calibration fit --report report.json --write
    python -m scripts.count_calibration sign --id 12 --role CHAMPION --signed-by "Simon" --signature "..." --confirm-owner
    python -m scripts.count_calibration private                   # the private evaluation as a dry run: who would enter and why not
    FBI_COUNT_EVAL=shadow python -m scripts.count_calibration private --write

``lab`` reads files only. ``fit`` and ``private`` read the database through a read-only connection unless ``--write`` is given and their
switch says ``shadow``. ``sign`` is the owner's: it needs ``--confirm-owner``, and a CHAMPION needs the verdict VALIDADO (the database
refuses it too). 0 provider requests; 0 AI; nothing reaches a reader or a published pick.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.countcal import lab, market, private, store, walkforward
from fbi.families import history
from fbi.families.fit import OUTCOME_KNOWN_AFTER
from fbi.research import protocol

HISTORY: timedelta = timedelta(days=3 * 365)


def _connect(*, write: bool) -> psycopg.Connection[Any]:
    conn = psycopg.connect(settings.database.psycopg_url)
    conn.read_only = not write
    return conn


def cmd_sql(args: argparse.Namespace) -> int:
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, statement in lab.statements().items():
        (out / name.replace(".csv", ".sql")).write_text(statement + "\n", encoding="utf-8")
        print(f"{name}: {out / name.replace('.csv', '.sql')}")
    return 0


def cmd_lab(args: argparse.Namespace) -> int:
    report = lab.run(Path(args.dir), measured_at=datetime.now(UTC))
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps(report["verdicts"], ensure_ascii=False))
    return 0


def _verdicts(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("stamp") != protocol.stamp(lab.PROTOCOL):
        raise SystemExit("the report was not made under the registered protocol AD-B07 (its stamp differs)")
    return dict(report["verdicts"]), report


def cmd_fit(args: argparse.Namespace) -> int:
    verdicts, report = _verdicts(Path(args.report))
    if args.write and store.mode() != "shadow":
        raise SystemExit(f"{store.SWITCH} is not shadow: nothing is written")
    at = datetime.now(UTC).replace(microsecond=0)
    with _connect(write=args.write) as conn:
        out: dict[str, Any] = {}
        for measure in ("corners_ft", "cards_lines_ft"):
            cards = measure == "cards_lines_ft"
            matches = history.load(conn, measure, since=at - HISTORY, cutoff=at, with_referee=cards)
            known = market.referee_known(conn, start=at - HISTORY, end=at) if cards else None
            params, n = walkforward.fit_current(matches, measure=measure, at=at, referee_known=known)
            for family, p in params.items():
                verdict = verdicts.get(family, walkforward.INSUFFICIENT)
                entry: dict[str, Any] = {**p.as_json(), "verdict": verdict, "out_of_sample": n}
                if args.write:
                    block = report.get(measure, {})
                    summary = block.get("families", block).get(family, {})
                    entry["id"] = store.save(conn, family=family, params=p, known_at=at, fitted_at=datetime.now(UTC), verdict=verdict,
                                             protocol=report["stamp"], report={k: summary.get(k) for k in
                                                                               ("matches", "days", "cal_minus_raw", "cal_minus_base",
                                                                                "reasons")},
                                             train_from=(at - HISTORY).date(), train_to=(at - OUTCOME_KNOWN_AFTER).date(),
                                             code_version=None)
                out[family] = entry
        if args.write:
            conn.commit()
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    if not args.confirm_owner:
        raise SystemExit("the signature is the owner's: add --confirm-owner")
    with _connect(write=True) as conn:
        sid = store.sign(conn, calibrator_id=args.id, role=args.role, signed_by=args.signed_by, signature=args.signature,
                         at=datetime.now(UTC))
        conn.commit()
    print(json.dumps({"signature": sid, "calibrator": args.id, "role": args.role}))
    return 0


def cmd_private(args: argparse.Namespace) -> int:
    with _connect(write=args.write) as conn:
        rep = private.run_pass(conn, now=datetime.now(UTC), dry_run=not args.write)
    print(json.dumps(rep.as_json(), indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="count_calibration", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sql")
    p.add_argument("--dir", required=True)
    p.set_defaults(fn=cmd_sql)
    p = sub.add_parser("lab")
    p.add_argument("--dir", required=True)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_lab)
    p = sub.add_parser("fit")
    p.add_argument("--report", required=True)
    p.add_argument("--write", action="store_true")
    p.set_defaults(fn=cmd_fit)
    p = sub.add_parser("sign")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--role", choices=(store.CHAMPION, store.RETIRED), required=True)
    p.add_argument("--signed-by", required=True)
    p.add_argument("--signature", required=True)
    p.add_argument("--confirm-owner", action="store_true")
    p.set_defaults(fn=cmd_sign)
    p = sub.add_parser("private")
    p.add_argument("--write", action="store_true")
    p.set_defaults(fn=cmd_private)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())


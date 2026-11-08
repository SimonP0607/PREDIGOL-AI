"""Bounded automatic promotion (``autopromo-v1``, architecture section 6, phase P3): what WOULD be eligible - a dry run, nothing more.

    python -m scripts.ia_autopromo check                  # the switch, the policies the owner signed, every candidate and its verdict
    python -m scripts.ia_autopromo check --json
    python -m scripts.ia_autopromo check --at 2026-11-07T00:00:00+00:00

Read-only: the connection is opened read-only and rolled back, every statement is a SELECT (``fbi.governance.autopromo``) and there is no
writer - not even with ``FBI_AUTOPROMO=on``. Promoting stays the owner's. Exit 0, or 2 when it cannot run (a bad argument).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg

from fbi.governance import promotions as registry
from fbi.governance.autopromo import policy as pol
from fbi.governance.autopromo import sources
from fbi.governance.autopromo.evaluate import evaluate

COMMANDS = ("check",)
OK, CANNOT = 0, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_autopromo", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--at", help="as of this moment (ISO 8601 with its offset)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the result as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(args: argparse.Namespace, conn: psycopg.Connection[Any], env: Mapping[str, str] | None = None) -> tuple[dict[str, Any] | str, int]:
    at = None
    if args.at:
        try:
            at = datetime.fromisoformat(args.at)
        except ValueError:
            return {"error": f"{args.at!r} is not a moment (ISO 8601)"}, CANNOT
        if at.tzinfo is None:
            return {"error": "--at needs its offset (e.g. +00:00)"}, CANNOT
    switch = pol.switch_on(env)
    records = registry.all_promotions(conn, at=at)
    book = pol.read_policies(conn, at=at)
    candidates = sources.read_calibrator_candidates(conn, records, at=at)
    verdicts = [evaluate(c, book, switch_on=switch, history=records) for c in candidates]
    eligible = [v for v in verdicts if v.verdict == "ELIGIBLE"]
    out: dict[str, Any] = {
        "version": pol.VERSION, "at": args.at, "switch": "on" if switch else "off", "writes": False,
        "classes": [c.value for c in pol.ChangeClass], "never_automatic": sorted(pol.NEVER_AUTOMATIC),
        "policies": {c.value: (p.as_json() if (p := book.of(c)) is not None else None) for c in pol.ChangeClass},
        "refused_policies": [r.as_json() for r in book.refused],
        "no_candidate_source": sorted(c.value for c in sources.NO_SOURCE),
        "candidates": [v.as_json() for v in verdicts], "eligible": len(eligible),
    }
    if args.as_json:
        return out, OK
    lines = [f"{pol.VERSION}: switch {out['switch']} - dry run, writes nothing; {len(eligible)} of {len(verdicts)} candidates would be eligible"]
    for cls in pol.ChangeClass:
        p = book.of(cls)
        state = "no signed policy" if p is None else f"{p.status} (intel.promotions#{p.source_id}, {p.signed_at.isoformat(timespec='minutes')})"
        extra = "  [no source of candidates yet]" if cls in sources.NO_SOURCE else ""
        lines.append(f"  policy {cls.value:<20} {state}{extra}")
    lines.extend(f"  refused policy row intel.promotions#{r.source_id} ({r.raw_class}): {r.reason}" for r in book.refused)
    for v in verdicts:
        c = v.candidate
        lines.append(f"  {v.verdict:<12} {c.change_class:<18} {c.key:<24} {c.version:<8} vs {c.champion_version or '-':<8} "
                     f"{c.method or '-':<8} n={c.n:<6} {', '.join(v.reasons) or 'every condition holds'}")
    return "\n".join(lines), OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        conn.read_only = True
        out, code = run(args, conn)
        conn.rollback()
    if isinstance(out, str):
        sys.stdout.write(out + "\n")
    else:
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False) + "\n")
        if code == CANNOT and "error" in out:
            sys.stderr.write(f"{out['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""The evaluation after the match and the validation board, measured by the owner (IA-112/113, AD-K01/AD-K02). Read only.

    python -m scripts.ia_selection_eval dry-run --since 2026-10-18 --until 2026-11-16 [--json]
    python -m scripts.ia_selection_eval board   --since 2026-10-18 --until 2026-11-16 [--json]

``dry-run`` computes the evaluation of every settled selection of the matches that kicked off in the Bogotá days ``[since, until)``
(``eval-sel-v1``) WITHOUT writing it, with its parity against ``intel.decision_outcomes``, and the board (``board-v1``, protocol
``AD-K02``) over those evaluations. ``board`` reads the evaluations already kept in ``intel.selection_evaluations``. The connection is
read-only and each statement is held to 95 s. Exit status: 0 a report, 2 it cannot run (a bad day or option).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Final

import psycopg

from fbi.ai.calendar import day_bounds
from fbi.core.clock import now
from fbi.evalpass import store
from fbi.evaluation import board, views
from fbi.protosign import store as signatures

READ_ONLY: Final = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"
OK: Final = 0


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"not a day: {text!r} (AAAA-MM-DD)") from exc


def bounds(since: date, until: date, *, at: datetime) -> tuple[datetime, datetime]:
    if until <= since:
        raise ValueError("--until must be after --since")
    start, _ = day_bounds(since)
    end, _ = day_bounds(until)
    return start, min(end, at)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_selection_eval", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("dry-run", "board"))
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--dsn", default=None)
    return ap


def summary(evs: Sequence[Any], report: store.Report) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for ev in evs:
        r = ev.row
        counts[f"layer:{r['layer']}"] += 1
        counts[f"taken:{r['layer']}:{r['taken']}"] += 1
        counts[f"result:{r['result']}"] += 1
        counts[f"verdict:{r['verdict']}"] += 1
        counts[f"parity:{r['parity']}"] += 1
        counts[f"lineup:{ev.detail['lineup']['why']}"] += 1
    return {"report": report.as_json(), "counts": dict(sorted(counts.items()))}


def run(conn: psycopg.Connection[Any], command: str, *, start: datetime, end: datetime) -> tuple[dict[str, Any], int]:
    if command == "dry-run":
        evs, rep = store.dry_run(conn, start=start, end=end)
        doc = {"evaluations": summary(evs, rep), "board": board.build((board.scored_of(ev.row) for ev in evs),
                                                                      signed=signatures.is_signed(conn, board.PROTOCOL))}
        return doc, OK
    kept = views.board(conn, start=start, end=end)
    return {"board": kept if kept is not None else {"read_failed": True, "error": "UndefinedTable"}}, OK


def render(doc: dict[str, Any]) -> str:
    lines = []
    if "evaluations" in doc:
        lines.append(json.dumps(doc["evaluations"], ensure_ascii=False, sort_keys=True))
    b = doc["board"]
    if b.get("read_failed"):
        return "\n".join([*lines, "board: intel.selection_evaluations does not exist yet"]) + "\n"
    lines.append(f"board {b['version']} protocol {b['protocol']['version']} ({b['protocol']['fingerprint'][:12]}...), "
                 f"signed by the owner: {b['signed_by_owner']}; Bonferroni m = {b['bonferroni']['m']}; {b['counts']}")
    for c in b["cells"]:
        lines.append(f"  {c['layer']:16s} {c['family']:12s} {c['market']:16s} candidates {c['candidates']:6d}  sample {c['sample']:5d} of "
                     f"{c['needed']}  {c['verdict']:12s} {','.join(c['failed'])}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        start, end = bounds(parse_day(args.since), parse_day(args.until), at=now())
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=READ_ONLY) as conn:
        doc, code = run(conn, args.command, start=start, end=end)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

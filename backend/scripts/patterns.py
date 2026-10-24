"""The search for patterns in the settled decisions of the system (plan F12.6), on demand: where, by the dimensions of the plan, the system differs
from everything else by more than chance explains - and how often chance alone would have said the same.

    python -m scripts.patterns search                          # the last 90 days, every dimension and measure: the reading, in text
    python -m scripts.patterns search --days 60 --selected-only --metric clv --dimension competition --dimension market
    python -m scripts.patterns search --json --out patterns.json     # the whole reading as JSON, and also in a file
    python -m scripts.patterns propose                         # dry run: the hypotheses the search leaves, and which the database has already
    python -m scripts.patterns propose --confirm               # write them (status PROPOSED, by the system; the owner decides in Evolución)

``search`` reads through a connection that cannot write. ``propose`` reads the same way, shows what it would propose (only a finding that has the
same sign in both halves of the window, that is not just how the price is built and does not say again what a larger finding says; at most ``--limit``)
and why it leaves out each of the others, and writes only with ``--confirm``; one the database already has - whatever the owner decided about it - is
left alone. The weekly job does the same on its own when ``FBI_PATTERN_SEARCH`` is ``report`` or ``propose`` (off otherwise).
0 provider requests, 0 AI; nothing it prints or writes reaches a model, a forecast or a pick.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.research import pattern_search as ps

READ_ONLY = "-c default_transaction_read_only=on"


def instant(text: str) -> datetime:
    """A day or an instant as the command line writes it (``2026-10-24``, ``2026-10-24T09:00``); one without a zone is UTC."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a day or an instant (2026-10-24, 2026-10-24T09:00)") from None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def options(args: argparse.Namespace) -> dict[str, Any]:
    """The parameters of the search the command line gave (the ones it did not give stay as the module has them)."""
    given: dict[str, Any] = {"min_matches": args.min_matches, "min_z": args.min_z, "half_min_matches": args.half_min_matches,
                             "half_min_z": args.half_min_z, "alpha": args.alpha}
    if args.metric:
        given["metrics"] = tuple(dict.fromkeys(args.metric))
    if args.dimension:
        given["dimensions"] = tuple(dict.fromkeys(args.dimension))
    return given


def read(conn: psycopg.Connection[Any], args: argparse.Namespace) -> dict[str, Any]:
    """The search itself over the window the command line gave."""
    return ps.run(conn, at=args.until or clock_now(), days=args.days, selected_only=args.selected_only, **options(args))


def search_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    report = read(conn, args)
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text if args.json else ps.render(report))
    return 0


def propose_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    """What the search leaves for the owner: a dry run, or with ``--confirm`` the hypotheses written (the caller commits)."""
    report = read(conn, args)
    found = ps.proposals(report, limit=args.limit)
    left = ps.triage(report, args.limit)[1]
    repeating = sum(1 for f in report["found"] if f["stable"] is True)
    print(f"{len(report['found'])} findings reached the bar in {report['tests']:,} comparisons (chance alone would give {report['expected_by_chance']:.1f}); "
          f"{repeating} repeat in both halves of the window; {len(found)} would be proposed.")
    for f, why in left:
        print(f"left out: {ps.DIMENSION_ES[f['dimension']]} {f['label'][:ps.LABEL_CHARS]} ({ps.MEASURE_ES[f['metric']]}, z {f['z']:+.1f}) - {why}")
    if not found:
        print("Nothing to propose.")
        return 0
    have = ps.known(conn, found)
    fresh = [p for p in found if p.key not in have]
    for p in found:
        if p.key in have:
            hid, status = have[p.key]
            print(f"already proposed: {p.key} as #{hid} ({status})")
        else:
            print(f"{'PROPOSING' if args.confirm else 'WOULD PROPOSE'} {p.key} ({p.target}): {p.title}")
    if args.confirm and fresh:
        ids = ps.register(conn, fresh, at=args.until or clock_now())
        print(f"Proposed {len(ids)} hypotheses to the owner (ids {', '.join(f'#{i}' for i in ids)}).")
    elif fresh:
        print("Nothing was written. Add --confirm to propose these hypotheses.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="patterns", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name, text in (("search", "the reading: what reaches the bar, what came nearest, how many questions were asked"),
                       ("propose", "the hypotheses the search leaves for the owner (a dry run unless --confirm)")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("--days", type=int, default=ps.WINDOW_DAYS, help="kick-offs of the last N days (default %(default)s)")
        sp.add_argument("--until", type=instant, help="kick-offs before this day or instant, UTC (default: now)")
        sp.add_argument("--selected-only", action="store_true", help="only the decisions that stayed as picks or watch-list (not the rejected or the investigated)")
        sp.add_argument("--metric", action="append", choices=ps.METRICS, help="a measure to read; repeat it for several (default: all)")
        sp.add_argument("--dimension", action="append", choices=ps.DIMENSIONS, help="a dimension to group by; repeat it for several (default: all)")
        sp.add_argument("--min-matches", type=int, default=ps.MIN_MATCHES, help="matches a group needs, and the rest (default %(default)s)")
        sp.add_argument("--min-z", type=float, default=ps.MIN_Z, help="the |z| a difference must reach (default %(default)s)")
        sp.add_argument("--half-min-matches", type=int, default=ps.HALF_MIN_MATCHES, help="matches the group needs in each half to be read there (default %(default)s)")
        sp.add_argument("--half-min-z", type=float, default=ps.HALF_MIN_Z, help="the |z| each half must reach, with the same sign (default %(default)s)")
        sp.add_argument("--alpha", type=float, default=ps.ALPHA, help="the chance of one false finding among all the comparisons (default %(default)s)")
        if name == "search":
            sp.add_argument("--json", action="store_true", help="print the reading as JSON")
            sp.add_argument("--out", help="also write the reading (the JSON) to this file")
        else:
            sp.add_argument("--limit", type=int, default=ps.MAX_PROPOSALS, help="the most hypotheses to propose (default %(default)s)")
            sp.add_argument("--confirm", action="store_true", help="write the hypotheses; without it, a dry run")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    writes = args.command == "propose" and args.confirm
    try:
        with psycopg.connect(settings.database.psycopg_url, options=None if writes else READ_ONLY) as conn:
            code = search_command(conn, args) if args.command == "search" else propose_command(conn, args)
            if writes:
                conn.commit()
            else:
                conn.rollback()
            return code
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""The price rule, a yardstick in shadow (plan Intelligence 2026, INT-A10, IA-054): what the price ALONE would give. Read-only.

    python -m scripts.ia_price_rule report --since 2026-10-12 --until 2026-11-11                # the long history: the captures
    python -m scripts.ia_price_rule report --since 2026-11-10 --until 2026-11-12 --price book   # the odds book, with its refreshes
    python -m scripts.ia_price_rule report --since 2026-10-12 --until 2026-11-11 --json

Over the matches that kicked off from the start of ``--since`` to the start of ``--until`` (Bogotá days; ``--until`` not included, and never
after now), the selections of the core markets whose best price beat the consensus without margin by decision-v1's value threshold, taken at
the first moment they did (``fbi.decision.price_rule``), and their closing-line value against the last price observed before kick-off, with
its 95 % interval by match and by day. ``--price book`` reads the odds book as of each moment and its last answer before kick-off (it reads
the answers' bodies from the RAW store: ``--raw``, by default the worker's own). The report is a REFERENCE: it is never a pick and nothing
publishes it. The connection is read-only and each statement is held to 95 s. Exit status: 0 a report, 2 it cannot run (a bad day or option).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import psycopg

from fbi.ai.calendar import day_start
from fbi.core.clock import now
from fbi.decision import price_rule
from fbi.decision.engine import BOOK, CONSENSUS, PRICE_SOURCES
from fbi.storage.payload_store import PayloadStore

COMMANDS = ("report",)
OK, CANNOT = 0, 2
READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def bounds(since: date, until: date, *, at: datetime) -> tuple[datetime, datetime]:
    """The kick-offs of the report: from the start of ``since`` to the start of ``until`` (Bogotá), never after ``at``."""
    if until <= since:
        raise ValueError("--until must be after --since")
    return day_start(since), min(day_start(until), at)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_price_rule", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--since", required=True, help="the first day (Bogotá) of the kick-offs")
    ap.add_argument("--until", required=True, help="the day after the last (Bogotá), not included")
    ap.add_argument("--price", choices=PRICE_SOURCES, default=CONSENSUS,
                    help="the reading of the market: the captures' consensus (default) or the odds book's answer in force")
    ap.add_argument("--raw", help="the RAW store the book's answers are read from (default: the worker's own)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _ci(x: dict[str, Any]) -> str:
    if x["mean"] is None:
        return "-"
    return f"{x['mean']:+.2%} [{x['low']:+.2%}, {x['high']:+.2%}] ({x['blocks']} blocks)"


def render(doc: dict[str, Any]) -> str:
    t, m, c, g = doc["taken"], doc["measured"], doc["clv"], doc["gate"]
    p = doc["population"]
    lines = [f"{doc['version']} ({doc['role']}, never a pick) from {doc['source']}, kick-offs {doc['kickoff']['from']} .. {doc['kickoff']['to']}",
             f"  population: {p.get('matches', 0)} matches, {p.get('matches_with_price', 0)} with a price, {p.get('selections_with_price', 0)} "
             f"selections priced at {p.get('moments', 0)} moments",
             f"  taken: {t['selections']} selections of {t['matches']} matches {t['by_market']}; measured {m['selections']} of {m['matches']} "
             f"matches on {m['days']} days; without a CLV {m['without_clv']}",
             f"  CLV ({c['definition']}): by match {_ci(c['by_match'])}; by day {_ci(c['by_day'])}; median {c['median']}, positive "
             f"{c['positive']}",
             f"  price's value at the take: mean {doc['price_ev_at_take']['mean']}; drift of the consensus to the close (pp): mean "
             f"{doc['p_drift_pp']['mean']}; close {doc['close']['minutes_to_kickoff']['p50']} min before kick-off (p50), "
             f"{doc['close']['minutes_after_take']['p50']} min after the take"]
    for name in ("by_market", "by_price_ev", "by_lead_hours"):
        for k, v in doc[name].items():
            lines.append(f"    {name[3:]:9s} {k:9s} {v['selections']:6d} selections {v['matches']:5d} matches  {_ci(v)}")
    lines.append(f"  gate: {g['selections']} measured selections, {g['min_selections']} needed: {g['verdict']}")
    if "reader" in doc:
        r = doc["reader"]
        lines.append(f"  book read: {r['bodies_read']} bodies ({r['unreadable']} unreadable) {r['problems']}")
    return "\n".join(lines) + "\n"


def run(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, price: str = CONSENSUS,
        store: PayloadStore | None = None) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready) and the exit status. The connection is the caller's; nothing is written."""
    return price_rule.report(conn, since=since, until=until, source=price, store=store), OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        since, until = bounds(parse_day(args.since), parse_day(args.until), at=now())
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    store = PayloadStore(args.raw or platform.runtime.raw_store_dir) if args.price == BOOK else None
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=READ_ONLY) as conn:
        doc, code = run(conn, since=since, until=until, price=args.price, store=store)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

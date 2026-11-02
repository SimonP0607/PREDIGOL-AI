"""The catalogue of markets by family (plan F9): the keys, the rules that grade them, and the matrix of what each family can become.

    python -m scripts.markets status                  # the catalogue as the database holds it, the last stored matrix, drift (read only)
    python -m scripts.markets sync                    # dry run: what writing the catalogue would change (nothing is written)
    python -m scripts.markets sync --apply            # write the rules and keys that are missing and link the definitions
    python -m scripts.markets matrix                  # build the matrix from the real data and print it (nothing is written)
    python -m scripts.markets matrix --store          # ... and keep it: this is what the admin page reads
    python -m scripts.markets matrix --json           # the whole matrix as JSON

``sync`` is what the weekly job does first: it never overwrites (a value the database holds that differs from the code is DRIFT and is
reported), and it refuses a rule that differs from the stored one (a rule is never edited: a new convention is a new version).
``matrix`` only reads the data PrediGol already keeps; 0 provider requests.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.market import catalogue, matrix
from fbi.market.rules import RULES


def _cell(value: Any, width: int) -> str:
    text = "" if value is None else str(value)
    return (text[: width - 1] + "…" if len(text) > width else text).ljust(width)


def print_matrix(doc: dict[str, Any]) -> None:
    print(f"matrix {doc['matrix_version']} · taxonomy {doc['taxonomy_version']} · prices of the last {doc['window_days']} days · "
          f"{doc['duration_ms']} ms")
    head = ("grp", "row", "verdict", "prio", "reason", "bets", "ext", "price fx", "houses", "results")
    widths = (3, 22, 15, 6, 22, 5, 4, 9, 7, 8)
    print(" ".join(_cell(h, w) for h, w in zip(head, widths, strict=True)))
    for r in doc["rows"]:
        price, results = r["price"], r["results"]
        values = (r["group"], r["key"], r["verdict"], r["priority"], r["reason"], len(r["bets"]), len(r["extracted_bets"]),
                  price["fixtures"] if price["fixtures"] else "", price["houses_median"] if price["houses_median"] is not None else "",
                  f"{results['pct']:.0%}" if results and results.get("pct") is not None else "")
        print(" ".join(_cell(v, w) for v, w in zip(values, widths, strict=True)))
    s = doc["summary"]
    print(f"\nverdicts: {s['by_verdict']} · priorities: {s['by_priority']} · {s['definitions']} bets, {s['extracted']} extracted, "
          f"{s['with_rule']} with a rule ({s['liquidable_rules']} of {s['rules']} rules can grade)")
    c = s["cards"]
    if c["matches_with_events"]:
        print(f"cards: {c['matches_with_events']} matches counted from events, {c['matches_with_a_dismissal']} with a dismissal "
              f"(the conventions would grade those differently: {c['convention_sensitive_pct']:.1%}); events equal the statistics in "
              f"{c['events_equal_statistics_pct']:.1%} of {c['events_vs_statistics_compared']} compared")


def sync_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    try:
        report = catalogue.sync(conn)
    except catalogue.RuleChangedError as exc:
        conn.rollback()
        print(f"REFUSED: {exc}")
        return 1
    print(f"rules written {report.rules_written} · keys written {report.keys_written} of {report.keys_total} derived · "
          f"definitions linked to a key {report.markets_linked}, to a rule {report.rules_linked} · {report.definitions} definitions, "
          f"{report.with_rule} with a rule")
    for line in report.drift:
        print("DRIFT: " + line)
    if args.apply:
        conn.commit()
        print("written.")
    else:
        conn.rollback()
        print("dry run: nothing was written (use --apply).")
    return 1 if report.drift else 0


def status_command(conn: psycopg.Connection[Any]) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT (SELECT count(*) FROM market.markets) AS keys, "
                    "(SELECT count(*) FROM market.markets WHERE is_tracked) AS tracked, "
                    "(SELECT count(*) FROM market.markets WHERE is_model_enabled) AS modelled, "
                    "(SELECT count(*) FROM market.settlement_rules) AS rules, "
                    "(SELECT count(*) FROM market.market_definitions WHERE settle_rule IS NOT NULL) AS with_rule, "
                    "(SELECT count(*) FROM market.market_definitions WHERE market_key IS NOT NULL) AS with_key, "
                    "(SELECT count(*) FROM market.market_definitions) AS definitions")
        counts = cur.fetchone() or {}
    print(f"catalogue: {counts['keys']} keys ({counts['tracked']} followed, {counts['modelled']} modelled) · "
          f"{counts['rules']} of {len(RULES)} rules in the database · {counts['with_key']} of {counts['definitions']} definitions "
          f"with a key, {counts['with_rule']} with a rule")
    last = matrix.latest(conn)
    if last is None:
        print("matrix: none stored yet (python -m scripts.markets matrix --store)")
    else:
        print(f"matrix: {last['matrix_version']} generated {last['generated_at']:%Y-%m-%d %H:%M} UTC in {last['duration_ms']} ms · "
              f"verdicts {last['summary'].get('by_verdict')}")
    try:
        report = catalogue.sync(conn)
    except catalogue.RuleChangedError as exc:
        print(f"PROBLEM: {exc}")
        return 1
    finally:
        conn.rollback()
    pending = report.rules_written + report.keys_written + report.markets_linked + report.rules_linked
    print(f"pending in the database: {pending} changes (run 'sync --apply')" if pending else "the database says what the code says.")
    for line in report.drift:
        print("DRIFT: " + line)
    return 1 if report.drift else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="markets", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="the catalogue, the last stored matrix, drift (read only)")
    s = sub.add_parser("sync", help="write the rules and keys that are missing (dry run unless --apply)")
    s.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    m = sub.add_parser("matrix", help="build the matrix from the real data (nothing is written unless --store)")
    m.add_argument("--store", action="store_true", help="keep this matrix in market.catalogue_runs (what the admin page reads)")
    m.add_argument("--json", action="store_true", help="print the whole matrix as JSON")
    m.add_argument("--price-days", type=int, default=matrix.PRICE_DAYS, help="days of prices to look at (default %(default)s)")
    m.add_argument("--outcome-days", type=int, default=matrix.OUTCOME_DAYS, help="days of results to look at (default %(default)s)")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "sync":
            return sync_command(conn, args)
        if args.command == "status":
            code = status_command(conn)
            conn.rollback()
            return code
        doc = matrix.generate(conn, at=clock_now(), price_days=args.price_days, outcome_days=args.outcome_days)
        if args.json:
            print(json.dumps(doc, indent=1, default=str))
        else:
            print_matrix(doc)
        if args.store:
            run = matrix.store(conn, doc)
            conn.commit()
            print(f"stored as run {run}.")
        else:
            conn.rollback()
        return 0


if __name__ == "__main__":
    sys.exit(main())

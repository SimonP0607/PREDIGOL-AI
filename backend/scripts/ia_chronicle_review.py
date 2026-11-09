"""The post-match review of the chronicle (``chronicle-review-v1``, IA-022), from the command line.

    python -m scripts.ia_chronicle_review preview                  # judge what is due, write nothing (read-only transaction)
    python -m scripts.ia_chronicle_review preview --fixture 123    # one match, even if it was reviewed (never written)
    python -m scripts.ia_chronicle_review run --confirm-owner      # judge and write ``ai.chronicle_reviews`` (append-only)

``preview`` reads and judges: no model, no cost, nothing stored. ``run`` writes one row per chronicle that has line-ups or minutes and
was not reviewed yet; it needs ``--confirm-owner`` because it writes. The review states no cause and changes no model, threshold or pick.
Exit 0 when it ran (also with nothing due), 1 when a match asked for has no chronicle to judge, 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from fbi.chronicle import review
from fbi.core.clock import now

OK, NO, CANNOT = 0, 1, 2

ONE_SQL = review.DUE_SQL.replace("AND g.kickoff_at >= %(since)s AND g.kickoff_at <= %(until)s",
                                 "AND g.id = %(fixture)s").replace(
    "WHERE NOT EXISTS (SELECT 1 FROM ai.chronicle_reviews r WHERE r.narrative_id = n.id AND r.version = %(version)s)", "WHERE true")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_chronicle_review", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("preview", "run"))
    ap.add_argument("--fixture", type=int, help="preview: one match (reviewed or not)")
    ap.add_argument("--confirm-owner", action="store_true", help="run: the owner asked for the rows to be written")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the result as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def render(r: review.Review) -> str:
    s = r.summary
    lines = [f"{review.VERSION} fixture {r.fixture_id} chronicle {r.narrative_id} ({r.narrative_version}) packet {r.packet_id} {r.status}  "
             f"score {r.outcome['home_goals']}-{r.outcome['away_goals']}",
             f"  sentences {s['sentences']}  firm claims {s['firm_claims']}  held {s['held']}  contradicted {s['contradicted']}  "
             f"by reference {s['by_reference']}"]
    for item in r.items:
        if item["verdict"] != review.NOT_EVALUABLE:
            lines.append(f"  [{item['verdict']}] {item['section']}.{item['index']}: {item['text']}")
    lines += [f"  pick {p['market']} {p['selection']} {p['line']}: {p['outcome']} ({p['verdict']})" for p in r.picks]
    return "\n".join(lines)


def preview(conn: psycopg.Connection[Any], fixture: int | None) -> tuple[list[review.Review], int]:
    if fixture is None:
        due = review.rows_of(conn, review.DUE_SQL, {"since": now() - review.LOOKBACK - review.SETTLE, "until": now() - review.SETTLE,
                                                  "version": review.VERSION, "limit": review.LIMIT})
    else:
        due = review.rows_of(conn, ONE_SQL, {"fixture": fixture, "limit": 1})
    out = [r for r in (review.review_one(conn, row) for row in due) if r is not None]
    return out, OK if (due or fixture is None) else NO


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run" and not args.confirm_owner:
        sys.stderr.write("run writes ai.chronicle_reviews: add --confirm-owner when the owner asked for it\n")
        return CANNOT
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        if args.command == "preview":
            conn.read_only = True
            reviews, code = preview(conn, args.fixture)
            conn.rollback()
            if args.as_json:
                sys.stdout.write(json.dumps([r.__dict__ for r in reviews], indent=1, default=str, ensure_ascii=False) + "\n")
            else:
                sys.stdout.write("\n".join(render(r) for r in reviews) + ("\n" if reviews else "nothing due (or no data yet)\n"))
            return code
        report = review.run(conn, at=now())
        conn.commit()
    sys.stdout.write(json.dumps(report.__dict__, default=str) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())

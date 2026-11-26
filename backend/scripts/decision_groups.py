"""The weekly search over the pre-registered groups of decisions, on demand (RP-8.5, ``decision-groups-v1``).

    python -m scripts.decision_groups report                 # the last 90 days: the three columns (se confirma / sin evidencia / se descarta), reading only
    python -m scripts.decision_groups report --days 60 --json
    python -m scripts.decision_groups propose                # dry run: the confirmed groups the database does not have yet
    python -m scripts.decision_groups propose --confirm      # write them (status PROPOSED, by the system; the owner decides in Evolución)

``report`` reads through a connection that cannot write. The weekly job does the same on its own when ``FBI_DECISION_GROUPS`` is ``report`` or ``propose``
(off otherwise). 0 provider requests, 0 AI; nothing it prints or writes reaches a model, a forecast or a pick.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.research import decision_groups as dg
from fbi.research import pattern_search as ps

READ_ONLY = "-c default_transaction_read_only=on"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="decision_groups", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("report", "propose"):
        sp = sub.add_parser(name)
        sp.add_argument("--days", type=int, default=ps.WINDOW_DAYS)
        if name == "report":
            sp.add_argument("--json", action="store_true")
        else:
            sp.add_argument("--confirm", action="store_true", help="write the hypotheses; without it, a dry run")
    args = ap.parse_args(argv)
    writes = args.command == "propose" and args.confirm
    at = clock_now()
    with psycopg.connect(settings.database.psycopg_url, options=None if writes else READ_ONLY) as conn:
        report = dg.run(conn, at=at, days=args.days)
        if args.command == "report":
            cols = dg.columns(report)
            sys.stdout.write((json.dumps(cols, ensure_ascii=False, indent=2) if args.json else dg.render(cols)) + "\n")
        else:
            found = ps.proposals(report, only_surviving=True)
            known = ps.known(conn, found)
            for p in found:
                sys.stdout.write(f"{'YA ESTÁ' if p.key in known else 'NUEVA  '} {p.title}\n")
            if not found:
                sys.stdout.write("Ningún grupo se confirma esta semana.\n")
            if writes:
                sys.stdout.write(f"escritas: {len(ps.register(conn, found, at=at))}\n")
                conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

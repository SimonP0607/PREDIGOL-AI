"""The hypotheses the repository proposes from a measurement (plan F12): the register, and what the database has of it.

    python -m scripts.hypotheses show [--full]        # the register against the database: which proposals are registered, and their status
    python -m scripts.hypotheses register             # dry run: the proposals the database does not have yet
    python -m scripts.hypotheses register --confirm   # write them (status PROPOSED, by the system; the owner decides in Evolución)

The register is ``fbi.research.hypotheses.REGISTER``: each proposal with the figures it rests on, tied by a test to the owner guide they come from.
``show`` reads through a connection that cannot write; ``register`` writes only the proposals that are not there yet - one that is, whatever the
owner decided about it, is left alone. 0 provider requests, 0 AI; nothing it prints or writes reaches a model, a forecast or a pick.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.research import hypotheses


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "register"))
    ap.add_argument("--full", action="store_true", help="also print the text and the evidence of each proposal (show)")
    ap.add_argument("--confirm", action="store_true", help="write the missing proposals; without it, a dry run (register)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "show":
        with psycopg.connect(settings.database.psycopg_url, options="-c default_transaction_read_only=on") as conn:
            have = hypotheses.registered(conn)
        print(hypotheses.render(have, full=args.full))
        return 0
    with psycopg.connect(settings.database.psycopg_url) as conn:
        try:
            lines = hypotheses.register(conn, at=clock_now(), confirm=args.confirm)
        except ValueError as exc:
            conn.rollback()
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        if args.confirm:
            conn.commit()
        else:
            conn.rollback()
    print("\n".join(lines))
    if not args.confirm and any(line.startswith("WOULD") for line in lines):
        print("Nothing was written. Add --confirm to register these proposals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

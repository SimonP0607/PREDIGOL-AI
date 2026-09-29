"""Load the provider's bet and bookmaker catalogues into the database.

    python -m scripts.load_bet_catalogue            # both scopes, then bookmakers
    python -m scripts.load_bet_catalogue --scope inplay
    python -m scripts.load_bet_catalogue --dry-run  # read and report, write nothing

Idempotent. Nothing is ever deleted: a bet the provider stops listing is
reported as vanished and kept, because prices captured under it are real.

Exit status: 0 good, 1 the catalogue files are unusable, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from fbi.catalog.provider_markets import SCOPES, load_bet_catalogue, load_bookmakers
from fbi.core.config import settings
from fbi.core.errors import ConfigError
from fbi.core.logging import configure as configure_logging

REPO = Path(__file__).resolve().parents[1]
CATALOGUE_DIR = REPO / "docs" / "api-football" / "catalogues"


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="load_bet_catalogue", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scope", choices=sorted(SCOPES), action="append")
    parser.add_argument("--directory", default=str(CATALOGUE_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    directory = Path(args.directory)
    try:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            reports = load_bet_catalogue(conn, directory=directory, scopes=args.scope)
            books = load_bookmakers(conn, directory=directory) if not args.scope else 0
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
    except ConfigError as exc:
        print(f"REFUSED: {exc}")
        return 1

    for r in reports:
        print(f"{r.scope:>8}: {r.rows_in_file} bet(s) in the catalogue, {r.mapped} mapped to our markets, "
              f"{r.inserted} new, {r.refreshed} refreshed")
        for bet_id, was, now in r.renamed:
            print(f"           RENAMED bet {bet_id}: {was!r} -> {now!r}")
        for bet_id, name in r.vanished:
            print(f"           NO LONGER LISTED bet {bet_id}: {name!r} (kept)")
    if books:
        print(f"bookmakers: {books} upserted (names only; our own judgements untouched)")
    if args.dry_run:
        print("--dry-run: rolled back")
    return 0


if __name__ == "__main__":
    sys.exit(main())

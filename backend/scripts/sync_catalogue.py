"""Build the competition catalogue and every season, from coverage already stored.

    python -m scripts.sync_catalogue                 # what it would do
    python -m scripts.sync_catalogue --apply
    python -m scripts.sync_catalogue --apply --tiers 1,2

NO provider request is made. raw.league_coverage already holds what one /leagues call
returned - 1,247 leagues, 8,746 league-seasons, twelve flags each - so the catalogue
is built from the payload on disk. Spending a request per league to re-read what we
stored would break the rule against repeating what RAW can answer.

Selected competitions become is_tracked, because a competition worth migrating is
worth capturing prices for, and pre-match odds cannot be backfilled. Tracking is only
ever changed for the competitions this run names: running with --tiers 1 must not stop
the odds capture of tiers 2-4. Anything followed but not selected is listed, not
touched.

Exit status: 0 good, 1 a selected league was missing from the coverage, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from fbi.catalog.from_raw import build_catalogue
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.migration.selection import select_competitions


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="sync_catalogue", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tiers", default="", help="only these tiers, e.g. 1,2 (default: all)")
    parser.add_argument("--no-track", action="store_true",
                        help="build the catalogue without following any of it live")
    args = parser.parse_args()

    wanted = {int(t) for t in args.tiers.split(",") if t.strip()} or None

    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = select_competitions(conn)
        tiers = {c.provider_league_id: c.tier for c in report.selected
                 if c.tier is not None and (wanted is None or c.tier in wanted)}
        print(f"{len(tiers)} competition(s) selected"
              + (f" in tier(s) {sorted(wanted)}" if wanted else "")
              + f" of {len(report.selected)} in the selection")
        if not args.apply:
            print("no provider request is made either way; add --apply to write the catalogue")
            return 0
        built = build_catalogue(conn, tiers=tiers, tracked=set() if args.no_track else None)

    print(f"competitions: {built.competitions_inserted} new, {built.competitions_updated} updated")
    print(f"seasons     : {built.seasons_inserted} new, {built.seasons_updated} updated")
    print(f"tracked     : {built.tracked}   untracked: {built.untracked}")
    for problem in built.skipped:
        print(f"  SKIPPED {problem}")
    if built.tracked_outside_selection:
        print(f"still followed but not in this selection ({len(built.tracked_outside_selection)}), "
              "left exactly as they were:")
        for entry in built.tracked_outside_selection[:20]:
            print(f"  KEPT {entry}")
    return 1 if built.skipped else 0


if __name__ == "__main__":
    sys.exit(main())

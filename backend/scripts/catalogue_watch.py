"""PM-03-08 (Plan Maestro PM, DOC-010): has the provider listed a competition the owner asked for? 0 requests.

    python -m scripts.catalogue_watch            what raw.league_coverage (the daily /leagues on disk) has that the baseline of
                                                 config/catalogue_watch.yaml did not: new league ids of a priority country and
                                                 new seasons of discontinued or cyclical competitions
    python -m scripts.catalogue_watch --limits   also the limitations themselves (the eleven missing, the ten waiting)

Compares by identifier (``fbi.catalog.watch``): a renamed competition is not new. Read-only connection; nothing is asked of the
provider and nothing is written. It works whatever ``FBI_CATALOGUE_WATCH`` says (that switch only adds the same check to the daily
catalogue_refresh). Exit 0 with nothing new, 3 with findings, 1 when the database cannot be read.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import psycopg

from fbi.catalog import watch
from fbi.core.config import settings


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="catalogue_watch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limits", action="store_true", help="also print the missing and waiting competitions of the file")
    args = ap.parse_args(argv)
    config = watch.load()
    try:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            conn.execute("SET default_transaction_read_only = on")
            conn.execute("SET statement_timeout = '90s'")
            listed = watch.read_listed(conn)
    except psycopg.Error as exc:
        print(f"cannot read raw.league_coverage: {type(exc).__name__}", file=sys.stderr)
        return 1
    found = watch.findings(listed, config)
    print(f"baseline {config.baseline_at}: {sum(len(v) for v in config.known.values())} league ids in {len(config.known)} "
          f"countries; {len(config.waiting)} waiting; provider lists {len(listed)} leagues now "
          f"(FBI_CATALOGUE_WATCH {'on' if watch.watch_on() else 'off'})")
    if args.limits:
        for m in config.missing:
            print(f"  missing  {m.get('country')}: {m.get('asked')}" + (f" - {m['note']}" if m.get("note") else ""))
        for w in config.waiting:
            print(f"  waiting  {w.league_id} {w.name} ({w.country}) {w.kind}, last season {w.last_season}")
    for f in found:
        print("  " + f.line())
    print(watch.notes(found))
    return 3 if found else 0


if __name__ == "__main__":
    sys.exit(main())

"""Fill competition logos and country flags from the stored /leagues payload.

    python -m scripts.backfill_competition_media            # what it would change
    python -m scripts.backfill_competition_media --apply

NO provider request is made: the payload that built the catalogue already carries
every league's logo and its country's code and flag.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg

from fbi.catalog.media import backfill_competition_media
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.storage.payload_store import PayloadStore

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="backfill_competition_media", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(settings.runtime.raw_store_dir)
    root = root if root.is_absolute() else REPO / root
    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = backfill_competition_media(conn, PayloadStore(root), apply=args.apply)
        if args.apply:
            conn.commit()
    print(json.dumps({"applied": args.apply, **report.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

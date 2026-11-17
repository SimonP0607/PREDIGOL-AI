"""Stadiums: Wikidata item, coordinates and altitude; the stadium of matches the provider sends without an id (AD-H04; IA-076).
0 provider requests.

    python -m scripts.venue_geo fetch --out /srv/lab/venues/wd_20261117.json   # the snapshot: few batched SPARQL queries, 1/min
    python -m scripts.venue_geo load --snapshot F --sha256 H                    # dry run: what the load would write
    python -m scripts.venue_geo load --snapshot F --sha256 H --dem --apply      # load it, with the altitude from GLO-90
    python -m scripts.venue_geo link                                            # dry run: links of matches without an id
    python -m scripts.venue_geo link --apply                                    # write them (last 365 days, next 14)
    python -m scripts.venue_geo queue --kind fixture_venue --limit 30           # the questions for a person
    python -m scripts.venue_geo decide 17 accept --chosen 556 --apply           # answer one (accept | reject | dismiss | undo)
    python -m scripts.venue_geo retire 3 --note "bad snapshot" --apply          # take a whole load back
    python -m scripts.venue_geo status                                          # the coverage

``fetch`` is the only command that asks Wikidata (and ``load --dem`` the only one that reads the elevation model, by range
requests to its open bucket). Everything that writes is a dry run unless ``--apply`` is given. The actor is
``script:venue_geo``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.venues import elevation, store, wikidata

ACTOR = "script:venue_geo"


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.venue_geo", description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--batch", type=int, default=wikidata.BATCH)
    p = sub.add_parser("load")
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--sha256", required=True)
    p.add_argument("--dem", action="store_true", help="read the altitude from the Copernicus DEM GLO-90")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("link")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("queue")
    p.add_argument("--kind", choices=("venue_qid", "fixture_venue"))
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("decide")
    p.add_argument("queue_id", type=int)
    p.add_argument("decision", choices=store.DECISIONS)
    p.add_argument("--chosen")
    p.add_argument("--note")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("retire")
    p.add_argument("load_id", type=int)
    p.add_argument("--note", required=True)
    p.add_argument("--apply", action="store_true")
    sub.add_parser("status")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.execute("SET statement_timeout = '15min'")
        if args.command == "fetch":
            qids = sorted({q for qs in store.team_qids(conn).values() for q in qs})
            conn.rollback()
            if not qids:
                _print({"ok": False, "reason": "no club has a Wikidata item yet (load AD-H01 first)"})
                return 1
            digest = wikidata.fetch_snapshot(qids, args.out, batch=args.batch)
            _print({"snapshot": str(args.out), "sha256": digest, "clubs": len(qids)})
            return 0
        if args.command == "load":
            snap = wikidata.read_snapshot(args.snapshot, args.sha256)
            reader = elevation.DemReader(elevation.http_range_reader()) if args.dem else None
            _print(store.load(conn, snap, snapshot_name=args.snapshot.name, actor=ACTOR, apply=args.apply,
                              reader=reader).as_dict())
        elif args.command == "link":
            _print(store.link(conn, apply=args.apply).as_dict())
        elif args.command == "queue":
            with conn.cursor() as cur:
                cur.execute("SELECT id, kind, subject_id, reason, candidates, rules_version, raised_at "
                            "FROM core.venue_review_open WHERE %(kind)s::text IS NULL OR kind = %(kind)s "
                            "ORDER BY id LIMIT %(limit)s", {"kind": args.kind, "limit": args.limit})
                cols = [d.name for d in cur.description or ()]
                _print([dict(zip(cols, r, strict=True)) for r in cur.fetchall()])
        elif args.command == "decide":
            _print(store.decide(conn, args.queue_id, args.decision, actor=ACTOR, chosen=args.chosen, note=args.note,
                                apply=args.apply))
        elif args.command == "retire":
            _print(store.retire(conn, args.load_id, actor=ACTOR, note=args.note, apply=args.apply))
        elif args.command == "status":
            _print(store.coverage(conn))
        if getattr(args, "apply", False):
            conn.commit()
        else:
            conn.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())

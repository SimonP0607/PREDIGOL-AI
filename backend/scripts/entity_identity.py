"""External identity, aliases and one player key (AD-H01, AD-H02, AD-H09; IA-071). 0 provider requests.

    python -m scripts.entity_identity fetch --dir /srv/lab/reep               # download the pinned Reep release, check sha256
    python -m scripts.entity_identity verify --dir /srv/lab/reep              # only check the files already there
    python -m scripts.entity_identity load --dir /srv/lab/reep                # dry run: what the load would write
    python -m scripts.entity_identity load --dir /srv/lab/reep --apply        # load it (once per release and rules version)
    python -m scripts.entity_identity sync-core --apply                       # our names + old alias tables + homonym queue
    python -m scripts.entity_identity player-keys --create-missing --apply    # fill player_id on squads and claims (AD-H09)
    python -m scripts.entity_identity status                                  # what is in force
    python -m scripts.entity_identity audit                                   # the criteria; exit 1 when one fails
    python -m scripts.entity_identity queue --kind name_mismatch --limit 30   # the questions for a person
    python -m scripts.entity_identity decide 17 accept --note "..." --apply   # answer one (see QUEUE_ACTIONS)
    python -m scripts.entity_identity link player 123 reep "" rp0abc reject --apply   # one link directly
    python -m scripts.entity_identity undo --queue 17 --apply                 # take a decision back
    python -m scripts.entity_identity retire 4 --note "bad release" --apply   # take a whole load back

Everything that writes is a DRY RUN unless ``--apply`` is given (the work is done in a transaction that is rolled back), except
``player-keys``, which without ``--apply`` only counts. The release files are downloaded to a working folder on the server, never
into the repository; Wikidata and Transfermarkt are never queried. The actor recorded is ``script:entity_identity``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.people.identity import reep, store
from fbi.people.identity.rules import QUEUE_KINDS

ACTOR = "script:entity_identity"


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.entity_identity", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("fetch", "verify", "load"):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True, type=Path)
        p.add_argument("--release", default=reep.DEFAULT_RELEASE)
        if name == "load":
            p.add_argument("--apply", action="store_true")
    p = sub.add_parser("sync-core")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("player-keys")
    p.add_argument("--create-missing", action="store_true")
    p.add_argument("--batch", type=int, default=2000)
    p.add_argument("--apply", action="store_true")
    sub.add_parser("status")
    sub.add_parser("audit")
    p = sub.add_parser("queue")
    p.add_argument("--kind", choices=QUEUE_KINDS)
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("decide")
    p.add_argument("queue_id", type=int)
    p.add_argument("action")
    p.add_argument("--note")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("link")
    p.add_argument("entity_type")
    p.add_argument("entity_id", type=int)
    p.add_argument("system")
    p.add_argument("namespace")
    p.add_argument("external_id")
    p.add_argument("action", choices=("accept", "reject"))
    p.add_argument("--note")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("undo")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--decision", type=int)
    g.add_argument("--queue", type=int)
    p.add_argument("--note")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("retire")
    p.add_argument("load_id", type=int)
    p.add_argument("--note", required=True)
    p.add_argument("--apply", action="store_true")
    return ap


def _finish(conn: psycopg.Connection[Any], apply: bool) -> None:
    if apply:
        conn.commit()
    else:
        conn.rollback()
        print("dry run: nothing was kept (add --apply)")


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        _print(reep.fetch(args.dir, args.release))
        return 0
    if args.command == "verify":
        _print(reep.verify(args.dir, args.release))
        return 0
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.execute("SET statement_timeout = '15min'")
        if args.command == "load":
            files = reep.verify(args.dir, args.release)
            data = reep.read(args.dir, store.provider_ids(conn))
            report = store.load_reep(conn, data, release=args.release,
                                     release_sha256=reep.pinned(args.release).release_sha256, files=files,
                                     as_of=datetime.now(UTC).date(), actor=ACTOR)
            _print({"load": report.load_id, "already_loaded": report.already_loaded, "counts": report.counts,
                    "stats": report.stats})
            _finish(conn, args.apply)
            return 0
        if args.command == "sync-core":
            report = store.sync_core(conn, actor=ACTOR)
            _print({"load": report.load_id, "unchanged": report.already_loaded, "counts": report.counts,
                    "stats": report.stats})
            _finish(conn, args.apply)
            return 0
        if args.command == "player-keys":
            if not args.apply:
                _print({"rows without player_id": store.player_key_gaps(conn)})
                conn.rollback()
                return 0
            keys = store.backfill_player_keys(conn, batch=args.batch, create_missing=args.create_missing)
            _print({"players_created": keys.players_created, "filled": keys.filled, "left": keys.left})
            return 0
        if args.command == "status":
            _print(store.coverage(conn))
            conn.rollback()
            return 0
        if args.command == "audit":
            checks = store.audit(conn)
            conn.rollback()
            for c in checks:
                print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.value} {c.detail}")
            return 0 if all(c.ok for c in checks) else 1
        if args.command == "queue":
            for row in store.open_queue(conn, kind=args.kind, limit=args.limit):
                print(" | ".join("" if v is None else str(v) for v in row))
            conn.rollback()
            return 0
        try:
            if args.command == "decide":
                _print({"decisions": store.decide(conn, args.queue_id, args.action, actor=ACTOR, note=args.note)})
            elif args.command == "link":
                link = (args.entity_type, args.entity_id, args.system, args.namespace, args.external_id)
                _print({"decision": store.decide_link(conn, link, args.action, actor=ACTOR, note=args.note)})
            elif args.command == "undo":
                _print({"undone": store.undo(conn, actor=ACTOR, decision_id=args.decision, queue_id=args.queue,
                                             note=args.note)})
            elif args.command == "retire":
                _print({"retired": store.retire_load(conn, args.load_id, actor=ACTOR, note=args.note)})
        except store.DecisionError as exc:
            conn.rollback()
            print(f"refused: {exc}")
            return 1
        _finish(conn, args.apply)
        return 0


if __name__ == "__main__":
    sys.exit(main())

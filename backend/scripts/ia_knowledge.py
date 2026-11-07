"""The Knowledge Store (``ks-v1``, Plan Maestro IA, P1), read from the console: one surface over the four memories, in shadow. Reads only.

    python -m scripts.ia_knowledge about --type referee --id 412 [--at 2026-11-01T12:00:00Z] [--aspect discipline] [--json]
    python -m scripts.ia_knowledge episode --fixture 1234567 [--at ISO] [--json]
    python -m scripts.ia_knowledge relations --type player --id 276 [--at ISO] [--json]
    python -m scripts.ia_knowledge coverage [--json]

``about`` is everything known about an entity as of ``--at`` (now when not given): the states of memory-v4 and memory-fam-v1, the AI's events and
lessons, the matches Match Knowledge put together, the relations and the hypotheses; ``episode`` is a match as it was known then; ``coverage`` says,
per type of entity, how many each memory covers, where they overlap and where they leave gaps. Nothing known after ``--at`` is shown, the session is
read-only and nothing is written (``fbi.knowledge.store``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.knowledge import store


def moment(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.ia_knowledge", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("about", "relations"):
        s = sub.add_parser(name)
        s.add_argument("--type", required=True, choices=store.ENTITY_TYPES)
        s.add_argument("--id", required=True)
        s.add_argument("--at", type=moment)
        s.add_argument("--limit", type=int, default=store.LIMIT)
        s.add_argument("--json", action="store_true")
        if name == "about":
            s.add_argument("--aspect", action="append", dest="aspects")
    e = sub.add_parser("episode")
    e.add_argument("--fixture", required=True, type=int)
    e.add_argument("--at", type=moment)
    e.add_argument("--json", action="store_true")
    c = sub.add_parser("coverage")
    c.add_argument("--json", action="store_true")
    return p


def text_of_answer(answer: dict[str, Any]) -> str:
    e = answer["entity"]
    lines = [f"{e['type']} {e['id']}" + (f" - {e['name']}" if e.get("name") else "") + f"   as of {answer['at']}   ({answer['version']})",
             "counts: " + (", ".join(f"{k} {n}" for k, n in answer["counts"].items()) or "nothing known")]
    for r in answer["records"]:
        extra = " ".join(x for x in (
            f"status={r['status']}" if r["status"] else "", f"conf={r['confidence']}" if r["confidence"] is not None else "",
            f"valid={r['valid_from'] or '?'}..{r['valid_to'] or ''}" if r["valid_from"] or r["valid_to"] else "") if x)
        lines.append(f"  [{r['kind']}] {r['aspect']}  known {r['known_at']}  {r['source']['table']}#{r['source']['id']}"
                     f" {r['source']['version'] or ''}  {extra}".rstrip())
    for a in answer["absent"]:
        lines.append(f"  absent  {a['source']}: {a['reason']}" + (f" - {a['detail']}" if a["detail"] else ""))
    for source, n in answer["truncated"].items():
        lines.append(f"  truncated  {source}: {n} older records not shown (--limit)")
    return "\n".join(lines)


def text_of_coverage(report: dict[str, Any]) -> str:
    lines = [f"coverage ({report['version']})"]
    for kind, block in report["types"].items():
        lines.append(f"{kind}: {block['union']} entities in all, {block['in_every_source']} in every source")
        for source, n in block["sources"].items():
            lines.append(f"  {source:34} {n:>7}  only here {block['only_in'][source]:>7}  missing {block['missing_from'][source]:>7}")
        for pair, n in block["pairs"].items():
            lines.append(f"  overlap {pair}: {n}")
        if block["not_held_by"]:
            lines.append(f"  cannot hold a {kind}: {', '.join(block['not_held_by'])}")
        if "legacy_string_keys" in block:
            lines.append(f"  referees of memory-v2 keyed by a string (not counted): {block['legacy_string_keys']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    at = getattr(args, "at", None) or datetime.now(UTC)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.read_only = True
        if args.command == "coverage":
            report = store.coverage(conn)
            print(store.dumps(report) if args.json else text_of_coverage(report))
            return 0
        try:
            if args.command == "episode":
                answer = store.episode(conn, args.fixture, at=at)
            elif args.command == "relations":
                answer = store.relations(conn, args.type, args.id, at=at, limit=args.limit)
            else:
                answer = store.about(conn, args.type, args.id, at=at, aspects=args.aspects, limit=args.limit)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    data = answer.as_dict()
    print(store.dumps(data) if args.json else text_of_answer(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())

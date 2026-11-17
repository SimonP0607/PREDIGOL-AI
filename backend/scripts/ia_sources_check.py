"""The checker of the registry of sources (IA-062), BY HAND: it is not scheduled. See ``fbi.ai.source_check`` for what it does.

    python -m scripts.ia_sources_check --limit 20                       # 20 sources (pending and authorised, high priority first)
    python -m scripts.ia_sources_check --source es-marca --source co-eltiempo
    python -m scripts.ia_sources_check --limit 20 --dry-run             # which sources it would ask, without any request

One request per domain (``robots.txt``), a pause between them, no retry; never a source the directory found blocked; never Exa or a
model. It writes nothing anywhere: it prints the proposals (JSON). Reads the registry from the database (read-only), or from the
pinned file of the image without one (``--bundled``). Exit 0; 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import httpx

from fbi.ai import source_check as check
from fbi.ai import source_policy as policy
from fbi.ai.source_registry import Source


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_sources_check", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--source", action="append", default=[], help="a source id (repeatable)")
    ap.add_argument("--limit", type=int, default=10, help="at most this many sources (default 10, at most 200)")
    ap.add_argument("--dry-run", action="store_true", help="list the sources it would ask, make no request")
    ap.add_argument("--bundled", action="store_true", help="read the registry from the image's pinned file, not the database")
    ap.add_argument("--dsn")
    return ap


def chosen(loaded: policy.SourcePolicy, ids: Sequence[str], limit: int) -> tuple[list[Source], list[dict[str, Any]]]:
    sources = sorted(loaded.by_domain.values(), key=lambda s: (s.state != "verificada_autorizada", s.source_id))
    if ids:
        sources = [s for s in sources if s.source_id in set(ids)]
    out: list[Source] = []
    skipped: list[dict[str, Any]] = []
    for s in sources:
        why = check.skip_reason(s, excluded=loaded.standing(s.domain).excluded)
        if why:
            if ids:
                skipped.append({"source_id": s.source_id, "skipped": why})
            continue
        out.append(s)
        if len(out) >= max(1, min(limit, 200)):
            break
    return out, skipped


def robots(client: httpx.Client, domain: str) -> check.Observation:
    try:
        r = client.get(f"https://{domain}/robots.txt")
    except httpx.HTTPError:
        return check.observe(None)
    return check.observe(r.status_code, r.text[:200_000] if r.status_code == 200 else "")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn = None
    if not args.bundled:
        import psycopg

        from fbi.core.config import settings as platform

        try:
            conn = psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c default_transaction_read_only=on")
        except psycopg.Error as exc:
            print(json.dumps({"error": f"database: {type(exc).__name__} (use --bundled)"}))
            return 2
    try:
        loaded = policy.load(conn)
    finally:
        if conn is not None:
            conn.close()
    if loaded is None:
        print(json.dumps({"error": "no registry could be read"}))
        return 2
    sources, skipped = chosen(loaded, args.source, args.limit)
    if args.dry_run:
        print(json.dumps({"would_ask": [s.domain for s in sources], "skipped": skipped, "registry": loaded.version}, indent=2))
        return 0
    today = datetime.now(UTC).date()
    proposals = []
    with httpx.Client(timeout=check.TIMEOUT_SECONDS, headers={"user-agent": check.USER_AGENT}, follow_redirects=True,
                      max_redirects=3) as client:
        for i, s in enumerate(sources):
            if i:
                time.sleep(check.PAUSE_SECONDS)
            p = check.propose(s, robots(client, s.domain), today=today)
            proposals.append(asdict(p))
    changed = [p for p in proposals if p["proposed"] != p["current"]]
    print(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "registry": loaded.version, "asked": len(sources), "changes": changed,
                      "unchanged": len(proposals) - len(changed), "skipped": skipped}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

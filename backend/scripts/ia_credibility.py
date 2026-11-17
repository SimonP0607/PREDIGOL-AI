"""``credibility-v2`` (IA-126, AD-C08): the credibility of each source by type of fact, with its interval. It informs; it decides nothing.

    python -m scripts.ia_credibility snapshot              every source by type as of now, and the replay against credibility-v1 (READ ONLY)
    python -m scripts.ia_credibility snapshot --record     the same, appended to ai.source_credibility (what the shadow job does once a day)
    python -m scripts.ia_credibility show [--outlet X]     the newest snapshot kept, by source (READ ONLY)

No provider, no model. Nothing here changes a status, a confidence, a tier or a domain. Run it inside the worker's image after the deploy.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.gates import typed_visible
from fbi.core.config import settings
from fbi.evidence.credibility_reads import snapshot
from fbi.shadowjobs import source_credibility

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"
SHOW_SQL = """
SELECT outlet, tier, fact_type, resolved, corroborated, value, rate, ci_low, ci_high, sufficient, as_of
  FROM ai.source_credibility
 WHERE version = 'credibility-v2' AND as_of = (SELECT max(as_of) FROM ai.source_credibility WHERE version = 'credibility-v2')
   AND (%(outlet)s::text IS NULL OR outlet = %(outlet)s)
 ORDER BY sufficient DESC, resolved DESC, outlet, fact_type LIMIT %(limit)s
"""


def lines(snap: dict[str, Any], top: int) -> list[str]:
    creds = sorted(snap["credibilities"], key=lambda c: (-c["resolved"], c["outlet"], c["fact_type"]))
    out = [f"credibility-v2 a {snap['at']} · {snap['claims']} afirmaciones leídas · {len(creds)} pares fuente-tipo · "
           f"{sum(1 for c in creds if c['sufficient'])} con la muestra mínima ({creds[0]['min_resolved'] if creds else 30})"]
    for c in creds[:top]:
        ci = c["ci95"]
        out.append(f"  {c['outlet']:<32} {c['tier']} {c['fact_type']:<12} {c['corroborated']:>4}/{c['resolved']:<4} "
                   f"valor {c['value']:.3f} · IC95 {'-' if ci is None else f'{ci[0]:.2f}-{ci[1]:.2f}'} · {c['word']}")
    out.append(f"  frente a credibility-v1: {snap['replay']['by_reason']}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ia_credibility", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("snapshot", "show"))
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--outlet")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "snapshot" and args.record:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            print(json.dumps(source_credibility.run(conn, now=now, code_version=None), ensure_ascii=False, default=str))
        return 0
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        conn.read_only = True
        if args.command == "show":
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(SHOW_SQL, {"outlet": args.outlet, "limit": args.top})
                print(json.dumps([dict(r) for r in cur.fetchall()], ensure_ascii=False, indent=2, default=str))
            return 0
        snap = snapshot(conn, at=now, typed=typed_visible(conn))
    print(json.dumps(snap, ensure_ascii=False, indent=2, default=str) if args.json else "\n".join(lines(snap, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

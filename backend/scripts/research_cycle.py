"""The state of the learning cycle: hypotheses by state with what each is waiting for, and the verdict of each experiment of the plan (RP-8.1). Reading only.

    python -m scripts.research_cycle            # counts by state + next step + verdicts of EXP-E1 ... EXP-E8
    python -m scripts.research_cycle --json

It writes nothing. A hypothesis whose state is not in the graph of ``fbi.research.cycle_state`` is listed apart (it would be a hole to close). ``--dsn`` overrides the
database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from fbi.research import cycle_state, verdicts

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=60000"


def counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM analytics.research_hypotheses GROUP BY status")
        return {str(s): int(n) for s, n in cur.fetchall()}


def report(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    by_state = counts(conn)
    states = [{"state": s, "n": by_state.get(s, 0), "who_moves_it": sorted(set(cycle_state.allowed(s).values())),
               "next_step": cycle_state.next_step(s)} for s in cycle_state.STATES]
    return {"version": cycle_state.VERSION, "states": states, "outside_the_graph": {s: n for s, n in by_state.items() if not cycle_state.known(s)},
            "verdicts": [{"experiment": v.experiment, "verdict": v.verdict, "n": v.n, "mean": v.mean, "low": v.low, "high": v.high,
                          "computed_at": v.computed_at.isoformat(), "protocol": v.protocol_version} for v in verdicts.latest(conn)],
            "experiments_without_a_decided_verdict": verdicts.pending(conn)}


def lines(doc: dict[str, Any]) -> list[str]:
    out = [f"Ciclo de aprendizaje ({doc['version']})"]
    for s in doc["states"]:
        who = "/".join(s["who_moves_it"]) or "final"
        out.append(f"  {s['state']:<14} {s['n']:>5}  mueve: {who:<14} {s['next_step']}")
    if doc["outside_the_graph"]:
        out.append(f"  FUERA DEL GRAFO: {doc['outside_the_graph']}")
    out.append("Veredictos de los experimentos del plan")
    if not doc["verdicts"]:
        out.append("  ninguno guardado todavía")
    for v in doc["verdicts"]:
        figs = "sin cifra" if v["mean"] is None else f"media {v['mean']:+.4f} [{v['low']:+.4f}; {v['high']:+.4f}]"
        out.append(f"  {v['experiment']}: {v['verdict']} (n={v['n']}, {figs}) protocolo {v['protocol']}")
    out.append(f"  sin veredicto decidido: {', '.join(doc['experiments_without_a_decided_verdict']) or 'ninguno'}")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research_cycle", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = report(conn)
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join(lines(doc))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The optimism of the joint of a parlay on the history of the shadow's decisions (plan RP-11.1, ``parlay-replay-v1``): read-only.

    python -m scripts.ia_parlay_replay [--days 60] [--json] [--save DIR]

Reads the selections the shadow confirmed (``intel.selection_lifecycle`` of decision-v2's kept chains) and their newest settlement, forms every combination of
two or three legs of different matches and teams of the same day, and says how often it came in against the joint said before the match, per band and overall,
with an interval that resamples whole days (``fbi.parlays.replay``). It writes nothing to the database (``--save`` writes the JSON report to a directory, nothing
else) and publishes nothing. Exit status: 0 done.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import local_day
from fbi.core.clock import now
from fbi.parlays import replay

READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=120000"
WRITER = "decision-v2-shadow-v1"
"""The writer of the chains whose confirmations are the shadow's legs (the same one ``fbi.tracking.parlay_v6_shadow`` reads; the tracking is imported only by its own doors, so
the reading is restated here and held equal by the test that reads both)."""
CONFIRMED_SQL = """
WITH tip AS (
    SELECT DISTINCT ON (s.chain_key) s.id, s.chain_key, s.fixture_id, s.state, s.source, s.source_id
      FROM intel.selection_lifecycle s JOIN core.fixtures f ON f.id = s.fixture_id
     WHERE s.writer = %(writer)s AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND s.known_at <= %(at)s
     ORDER BY s.chain_key, s.id DESC
)
SELECT t.chain_key, t.fixture_id, f.kickoff_at, f.home_team_id, f.away_team_id,
       COALESCE(d2.p_market, d1.p_market)::float8 AS p_market,
       COALESCE(d2.p_cal, d1.p_cal, d2.p_model, d1.p_model)::float8 AS p
  FROM tip t
  JOIN core.fixtures f ON f.id = t.fixture_id
  LEFT JOIN intel.decisions_v2 d2 ON t.source = 'intel.decisions_v2' AND d2.id = t.source_id
  LEFT JOIN intel.decisions d1 ON t.source = 'intel.decisions' AND d1.id = t.source_id
 WHERE t.state = 'confirmada_sombra'
 ORDER BY f.kickoff_at, t.chain_key
"""
"""The chains whose newest row is a confirmation, with the probability the shadow gave the leg (the calibrated one when there is one) and the market's."""
SETTLED_SQL = """
SELECT DISTINCT ON (s.chain_key) s.chain_key, s.result
  FROM intel.selection_settlements s
 WHERE s.kind IN ('primera', 'correccion') AND s.chain_key = ANY(%(chains)s)
 ORDER BY s.chain_key, s.known_at DESC, s.id DESC
"""
"""The newest settlement of each chain (``parlay_states.V6_LEGS_SQL``'s reading)."""


def read_legs(conn: psycopg.Connection[Any], *, at: datetime, days: int) -> list[replay.Leg]:
    """The legs of the last ``days`` days: every chain the shadow confirmed (as of the moment each match kicked off), with its newest settlement."""
    with conn.cursor(row_factory=dict_row) as cur:
        confirmed = cur.execute(CONFIRMED_SQL, {"writer": WRITER, "start": at - timedelta(days=days), "end": at, "at": at}).fetchall()
        chains = [r["chain_key"] for r in confirmed]
        settled = {r["chain_key"]: r["result"] for r in cur.execute(SETTLED_SQL, {"chains": chains}).fetchall()} if chains else {}
    rows = [{"chain_key": r["chain_key"], "fixture_id": r["fixture_id"], "day": local_day(r["kickoff_at"]),
             "teams": [t for t in (r["home_team_id"], r["away_team_id"]) if t is not None], "p": r["p"], "p_market": r["p_market"],
             "result": settled.get(r["chain_key"])} for r in confirmed]
    return replay.legs_of(rows)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_parlay_replay", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dsn", help="the database (default: the platform's)")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", help="a directory to keep the JSON report in")
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    days = max(1, min(args.days, 180))
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=READ_ONLY) as conn:
        out = replay.report(read_legs(conn, at=now(), days=days))
    out["days_back"] = days
    if args.save:
        Path(args.save).mkdir(parents=True, exist_ok=True)
        (Path(args.save) / f"parlay_replay_{now():%Y%m%dT%H%M}.json").write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    if args.json:
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render(out))
    return 0


def pct(x: float | None) -> str:
    return "sin dato" if x is None else f"{100 * x:.2f} %".replace(".", ",")


def render(r: dict[str, Any]) -> str:
    left = ", ".join(f"{k} {v}" for k, v in r["left_out"].items() if v) or "ninguna"
    lines = [f"Repetición histórica de la conjunta ({r['version']}) · {r['days_back']} días · {r['legs']} selecciones, {r['legs_replayed']} repetidas (fuera: {left})",
             f"  {r['combinations']} combinaciones ({', '.join(f'{k} patas: {v}' for k, v in r['by_size'].items()) or 'ninguna'}) en {r['days']} días con {r['distinct_legs']} "
             f"selecciones distintas; la meta es {r['needed']} o más: {'se alcanza' if r['enough'] else 'NO se alcanza'}"]
    for key, name in (("model", "con la cifra del modelo"), ("market", "con la referencia del mercado")):
        m = r[key]
        interval = m["interval"]
        span = "sin intervalo (menos de dos días)" if interval is None else f"intervalo 95 % de {pct(interval[0])} a {pct(interval[1])}"
        lines.append(f"  {name}: {m['n']} combinaciones; dicho {pct(m['said'])}, ocurrido {pct(m['came_in'])}, optimismo {pct(m['optimism'])}; {span}")
    for b in r["bands"]:
        lines.append(f"    banda {pct(b['from'])} a {pct(b['to'])}: {b['n']} combinaciones; dicho {pct(b['said'])}, ocurrido {pct(b['came_in'])}")
    lines.append("  " + r["note"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

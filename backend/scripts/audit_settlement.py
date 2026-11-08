"""What was settled, settled again on paper (plan PICKS, F6): stored results against the same rules on today's scores.

    python -m scripts.audit_settlement               # read-only; matches that kicked off in the last 30 days
    python -m scripts.audit_settlement --days 7
    python -m scripts.audit_settlement --json

For every settled record that rests on a score - shadow picks, the items of the picks of the day, PrediGol's parlay
legs, a reader's picks and parlay legs - it reads the record and its match exactly as the resettlement does
(``fbi.picks.resettlement.SINGLES``), settles it again with the same rules (``fbi.picks.settlement``) and compares
(``resettlement.judge``). Each record ends in one of:

* ``same``: what is stored is what the rules give now;
* ``held``: a difference the rules leave to a person (a void by rule, a match that no longer settles);
* ``change`` explained by a correction of the result the trail already holds (``core.fixture_result_revisions``),
  recorded AFTER the record was settled, that the resettlement has not applied yet;
* ``change`` UNEXPLAINED: the plan's criterion is zero of these.

Then the days of the picks of the day: won + lost + void + open must be the set's size (D3, in the data), and how
long the performance console's two queries take (R1). It reads through a connection the server keeps READ ONLY and
writes nothing; a correction goes through ``python -m scripts.resettle`` with its trail and the owner's word.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.picks import resettlement, settlement
from fbi.picks.product_settlement import settle_single

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=300000 -c TimeZone=UTC"
EXAMPLES = 20

FIXTURES_SQL = "SELECT id FROM core.fixtures WHERE kickoff_at >= %(since)s AND kickoff_at < %(until)s ORDER BY id"
SETS_SQL = """
SELECT s.day, s.source, s.rule_version, count(i.*)::int AS items,
       count(*) FILTER (WHERE i.status IN ('WIN', 'HALF_WIN'))::int AS won,
       count(*) FILTER (WHERE i.status IN ('LOSS', 'HALF_LOSS'))::int AS lost,
       count(*) FILTER (WHERE i.status IN ('VOID', 'PUSH'))::int AS voids,
       count(*) FILTER (WHERE i.status = 'PENDING')::int AS open,
       count(*) FILTER (WHERE i.status IN ('HALF_WIN', 'HALF_LOSS'))::int AS halves,
       count(*) FILTER (WHERE i.status NOT IN ('WIN', 'HALF_WIN', 'LOSS', 'HALF_LOSS', 'VOID', 'PUSH', 'PENDING'))::int
         AS other,
       sum(i.profit_units) AS units
  FROM picks.daily_sets s JOIN picks.daily_set_items i ON i.set_id = s.id
 WHERE s.day >= %(since)s::date
 GROUP BY s.id, s.day, s.source, s.rule_version ORDER BY s.day, s.source
"""


def reprice(kind: resettlement.Kind, row: Mapping[str, Any], at: datetime) -> settlement.Settlement:
    """How the rules settle this record on the current result: the resettlement's own reading (``_pass``)."""
    price = Decimal(row["price"]) if row["price"] is not None else None
    if kind.pick:
        return settlement.settle(
            row["market_key"], row["selection"], Decimal(row["line"]), price or Decimal("2"), Decimal(row["stake"]),
            settlement.MatchState(row["status_short"], row["reg_goals_home"], row["reg_goals_away"],
                                  row["et_goals_home"], row["et_goals_away"], row["ft_goals_home"],
                                  row["ft_goals_away"], row["taken_kickoff"]), at=at)
    return settle_single(dict(row), price, at=at)


def verdict(kind: resettlement.Kind, row: Mapping[str, Any], at: datetime) -> resettlement.Verdict:
    price = row["price"]
    outcome = reprice(kind, row, at)
    score_based = row["basis"] == settlement.BASIS if kind.pick else row["status"] != "VOID"
    return resettlement.judge(stored_status=row["status"], stored_profit=row["profit"], score_based=score_based,
                              outcome=outcome, priced=kind.profit_col is not None and price is not None,
                              upper=kind.upper, status_short=row["status_short"])


def corrected_after(revision: resettlement.Revision | None, settled_at: datetime | None) -> bool:
    """A difference is explained by a correction only if the result was corrected AFTER the record was settled: one
    corrected before it should already be in what was stored."""
    return revision is not None and (settled_at is None or revision.observed_at > settled_at)


def tally(kind: resettlement.Kind, rows: Iterable[Mapping[str, Any]], at: datetime,
          revisions: Mapping[int, resettlement.Revision]) -> dict[str, Any]:
    """One kind of record: how many agree, are held (by code), changed with a recorded correction, or unexplained."""
    out: dict[str, Any] = {"examined": 0, "same": 0, "held": Counter(), "explained": 0, "unexplained": 0,
                           "examples": []}
    for row in rows:
        out["examined"] += 1
        v = verdict(kind, row, at)
        if v.action == "same":
            out["same"] += 1
        elif v.action == "held":
            out["held"][v.code] += 1
        elif corrected_after(revisions.get(int(row["fixture_id"])), row["settled_at"]):
            out["explained"] += 1
        else:
            out["unexplained"] += 1
            if len(out["examples"]) < EXAMPLES:
                out["examples"].append({"kind": kind.name, "key": [row["k1"], row["k2"]],
                                        "fixture_id": int(row["fixture_id"]), "market": row["market_key"],
                                        "selection": row["selection"], "line": str(row["line"]),
                                        "stored": [row["status"], str(row["profit"])],
                                        "now": [str(v.status), str(v.profit)]})
    out["held"] = dict(out["held"])
    return out


def day_sums(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """D3 in the data: every item of a set counts once - won + lost + void or push + open is its size."""
    out = []
    for r in rows:
        total = r["won"] + r["lost"] + r["voids"] + r["open"]
        out.append({"day": str(r["day"]), "source": r["source"], "rule": r["rule_version"], "items": r["items"],
                    "won": r["won"], "lost": r["lost"], "voids": r["voids"], "open": r["open"],
                    "halves": r["halves"], "units": None if r["units"] is None else str(r["units"]),
                    "adds_up": total == r["items"] and r["other"] == 0})
    return out


def performance_timing(conn: psycopg.Connection[Any]) -> dict[str, float]:
    from fbi.api.repositories import analytics

    out = {}
    for name, read in (("summary", analytics.settled_summary), ("slices", analytics.performance_slices)):
        t = time.monotonic()
        read(conn)
        out[name] = round(time.monotonic() - t, 2)
    return out


def collect(conn: psycopg.Connection[Any], *, days: int, at: datetime, timing: bool) -> dict[str, Any]:
    since = at - timedelta(days=days)
    fixtures = [int(r["id"]) for r in conn.execute(FIXTURES_SQL, {"since": since, "until": at})]
    revisions = resettlement.latest_revisions(conn, fixtures) if fixtures else {}
    kinds: dict[str, Any] = {}
    for kind in resettlement.SINGLES:
        rows = conn.execute(kind.select, {"fixtures": fixtures}).fetchall() if fixtures else []
        kinds[kind.name] = tally(kind, rows, at, revisions)
    sets = day_sums(conn.execute(SETS_SQL, {"since": since}).fetchall())
    out: dict[str, Any] = {"at": at.isoformat(), "days": days, "fixtures": len(fixtures),
                           "fixtures_with_corrections": len(revisions), "kinds": kinds, "daily_sets": sets}
    if timing:
        out["performance_seconds"] = performance_timing(conn)
    return out


def report(f: Mapping[str, Any]) -> None:
    print(f"Liquidación recalculada · {f['at']} · partidos de los últimos {f['days']} días: {f['fixtures']:,} "
          f"({f['fixtures_with_corrections']:,} con correcciones del resultado)\n")
    examples: list[Any] = []
    for name, k in f["kinds"].items():
        print(f"  {name:16} {k['examined']:7,} examinados · {k['same']:7,} iguales · retenidos {k['held'] or 0} · "
              f"cambio con corrección registrada {k['explained']:,} · SIN EXPLICAR {k['unexplained']:,}")
        examples += k["examples"]
    for e in examples:
        print(f"    {e}")
    bad = [s for s in f["daily_sets"] if not s["adds_up"]]
    by_source: dict[str, int] = defaultdict(int)
    for s in f["daily_sets"]:
        by_source[s["source"]] += 1
    print(f"\nPicks del día: {len(f['daily_sets'])} sets {dict(by_source)}; "
          f"{len(bad)} cuyos ganados + perdidos + nulos + por jugar no suman su tamaño")
    for s in bad:
        print(f"    {s}")
    if "performance_seconds" in f:
        p = f["performance_seconds"]
        print(f"\nConsola de rendimiento (R1): totales {p['summary']} s · porciones {p['slices']} s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="matches that kicked off in the last N days (30)")
    parser.add_argument("--no-timing", action="store_true", help="skip timing the performance console's queries")
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    from fbi.core.clock import now as clock_now

    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY, row_factory=dict_row) as conn:
        figures = collect(conn, days=args.days, at=clock_now(), timing=not args.no_timing)
    if args.json:
        print(json.dumps(figures, ensure_ascii=False, indent=2, default=str))
    else:
        report(figures)
    unexplained = sum(k["unexplained"] for k in figures["kinds"].values())
    return 1 if unexplained or any(not s["adds_up"] for s in figures["daily_sets"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

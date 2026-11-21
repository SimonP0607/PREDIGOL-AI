"""PM-05-07: the market's margin and dispersion by competition, market and day (``fbi.market.league_daily``) - the owner's commands.

    python -m scripts.market_league_stats show [--days 14] [--league 239]   # what is stored, by competition and market (read only)
    python -m scripts.market_league_stats check --day 2026-11-15 [--fixtures 20]
        # read only: one day measured in memory (nothing written) against an independent SQL computation of the same margins, and
        # the margin of each book of the first N matches, to recompute by hand (the card's test)
    python -m scripts.market_league_stats run [--day 2026-11-15 ...]       # writes; only with FBI_MARKET_LEAGUE_STATS on

Inside the worker's container (``docker exec predigol-worker python -m scripts.market_league_stats ...``), away from the copies
(03:50-05:00 UTC), the statistics pass (07:20 UTC) and the ``fixtures_sync``. No provider request; ``show`` and ``check`` write nothing.
Exit 0 when everything agrees (``check``), 1 when a difference is found, 2 when ``run`` finds the switch off.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

INDEPENDENT_SQL = """
WITH q AS (
  SELECT o.fixture_id, cs.competition_id, o.bookmaker_id, o.market_key, o.line, o.selection, o.odds_decimal
    FROM core.fixtures f
    JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    JOIN market.final_prematch_odds o ON o.fixture_id = f.id
   WHERE f.kickoff_at >= (%(day)s::date)::timestamp AT TIME ZONE 'UTC' AND f.kickoff_at < (%(day)s::date + 1)::timestamp AT TIME ZONE 'UTC'
     AND f.status_group = 'finished'
     AND ((o.market_key = '1X2' AND o.line = 0 AND o.selection IN ('Home', 'Draw', 'Away'))
       OR (o.market_key = 'BTTS' AND o.line = 0 AND o.selection IN ('Yes', 'No'))
       OR (o.market_key = 'OU' AND o.line = 2.5 AND o.selection IN ('Over', 'Under')))
), b AS (
  SELECT fixture_id, competition_id, bookmaker_id, market_key, line, count(*) AS n, sum(1 / odds_decimal) - 1 AS margin
    FROM q GROUP BY 1, 2, 3, 4, 5
), ok AS (
  SELECT * FROM b
   WHERE n = CASE market_key WHEN '1X2' THEN 3 ELSE 2 END
     AND margin > 0 AND margin <= CASE market_key WHEN '1X2' THEN 0.40 ELSE 0.25 END
)
SELECT competition_id, market_key, line, count(DISTINCT fixture_id) AS fixtures, count(*) AS books,
       avg(margin) AS margin_mean, percentile_cont(0.5) WITHIN GROUP (ORDER BY margin) AS margin_median,
       percentile_cont(0.1) WITHIN GROUP (ORDER BY margin) AS margin_p10, percentile_cont(0.9) WITHIN GROUP (ORDER BY margin) AS margin_p90
  FROM ok GROUP BY 1, 2, 3 ORDER BY 1, 2
"""
"""The same margins computed by PostgreSQL alone, without the module's code: the check compares both."""

BOOKS_SQL = """
SELECT o.fixture_id, o.market_key, o.line, o.bookmaker_id, string_agg(o.selection || '=' || o.odds_decimal, ' ' ORDER BY o.selection)
       AS prices, round(sum(1 / o.odds_decimal) - 1, 5) AS margin
  FROM market.final_prematch_odds o
 WHERE o.fixture_id = ANY(%(ids)s)
   AND ((o.market_key IN ('1X2', 'BTTS') AND o.line = 0) OR (o.market_key = 'OU' AND o.line = 2.5))
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 4
"""


def _f(x: Any) -> float:
    return float(x)


def check(conn: Any, day: date, fixtures: int) -> int:
    from fbi.market import league_daily

    rows = conn.execute(league_daily.PRICES_SQL, {"day": day}).fetchall()
    prices = [league_daily.Price(fixture_id=r[0], competition_id=r[1], day=day, bookmaker_id=r[2], market_key=r[3], line=Decimal(r[4]),
                                 selection=r[5], odds=Decimal(r[6])) for r in rows]
    mine = {(s.competition_id, s.market_key, Decimal(s.line)): s for s in league_daily.summarise(prices).stats}
    theirs = {(r[0], r[1], Decimal(r[2])): r for r in conn.execute(INDEPENDENT_SQL, {"day": day}).fetchall()}
    differences = 0
    for key in sorted(set(mine) | set(theirs), key=lambda k: (k[0], k[1])):
        a, b = mine.get(key), theirs.get(key)
        if a is None or b is None:
            differences += 1
            print({"diferencia": "solo_en_uno", "key": [key[0], key[1], str(key[2])], "modulo": a is not None, "sql": b is not None})
            continue
        pairs = {"fixtures": (a.n_fixtures, b[3]), "books": (a.n_books, b[4]), "margin_mean": (a.margin_mean, _f(b[5])),
                 "margin_median": (a.margin_median, _f(b[6])), "margin_p10": (a.margin_p10, _f(b[7])), "margin_p90": (a.margin_p90, _f(b[8]))}
        bad = {k: v for k, v in pairs.items() if abs(float(v[0]) - float(v[1])) > 1e-9}
        if bad:
            differences += 1
            print({"diferencia": "valores", "key": [key[0], key[1], str(key[2])], **{k: [float(x) for x in v] for k, v in bad.items()}})
    ids = sorted({p.fixture_id for p in prices})[:fixtures]
    if ids:
        for r in conn.execute(BOOKS_SQL, {"ids": ids}).fetchall():
            print(f"libro fixture={r[0]} {r[1]}@{r[2]} casa={r[3]} {r[4]} margen={r[5]}")
    conn.rollback()
    print({"day": day.isoformat(), "precios": len(prices), "filas": len(mine), "filas_sql": len(theirs), "diferencias": differences,
           "partidos_listados": len(ids)})
    return 1 if differences else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--league", type=int, help="the provider's league id")
    c = sub.add_parser("check")
    c.add_argument("--day", type=date.fromisoformat, required=True)
    c.add_argument("--fixtures", type=int, default=20)
    r = sub.add_parser("run")
    r.add_argument("--day", type=date.fromisoformat, action="append")
    args = parser.parse_args(argv)

    import psycopg

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.market import league_daily

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="market_league_stats") as conn:
        if args.cmd == "show":
            conn.execute("SET default_transaction_read_only = on")
            until = now().date()
            for row in league_daily.read(conn, since=until - timedelta(days=args.days), until=until, competition=args.league):
                print({k: (str(v) if isinstance(v, Decimal | date) else v) for k, v in row.items() if k != "measured_at"})
            return 0
        if args.cmd == "check":
            conn.execute("SET default_transaction_read_only = on")
            return check(conn, args.day, args.fixtures)
        if league_daily.mode() != "on":
            print(f"{league_daily.SWITCH} is off: nothing is measured")
            return 2
        report = league_daily.run_pass(conn, now=now(), days=args.day)
        print(report.as_json() | {"errors": report.errors})
        return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

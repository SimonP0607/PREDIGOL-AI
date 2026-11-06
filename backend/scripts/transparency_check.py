"""Every figure of «Cómo le va a PrediGol» against an independent query (plan UX, A12: «cada cifra cuadra con una consulta
independiente en cada despliegue»). Read-only; exit 0 when they all match, 1 on the first mismatch list, 2 if the database is
not reachable.

    python -m scripts.transparency_check [--tz America/Bogota]

The page's numbers come from ``fbi.api.services.transparency.build`` (no cache); the contrast's from the SQL below, written apart
from the service's - other formulations (aggregates and FILTER where the service tallies in Python, containment where it casts,
window functions where it uses DISTINCT ON), the periods cut in SQL instead of ``period_bounds`` - so a mistake in one shows as a
difference. What is not re-derived on purpose: the line value's formula (``fbi.market.closing_value.clv``, one definition for the
whole system, applied to a closing probability fetched apart) and the plan's rules (25 settled for a ROI, «other» under 25).
It prints figures only: no client data is read.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.api.services import transparency as service
from fbi.api.services import transparency_picks
from fbi.api.services.forecast import VERSION as FORECAST_VERSION
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.decision_versions import DECISION_CORE
from fbi.market import closing_value

PERIOD_SQL = """
WITH b AS (SELECT CASE %(period)s WHEN '7d' THEN ((now_local::date - 6)::timestamp AT TIME ZONE %(tz)s)
                                  WHEN '30d' THEN ((now_local::date - 29)::timestamp AT TIME ZONE %(tz)s)
                                  ELSE '-infinity'::timestamptz END AS since,
                  ((now_local::date + 1)::timestamp AT TIME ZONE %(tz)s) AS until
             FROM (SELECT (%(at)s::timestamptz AT TIME ZONE %(tz)s) AS now_local) n)
SELECT count(*)::int AS published,
       count(*) FILTER (WHERE i.status = 'PENDING')::int AS pending,
       count(*) FILTER (WHERE i.status = 'WIN')::int AS won,
       count(*) FILTER (WHERE i.status = 'LOSS')::int AS lost,
       count(*) FILTER (WHERE i.status = 'HALF_WIN')::int AS half_won,
       count(*) FILTER (WHERE i.status = 'HALF_LOSS')::int AS half_lost,
       count(*) FILTER (WHERE i.status = 'PUSH')::int AS push,
       count(*) FILTER (WHERE i.status = 'VOID')::int AS void,
       count(*) FILTER (WHERE i.status NOT IN ('PENDING', 'VOID') AND i.profit_units IS NOT NULL)::int AS settled,
       COALESCE(sum(i.profit_units) FILTER (WHERE i.status <> 'PENDING'), 0) AS units
  FROM b, picks.daily_sets s
  JOIN picks.daily_set_items i ON i.set_id = s.id
  JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE s.source = 'qualified' AND f.kickoff_at >= b.since AND f.kickoff_at < b.until
"""

PARLAY_SQL = """
WITH p AS (
    SELECT p.id, p.kind, p.status, p.profit_units, min(f.kickoff_at) AS first_kickoff
      FROM picks.parlays p
      JOIN picks.parlay_legs l ON l.parlay_id = p.id
      JOIN core.fixtures f ON f.id = l.fixture_id
     WHERE p.source = 'qualified' AND p.status <> 'BUILDING'
     GROUP BY p.id
)
SELECT kind,
       count(*)::int AS published,
       count(*) FILTER (WHERE status IN ('READY', 'ACTIVE'))::int AS pending,
       count(*) FILTER (WHERE status IN ('WON', 'PARTIAL_VOID'))::int AS won,
       count(*) FILTER (WHERE status = 'LOST')::int AS lost,
       count(*) FILTER (WHERE status = 'VOID')::int AS void,
       count(*) FILTER (WHERE status = 'PARTIAL_VOID')::int AS partial,
       count(*) FILTER (WHERE status IN ('WON', 'PARTIAL_VOID', 'LOST') AND profit_units IS NOT NULL)::int AS settled,
       COALESCE(sum(profit_units) FILTER (WHERE status NOT IN ('READY', 'ACTIVE')), 0) AS units
  FROM p
 WHERE first_kickoff < ((%(at)s::timestamptz AT TIME ZONE %(tz)s)::date + 1)::timestamp AT TIME ZONE %(tz)s
 GROUP BY kind
"""

MARKET_SQL = """
SELECT i.market_key,
       count(*)::int AS published,
       count(*) FILTER (WHERE i.status NOT IN ('PENDING', 'VOID') AND i.profit_units IS NOT NULL)::int AS settled,
       COALESCE(sum(i.profit_units) FILTER (WHERE i.status <> 'PENDING'), 0) AS units
  FROM picks.daily_sets s
  JOIN picks.daily_set_items i ON i.set_id = s.id
  JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE s.source = 'qualified' AND f.kickoff_at < ((%(at)s::timestamptz AT TIME ZONE %(tz)s)::date + 1)::timestamp AT TIME ZONE %(tz)s
 GROUP BY 1
"""

DAY_FACTS_SQL = """
WITH days AS (SELECT generate_series(%(first)s::date, %(last)s::date, interval '1 day')::date AS day),
picked AS (SELECT DISTINCT s.day FROM picks.daily_sets s
            WHERE s.source = 'qualified' AND EXISTS (SELECT 1 FROM picks.daily_set_items i WHERE i.set_id = s.id)),
games AS (SELECT (f.kickoff_at AT TIME ZONE 'America/Bogota')::date AS day, count(*)::int AS n
            FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id AND c.is_tracked
           WHERE f.kickoff_at >= %(first)s::date - 1 AND f.kickoff_at < %(last)s::date + 2
           GROUP BY 1),
qual AS (SELECT (f.kickoff_at AT TIME ZONE 'America/Bogota')::date AS day, count(*)::int AS n
           FROM picks.picks p JOIN core.fixtures f ON f.id = p.fixture_id
          WHERE p.qualification @> '{"qualified": true}'::jsonb AND p.created_at < f.kickoff_at
            AND f.kickoff_at >= %(first)s::date - 1 AND f.kickoff_at < %(last)s::date + 2
          GROUP BY 1)
SELECT days.day, picked.day IS NOT NULL AS has_picks, COALESCE(games.n, 0) AS matches, COALESCE(qual.n, 0) AS qualified
  FROM days LEFT JOIN picked ON picked.day = days.day LEFT JOIN games ON games.day = days.day
  LEFT JOIN qual ON qual.day = days.day
 ORDER BY 1
"""

DAY_STOPS_SQL = """
WITH ranked AS (
    SELECT d.kickoff_at, d.filters, d.pick_id,
           row_number() OVER (PARTITION BY d.fixture_id, d.market_key, d.selection, d.line
                              ORDER BY d.known_at DESC, d.id DESC) AS rn
      FROM intel.decisions d
     WHERE d.decision_version = %(decision_version)s AND d.known_at < d.kickoff_at
       AND d.kickoff_at >= (%(first)s::date::timestamp AT TIME ZONE 'America/Bogota')
       AND d.kickoff_at < ((%(last)s::date + 1)::timestamp AT TIME ZONE 'America/Bogota')
), latest AS (
    SELECT (kickoff_at AT TIME ZONE 'America/Bogota')::date AS day, filters, pick_id,
           (SELECT min((x ->> 'n')::int) FROM jsonb_array_elements(filters) x WHERE (x ->> 'ok')::boolean IS FALSE) AS first_n
      FROM ranked WHERE rn = 1
)
SELECT l.day,
       (SELECT x ->> 'key' FROM jsonb_array_elements(l.filters) x WHERE (x ->> 'n')::int = l.first_n LIMIT 1) AS stop,
       (p.qualification @> '{"qualified": true}'::jsonb) IS TRUE AS qualified,
       count(*)::int AS n
  FROM latest l LEFT JOIN picks.picks p ON p.id = l.pick_id
 GROUP BY 1, 2, 3
"""

CLOSE_SQL = """
WITH items AS (
    SELECT i.set_id, i.rank, i.fixture_id, i.market_key, i.selection, i.line, i.odds, f.kickoff_at
      FROM picks.daily_sets s JOIN picks.daily_set_items i ON i.set_id = s.id JOIN core.fixtures f ON f.id = i.fixture_id
     WHERE s.source = 'qualified' AND f.kickoff_at <= %(at)s
), closes AS (
    SELECT it.set_id, it.rank, m.p_fair, m.as_of,
           row_number() OVER (PARTITION BY it.set_id, it.rank ORDER BY m.as_of DESC) AS rn
      FROM items it JOIN market.market_consensus m
        ON m.fixture_id = it.fixture_id AND m.market_key = it.market_key AND m.selection = it.selection
       AND m.line = it.line AND m.devig_method = 'shin' AND m.as_of < it.kickoff_at
)
SELECT it.odds, c.p_fair, extract(epoch FROM it.kickoff_at - c.as_of) / 60 AS minutes
  FROM items it JOIN closes c ON c.set_id = it.set_id AND c.rank = it.rank AND c.rn = 1
"""

FORECAST_SQL = """
WITH f AS (
    SELECT x.*, fx.kickoff_at, r.reg_goals_home AS h, r.reg_goals_away AS a,
           rank() OVER (PARTITION BY x.fixture_id, x.market_key, x.line ORDER BY x.known_at DESC) AS rk
      FROM models.match_forecasts x
      JOIN core.fixtures fx ON fx.id = x.fixture_id AND fx.status_group = 'finished'
      JOIN core.fixture_results r ON r.fixture_id = x.fixture_id
     WHERE x.version = %(version)s AND x.market_key = %(market)s AND x.line = %(line)s AND x.known_at < fx.kickoff_at
       AND x.known_at >= %(since)s::timestamptz - interval '7 days'
       AND fx.kickoff_at >= %(since)s AND fx.kickoff_at < %(at)s
       AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
)
SELECT count(DISTINCT fixture_id)::int AS matches,
       count(DISTINCT fixture_id) FILTER (WHERE calibration = 'CALIBRATED')::int AS calibrated,
       width_bucket(LEAST(p, 0.9999), 0, 1, 10) AS bucket,
       count(*) FILTER (WHERE calibration = 'CALIBRATED' AND (%(side)s::text IS NULL OR selection = %(side)s))::int AS n,
       count(*) FILTER (WHERE calibration = 'CALIBRATED' AND (%(side)s::text IS NULL OR selection = %(side)s) AND
                        CASE market_key
                          WHEN '1X2' THEN selection = CASE WHEN h > a THEN 'Home' WHEN h < a THEN 'Away' ELSE 'Draw' END
                          WHEN 'OU' THEN (selection = 'Over') = (h + a >= 3)
                          ELSE (selection = 'Yes') = (h >= 1 AND a >= 1) END)::int AS hits
  FROM f WHERE rk = 1
 GROUP BY GROUPING SETS ((), (bucket))
"""

EDGE_SQL = """
SELECT count(*)::int AS pairs, count(*) FILTER (WHERE role = 'VALIDATED')::int AS passed_pairs,
       count(DISTINCT market_key)::int AS markets,
       count(DISTINCT market_key) FILTER (WHERE role = 'VALIDATED')::int AS passed_markets
  FROM (SELECT market_key, model_name, (array_agg(to_role ORDER BY at DESC, id DESC))[1] AS role
          FROM intel.promotions WHERE entity = 'market_edge' GROUP BY 1, 2) t
"""


@dataclass(frozen=True)
class Mismatch:
    figure: str
    page: object
    independent: object


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _q(value: Decimal | float | None, places: str) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal(places))


def _expect_tally(out: list[Mismatch], name: str, page: Any, row: dict[str, Any]) -> None:
    for key in ("published", "pending", "won", "lost", "half_won", "half_lost", "push", "void", "settled"):
        if key in row and getattr(page, key) != row[key]:
            out.append(Mismatch(f"{name}.{key}", getattr(page, key), row[key]))
    n = int(row["settled"])
    enough = n >= service.MIN_SAMPLE
    units = _q(row["units"], "0.01") if enough else None
    roi = _q(Decimal(row["units"]) / n, "0.0001") if enough else None
    margin = _q(1 / math.sqrt(n), "0.0001") if enough else None
    for key, expected in (("units", units), ("roi", roi), ("margin", margin), ("conclusive", n >= service.CONCLUSIVE)):
        if getattr(page, key) != expected:
            out.append(Mismatch(f"{name}.{key}", getattr(page, key), expected))


def _listed(conn: psycopg.Connection[Any], *, tz: str, at: datetime) -> tuple[list[Any], int | None]:
    """Every published pick through the list's own pages (the cursor followed to the end) and the total it announced."""
    items: list[Any] = []
    cursor: str | None = None
    total: int | None = None
    for _ in range(10_000):
        page = transparency_picks.published_picks(conn, tz=tz, limit=7, cursor=cursor, at=at)
        items.extend(page.data)
        total = page.meta.total if total is None else total
        cursor = page.meta.next_cursor
        if cursor is None:
            break
    return items, total


def check(conn: psycopg.Connection[Any], *, tz: str, at: datetime) -> list[Mismatch]:
    """The page at ``at`` for a reader in ``tz`` against the independent queries: the differences, none when they agree."""
    page = service.build(conn, tz=tz, at=at)
    out: list[Mismatch] = []
    for p in page.periods:
        (row,) = _rows(conn, PERIOD_SQL, {"period": p.period, "tz": tz, "at": at})
        _expect_tally(out, f"periods.{p.period}", p, row)

    whole = next(p for p in page.periods if p.period == "all")
    items, announced = _listed(conn, tz=tz, at=at)
    if announced != whole.published or len(items) != whole.published:
        out.append(Mismatch("picks.list.total", (announced, len(items)), whole.published))
    keys = [(i.kickoff_at, i.published_at, i.market, i.selection, i.line, i.home, i.away) for i in items]
    if len(set(keys)) != len(keys):
        out.append(Mismatch("picks.list.repeated", len(keys) - len(set(keys)), 0))
    if [i.kickoff_at for i in items] != sorted((i.kickoff_at for i in items), reverse=True):
        out.append(Mismatch("picks.list.order", "not newest first", "newest first"))
    by_result = {r: sum(1 for i in items if i.result == r) for r in
                 ("PENDING", "WIN", "LOSS", "HALF_WIN", "HALF_LOSS", "PUSH", "VOID")}
    expected_results = {"PENDING": whole.pending, "WIN": whole.won, "LOSS": whole.lost, "HALF_WIN": whole.half_won,
                "HALF_LOSS": whole.half_lost, "PUSH": whole.push, "VOID": whole.void}
    if by_result != expected_results:
        out.append(Mismatch("picks.list.results", by_result, expected_results))
    listed_units = sum((i.units for i in items if i.units is not None and i.result not in ("PENDING", "VOID")),
                       Decimal(0))
    (whole_row,) = _rows(conn, PERIOD_SQL, {"period": "all", "tz": tz, "at": at})
    if listed_units != Decimal(whole_row["units"]):
        out.append(Mismatch("picks.list.units", listed_units, Decimal(whole_row["units"])))

    parlay_rows = {str(r["kind"]): r for r in _rows(conn, PARLAY_SQL, {"tz": tz, "at": at})}
    if [pl.kind for pl in page.parlays] != ["daily", "multiday"]:
        out.append(Mismatch("parlays.kinds", [pl.kind for pl in page.parlays], ["daily", "multiday"]))
    for pl in page.parlays:
        row = parlay_rows.get(pl.kind) or {"published": 0, "pending": 0, "won": 0, "lost": 0, "void": 0, "partial": 0,
                                           "settled": 0, "units": 0}
        _expect_tally(out, f"parlays.{pl.kind}", pl, {**row, "half_won": 0, "half_lost": 0, "push": 0})
        if pl.partial != row["partial"]:
            out.append(Mismatch(f"parlays.{pl.kind}.partial", pl.partial, row["partial"]))

    markets = {str(r["market_key"]): r for r in _rows(conn, MARKET_SQL, {"tz": tz, "at": at})}
    big = {k: r for k, r in markets.items() if int(r["settled"]) >= service.MIN_SAMPLE}
    small = [r for k, r in markets.items() if k not in big]
    expected_markets = dict(big)
    if small:
        expected_markets[service.OTHER] = {"published": sum(int(r["published"]) for r in small),
                                           "settled": sum(int(r["settled"]) for r in small),
                                           "units": sum((Decimal(r["units"]) for r in small), Decimal(0))}
    if sorted(m.market for m in page.markets) != sorted(expected_markets):
        out.append(Mismatch("markets.kinds", sorted(m.market for m in page.markets), sorted(expected_markets)))
    for m in page.markets:
        if m.market in expected_markets:
            _expect_tally(out, f"markets.{m.market}", m, expected_markets[m.market])

    first, last = page.days.since, page.days.until
    facts = _rows(conn, DAY_FACTS_SQL, {"first": first, "last": last}) if first <= last else []
    stops: dict[Any, dict[tuple[str, bool], int]] = {}
    measured: dict[Any, int] = {}
    if first <= last:
        for r in _rows(conn, DAY_STOPS_SQL, {"first": first, "last": last, "decision_version": DECISION_CORE}):
            measured[r["day"]] = measured.get(r["day"], 0) + int(r["n"])
            if r["stop"] is not None:
                slot = (str(r["stop"]), bool(r["qualified"]))
                by_day = stops.setdefault(r["day"], {})
                by_day[slot] = by_day.get(slot, 0) + int(r["n"])
    order: dict[str, int] = {key: i for i, key in enumerate(service.STOPS)}
    expected_days = []
    for r in facts:
        if r["has_picks"]:
            continue
        reason = ("no_matches" if r["matches"] == 0 else
                  "no_qualified_candidates" if r["qualified"] == 0 else "not_chosen")
        counts: dict[str, int] = {}
        for (stop_key, qualified), n in stops.get(r["day"], {}).items():
            if reason != "not_chosen" or qualified:
                counts[stop_key] = counts.get(stop_key, 0) + n
        stop = max(counts, key=lambda k: (counts[k], -order.get(k, len(order))), default=None)
        expected_days.append((r["day"], reason, int(r["matches"]), measured.get(r["day"], 0), stop))
    got_days = [(d.day, d.reason, d.matches, d.measured, d.stop) for d in sorted(page.days.items, key=lambda d: d.day)]
    if got_days != expected_days:
        out.append(Mismatch("days.items", got_days, expected_days))
    if page.days.days != len(facts) or page.days.without != len(expected_days):
        out.append(Mismatch("days.count", (page.days.days, page.days.without), (len(facts), len(expected_days))))
    if page.evaluation.qualified != sum(int(r["qualified"]) for r in facts):
        out.append(Mismatch("evaluation.qualified", page.evaluation.qualified, sum(int(r["qualified"]) for r in facts)))

    closes = _rows(conn, CLOSE_SQL, {"at": at})
    values = [closing_value.clv(Decimal(r["odds"]), Decimal(r["p_fair"])) for r in closes]
    lv = page.line_value
    enough = len(values) >= service.MIN_SAMPLE
    mean = _q(sum(values, Decimal(0)) / len(values), "0.0001") if enough else None
    positive = _q(Decimal(sum(1 for v in values if v > 0)) / len(values), "0.0001") if enough else None
    minutes = sorted(float(r["minutes"]) for r in closes)
    median = None
    if minutes:
        mid = len(minutes) // 2
        median = round(minutes[mid] if len(minutes) % 2 else (minutes[mid - 1] + minutes[mid]) / 2)
    for key, expected in (("n", len(values)), ("mean", mean), ("positive", positive), ("minutes", median)):
        if getattr(lv, key) != expected:
            out.append(Mismatch(f"line_value.{key}", getattr(lv, key), expected))

    since = at - timedelta(days=service.CALIBRATION_DAYS)
    for fc in page.forecasts:
        rows = _rows(conn, FORECAST_SQL, {"version": FORECAST_VERSION, "market": fc.market, "line": fc.line,
                                          "side": fc.selection, "since": since, "at": at})
        total = next(r for r in rows if r["bucket"] is None)
        if (fc.matches, fc.calibrated) != (total["matches"], total["calibrated"]):
            out.append(Mismatch(f"forecasts.{fc.market}.matches", (fc.matches, fc.calibrated),
                                (total["matches"], total["calibrated"])))
        if fc.bins:
            got = [(b.low, b.n, b.observed) for b in fc.bins]
            expected_bins = [(Decimal(int(r["bucket"]) - 1) / 10, int(r["n"]),
                              _q(Decimal(int(r["hits"])) / int(r["n"]), "0.001"))
                             for r in sorted((r for r in rows if r["bucket"] is not None), key=lambda r: r["bucket"])
                             if int(r["n"]) >= service.MIN_BIN]
            if got != expected_bins:
                out.append(Mismatch(f"forecasts.{fc.market}.bins", got, expected_bins))

    (edge,) = _rows(conn, EDGE_SQL, {})
    ev = page.evaluation
    for key in ("pairs", "passed_pairs", "markets", "passed_markets"):
        if getattr(ev, key) != edge[key]:
            out.append(Mismatch(f"evaluation.{key}", getattr(ev, key), edge[key]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tz", default="America/Bogota", help="the reader's time zone the periods are cut in")
    args = parser.parse_args(argv)
    try:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=5,
                             options="-c default_transaction_read_only=on -c statement_timeout=60000") as conn:
            at = now()
            found = check(conn, tz=args.tz, at=at)
            page = service.build(conn, tz=args.tz, at=at)
    except psycopg.OperationalError as exc:
        print(f"transparency: database not reachable ({type(exc).__name__})")
        return 2
    for m in found:
        print(f"MISMATCH {m.figure}: page {m.page!r} vs independent {m.independent!r}")
    all_ = next(p for p in page.periods if p.period == "all")
    print(f"transparency: {'OK' if not found else f'{len(found)} mismatch(es)'} at {at.isoformat(timespec='seconds')} "
          f"({args.tz}): published {all_.published}, settled {all_.settled}, parlays "
          f"{[(p.kind, p.published) for p in page.parlays]}, days without picks "
          f"{page.days.without}/{page.days.days}, line value n={page.line_value.n}, "
          f"forecasts {[(f.market, f.state, f.matches) for f in page.forecasts]}, "
          f"evaluation {page.evaluation.passed_pairs}/{page.evaluation.pairs}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

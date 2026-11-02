"""PrediGol's forecast of a match, apart from its value and from any pick (plan F5). 0 provider requests.

    python -m scripts.match_forecast status                    # what has been written, how much of it is calibrated, the matches without one
    python -m scripts.match_forecast show 45140                # what PrediGol said about one match, set by set, when it said it
    python -m scripts.match_forecast show 45140 --at 2026-10-23T09:00:00+00:00     # ... and what it had said by then
    python -m scripts.match_forecast write                     # dry run: what a pass over the upcoming matches would write
    python -m scripts.match_forecast write --apply             # the same pass as the pick pipeline's step, by hand
    python -m scripts.match_forecast write --fixture 45140 --apply     # only these matches (repeatable)

The pick pipeline writes the forecasts itself (a step of its own, ``fbi.forecasting.match_forecast``); this is the same step by hand and a
way to look at what it wrote. A forecast is a probability and the interval around it: ``CALIBRATED`` only where a champion calibrator
exists, ``UNCALIBRATED`` (the model's own number, with the reason) everywhere else. It is not a value (that needs a price) and not a pick.
Nothing here creates a decision, a candidate or a pick, and nothing here shows users anything: whether they see the forecast is the
owner's switch (``FBI_FORECAST_USERS``).

``write`` is a DRY RUN unless ``--apply`` is given. ``status`` and ``show`` only read.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.forecasting import match_forecast as mf
from fbi.predictions.forecast import HORIZON

TOTALS_SQL = """
SELECT count(*) AS rows, count(DISTINCT fixture_id) AS fixtures, count(DISTINCT (fixture_id, known_at, market_key, line)) AS sets,
       min(known_at) AS first, max(known_at) AS last
  FROM models.match_forecasts WHERE version = %(version)s
"""

BY_MARKET_SQL = """
SELECT market_key, calibration, basis, model_name, count(DISTINCT (fixture_id, known_at, line)) AS sets
  FROM models.match_forecasts WHERE version = %(version)s AND known_at >= %(since)s
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4
"""

BY_DAY_SQL = """
SELECT (known_at AT TIME ZONE 'UTC')::date AS day, count(DISTINCT fixture_id) AS fixtures, count(DISTINCT (fixture_id, known_at, market_key, line)) AS sets
  FROM models.match_forecasts WHERE version = %(version)s AND known_at >= %(since)s GROUP BY 1 ORDER BY 1 DESC
"""

UPCOMING_SQL = """
SELECT f.id, f.kickoff_at, c.name AS competition,
       (SELECT s.class FROM analytics.competition_data_scores s WHERE s.competition_season_id = f.competition_season_id) AS data_class,
       EXISTS (SELECT 1 FROM models.match_forecasts m WHERE m.fixture_id = f.id AND m.version = %(version)s) AS has_forecast
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
       JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.kickoff_at > %(now)s AND f.kickoff_at <= %(until)s AND f.status_group = 'scheduled'
"""

SHOW_SQL = """
SELECT known_at, market_key, line, model_name, calibration, basis, selection, p, p_lo, p_hi, p_model, p_market_used, data_cutoff_ts
  FROM models.match_forecasts
 WHERE fixture_id = %(f)s AND version = %(version)s AND known_at <= %(at)s
 ORDER BY known_at, market_key, line, id
"""


def _n(value: int) -> str:
    return f"{value:,}"


def _when(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "-"


def _line(label: str, value: Any, width: int = 40) -> None:
    print(f"  {label:<{width}} {value}")


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value) * 100:5.1f}%"


# ── looking ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=max(args.days, 1))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TOTALS_SQL, {"version": mf.VERSION})
        t = cur.fetchone() or {}
        print(f"PrediGol's forecast ({mf.VERSION})")
        _line("rows", _n(int(t.get("rows") or 0)))
        _line("matches with a forecast", _n(int(t.get("fixtures") or 0)))
        _line("market sets (one per market and moment)", _n(int(t.get("sets") or 0)))
        _line("first / last said", f"{_when(t.get('first'))} / {_when(t.get('last'))}")
        cur.execute(BY_DAY_SQL, {"version": mf.VERSION, "since": since})
        print(f"\nPer day (UTC), last {args.days} days")
        for r in cur.fetchall():
            _line(str(r["day"]), f"{_n(int(r['fixtures']))} matches, {_n(int(r['sets']))} market sets")
        cur.execute(BY_MARKET_SQL, {"version": mf.VERSION, "since": since})
        print(f"\nBy market, calibration and why (last {args.days} days)")
        for r in cur.fetchall():
            _line(f"{r['market_key']:<5}{r['calibration']:<13}{r['basis']:<15}{r['model_name']}", _n(int(r["sets"])))
        cur.execute(UPCOMING_SQL, {"version": mf.VERSION, "now": now, "until": now + HORIZON})
        rows = cur.fetchall()
    with_forecast = [r for r in rows if r["has_forecast"]]
    without = [r for r in rows if not r["has_forecast"]]
    not_fit = [r for r in without if r["data_class"] in mf.NOT_FIT]
    print(f"\nUpcoming matches ({HORIZON}): {_n(len(rows))}")
    _line("with a forecast", _n(len(with_forecast)))
    _line("without one, in a competition not fit for a model", _n(len(not_fit)))
    _line("without one, any other reason", _n(len(without) - len(not_fit)))
    for r in [x for x in without if x["data_class"] not in mf.NOT_FIT][: args.list]:
        _line(f"  {r['id']} {_when(r['kickoff_at'])}", f"{r['competition']} ({r['data_class'] or 'no class'})")
    return 0


def show_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    at = datetime.fromisoformat(args.at) if args.at else datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SHOW_SQL, {"f": args.fixture, "version": mf.VERSION, "at": at})
        rows = cur.fetchall()
    if not rows:
        print(f"match {args.fixture}: PrediGol had said nothing by {at.isoformat()}")
        return 0
    print(f"match {args.fixture}: what PrediGol had said by {at.isoformat()}")
    seen: tuple[Any, ...] | None = None
    for r in rows:
        key = (r["known_at"], r["market_key"], r["line"])
        if key != seen:
            seen = key
            print(f"\n  {_when(r['known_at'])}  {r['market_key']} {r['line']}  {r['model_name']}  {r['calibration']} ({r['basis']})"
                  f"  data up to {_when(r['data_cutoff_ts'])}")
        extra = f"  model {_pct(r['p_model'])}" if r["calibration"] == "CALIBRATED" else ""
        interval = "no interval" if r["p_lo"] is None or r["p_hi"] is None else f"{_pct(r['p_lo'])} - {_pct(r['p_hi'])}"
        print(f"      {r['selection']:<6} {_pct(r['p'])}   {interval}{extra}")
    return 0


# ── writing ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def write_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    report = mf.write_match_forecasts(conn, at=datetime.now(UTC), code_version=code_version(),
                                      fixture_ids=args.fixture or None)
    print(("written: " if args.apply else "dry run, would write: ") + report.summary())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="match_forecast", description=__doc__.split("\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status", help="what has been written and what is missing")
    st.add_argument("--days", type=int, default=7, help="days to look back in the per-day and per-market counts")
    st.add_argument("--list", type=int, default=10, help="how many upcoming matches without a forecast to name")
    sh = sub.add_parser("show", help="what PrediGol said about one match")
    sh.add_argument("fixture", type=int)
    sh.add_argument("--at", help="ISO moment: what it had said by then (default: now)")
    wr = sub.add_parser("write", help="the pipeline's step by hand (a dry run unless --apply)")
    wr.add_argument("--fixture", type=int, action="append", help="only this match (repeatable)")
    wr.add_argument("--apply", action="store_true")
    return parser


READ_ONLY = {"status": status_command, "show": show_command}


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "write":
            code = write_command(conn, args)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            return code
        code = READ_ONLY[args.command](conn, args)
        conn.rollback()
        return code


if __name__ == "__main__":
    sys.exit(main())

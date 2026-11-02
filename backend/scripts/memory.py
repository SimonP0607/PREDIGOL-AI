"""The longitudinal memory (plan F8, ``memory-v4``): build its lineage day by day, look at what is written. 0 provider requests, 0 model calls.

    python -m scripts.memory status                          # rows by version, the lineage, the confidence by kind of memory
    python -m scripts.memory coverage --days 15              # day by day (Bogotá): the matches that report each figure, the rows written
    python -m scripts.memory rebuild                         # dry run of the lineage, 13 October to yesterday: nothing is written
    python -m scripts.memory rebuild --apply                 # write it, one commit per day
    python -m scripts.memory rebuild --from 2026-10-13 --to 2026-10-20 --apply --max-seconds 600
    python -m scripts.memory audit --sample 100 --seed 1     # recompute a sample of entities from scratch and compare with what is stored
    python -m scripts.memory priors --days 365               # how many matches a league's mean is worth, measured on the stored matches

``rebuild`` is ``fbi.intel.memory.rebuild``: every day from the first of the lineage (``LINEAGE_START``) to yesterday, oldest first, each on the
rows of the days before it, from the data as they are today. It is idempotent and resumable - a day that is written is skipped - so a run that
stopped (``--max-seconds``) is continued by running it again. A DRY RUN unless ``--apply`` is given: the same writes in a transaction that is
rolled back at the end (it says how much the table would grow). Until the lineage has begun the nightly step of the worker writes nothing; after
it, the nightly step continues it.

``audit`` is the proof that the stored state is what the data say: for a sample of the newest rows of the lineage it adds up, day by day, what
the data say of each entity and compares the numbers with the stored state. A difference is a day whose data changed after the memory booked it
(a statistic that arrived later than the three days the nightly step looks back); the memory never rewrites a row, so it stays and is shown.

``priors`` measures the weights ``m`` of the shrinkage of corners, cards and expected goals (``memory.METRICS``): for each figure, how much it
varies from match to match inside a team and from team to team inside a competition (``memory.variance_components``) over the matches of the last
``--days``; their ratio is the number of matches a league's mean is worth, and it is shown beside the weight the memory uses. It only measures:
changing a weight is a new version of the memory.

``status``, ``coverage``, ``audit`` and ``priors`` only read.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import local_day
from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.intel import memory

VERSIONS_SQL = """
SELECT version, count(*) AS rows, count(DISTINCT (entity_type, entity_id, aspect)) AS series, min(as_of_day) AS first,
       max(as_of_day) AS last, max(built_at) AS built
  FROM intel.entity_memory GROUP BY version ORDER BY min(built_at), version
"""
KINDS_SQL = """
WITH newest AS (
    SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, CASE WHEN aspect LIKE 'market:%%' THEN 'market:*' ELSE aspect END AS aspect,
           as_of_day, confidence
      FROM intel.entity_memory WHERE version = %(version)s ORDER BY entity_type, entity_id, aspect, as_of_day DESC, id DESC
)
SELECT entity_type, aspect, count(*) AS series, avg(confidence)::float8 AS mean,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY confidence)::float8 AS median, max(as_of_day) AS last
  FROM newest GROUP BY 1, 2 ORDER BY 1, 2
"""
SIZE_SQL = "SELECT pg_total_relation_size('intel.entity_memory'), pg_relation_size('intel.entity_memory')"
COVERAGE_SQL = """
WITH m AS (
    SELECT f.id, (f.kickoff_at AT TIME ZONE 'America/Bogota')::date AS day,
           (SELECT count(DISTINCT s.team_side) FROM core.fixture_team_stats s WHERE s.fixture_id = f.id AND s.corners IS NOT NULL) = 2 AS corners,
           (SELECT count(DISTINCT s.team_side) FROM core.fixture_team_stats s WHERE s.fixture_id = f.id) = 2 AS cards,
           (SELECT count(DISTINCT s.team_side) FROM core.fixture_team_stats s WHERE s.fixture_id = f.id AND s.expected_goals IS NOT NULL) = 2 AS xg
      FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
), written AS (
    SELECT as_of_day AS day, count(*) FILTER (WHERE aspect = 'corners') AS corners_rows, count(*) FILTER (WHERE aspect = 'cards') AS cards_rows,
           count(*) FILTER (WHERE aspect = 'xg') AS xg_rows
      FROM intel.entity_memory
     WHERE version = %(version)s AND entity_type = 'team' AND aspect IN ('corners', 'cards', 'xg') AND as_of_day >= %(from)s GROUP BY 1
)
SELECT m.day, count(*) AS matches, count(*) FILTER (WHERE m.corners) AS corners, count(*) FILTER (WHERE m.cards) AS cards,
       count(*) FILTER (WHERE m.xg) AS xg, COALESCE(max(w.corners_rows), 0) AS corners_rows, COALESCE(max(w.cards_rows), 0) AS cards_rows,
       COALESCE(max(w.xg_rows), 0) AS xg_rows
  FROM m LEFT JOIN written w ON w.day = m.day GROUP BY m.day ORDER BY m.day
"""
PRIORS_FIXTURES_SQL = """
SELECT f.id AS fixture_id, cs.competition_id, f.home_team_id, f.away_team_id
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
"""
LATEST_SQL = """
SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, entity_id, aspect, as_of_day, stats
  FROM intel.entity_memory WHERE version = %(version)s ORDER BY entity_type, entity_id, aspect, as_of_day DESC, id DESC
"""


def _n(value: int | float) -> str:
    return f"{int(value):,}"


def _mb(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def _m(weight: float | None) -> str:
    return "-" if weight is None else f"{weight:.1f}"


def _size(conn: psycopg.Connection[Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(SIZE_SQL)
        row = cur.fetchone()
    return int(row[0]) if row else 0


def yesterday(now: datetime) -> date:
    return local_day(now) - timedelta(days=1)


# ── rebuild ─────────────────────────────────────────────────────────────────


def rebuild_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    start = args.start or memory.LINEAGE_START
    end = args.end or yesterday(now)
    if end < start:
        print(f"nothing to build: {end} is before {start}")
        return 0
    print(f"{'APPLY' if args.apply else 'dry run (nothing is written)'}: {memory.VERSION}, every day from {start} to {end}, from the data as they are now")
    before = _size(conn)
    began = time.monotonic()
    report = memory.rebuild(conn, start=start, end=end, at=now, commit=conn.commit if args.apply else None, max_seconds=args.max_seconds)
    for day, rows in report.by_day.items():
        print(f"  {day}: {_n(rows)} rows" + ("" if rows else " (already written, or nothing that day)"), flush=True)
    grown = _size(conn) - before
    verb = "written" if args.apply else "that would be written"
    print(f"{_n(report.days)} days looked at ({report.first} - {report.last}), {_n(report.rows)} rows {verb} in {time.monotonic() - began:.0f} s; "
          f"intel.entity_memory {'grew' if args.apply else 'would grow'} by {_mb(grown)} (table and indexes)")
    if report.stopped:
        print(f"stopped: the {args.max_seconds:.0f} s budget ran out - run it again to go on")
    elif not args.apply and report.rows:
        print("dry run: re-run with --apply to write it")
    return 0


# ── status and coverage ─────────────────────────────────────────────────────


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(VERSIONS_SQL)
        versions = cur.fetchall()
        cur.execute(KINDS_SQL, {"version": memory.VERSION})
        kinds = cur.fetchall()
    print(f"writer: {memory.VERSION}; the lineage begins on {memory.LINEAGE_START}; intel.entity_memory weighs {_mb(_size(conn))}")
    for v in versions:
        print(f"  {v['version']}: {_n(v['rows'])} rows in {_n(v['series'])} series, days {v['first']} - {v['last']}, last built {v['built']:%d %b %H:%M} UTC")
    last = yesterday(now)
    if last >= memory.LINEAGE_START:
        started = memory.lineage_started(conn, last)
        built = any(v["version"] == memory.VERSION for v in versions)
        print(f"  the nightly step is "
              f"{'writing: the lineage has begun' if started or last == memory.LINEAGE_START else 'WAITING for the rebuild (it writes nothing until the lineage has begun)'}"
              f"{'' if built else '; no row of ' + memory.VERSION + ' yet'}")
    if kinds:
        print(f"  {'kind':<28} {'series':>7} {'mean confidence':>16} {'median':>8}  newest day")
        for k in kinds:
            print(f"  {k['entity_type'] + ' x ' + k['aspect']:<28} {_n(k['series']):>7} {k['mean']:>16.3f} {k['median']:>8.3f}  {k['last']}")
    return 0


def coverage_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    until = datetime.combine(local_day(now) + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    since = until - timedelta(days=args.days + 1)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE_SQL, {"since": since, "until": until, "version": memory.VERSION, "from": local_day(since)})
        rows = cur.fetchall()
    print("day (Bogotá)  matches |  corners  cards  xg  | team rows written: corners  cards  xg")
    for r in rows:
        print(f"{r['day']!s:<12} {r['matches']:>8} | {r['corners']:>8} {r['cards']:>6} {r['xg']:>3}  | {'':>18} {r['corners_rows']:>8} {r['cards_rows']:>6} {r['xg_rows']:>3}")
    print("(each match that reports a figure gives a row to each of its two teams, or fewer when a team played twice that day)")
    return 0


# ── priors ──────────────────────────────────────────────────────────────────

CHUNK = 2000
"""Matches whose statistics are read in one query."""


def priors_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    until = datetime.combine(local_day(now) + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    since = until - timedelta(days=args.days)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PRIORS_FIXTURES_SQL, {"since": since, "until": until})
        fixtures = [dict(r) for r in cur.fetchall()]
    # competition -> team -> the figure it produced (own) / conceded (opp) in each match, per figure
    series: dict[str, dict[str, dict[Any, dict[Any, list[float]]]]] = {a: {"own": {}, "opp": {}} for a in memory.METRICS}
    started = time.monotonic()
    for first in range(0, len(fixtures), CHUNK):
        chunk = fixtures[first:first + CHUNK]
        stats: dict[int, dict[str, dict[str, Any]]] = {}
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(memory.STATS_SQL, {"fixtures": [int(f["fixture_id"]) for f in chunk]})
            for r in cur.fetchall():
                stats.setdefault(int(r["fixture_id"]), {})[str(r["team_side"])] = dict(r)
        for f in chunk:
            sides = stats.get(int(f["fixture_id"]), {})
            home, away = sides.get("home") or {}, sides.get("away") or {}
            for aspect, metric in memory.METRICS.items():
                pair = metric.pair(home, away)
                if pair is None:
                    continue
                for team, own, opp in ((f["home_team_id"], pair[0], pair[1]), (f["away_team_id"], pair[1], pair[0])):
                    series[aspect]["own"].setdefault(f["competition_id"], {}).setdefault(team, []).append(own)
                    series[aspect]["opp"].setdefault(f["competition_id"], {}).setdefault(team, []).append(opp)
    print(f"priors: {_n(len(fixtures))} finished matches between {local_day(since)} and {local_day(until - timedelta(days=1))} (Bogotá), read in "
          f"{time.monotonic() - started:.0f} s; teams with at least {args.min_matches} matches that report the figure, in competitions with at least "
          f"{args.min_teams} such teams")
    print(f"  {'figure':<8} {'competitions':>12} {'teams':>6} {'matches':>8} | {'SD match':>8} {'SD team':>8} | {'m own':>6} {'m opp':>6} | "
          f"{'m in use':>8} | {'a team with 10 matches is itself':>32}")
    for aspect, metric in memory.METRICS.items():
        produced = memory.variance_components(series[aspect]["own"], min_matches=args.min_matches, min_teams=args.min_teams)
        conceded = memory.variance_components(series[aspect]["opp"], min_matches=args.min_matches, min_teams=args.min_teams)
        if produced is None or conceded is None:
            print(f"  {aspect:<8} not enough matches that report it (need {args.min_teams} teams with {args.min_matches} matches in one competition)")
            continue
        print(f"  {aspect:<8} {_n(produced.competitions):>12} {_n(produced.teams):>6} {_n(produced.matches):>8} | {produced.within ** 0.5:>8.2f} "
              f"{(produced.between ** 0.5 if produced.between > 0 else 0.0):>8.2f} | {_m(produced.prior_weight):>6} {_m(conceded.prior_weight):>6} | "
              f"{metric.prior_weight:>8.1f} | {10 / (10 + metric.prior_weight):>31.0%}")
    print("m = variance of a team from match to match / variance between the teams of a competition: how many matches a league's mean is worth "
          "(a team with n matches is its own figure in the proportion n / (n + m)). SD = square root of each variance, in the unit of the figure "
          "(the 'own' figure: what a team produces). This only measures: a weight changes with a new version of the memory.")
    return 0


# ── audit ───────────────────────────────────────────────────────────────────


def _same(stored: Any, fresh: Any) -> bool:
    if isinstance(fresh, float) or isinstance(stored, float):
        try:
            return abs(float(stored) - float(fresh)) <= 1e-5 * max(1.0, abs(float(fresh)))
        except (TypeError, ValueError):
            return False
    if isinstance(fresh, dict):  # a counter the news never touched is absent: absent means 0
        return isinstance(stored, dict) and all(_same(stored.get(k, 0), fresh.get(k, 0)) for k in {*stored, *fresh})
    if isinstance(fresh, list):
        return isinstance(stored, list) and sorted(stored) == sorted(fresh)
    return bool(stored == fresh)


def audit_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LATEST_SQL, {"version": memory.VERSION})
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        print(f"nothing to audit: no row of {memory.VERSION} yet")
        return 0
    rows = [r for r in rows if not memory.is_legacy((str(r["entity_type"]), str(r["entity_id"]), str(r["aspect"])))]
    sample = random.Random(args.seed).sample(rows, min(args.sample, len(rows)))
    last = max(r["as_of_day"] for r in sample)
    wanted = {(str(r["entity_type"]), str(r["entity_id"]), str(r["aspect"])): r for r in sample}
    states: dict[memory.EKey, dict[str, Any]] = {}
    day = memory.LINEAGE_START
    began = time.monotonic()
    while day <= last:
        deltas, _, _ = memory.day_deltas(conn, day)
        for key in wanted:
            if key in deltas:
                states[key] = memory.merge(states.get(key), deltas[key])
        day += timedelta(days=1)
    same = 0
    differences: list[str] = []
    for key, row in wanted.items():
        fresh = states.get(key, {})
        stored = row["stats"] or {}
        bad = [f for f, v in fresh.items() if f not in memory.DERIVED and f != "n_eff" and not f.startswith("w_") and not _same(stored.get(f), v)]
        if bad:
            differences.append(f"{key[0]} {key[1]} {key[2]} (row of {row['as_of_day']}): {', '.join(sorted(bad))}")
        else:
            same += 1
    print(f"audit of {_n(len(wanted))} of {_n(len(rows))} series of {memory.VERSION} (seed {args.seed}), every day {memory.LINEAGE_START} - {last} "
          f"added up again from the data in {time.monotonic() - began:.0f} s")
    print(f"  the stored state is what the data say: {_n(same)}; different: {_n(len(differences))}")
    for line in differences[:15]:
        print("  DIFFERENT " + line)
    if len(differences) > 15:
        print(f"  ... and {len(differences) - 15} more")
    return 1 if differences else 0


# ── main ────────────────────────────────────────────────────────────────────


def _day(text: str) -> date:
    return date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memory", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("rebuild", help="build the lineage day by day (dry run unless --apply)")
    r.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    r.add_argument("--from", dest="start", type=_day, default=None, help=f"first day (default {memory.LINEAGE_START})")
    r.add_argument("--to", dest="end", type=_day, default=None, help="last day (default: yesterday, Bogotá)")
    r.add_argument("--max-seconds", type=float, default=None, help="stop between days after this long")
    sub.add_parser("status", help="rows by version, the lineage, the confidence by kind (read only)")
    c = sub.add_parser("coverage", help="day by day: matches that report each figure, rows written (read only)")
    c.add_argument("--days", type=int, default=15)
    a = sub.add_parser("audit", help="recompute a sample of entities from scratch and compare (read only)")
    a.add_argument("--sample", type=int, default=100)
    a.add_argument("--seed", type=int, default=1)
    q = sub.add_parser("priors", help="measure how many matches a league's mean is worth for corners, cards and xG (read only)")
    q.add_argument("--days", type=int, default=365, help="how many days back (default 365)")
    q.add_argument("--min-matches", type=int, default=5, help="a team counts with at least this many matches that report the figure")
    q.add_argument("--min-teams", type=int, default=8, help="a competition counts with at least this many such teams")
    return ap


def main(argv: list[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        now = clock_now()
        if args.command == "rebuild":
            code = rebuild_command(conn, args, now=now)
            if not args.apply:
                conn.rollback()  # a dry run writes nothing: end its transaction without keeping anything
            return code
        code = {"status": status_command, "coverage": coverage_command, "audit": audit_command, "priors": priors_command}[args.command](
            conn, args, now=now)
        conn.rollback()  # read only
        return code


if __name__ == "__main__":
    sys.exit(main())

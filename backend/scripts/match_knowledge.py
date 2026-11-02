"""Match Knowledge (plan F7): a finished match as one object in layers. Build it, check it, look at one match. 0 provider requests.

    python -m scripts.match_knowledge status                         # coverage, the size of the tables, the last runs of the worker's job
    python -m scripts.match_knowledge coverage --days 400            # matches with a build, how complete, lines of events read
    python -m scripts.match_knowledge build                          # dry run: what a pass of the worker would build (the last 10 days)
    python -m scripts.match_knowledge build --apply                  # build it
    python -m scripts.match_knowledge build --days 400 --apply       # the backfill: one commit per 200 matches
    python -m scripts.match_knowledge build --fixture 123 --apply    # one or more matches, whatever their age (finished ones only)
    python -m scripts.match_knowledge audit --sample 200 --seed 1    # the criteria of the plan, on the stored rows and a sample rebuilt
    python -m scripts.match_knowledge show 123                       # the newest build of a match: layer by layer
    python -m scripts.match_knowledge show 123 --layer c6_market     # one layer, as JSON
    python -m scripts.match_knowledge show 123 --json --fresh        # the whole row, and whether building it today says the same

``build`` reads the facts already stored (``fbi.knowledge.reader``), builds the nine layers of every finished match that has been
settled (26 hours after kick-off) and whose inputs are not the ones its newest build read, and adds the row (``fbi.knowledge.builder``).
It is a DRY RUN unless ``--apply`` is given: the report says what would be written and nothing is. It looks at the competitions PrediGol
follows unless ``--all-competitions`` is given. A match is never built twice from the same inputs: running it again writes nothing.

``audit`` only reads. It exits 1 when a criterion fails: under 95 % of the finished matches of the followed competitions with a build, a
stored row whose ``content_hash`` is not the hash of its own layers, a row that is up to date (its inputs are the ones it read) and that
building today would say differently (a rule changed and its version did not), lines of events that are stale.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.knowledge import builder, layers, reader

MIN_COVERAGE = 95.0
"""The share of the finished matches of the followed competitions that must have a build (the criterion of the plan)."""
FLAPPING = 5
"""A match built more often than this is one whose inputs keep changing: the audit names how many."""

FINISHED_SQL = "SELECT id FROM core.fixtures WHERE id = ANY(%(ids)s::bigint[]) AND status_group = 'finished'"
LAST_RUNS_SQL = """
SELECT id, started_at, finished_at, status, rows_written, rows_updated, rows_normalized, errors, params
  FROM raw.ingestion_runs WHERE job_type = %s ORDER BY started_at DESC LIMIT %s
"""
TABLES_SQL = """
SELECT (SELECT count(*) FROM intel.match_knowledge) AS rows,
       (SELECT count(DISTINCT fixture_id) FROM intel.match_knowledge) AS matches,
       (SELECT count(*) FROM core.fixture_event_kinds) AS kinds,
       pg_total_relation_size('intel.match_knowledge') AS rows_bytes, pg_total_relation_size('core.fixture_event_kinds') AS kinds_bytes
"""
CHURN_SQL = """
SELECT count(*) FILTER (WHERE n > 1) AS rebuilt, count(*) FILTER (WHERE n > %(flapping)s) AS flapping, COALESCE(max(n), 0) AS most
  FROM (SELECT fixture_id, count(*) AS n FROM intel.match_knowledge WHERE version = %(version)s GROUP BY fixture_id) c
"""
SAMPLE_SQL = """
SELECT l.id, l.fixture_id, l.inputs_hash, l.content_hash, l.completeness, l.layers, l.quality
  FROM intel.match_knowledge_latest l JOIN core.fixtures f ON f.id = l.fixture_id
 WHERE l.version = %(version)s AND f.kickoff_at >= %(since)s
 ORDER BY md5(l.fixture_id::text || %(seed)s), l.fixture_id LIMIT %(sample)s
"""
NEWEST_SQL = """
SELECT id, fixture_id, version, supersedes, built_at, known_at, inputs_hash, content_hash, completeness, layers, quality
  FROM intel.match_knowledge WHERE fixture_id = %s AND version = %s ORDER BY id DESC LIMIT 1
"""
CHAIN_SQL = "SELECT id, supersedes, built_at, content_hash FROM intel.match_knowledge WHERE fixture_id = %s AND version = %s ORDER BY id"


def _n(value: int) -> str:
    return f"{value:,}"


def _kb(value: float) -> str:
    return f"{value / 1024:.2f} KB"


def _mb(value: float) -> str:
    return f"{value / 1024 / 1024:.1f} MB"


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.2f} %" if whole else "n/a"


# ── build ───────────────────────────────────────────────────────────────────


def finished_among(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[int]:
    """The matches asked for that are finished, in the order they were asked for: Match Knowledge is of matches that are over."""
    with conn.cursor() as cur:
        cur.execute(FINISHED_SQL, {"ids": list(ids)})
        finished = {int(r[0]) for r in cur.fetchall()}
    return [i for i in ids if i in finished]


def build_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime, commit: bool = True) -> int:
    tracked = not args.all_competitions
    if args.fixture:
        asked = list(dict.fromkeys(args.fixture))
        queue = finished_among(conn, asked)
        left_alone = len(asked) - len(queue)
        what = f"{_n(len(queue))} matches asked for" + (f" ({left_alone} not finished: left alone)" if left_alone else "")
    else:
        queue = builder.candidates(conn, now=now, days=args.days, tracked=tracked)
        what = (f"{_n(len(queue))} finished matches settled in the last {args.days} days "
                f"({'followed competitions' if tracked else 'all competitions'})")
    print(f"{'APPLY' if args.apply else 'dry run (nothing is written)'}: {what}")
    started = time.monotonic()
    shown = 0

    def progress(report: builder.BuildReport) -> None:
        nonlocal shown
        if len(queue) >= 1000 and report.seen - shown >= 1000:
            shown = report.seen
            print(f"  ... {_n(report.seen)}/{_n(len(queue))} looked at, {_n(report.built)} built, {time.monotonic() - started:.0f} s", flush=True)

    report = builder.build_many(conn, queue, apply=args.apply, max_seconds=args.max_seconds, limit=args.limit or None,
                                commit=commit and args.apply, chunk=args.chunk, progress=progress)
    verb = "built" if args.apply else "that would be built"
    print(f"looked at {_n(report.seen)} in {report.seconds:.1f} s: {_n(report.due)} due, {_n(report.built)} {verb} "
          f"({_n(report.same_content)} say what the last build said), {_n(report.raced)} left to another builder, {_n(report.failed)} failed")
    if report.built:
        print(f"the layers weigh {_kb(report.bytes)} in all: {_kb(report.bytes / report.built)} a match, the biggest {_kb(report.biggest)}")
        print("completeness: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(report.by_completeness.items())))
        for name in layers.LAYERS:
            states = {k.split(":", 1)[1]: v for k, v in report.by_layer.items() if k.startswith(name + ":")}
            if states:
                print(f"  {name:<14} " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(states.items())) + f"  ({_kb(report.layer_bytes[name] / report.built)} a match)")
    if args.apply and report.kinds:
        print(f"lines of events written or deleted: {_n(report.kinds)}")
    if report.stopped:
        print(f"STOPPED ({report.stopped}): {_n(report.left)} matches not reached")
    for message in report.errors[:10]:
        print("  FAILED " + message)
    if not args.apply and report.built:
        print("dry run: re-run with --apply to write it")
    return 1 if report.failed else 0


# ── coverage and status ─────────────────────────────────────────────────────


def _coverage_lines(label: str, c: dict[str, Any]) -> list[str]:
    e = c["events"]
    return [f"{label}, kicked off in the last {c['days']} days and settled: {_n(c['finished'])} finished matches, {_n(c['built'])} with a build "
            f"({c['share']:.2f} %): complete {_n(c['complete'])}, partial {_n(c['partial'])}, minimal {_n(c['minimal'])}",
            f"   events: {_n(e['with_events'])} matches have lines; the kind of each line is read for {_n(e['read'])}, "
            f"not yet for {_n(e['unread'])}, stale for {_n(e['stale'])}"]


def coverage_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    followed = builder.coverage(conn, now=now, days=args.days)
    everything = builder.coverage(conn, now=now, days=args.days, tracked=False)
    for line in [*_coverage_lines("followed competitions", followed), *_coverage_lines("all competitions", everything)]:
        print(line)
    met = followed["share"] >= MIN_COVERAGE
    print(f"criterion of the plan (at least {MIN_COVERAGE:g} % of the finished matches of the followed competitions): "
          f"{'MET' if met else 'NOT MET'}")
    return 0 if met or not followed["finished"] else 1


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TABLES_SQL)
        tables = cur.fetchone() or {}
        cur.execute(LAST_RUNS_SQL, (builder.JOB, args.runs))
        runs = cur.fetchall()
    print(f"rules: layers {layers.VERSION}, events {layers.RULES['events']}, sides {layers.RULES['sides']}")
    print(f"intel.match_knowledge: {_n(tables['rows'])} rows of {_n(tables['matches'])} matches, {_mb(tables['rows_bytes'])} "
          f"(with its indexes); core.fixture_event_kinds: {_n(tables['kinds'])} lines, {_mb(tables['kinds_bytes'])}")
    for line in _coverage_lines("followed competitions", builder.coverage(conn, now=now, days=args.days)):
        print(line)
    if not runs:
        print(f"the worker's job ({builder.JOB}) has no run in the ledger yet (a pass that builds nothing leaves none)")
    for r in runs:
        print(f"  run {r['id']} {r['started_at']:%Y-%m-%d %H:%M} {r['status']}: built {_n(r['rows_written'])}, lines {_n(r['rows_updated'])}, "
              f"looked at {_n(r['rows_normalized'])}" + (f", errors {r['errors']}" if r["errors"] else ""))
    return 0


# ── audit ───────────────────────────────────────────────────────────────────


def audit_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    failures: list[str] = []
    followed = builder.coverage(conn, now=now, days=args.days)
    for line in _coverage_lines("followed competitions", followed):
        print(line)
    if followed["finished"] and followed["share"] < MIN_COVERAGE:
        failures.append(f"only {followed['share']:.2f} % of the finished matches have a build (the plan asks for {MIN_COVERAGE:g} %)")
    if followed["events"]["stale"]:
        failures.append(f"{_n(followed['events']['stale'])} matches have lines of events that are stale")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CHURN_SQL, {"version": layers.VERSION, "flapping": FLAPPING})
        churn = cur.fetchone() or {}
        cur.execute(SAMPLE_SQL, {"version": layers.VERSION, "since": now - timedelta(days=args.days), "seed": str(args.seed),
                                 "sample": args.sample})
        sample = cur.fetchall()
    print(f"matches built more than once: {_n(churn['rebuilt'])}; more than {FLAPPING} times: {_n(churn['flapping'])}; the most: {churn['most']}")
    integrity = stale = drift = 0
    completeness: Counter[str] = Counter()
    states: Counter[str] = Counter()
    sizes: list[int] = []
    bad: list[str] = []
    for start in range(0, len(sample), reader.CHUNK):
        part = sample[start:start + reader.CHUNK]
        ids = [int(r["fixture_id"]) for r in part]
        signatures = reader.signatures(conn, ids)
        reads = reader.read(conn, ids)
        for row in part:
            fid = int(row["fixture_id"])
            completeness[str(row["completeness"])] += 1
            for name, layer in row["layers"].items():
                states[f"{name}:{layer['status']}"] += 1
            sizes.append(len(json.dumps(row["layers"], separators=(",", ":"), ensure_ascii=False)))
            if layers.content_hash(row["layers"], row["quality"], row["completeness"]) != row["content_hash"]:
                integrity += 1
                bad.append(f"match {fid}: the stored content_hash is not the hash of its layers")
                continue
            if signatures.get(fid) != row["inputs_hash"]:
                stale += 1
                continue
            read = reads.get(fid)
            if read is None or layers.build(read.inputs).content_hash != row["content_hash"]:
                drift += 1
                bad.append(f"match {fid}: up to date, and building it today says something else")
    print(f"sample of {_n(len(sample))} newest builds (seed {args.seed}): {_n(integrity)} whose content_hash is not the hash of their layers, "
          f"{_n(stale)} out of date (their inputs changed since), {_n(drift)} up to date that building today would say differently")
    if sample:
        print("completeness: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(completeness.items())))
        print(f"weight of the layers: mean {_kb(sum(sizes) / len(sizes))}, biggest {_kb(max(sizes))}")
        for name in layers.LAYERS:
            seen = {k.split(':', 1)[1]: v for k, v in states.items() if k.startswith(name + ':')}
            if seen:
                print(f"  {name:<14} " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(seen.items())))
    if integrity:
        failures.append(f"{integrity} stored rows whose content_hash is not the hash of their layers")
    if drift:
        failures.append(f"{drift} rows up to date that building today says differently: a rule changed and its version did not")
    for line in bad[:10]:
        print("  " + line)
    for failure in failures:
        print("FAIL: " + failure)
    print("audit: " + ("FAILED" if failures else "ok"))
    return 1 if failures else 0


# ── show ────────────────────────────────────────────────────────────────────


def show_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEWEST_SQL, (args.fixture, layers.VERSION))
        row = cur.fetchone()
        if row is None:
            print(f"match {args.fixture} has no build of {layers.VERSION}")
            return 1
        cur.execute(CHAIN_SQL, (args.fixture, layers.VERSION))
        chain = cur.fetchall()
    fresh = None
    if args.fresh:
        read = reader.read(conn, [args.fixture]).get(args.fixture)
        fresh = layers.build(read.inputs) if read is not None else None
    if args.layer:
        if args.layer not in row["layers"]:
            print(f"no layer {args.layer}; they are: {', '.join(row['layers'])}")
            return 1
        print(json.dumps(row["layers"][args.layer], indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.json:
        out = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
        print(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"match {row['fixture_id']}: build {row['id']} of {layers.VERSION}, {row['completeness']}, known at {row['known_at']:%Y-%m-%d %H:%M} UTC, "
              f"built {row['built_at']:%Y-%m-%d %H:%M} UTC; the build{'s' if len(chain) > 1 else ''}: "
              + " -> ".join(str(c["id"]) for c in chain))
        print(f"quality: {json.dumps(row['quality'], ensure_ascii=False, sort_keys=True)}")
        for name, layer in row["layers"].items():
            size = len(json.dumps(layer, separators=(",", ":"), ensure_ascii=False))
            notes = f"  notes: {', '.join(layer['notes'])}" if layer.get("notes") else ""
            print(f"  {name:<14} {layer['status']:<8} {_kb(size):>9}  known {layer.get('known_at', '-')}{notes}")
    if fresh is not None:
        same = fresh.content_hash == row["content_hash"]
        print("building it today says " + ("the same" if same else "something else (out of date, or a rule changed)"))
    return 0


# ── main ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="match_knowledge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build Match Knowledge of the finished matches that need it (dry run unless --apply)")
    b.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    b.add_argument("--days", type=int, default=builder.DEFAULT_DAYS, help="matches that kicked off in the last N days (default %(default)s)")
    b.add_argument("--fixture", type=int, action="append", help="a fixture id (repeatable): these matches, whatever their age")
    b.add_argument("--all-competitions", action="store_true", help="not only the competitions PrediGol follows")
    b.add_argument("--limit", type=int, default=0, help="stop after this many rows built")
    b.add_argument("--max-seconds", type=float, default=None, help="stop between matches after this long")
    b.add_argument("--chunk", type=int, default=reader.CHUNK, help="matches looked at, and committed, at a time (default %(default)s)")

    c = sub.add_parser("coverage", help="matches with a build, how complete, lines of events read (read only)")
    c.add_argument("--days", type=int, default=400)

    s = sub.add_parser("status", help="coverage, the size of the tables and the last runs of the worker's job (read only)")
    s.add_argument("--days", type=int, default=400)
    s.add_argument("--runs", type=int, default=5, help="runs of the job to list")

    a = sub.add_parser("audit", help="the criteria of the plan on the stored rows and a sample rebuilt (read only)")
    a.add_argument("--days", type=int, default=400)
    a.add_argument("--sample", type=int, default=200, help="newest builds to check (0 = none)")
    a.add_argument("--seed", default="1", help="the seed of the sample: the same seed gives the same matches")

    w = sub.add_parser("show", help="the newest build of one match (read only)")
    w.add_argument("fixture", type=int)
    w.add_argument("--layer", help="print this layer as JSON")
    w.add_argument("--json", action="store_true", help="print the whole row as JSON")
    w.add_argument("--fresh", action="store_true", help="also build it in memory and say whether it is the same")
    return ap


def main(argv: list[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "build":
            code = build_command(conn, args, now=clock_now())
            if not args.apply:
                conn.rollback()  # a dry run writes nothing: end its transaction without keeping anything
            return code
        if args.command == "coverage":
            code = coverage_command(conn, args, now=clock_now())
        elif args.command == "status":
            code = status_command(conn, args, now=clock_now())
        elif args.command == "audit":
            code = audit_command(conn, args, now=clock_now())
        else:
            code = show_command(conn, args)
        conn.rollback()  # read only
        return code


if __name__ == "__main__":
    sys.exit(main())

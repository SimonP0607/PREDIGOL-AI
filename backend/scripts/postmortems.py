"""The ONE post-mortem (plan F8): study every selection PrediGol looked at, once; look at what was written. 0 provider requests, 0 model calls.

    python -m scripts.postmortems status                       # what is written, by version, source and verdict; the prices; the backlog
    python -m scripts.postmortems coverage --days 15           # selections in the universe and studied, day by day (Bogotá)
    python -m scripts.postmortems build                        # dry run: what a pass of the worker would write (the last 7 days)
    python -m scripts.postmortems build --apply                # write it
    python -m scripts.postmortems build --days 15 --apply      # the backfill: selections 400 at a time, one commit each; then the matches

``build`` is the same function the learning cycle of the AI (07:35 Bogotá) and the nightly step of the intelligence layer run
(``fbi.intel.postmortem.study``, then ``fbi.intel.match_review.review_matches``), looped until nothing is left. A selection is written once
(a unique index): running it again writes nothing. It is a DRY RUN unless ``--apply`` is given - the same writes in a transaction that is
rolled back at the end. A selection is studied three hours after its match began; one whose match has no regulation score or whose market
has no settlement rule is counted and left alone.

``status`` and ``coverage`` only read. ``status`` counts how often the same selection carries a different price in the parts of PrediGol that
priced it (``evidence.prices``): the price taken (``evidence.price_from``) is chosen by a stated order, and this is how much that choice
matters (plan F8; measured on 23 Oct 2026: the same odds in 31 % of the pairs of item and review).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_start, local_day
from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.intel import match_review, postmortem

MAX_ROUNDS = 400
"""Rounds of ``build`` at most (400 selections each): a safety stop, never reached by a real backfill."""

VERSIONS_SQL = """
SELECT version, count(*) FILTER (WHERE market_key IS NOT NULL) AS selections,
       count(*) FILTER (WHERE market_key IS NULL) AS decisions_only, min(created_at) AS first, max(created_at) AS last
  FROM intel.postmortems GROUP BY version ORDER BY min(created_at), version
"""
TABLES_SQL = """
SELECT (SELECT count(*) FROM intel.selection_postmortems) AS selections,
       (SELECT count(*) FROM intel.match_postmortems) AS matches,
       (SELECT count(*) FROM ai.postmortem_narratives) AS narratives,
       (SELECT count(*) FROM ai.pick_postmortems) AS legacy_selections,
       (SELECT count(*) FROM ai.postmortems) AS legacy_matches,
       pg_total_relation_size('intel.postmortems') AS bytes, pg_total_relation_size('intel.match_postmortems') AS match_bytes
"""
SOURCE_SQL = """
SELECT CASE WHEN 'decision' = ANY(roles) AND roles && %(ai_roles)s THEN 'both'
            WHEN 'decision' = ANY(roles) THEN 'decision only' ELSE 'AI only' END AS source, count(*) AS n
  FROM intel.selection_postmortems GROUP BY 1 ORDER BY 1
"""
VERDICT_SQL = "SELECT review_verdict AS k, count(*) AS n FROM intel.selection_postmortems GROUP BY 1 ORDER BY 2 DESC"
CLASS_SQL = "SELECT loss_class AS k, count(*) AS n FROM intel.selection_postmortems WHERE loss_class IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
LUCK_SQL = "SELECT verdict AS k, count(*) AS n FROM intel.selection_postmortems GROUP BY 1 ORDER BY 2 DESC"
PRICE_FROM_SQL = """
SELECT COALESCE(evidence->>'price_from', 'none') AS k, count(*) AS n FROM intel.selection_postmortems GROUP BY 1 ORDER BY 2 DESC
"""
PRICE_PAIRS_SQL = """
WITH p AS (
    SELECT id, evidence->'prices' AS prices FROM intel.selection_postmortems
     WHERE jsonb_typeof(evidence->'prices') = 'object'
)
SELECT a.key || ' / ' || b.key AS pair, count(*) AS n,
       count(*) FILTER (WHERE (a.value->>'odds')::numeric = (b.value->>'odds')::numeric) AS same,
       avg(abs((a.value->>'odds')::numeric / (b.value->>'odds')::numeric - 1)) AS mean_difference
  FROM p, jsonb_each(p.prices) a, jsonb_each(p.prices) b
 WHERE a.key < b.key AND (a.value->>'odds') IS NOT NULL AND (b.value->>'odds') IS NOT NULL AND (b.value->>'odds')::numeric > 0
 GROUP BY 1 ORDER BY 1
"""
DONE_SQL = """
SELECT fixture_id, market_key, selection, line FROM intel.postmortems
 WHERE version = %(version)s AND market_key IS NOT NULL AND fixture_id = ANY(%(fixtures)s)
"""
KICKOFFS_SQL = "SELECT id, kickoff_at FROM core.fixtures WHERE id = ANY(%(ids)s)"


def _n(value: int) -> str:
    return f"{value:,}"


def _mb(value: float) -> str:
    return f"{value / 1024 / 1024:.2f} MB"


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "n/a"


def _counts(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any] | None = None) -> list[tuple[str, int]]:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return [(str(r[0]), int(r[1])) for r in cur.fetchall()]


# ── build ───────────────────────────────────────────────────────────────────


def build_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    lookback = timedelta(days=args.days)
    print(f"{'APPLY' if args.apply else 'dry run (nothing is written)'}: selections and matches that finished in the last {args.days} days "
          f"and are at least {postmortem.SETTLE_DELAY} old, under {postmortem.VERSION}")
    started = time.monotonic()
    total = Counter[str]()
    by_class = Counter[str]()
    by_source = Counter[str]()
    skipped = Counter[str]()
    errors: list[str] = []
    candidates = done = left = 0
    for round_no in range(1, MAX_ROUNDS + 1):
        study = postmortem.study(conn, at=now, lookback=lookback, limit=args.chunk)
        if round_no == 1:
            candidates, done = study.candidates, study.done
        left = study.left
        for name in ("studied", "wins", "losses", "memory_events", "outcome_disagreements"):
            total[name] += getattr(study, name)
        by_class.update(study.by_class)
        by_source.update(study.by_source)
        skipped.update(study.skipped)
        errors += study.errors
        if args.apply:
            conn.commit()
        if study.studied:
            print(f"  round {round_no}: {_n(study.studied)} studied, {_n(study.left)} left, {time.monotonic() - started:.0f} s", flush=True)
        if not study.studied or not study.left or (args.max_seconds and time.monotonic() - started > args.max_seconds):
            break
    matches = events = context_errors = 0
    for _ in range(MAX_ROUNDS):
        review = match_review.review_matches(conn, at=now, lookback=lookback, limit=200)
        matches += review.matches
        events += review.memory_events
        context_errors += review.context_errors
        errors += review.errors
        if args.apply:
            conn.commit()
        if not review.matches:
            break
    verb = "written" if args.apply else "that would be written"
    print(f"selections: {_n(candidates)} in the universe, {_n(done)} already written, {_n(total['studied'])} {verb} "
          f"({_n(total['wins'])} won, {_n(total['losses'])} lost), {_n(left)} left")
    if by_source:
        print("  by who looked at them: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(by_source.items())))
    if by_class:
        print("  classes of the losses: " + ", ".join(f"{k} {_n(v)}" for k, v in by_class.most_common()))
    if skipped:
        print("  left alone: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(skipped.items())))
    print(f"  results that differ from the decision layer's own settlement: {_n(total['outcome_disagreements'])}")
    print(f"matches as a whole: {_n(matches)} {verb}; memory events {_n(events + total['memory_events'])}; context errors {_n(context_errors)}")
    for message in errors[:10]:
        print("  FAILED " + message)
    if len(errors) > 10:
        print(f"  ... and {len(errors) - 10} more")
    if not args.apply and (total["studied"] or matches):
        print("dry run: re-run with --apply to write it")
    return 1 if errors else 0


# ── status and coverage ─────────────────────────────────────────────────────


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    from fbi.intel.pm_facts import AI_ROLES

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(VERSIONS_SQL)
        versions = cur.fetchall()
        cur.execute(TABLES_SQL)
        tables = cur.fetchone() or {}
    print(f"writer: {postmortem.VERSION} (selections), {match_review.VERSION} (matches)")
    print("intel.postmortems by version: " + ("; ".join(
        f"{v['version']}: {_n(v['selections'])} by selection, {_n(v['decisions_only'])} by decision ({v['first']:%d %b} - {v['last']:%d %b})"
        for v in versions) or "empty"))
    print(f"the newest of each selection: {_n(tables['selections'])}; matches as a whole: {_n(tables['matches'])}; narratives: "
          f"{_n(tables['narratives'])}; frozen tables: {_n(tables['legacy_selections'])} by selection (pm-v2), {_n(tables['legacy_matches'])} "
          f"by match (pm-v1.1); intel.postmortems weighs {_mb(tables['bytes'])}, intel.match_postmortems {_mb(tables['match_bytes'])}")
    for title, sql, params in (("who looked at them", SOURCE_SQL, {"ai_roles": sorted(AI_ROLES)}), ("verdict of the review", VERDICT_SQL, None),
                               ("class of a loss", CLASS_SQL, None), ("luck against price quality", LUCK_SQL, None),
                               ("the price taken came from", PRICE_FROM_SQL, None)):
        rows = _counts(conn, sql, params)
        if rows:
            print(f"  {title}: " + ", ".join(f"{k} {_n(v)}" for k, v in rows))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PRICE_PAIRS_SQL)
        pairs = cur.fetchall()
    for p in pairs:
        print(f"  the same selection priced by {p['pair']}: {_n(p['n'])} pairs, the same odds in {_share(int(p['same']), int(p['n']))}, "
              f"mean difference {100 * float(p['mean_difference']):.1f} %")
    since = day_start(local_day(now - timedelta(days=args.days)))
    candidates = postmortem.universe(conn, since=since, until=now - postmortem.SETTLE_DELAY)
    fixtures = sorted({k[0] for k in candidates})
    with conn.cursor() as cur:
        cur.execute(DONE_SQL, {"version": postmortem.VERSION, "fixtures": fixtures})
        written = {(int(r[0]), str(r[1]), str(r[2]), r[3]) for r in cur.fetchall()}
    waiting = sum(1 for k in candidates if k not in written)
    print(f"the last {args.days} days: {_n(len(candidates))} selections in the universe, {_n(len(candidates) - waiting)} written, "
          f"{_n(waiting)} waiting (a match with no regulation score or a market with no settlement rule waits for good)")
    return 0


def coverage_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    since = day_start(local_day(now - timedelta(days=args.days)))
    candidates = postmortem.universe(conn, since=since, until=now - postmortem.SETTLE_DELAY)
    fixtures = sorted({k[0] for k in candidates})
    with conn.cursor() as cur:
        cur.execute(KICKOFFS_SQL, {"ids": fixtures})
        day_of = {int(r[0]): local_day(r[1]) for r in cur.fetchall()}
        cur.execute(DONE_SQL, {"version": postmortem.VERSION, "fixtures": fixtures})
        written = {(int(r[0]), str(r[1]), str(r[2]), r[3]) for r in cur.fetchall()}
    days: dict[Any, list[int]] = {}
    for key in candidates:
        days.setdefault(day_of.get(key[0]), [0, 0])
        days[day_of.get(key[0])][0] += 1
        days[day_of.get(key[0])][1] += int(key in written)
    print("day (Bogotá)   selections  written  waiting")
    for day in sorted(days, key=lambda d: (d is None, d)):
        total, have = days[day]
        print(f"{str(day) if day else 'unknown':<13} {total:>11} {have:>8} {total - have:>8}")  # str(): a date formats its spec as strftime
    total = sum(v[0] for v in days.values())
    have = sum(v[1] for v in days.values())
    print(f"{'all':<13} {total:>11} {have:>8} {total - have:>8}  ({_share(have, total)} written)")
    return 0


# ── main ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="postmortems", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="study the selections and matches that need it (dry run unless --apply)")
    b.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    b.add_argument("--days", type=int, default=7, help="matches that finished in the last N days (default %(default)s)")
    b.add_argument("--chunk", type=int, default=postmortem.LIMIT, help="selections studied, and committed, at a time (default %(default)s)")
    b.add_argument("--max-seconds", type=float, default=None, help="stop between rounds after this long")
    s = sub.add_parser("status", help="what is written, the prices and the backlog (read only)")
    s.add_argument("--days", type=int, default=7)
    c = sub.add_parser("coverage", help="selections in the universe and studied, day by day (read only)")
    c.add_argument("--days", type=int, default=15)
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
        code = status_command(conn, args, now=clock_now()) if args.command == "status" else coverage_command(conn, args, now=clock_now())
        conn.rollback()  # read only
        return code


if __name__ == "__main__":
    sys.exit(main())

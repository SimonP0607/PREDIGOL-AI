"""The ONE post-mortem (plan F8): study every selection PrediGol looked at, once; look at what was written. 0 provider requests, 0 model calls.

    python -m scripts.postmortems status                       # what is written, by version, source and verdict; the prices; the backlog
    python -m scripts.postmortems coverage --days 15           # selections in the universe and studied, day by day (Bogotá)
    python -m scripts.postmortems closes --days 15             # the two closes a price is judged against, measured over the same selections
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
from statistics import StatisticsError, correlation, mean
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_start, local_day
from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.intel import match_review, postmortem
from fbi.market import closing_reference, closing_value

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
CLOSES_SQL = """
SELECT p.clv::float8 AS clv, p.price_move::float8 AS price_move, p.p_close::float8 AS p_close, p.close_odds::float8 AS close_odds,
       (p.evidence->'close'->>'minutes_to_ko')::int AS consensus_minutes, (p.evidence->'same_book_close'->>'minutes_to_ko')::int AS book_minutes
  FROM intel.selection_postmortems p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
"""
"""The post-mortems of the matches of a window with the two closes each one stored: the last Shin consensus (``p_close``, ``clv``) and the
provider's last price at the bookmaker the price was taken at (``close_odds``, ``price_move``), each with the minutes before kick-off."""
LABELS = ("GOOD", "NEUTRAL", "BAD")
"""The quality of a decision price, best first (``fbi.market.closing_value.quality``)."""


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


# ── closes ──────────────────────────────────────────────────────────────────


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _spread(values: list[float], digits: int = 0) -> str:
    if not values:
        return "n/a"
    return ", ".join(f"{name} {_quantile(values, q):.{digits}f}" for name, q in (("p10", 0.1), ("median", 0.5), ("p90", 0.9)))


def _pct(value: float) -> str:
    return f"{100 * value:+.1f} %"


def closes_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    """The two closes a price is judged against, over the SAME selections (plan F8.7): how many selections have each, how near kick-off each was
    captured, and how much the label of a price (GOOD / NEUTRAL / BAD) depends on which of the two it is measured at. It measures; the choice of the
    close CLV is measured at is the owner's (``fbi.market.closing_reference``)."""
    far_after = closing_reference.FAR_FROM_KICKOFF
    since = day_start(local_day(now - timedelta(days=args.days)))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLOSES_SQL, {"since": since, "until": now})
        rows = cur.fetchall()
    total = len(rows)
    print(f"the two closes a price is judged against, over the same selections: the matches of the last {args.days} days "
          f"({_n(total)} post-mortems)")
    if not rows:
        print("nothing is written in that window: python -m scripts.postmortems build --apply")
        return 0
    consensus = [r for r in rows if r["p_close"] is not None]
    book = [r for r in rows if r["close_odds"] is not None]
    both = [r for r in consensus if r["close_odds"] is not None and r["clv"] is not None and r["price_move"] is not None]
    far = [r for r in consensus if r["consensus_minutes"] is not None and r["consensus_minutes"] > far_after]
    print(f"  1. the last Shin consensus before kick-off ({closing_reference.REFERENCE}; what CLV is measured at): {_n(len(consensus))} "
          f"({_share(len(consensus), total)}); captured, in minutes before kick-off: "
          f"{_spread([float(r['consensus_minutes']) for r in consensus if r['consensus_minutes'] is not None])}; "
          f"more than {far_after} minutes before it: {_share(len(far), len(consensus))}")
    print(f"  2. the provider's last price at the bookmaker the price was taken at (what the price move is measured at): {_n(len(book))} "
          f"({_share(len(book), total)}); stamped, in minutes before kick-off: "
          f"{_spread([float(r['book_minutes']) for r in book if r['book_minutes'] is not None])}")
    both_n = sum(1 for r in consensus if r["close_odds"] is not None)
    print(f"  both: {_n(both_n)} ({_share(both_n, total)}); only the first: {_n(len(consensus) - both_n)}; "
          f"only the second: {_n(len(book) - both_n)}; neither: {_n(total - len(consensus) - len(book) + both_n)}")
    if len(both) < 2:
        print("  too few selections with both to compare them")
        return 0
    clvs = [float(r["clv"]) for r in both]
    moves = [float(r["price_move"]) for r in both]
    try:
        corr = f"{correlation(clvs, moves):.2f}"
    except StatisticsError:  # one of the two does not vary
        corr = "n/a"
    print(f"over the {_n(len(both))} that have both:")
    print(f"  mean CLV {_pct(mean(clvs))}, mean price move {_pct(mean(moves))}: the gap, {100 * (mean(moves) - mean(clvs)):.1f} points, is about the "
          f"closing margin of the books (clv = (1 + price move) x p_close x close_odds - 1); correlation {corr}")
    ratios = [float(r["p_close"]) * float(r["close_odds"]) for r in both]
    print(f"  p_close x close_odds, about 1 / (1 + margin) when both closes are the same moment: {_spread(ratios, 2)}; above 1.00 in "
          f"{_share(sum(1 for x in ratios if x > 1), len(ratios))} (the book's own last price was above the fair price of the consensus)")
    cells = Counter((closing_value.quality(c), closing_value.quality(m)) for c, m in zip(clvs, moves, strict=True))
    print("  the quality of the price by CLV (rows) and by the price move with the same band of +-1 % (columns; to compare, not a rule):")
    print(f"    {'':<8}" + "".join(f"{name:>9}" for name in LABELS))
    for label in LABELS:
        print(f"    {label:<8}" + "".join(f"{_n(cells[(label, other)]):>9}" for other in LABELS))
    agree = sum(cells[(label, label)] for label in LABELS)
    rank = {name: i for i, name in enumerate(LABELS)}  # GOOD 0, NEUTRAL 1, BAD 2
    worse = sum(n for (by_clv, by_move), n in cells.items() if rank[by_clv] > rank[by_move])
    print(f"  the two labels agree in {_share(agree, len(both))}; where they differ ({_n(len(both) - agree)}), CLV says worse than the price move "
          f"in {_share(worse, len(both) - agree)} (the margin of the book is in the price move, not in CLV)")

    def agreement(subset: list[dict[str, Any]]) -> str:
        hits = sum(1 for r in subset if closing_value.quality(float(r["clv"])) == closing_value.quality(float(r["price_move"])))
        return f"{_share(hits, len(subset))} of {_n(len(subset))}"

    near = [r for r in both if r["consensus_minutes"] is not None and r["consensus_minutes"] <= far_after]
    distant = [r for r in both if r["consensus_minutes"] is not None and r["consensus_minutes"] > far_after]
    print(f"  they agree in {agreement(near)} when the consensus was captured at most {far_after} minutes before kick-off, "
          f"in {agreement(distant)} when it was captured earlier")
    print("nothing here changes the close CLV is measured at: that is the owner's decision (fbi.market.closing_reference)")
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
    k = sub.add_parser("closes", help="the two closes a price is judged against, measured over the same selections (read only)")
    k.add_argument("--days", type=int, default=15, help="matches that kicked off in the last N days (default %(default)s)")
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
        reads = {"status": status_command, "coverage": coverage_command, "closes": closes_command}
        code = reads[args.command](conn, args, now=clock_now())
        conn.rollback()  # read only
        return code


if __name__ == "__main__":
    sys.exit(main())

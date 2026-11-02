"""Competition stages and ties (plan F2): build them, audit them, look at one season. 0 provider requests.

    python -m scripts.competition_stages build                      # dry run: the seasons worth building now
    python -m scripts.competition_stages build --apply              # build them, one commit per season
    python -m scripts.competition_stages build --all --apply        # the whole history (first deploy)
    python -m scripts.competition_stages build --league 2 --year 2025 --apply
    python -m scripts.competition_stages build --season 123 --force --apply
    python -m scripts.competition_stages audit                      # coverage, aggregates, ties, contradicted, a sample
    python -m scripts.competition_stages audit --drift --sample 40 --seed 7
    python -m scripts.competition_stages show --season 123          # the stages and ties of one season
    python -m scripts.competition_stages show --fixture 456

``build`` reads each season's fixtures, results and the provider's winner flags, works out its stages and ties
(``fbi.competitions``) and writes them with the stage, tie and leg of every fixture (``core.competition_stages``,
``core.ties``, ``core.fixtures``). It is a DRY RUN unless ``--apply`` is given: the report says what would be written
and nothing is. A season whose result is the one already stored is not written again. ``--force`` rewrites anyway.

``audit`` only reads. It says how much of the fixtures table has a stage, recomputes every aggregate from the legs'
goals in SQL (without the builder's code), counts the ties by status and by how they were decided, lists the ties the
next round contradicts, and prints a reproducible random sample of two-legged ties with their legs - to be checked
against an outside source by a person. It exits 1 when a criterion fails (coverage under 98% of the fixtures of the
tracked competitions, a stored aggregate that is not the sum of its legs, a sampled tie whose legs do not add up).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.competitions import builder
from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging

MIN_COVERAGE = 0.98
"""The share of the fixtures of the tracked competitions that must have a stage (the criterion of the plan)."""

SEASONS_OF_LEAGUES_SQL = """
SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.provider_league_id = ANY(%(leagues)s::int[])
   AND (%(years)s::int[] IS NULL OR cs.season = ANY(%(years)s::int[]))
   AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id)
 ORDER BY cs.id
"""
ALL_SEASONS_SQL = """
SELECT cs.id FROM core.competition_seasons cs
 WHERE EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id) ORDER BY cs.id
"""
SEASON_OF_FIXTURE_SQL = "SELECT competition_season_id FROM core.fixtures WHERE id = %s"

TIES_SQL = """
SELECT t.id, t.status, t.format, t.decided_by, t.reason, t.winner_check, t.flags
  FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id
  JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (%(everything)s OR c.is_tracked)
"""
STAGES_SQL = """
SELECT s.kind, s.role, s.tie_format, s.stage, s.fixtures
  FROM core.competition_stages s JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (%(everything)s OR c.is_tracked)
"""
NO_STAGE_SQL = """
SELECT c.provider_league_id AS league, c.name, cs.season, count(*) AS fixtures
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.stage_id IS NULL AND (%(everything)s OR c.is_tracked)
 GROUP BY 1, 2, 3 ORDER BY 4 DESC, 1, 3 LIMIT %(limit)s
"""
TIE_HEADER_SQL = """
SELECT t.id AS tie_id, c.provider_league_id AS league, c.name AS competition, cs.id AS season_id, cs.season, s.stage, s.ordinal,
       t.team_a_id, t.team_b_id, ta.name AS side_a, tb.name AS side_b, tw.name AS winner, t.format, t.status, t.legs, t.played,
       t.aggregate_a, t.aggregate_b, t.decided_by, t.shootout_a, t.shootout_b, t.winner_check, t.reason, t.flags
  FROM core.ties t JOIN core.competition_stages s ON s.id = t.stage_id
  JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams ta ON ta.id = t.team_a_id JOIN core.teams tb ON tb.id = t.team_b_id
  LEFT JOIN core.teams tw ON tw.id = t.winner_team_id
"""
CONTRADICTED_SQL = (TIE_HEADER_SQL + """
 WHERE t.winner_check = 'contradicted' AND (%(everything)s OR c.is_tracked)
 ORDER BY c.provider_league_id, cs.season, s.ordinal LIMIT %(limit)s
""")
SAMPLE_SQL = (TIE_HEADER_SQL + """
 WHERE t.status = 'decided' AND t.format = 'two_legged' AND t.played = 2 AND NOT 'score_repaired' = ANY(t.flags)
   AND (%(everything)s OR c.is_tracked)
 ORDER BY md5(t.id::text || %(seed)s), t.id LIMIT %(limit)s
""")
LEGS_SQL = """
SELECT f.tie_id, f.leg, f.id AS fixture_id, f.kickoff_at, f.status_short AS status, th.name AS home, ta.name AS away,
       f.home_team_id, f.away_team_id, r.goals_home, r.goals_away, r.pen_home, r.pen_away
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.tie_id = ANY(%(ties)s::bigint[]) ORDER BY f.tie_id, f.leg
"""
SEASON_SQL = """
SELECT c.provider_league_id AS league, c.name, c.country, cs.season, cs.id AS season_id
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id WHERE cs.id = %s
"""
STAGES_OF_SEASON_SQL = """
SELECT ordinal, stage, kind, role, rule, round_key, teams, fixtures, tie_format, tie_reason, ties, first_kickoff_at,
       last_kickoff_at, stages_version, ties_version, built_at, is_replay, base_stage
  FROM core.competition_stages WHERE competition_season_id = %s ORDER BY ordinal
"""


def _n(value: int) -> str:
    return f"{value:,}"


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.2f}%" if whole else "n/a"


# ── build ───────────────────────────────────────────────────────────────────


def select_seasons(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> list[int]:
    """The seasons the options name: ``--season``, the seasons of ``--league`` (``--year``), ``--all``, or what is pending."""
    if args.season:
        return list(dict.fromkeys(args.season))
    with conn.cursor() as cur:
        if args.league:
            cur.execute(SEASONS_OF_LEAGUES_SQL, {"leagues": args.league, "years": args.year or None})
            return [int(r[0]) for r in cur.fetchall()]
        if args.all:
            cur.execute(ALL_SEASONS_SQL)
            return [int(r[0]) for r in cur.fetchall()]
    return builder.pending(conn, now=now)


def build_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime, commit: bool = True) -> int:
    queue = select_seasons(conn, args, now=now)
    if args.limit:
        queue = queue[: args.limit]
    mode = "APPLY" if args.apply else "dry run (nothing is written)"
    print(f"{mode}: {_n(len(queue))} seasons to read{', forced' if args.force else ''}")
    started = time.monotonic()

    def progress(done: int, total: int) -> None:
        if total >= 200 and done % 100 == 0:
            print(f"  ... {_n(done)}/{_n(total)} seasons, {time.monotonic() - started:.0f} s", flush=True)

    report = builder.build_many(conn, queue, now=now, apply=args.apply, force=args.force, max_seconds=args.max_seconds,
                                commit=commit, progress=progress)
    verb = "written" if args.apply else "that would be written"
    print(f"seasons read {_n(report.seasons)} in {time.monotonic() - started:.1f} s: {_n(report.changed)} changed "
          f"({_n(report.first_builds)} for the first time), {_n(report.unchanged)} left as they were, "
          f"{_n(report.failed)} failed")
    print(f"stages {_n(report.stages)} and ties {_n(report.ties)} in the seasons read; "
          f"rows {verb}: {_n(report.rows_written)}; fixtures given a stage, tie or leg: {_n(report.fixtures_updated)}")
    if report.ties_by_status:
        print("ties by status: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(report.ties_by_status.items())))
    if report.contradicted:
        print(f"ties the next round contradicts: {_n(report.contradicted)} (python -m scripts.competition_stages audit lists them)")
    if report.stopped_for_time:
        print(f"STOPPED at the time limit: {_n(report.seasons_left)} seasons not reached")
    for message in report.errors[:10]:
        print("  FAILED " + message)
    if not args.apply and report.changed:
        print("dry run: re-run with --apply to write it")
    return 1 if report.failed else 0


# ── audit ───────────────────────────────────────────────────────────────────


def _score(goals: tuple[int | None, int | None]) -> str:
    return "?-?" if goals[0] is None or goals[1] is None else f"{goals[0]}-{goals[1]}"


def _tie_lines(conn: psycopg.Connection[Any], ties: Sequence[dict[str, Any]]) -> tuple[list[str], int]:
    """The ties with their legs, and how many do not add up (the legs' goals summed here, in Python, against the
    aggregate stored)."""
    legs: dict[int, list[dict[str, Any]]] = {}
    if ties:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(LEGS_SQL, {"ties": [t["tie_id"] for t in ties]})
            for row in cur.fetchall():
                legs.setdefault(int(row["tie_id"]), []).append(row)
    lines: list[str] = []
    bad = 0
    for t in ties:
        shoot = f", shoot-out {t['shootout_a']}-{t['shootout_b']}" if t["shootout_a"] is not None else ""
        winner = f"winner {t['winner']} ({t['decided_by']}{shoot})" if t["winner"] else f"no winner ({t['reason']})"
        agg = _score((t["aggregate_a"], t["aggregate_b"]))
        lines.append(f"  tie {t['tie_id']}: {t['competition']} ({t['league']}) {t['season']} · {t['stage']} · {t['side_a']} "
                     f"v {t['side_b']} · {t['format']} {t['status']} · aggregate {agg} · {winner} · next round: "
                     f"{t['winner_check']}" + (f" · {','.join(t['flags'])}" if t["flags"] else ""))
        sums = [0, 0]
        complete = True
        for leg in legs.get(int(t["tie_id"]), []):
            if leg["goals_home"] is None or leg["goals_away"] is None:
                complete = False
            else:
                for i, team in enumerate((t["team_a_id"], t["team_b_id"])):
                    sums[i] += leg["goals_home"] if leg["home_team_id"] == team else leg["goals_away"]
            pens = f" ({leg['pen_home']}-{leg['pen_away']} pens)" if leg["pen_home"] is not None else ""
            lines.append(f"      leg {leg['leg']} · {leg['kickoff_at']:%Y-%m-%d} · {leg['home']} "
                         f"{_score((leg['goals_home'], leg['goals_away']))} {leg['away']} · {leg['status']}{pens}"
                         f" · fixture {leg['fixture_id']}")
        if t["format"] in ("single", "two_legged") and t["aggregate_a"] is not None and complete:
            ok = (sums[0], sums[1]) == (t["aggregate_a"], t["aggregate_b"])
            bad += not ok
            lines.append(f"      legs add up to {sums[0]}-{sums[1]}: " + ("OK" if ok else "DIFFERENT from the stored aggregate"))
    return lines, bad


def audit_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, now: datetime) -> int:
    everything = bool(args.all_competitions)
    scope = "all competitions" if everything else "tracked competitions"
    failures: list[str] = []
    print(f"== competition stages and ties · {scope} · {now:%Y-%m-%d %H:%M} UTC")

    cov = builder.coverage(conn, tracked_only=not everything)
    print("\n-- coverage")
    print(f"  fixtures {_n(cov['fixtures'])} · with a stage {_n(cov['with_stage'])} ({_share(cov['with_stage'], cov['fixtures'])}) "
          f"· in knock-out or qualifying stages {_n(cov['in_ties'])} · with a tie {_n(cov['with_tie'])} "
          f"({_share(cov['with_tie'], cov['in_ties'])}) · in a stage no rule reads {_n(cov['unresolved'])}")
    share = cov["with_stage"] / cov["fixtures"] if cov["fixtures"] else 0.0
    verdict = "PASS" if share >= MIN_COVERAGE else "FAIL"
    print(f"  {verdict}  at least {100 * MIN_COVERAGE:.0f}% of the fixtures have a stage")
    if verdict == "FAIL":
        failures.append("coverage")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NO_STAGE_SQL, {"everything": everything, "limit": args.limit})
        missing = list(cur.fetchall())
    if missing:
        print("  seasons with fixtures that have no stage (most first):")
        for m in missing:
            print(f"    {m['name']} ({m['league']}) {m['season']}: {_n(m['fixtures'])}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STAGES_SQL, {"everything": everything})
        stages = list(cur.fetchall())
    kinds = Counter(s["kind"] for s in stages)
    print(f"\n-- stages: {_n(len(stages))} · " + " · ".join(f"{k} {_n(v)}" for k, v in sorted(kinds.items())))
    formats = Counter(s["tie_format"] for s in stages if s["kind"] in ("knockout", "qualifying"))
    print("  how the ties of knock-out and qualifying stages are played: "
          + " · ".join(f"{k or 'none'} {_n(v)}" for k, v in sorted(formats.items(), key=lambda kv: str(kv[0]))))
    unresolved: Counter[str] = Counter()
    for s in stages:
        if s["kind"] == "unresolved":
            unresolved[s["stage"]] += int(s["fixtures"])
    if unresolved:
        top = ", ".join(f"{label or '(no round)'!r} {_n(n)}" for label, n in unresolved.most_common(args.limit))
        print(f"  labels no rule reads ({_n(len(unresolved))} labels, {_n(sum(unresolved.values()))} fixtures): {top}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TIES_SQL, {"everything": everything})
        ties = list(cur.fetchall())
    print(f"\n-- ties: {_n(len(ties))}")
    by_status = Counter(t["status"] for t in ties)
    print("  status: " + " · ".join(f"{k} {_n(v)}" for k, v in sorted(by_status.items())))
    print("  decided by: " + " · ".join(f"{k} {_n(v)}" for k, v in sorted(
        Counter(t["decided_by"] for t in ties if t["status"] == "decided").items(), key=lambda kv: -kv[1])))
    reasons = Counter(t["reason"] for t in ties if t["status"] == "unresolved")
    if reasons:
        print("  unresolved because: " + " · ".join(f"{k} {_n(v)}" for k, v in reasons.most_common()))
    print("  the next round: " + " · ".join(f"{k} {_n(v)}" for k, v in sorted(
        Counter(t["winner_check"] for t in ties if t["status"] == "decided").items())))
    flags = Counter(f for t in ties for f in t["flags"])
    if flags:
        print("  flags: " + " · ".join(f"{k} {_n(v)}" for k, v in flags.most_common()))

    agg = builder.aggregate_check(conn)
    print("\n-- aggregates, summed from the legs' goals in SQL (not by the builder)")
    print(f"  ties checked {_n(agg['checked'])} · different from the stored aggregate {_n(agg['different'])} · "
          f"missing {_n(agg['missing'])} · none by design (a leg awarded without a score, or a shoot-out the goals "
          f"contradict) {_n(agg['unknown'])} · set apart because the provider's extra-time score was repaired "
          f"{_n(agg['repaired'])}")
    broken = agg["different"] + agg["missing"]
    print(f"  {'PASS' if not broken else 'FAIL'}  every stored aggregate is the sum of its legs, and none is missing")
    if broken:
        failures.append("aggregates")
        for d in builder.aggregate_differences(conn, limit=args.limit):
            print(f"    tie {d['tie_id']} ({d['kind']}): stored {d['stored_a']}-{d['stored_b']}, legs {d['summed_a']}-{d['summed_b']}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CONTRADICTED_SQL, {"everything": everything, "limit": args.limit})
        contradicted = list(cur.fetchall())
    shown = Counter(t["winner_check"] for t in ties)["contradicted"]
    print(f"\n-- ties the next round contradicts: {_n(shown)} (the pitch decides; these are administrative decisions or "
          f"data errors)" + (f" - first {len(contradicted)}:" if contradicted else ""))
    lines, _ = _tie_lines(conn, contradicted)
    for line in lines:
        print(line)

    if args.sample:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(SAMPLE_SQL, {"everything": everything, "limit": args.sample, "seed": str(args.seed)})
            sample = list(cur.fetchall())
        print(f"\n-- a sample of {len(sample)} decided two-legged ties (seed {args.seed}; the same seed gives the same "
              f"ties) to check against an outside source")
        lines, bad = _tie_lines(conn, sample)
        for line in lines:
            print(line)
        print(f"  {'PASS' if not bad else 'FAIL'}  the legs of every sampled tie add up to its aggregate")
        if bad:
            failures.append("sample")

    if args.drift:
        with conn.cursor() as cur:
            cur.execute(ALL_SEASONS_SQL)
            seasons = [int(r[0]) for r in cur.fetchall()]
        started = time.monotonic()
        stale = builder.drift(conn, seasons, now=now)
        print(f"\n-- drift: {_n(len(stale))} of {_n(len(seasons))} seasons would change if they were built now "
              f"({time.monotonic() - started:.0f} s)" + (f" - first: {stale[:20]}" if stale else ""))

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "all criteria pass"))
    return 1 if failures else 0


# ── show ────────────────────────────────────────────────────────────────────


def show_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    season_id = args.season
    if args.fixture:
        with conn.cursor() as cur:
            cur.execute(SEASON_OF_FIXTURE_SQL, (args.fixture,))
            found = cur.fetchone()
        if found is None:
            print(f"fixture {args.fixture} not found")
            return 1
        season_id = int(found[0])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEASON_SQL, (season_id,))
        head = cur.fetchone()
        if head is None:
            print(f"season {season_id} not found")
            return 1
        cur.execute(STAGES_OF_SEASON_SQL, (season_id,))
        stages = list(cur.fetchall())
        cur.execute(TIE_HEADER_SQL + " WHERE cs.id = %s ORDER BY s.ordinal, t.id", (season_id,))
        ties = list(cur.fetchall())
    print(f"{head['name']} ({head['country'] or '-'}) · league {head['league']} · season {head['season']} · id {head['season_id']}")
    if not stages:
        print(f"  not built yet (python -m scripts.competition_stages build --season {season_id} --apply)")
        return 0
    by_stage: dict[int, list[dict[str, Any]]] = {}
    for t in ties:
        by_stage.setdefault(int(t["ordinal"]), []).append(t)
    for s in stages:
        replay = f" · replays of {s['base_stage']!r}" if s["is_replay"] else ""
        bracket = f" · {s['round_key']}" + (f" ({s['teams']} teams)" if s["teams"] else "") if s["round_key"] else ""
        print(f"\n  {s['ordinal']:>2}. {s['stage'] or '(no round)'} · {s['kind']}/{s['role']} · rule {s['rule']}{bracket}{replay}"
              f" · {s['fixtures']} fixtures {s['first_kickoff_at']:%Y-%m-%d}..{s['last_kickoff_at']:%Y-%m-%d}"
              + (f" · ties {s['tie_format']}" + (f" ({s['tie_reason']})" if s["tie_reason"] else "") if s["tie_format"] else ""))
        lines, _ = _tie_lines(conn, by_stage.get(int(s["ordinal"]), []))
        for line in lines:
            print("  >>" + line[4:] if args.fixture and line.endswith(f"fixture {args.fixture}") else line)
    built = stages[0]
    print(f"\n  built {built['built_at']:%Y-%m-%d %H:%M} UTC by {built['stages_version']} / {built['ties_version']}")
    return 0


# ── main ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="competition_stages", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build the stages and ties of competition seasons (dry run unless --apply)")
    b.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    b.add_argument("--force", action="store_true", help="rewrite even a season whose stored result is the same")
    which = b.add_mutually_exclusive_group()
    which.add_argument("--season", type=int, action="append", help="competition season id (repeatable)")
    which.add_argument("--league", type=int, action="append", help="provider league id (repeatable): all its seasons")
    which.add_argument("--all", action="store_true", help="every season with fixtures")
    b.add_argument("--year", type=int, action="append", help="with --league: only this season year (repeatable)")
    b.add_argument("--limit", type=int, default=0, help="stop after this many seasons")
    b.add_argument("--max-seconds", type=float, default=None, help="stop between seasons after this long")

    a = sub.add_parser("audit", help="coverage, aggregates, ties and a sample to check by hand (read only)")
    a.add_argument("--all-competitions", action="store_true", help="not only the tracked competitions")
    a.add_argument("--sample", type=int, default=20, help="two-legged ties to print for checking (0 = none)")
    a.add_argument("--seed", default="1", help="the seed of the sample: the same seed gives the same ties")
    a.add_argument("--limit", type=int, default=25, help="rows per list")
    a.add_argument("--drift", action="store_true", help="also rebuild every season in memory and count those that differ")

    s = sub.add_parser("show", help="the stages and ties of one season")
    target = s.add_mutually_exclusive_group(required=True)
    target.add_argument("--season", type=int, help="competition season id")
    target.add_argument("--fixture", type=int, help="fixture id: the season it is in")
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
        code = audit_command(conn, args, now=clock_now()) if args.command == "audit" else show_command(conn, args)
        conn.rollback()  # read only
        return code


if __name__ == "__main__":
    sys.exit(main())

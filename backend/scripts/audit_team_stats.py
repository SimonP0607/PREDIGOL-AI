"""Team statistics truth audit, and why some teams have so few matches.

    python -m scripts.audit_team_stats                  # focus teams + 10 per golden league, this and last season
    python -m scripts.audit_team_stats --team 50 --league 39 --season 2026
    python -m scripts.audit_team_stats --history 80     # also classify 80 thin-history teams (/leagues?team)
    python -m scripts.audit_team_stats --history 80 --no-stats

/teams/statistics (league + season + team) against our finished fixtures of exactly that league
and season, and against the team page's record. Every answer is a NEW raw payload. Writes
audit.truth_v2_runs, the evidence ledger and data/truth/<stamp>-team_stats/. Nothing in core is
changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2 import team_history as th
from fbi.truth.v2 import team_stats as ts
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
GOLDEN = (39, 140, 135, 78, 61)
FOCUS = {50: "Manchester City", 541: "Real Madrid", 529: "Barcelona", 157: "Bayern München", 505: "Inter",
         8: "Colombia"}
PER_LEAGUE = 10


def _rows(conn: psycopg.Connection[Any], sql: str, params: Any = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def current_season(conn: psycopg.Connection[Any], league: int) -> int | None:
    rows = _rows(conn, "SELECT cs.season FROM core.competition_seasons cs JOIN core.competitions c ON "
                       "c.id = cs.competition_id WHERE c.provider_league_id = %s AND cs.is_current", (league,))
    return int(rows[0]["season"]) if rows else None


def plan(conn: psycopg.Connection[Any]) -> list[tuple[int, int, int, str]]:
    """(league, season, provider team, name) to audit: focus teams in every competition of their current
    season and their previous domestic season; 10 teams per golden league this and last season; one women's
    and one youth team."""
    out: list[tuple[int, int, int, str]] = []
    for pid, name in FOCUS.items():
        for r in _rows(conn, """
            SELECT DISTINCT c.provider_league_id, cs.season FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
              JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
             WHERE t.provider_team_id = %s AND f.status_group = 'finished'
               AND cs.season >= (SELECT max(cs2.season) - 1 FROM core.competition_seasons cs2
                                  JOIN core.fixtures f2 ON f2.competition_season_id = cs2.id
                                 WHERE t.id IN (f2.home_team_id, f2.away_team_id) AND f2.status_group = 'finished')
            """, (pid,)):
            out.append((int(r["provider_league_id"]), int(r["season"]), pid, name))
    for league in GOLDEN:
        season = current_season(conn, league)
        if season is None:
            continue
        for s in (season, season - 1):
            teams = _rows(conn, """
                SELECT DISTINCT t.provider_team_id, t.name FROM core.fixtures f
                  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                  JOIN core.competitions c ON c.id = cs.competition_id
                  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
                 WHERE c.provider_league_id = %s AND cs.season = %s ORDER BY t.provider_team_id""", (league, s))
            rnd = random.Random(league * 10_000 + s)
            for t in rnd.sample(teams, min(PER_LEAGUE, len(teams))):
                out.append((league, s, int(t["provider_team_id"]), str(t["name"])))
    for league, label in ((44, "women"), (38, "youth")):
        found = _rows(conn, """
            SELECT c.provider_league_id, cs.season, t.provider_team_id, t.name, count(*) AS n FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
              JOIN core.teams t ON t.id = f.home_team_id
             WHERE c.provider_league_id = %s AND f.status_group = 'finished'
             GROUP BY 1, 2, 3, 4 ORDER BY cs.season DESC, n DESC LIMIT 1""", (league,))
        if found:
            top = found[0]
            out.append((int(top["provider_league_id"]), int(top["season"]), int(top["provider_team_id"]),
                        f"{top['name']} ({label})"))
    seen, unique = set(), []
    for item in out:
        if item[:3] not in seen:
            seen.add(item[:3])
            unique.append(item)
    return unique


async def stats(run: V2Run, conn: psycopg.Connection[Any], targets: list[tuple[int, int, int, str]]
                ) -> tuple[list[ts.TeamAudit], list[Evidence]]:
    audits, evidence = [], []
    ids = {int(r["provider_team_id"]): int(r["id"]) for r in _rows(
        conn, "SELECT id, provider_team_id FROM core.teams WHERE provider_team_id = ANY(%s)",
        ([t[2] for t in targets],))}
    for league, season, team, name in targets:
        if team not in ids:
            continue
        answer = await run.get("/teams/statistics", {"league": league, "season": season, "team": team})
        rows = ts.our_fixtures(conn, league=league, season=season, team_id=ids[team])
        a = ts.audit_team(answer.body if answer else None, rows, league=league, season=season, team=team, name=name,
                          at=run.at, product=ts.product_record(conn, ids[team]),
                          payload_hash=answer.payload_hash if answer else None)
        audits.append(a)
        evidence += ts.evidence(a, answer.ref() if answer else None)
    for extra in (ts.scope_evidence(audits), ts.shootout_evidence(audits)):
        if extra is not None:
            evidence.append(extra)
    return audits, evidence


async def history(run: V2Run, conn: psycopg.Connection[Any], n: int) -> tuple[dict[str, Any], list[Evidence]]:
    teams = th.team_counts(conn)
    dist = th.distribution(teams)
    dups = th.duplicates(teams)
    tracked = {int(r["provider_league_id"]) for r in _rows(conn, "SELECT provider_league_id FROM core.competitions "
                                                                 "WHERE is_tracked")}
    # a season counts as held only when it was migrated: catalogue rows exist for seasons whose fixtures were
    # never fetched (before 2018, Friendlies Clubs before the current season)
    held = {(int(r["provider_league_id"]), int(r["season"])): int(r["id"]) for r in _rows(
        conn, "SELECT cs.id, c.provider_league_id, cs.season FROM core.competition_seasons cs "
              "JOIN core.competitions c ON c.id = cs.competition_id "
              "WHERE EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id)")}
    thin = [t for t in teams if int(t["fixtures"]) < 20]
    rnd = random.Random(20261004)
    sample = rnd.sample(thin, min(n, len(thin)))
    verdicts = []
    for t in sample:
        answer = await run.get("/leagues", {"team": int(t["provider_team_id"])})
        ours = {(int(r["provider_league_id"]), int(r["season"])): int(r["n"]) for r in _rows(conn, """
            SELECT c.provider_league_id, cs.season, count(*) AS n FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
             WHERE %s IN (f.home_team_id, f.away_team_id) GROUP BY 1, 2""", (int(t["id"]),))}
        verdicts.append(th.classify(t, answer.body if answer else None, tracked=tracked, held=held, ours_by_cs=ours,
                                    dups=dups.get(int(t["provider_team_id"]), [])))
    labels: dict[str, int] = {}
    for v in verdicts:
        labels[v.label] = labels.get(v.label, 0) + 1
    body = {"distribution": dist, "thin_teams": len(thin), "duplicate_rows": len(dups), "sampled": len(sample),
            "labels": labels, "verdicts": [v.__dict__ for v in verdicts]}
    return body, th.evidence(verdicts)


def markdown(audits: list[ts.TeamAudit], hist: dict[str, Any] | None, codes: dict[str, str], requests: int) -> str:
    lines = [f"# Team statistics truth audit - {len(audits)} team-seasons, {requests} requests", "",
             "| Team | League | Season | Verdict | Played API/ours | W-D-L API | W-D-L ours | GF-GA API | GF-GA ours | "
             "Team page record: headline (lifetime) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for a in sorted(audits, key=lambda a: (a.verdict == "ok", a.league, a.season)):
        def wdl(d: dict[str, int | None]) -> str:
            return f"{d.get('wins.total')}-{d.get('draws.total')}-{d.get('loses.total')}"

        def g(d: dict[str, int | None]) -> str:
            return f"{d.get('goals_for.total')}-{d.get('goals_against.total')}"

        lines.append(f"| {a.name} ({a.team}) | {a.league} | {a.season} | **{a.verdict}** | "
                     f"{a.api.get('played.total')}/{a.ours.get('played.total')} | {wdl(a.api)} | {wdl(a.ours)} | "
                     f"{g(a.api)} | {g(a.ours)} | {a.product.get('played')} {a.product.get('competition') or ''} "
                     f"{a.product.get('season') or ''} (lifetime {a.product.get('lifetime_played')}) |")
    if hist:
        lines += ["", f"## Thin histories - {hist['thin_teams']} teams under 20 fixtures, {hist['sampled']} sampled",
                  "", f"Distribution: {hist['distribution']['buckets']}", "", f"Labels: {hist['labels']}"]
    if codes:
        lines += ["", "Evidence: " + " ".join(sorted(codes.values()))]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    from fbi.providers.api_football.build import build_client

    at = now()
    client = build_client(max_requests=args.max_requests)
    try:
        with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
            conn.execute("SET statement_timeout = '300s'")
            if args.team:
                targets = [(args.league, args.season, t, str(t)) for t in args.team]
            elif args.no_stats:
                targets = []
            else:
                targets = plan(conn)
            run = V2Run(conn, client, "team_stats", at, params={"targets": len(targets), "history": args.history})
            audits: list[ts.TeamAudit] = []
            evidence: list[Evidence] = []
            hist: dict[str, Any] | None = None
            try:
                audits, evidence = await stats(run, conn, targets)
                if args.history:
                    hist, hist_ev = await history(run, conn, args.history)
                    evidence += hist_ev
            except BaseException:
                run.finish({"error": "interrupted or failed", "done": len(audits)}, failed=True)
                raise
            codes = record_all(conn, evidence, at=at, run_id=run.run_id)
            if not args.team and not args.no_stats and not run.stopped:
                clear_unseen(conn, area="team_stats", scope_prefix="team_stats:", seen=codes.keys(), at=at)
            if args.history and not run.stopped:
                clear_unseen(conn, area="team_history", scope_prefix="team_history:", seen=codes.keys(), at=at)
            verdicts: dict[str, int] = {}
            for a in audits:
                verdicts[a.verdict] = verdicts.get(a.verdict, 0) + 1
            hist_summary = {k: v for k, v in (hist or {}).items() if k != "verdicts"}
            summary = {"team_seasons": len(audits), "verdicts": verdicts, "requests": run.requests,
                       "stopped": run.stopped, "failures": run.failures[:20], "evidence": codes,
                       "history": hist_summary}
            body = {**summary, "audits": [a.__dict__ for a in audits], "history_verdicts": (hist or {}).get("verdicts")}
            folder = write_report(REPORTS, "team_stats", at, body, markdown(audits, hist, codes, run.requests))
            status = run.finish(summary, report_dir=folder)
    finally:
        await client.aclose()
    print(json.dumps({"status": status, "team_seasons": len(audits), "verdicts": verdicts,
                      "history": hist_summary.get("labels"), "requests": run.requests,
                      "evidence": len(codes), "report": str(folder)}, indent=1, default=str))
    return 0 if status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_team_stats", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", type=int, action="append", help="provider team id (with --league and --season)")
    parser.add_argument("--league", type=int)
    parser.add_argument("--season", type=int)
    parser.add_argument("--history", type=int, default=0, help="classify N thin-history teams")
    parser.add_argument("--no-stats", action="store_true")
    parser.add_argument("--max-requests", type=int, default=400)
    args = parser.parse_args()
    if args.team and (args.league is None or args.season is None):
        parser.error("--team needs --league and --season")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

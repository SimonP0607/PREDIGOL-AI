"""Standings truth audit: the provider's table vs ours vs the table our fixtures imply.

    python -m scripts.audit_standings                       # every tracked current season with a table
    python -m scripts.audit_standings --league 39 --league 140
    python -m scripts.audit_standings --season 2025 --league 39   # a past season (golden validation)
    python -m scripts.audit_standings --no-api              # ours vs the fixtures only, 0 requests
    python -m scripts.audit_standings --external FILE.json  # also compare an official table (see below)
    python -m scripts.audit_standings --decisions FILE.json # results decided off the pitch (sports courts)

One /standings request per season, stored as a NEW raw payload. Writes audit.truth_v2_runs, the
evidence ledger (audit.evidence_ledger) and data/truth/<stamp>-standings/. Nothing in core is
changed.

External file: a JSON list of {"league", "season", "source", "url", "accessed_at",
"rows": [{"team": <provider team id>, "name", "played", "points", "gd"}]} transcribed from the
league's official site; each row is compared with the provider's table and with ours (tolerance 0).

Exit status: 0 completed, 1 partial (a request failed or the cap stopped it).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2 import standings as st
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
ORDER = ("predigol_behind", "mismatch", "missing_in_db", "provider_stale", "fixtures_missing", "provider_identity",
         "provider_inconsistent", "adjusted", "provider_lag_expected", "no_api_table", "no_table", "not_asked", "ok")

SCOPE_CURRENT = """c.is_tracked AND cs.is_current AND (
    EXISTS (SELECT 1 FROM core.standings s WHERE s.competition_season_id = cs.id)
    OR c.type = 'league'
    OR EXISTS (SELECT 1 FROM raw.league_coverage lc WHERE lc.provider_league_id = c.provider_league_id
                  AND lc.season = cs.season AND lc.standings))"""


def external_evidence(ext: dict[str, Any], audit: st.SeasonAudit, api: list[st.Row], db: list[st.Row]) -> list[Evidence]:
    """An official table against the provider's and ours: played and points, tolerance 0."""
    out: list[Evidence] = []
    api_by = {r.team: r for r in api}
    db_by = {r.team: r for r in db}
    api_off, db_off, compared = [], [], 0
    for row in ext.get("rows", []):
        team = int(row["team"])
        compared += 1
        a, d = api_by.get(team), db_by.get(team)
        want = (int(row["played"]), int(row["points"]))
        if a is None or (a.total.played, a.total.points) != want:
            api_off.append({"team": team, "name": row.get("name"), "official": want,
                            "provider": None if a is None else (a.total.played, a.total.points)})
        if d is None or (d.total.played, d.total.points) != want:
            db_off.append({"team": team, "name": row.get("name"), "official": want,
                           "predigol": None if d is None else (d.total.played, d.total.points)})
    source = {k: ext.get(k) for k in ("source", "url", "accessed_at")}
    label = f"{audit.name} {audit.season} ({audit.league})"
    key = f"standings:{audit.league}:{audit.season}:official"
    audit.notes.append(f"official table ({ext.get('source')}): {compared} rows, provider differs on {len(api_off)}, "
                       f"ours on {len(db_off)}")
    if api_off:
        out.append(Evidence(
            key=f"{key}:provider", area="standings", issue_type="PROVIDER_EXTERNAL_MISMATCH", severity="high",
            at_fault="provider", entity=label,
            claim=f"{label}: the provider's table differs from the official one on {len(api_off)} of {compared} rows "
                  "(played, points)",
            api={"payload_hash": audit.payload_hash, "rows": api_off[:10]}, external={**source, "rows": compared}))
    if db_off:
        out.append(Evidence(
            key=f"{key}:predigol", area="standings", issue_type="STANDINGS_MISMATCH", severity="high",
            at_fault="predigol" if not api_off else "undetermined", entity=label,
            claim=f"{label}: our newest table differs from the official one on {len(db_off)} of {compared} rows",
            db={"snapshot_at": audit.snapshot_at, "rows": db_off[:10]}, external={**source, "rows": compared}))
    return out


def markdown(audits: list[st.SeasonAudit], codes: dict[str, str], requests: int) -> str:
    lines = [f"# Standings truth audit - {len(audits)} seasons, {requests} requests", "",
             "| League | Season | Verdict | Rows (API/DB) | Row verdicts | Provider update | Our snapshot | "
             "Last finished | Evidence |", "|---|---|---|---|---|---|---|---|---|"]

    def fmt(v: Any) -> str:
        return v.strftime("%m-%d %H:%M") if hasattr(v, "strftime") else ("-" if v is None else str(v))

    for a in sorted(audits, key=lambda a: (ORDER.index(a.verdict) if a.verdict in ORDER else 99, a.league)):
        rows = ", ".join(f"{k} {n}" for k, n in sorted(a.counts().items()))
        ev = " ".join(c for k, c in codes.items() if k.startswith(f"standings:{a.league}:{a.season}:"))
        lines.append(f"| {a.name} ({a.league}) | {a.season} | **{a.verdict}** | {a.api_rows}/{a.db_rows} | {rows} | "
                     f"{fmt(a.api_update)} | {fmt(a.snapshot_at)} | {fmt(a.last_finished)} | {ev} |")
    return "\n".join(lines) + "\n"


async def audit_one(run: V2Run, conn: psycopg.Connection[Any], facts: dict[str, Any], *, no_api: bool,
                    externals: dict[tuple[int, int], dict[str, Any]],
                    decisions: dict[int, st.Decision] | None = None) -> tuple[st.SeasonAudit, list[Evidence]]:
    answer = None
    if run.client is not None:
        answer = await run.get("/standings", {"league": facts["provider_league_id"], "season": facts["season"]})
    db = st.db_rows(conn, int(facts["cs_id"]))
    matches = st.finished(conn, int(facts["cs_id"]))
    body: dict[str, Any] | None = answer.body if answer is not None else None
    if no_api:
        # ours vs the fixtures: our newest snapshot plays the provider's part
        body = {"response": [{"league": {"standings": [[
            {"team": {"id": r.team, "name": r.name}, "group": r.group, "rank": r.rank, "points": r.total.points,
             "all": {"played": r.total.played, "win": r.total.win, "draw": r.total.draw, "lose": r.total.lose,
                     "goals": {"for": r.total.gf, "against": r.total.ga}}} for r in db]]}}]}
    mine = {f: d for f, d in (decisions or {}).items()
            if (d.league, d.season) == (int(facts["provider_league_id"]), int(facts["season"]))}
    audit = st.audit_season(facts, body, db, matches, at=run.at,
                            payload_hash=answer.payload_hash if answer else None,
                            fetched_at=answer.fetched_at if answer else None,
                            awarded_pairs=st.awarded(conn, int(facts["cs_id"])),
                            official=st.decided(conn, int(facts["cs_id"]), mine))
    evidence: list[Evidence] = []
    if not no_api:
        evidence += st.evidence(audit, answer.ref() if answer else None)
        ext = externals.get((audit.league, audit.season))
        if ext is not None and answer is not None:
            evidence += external_evidence(ext, audit, st.api_rows(answer.body), db)
    return audit, evidence


async def run(args: argparse.Namespace) -> int:
    from fbi.providers.api_football.build import build_client

    at = now()
    client = None if args.no_api else build_client(max_requests=args.max_requests)
    externals: dict[tuple[int, int], dict[str, Any]] = {}
    if args.external:
        for ext in json.loads(Path(args.external).read_text()):
            externals[(int(ext["league"]), int(ext["season"]))] = ext
    decisions = st.load_decisions(args.decisions)
    try:
        with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
            conn.execute("SET statement_timeout = '120s'")
            if args.season is not None:
                where, params = "cs.season = %(season)s", {"season": args.season}
            else:
                where, params = SCOPE_CURRENT, {}
            if args.league:
                where += " AND c.provider_league_id = ANY(%(leagues)s)"
                params["leagues"] = args.league
            seasons = st.season_facts(conn, where, params)
            run = V2Run(conn, client, "standings", at, params={"leagues": args.league, "season": args.season,
                                                               "seasons": len(seasons), "api": not args.no_api})
            audits: list[st.SeasonAudit] = []
            evidence: list[Evidence] = []
            try:
                for facts in seasons:
                    audit, found = await audit_one(run, conn, facts, no_api=args.no_api, externals=externals,
                                                   decisions=decisions)
                    audits.append(audit)
                    evidence += found
            except BaseException:
                run.finish({"error": "interrupted or failed", "seasons_done": len(audits)}, failed=True)
                raise
            codes = record_all(conn, evidence, at=at, run_id=run.run_id) if not args.no_api else {}
            if not args.no_api and not args.league and args.season is None and not run.stopped:
                clear_unseen(conn, area="standings", scope_prefix="standings:", seen=codes.keys(), at=at,
                             keep_containing=None if externals else ":official")
            elif not args.no_api:
                # a scoped run audited each of its seasons whole: what it no longer finds there is cleared
                for a in audits:
                    if a.verdict != "not_asked":
                        clear_unseen(conn, area="standings", scope_prefix=f"standings:{a.league}:{a.season}:",
                                     seen=codes.keys(), at=at,
                                     keep_containing=None if (a.league, a.season) in externals else ":official")
            verdicts: dict[str, int] = {}
            for a in audits:
                verdicts[a.verdict] = verdicts.get(a.verdict, 0) + 1
            summary = {"seasons": len(audits), "verdicts": verdicts, "requests": run.requests,
                       "stopped": run.stopped, "failures": run.failures[:20], "evidence": codes,
                       "by_season": [a.summary() for a in audits]}
            body_out = {**summary, "rows": {f"{a.league}:{a.season}": [r.__dict__ for r in a.rows] for a in audits}}
            folder = write_report(REPORTS, "standings", at, body_out, markdown(audits, codes, run.requests))
            status = run.finish(summary, report_dir=folder)
    finally:
        if client is not None:
            await client.aclose()
    print(json.dumps({"status": status, "seasons": len(audits), "verdicts": verdicts, "requests": run.requests,
                      "evidence": len(codes), "report": str(folder)}, indent=1, default=str))
    return 0 if status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_standings", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league", type=int, action="append", help="provider league id (repeatable)")
    parser.add_argument("--season", type=int, help="a past season instead of the current ones")
    parser.add_argument("--no-api", action="store_true", help="0 requests: our table vs our fixtures")
    parser.add_argument("--external", help="official tables to compare (JSON)")
    parser.add_argument("--decisions", help="official results decided off the pitch (JSON, see fbi.truth.v2.standings."
                                            "load_decisions)")
    parser.add_argument("--max-requests", type=int, default=400)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())

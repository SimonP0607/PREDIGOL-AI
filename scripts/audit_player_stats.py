"""Player statistics truth audit: provider season blocks vs our match rows vs what the product shows.

    python -m scripts.audit_player_stats                         # focus players + 20 per golden league
    python -m scripts.audit_player_stats --player 1100 --player 184
    python -m scripts.audit_player_stats --per-league 0          # focus players only
    python -m scripts.audit_player_stats --external FILE.json    # also compare an external source

Per player: /players?id&season for this and last season (every team x league block), and for the
focus players /players/teams (career: current club, national team), /players/squads and
/injuries?player&season. Every answer is a NEW raw payload. Writes audit.truth_v2_runs, the evidence
ledger and data/truth/<stamp>-player_stats/. Nothing in core is changed.

External file: a JSON list of {"player", "season", "league", "team", "source", "url", "accessed_at",
"appearances", "goals", "assists", "minutes"} from FBref / Transfermarkt / ESPN / an official site.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2 import players as pl
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
FOCUS = {1496: "Raphinha", 386828: "Lamine Yamal", 1100: "E. Haaland", 184: "H. Kane"}
GOLDEN = (39, 140, 135, 78, 61)
PRODUCT_WINDOW = timedelta(days=400)


def _rows(conn: psycopg.Connection[Any], sql: str, params: Any = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def season_now(conn: psycopg.Connection[Any]) -> int:
    rows = _rows(conn, "SELECT cs.season FROM core.competition_seasons cs JOIN core.competitions c ON "
                       "c.id = cs.competition_id WHERE c.provider_league_id = 39 AND cs.is_current")
    return int(rows[0]["season"]) if rows else now().year


def sample_players(conn: psycopg.Connection[Any], season: int, per_league: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for league in GOLDEN:
        rows = _rows(conn, """
            SELECT DISTINCT ps.provider_player_id, COALESCE(p.name, ps.player_name) AS name
              FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
              LEFT JOIN core.players p ON p.provider_player_id = ps.provider_player_id
             WHERE c.provider_league_id = %s AND cs.season = %s AND ps.minutes > 0
             ORDER BY 1""", (league, season))
        rnd = random.Random(league * 7 + season)
        for r in rnd.sample(rows, min(per_league, len(rows))):
            out[int(r["provider_player_id"])] = str(r["name"])
    return out


def current_club(career: list[dict[str, Any]], national: set[int]) -> tuple[dict[str, Any] | None,
                                                                          dict[str, Any] | None]:
    """(club, national team) from /players/teams: the entry with the latest season of each kind."""
    best: dict[bool, tuple[int, dict[str, Any]]] = {}
    for item in career:
        team_raw = item.get("team")
        team: dict[str, Any] = team_raw if isinstance(team_raw, dict) else {}
        seasons = [s for s in item.get("seasons") or [] if isinstance(s, int)]
        tid = team.get("id")
        if not isinstance(tid, int) or not seasons:
            continue
        is_nat = tid in national
        if is_nat not in best or max(seasons) > best[is_nat][0]:
            best[is_nat] = (max(seasons), {"id": tid, "name": team.get("name"), "last_season": max(seasons)})
    return (best[False][1] if False in best else None), (best[True][1] if True in best else None)


async def audit_player(run: V2Run, conn: psycopg.Connection[Any], player: int, name: str, seasons: tuple[int, ...],
                       *, focus: bool, national: set[int], tracked: set[int],
                       migrated: set[tuple[int, int]]) -> tuple[dict[str, Any], list[Evidence]]:
    verdicts: list[pl.BlockVerdict] = []
    refs = []
    profile: dict[str, Any] = {}
    for season in seasons:
        answer = await run.get("/players", {"id": player, "season": season})
        prof, blocks = pl.api_blocks(answer.body) if answer else ({}, [])
        profile = profile or prof
        if answer:
            refs.append(answer.ref())
        ours = {(int(r["team"]), int(r["league"])): r for r in pl.our_blocks(conn, player, season)}
        api_by = {(b.team, b.league): b for b in blocks}
        for key in sorted(set(ours) | set(api_by)):
            v = pl.judge_block(api_by.get(key), ours.get(key))
            if v.verdict in ("ours_missing", "not_in_db"):
                v.gaps = pl.team_detail_gaps(conn, v.league, v.season, v.team)
            verdicts.append(pl.refine(v, tracked=tracked, migrated=migrated))
    club = nat = None
    extra: dict[str, Any] = {}
    if focus:
        career = await run.get("/players/teams", {"player": player})
        club, nat = current_club(career.items if career else [], national)
        squads = await run.get("/players/squads", {"player": player})
        extra["squads"] = [{"team": (i.get("team") or {}).get("id"), "name": (i.get("team") or {}).get("name")}
                           for i in (squads.items if squads else [])]
        injuries = await run.get("/injuries", {"player": player, "season": seasons[0]})
        ours_abs = _rows(conn, "SELECT count(*) AS n FROM core.player_absences WHERE provider_player_id = %s "
                               "AND fixture_id IN (SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs "
                               "ON cs.id = f.competition_season_id WHERE cs.season = %s)", (player, seasons[0]))
        extra["injuries"] = {"provider": len(injuries.items) if injuries else None, "ours": ours_abs[0]["n"]}
    product = pl.product_view(conn, player, run.at - PRODUCT_WINDOW)
    evidence = pl.player_evidence(player, name, verdicts, product, club, refs[0] if refs else None)
    row = {"player": player, "name": name, "focus": focus, "profile": {k: profile.get(k) for k in (
        "name", "firstname", "lastname", "age", "nationality", "height", "weight") if profile},
           "current_club": club, "national_team": nat,
           "last_appearance_team": {"name": product.get("team"), "is_national": product.get("team_is_national")},
           "product": product, "blocks": [v.__dict__ for v in verdicts], **extra}
    return row, evidence


def external_evidence(ext: list[dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                                                      list[Evidence]]:
    """An external source's season figures against the provider's block and our rows (tolerance 0;
    minutes within the slack)."""
    blocks = {(r["player"], b["season"], b["league"], b["team"]): b for r in rows for b in r["blocks"]}
    checks, out = [], []
    for e in ext:
        key = (int(e["player"]), int(e["season"]), int(e["league"]), int(e["team"]))
        b = blocks.get(key)
        api, ours = (b or {}).get("api") or {}, (b or {}).get("ours") or {}
        row: dict[str, Any] = {"key": key, "source": e.get("source"), "fields": {}}
        for f in ("appearances", "goals", "assists", "minutes"):
            if e.get(f) is None:
                continue
            slack = pl.MINUTES_SLACK if f == "minutes" else 0
            row["fields"][f] = {"external": e[f], "provider": api.get(f), "ours": ours.get(f),
                                "provider_ok": api.get(f) is not None and abs(int(api[f]) - int(e[f])) <= slack,
                                "ours_ok": ours.get(f) is not None and abs(int(ours[f]) - int(e[f])) <= slack}
        checks.append(row)
        bad_api = [f for f, x in row["fields"].items() if not x["provider_ok"]]
        if bad_api:
            out.append(Evidence(
                key=f"player_stats:{key[0]}:{key[2]}:{key[1]}:{key[3]}:external", area="player_stats",
                issue_type="PROVIDER_EXTERNAL_MISMATCH", severity="medium", at_fault="undetermined",
                entity=f"player {key[0]} league {key[2]} {key[1]}",
                claim=f"player {key[0]}: the provider differs from {e.get('source')} on {', '.join(bad_api)}",
                api={f: row["fields"][f]["provider"] for f in bad_api}, db={f: row["fields"][f]["ours"] for f in bad_api},
                external={**{k: e.get(k) for k in ("source", "url", "accessed_at")},
                          **{f: row["fields"][f]["external"] for f in bad_api}}))
    return checks, out


def markdown(rows: list[dict[str, Any]], codes: dict[str, str], requests: int,
             checks: list[dict[str, Any]]) -> str:
    lines = [f"# Player statistics truth audit - {len(rows)} players, {requests} requests", "",
             "| Player | Club (provider) | Shown team (last appearance) | Blocks ok / not | Product apps (bench rows) |",
             "|---|---|---|---|---|"]
    for r in rows:
        ok = sum(1 for b in r["blocks"] if b["verdict"] == "ok")
        bad = [f"{b['league_name']} {b['season']}: {b['verdict']}" for b in r["blocks"] if b["verdict"] != "ok"]
        club = (r.get("current_club") or {}).get("name", "-")
        shown = r["last_appearance_team"].get("name")
        lines.append(f"| {r['name']} ({r['player']}) | {club} | {shown} | {ok} / {len(bad)} {'; '.join(bad[:3])} | "
                     f"{r['product'].get('apps')} ({r['product'].get('bench_rows')}) |")
    if checks:
        lines += ["", "## External checks", ""]
        for c in checks:
            lines.append(f"* {c['key']} ({c['source']}): " + ", ".join(
                f"{f} ext {x['external']} / provider {x['provider']} / ours {x['ours']}" for f, x in c["fields"].items()))
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
            season = season_now(conn)
            seasons = (season, season - 1)
            focus = {p: FOCUS.get(p, str(p)) for p in args.player} if args.player else dict(FOCUS)
            sample = {} if args.player else sample_players(conn, season, args.per_league)
            national = {int(r["provider_team_id"]) for r in _rows(conn, "SELECT provider_team_id FROM core.teams "
                                                                        "WHERE is_national")}
            tracked = {int(r["provider_league_id"]) for r in _rows(conn, "SELECT provider_league_id FROM "
                                                                         "core.competitions WHERE is_tracked")}
            migrated = {(int(r["provider_league_id"]), int(r["season"])) for r in _rows(conn, """
                SELECT c.provider_league_id, cs.season FROM core.competition_seasons cs
                  JOIN core.competitions c ON c.id = cs.competition_id
                 WHERE EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = cs.id)""")}
            run = V2Run(conn, client, "player_stats", at, params={"focus": list(focus), "sample": len(sample),
                                                                  "seasons": list(seasons)})
            rows: list[dict[str, Any]] = []
            evidence: list[Evidence] = []
            try:
                for pid, name in [*focus.items(), *[(p, n) for p, n in sample.items() if p not in focus]]:
                    row, found = await audit_player(run, conn, pid, name, seasons, focus=pid in focus,
                                                    national=national, tracked=tracked, migrated=migrated)
                    rows.append(row)
                    evidence += found
            except BaseException:
                run.finish({"error": "interrupted or failed", "done": len(rows)}, failed=True)
                raise
            evidence += pl.product_evidence(rows) + pl.summary_evidence(rows)
            checks: list[dict[str, Any]] = []
            if args.external:
                checks, ext_ev = external_evidence(json.loads(Path(args.external).read_text()), rows)
                evidence += ext_ev
            codes = record_all(conn, evidence, at=at, run_id=run.run_id)
            if not args.player and not run.stopped:
                clear_unseen(conn, area="player_stats", scope_prefix="player_stats:", seen=codes.keys(), at=at)
            verdicts: dict[str, int] = {}
            for r in rows:
                for b in r["blocks"]:
                    verdicts[b["verdict"]] = verdicts.get(b["verdict"], 0) + 1
            summary = {"players": len(rows), "block_verdicts": verdicts, "requests": run.requests,
                       "stopped": run.stopped, "failures": run.failures[:20], "evidence": codes,
                       "external_checks": len(checks)}
            folder = write_report(REPORTS, "player_stats", at, {**summary, "players_detail": rows, "checks": checks},
                                  markdown(rows, codes, run.requests, checks))
            status = run.finish(summary, report_dir=folder)
    finally:
        await client.aclose()
    print(json.dumps({"status": status, "players": len(rows), "block_verdicts": verdicts, "requests": run.requests,
                      "evidence": len(codes), "report": str(folder)}, indent=1, default=str))
    return 0 if status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_player_stats", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--player", type=int, action="append", help="provider player id (repeatable)")
    parser.add_argument("--per-league", type=int, default=20)
    parser.add_argument("--external", help="external season figures to compare (JSON)")
    parser.add_argument("--max-requests", type=int, default=500)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())

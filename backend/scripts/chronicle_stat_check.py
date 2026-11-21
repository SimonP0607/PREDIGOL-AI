"""PM-11-07 (IA-158): does the chronicle tell the figure the profile shows? The owner's read-only command.

    python -m scripts.chronicle_stat_check check [--sample 500] [--days 30]   # the C-13 sheet against the profile, match by match
    python -m scripts.chronicle_stat_check today [--days 14] [--limit 500]    # the chronicles already stored against the profile

Inside the worker's container (``docker exec predigol-worker python -m scripts.chronicle_stat_check ...``). Reads only (a read-only
transaction, 90 s per statement); calls no model and no provider; writes nothing.

``check`` takes the last ``--sample`` matches (kick-off in the last ``--days`` days or the next two) whose competition season has statistics
documents, builds each side's ``xg`` fact as the content plan builds it with ``FBI_CHRONICLE_STAT_SHEET`` on (``fbi.chronicle.stat_sheet``
and ``fbi.chronicle.plan.sheet_facts``) and compares it with what the team's statistics page serves (``fbi.api.services.stats_profile``:
the match's competition season, ``u10`` and ``all``, ``season`` when there is no ``u10`` - the web's own fallback). Acceptance: 0
differences. Exit code 1 when there is one.

``today`` reads the plans of the chronicles stored in the last ``--days`` days (``ai.chronicles``, switch off: the packet's figures) and
compares their ``xg`` and the form's goals per match with the profile, only where the statistics document was computed before the plan
(the document in force when the chronicle was written). It documents the differences of today; it never fails.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

SAMPLE_SQL = """
SELECT f.id, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name, f.competition_season_id
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
   AND EXISTS (SELECT 1 FROM analytics.stat_documents d WHERE d.kind = 'league' AND d.entity_id = f.competition_season_id
                AND d.competition_season_id = f.competition_season_id AND d.scope = 'season' AND d.context = 'all')
 ORDER BY f.kickoff_at DESC, f.id DESC
 LIMIT %(n)s
"""

STORED_SQL = """
SELECT DISTINCT ON (c.fixture_id) c.id, c.fixture_id, c.plan_at, c.plan, c.content, c.status, f.home_team_id, f.away_team_id,
       f.competition_season_id
  FROM ai.chronicles c JOIN core.fixtures f ON f.id = c.fixture_id
 WHERE c.created_at > %(since)s AND c.version = 'chronicle-v4'
 ORDER BY c.fixture_id, c.id DESC
 LIMIT %(n)s
"""


def profile_of(conn: Any, team_id: int, cs: int) -> tuple[dict[str, float], datetime | None, str | None]:
    """The values the team's statistics page shows in that competition season (u10, else season), its date and scope."""
    from fbi.api.contracts.intelligence.base import Missing
    from fbi.api.problem import ApiError
    from fbi.api.services import stats_profile

    for scope in ("u10", "season"):
        try:
            e = stats_profile.entity(conn, "equipo", team_id, role="perfil", season=cs, scope=scope, context="all")  # type: ignore[arg-type]
        except ApiError:
            continue
        if e.team is None or isinstance(e.team, Missing):
            return {}, None, None
        values = {f.key: float(f.value) for f in e.team.figures if not isinstance(f.value, Missing)}
        return values, e.computed_at, scope
    return {}, None, None


def _connect() -> Any:
    import psycopg

    from fbi.core.config import settings

    conn = psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="chronicle_stat_check")
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("SET statement_timeout = '90s'")
    return conn


def check(conn: Any, *, sample: int, days: int, at: datetime) -> dict[str, Any]:
    from psycopg.rows import dict_row

    from fbi.chronicle import plan as cp
    from fbi.chronicle import stat_sheet

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SAMPLE_SQL, {"since": at - timedelta(days=days), "until": at + timedelta(days=2), "n": sample})
        matches = cur.fetchall()
    told = silent = 0
    found: list[dict[str, Any]] = []
    for m in matches:
        sheet = stat_sheet.read(conn, int(m["id"]), home_id=int(m["home_team_id"]), away_id=int(m["away_team_id"]))
        latest = max((s.computed_at for s in sheet.values()), default=at)
        # the plan's moment: when the documents are in force (a check run before the night's pass reads the documents it finds)
        inp = cp.PlanInput(fixture_id=int(m["id"]), at=max(at, latest), home=str(m["home_name"]), away=str(m["away_name"]),
                           competition="", sheet=sheet)
        facts, _ = cp.sheet_facts(inp, set())
        profile = {side: profile_of(conn, int(m[f"{side}_team_id"]), int(m["competition_season_id"]))[0] for side in ("home", "away")}
        told += len(facts)
        silent += sum(1 for side in ("home", "away") if not any(f.side == side for f in facts))
        found += [d.as_json() for d in stat_sheet.differences(int(m["id"]), facts, profile)]
    return {"command": "check", "version": stat_sheet.VERSION, "matches": len(matches), "xg_facts": told, "sides_without_xg": silent,
            "differences": len(found), "examples": found[:20]}


def _facts(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [f for f in plan.get("facts") or [] if isinstance(f, Mapping)]


def _cited(content: Mapping[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for sections in (content or {}).get("es", {}).values() if isinstance(content, Mapping) else []:
        for s in sections or []:
            out |= {str(i) for i in s.get("facts") or []}
    return out


def today(conn: Any, *, days: int, limit: int, at: datetime) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STORED_SQL, {"since": at - timedelta(days=days), "n": limit})
        stored = cur.fetchall()
    compared = with_xg = 0
    counts = {"xg_distinta": 0, "xg_igual": 0, "xg_sin_perfil": 0, "goles_distinta": 0, "goles_igual": 0,
              "goles_sin_perfil": 0, "escrita_en_texto": 0}
    examples: list[dict[str, Any]] = []
    for r in stored:
        plan = r["plan"] if isinstance(r["plan"], Mapping) else {}
        cited = _cited(r["content"])
        for f in _facts(plan):
            if f.get("kind") not in ("xg", "form") or f.get("side") not in ("home", "away"):
                continue
            side, params = str(f["side"]), f.get("params") or {}
            values, computed_at, scope = profile_of(conn, int(r[f"{side}_team_id"]), int(r["competition_season_id"]))
            if computed_at is None or computed_at > r["plan_at"]:
                continue  # no document, or one computed after the chronicle: not the figure the reader saw beside it
            compared += 1
            pairs = (("xg_for", "xg_for"), ("xg_against", "xg_against")) if f["kind"] == "xg" else (("goals_for", "goals_for"),
                                                                                                     ("goals_against", "goals_against"))
            for told_key, c13_key in pairs:
                told = params.get(told_key)
                if not isinstance(told, (int, float)):
                    continue
                shown = values.get(c13_key)
                label = "xg" if f["kind"] == "xg" else "goles"
                with_xg += f["kind"] == "xg"
                if shown is None:
                    counts[f"{label}_sin_perfil"] += 1
                    continue
                same = round(float(told), 1) == round(shown, 1)
                counts[f"{label}_{'igual' if same else 'distinta'}"] += 1
                if not same and len(examples) < 25:
                    examples.append({"fixture_id": int(r["fixture_id"]), "side": side, "key": told_key, "chronicle": told,
                                     "profile": round(shown, 3), "profile_scope": scope, "chronicle_n": params.get("n"),
                                     "in_text": str(f.get("id")) in cited, "plan_at": r["plan_at"].isoformat()})
            if str(f.get("id")) in cited:
                counts["escrita_en_texto"] += 1
    return {"command": "today", "chronicles": len(stored), "facts_compared": compared, "figures_xg": with_xg, **counts,
            "rule": "igual = la misma cifra con un decimal (como se lee); el perfil: temporada de la competición del partido, u10/all",
            "examples": examples}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--sample", type=int, default=500)
    c.add_argument("--days", type=int, default=30)
    t = sub.add_parser("today")
    t.add_argument("--days", type=int, default=14)
    t.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    from fbi.core.clock import now

    with _connect() as conn:
        if args.command == "check":
            out = check(conn, sample=args.sample, days=args.days, at=now())
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            return 1 if out["differences"] else 0
        print(json.dumps(today(conn, days=args.days, limit=args.limit, at=now()), ensure_ascii=False, indent=2, default=str))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

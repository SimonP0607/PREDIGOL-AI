"""Competition phases audit: every stored table mapped to the stage it ranks, and the table each match is shown with.

    python -m scripts.audit_competition_phases                      # every current season with a stored table
    python -m scripts.audit_competition_phases --all                # every season with a stored table
    python -m scripts.audit_competition_phases --league 239 --league 128 [--season 2026]
    python -m scripts.audit_competition_phases --golden config/truth/phase_golden.json

A league + season is not one table. For each season the newest snapshot's tables are mapped
(``fbi.competitions.phases``): label, rows, the stage each ranks, its kind (full, group, ranking,
aggregate, other), how the stage was found (label, games, single, unmapped) and the agreement of its
games played with the stage's finished matches.

Then every fixture of the season is checked twice:

* the table the Match Center shows now (``SeasonTables.for_match``) must rank the match's stage (or,
  for a knock-out round, its phase's league stage / the league stage before it), must never be a
  ranking or an aggregate, and must be one table when one table holds both teams - a failure is an
  OPEN PrediGol bug (``phases:<league>:<season>:current``);
* the query the Match Center used until 4 Oct 2026 (each team's newest row across ALL the season's
  tables, ``DISTINCT ON (team)``) is replayed: a fixture whose rows it took from another table than
  the match's stage's is the P0 bug's footprint, recorded FIXED with the fix and its tests
  (``phases:<league>:<season>:match_center_mixed``).

Golden file (``config/truth/phase_golden.json``): the expected stage and kind of named tables, and
the table of each side for named fixtures; any difference fails the run (exit 1).

Writes audit.truth_v2_runs (kind phases), the evidence ledger (area phases) and
data/truth/<stamp>-phases/. 0 provider requests. Nothing in core is changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.competitions.phases import VERSION, TableMap, is_split, stage_of
from fbi.competitions.tables import SeasonTables, load_season
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
FIX = ("4 Oct 2026 (be-51): the Match Center reads the table that ranks the match's stage "
       "(fbi.competitions.tables.match_tables); the competition page keeps each table apart")
TESTS = "tests/unit/test_competition_phases.py, tests/integration/test_competition_phases_db.py"

SCOPE_SQL = """
SELECT cs.id AS cs_id, c.id AS competition_id, c.provider_league_id AS league, c.name, c.country, cs.season,
       cs.is_current
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
 WHERE EXISTS (SELECT 1 FROM core.standings s WHERE s.competition_season_id = cs.id) AND ({where})
 ORDER BY c.provider_league_id, cs.season
"""

FIXTURES_SQL = """
SELECT f.id, f.provider_fixture_id, f.round, f.kickoff_at, f.status_group, f.home_team_id, f.away_team_id,
       th.name AS home, ta.name AS away
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.competition_season_id = %(cs)s
"""

OLD_MATCH_CENTER_SQL = """
WITH fx AS (SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id FROM core.fixtures f
             WHERE f.competition_season_id = %(cs)s),
pick AS (
    SELECT DISTINCT ON (fx.id, s.team_id) fx.id AS fixture_id, s.team_id, s.snapshot_at, s.group_key
      FROM fx JOIN core.standings s
        ON s.competition_season_id = %(cs)s AND s.team_id IN (fx.home_team_id, fx.away_team_id)
     ORDER BY fx.id, s.team_id, (s.snapshot_at <= fx.kickoff_at) DESC,
              CASE WHEN s.snapshot_at <= fx.kickoff_at THEN s.snapshot_at END DESC NULLS LAST, s.snapshot_at
)
SELECT p.fixture_id, p.team_id, p.snapshot_at, p.group_key,
       (SELECT count(*) FROM core.standings x WHERE x.competition_season_id = %(cs)s AND x.team_id = p.team_id
           AND x.snapshot_at = p.snapshot_at) AS team_tables
  FROM pick p
"""
"""The Match Center's standings query until 4 Oct 2026, for every fixture of a season at once. Where
a team has rows in several tables of the snapshot it read, the row it returned depended on row order."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def table_line(m: TableMap) -> dict[str, Any]:
    return {"key": m.key, "label": m.label, "rows": m.rows, "stage": m.stage, "stages": list(m.stages),
            "phase": m.phase, "kind": m.kind, "method": m.method, "agreement": f"{m.agree}/{m.counted}",
            "note": m.note}


def allowed(st: SeasonTables, fixture_round: str | None, chosen_stage: str) -> bool:
    """The stage of the table shown is the match's own, or (knock-out round) a league stage that may
    stand for it: its phase's, or in a single-phase season any earlier one."""
    own = stage_of(fixture_round)
    if chosen_stage == own:
        return True
    stage = next((s for s in st.season.stages if s.name == chosen_stage), None)
    me = next((s for s in st.season.stages if s.name == own), None)
    if stage is None or stage.kind != "league" or (me is not None and me.kind == "league"):
        return False
    return stage.phase == (me.phase if me else own.split(" - ")[0]) or not is_split(st.season.stages)


def audit_season(conn: psycopg.Connection[Any], row: dict[str, Any], golden: dict[str, Any] | None) -> dict[str, Any]:
    season = load_season(conn, int(row["cs_id"]))
    st = SeasonTables(conn, season)
    newest = st.times[-1]
    maps = st.maps(newest)
    out: dict[str, Any] = {
        "league": row["league"], "season": row["season"], "name": row["name"], "country": row["country"],
        "cs_id": row["cs_id"], "is_current": row["is_current"], "snapshot_at": newest, "snapshots": len(st.times),
        "split": is_split(season.stages),
        "stages": [{"name": s.name, "phase": s.phase, "kind": s.kind, "fixtures": s.fixtures, "finished": s.finished,
                    "first": s.first_kickoff, "last": s.last_kickoff,
                    "tables": sum(1 for m in maps if m.stage == s.name)} for s in season.stages],
        "tables": [table_line(m) for m in maps],
    }
    out["stage_without_table"] = [
        s.name for s in season.stages
        if s.kind == "league" and s.finished > 0 and s.first_kickoff is not None and s.first_kickoff < newest
        and not any(m.stage == s.name or s.name in m.stages for m in maps)]
    old: dict[tuple[int, int], dict[str, Any]] = {(int(r["fixture_id"]), int(r["team_id"])): r
                                                  for r in _rows(conn, OLD_MATCH_CENTER_SQL, {"cs": season.cs_id})}
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    current_bad: list[dict[str, Any]] = []
    for f in _rows(conn, FIXTURES_SQL, {"cs": season.cs_id}):
        counts["fixtures"] += 1
        sides = (int(f["home_team_id"]), int(f["away_team_id"]))
        found = st.for_match(f["round"], f["kickoff_at"], *sides)
        new_keys = dict(found.choice.keys) if found else {}
        if found is not None:
            counts["shown_with_table"] += 1
            counts[f"reason:{found.choice.reason}"] += 1
            for team, key in new_keys.items():
                m = found.maps[key]
                if m.kind not in ("full", "group") or not m.stage or not allowed(st, f["round"], m.stage):
                    current_bad.append({"fixture": f["provider_fixture_id"], "team": team, "key": key,
                                        "kind": m.kind, "stage": m.stage, "round": f["round"]})
            if len(set(new_keys.values())) > 1 and any(
                    all(t in m.teams for t in sides) and m.stage == found.choice.stage and m.kind in ("full", "group")
                    for m in found.maps.values()):
                current_bad.append({"fixture": f["provider_fixture_id"], "split_although_one_table_holds_both": True})
        olds = {t: old.get((int(f["id"]), t)) for t in sides}
        if not any(olds.values()):
            continue
        counts["old_with_rows"] += 1
        if any(o and int(o["team_tables"]) > 1 for o in olds.values()):
            counts["old_order_dependent"] += 1
        old_keys = {t: str(o["group_key"]) for t, o in olds.items() if o}
        wrong = {t: k for t, k in old_keys.items() if new_keys.get(t) != k}
        if wrong:
            counts["old_wrong_table"] += 1
            if len(set(old_keys.values())) > 1:
                counts["old_two_tables"] += 1
            if f["status_group"] in ("scheduled", "live"):
                counts["old_wrong_table_upcoming"] += 1
            if len(examples) < 8:
                examples.append({"fixture": f["provider_fixture_id"], "match": f"{f['home']} v {f['away']}",
                                 "round": f["round"], "kickoff": f["kickoff_at"],
                                 "old": [old_keys.get(t) for t in sides], "new": [new_keys.get(t) for t in sides]})
    out["fixtures"] = dict(counts)
    out["examples"] = examples
    out["current_bad"] = current_bad
    out["golden"] = check_golden(st, maps, golden) if golden else None
    return out


def check_golden(st: SeasonTables, maps: list[TableMap], golden: dict[str, Any]) -> dict[str, Any]:
    by_label = {m.label: m for m in maps}
    diffs: list[str] = []
    checked = 0
    for label, want in (golden.get("tables") or {}).items():
        checked += 1
        m = by_label.get(label)
        if m is None:
            diffs.append(f"table {label!r} not in the newest snapshot")
            continue
        got = {"stage": m.stage, "kind": m.kind}
        for k, v in want.items():
            if got.get(k) != v:
                diffs.append(f"table {label!r}: {k} {got.get(k)!r}, expected {v!r}")
    fixtures = {int(r["provider_fixture_id"]): r for r in _rows(st.conn, FIXTURES_SQL, {"cs": st.season.cs_id})}
    for g in golden.get("fixtures") or []:
        checked += 1
        f = fixtures.get(int(g["fixture"]))
        if f is None:
            diffs.append(f"fixture {g['fixture']} not stored in this season")
            continue
        found = st.for_match(f["round"], f["kickoff_at"], int(f["home_team_id"]), int(f["away_team_id"]))
        got_tables = [None, None] if found is None else [
            found.maps[found.choice.keys[t]].label if t in found.choice.keys else None
            for t in (int(f["home_team_id"]), int(f["away_team_id"]))]
        if got_tables != g["tables"]:
            diffs.append(f"fixture {g['fixture']} ({f['home']} v {f['away']}, {f['round']}): tables {got_tables}, "
                         f"expected {g['tables']}")
    return {"checked": checked, "differences": diffs, "verdict": "PASS" if not diffs else "FAIL"}


def evidence(s: dict[str, Any]) -> list[Evidence]:
    label = f"{s['name']} {s['season']} ({s['league']})"
    key = f"phases:{s['league']}:{s['season']}"
    fx = s["fixtures"]
    out: list[Evidence] = []
    if fx.get("old_wrong_table"):
        out.append(Evidence(
            key=f"{key}:match_center_mixed", area="phases", issue_type="PHASE_TABLE_MIXED", severity="high",
            at_fault="predigol", entity=label, status="FIXED", fix=FIX, test=TESTS,
            claim=f"{label}: until 4 Oct 2026 the Match Center showed {fx['old_wrong_table']} of {fx['fixtures']} "
                  f"matches with a row from another table than the match's stage's ({fx.get('old_two_tables', 0)} "
                  f"with the two teams' rows from two different tables; {fx.get('old_wrong_table_upcoming', 0)} "
                  "of them still to be played)",
            db={"examples": s["examples"], "tables": s["tables"], "snapshot_at": s["snapshot_at"]},
            root_cause="NORMALIZER_BUG in the read path: SELECT DISTINCT ON (team_id) over every table of the "
                       "season (core.standings keeps each table apart since 0048; the query did not)"))
    if s["current_bad"]:
        out.append(Evidence(
            key=f"{key}:current", area="phases", issue_type="PHASE_TABLE_MIXED", severity="critical",
            at_fault="predigol", entity=label,
            claim=f"{label}: the Match Center now shows {len(s['current_bad'])} match side(s) with a table that does "
                  "not rank the match's stage",
            db={"cases": s["current_bad"][:20]}))
    has_fixtures = any(st["fixtures"] for st in s["stages"])
    for t in s["tables"]:
        if t["method"] == "unmapped" and has_fixtures and len(s["tables"]) > 1:
            out.append(Evidence(
                key=f"{key}:unmapped:{t['key']}", area="phases", issue_type="PHASE_TABLE_UNMAPPED", severity="info",
                at_fault="none", entity=label, status="MONITOR",
                claim=f"{label}: the table {t['label']!r} ({t['rows']} teams) ranks no stage the round labels name "
                      "(a period or special table): shown on the competition page, never for a match",
                db={"table": t, "stages": [x["name"] for x in s["stages"]]}))
    for stage in s["stage_without_table"]:
        if len(s["tables"]) and any(t["stage"] for t in s["tables"]):
            out.append(Evidence(
                key=f"{key}:no_table:{stage}", area="phases", issue_type="PROVIDER_COVERAGE", severity="low",
                at_fault="provider", entity=label, status="MONITOR",
                claim=f"{label}: the stage {stage!r} has finished matches but the provider's newest table answer "
                      "holds no table for it (its other stages have one): its matches are shown without a table",
                db={"tables": [t["label"] for t in s["tables"]], "snapshot_at": s["snapshot_at"]}))
    g = s.get("golden")
    if g and g["differences"]:
        out.append(Evidence(
            key=f"{key}:golden", area="phases", issue_type="MAPPING_ERROR", severity="high", at_fault="predigol",
            entity=label, claim=f"{label}: {len(g['differences'])} golden expectation(s) not met",
            db={"differences": g["differences"]}))
    return out


def markdown(seasons: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = ["# Competition phases audit", "",
             f"Mapping version `{VERSION}`; {summary['seasons']} seasons, {summary['tables']} tables. "
             "Old = the Match Center query until 4 Oct 2026 (each team's newest row across all tables).", "",
             "| Competition | Season | Tables (label -> stage, kind, how, agreement) | Fixtures | Old wrong table "
             "(two tables / upcoming) | Now wrong | Golden |",
             "|---|---|---|---:|---|---:|---|"]
    for s in seasons:
        tables = "<br>".join(f"{t['label'] or '(no label)'} -> {t['stage'] or '+'.join(t['stages']) or '-'}, "
                             f"{t['kind']}, {t['method']}, {t['agreement']}" for t in s["tables"])
        fx = s["fixtures"]
        g = s.get("golden")
        lines.append(f"| {s['name']} ({s['league']}) | {s['season']} | {tables} | {fx.get('fixtures', 0)} | "
                     f"{fx.get('old_wrong_table', 0)} ({fx.get('old_two_tables', 0)} / "
                     f"{fx.get('old_wrong_table_upcoming', 0)}) | {len(s['current_bad'])} | "
                     f"{g['verdict'] if g else ''} |")
    examples = [(s, e) for s in seasons for e in s["examples"][:2]]
    if examples:
        lines += ["", "## Examples of the old query's rows", "",
                  "| Competition | Match | Round | Old tables (home, away) | Now |", "|---|---|---|---|---|"]
        for s, e in examples[:40]:
            lines.append(f"| {s['name']} {s['season']} | {e['match']} | {e['round']} | {e['old']} | {e['new']} |")
    golden = [s for s in seasons if s.get("golden") and s["golden"]["differences"]]
    if golden:
        lines += ["", "## Golden differences", ""]
        for s in golden:
            lines += [f"* {s['name']} {s['season']}: {d}" for d in s["golden"]["differences"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", type=int, action="append", default=[])
    ap.add_argument("--season", type=int)
    ap.add_argument("--all", action="store_true", help="every season with a stored table, not only current ones")
    ap.add_argument("--golden", help="expected mappings (config/truth/phase_golden.json); its seasons are audited")
    args = ap.parse_args(argv)
    golden_all: dict[tuple[int, int], dict[str, Any]] = {}
    if args.golden:
        for g in json.loads(Path(args.golden).read_text())["seasons"]:
            golden_all[(int(g["league"]), int(g["season"]))] = g
    at = now()
    conds, params = [], {}
    if args.league:
        conds.append("c.provider_league_id = ANY(%(leagues)s)")
        params["leagues"] = args.league
    if args.season:
        conds.append("cs.season = %(season)s")
        params["season"] = args.season
    if golden_all and not args.league:
        conds = ["(c.provider_league_id, cs.season) IN (" + ", ".join(f"({lg}, {sn})" for lg, sn in golden_all) + ")"]
    elif not args.all and not args.season:
        conds.append("cs.is_current")
    where = " AND ".join(conds) or "true"
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '300s'")
        run = V2Run(conn, None, "phases", at, params={"where": where, "golden": args.golden, "version": VERSION})
        seasons = []
        failed = False
        for row in _rows(conn, SCOPE_SQL.format(where=where), params):
            try:
                seasons.append(audit_season(conn, row, golden_all.get((int(row["league"]), int(row["season"])))))
            except Exception as exc:  # one season must not stop the others; the run is then partial
                run.failures.append(f"{row['name']} {row['season']}: {exc!r}"[:300])
        items = [ev for s in seasons for ev in evidence(s)]
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        for s in seasons:
            clear_unseen(conn, area="phases", scope_prefix=f"phases:{s['league']}:{s['season']}:",
                         seen=[ev.key for ev in items], at=at)
        golden_failed = [s for s in seasons if s.get("golden") and s["golden"]["differences"]]
        now_wrong = sum(len(s["current_bad"]) for s in seasons)
        summary = {
            "version": VERSION, "seasons": len(seasons), "tables": sum(len(s["tables"]) for s in seasons),
            "kinds": dict(Counter(t["kind"] for s in seasons for t in s["tables"])),
            "methods": dict(Counter(t["method"] for s in seasons for t in s["tables"])),
            "fixtures": sum(s["fixtures"].get("fixtures", 0) for s in seasons),
            "old_wrong_table": sum(s["fixtures"].get("old_wrong_table", 0) for s in seasons),
            "old_two_tables": sum(s["fixtures"].get("old_two_tables", 0) for s in seasons),
            "old_wrong_table_upcoming": sum(s["fixtures"].get("old_wrong_table_upcoming", 0) for s in seasons),
            "seasons_with_old_wrong_table": sum(1 for s in seasons if s["fixtures"].get("old_wrong_table")),
            "now_wrong": now_wrong,
            "stage_without_table": sum(len(s["stage_without_table"]) for s in seasons),
            "golden": {"seasons": sum(1 for s in seasons if s.get("golden")), "failed": len(golden_failed),
                       "checked": sum(s["golden"]["checked"] for s in seasons if s.get("golden"))},
            "evidence": len(codes), "failures": run.failures,
        }
        folder = write_report(REPORTS, "phases", at, {"summary": summary, "seasons": seasons}, markdown(seasons, summary))
        failed = bool(golden_failed) or now_wrong > 0
        status = run.finish(summary, report_dir=folder, failed=False)
    print(json.dumps({**summary, "report": str(folder), "status": status}, indent=1, default=str))
    return 1 if failed or status != "completed" else 0


if __name__ == "__main__":
    sys.exit(main())

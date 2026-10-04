"""Fixtures and results truth: every tracked current season's full list, plus a sample by status.

* ``/fixtures?league&season`` for every tracked current season: every fixture the provider lists
  against ours (identity, kick-off, status, round, venue, score) - the automated validation;
* ``/fixtures?ids`` for a sample drawn per status (FT, AET, PEN, NS, TBD, PST, CANC, ABD, AWD,
  WO, SUSP, INT) and for the suspicious: scheduled matches whose kick-off is hours past, live
  matches that should have ended.

Comparison reuses ``fbi.truth.compare`` (the GATE A rules); findings are grouped into one ledger
entry per field and kind, with examples - never one entry per fixture.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth import compare
from fbi.truth.audit import db_fixtures, db_season_fixtures
from fbi.truth.findings import SEVERITY_ORDER, Finding, Kind, Severity, Tally
from fbi.truth.v2.ledger import Evidence
from fbi.truth.v2.runner import V2Run

STATUSES = ("FT", "AET", "PEN", "NS", "TBD", "PST", "CANC", "ABD", "AWD", "WO", "SUSP", "INT")
PER_STATUS = 20
STALE_SCHEDULED_AFTER = timedelta(hours=6)
LIVE_TOO_LONG = timedelta(hours=4)
MAX_IDS = 20


def current_seasons(conn: psycopg.Connection[Any]) -> list[tuple[int, int, str]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT c.provider_league_id, cs.season, c.name FROM core.competition_seasons cs "
                    "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.is_tracked AND cs.is_current "
                    "ORDER BY c.provider_league_id")
        return [(int(r["provider_league_id"]), int(r["season"]), str(r["name"])) for r in cur.fetchall()]


def sample_ids(conn: psycopg.Connection[Any], *, at: datetime, seed: float = 0.42) -> dict[str, list[int]]:
    """Provider fixture ids per stratum (status, plus stale_scheduled and live_too_long)."""
    out: dict[str, list[int]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (seed,))
        for status in STATUSES:
            window = ("AND f.kickoff_at BETWEEN %(at)s - interval '2 days' AND %(at)s + interval '7 days'"
                      if status in ("NS", "TBD") else "")
            cur.execute(f"SELECT f.provider_fixture_id FROM core.fixtures f WHERE f.status_short = %(s)s {window} "
                        "ORDER BY random() LIMIT %(n)s", {"s": status, "n": PER_STATUS, "at": at})
            out[status] = [int(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT f.provider_fixture_id FROM core.fixtures f WHERE f.status_group = 'scheduled' "
                    "AND f.kickoff_at < %(at)s - %(stale)s AND f.kickoff_at > %(at)s - interval '30 days' "
                    "ORDER BY random() LIMIT 60", {"at": at, "stale": STALE_SCHEDULED_AFTER})
        out["stale_scheduled"] = [int(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT f.provider_fixture_id FROM core.fixtures f WHERE f.status_group = 'live' "
                    "AND f.kickoff_at < %(at)s - %(long)s ORDER BY random() LIMIT 40",
                    {"at": at, "long": LIVE_TOO_LONG})
        out["live_too_long"] = [int(r[0]) for r in cur.fetchall()]
    return out


async def run_lists(run: V2Run, conn: psycopg.Connection[Any], seasons: Sequence[tuple[int, int, str]],
                    fixtures: Tally, results: Tally) -> dict[str, int]:
    totals = {"seasons": 0, "api": 0, "db": 0}
    for league, season, _name in seasons:
        answer = await run.get("/fixtures", {"league": league, "season": season})
        if answer is None:
            continue
        ours = db_season_fixtures(conn, league, season)
        totals["seasons"] += 1
        totals["api"] += len(answer.items)
        totals["db"] += len(ours)
        seen = set()
        for item in answer.items:
            pid = compare._id(item.get("fixture"))
            if pid is None:
                continue
            seen.add(pid)
            compare.compare_fixture(item, ours.get(pid), now=run.at, tally=fixtures, results=results)
        for pid, row in ours.items():
            if pid not in seen:
                fixtures.compared()
                fixtures.add(Finding.of("fixtures", f"fixture {pid} ({league}/{season})", "fixture",
                                        Kind.MISSING_IN_API, Severity.MEDIUM,
                                        db=f"{row['status_short']} {row['kickoff_at']:%Y-%m-%d %H:%M}Z",
                                        note="we hold a fixture the provider no longer lists for this season"))
    return totals


async def run_sample(run: V2Run, conn: psycopg.Connection[Any], strata: Mapping[str, Sequence[int]],
                     fixtures: Tally, results: Tally) -> dict[str, dict[str, int]]:
    """Each stratum's fixtures by id; per stratum how many were compared and how many disagreed."""
    per: dict[str, dict[str, int]] = {}
    for stratum, ids in strata.items():
        before_f, before_r = fixtures.total_findings, results.total_findings
        asked = 0
        for start in range(0, len(ids), MAX_IDS):
            batch = list(ids[start:start + MAX_IDS])
            answer = await run.get("/fixtures", {"ids": "-".join(str(i) for i in batch)})
            if answer is None:
                continue
            ours = db_fixtures(conn, batch)
            for item in answer.items:
                pid = compare._id(item.get("fixture"))
                if pid is None:
                    continue
                asked += 1
                compare.compare_fixture(item, ours.get(pid), now=run.at, tally=fixtures, results=results)
        per[stratum] = {"fixtures": asked, "findings": (fixtures.total_findings - before_f)
                        + (results.total_findings - before_r)}
    return per


ISSUE = {
    ("fixtures", "fixture", "missing_in_db"): ("MISSING_BACKFILL", "predigol"),
    ("fixtures", "fixture", "missing_in_api"): ("STALE_ENTITY", "predigol"),
    ("fixtures", "status_short", "stale"): ("STALE_ENTITY", "predigol"),
    ("fixtures", "status_short", "provider_lag"): ("PROVIDER_STALE", "provider"),
    ("fixtures", "status_short", "mismatch"): ("FIXTURE_MISMATCH", "undetermined"),
    ("fixtures", "status_group", "inconsistent"): ("NORMALIZER_BUG", "predigol"),
    ("fixtures", "kickoff_at", "stale"): ("STALE_ENTITY", "predigol"),
    ("fixtures", "kickoff_at", "mismatch"): ("FIXTURE_MISMATCH", "undetermined"),
    ("fixtures", "teams", "mismatch"): ("FIXTURE_MISMATCH", "undetermined"),
    ("fixtures", "competition", "mismatch"): ("SEASON_MISMATCH", "predigol"),
    ("fixtures", "round", "mismatch"): ("FIXTURE_MISMATCH", "undetermined"),
    ("fixtures", "venue", "mismatch"): ("FIXTURE_MISMATCH", "undetermined"),
}


def evidence(fixtures: Tally, results: Tally, api_note: Mapping[str, Any]) -> list[Evidence]:
    groups: dict[tuple[str, str, str], list[Finding]] = {}
    for t in (fixtures, results):
        for f in t.findings:
            groups.setdefault((f.dataset, f.field.split(" ")[0], f.kind.value), []).append(f)
    out = []
    for (dataset, fld, kind), items in sorted(groups.items()):
        issue, fault = ISSUE.get((dataset, fld, kind), ("RESULT_MISMATCH" if dataset == "results"
                                                        else "FIXTURE_MISMATCH", "undetermined"))
        worst = min(items, key=lambda f: SEVERITY_ORDER[f.severity]).severity.value
        ex = [{"entity": f.entity, "field": f.field, "api": f.api, "db": f.db, "note": f.note} for f in items[:8]]
        out.append(Evidence(key=f"fixtures:{dataset}:{fld}:{kind}", area="fixtures", issue_type=issue,
                            severity=worst, at_fault=fault, entity=f"{len(items)} fixtures",
                            claim=f"{len(items)} {dataset} findings on {fld} ({kind})",
                            api={**dict(api_note), "examples": ex}))
    return out

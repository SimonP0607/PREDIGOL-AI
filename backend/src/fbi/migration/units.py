"""Turn a priced plan into resumable units, and report how the migration is going."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.core.version import code_version
from fbi.ingestion.backfill import KIND_ORDER, add_unit, expand_detail_batches
from fbi.migration.planner import MigrationPlan

ENDPOINTS = {
    "league_coverage": "/leagues",
    "fixtures_season": "/fixtures",
    "standings_season": "/standings",
    "injuries_season": "/injuries",
    "teams_season": "/teams",
    "players_season": "/players",
}


def priority(tier: int, kind: str, season: int, current: int) -> int:
    """Tier first, then kind (coverage, fixtures, details...), then the most recent season."""
    return tier * 10_000 + KIND_ORDER.index(kind) * 100 + max(0, min(99, current - season))


def save_plan(conn: psycopg.Connection, plan: MigrationPlan, *, name: str) -> int:
    """Store the plan as computed. The same plan (same hash) is stored once."""
    summary = plan.as_dict()
    h = plan.plan_hash()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO raw.migration_plans (name, plan_hash, config, summary, code_version) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (plan_hash) DO NOTHING RETURNING id",
                    (name, h, Json({"tiers": list(plan.tiers), "ids_batching": plan.ids_batching,
                                    "with_optional": plan.with_optional}),
                     Json(json.loads(json.dumps(summary, default=str))), code_version()))
        got = cur.fetchone()
        if got is None:
            cur.execute("SELECT id FROM raw.migration_plans WHERE plan_hash = %s", (h,))
            got = cur.fetchone()
    conn.commit()
    assert got is not None
    return int(got[0])


@dataclass
class SeedReport:
    created: int = 0
    existing: int = 0
    detail_units: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


def seed_plan(conn: psycopg.Connection, plan: MigrationPlan, *, plan_id: int | None, current_season: int) -> SeedReport:
    """Units for everything the plan prices. Idempotent.

    Detail units cannot always be created up front: the fixture ids are not known
    until the fixtures unit has run. So the fixtures unit carries
    ``then_details`` and expands them when it completes - AND detail units are
    expanded here for whatever is already stored.

    Both, not either. The bug this replaces was an ``if/elif``: when the plan
    priced a fixtures unit, ``add_unit`` was called and the ``elif`` was skipped,
    so a season whose fixtures a PREVIOUS plan had already stored created nothing
    (the insert hit ON CONFLICT DO NOTHING) and expanded nothing. 1,893 played
    fixtures ended up with no detail while every task row said done.
    """
    report = SeedReport()

    def add(kind: str, league: int, season: int, tier: int, params: dict[str, Any], page: int | None = None) -> None:
        with conn.cursor() as cur:
            ok = add_unit(cur, kind=kind, league_id=league, season=season, endpoint=ENDPOINTS[kind], params=params,
                          priority=priority(tier, kind, season, current_season), tier=tier, plan_id=plan_id,
                          page=page)
        if ok:
            report.created += 1
            report.by_kind[kind] = report.by_kind.get(kind, 0) + 1
        else:
            report.existing += 1

    tiers = sorted(plan.tiers)
    for u in plan.global_units:
        if u.kind == "league_coverage":
            add("league_coverage", 0, 0, tiers[0] if tiers else 1, {})
    for s in plan.seasons:
        kinds = {u.kind for u in s.units}
        wants_details = "fixture_details" in kinds
        base = {"league": s.league_id, "season": s.season}
        if "fixtures_season" in kinds:
            add("fixtures_season", s.league_id, s.season, s.tier, {**base, "then_details": wants_details})
        if wants_details:
            # Whatever is already stored gets its detail units now. Fixtures this
            # season does not have yet are covered by then_details above, and
            # expand_detail_batches only ever adds what is not already there.
            report.detail_units += expand_detail_batches(
                conn, league_id=s.league_id, season=s.season, tier=s.tier, plan_id=plan_id,
                priority=priority(s.tier, "fixture_details", s.season, current_season))
        for kind in ("standings_season", "injuries_season", "teams_season"):
            if kind in kinds:
                add(kind, s.league_id, s.season, s.tier, base)
        if "players_season" in kinds:
            add("players_season", s.league_id, s.season, s.tier, {**base, "page": 1}, page=1)
    conn.commit()
    report.by_kind["fixture_details"] = report.by_kind.get("fixture_details", 0) + report.detail_units
    return report


@dataclass(frozen=True, slots=True)
class StatusRow:
    tier: int | None
    kind: str
    status: str
    units: int
    requests: int
    rows: int


def migration_status(conn: psycopg.Connection) -> list[StatusRow]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT tier, kind, status, count(*), coalesce(sum(requests_spent), 0), "
                    "coalesce(sum(rows_written), 0) FROM raw.backfill_tasks GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")
        return [StatusRow(a, str(b), str(c), int(d), int(e), int(f)) for a, b, c, d, e, f in cur.fetchall()]

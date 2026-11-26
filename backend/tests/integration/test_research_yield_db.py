"""RP-9.8 on stored rows: the counters of EXP-E8 read the day plan's level, the ledger's research cost and the web facts of a match. One
transaction, rolled back (the ``db`` fixture)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ai import research_yield as ry
from fbi.ai.evidence import EvidenceIn, store

from .conftest import Seed

NOW = datetime(2032, 10, 20, 12, 0, tzinfo=UTC)


def plan(
    db: psycopg.Connection[Any], fixture_id: int, *, league: int | None, created: datetime
) -> None:
    entry = {
        "fixture_id": fixture_id,
        "kickoff_at": (NOW + timedelta(hours=8)).isoformat(),
        "competition_id": 1,
        "competition": "X",
        "country": None,
        "tier": 3,
        "home": "H",
        "away": "A",
        "has_market": False,
        "odds_at": None,
        "n_bookmakers": None,
        "priority": 1.0,
        "important": False,
        "provider_league_id": league,
    }
    db.execute(
        "INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, universe) "
        "VALUES (%s, 'opened', %s, 'test', 1, 0, %s::jsonb)",
        (created.date(), created, json.dumps([entry])),
    )


def usage(
    db: psycopg.Connection[Any],
    fixture_id: int | None,
    purpose: str,
    tier: str,
    usd: str,
    at: datetime,
) -> None:
    db.execute(
        "INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, fixture_id) VALUES (%s, %s, %s, 'p', 'm', %s, 'ok', %s)",
        (at, purpose, tier, usd, fixture_id),
    )


def fact(db: psycopg.Connection[Any], seed: Seed, tag: str, *, status: str) -> None:
    item = EvidenceIn(
        fixture_id=seed.fixture_id,
        team_id=seed.home_team_id,
        kind="news",
        claim=f"claim {tag}",
        origin="web",
        source_name="marca.com",
        retrieved_at=NOW - timedelta(hours=2),
        story_key=f"t:{tag}",
        source_url=f"https://marca.com/{tag}",
        assertion="info",
        source_tier="media",
        published_at=NOW - timedelta(hours=3),
        claim_type="OTHER",
        subject_type="TEAM",
        subject_id=seed.home_team_id,
        fresh_until=NOW + timedelta(hours=20),
    )
    evidence_id, created = store(db, item, at=NOW - timedelta(hours=2))
    assert created
    db.execute("UPDATE ai.evidence SET status = %s WHERE id = %s", (status, evidence_id))


def test_the_counters_join_the_plan_the_ledger_and_the_facts(
    db: psycopg.Connection[Any], seed: Seed
) -> None:
    plan(db, seed.fixture_id, league=239, created=NOW - timedelta(hours=10))
    usage(db, seed.fixture_id, "web_search", "search", "0.02", NOW - timedelta(hours=3))
    usage(db, seed.fixture_id, "evidence_extraction", "bulk", "0.003", NOW - timedelta(hours=3))
    usage(db, seed.fixture_id, "pick_review", "analysis", "0.40", NOW - timedelta(hours=3))
    usage(db, None, "web_search", "search", "0.02", NOW - timedelta(hours=3))
    fact(db, seed, "a", status="CONFIRMED")
    fact(db, seed, "b", status="PROBABLE")
    rows = ry.read(db, since=NOW - timedelta(days=1), until=NOW)
    assert [(m.fixture_id, m.level, m.cost, m.calls, m.facts, m.confirmed) for m in rows] == [
        (seed.fixture_id, "A", Decimal("0.023"), 2, 2, 1)
    ]
    doc = ry.report(rows, since=NOW - timedelta(days=1), until=NOW)
    assert (
        doc["levels"]["A"]["confirmed_per_match"] == 1.0 and doc["total"]["confirmed_share"] == 0.5
    )
    assert doc["progress"]["enough"] is False


def test_the_window_leaves_out_what_is_outside_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    plan(db, seed.fixture_id, league=None, created=NOW - timedelta(days=40))
    usage(db, seed.fixture_id, "web_search", "search", "0.02", NOW - timedelta(days=40))
    assert ry.read(db, since=NOW - timedelta(days=30), until=NOW) == []

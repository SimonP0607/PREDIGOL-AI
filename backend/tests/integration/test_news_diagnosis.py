"""IA-018 in a real database: the owner's diagnosis of a match's news. A reader (USER) is refused; the owner gets the match with its priority
group and coverage, the AI's day and the market, the passes with their web counts, the searches paid, Exa's envelope, the web items by status
and the verdict. Nothing is written while it answers. The transaction is rolled back."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.api.app import create_app
from fbi.api.deps import get_db
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
_provider_ids = count(9_818_001)


def client(db: psycopg.Connection[Any], role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def path(fid: int) -> str:
    return f"/api/v1/admin/matches/{fid}/news/diagnostics"


def fixture(db: psycopg.Connection[Any], seed: Seed, kickoff: datetime) -> int:
    return int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group) "
        "VALUES (%s, %s, %s, %s, %s, 'scheduled') RETURNING id",
        (next(_provider_ids), seed.season_id, seed.home_team_id, seed.away_team_id, kickoff))))


def priced(db: psycopg.Connection[Any], seed: Seed, fid: int) -> None:
    for sel, p_fair, odds in (("Home", "0.43", "2.20"), ("Draw", "0.28", "3.40"), ("Away", "0.29", "3.30")):
        db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, "
                   "overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', %s, 0, %s, 'shin', %s, 5, 0.05, %s, %s)",
                   (fid, sel, NOW - timedelta(hours=1), p_fair, odds, seed.bookmaker_id))


def passed(db: psycopg.Connection[Any], fid: int, kind: str, *, at: datetime, day: Any, counts: dict[str, int]) -> None:
    db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
               "SELECT id, %s, %s, %s, %s, kickoff_at, 'ok', %s FROM core.fixtures WHERE id = %s",
               (day, kind, at - timedelta(minutes=2), at, Jsonb(counts), fid))


def web_item(db: psycopg.Connection[Any], fid: int, team: int, *, status: str, n: int) -> None:
    retrieved = NOW - timedelta(hours=1)
    story = f"web:{fid}:{team}:p{n}:injury:out"
    digest = hashlib.sha256(f"{story}:{n}".encode()).hexdigest()
    db.execute("INSERT INTO ai.evidence (fixture_id, team_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, "
               "published_at, retrieved_at, story_key, content_hash, confidence, relevance, attributes, status, status_reason, status_changed_at) "
               "VALUES (%s, %s, 'injury', 'El jugador es baja por lesión según el club.', 'web', 'www.sport.es', 'https://www.sport.es/n/1', NULL, "
               "'media', NULL, %s, %s, %s, 0.5, 0.6, %s, %s, 'test', %s)",
               (fid, team, retrieved, story, digest, Jsonb({"assertion": "out"}), status, retrieved))


def test_a_reader_is_refused_and_the_owner_is_answered(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = fixture(db, seed, NOW + timedelta(hours=6))
    assert client(db, "USER").get(path(fid)).status_code == 403, "the diagnosis is the owner's alone"
    assert client(db, "SUPER_ADMIN").get(path(fid)).status_code == 200
    assert client(db, "SUPER_ADMIN").get(path(987_654_321)).status_code == 404


def test_the_diagnosis_of_a_searched_match_has_the_shape_the_web_reads(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    kickoff = NOW + timedelta(hours=6)
    fid = fixture(db, seed, kickoff)
    priced(db, seed, fid)
    day = local_day(kickoff)
    paid_at = NOW - timedelta(hours=2)
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, fixture_id) "
               "VALUES (%s, 'web_search', 'search', 'exa', 'exa', %s, 'ok', %s), (%s, 'web_search', 'search', 'exa', 'exa', %s, 'ok', %s), "
               "(%s, 'web_search', 'search', 'exa', 'exa', 0, 'failed', %s)",
               (paid_at, Decimal("0.015"), fid, paid_at, Decimal("0.015"), fid, paid_at, fid))
    passed(db, fid, "first", at=paid_at, day=day, counts={"web_searches": 2, "web_asked": 2, "web_read": 5, "web_priority": 1, "brief_llm": 1})
    web_item(db, fid, seed.home_team_id, status="CONFIRMED", n=1)
    web_item(db, fid, seed.away_team_id, status="RUMOR", n=2)

    body = client(db, "SUPER_ADMIN").get(path(fid)).json()
    assert body["status"] == "ok"
    d = body["data"]
    assert set(d) == {"as_of", "match", "coverage", "day", "passes", "next_pass", "searches", "exa", "evidence", "evidence_newest_at", "verdict"}
    assert d["match"]["fixture_id"] == fid and d["match"]["provider_league_id"] == 39 and d["match"]["priority_group"] == 1
    assert d["coverage"]["groups"] == [1, 2, 3] and d["coverage"]["covered"] is d["coverage"]["switch_on"]
    assert d["day"]["day"] == day.isoformat() and d["day"]["has_market"] is True
    [first] = d["passes"]
    assert first["kind"] == "first" and first["web"] == {"web_searches": 2, "web_asked": 2, "web_read": 5, "web_priority": 1}
    assert d["searches"]["searches"] == 2 and d["searches"]["failed"] == 1 and Decimal(d["searches"]["cost_usd"]) == Decimal("0.03")
    assert d["searches"]["sources_read"] == 5
    assert d["evidence"] == {"CONFIRMED": 1, "PROBABLE": 0, "CONTRADICTORY": 0, "RUMOR": 1, "OUTDATED": 0}
    assert d["exa"] is None or set(d["exa"]) == {"allowed", "reason", "budget_usd", "spent_month_usd", "spent_today_usd", "daily_cap_usd"}
    v = d["verdict"]
    assert v["code"] == "searched" and v["searches"] == 2 and v["pages"] == 5 and v["items"] == 2
    assert datetime.fromisoformat(v["at"]) == paid_at
    assert d["next_pass"] is None or d["next_pass"]["kind"] in ("pre", "final")


def test_a_match_never_searched_says_why(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    bare = fixture(db, seed, NOW + timedelta(hours=7))
    d = client(db, "SUPER_ADMIN").get(path(bare)).json()["data"]
    assert d["day"]["has_market"] is False and d["verdict"]["code"] == "no_market" and d["next_pass"] is None
    assert d["searches"]["searches"] == 0 and d["searches"]["sources_read"] == 0 and d["passes"] == []

    db.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    d = client(db, "SUPER_ADMIN").get(path(bare)).json()["data"]
    assert d["day"]["has_market"] is None and d["verdict"]["code"] == "not_tracked"


def test_the_diagnosis_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = fixture(db, seed, NOW + timedelta(hours=5))
    tables = ("ai.usage", "ai.fixture_passes", "ai.evidence", "ai.day_plans", "ai.envelope_alerts")
    before = {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables}
    assert client(db, "SUPER_ADMIN").get(path(fid)).status_code == 200
    assert {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables} == before

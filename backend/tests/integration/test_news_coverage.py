"""IA-016 in a real database: the day's universe carries each competition's API-Football id (its priority group for the news coverage), a
pass of a covered match takes no place of the day's web caps, and a match's news say whether it was searched - never searched, or searched
with the time of the last search, the searches paid and the pages read. The transaction is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.config import AiSettings
from fbi.ai.cycle import _allowance
from fbi.ai.day import universe
from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import news as service
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration

AT = datetime(2032, 8, 1, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
NOW = datetime.now(UTC).replace(microsecond=0)
_provider_ids = count(9_816_001)


def fixture(db: psycopg.Connection[Any], seed: Seed, kickoff: datetime) -> int:
    return int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group) "
        "VALUES (%s, %s, %s, %s, %s, 'scheduled') RETURNING id",
        (next(_provider_ids), seed.season_id, seed.home_team_id, seed.away_team_id, kickoff))))


def passed(db: psycopg.Connection[Any], fid: int, kind: str, *, at: datetime, counts: dict[str, int]) -> None:
    db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
               "SELECT id, %s, %s, %s, %s, kickoff_at, 'ok', %s FROM core.fixtures WHERE id = %s",
               (local_day(at), kind, at - timedelta(minutes=2), at, Jsonb(counts), fid))


def test_the_days_universe_carries_the_competitions_league_id(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    fid = fixture(db, seed, AT + timedelta(hours=8))
    mine = [f for f in universe(db, day=local_day(AT), at=AT) if f.fixture_id == fid]
    assert len(mine) == 1 and mine[0].provider_league_id == 39, "the seed's Premier League: group 1 of the owner's priority"


def test_a_covered_pass_takes_no_place_of_the_days_web_caps(db: psycopg.Connection[Any], seed: Seed) -> None:
    settings = AiSettings(max_web_first=20, max_web_pre=12)
    before = _allowance(db, settings, at=AT)
    covered, capped, pre = (fixture(db, seed, AT + timedelta(hours=h)) for h in (6, 7, 8))
    passed(db, covered, "first", at=AT - timedelta(hours=3), counts={"web_searches": 2, "web_priority": 1, "web_press": 1})
    passed(db, capped, "first", at=AT - timedelta(hours=3), counts={"web_searches": 1})
    passed(db, pre, "pre", at=AT - timedelta(hours=1), counts={"web_searches": 1})
    after = _allowance(db, settings, at=AT)
    assert before.web_first - after.web_first == 1, "only the match outside the coverage counts against FBI_AI_MAX_WEB_FIRST"
    assert before.web_pre - after.web_pre == 1


def client(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1")
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def test_a_matchs_news_say_whether_it_was_searched(db: psycopg.Connection[Any], seed: Seed,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    api = client(db, monkeypatch)
    never = fixture(db, seed, NOW + timedelta(hours=5))
    body = api.get(f"/api/v1/matches/{never}/news").json()
    assert body["status"] == "empty" and body["data"]["items"] == []
    assert body["data"]["search"] == {"searched": "no", "last_searched_at": None, "searches": 0, "sources_read": 0}
    assert body["reason"] == service.empty_reason(service.NewsSearch(searched="no"))

    searched = fixture(db, seed, NOW + timedelta(hours=6))
    paid_at, cached_at = NOW - timedelta(hours=4), NOW - timedelta(hours=1)
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, fixture_id) "
               "VALUES (%s, 'web_search', 'search', 'exa', 'exa', %s, 'ok', %s), (%s, 'web_search', 'search', 'exa', 'exa', %s, 'ok', %s), "
               "(%s, 'web_search', 'search', 'exa', 'exa', 0, 'failed', %s)",
               (paid_at, Decimal("0.015"), searched, paid_at, Decimal("0.015"), searched, NOW - timedelta(minutes=30), searched))
    passed(db, searched, "first", at=paid_at, counts={"web_searches": 2, "web_asked": 2, "web_read": 5, "web_priority": 1})
    passed(db, searched, "pre", at=cached_at, counts={"web_searches": 0, "web_asked": 2, "web_read": 1})
    passed(db, searched, "final", at=NOW + timedelta(hours=1), counts={"web_searches": 0, "web_asked": 1, "web_read": 9})  # after now
    state = api.get(f"/api/v1/matches/{searched}/news").json()["data"]["search"]
    assert state["searched"] == "yes" and state["searches"] == 2, "a failed search is not a search"
    assert datetime.fromisoformat(state["last_searched_at"]) == cached_at, "the pass answered from the cache is the last search"
    assert state["sources_read"] == 6, "pages read as of now, each once"

    older = fixture(db, seed, NOW + timedelta(hours=7))
    passed(db, older, "first", at=paid_at, counts={"web_searches": 1})
    state = api.get(f"/api/v1/matches/{older}/news").json()["data"]["search"]
    assert state["searched"] == "yes" and state["sources_read"] is None, "a pass that did not count its pages: unknown, not zero"

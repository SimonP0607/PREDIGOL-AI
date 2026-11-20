"""The owner's console of the provider's requests over the real application and a migrated database (plan PM, PM-04-05; BE-076): off,
404 even to the owner; on, the owner gets annex F's window from ``raw.provider_quota``, today's lanes and endpoints from
``raw.provider_endpoint_usage`` and the stored answers by competition; a reader gets 403."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.cache import clear as clear_cache
from fbi.api.deps import get_db
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.unit.test_provider_usage import ANNEX_F_DAYS, START

pytestmark = pytest.mark.integration
ROUTE = "/api/v1/admin/monitoring/provider-usage"


def client(db: psycopg.Connection, role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


@pytest.fixture
def seeded(db: psycopg.Connection) -> psycopg.Connection:
    """Annex F's 30 days, today's counts by endpoint and lane, and two stored answers of one league (rolled back after the test)."""
    db.execute("DELETE FROM raw.provider_quota WHERE provider = 'api_football' AND quota_date BETWEEN %s AND %s",
               (START, START + timedelta(days=29)))
    for i, spent in enumerate(ANNEX_F_DAYS):
        db.execute("INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) VALUES ('api_football', %s, %s, 60000)",
                   (START + timedelta(days=i), spent))
    today = datetime.now(UTC).date()
    db.execute("DELETE FROM raw.provider_endpoint_usage WHERE provider = 'api_football' AND usage_date = %s", (today,))
    for endpoint, lane, job, n in (("/odds", "cuotas", "odds_book_refresh", 159), ("/fixtures", "directo", "live_match_capture", 40),
                                   ("/players/teams", "referencia", "reference_refresh", 347)):
        db.execute("INSERT INTO raw.provider_endpoint_usage (provider, usage_date, endpoint, lane, job, requests) "
                   "VALUES ('api_football', %s, %s, %s, %s, %s)", (today, endpoint, lane, job, n))
    db.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type) "
               "VALUES (880077, 'Liga Ficticia del Consumo', 'Ficticia', 'league', 'club', 'domestic_league')")
    run = db.execute("INSERT INTO raw.ingestion_runs (job_name, api_calls) VALUES ('test_usage', 2) RETURNING id").fetchone()
    assert run is not None
    for k in range(2):
        db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, bytes) "
                   "VALUES (%s, %s, '/standings', %s, %s, 200, 'x', 1)",
                   (f"usage-test-{k}", run[0], '{"league": 880077, "season": 2026}', datetime(2026, 11, 10, 12, k, tzinfo=UTC)))
    clear_cache()
    return db


def test_off_it_answers_404_to_the_owner(seeded: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_USAGE_CONSOLE", raising=False)
    assert client(seeded, "SUPER_ADMIN").get(ROUTE).status_code == 404


def test_on_the_owner_gets_annex_f_and_today(seeded: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_USAGE_CONSOLE", "1")
    assert client(seeded, "USER").get(ROUTE).status_code == 403
    answer = client(seeded, "SUPER_ADMIN").get(ROUTE, params={"until": "2026-11-18", "days": 30})
    assert answer.status_code == 200, answer.text
    body = answer.json()["data"]
    w = body["window"]
    assert (w["days"], round(w["mean"]), round(w["median"]), w["max_normal"], w["max_normal_day"]) == (
        30, 17_845, 15_802, 23_430, "2026-11-02")
    assert w["exhausted_days"] == 1
    assert len(body["days"]) == 30
    lanes = {lane["lane"]: lane for lane in body["lanes"]}
    assert (lanes["cuotas"]["today"], lanes["directo"]["today"], lanes["referencia"]["today"]) == (159, 40, 347)
    assert body["today"]["counted"] == 546
    assert body["endpoints"][0] == {"endpoint": "/players/teams", "lane": "referencia", "today": 347, "window": 347}
    league = next(c for c in body["competitions"] if c["league_id"] == 880077)
    assert (league["name"], league["responses"]) == ("Liga Ficticia del Consumo", 2)
    assert body["guards"]["lanes_mode"] in {"off", "measure", "enforce"}

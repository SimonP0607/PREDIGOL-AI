"""What a public deployment closes, by configuration, and what stays as it is locally.

* FBI_API_DOCS=0: no /docs and no /openapi.json - they list every route, the admin ones included.
* FBI_API_HEALTH_DETAIL=0: /health says how each part is (ok / degraded / down and a stable code),
  not why - the reasons name the schema revision, the provider's quota and its last error.
Locally both stay open, as before.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from fbi.core.config import reset_cache
from tests.integration.conftest import Seed

PARTS = ("app", "database", "worker", "football_provider")


@pytest.fixture()
def env(migrated_database: str, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    monkeypatch.setenv("FBI_APIFOOTBALL_KEY", "not-a-key")
    monkeypatch.delenv("FBI_API_DOCS", raising=False)
    monkeypatch.delenv("FBI_API_HEALTH_DETAIL", raising=False)
    reset_cache()
    yield monkeypatch
    reset_cache()


def _client() -> TestClient:
    from fbi.api.app import create_app

    return TestClient(create_app())


def test_locally_the_docs_and_the_detailed_health_stay_open(env: pytest.MonkeyPatch) -> None:
    with _client() as c:
        assert c.get("/docs").status_code == 200
        assert c.get("/openapi.json").status_code == 200
        body = c.get("/api/v1/health").json()
    assert body["database"]["data"].get("revision"), "the local health names the revision"


def test_a_deployment_closes_the_docs_and_the_schema(env: pytest.MonkeyPatch) -> None:
    env.setenv("FBI_API_DOCS", "0")
    with _client() as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/api/v1/health").status_code in (200, 503), "health is still served"


def test_a_deployment_says_how_each_part_is_not_why(env: pytest.MonkeyPatch) -> None:
    env.setenv("FBI_API_HEALTH_DETAIL", "0")
    with _client() as c:
        for path in ("/api/v1/health", "/health"):
            response = c.get(path)
            body = response.json()
            assert body["status"] in ("ok", "degraded", "down"), path
            for part in PARTS:
                assert body[part]["status"] in ("ok", "degraded", "down", "unknown", "stale"), (path, part)
                assert body[part]["code"], "a stable code is still given, for monitors"
                assert body[part]["data"] == {} and body[part]["vars"] == {} and body[part]["detail"] == "", (
                    path, part, body[part])
            assert "revision" not in response.text and "remaining" not in response.text

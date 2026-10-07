"""fbi.api.deps: the API's read connections come from a bounded pool - reused between requests, never more than
FBI_API_DB_POOL_MAX at once, a 503 "database busy" (not a hang, not a crash) when every one is taken."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api import deps
from fbi.core.config import reset_cache


@pytest.fixture()
def pooled(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_API_DB_POOL_MAX", "2")
    mp.setenv("FBI_API_DB_POOL_TIMEOUT", "0.5")
    reset_cache()
    deps.close_pools()
    yield migrated_database
    deps.close_pools()
    mp.undo()
    reset_cache()


def api_backends(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                           "AND pid <> pg_backend_pid() AND query NOT ILIKE '%%pg_stat_activity%%' "
                           "AND backend_type = 'client backend'").fetchone()
        return int(row[0]) if row else 0


def test_requests_share_a_bounded_pool(pooled: str) -> None:
    from fbi.api.app import create_app

    with TestClient(create_app()) as c:
        for _ in range(12):
            assert c.get("/api/v1/competitions").status_code in (200, 401)
        pool = deps.read_pool()
        assert pool is not None
        stats = pool.get_stats()
        assert stats["pool_max"] == 2
        assert stats.get("connections_num", 0) <= 2  # 12 requests, at most two connections ever opened
        assert api_backends(pooled) <= 3  # the pool's two, plus at most the health check's own


def test_every_connection_taken_is_a_503_not_a_hang(pooled: str) -> None:
    from fbi.api.app import create_app

    pool = deps.read_pool()
    assert pool is not None
    held = [pool.getconn(), pool.getconn()]
    try:
        with TestClient(create_app()) as c:
            r = c.get("/api/v1/competitions")
            assert r.status_code == 503
    finally:
        for conn in held:
            pool.putconn(conn)


def test_pooling_can_be_turned_off(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_DB_POOL_MAX", "0")
    assert deps.read_pool() is None

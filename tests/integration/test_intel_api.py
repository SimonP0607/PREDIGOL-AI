"""PrediGol Intelligence over HTTP: every admin view answers (on whatever the test database holds), a user cannot reach
them, and an unknown decision is a 404."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, principal

VIEWS = ("/api/v1/admin/intelligence/day", "/api/v1/admin/intelligence/decisions",
         "/api/v1/admin/intelligence/calibration", "/api/v1/admin/intelligence/memory",
         "/api/v1/admin/intelligence/reports", "/api/v1/admin/intelligence/markets",
         "/api/v1/admin/intelligence/runs", "/api/v1/admin/intelligence/costs",
         "/api/v1/admin/intelligence/memory/team/1")


@pytest.fixture()
def env(migrated_database: str, seed: Seed) -> Iterator[Seed]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    yield seed
    mp.undo()
    reset_cache()


def client_for(role: str) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = dataclasses.replace(principal(role, user_id=1))
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE)


def test_every_view_answers_for_the_owner_and_none_for_a_user(env: Seed) -> None:
    admin = client_for("SUPER_ADMIN")
    for path in VIEWS:
        r = admin.get(path)
        assert r.status_code == 200, (path, r.text[:300])
        assert r.json()["status"] in ("ok", "empty")
    day = admin.get("/api/v1/admin/intelligence/day").json()["data"]
    assert {"decisions", "depth", "usage", "sources", "selections_v6", "calibration"} <= set(day)
    costs = admin.get("/api/v1/admin/intelligence/costs").json()["data"]
    assert costs["thresholds"] == [50, 70, 85, 95, 100]
    dossier = admin.get(f"/api/v1/admin/intelligence/matches/{env.fixture_id}/dossier")
    assert dossier.status_code == 200
    assert admin.get("/api/v1/admin/intelligence/decisions/999999999").status_code == 404
    user = client_for("USER")
    for path in VIEWS[:3]:
        assert user.get(path).status_code in (401, 403)

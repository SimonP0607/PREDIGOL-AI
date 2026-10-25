"""Observability of the API with an account signed in (plan UX, A2).

- The owner's test error: only a SUPER_ADMIN can raise it; it answers 500 with its request id and reaches Sentry
  under that id, with the owner's pseudonym and nothing personal.
- /auth/me gives the account its pseudonym, the one the web's errors carry: an HMAC of its id, not the id.
- Every log line written while a request is served carries its request id and, once known, the account's id.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
import structlog
from fastapi import Depends
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from fbi.api.security import observe_principal, require_app, same_site_only
from fbi.auth import crypto, service, throttle
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from tests.unit.sentry_capture import capturing_sentry

OWNER = "lookout@predigol.test"
OWNER_PW = "Lookout-pass-2026!"
READER = "reader-a2@predigol.test"
READER_PW = "Reader-a2-pass-26"
SAME_SITE = {"x-requested-with": "predigol"}


@pytest.fixture(scope="module")
def people(migrated_database: str) -> Iterator[dict[str, int]]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")  # the owner signs in with the password alone here (MFA: test_auth_mfa.py)
    reset_cache()
    reset_auth_settings()
    throttle.reset_all()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
    owner = service.create_user_unattended(email=OWNER, display_name="Lookout", role="SUPER_ADMIN", password=OWNER_PW)
    reader = service.create_user_unattended(email=READER, display_name="Reader", role="USER", password=READER_PW)
    yield {"owner": int(owner["id"]), "reader": int(reader["id"])}
    mp.undo()
    reset_cache()
    reset_auth_settings()


def scalars(node: Any, key: str = "") -> list[tuple[str, Any]]:
    """Every value in an event, however deep, with the key it sits under."""
    if isinstance(node, dict):
        return [kv for k, x in node.items() for kv in scalars(x, str(k))]
    if isinstance(node, list):
        return [kv for x in node for kv in scalars(x, key)]
    return [(key, node)]


def signed_in(email: str, password: str, *, app: Any = None) -> TestClient:
    from fbi.api.app import create_app

    client = TestClient(app or create_app(), headers=SAME_SITE, raise_server_exceptions=False)
    client.__enter__()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200 and r.json()["stage"] == "full", r.text
    return client


def test_the_owners_test_error_reaches_sentry_under_its_request_id(people: dict[str, int],
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    owner = signed_in(OWNER, OWNER_PW)
    try:
        with capturing_sentry(monkeypatch) as transport:
            r = owner.post("/api/v1/admin/monitoring/test-error")
        assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
        [event] = transport.events()
        assert event["tags"]["request_id"] == r.json()["request_id"]
        assert event["exception"]["values"][-1]["type"] == "MonitoringTestError"
        assert event["user"] == {"id": crypto.observability_id(people["owner"])}
        raw = transport.raw()
        for secret in (OWNER, OWNER_PW):
            assert secret not in raw, secret
        # the account's id under no key that names an id, and as no text (a substring test flaked: id 1 against a
        # request id ending in "1"; line numbers and flags may equal a small id, so they do not count)
        owner_id = people["owner"]
        found = [(k, v) for k, v in scalars(event) if (isinstance(v, str) and v == str(owner_id)) or (
            isinstance(v, int) and not isinstance(v, bool) and v == owner_id and "id" in k.lower())]
        assert found == [], found
    finally:
        owner.__exit__(None, None, None)


def test_only_the_owner_can_raise_it(people: dict[str, int]) -> None:
    reader = signed_in(READER, READER_PW)
    try:
        assert reader.post("/api/v1/admin/monitoring/test-error").status_code == 403
    finally:
        reader.__exit__(None, None, None)


def test_an_account_learns_its_pseudonym_never_its_id_in_disguise(people: dict[str, int]) -> None:
    reader = signed_in(READER, READER_PW)
    try:
        me = reader.get("/api/v1/auth/me").json()
        assert me["observability_id"] == crypto.observability_id(people["reader"])
        assert len(me["observability_id"]) == 20 and me["observability_id"] != str(people["reader"])
    finally:
        reader.__exit__(None, None, None)


def test_every_log_line_of_a_request_carries_its_id_and_the_accounts(people: dict[str, int]) -> None:
    from fbi.api.app import create_app

    app = create_app()
    probe_log = structlog.get_logger("probe")

    def probe() -> dict[str, str]:
        probe_log.info("probe.inside_the_route")
        return {"status": "ok"}

    app.add_api_route("/api/v1/__probe", probe, methods=["GET"],
                      dependencies=[Depends(same_site_only), Depends(require_app), Depends(observe_principal)])
    reader = signed_in(READER, READER_PW, app=app)
    try:
        with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
            r = reader.get("/api/v1/__probe")
        assert r.status_code == 200
        line = next(e for e in logs if e["event"] == "probe.inside_the_route")
        assert line["request_id"] == r.headers["x-request-id"]
        assert line["user_id"] == people["reader"]
    finally:
        reader.__exit__(None, None, None)

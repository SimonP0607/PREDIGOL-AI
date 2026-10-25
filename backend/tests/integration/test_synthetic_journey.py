"""The synthetic journey against the real API and its database (plan UX, A2): a pass is a completed ledger row with
every step in its notes and the session closed; a failing step is a failed row naming the step and its status, and an
error in the log (which Sentry receives)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from fbi.ops import synthetic

EMAIL = "synthetic-a2@predigol.test"
PASSWORD = "Synthetic-a2-pass-26"


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_API_LOGIN_RATE_LIMIT", "1000")
    reset_cache()
    reset_auth_settings()
    throttle.reset_all()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = %s", (synthetic.JOB_TYPE,))
    service.create_user_unattended(email=EMAIL, display_name="Synthetic", role="USER", password=PASSWORD)
    yield migrated_database
    mp.undo()
    reset_cache()
    reset_auth_settings()


def platform(*, broken: str | None = None) -> TestClient:
    """The API, with the web's sign-in page stood in for (the journey only checks that it is a page)."""
    from fbi.api.app import create_app

    app = create_app()

    def page() -> HTMLResponse:
        return HTMLResponse("<!doctype html><html lang=\"es\"><body>Inicia sesión</body></html>")

    app.add_api_route("/login", page, methods=["GET"])
    if broken is not None:
        @app.middleware("http")
        async def _break(request: Any, call_next: Callable[[Any], Any]) -> Any:
            if request.url.path == broken:
                return JSONResponse({"status": "error"}, status_code=500)
            return await call_next(request)

    return TestClient(app, base_url="http://testserver")


def last_run(dsn: str) -> tuple[Any, ...]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT status, errors, last_error, notes FROM raw.ingestion_runs WHERE job_type = %s "
                           "ORDER BY id DESC LIMIT 1", (synthetic.JOB_TYPE,)).fetchone()
    assert row is not None
    return tuple(row)


def open_sessions(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT count(*) FROM auth.sessions s JOIN auth.users u ON u.id = s.user_id "
                           "WHERE u.email = %s AND s.revoked_at IS NULL", (EMAIL,)).fetchone()
    assert row is not None
    return int(row[0])


def test_a_pass_is_a_completed_row_with_every_step_and_the_session_closed(database: str) -> None:
    cfg = synthetic.JourneyConfig(base_url="http://testserver", email=EMAIL, password=PASSWORD)
    with psycopg.connect(database) as conn, platform() as client:
        steps = synthetic.run_once(conn, cfg, client=client)
    assert all(s.ok for s in steps), [s.problem() for s in steps if not s.ok]
    status, errors, last_error, notes = last_run(database)
    assert (status, errors, last_error) == ("completed", 0, None)
    for name in ("page", "sign_in", "home", "matches_today", "picks", "my_picks", "sign_out"):
        assert name in notes, name
    assert PASSWORD not in notes and EMAIL not in notes
    assert open_sessions(database) == 0, "it signs out after itself"


def test_a_failing_step_is_a_failed_row_naming_it_and_an_error_in_the_log(database: str) -> None:
    cfg = synthetic.JourneyConfig(base_url="http://testserver", email=EMAIL, password=PASSWORD)
    with capture_logs() as logs, psycopg.connect(database) as conn, platform(broken="/api/v1/picks") as client:
        synthetic.run_once(conn, cfg, client=client)
    status, errors, last_error, _ = last_run(database)
    assert (status, errors, last_error) == ("failed", 1, "picks: HTTP 500")
    line = next(e for e in logs if e["event"] == "synthetic.failed")
    assert line["log_level"] == "error" and line["step"] == "picks" and line["status"] == 500
    assert open_sessions(database) == 0


def test_a_refused_sign_in_stops_there(database: str) -> None:
    cfg = synthetic.JourneyConfig(base_url="http://testserver", email=EMAIL, password="Not-the-password-26")
    with psycopg.connect(database) as conn, platform() as client:
        steps = synthetic.run_once(conn, cfg, client=client)
    assert [s.name for s in steps] == ["page", "sign_in"]
    status, _, last_error, _ = last_run(database)
    assert (status, last_error) == ("failed", "sign_in: HTTP 401")

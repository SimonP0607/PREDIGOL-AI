"""An unexpected error leaves its detail in the log, without personal data (plan UX, A1, defect F65).

The audit found `_contain` (the API's last line of defence) logging only the error's class name: a 500 in production
said "ValueError" and nothing else, and nobody could tell what broke. From A1 the log line keeps the type, the message
and the traceback, under the request id the client received - after a filter of personal data: an email address, an
IP address and anything shaped like a session token never reach the log, nor does a credential (fbi.core.logging).
The client still gets nothing but the request id.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from fbi.core.logging import scrub_personal

EMAIL = "someone.private@example.com"
TOKEN = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0Ga5KoPiRqWe"  # the shape of tokens.new_token()
IP = "203.0.113.77"


def explode_in_a_named_frame() -> None:
    raise ValueError(f"lookup failed for {EMAIL} with token {TOKEN} from {IP}")


@pytest.fixture()
def boom() -> TestClient:
    from fbi.api.app import create_app

    app = create_app()

    def route() -> dict[str, Any]:
        explode_in_a_named_frame()
        return {}

    app.add_api_route("/api/v1/__boom", route, methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def test_an_unexpected_error_logs_its_type_message_and_trace_under_the_request_id(boom: TestClient) -> None:
    with capture_logs() as logs:
        r = boom.get("/api/v1/__boom")
    assert r.status_code == 500
    rid = r.json()["request_id"]
    assert r.headers["x-request-id"] == rid
    assert r.json()["error"]["code"] == "internal"
    line = next(e for e in logs if e["event"] == "api.unhandled")
    assert line["request_id"] == rid and line["error"] == "ValueError"
    assert "lookup failed for" in line["message"]
    assert "explode_in_a_named_frame" in line["trace"], "the trace names the frame that raised"
    assert line["method"] == "GET" and line["path"] == "/api/v1/__boom"


def test_nothing_personal_reaches_the_log_line_or_the_answer(boom: TestClient) -> None:
    with capture_logs() as logs:
        r = boom.get("/api/v1/__boom")
    line = next(e for e in logs if e["event"] == "api.unhandled")
    written = " ".join(str(v) for v in line.values())
    for secret in (EMAIL, TOKEN, IP):
        assert secret not in written, secret
        assert secret not in r.text, secret
    assert "<email>" in line["message"] and "<token>" in line["message"] and "<ip>" in line["message"]


@pytest.mark.parametrize(("raw", "kept", "gone"), [
    ("mail Ana.Perez+x@sub.example.co then", "mail <email> then", "Ana.Perez"),
    ("from 192.168.10.4:5432", "from <ip>:5432", "192.168.10.4"),
    ("v6 2001:db8::8a2e:370:7334 here", "v6 <ip> here", "2001:db8"),
    ("cookie Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0Ga5KoPiRqWe end", "cookie <token> end", "Zk3pQ9mX"),
    ("sha " + "9f" * 32, "sha <hex>", "9f9f9f9f"),
    ("postgresql+psycopg://fbi:hunter2secret@db/fbi", "postgresql+psycopg://fbi:[REDACTED]@db/fbi", "hunter2"),
])
def test_the_filter_takes_out_what_names_a_person_or_opens_a_door(raw: str, kept: str, gone: str) -> None:
    out = scrub_personal(raw)
    assert out == kept and gone not in out


def test_the_filter_keeps_what_a_trace_needs() -> None:
    """Long function names, file paths, line numbers and versions are not personal data."""
    trace = ('File "/app/src/fbi/api/services/records.py", line 301, in '
             "test_the_six_client_routes_answer_the_shape_kept_in_the_snapshot\n"
             "psycopg.errors.UndefinedColumn: column u.status does not exist (v1.168.61)")
    assert scrub_personal(trace) == trace

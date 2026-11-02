"""An unexpected error leaves its detail in the log, without personal data (plan UX, A1, defect F65).

The audit found `_contain` (the API's last line of defence) logging only the error's class name: a 500 in production
said "ValueError" and nothing else, and nobody could tell what broke. From A1 the log line keeps the type, the message
and the traceback, under the request id the client received - after a filter of personal data: an email address, an
IP address and anything shaped like a session token never reach the log, nor does a credential (fbi.core.logging).
The client still gets nothing but the request id.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from fbi.core.logging import scrub_personal

EMAIL = "someone.private@example.com"
TOKEN = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0Ga5KoPiRqWe"  # the shape of tokens.new_token(); made up  # gitleaks:allow
IP = "203.0.113.77"


@contextmanager
def api_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[MutableMapping[str, Any]]]:
    """The API's log lines, captured. The app's logger is cached on first use (fbi.core.logging.configure:
    cache_logger_on_first_use), so after any other test built an app, capture_logs alone would not see it: the
    module's logger is replaced by one bound inside the capture."""
    import fbi.api.app as app_module

    with capture_logs() as logs:
        monkeypatch.setattr(app_module, "log", structlog.get_logger("api"))
        yield logs


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


def test_an_unexpected_error_logs_its_type_message_and_trace_under_the_request_id(
        boom: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with api_logs(monkeypatch) as logs:
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


def test_nothing_personal_reaches_the_log_line_or_the_answer(boom: TestClient,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    with api_logs(monkeypatch) as logs:
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
    ("postgresql+psycopg://fbi:hunter2secret@db/fbi", "postgresql+psycopg://fbi:[REDACTED]@db/fbi",  # gitleaks:allow (made up)
     "hunter2"),
    # found by the review of A1: an address with accents, raw bytes, a password hash, a token without a digit
    ("from simón.pérez@upb.edu.co", "from <email>", "pérez"),
    ("got b'\\x9f\\x3a\\x00key' here", "got <bytes> here", "x9f"),
    ("hash $argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2g end", "hash <hash> end", "c2FsdHNhbHQ"),
    ("cookie abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ end", "cookie <token> end", "abcdefghij"),
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


def test_the_lines_where_libraries_put_the_data_never_reach_the_log() -> None:
    """A database's refusal says the row it refused on the lines after its summary, a validation error says its
    input there: only the first line is logged, and the trace keeps the frames, not the message (review of A1)."""
    from fbi.core.logging import error_summary, error_trace

    def refuse() -> None:
        raise ValueError('duplicate key value violates unique constraint "users_email_key"\n'
                         "DETAIL:  Key (email)=(Ana Pérez, ana@example.com) already exists.")

    try:
        refuse()
    except ValueError as exc:
        summary, trace = error_summary(exc), error_trace(exc)
    assert summary == "duplicate key value violates unique constraint <value>", "a quoted text is not logged"
    assert "refuse" in trace and trace.endswith("ValueError")
    for secret in ("Ana Pérez", "ana@example.com", "DETAIL"):
        assert secret not in summary and secret not in trace


def test_a_validation_error_logs_where_it_failed_not_what_it_was_given() -> None:
    from pydantic import BaseModel, ValidationError

    from fbi.core.logging import error_summary, error_trace

    class Account(BaseModel):
        age: int

    given = {"age": ", ".join(("Ana Pérez", "ana@example.com"))}  # data, as a request would bring it: not code
    try:
        Account.model_validate(given)
    except ValidationError as exc:
        summary, trace = error_summary(exc), error_trace(exc)
    assert summary == "1 validation error(s): age (int_parsing)", "where it failed and how, not what it was given"
    for secret in ("Ana Pérez", "ana@example.com", "input_value"):
        assert secret not in summary and secret not in trace


def test_a_database_error_logs_its_sqlstate_not_the_value_it_quotes() -> None:
    """psycopg's first line can quote the value it refused ('invalid input syntax for type integer: "..."'): the
    summary is its SQLSTATE and what it names (second review of A1)."""
    import psycopg

    from fbi.core.logging import error_summary

    value = "Ana " + "Pérez"
    summary = error_summary(psycopg.errors.InvalidTextRepresentation(
        f'invalid input syntax for type integer: "{value}"'))
    assert summary.startswith("sqlstate 22P02") and "Pérez" not in summary


def test_a_group_of_errors_says_how_many_and_what_kinds() -> None:
    from fbi.core.logging import error_summary, error_trace

    group = ExceptionGroup("two", [ValueError("ana@example.com"), KeyError("secret")])
    assert error_summary(group) == "2 errors: ValueError, KeyError"
    assert "ana@example.com" not in error_trace(group)


def test_a_chain_of_causes_keeps_each_cause_s_frames_and_none_of_their_messages() -> None:
    from fbi.core.logging import error_trace

    secret, note = "ana" + "@example.com", "wrap" + "ped"  # data, not code: the frames show source lines

    def low() -> None:
        raise KeyError(secret)

    def high() -> None:
        try:
            low()
        except KeyError as exc:
            raise RuntimeError(note) from exc

    try:
        high()
    except RuntimeError as exc:
        trace = error_trace(exc)
    assert "low" in trace and "high" in trace and "KeyError (a cause)" in trace and trace.endswith("RuntimeError")
    assert secret not in trace and note not in trace


def test_a_value_the_caller_passed_is_not_logged_even_where_python_quotes_it() -> None:
    """int() and float() quote the text they could not read, fromisoformat() the date, a KeyError is the key (third
    review of A1): a quoted value becomes <value> and a KeyError says nothing but its type."""
    from datetime import date

    from fbi.core.logging import error_summary

    name = "Juan " + "Pérez Gómez"  # data, as a request would bring it: not code
    summaries = []
    for parse in (int, float, date.fromisoformat):
        try:
            parse(name)
        except ValueError as exc:
            summaries.append(error_summary(exc))
    by_name: dict[str, int] = {}
    try:
        by_name[name]
    except KeyError as exc:
        summaries.append(error_summary(exc))
    assert len(summaries) == 4
    for summary in summaries:
        assert "Pérez" not in summary and "Juan" not in summary, summary
    assert summaries[0] == "invalid literal for int() with base 10: <value>"
    assert summaries[3] == "", "a KeyError's message is the key"


def test_a_long_message_is_cut_before_the_filter_runs() -> None:
    """The filter's patterns over a 16 KB line took more than a second of the server's loop (third review of A1)."""
    from fbi.core.logging import error_summary

    huge = ValueError("a." * 8000)  # a 16 KB run the address pattern backtracks over: 0.6 s when filtered whole
    started = time.perf_counter()
    summary = error_summary(huge)
    assert time.perf_counter() - started < 0.1 and len(summary) <= 300


def test_when_summarising_fails_the_answer_and_the_log_line_still_come(boom: TestClient,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """An error inside the summary would reach the server, which logs the original error's messages unfiltered
    (third review of A1): the log line keeps the type and the request id, the client gets its 500."""
    import fbi.api.app as app_module

    def broken(_: BaseException) -> str:
        raise RuntimeError("the summariser broke")

    monkeypatch.setattr(app_module, "error_summary", broken)
    with api_logs(monkeypatch) as logs:
        r = boom.get("/api/v1/__boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    line = next(e for e in logs if e["event"] == "api.unhandled")
    assert line["error"] == "ValueError" and line["request_id"] == r.json()["request_id"]
    assert "summarising the error failed" in line["message"] and line["trace"] == ""
    assert EMAIL not in " ".join(str(v) for v in line.values())


def test_an_unexpected_error_reaches_sentry_under_the_request_id_the_client_got(
        boom: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan UX, A2: the same error, to Sentry too when it is on - under the request id the client received, with
    nothing of what its message carried."""
    from tests.unit.sentry_capture import capturing_sentry

    with capturing_sentry(monkeypatch) as transport:
        r = boom.get("/api/v1/__boom")
    assert r.status_code == 500
    [event] = transport.events()
    assert event["tags"]["request_id"] == r.json()["request_id"] == r.headers["x-request-id"]
    assert event["tags"]["path"] == "/api/v1/__boom" and event["tags"]["method"] == "GET"
    assert event["exception"]["values"][-1]["type"] == "ValueError"
    assert "user" not in event, "nobody was signed in"
    for secret in (EMAIL, TOKEN, IP):
        assert secret not in transport.raw(), secret

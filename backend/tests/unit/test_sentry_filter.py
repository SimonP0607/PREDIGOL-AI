"""What reaches Sentry (plan UX, A2): the error, never the person.

An event is loaded with fake personal data the way the SDK and the libraries would carry it - cookies, an
Authorization header, a request body with a password, a query string with a token, a user with an email and an IP,
an exception message quoting a value, frames with local variables, SQL and console breadcrumbs, extras named like
secrets - and not one of those values may be left after the filter (fbi.core.sentry.scrub_event). What a person
needs to debug stays: the type, the frames, the route without its query, the browser's name, the request id and the
account's pseudonym.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
import sentry_sdk
import structlog

from fbi.auth import crypto
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core import sentry
from tests.unit.sentry_capture import capturing_sentry

# data, as a request would bring it: built from parts so that no source line carries it whole
EMAIL = "ana.perez" + "@example.com"
PASSWORD = "Hunter2-" + "secret!"
TOKEN = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0" + "Ga5KoPiRqWe"  # made up  # gitleaks:allow
IP = "203.0.113." + "77"
NAME = "Ana " + "Pérez Gómez"
COOKIE = "__Host-predigol_session=" + TOKEN
SECRETS = (EMAIL, PASSWORD, TOKEN, IP, NAME, "Pérez")
PSEUDONYM = "0123456789abcdef0123"


def loaded_event() -> dict[str, Any]:
    return {
        "event_id": "e" * 32,
        "level": "error",
        "release": "predigol-web@abc",
        "request": {
            "method": "POST",
            "url": f"https://user:{PASSWORD}@predigolai.com/api/v1/me/picks?token={TOKEN}&email={EMAIL}#frag",
            "query_string": f"token={TOKEN}",
            "cookies": {"__Host-predigol_session": TOKEN},
            "data": {"email": EMAIL, "password": PASSWORD},
            "env": {"REMOTE_ADDR": IP},
            "headers": {"Cookie": COOKIE, "Authorization": f"Bearer {TOKEN}", "X-Forwarded-For": IP,
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"},
        },
        "user": {"id": 42, "email": EMAIL, "ip_address": IP, "username": NAME},
        "exception": {"values": [
            {"type": "ValueError", "value": f"invalid literal for int() with base 10: '{NAME}' from {EMAIL}\n"
                                            f"DETAIL: Key (email)=({EMAIL}) already exists",
             "mechanism": {"type": "generic", "data": {"password": PASSWORD}},
             "stacktrace": {"frames": [{"function": "save_pick", "filename": "records.py", "lineno": 301,
                                        "context_line": f"    lookup({EMAIL!r})",
                                        "pre_context": [f"token = {TOKEN!r}"],
                                        "vars": {"password": PASSWORD, "email": EMAIL}}]}},
            {"type": "KeyError", "value": f"'{EMAIL}'"},
        ]},
        "logentry": {"message": "sign-in failed for %s", "params": [EMAIL], "formatted": f"sign-in failed for {EMAIL}"},
        "breadcrumbs": {"values": [
            {"category": "query", "message": f"SELECT * FROM auth.users WHERE email = '{EMAIL}'"},
            {"category": "console", "message": f"password is {PASSWORD}"},
            {"category": "ui.click", "message": f"button[aria-label='{NAME}']"},
            {"type": "http", "category": "fetch", "data": {"method": "GET", "status_code": 500,
                                                            "url": f"/api/v1/me/picks?cursor={TOKEN}",
                                                            "request_body": PASSWORD}},
            {"category": "navigation", "data": {"from": f"/reset?token={TOKEN}", "to": "/home"}},
            {"category": "auth", "message": f"user {EMAIL} signed in from {IP}", "data": {"session": TOKEN}},
        ]},
        "extra": {"password": PASSWORD, "note": f"for {EMAIL}", "nested": {"api_key": TOKEN, "ok": "kept"}},
        "contexts": {"browser": {"name": "Safari", "version": "18.0"}, "response": {"cookie": TOKEN}},
        "tags": {"request_id": "a1b2c3d4e5f6", "email": EMAIL, "route": "/my-picks"},
    }


def test_nothing_personal_survives_the_filter() -> None:
    out = sentry.scrub_event(loaded_event())
    assert out is not None
    written = json.dumps(out, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in written, secret
    assert "user" not in out, "an id that is not a pseudonym is not sent"


def test_what_a_person_needs_to_debug_stays() -> None:
    out = sentry.scrub_event(loaded_event())
    assert out is not None
    assert out["request"] == {"method": "POST", "url": "https://predigolai.com/api/v1/me/picks",
                              "headers": {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"}}
    first, second = out["exception"]["values"]
    assert first["type"] == "ValueError" and first["value"] == "invalid literal for int() with base 10: <value> " \
                                                               "from <email>"
    frame = first["stacktrace"]["frames"][0]
    assert frame["function"] == "save_pick" and frame["lineno"] == 301 and "vars" not in frame
    assert "mechanism" in first and "data" not in first["mechanism"]
    assert second == {"type": "KeyError", "value": ""}
    assert out["tags"] == {"request_id": "a1b2c3d4e5f6", "route": "/my-picks"}
    assert out["contexts"]["browser"] == {"name": "Safari", "version": "18.0"}
    assert out["extra"] == {"note": "for <email>", "nested": {"ok": "kept"}}
    kinds = [c.get("category") for c in out["breadcrumbs"]["values"]]
    assert kinds == ["fetch", "navigation", "auth"], "SQL, console lines and clicks never leave"
    fetch = out["breadcrumbs"]["values"][0]["data"]
    assert fetch == {"method": "GET", "status_code": 500, "url": "/api/v1/me/picks"}
    assert out["breadcrumbs"]["values"][1]["data"] == {"from": "/reset", "to": "/home"}


def test_a_pseudonym_is_the_only_user_that_goes() -> None:
    event = loaded_event()
    event["user"] = {"id": PSEUDONYM, "email": EMAIL, "ip_address": IP}
    out = sentry.scrub_event(event)
    assert out is not None and out["user"] == {"id": PSEUDONYM}


@pytest.mark.parametrize("broken", [{"request": "not a dict"}, {"exception": {"values": "x"}}, {"breadcrumbs": 7},
                                    {"user": ["x"]}, {"extra": {"deep": [[[[[[[[{"password": "x"}]]]]]]]]}}])
def test_an_event_the_filter_cannot_read_is_never_sent_as_it_came(broken: dict[str, Any]) -> None:
    out = sentry.scrub_event(dict(broken))
    assert out is None or "password" not in json.dumps(out)


def test_the_pseudonym_groups_one_account_and_tells_nobody_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AUTH_SECRET_KEY", crypto.new_key_b64())
    reset_auth_settings()
    try:
        first = crypto.observability_id(42)
        assert first is not None and sentry.USER_ID.fullmatch(first)
        assert crypto.observability_id(42) == first and crypto.observability_id(43) != first
        unkeyed = {hashlib.sha256(s).hexdigest()[:20] for s in (b"42", b"user:42")}
        assert first != "42" and first not in unkeyed, "not the id, nor a hash anyone computes without the key"
        monkeypatch.setenv("FBI_AUTH_SECRET_KEY", crypto.new_key_b64())
        reset_auth_settings()
        assert crypto.observability_id(42) != first, "another key, another pseudonym: it depends on the secret"
        monkeypatch.delenv("FBI_AUTH_SECRET_KEY")
        reset_auth_settings()
        assert crypto.observability_id(42) is None, "without the key, no user at all"
    finally:
        reset_auth_settings()


def test_a_handled_error_reaches_sentry_with_its_tags_and_nothing_personal(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sentry.capture_exception(ValueError("x")) is None, "off: nothing is reported"
    with capturing_sentry(monkeypatch) as transport:
        try:
            raise ValueError(f"lookup failed for {EMAIL} with token {TOKEN}")
        except ValueError as exc:
            assert sentry.capture_exception(exc, user=PSEUDONYM, request_id="a1b2c3d4e5f6", path="/api/v1/home")
        [event] = transport.events()
        assert event["tags"]["request_id"] == "a1b2c3d4e5f6" and event["tags"]["path"] == "/api/v1/home"
        assert event["user"] == {"id": PSEUDONYM}
        assert event["exception"]["values"][0]["value"] == "lookup failed for <email> with token <token>"
        for secret in SECRETS:
            assert secret not in transport.raw(), secret


def test_an_error_the_worker_logs_and_handles_is_reported_once_in_a_while(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job's pass that fails is logged and the worker goes on (fbi.core.logging: the processor of
    fbi.core.sentry); Sentry gets the event's name and a few short fields through the filter - and not a second
    report of the same event within ten minutes, nor info lines, nor the API's error, reported with its exception."""
    monkeypatch.setattr(sentry, "ERROR_LOGS", sentry._ReportLimit())
    log = structlog.get_logger("worker-test")
    with capturing_sentry(monkeypatch, "worker") as transport:
        processors = [sentry.report_error_logs]
        for _ in range(3):
            sentry.report_error_logs(log, "error", {"event": "job.pass_failed", "job": "match_knowledge",
                                                    "error": f"KeyError: '{EMAIL}'"})
        sentry.report_error_logs(log, "info", {"event": "job.done"})
        sentry.report_error_logs(log, "error", {"event": "api.unhandled", "error": "ValueError"})
        events = transport.events()
        assert processors and len(events) == 1
        [event] = events
        assert event["message"] == "job.pass_failed" and event["tags"]["log_event"] == "job.pass_failed"
        assert event["extra"]["job"] == "match_knowledge" and event["extra"]["error"] == "KeyError: <value>"
        assert EMAIL not in transport.raw()


def test_the_report_limit_spares_the_month_of_the_free_plan() -> None:
    limit = sentry._ReportLimit(gap_s=600.0, per_hour=3)
    assert limit.allow("a", now=0.0) and not limit.allow("a", now=599.0) and limit.allow("a", now=601.0)
    assert limit.allow("b", now=602.0) and not limit.allow("c", now=603.0), "three an hour, whatever the event"
    assert limit.allow("c", now=3700.0)


def test_sentry_is_off_again_after_a_capturing_test() -> None:
    assert not sentry_sdk.is_initialized() and not sentry.enabled()


def test_the_trace_ids_stay_and_a_url_as_a_file_name_loses_its_query() -> None:
    event = loaded_event()
    event["contexts"]["trace"] = {"trace_id": "a" * 32, "span_id": "b" * 16, "op": f"lookup {EMAIL}"}
    event["exception"]["values"][0]["stacktrace"]["frames"][0]["filename"] = f"https://predigolai.com/reset?token={TOKEN}"
    out = sentry.scrub_event(event)
    assert out is not None
    assert out["contexts"]["trace"]["trace_id"] == "a" * 32 and out["contexts"]["trace"]["span_id"] == "b" * 16
    assert EMAIL not in json.dumps(out["contexts"])
    assert out["exception"]["values"][0]["stacktrace"]["frames"][0]["filename"] == "https://predigolai.com/reset"


def test_the_backend_sends_the_same_error_once_an_hour_and_a_bounded_day() -> None:
    """Review of A2: a broken route after a deploy reported once per request and could spend the free plan's month
    (5,000 errors) in a day, leaving the rest of the month without reports."""
    budget = sentry.EventBudget(gap_s=3600.0, per_day=3)
    assert budget.allow("ValueError@/api/v1/home", now=0.0)
    assert not budget.allow("ValueError@/api/v1/home", now=3599.0)
    assert budget.allow("ValueError@/api/v1/home", now=3601.0)
    assert budget.allow("KeyError@/api/v1/picks", now=3602.0)
    assert not budget.allow("TypeError@/api/v1/odds", now=3603.0), "the day's three are spent"
    assert budget.allow("TypeError@/api/v1/odds", now=90000.0)


def test_before_send_filters_then_keeps_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    with capturing_sentry(monkeypatch) as transport:
        for _ in range(3):
            try:
                raise ValueError(f"lookup failed for {EMAIL}")
            except ValueError as exc:
                sentry.capture_exception(exc, request_id="a1b2c3d4e5f6", path="/api/v1/home")
        try:
            raise KeyError("other")
        except KeyError as exc:
            sentry.capture_exception(exc, request_id="b1", path="/api/v1/home")
        kinds = [e["exception"]["values"][-1]["type"] for e in transport.events()]
        assert kinds == ["ValueError", "KeyError"], "the same error once; another error still goes"


def test_no_trace_header_tells_third_parties_the_projects_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of A2: by default the SDK adds "baggage" with the public key and the release to every outgoing request
    (API-Football, Anthropic, Telegram...)."""
    monkeypatch.setenv("FBI_SENTRY_DSN", "https://public@o0.ingest.example.invalid/1")
    opts = sentry.options("worker")
    assert opts is not None and opts["trace_propagation_targets"] == []
    assert opts["before_send"] is sentry.send_or_drop and opts["send_client_reports"] is False
    # e2e of A2: the SDK's release health sent every request's session as counts - no sessions leave either
    assert opts["auto_session_tracking"] is False


def test_the_owners_test_error_arrives_every_time_but_inside_the_days_budget() -> None:
    """e2e of A2: pressed twice within the hour, the second test error was the "same error" and never arrived - the
    owner would read a broken Sentry. Each press is its own event; the day's budget still holds."""
    budget = sentry.EventBudget(gap_s=3600.0, per_day=3)

    def test_error(rid: str) -> dict[str, object]:
        return {"exception": {"values": [{"type": "MonitoringTestError"}]}, "transaction": "/api/v1/admin/monitoring/test-error",
                "tags": {"request_id": rid}}

    keys = [sentry.event_key(test_error(r)) for r in ("a1", "b2", "c3", "d4")]
    assert len(set(keys)) == 4
    assert [budget.allow(k, now=10.0 + i) for i, k in enumerate(keys)] == [True, True, True, False], "the day's cap"
    other = {"exception": {"values": [{"type": "ValueError"}]}, "transaction": "/x", "tags": {"request_id": "e5"}}
    again = {**other, "tags": {"request_id": "f6"}}
    assert sentry.event_key(other) == sentry.event_key(again), "any other error is the same error whatever its request"

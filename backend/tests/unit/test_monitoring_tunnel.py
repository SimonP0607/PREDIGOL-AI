"""The browser's errors reach Sentry through this API, filtered, and the API is no open relay (plan UX, A2).

The web sends its events to /api/v1/monitoring/envelope instead of to Sentry: the reader's address never reaches a
third party and every event takes the server's filter again. The tunnel forwards only to this platform's web project,
whose DSN never leaves the server (the browser names a stand-in), only error events (never attachments, replays,
sessions or feedback), at most 100 KB, and a client and the whole process have their limits. The forwarding itself is
replaced here by a recorder: nothing leaves the test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from fbi.api.limits import SlidingWindow
from fbi.api.routers import monitoring
from fbi.core.sentry import BROWSER_DSN

WEB_DSN = "https://webkey@o0.ingest.example.invalid/2"
SAME_SITE = {"x-requested-with": "predigol"}
EMAIL = "ana.perez" + "@example.com"
TOKEN = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0" + "Ga5KoPiRqWe"  # made up  # gitleaks:allow
NAME = "Ana " + "Pérez Gómez"


def envelope(dsn: str = BROWSER_DSN, *, extra_items: list[tuple[dict[str, Any], bytes]] | None = None) -> bytes:
    event = {
        "event_id": "f" * 32, "platform": "javascript", "release": "predigol-web@abc", "level": "error",
        "exception": {"values": [{"type": "TypeError",
                                  "value": f"Cannot read properties of undefined (reading '{NAME}') {EMAIL}"}]},
        "request": {"url": f"https://predigolai.com/my-picks?token={TOKEN}",
                    "headers": {"User-Agent": "Mozilla/5.0 (Android 15)", "Referer": f"https://x/?email={EMAIL}"}},
        "user": {"id": "0123456789abcdef0123", "email": EMAIL},
        "breadcrumbs": [{"category": "console", "message": f"token {TOKEN}"},
                        {"category": "ui.click", "message": NAME},
                        {"category": "fetch", "type": "http",
                         "data": {"method": "GET", "url": f"/api/v1/me/picks?cursor={TOKEN}", "status_code": 500}}],
        "tags": {"request_id": "a1b2c3d4e5f6", "viewport": "390"},
        "extra": {"email": EMAIL},
    }
    payload = json.dumps(event).encode()
    parts = [json.dumps({"dsn": dsn, "event_id": "f" * 32, "sent_at": "2026-10-25T10:00:00Z",
                         "trace": {"user_segment": EMAIL}}).encode(),
             json.dumps({"type": "event", "length": len(payload)}).encode(), payload]
    for header, body in extra_items or []:
        parts += [json.dumps(header).encode(), body]
    return b"\n".join(parts) + b"\n"


@pytest.fixture()
def tunnel(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[tuple[str, bytes]]]]:
    monkeypatch.setenv("FBI_SENTRY_WEB_DSN", WEB_DSN)
    monkeypatch.delenv("FBI_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("FBI_ENV", "local")  # what the answer names: not whatever the CI exports
    monkeypatch.setattr(monitoring, "PER_CLIENT", SlidingWindow(per_window=1000, window_s=60.0))
    monkeypatch.setattr(monitoring, "PER_PROCESS", SlidingWindow(per_window=1000, window_s=3600.0))
    monkeypatch.setattr(monitoring, "PER_DAY", SlidingWindow(per_window=1000, window_s=86400.0))
    sent: list[tuple[str, bytes]] = []

    def record(dsn: str, body: bytes) -> int:
        sent.append((dsn, body))
        return 200

    monkeypatch.setattr(monitoring, "forward", record)
    from fbi.api.app import create_app

    with TestClient(create_app()) as client:
        yield client, sent


def test_without_a_web_project_the_browser_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_SENTRY_WEB_DSN", raising=False)
    monkeypatch.delenv("FBI_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("FBI_ENV", "local")
    from fbi.api.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/monitoring/client").json() == {
            "enabled": False, "dsn": None, "environment": "local", "tunnel": "/api/v1/monitoring/envelope"}
        r = client.post("/api/v1/monitoring/envelope", content=envelope(), headers=SAME_SITE)
        assert r.status_code == 404


def test_the_browser_learns_where_to_report_and_never_the_projects_key(
        tunnel: tuple[TestClient, list[tuple[str, bytes]]]) -> None:
    """Review of A2: on the free plan a key cannot be rate-limited, so the web project's DSN in the page would let
    anyone spend the month straight at Sentry, around the tunnel's caps. The browser gets a stand-in."""
    client, _ = tunnel
    r = client.get("/api/v1/monitoring/client")
    assert r.json() == {"enabled": True, "dsn": BROWSER_DSN, "environment": "local",
                        "tunnel": "/api/v1/monitoring/envelope"}
    assert "webkey" not in r.text and "ingest" not in r.text


def test_an_event_is_forwarded_filtered_and_nothing_else_goes(
        tunnel: tuple[TestClient, list[tuple[str, bytes]]]) -> None:
    client, sent = tunnel
    others: list[tuple[dict[str, Any], bytes]] = [
              ({"type": "attachment", "length": 9, "filename": "notes.txt"}, f"{EMAIL}x".encode()[:9]),
              ({"type": "replay_recording", "length": 5}, b"12345"),
              ({"type": "session"}, json.dumps({"did": EMAIL}).encode()),
              ({"type": "feedback"}, json.dumps({"message": NAME}).encode())]
    r = client.post("/api/v1/monitoring/envelope", content=envelope(extra_items=others), headers=SAME_SITE)
    assert r.status_code == 200 and r.json() == {"status": "ok", "events": 1}
    [(dsn, body)] = sent
    assert dsn == WEB_DSN
    header, items = monitoring.parse_envelope(body)
    assert header == {"dsn": WEB_DSN, "event_id": "f" * 32, "sent_at": "2026-10-25T10:00:00Z"}, \
        "under the project's real DSN, which only the server knows; the trace header (it named the reader) dropped"
    assert [kind for kind, _ in items] == ["event"]
    text = body.decode()
    for secret in (EMAIL, TOKEN, NAME, "Pérez"):
        assert secret not in text, secret
    event = json.loads(items[0][1])
    assert event["request"] == {"url": "https://predigolai.com/my-picks",
                                "headers": {"User-Agent": "Mozilla/5.0 (Android 15)"}}
    assert event["user"] == {"id": "0123456789abcdef0123"}
    assert event["tags"] == {"request_id": "a1b2c3d4e5f6", "viewport": "390"}
    assert [c["category"] for c in event["breadcrumbs"]["values"]] == ["fetch"]


@pytest.mark.parametrize(("body", "code"), [
    (envelope("https://otherkey@o0.ingest.example.invalid/9"), 400),
    (envelope(WEB_DSN), 400),  # only the stand-in: the browser never knew the real one
    (b"not an envelope", 400),
    (b'{"dsn": "' + BROWSER_DSN.encode() + b'"}\n{"type": "event", "length": 999}\n{}', 400),
])
def test_an_envelope_for_another_project_or_unreadable_is_refused(
        tunnel: tuple[TestClient, list[tuple[str, bytes]]], body: bytes, code: int) -> None:
    client, sent = tunnel
    r = client.post("/api/v1/monitoring/envelope", content=body, headers=SAME_SITE)
    assert r.status_code == code and r.json()["error"]["code"] == "bad_envelope"
    assert sent == [], "nothing is forwarded"


def test_a_report_over_100_kb_is_refused(tunnel: tuple[TestClient, list[tuple[str, bytes]]]) -> None:
    client, sent = tunnel
    big = envelope(extra_items=[({"type": "attachment", "length": 120_000}, b"x" * 120_000)])
    r = client.post("/api/v1/monitoring/envelope", content=big, headers=SAME_SITE)
    assert r.status_code == 413 and sent == []


def test_a_cross_site_post_is_refused(tunnel: tuple[TestClient, list[tuple[str, bytes]]]) -> None:
    client, sent = tunnel
    assert client.post("/api/v1/monitoring/envelope", content=envelope()).status_code == 403
    assert sent == []


def test_a_client_and_the_process_have_their_limits(tunnel: tuple[TestClient, list[tuple[str, bytes]]],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    client, sent = tunnel
    monkeypatch.setattr(monitoring, "PER_CLIENT", SlidingWindow(per_window=2, window_s=60.0))
    codes = [client.post("/api/v1/monitoring/envelope", content=envelope(), headers=SAME_SITE).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429] and len(sent) == 2
    monkeypatch.setattr(monitoring, "PER_CLIENT", SlidingWindow(per_window=1000, window_s=60.0))
    monkeypatch.setattr(monitoring, "PER_DAY", SlidingWindow(per_window=0, window_s=86400.0))
    assert client.post("/api/v1/monitoring/envelope", content=envelope(), headers=SAME_SITE).status_code == 429
    assert len(sent) == 2, "past the day's share nothing is forwarded"


def test_junk_does_not_spend_the_share_real_browsers_need(tunnel: tuple[TestClient, list[tuple[str, bytes]]],
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of A2: the hourly budget was charged before the envelope was read, so junk posts blocked real
    reports. It is charged only for an envelope that is forwarded."""
    client, sent = tunnel
    monkeypatch.setattr(monitoring, "PER_PROCESS", SlidingWindow(per_window=1, window_s=3600.0))
    for _ in range(5):
        assert client.post("/api/v1/monitoring/envelope", content=b"junk", headers=SAME_SITE).status_code == 400
        assert client.post("/api/v1/monitoring/envelope", content=envelope("https://k@x.invalid/9"),
                           headers=SAME_SITE).status_code == 400
    assert client.post("/api/v1/monitoring/envelope", content=envelope(), headers=SAME_SITE).status_code == 200
    assert len(sent) == 1


def test_input_python_cannot_read_is_refused_not_a_500(tunnel: tuple[TestClient, list[tuple[str, bytes]]]) -> None:
    """Review of A2: a nesting too deep raised RecursionError and half an emoji (a lone surrogate) failed the
    re-encoding - both became a 500 and an error of the backend."""
    client, sent = tunnel
    deep = b"[" * 100_000
    assert client.post("/api/v1/monitoring/envelope", content=deep, headers=SAME_SITE).status_code == 400
    head = json.dumps({"dsn": BROWSER_DSN}).encode()
    r = client.post("/api/v1/monitoring/envelope", content=head + b"\n" + json.dumps({"type": "event"}).encode()
                    + b"\n" + deep + b"\n", headers=SAME_SITE)
    assert r.status_code == 200 and r.json()["events"] == 0
    half = b'{"exception": {"values": [{"type": "Error", "value": "cut \\ud83d"}]}}'
    body = head + b"\n" + json.dumps({"type": "event", "length": len(half)}).encode() + b"\n" + half + b"\n"
    r = client.post("/api/v1/monitoring/envelope", content=body, headers=SAME_SITE)
    assert r.status_code == 200 and r.json()["events"] == 1
    assert b"\\ud83d" in sent[-1][1], "written as an escape, never a failure"


def test_when_sentry_asks_to_wait_the_browser_is_told(tunnel: tuple[TestClient, list[tuple[str, bytes]]],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = tunnel
    monkeypatch.setattr(monitoring, "forward", lambda dsn, body: 429)
    assert client.post("/api/v1/monitoring/envelope", content=envelope(), headers=SAME_SITE).status_code == 429


def test_the_forwarder_posts_to_the_projects_envelope_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert monitoring.forward(WEB_DSN, b"{}\n") == 200
    [request] = seen
    assert str(request.url) == "https://o0.ingest.example.invalid/api/2/envelope/"
    assert request.headers["content-type"] == "application/x-sentry-envelope" and request.content == b"{}\n"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(down), **kw))
    assert monitoring.forward(WEB_DSN, b"{}\n") == 0, "Sentry unreachable: the browser is not made to wait"

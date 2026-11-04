"""Resend over HTTP (plan UX, A5): one request per message with its idempotency key, and every answer that is not an
id turned into what the queue must do - again later, wait for the quota, wait for the owner, or give up - without
the provider's words (they can quote the address) and without the key."""

from __future__ import annotations

import json

import httpx
import pytest

from fbi.messaging.email import ResendClient, classify, client_from_env
from fbi.messaging.provider import Outgoing, ProviderError

KEY = "re_test_0000000000000000000000000000"  # gitleaks:allow - a made-up key for the stubbed transport
MESSAGE = Outgoing(to="lector@example.com", subject="Asunto", text="Hola", html="<p>Hola</p>",
                   idempotency_key="privacy_request_received:12@1761400000",
                   tags={"category": "privacy", "template": "privacy_request_received"})


def client(handler: httpx.MockTransport | None = None, **kw: str) -> ResendClient:
    return ResendClient(KEY, "PrediGol <avisos@correo.example.com>", transport=handler, **kw)


def answering(status: int, body: object = None, headers: dict[str, str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers=headers)
    return httpx.MockTransport(handle)


def test_a_message_is_one_request_with_its_key_and_nothing_else_about_the_reader() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"})

    provider_id = client(httpx.MockTransport(handle), reply_to="hola@example.com").send(MESSAGE)
    assert provider_id == "4ef9a417-02e9-4d39-ad75-9611e0fcc33c"
    [request] = seen
    assert request.method == "POST" and request.url == "https://api.resend.com/emails"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["idempotency-key"] == MESSAGE.idempotency_key
    body = json.loads(request.content)
    assert body == {"from": "PrediGol <avisos@correo.example.com>", "to": ["lector@example.com"], "subject": "Asunto",
                    "text": "Hola", "html": "<p>Hola</p>", "reply_to": "hola@example.com",
                    "tags": [{"name": "category", "value": "privacy"},
                             {"name": "template", "value": "privacy_request_received"}]}


@pytest.mark.parametrize(("status", "name", "kind"), [
    (429, "daily_quota_exceeded", "quota_day"),
    (429, "monthly_quota_exceeded", "quota_month"),
    (429, "rate_limit_exceeded", "retry"),
    (409, "concurrent_idempotent_requests", "retry"),
    (409, "resource_locked", "retry"),
    (409, "invalid_idempotent_request", "permanent"),
    (401, "validation_error", "config"),
    (403, "validation_error", "config"),
    (500, "application_error", "retry"),
    (503, "service_unavailable", "retry"),
    (400, "validation_error", "permanent"),
    (422, "missing_required_field", "permanent"),
    (404, "not_found", "permanent"),
])
def test_every_refusal_says_what_the_queue_must_do(status: int, name: str, kind: str) -> None:
    body = {"statusCode": status, "name": name, "message": "The to address lector@example.com is not valid"}
    with pytest.raises(ProviderError) as caught:
        client(answering(status, body)).send(MESSAGE)
    assert caught.value.kind == kind
    assert caught.value.code == f"resend {status} {name}"
    assert "lector@example.com" not in str(caught.value) and KEY not in str(caught.value)


def test_a_rate_limit_carries_the_wait_the_provider_asks_for() -> None:
    error = classify(httpx.Response(429, json={"name": "rate_limit_exceeded"}, headers={"retry-after": "7"}))
    assert error.kind == "retry" and error.retry_after_s == 7.0
    assert classify(httpx.Response(429, json={"name": "x"}, headers={"retry-after": "soon"})).retry_after_s is None


def test_an_answer_without_an_id_or_a_body_is_tried_again() -> None:
    with pytest.raises(ProviderError) as caught:
        client(answering(200, {"ok": True})).send(MESSAGE)
    assert caught.value.kind == "retry"
    weird = classify(httpx.Response(502, content=b"<html>bad gateway</html>"))
    assert weird.kind == "retry" and weird.code == "resend 502"


def test_the_network_failing_is_tried_again_without_the_key_in_the_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out talking to {request.url} with {KEY}")

    with pytest.raises(ProviderError) as caught:
        client(httpx.MockTransport(handle)).send(MESSAGE)
    assert caught.value.kind == "retry" and caught.value.code == "resend unreachable (ConnectTimeout)"
    assert KEY not in str(caught.value)


def test_no_key_or_no_sender_is_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_RESEND_API_KEY", raising=False)
    monkeypatch.setenv("FBI_EMAIL_FROM", "PrediGol <avisos@correo.example.com>")
    assert client_from_env() is None
    monkeypatch.setenv("FBI_RESEND_API_KEY", KEY)
    monkeypatch.delenv("FBI_EMAIL_FROM")
    assert client_from_env() is None
    monkeypatch.setenv("FBI_EMAIL_FROM", "PrediGol <avisos@correo.example.com>")
    provider = client_from_env()
    assert provider is not None and provider.name == "resend"
    provider.close()
    with pytest.raises(ValueError):
        ResendClient("", "x")

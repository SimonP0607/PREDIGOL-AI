"""The owner's communiqués, without a database (closing plan 4.3): the rules of what he may write, the channel post
with a fake Telegram, and that the public route is the only one readers reach."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fbi.customer import announcements as ann
from fbi.customer.db import CustomerError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def content(**changes: object) -> ann.Content:
    base = ann.Content(kind="maintenance", title_es="Mantenimiento esta noche", title_en="Maintenance tonight",
                       body_es="Habrá una pausa corta.", body_en="There will be a short pause.",
                       starts_at=NOW, ends_at=NOW + timedelta(hours=6), to_banner=True, critical=True)
    return replace(base, **changes)  # type: ignore[arg-type]


def refused(**changes: object) -> str:
    with pytest.raises(CustomerError) as caught:
        ann.validate(content(**changes))
    return caught.value.code


def test_a_well_formed_communique_passes() -> None:
    assert ann.validate(content()).kind == "maintenance"


def test_there_is_no_promotion_and_no_other_kind() -> None:
    assert ann.KINDS == ("maintenance", "incident", "update", "general")
    assert refused(kind="promotion") == "bad_kind"


@pytest.mark.parametrize("field", ["title_es", "title_en", "body_es", "body_en"])
def test_the_texts_have_limits_and_are_plain(field: str) -> None:
    assert refused(**{field: "ab"}) == "bad_text"
    assert refused(**{field: "x" * 601}) == "bad_text"
    assert refused(**{field: "<b>negrita</b>"}) == "bad_text"


def test_the_dates_make_sense() -> None:
    assert refused(ends_at=NOW) == "bad_dates"
    assert refused(ends_at=NOW + timedelta(days=ann.MAX_DAYS + 1)) == "bad_dates"


def test_a_destination_is_needed() -> None:
    assert refused(to_banner=False, to_updates=False, to_telegram=False, to_email=False) == "no_destination"


def test_novedades_take_only_updates() -> None:
    assert refused(kind="general", to_updates=True, critical=False) == "updates_only_updates"
    assert ann.validate(content(kind="update", to_updates=True, critical=False)).to_updates


def test_only_maintenance_and_incident_are_critical_and_only_critical_goes_by_email() -> None:
    assert refused(kind="general", critical=True) == "critical_kind"
    assert refused(kind="update", critical=True) == "critical_kind"
    assert refused(critical=False, to_email=True) == "email_critical_only"
    assert ann.validate(content(kind="incident", to_email=True)).to_email


def test_an_email_is_short() -> None:
    assert refused(to_email=True, body_es="x" * 201) == "email_too_long"


def test_the_daily_cap_defaults_to_three_and_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_ANNOUNCE_DAILY_CAP", raising=False)
    assert ann.daily_cap() == 3
    monkeypatch.setenv("FBI_ANNOUNCE_DAILY_CAP", "1")
    assert ann.daily_cap() == 1
    monkeypatch.setenv("FBI_ANNOUNCE_DAILY_CAP", "nonsense")
    assert ann.daily_cap() == 3


ROW = {"title_es": "Pausa", "title_en": "Pause", "body_es": "Volvemos pronto.", "body_en": "Back soon."}


def test_the_channel_post_is_spanish_then_english() -> None:
    title, body = ann.telegram_text(ROW)
    assert title == "Pausa / Pause"
    assert body == "Volvemos pronto.\n\nBack soon."


def test_without_telegram_nothing_is_posted_and_nothing_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("FBI_TELEGRAM_CHANNEL_ID", raising=False)
    assert not ann.telegram_configured()
    assert ann.post_to_channel(ROW) == (False, "not_configured")


def test_the_channel_post_goes_to_the_channel_with_a_fake_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_TELEGRAM_BOT_TOKEN", "123:fake-token-for-the-test")  # gitleaks:allow
    monkeypatch.setenv("FBI_TELEGRAM_CHANNEL_ID", "@predigol_canal")
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    assert ann.telegram_configured()
    assert ann.post_to_channel(ROW, transport=httpx.MockTransport(handler)) == (True, None)
    assert seen[0]["chat_id"] == "@predigol_canal"
    assert "Pausa / Pause" in str(seen[0]["text"]) and "Back soon." in str(seen[0]["text"])


def test_a_failing_channel_is_a_reason_not_an_exception_and_never_shows_the_token(
        monkeypatch: pytest.MonkeyPatch) -> None:
    token = "123:fake-token-for-the-test"  # gitleaks:allow
    monkeypatch.setenv("FBI_TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("FBI_TELEGRAM_CHANNEL_ID", "@predigol_canal")
    refusing = httpx.MockTransport(lambda request: httpx.Response(500))
    sent, reason = ann.post_to_channel(ROW, transport=refusing)
    assert not sent and reason is not None and token not in reason

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    sent, reason = ann.post_to_channel(ROW, transport=httpx.MockTransport(unreachable))
    assert not sent and reason is not None and token not in reason


def start(text: str = "/start", chat_type: str = "private") -> dict[str, object]:
    return {"message": {"text": text, "chat": {"id": 42, "type": chat_type}}}


def test_the_bot_greets_on_start_and_holds_no_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_WEB_BASE_URL", "https://predigolai.com")
    reply = ann.bot_welcome(start())
    assert reply is not None and reply[0] == "42"
    assert "https://predigolai.com/novedades" in reply[1]
    assert ann.bot_welcome(start("/start@predigol_bot")) is not None
    assert ann.bot_welcome(start("¿cuál es el pick de hoy?")) is None
    assert ann.bot_welcome(start(chat_type="group")) is None
    assert ann.bot_welcome({"channel_post": {"text": "/start"}}) is None


def test_the_webhook_secret_is_long_and_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "s" * 32
    monkeypatch.delenv("FBI_TELEGRAM_WEBHOOK_SECRET", raising=False)
    assert not ann.webhook_secret_ok(secret)
    monkeypatch.setenv("FBI_TELEGRAM_WEBHOOK_SECRET", "short")
    assert not ann.webhook_secret_ok("short")
    monkeypatch.setenv("FBI_TELEGRAM_WEBHOOK_SECRET", secret)
    assert ann.webhook_secret_ok(secret) and not ann.webhook_secret_ok("t" * 32)


def test_the_webhook_route_answers_only_to_the_secret_and_greets_with_a_fake_telegram(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fbi.api.errors import install
    from fbi.api.routers import announcements as routes

    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(routes, "TELEGRAM_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("FBI_TELEGRAM_BOT_TOKEN", "123:fake-token-for-the-test")  # gitleaks:allow
    monkeypatch.setenv("FBI_TELEGRAM_WEBHOOK_SECRET", "w" * 32)
    app = FastAPI()
    install(app)
    app.include_router(routes.bot_router, prefix="/api/v1")
    client = TestClient(app)
    assert client.post(f"/api/v1/telegram/webhook/{'x' * 32}", json=start()).status_code == 404
    assert sent == []
    assert client.post(f"/api/v1/telegram/webhook/{'w' * 32}", json=start()).status_code == 204
    assert [m["chat_id"] for m in sent] == ["42"]
    assert client.post(f"/api/v1/telegram/webhook/{'w' * 32}", json=start("hola, ayuda")).status_code == 204
    assert len(sent) == 1

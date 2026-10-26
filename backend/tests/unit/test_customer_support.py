"""The rules of a reader's ticket (plan UX, A14; section 32 of the plan), without a database: the priority and the first
answer's target of each category, the context the page attaches as the server keeps it, when a ticket is late, the
switch, the e-mails' words and the limits of what a reader may send."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from fbi.api.contracts.support import SupportContextIn, TicketAnswerIn, TicketCloseIn, TicketIn
from fbi.customer import support
from fbi.customer.db import CustomerError
from fbi.messaging import templates

# 26 Oct 2026, 10:00 in Bogotá (UTC-5, no summer time)
MORNING = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


def ticket(**over: Any) -> support.Ticket:
    base: dict[str, Any] = {"id": 1, "user_id": 7, "kind": "support", "category": "technical", "status": "open",
                            "opened_at": MORNING, "due_on": None, "extended_to": None, "closed_at": None,
                            "context": None, "effort": None, "messages": []}
    return support.Ticket(**{**base, **over})


def owner_says(at: datetime) -> support.Message:
    return support.Message(id=9, author="owner", body="Hola", at=at, channel="web")


# ── priority and the first answer ─────────────────────────────────────────────────────


def test_each_category_has_the_priority_of_section_32() -> None:
    assert {c: support.priority_of(c) for c in (*support.CATEGORIES, "privacy")} == {
        "access": "urgent", "account": "high", "technical": "high", "wrong_data": "medium", "suggestion": "low",
        "complaint": "high", "privacy": "high"}
    assert support.CATEGORIES[0] == "access", "the urgent one first: the sheet offers them in this order"
    assert sorted(support.URGENT) == ["access"]
    assert support.PRIORITY_CATEGORIES == {"urgent": ("access",), "high": ("account", "technical", "complaint", "privacy"),
                                           "medium": ("wrong_data",), "low": ("suggestion",)}


def test_the_first_answer_is_due_in_hours_or_the_same_day() -> None:
    assert support.respond_by("account", MORNING) == MORNING + timedelta(hours=24)
    assert support.respond_by("technical", MORNING) == MORNING + timedelta(hours=24)
    assert support.respond_by("complaint", MORNING) == MORNING + timedelta(hours=24)
    assert support.respond_by("wrong_data", MORNING) == MORNING + timedelta(hours=48)
    assert support.respond_by("suggestion", MORNING) == MORNING + timedelta(days=7)
    # urgent, opened at 10:00 in Bogotá: by the end of that day (23:59 in Bogotá = 04:59 UTC the next day)
    assert support.respond_by("access", MORNING) == datetime(2026, 10, 27, 4, 59, tzinfo=UTC)
    # urgent, opened at 19:59 in Bogotá: still the same day
    assert support.respond_by("access", datetime(2026, 10, 27, 0, 59, tzinfo=UTC)) == datetime(2026, 10, 27, 4, 59, tzinfo=UTC)
    # urgent, opened at 20:30 in Bogotá: the next day by noon (17:00 UTC), not in half an hour
    assert support.respond_by("access", datetime(2026, 10, 27, 1, 30, tzinfo=UTC)) == datetime(2026, 10, 27, 17, 0, tzinfo=UTC)


def test_a_ticket_is_late_past_its_target_with_no_answer_and_a_request_past_its_deadline() -> None:
    late_at = MORNING + timedelta(hours=25)
    assert ticket().late(late_at)
    assert not ticket().late(MORNING + timedelta(hours=23))
    assert not ticket(messages=[owner_says(MORNING + timedelta(hours=30))]).late(late_at), "answered once: not late"
    assert not ticket(status="closed", closed_at=late_at).late(late_at + timedelta(days=3))
    assert ticket(status="answered", messages=[]).late(late_at) is True, "answered by status alone is not an answer"
    privacy = ticket(kind="privacy_query", category="privacy", due_on=date(2026, 11, 9))
    assert privacy.respond_by is None and privacy.priority == "high"
    assert not privacy.late(datetime(2026, 11, 9, 23, 0, tzinfo=UTC)), "the deadline day itself is still in time"
    assert privacy.late(datetime(2026, 11, 10, 6, 0, tzinfo=UTC))
    extended = ticket(kind="privacy_claim", category="privacy", due_on=date(2026, 11, 9), extended_to=date(2026, 11, 19))
    assert extended.deadline == date(2026, 11, 19) and not extended.late(datetime(2026, 11, 12, 15, 0, tzinfo=UTC))
    assert ticket().waiting and not ticket(status="answered").waiting
    assert ticket(messages=[owner_says(MORNING + timedelta(hours=2))]).first_answer_at == MORNING + timedelta(hours=2)


# ── the context ──────────────────────────────────────────────────────────────────────


def test_the_context_keeps_the_known_keys_in_their_shape() -> None:
    raw = {"route": "/matches/1234", "request_id": "a1b2c3d4e5f6", "web_version": "2026.10.26+ab12cd3",
           "device": "phone", "pwa": True, "match_id": 1234}
    assert support.clean_context(raw) == raw
    assert support.clean_context({}) is None and support.clean_context(None) is None
    assert support.clean_context({"device": "desktop", "pwa": False}) == {"device": "desktop", "pwa": False}


@pytest.mark.parametrize("raw", [
    {"route": "/reset-password?token=abc"},  # a query never reaches the server (the page sends the path alone)
    {"route": "/matches#x"},
    {"route": "https://evil.example/matches"},
    {"route": "matches"},
    {"route": "/" + "a" * 200},
    {"request_id": "abc-def"},
    {"request_id": "x" * 33},
    {"web_version": "1.0 beta"},
    {"device": "watch"},
    {"pwa": "yes"},
    {"match_id": True},
    {"match_id": 0},
    {"match_id": "12"},
    {"email": "lectora@example.org"},  # an unknown key: never kept
    {"password": "x"},
    {"form": {"field": "value"}},
])
def test_the_context_refuses_anything_else(raw: dict[str, object]) -> None:
    with pytest.raises(CustomerError) as caught:
        support.clean_context(raw)
    assert (caught.value.status, caught.value.code) == (422, "invalid_context")


def test_a_one_use_links_page_keeps_only_its_name() -> None:
    assert support.clean_context({"route": "/reset-password/abc123"}) == {"route": "/reset-password"}
    assert support.clean_context({"route": "/activate"}) == {"route": "/activate"}
    assert support.clean_context({"route": "/unlock/zz"}) == {"route": "/unlock"}
    assert support.clean_context({"route": "/activated-elsewhere"}) == {"route": "/activated-elsewhere"}


# ── the switch ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "on"), [(None, True), ("", True), ("1", True), ("on", True), ("0", False),
                                         ("off", False), ("no", False), ("maybe", False)])
def test_the_switch_is_born_on_and_turns_off_with_a_line(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                         on: bool) -> None:
    monkeypatch.delenv(support.SWITCH, raising=False)
    if raw is not None:
        monkeypatch.setenv(support.SWITCH, raw)
    assert support.support_on() is on


def test_with_the_switch_off_a_reader_cannot_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(support.SWITCH, "0")
    for call in (lambda: support.open_ticket(7, "technical", "Hola"), lambda: support.reply(7, 1, "Hola"),
                 lambda: support.close(7, 1)):
        with pytest.raises(CustomerError) as caught:
            call()
        assert (caught.value.status, caught.value.code) == (404, "not_available")


def test_what_a_reader_sends_is_checked_before_any_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(support.SWITCH, raising=False)
    cases = {
        "use_privacy_request": lambda: support.open_ticket(7, "privacy", "¿Qué datos tienen de mí?"),
        "unknown_category": lambda: support.open_ticket(7, "billing", "Hola"),
        "invalid_message": lambda: support.open_ticket(7, "technical", "   "),
    }
    for expected, call in cases.items():
        with pytest.raises(CustomerError) as caught:
            call()
        assert caught.value.code == expected
    with pytest.raises(CustomerError) as long:
        support.open_ticket(7, "technical", "x" * (support.MAX_TEXT + 1))
    assert long.value.code == "invalid_message"
    with pytest.raises(CustomerError) as effort:
        support.close(7, 1, effort=6)
    assert effort.value.code == "invalid_effort"


# ── the contracts ────────────────────────────────────────────────────────────────────


def test_the_contracts_refuse_what_the_plan_does_not_allow() -> None:
    TicketIn(category="wrong_data", text="El marcador está mal", context=SupportContextIn(match_id=5))
    for bad in ({"category": "privacy", "text": "x"}, {"category": "technical", "text": ""},
                {"category": "technical", "text": "x" * 2001}, {"category": "technical", "text": "x", "files": []},
                {"category": "technical", "text": "x", "context": {"cookie": "x"}}):
        with pytest.raises(ValidationError):
            TicketIn.model_validate(bad)
    with pytest.raises(ValidationError):
        TicketCloseIn(effort=0)
    assert TicketAnswerIn(body="Listo").model_dump() == {"body": "Listo", "status": "answered", "channel": "web"}
    with pytest.raises(ValidationError):
        TicketAnswerIn.model_validate({"body": "x", "channel": "sms"})


# ── the e-mails ──────────────────────────────────────────────────────────────────────


def test_the_receipt_and_the_answer_say_the_number_the_topic_and_the_moment_never_a_word_of_the_thread() -> None:
    received = templates.render("support_ticket_received", "es",
                                {"ticket": "34", "category": "access", "by": "2026-10-27T04:59:00+00:00"},
                                {"name": "Lectora"}, zone="America/Bogota")
    assert "el acceso a tu cuenta (n.º 34)" in received.text
    assert "26 de octubre de 2026, 23:59 (hora de Bogota)" in received.text, "the moment, in the reader's time zone"
    assert received.link is not None and received.link.endswith("/help/messages/34")
    answered = templates.render("support_ticket_answered", "en", {"ticket": "34", "category": "wrong_data"},
                                {"name": "Reader"}, zone="UTC")
    assert "your message about wrong data (no. 34)" in answered.text
    assert "we do not copy it into this e-mail" in answered.text
    for name in ("support_ticket_received", "support_ticket_answered"):
        t = templates.TEMPLATES[name]
        assert t.category == "support" and t.stale_after is not None
        assert "body" not in t.params and "text" not in t.params, "the queue never keeps a word of the thread"
    with pytest.raises(templates.TemplateError):
        templates.check_params("support_ticket_answered", {"ticket": "34", "category": "privacy"})
    with pytest.raises(templates.TemplateError):
        templates.check_params("support_ticket_answered", {"ticket": "x34", "category": "access"})
    with pytest.raises(templates.TemplateError):
        templates.check_params("support_ticket_received", {"ticket": "34", "category": "access", "by": "mañana"})

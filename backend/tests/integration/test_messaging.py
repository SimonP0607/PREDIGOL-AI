"""The messages to readers against the migrated database (plan UX, A5), with the provider simulated.

* The queue: one message per deduplication key, in the reader's language, with only the template's own parameters;
  what was asked never changes and nothing is deleted.
* The messenger: the address and the name read when sending, the reader's choices and their address's state
  applied, retries after 1 min, 5 min, 30 min, 2 h and 12 h then 'failed', a permanent refusal at once, a broken
  configuration stopping the pass, the provider's quota and the daily cap waiting, two messengers never sending the
  same message, one ledger row per cycle.
* The signed webhook: a hard bounce or a complaint recorded and stopping the address; nothing unsigned or stale.
* The reader's preferences over HTTP; a privacy request and its answer queuing their messages without their words;
  the owner's queue and preview.
* The owner's notices: counts and a link to the console, never a reader's address, alias or words.
* A material change of a legal text: one message per reader who accepted the text before, only once it is published.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, legal, privacy, workdays
from fbi.messaging import notices, outbox, runner, templates, webhooks
from fbi.messaging.legal_change import enqueue_legal_changes
from fbi.messaging.provider import Outgoing, ProviderError
from fbi.messaging.templates import Copy, Template, TemplateError
from tests.integration.helpers import forget_sign_in_failures

READER = "zq.distinto+a5@example.org"
READER_NAME = "Zacarías Quintero-Pérez"
READER_EN = "reader.en@example.org"
OTHER = "otro.lector@example.org"
OWNER = "owner.a5@predigol.test"
ROBOT = "robot.a5@predigol.test"
PASSWORD = "Reader-pass-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
SAME_SITE = {"x-requested-with": "predigol"}
SECRET_TEXT = "Texto privado zzq-7781 del lector"
OWNER_TEXT = "Respuesta privada del dueño qq-5512"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"a5-integration-webhook-secret-32").decode()  # gitleaks:allow - made up


def wipe_messaging(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.ticket_messages",
                      "customer.support_tickets", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind IN ('ticket_new', 'privacy_due', 'outbox_failing', "
                     "'synthetic_failed')")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type IN ('messenger_cycle', 'synthetic_journey')")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_SYNTHETIC_EMAIL", ROBOT)
    mp.setenv("FBI_WEB_BASE_URL", "https://predigol.example")
    reset_cache()
    reset_session_settings()

    def wipe() -> None:
        wipe_messaging(migrated_database)
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM auth.sessions")
            conn.execute("DELETE FROM auth.audit_events")
            conn.execute("DELETE FROM picks.user_picks")
            conn.execute("DELETE FROM auth.users")

    wipe()
    for email, name, role, lang in ((READER, READER_NAME, "USER", "es"), (READER_EN, "Reader En", "USER", "en"),
                                    (OTHER, "Otro", "USER", "es"), (OWNER, "Owner", "SUPER_ADMIN", "es"),
                                    (ROBOT, "Robot", "USER", "es")):
        service.create_user_unattended(email=email, display_name=name, role=role, password=PASSWORD, language=lang,
                                       timezone="America/Bogota")
    yield migrated_database
    wipe()
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    wipe_messaging(database)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET display_name = %s WHERE email = %s", (READER_NAME, READER))
    consents._clear.clear()
    monkeypatch.delenv(consents.GATE_ENV, raising=False)
    monkeypatch.delenv("FBI_EMAIL_SEND", raising=False)
    monkeypatch.delenv("FBI_RESEND_WEBHOOK_SECRET", raising=False)
    yield database
    consents._clear.clear()


@pytest.fixture()
def conn(fresh: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(fresh) as c:
        yield c


def user_id(conn: psycopg.Connection[Any], email: str) -> int:
    row = conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,)).fetchone()
    assert row is not None
    return int(row[0])


def queue(conn: psycopg.Connection[Any], email: str = READER, *, key: str | None = None,
          template: str = "privacy_request_answered", params: dict[str, str] | None = None) -> int:
    mid = outbox.enqueue(conn, user_id=user_id(conn, email), template=template,
                         params=params or {"request": "privacy_query", "ticket": "7"},
                         dedup_key=key or f"test:{uuid.uuid4().hex}")
    conn.commit()
    assert mid is not None
    return mid


def message(conn: psycopg.Connection[Any], mid: int) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM customer.messages_outbox WHERE id = %s", (mid,))
        row = cur.fetchone()
    conn.commit()
    assert row is not None
    return dict(row)


class FakeProvider:
    name = "fake"

    def __init__(self, *script: str | ProviderError) -> None:
        self.script = list(script)
        self.sent: list[Outgoing] = []

    def send(self, msg: Outgoing) -> str:
        self.sent.append(msg)
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, ProviderError):
                raise item
            return item
        return f"prov-{uuid.uuid4().hex}"


def client(email: str) -> TestClient:
    from fbi.api.app import create_app

    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


# ── the queue ─────────────────────────────────────────────────────────────────────────

def test_a_message_is_queued_once_in_the_readers_language_without_a_body(conn: psycopg.Connection[Any]) -> None:
    es = queue(conn, READER, key="test:once-es")
    en = queue(conn, READER_EN, key="test:once-en")
    assert outbox.enqueue(conn, user_id=user_id(conn, READER), template="privacy_request_answered",
                          params={"request": "privacy_query", "ticket": "7"}, dedup_key="test:once-es") is None
    assert message(conn, es)["locale"] == "es" and message(conn, en)["locale"] == "en"
    row = message(conn, es)
    assert row["status"] == "queued" and row["category"] == "privacy" and row["attempts"] == 0
    assert row["params"] == {"request": "privacy_query", "ticket": "7"}
    columns = {c for (c,) in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'customer' "
        "AND table_name = 'messages_outbox'").fetchall()}
    assert not columns & {"body", "subject", "html", "text", "email", "address", "name", "to"}


def test_the_queue_refuses_what_it_must_never_keep(conn: psycopg.Connection[Any]) -> None:
    uid = user_id(conn, READER)
    for params in ({"request": "privacy_query", "ticket": "7", "token": "abc"},
                   {"request": "privacy_query", "ticket": "7", "name": READER_NAME},
                   {"request": "privacy_query"}):
        with pytest.raises(TemplateError):
            outbox.enqueue(conn, user_id=uid, template="privacy_request_answered", params=params,
                           dedup_key=f"test:{uuid.uuid4().hex}")
    with pytest.raises(TemplateError, match="deduplication key"):
        outbox.enqueue(conn, user_id=uid, template="privacy_request_answered",
                       params={"request": "privacy_query", "ticket": "7"}, dedup_key="short")
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM customer.messages_outbox").fetchone() == (0,)


def test_what_was_asked_never_changes_and_nothing_is_deleted(conn: psycopg.Connection[Any]) -> None:
    mid = queue(conn)
    for sql in ("UPDATE customer.messages_outbox SET template = 'legal_change' WHERE id = %s",
                "UPDATE customer.messages_outbox SET params = '{}' WHERE id = %s",
                "UPDATE customer.messages_outbox SET user_id = user_id + 1 WHERE id = %s",
                "DELETE FROM customer.messages_outbox WHERE id = %s"):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(sql, (mid,))
        conn.rollback()
    conn.execute("UPDATE customer.messages_outbox SET status = 'suppressed', last_error = 'x' WHERE id = %s", (mid,))
    conn.commit()
    with pytest.raises(psycopg.errors.CheckViolation):  # 'sent' needs the provider's id and the moment
        conn.execute("UPDATE customer.messages_outbox SET status = 'sent' WHERE id = %s", (mid,))
    conn.rollback()


# ── the messenger ─────────────────────────────────────────────────────────────────────

def test_a_message_leaves_with_the_address_and_the_name_of_that_moment(conn: psycopg.Connection[Any]) -> None:
    mid = queue(conn, key="test:moment")
    conn.execute("UPDATE auth.users SET display_name = 'Zacarías Q.' WHERE email = %s", (READER,))
    conn.commit()
    fake = FakeProvider("re-id-1")
    report = outbox.dispatch(conn, fake, at=NOW)
    assert report.sent == 1 and report.failed == report.retried == 0
    [sent] = fake.sent
    assert sent.to == READER and "Hola, Zacarías Q." in sent.text and "(n.º 7)" in sent.text
    assert sent.idempotency_key == f"test:moment@{int(message(conn, mid)['created_at'].timestamp())}"
    assert sent.tags == {"category": "privacy", "template": "privacy_request_answered"}
    row = message(conn, mid)
    assert row["status"] == "sent" and row["provider_id"] == "re-id-1" and row["attempts"] == 1
    assert row["sent_at"] == NOW and row["last_error"] is None
    assert outbox.dispatch(conn, FakeProvider(), at=NOW).sent == 0, "a sent message is not sent again"


def test_retries_follow_the_schedule_and_then_the_message_fails(conn: psycopg.Connection[Any]) -> None:
    mid = queue(conn)
    at = NOW
    gaps = []
    for attempt in range(1, outbox.MAX_ATTEMPTS + 1):
        report = outbox.dispatch(conn, FakeProvider(ProviderError("retry", "resend 503 service_unavailable")), at=at)
        row = message(conn, mid)
        assert row["attempts"] == attempt and row["last_error"] == "resend 503 service_unavailable"
        if attempt < outbox.MAX_ATTEMPTS:
            assert report.retried == 1 and row["status"] == "queued"
            gaps.append(row["next_attempt_at"] - at)
            assert outbox.dispatch(conn, FakeProvider(), at=row["next_attempt_at"] - timedelta(seconds=1)).sent == 0
            at = row["next_attempt_at"]
        else:
            assert report.failed == 1 and row["status"] == "failed"
    assert gaps == list(outbox.RETRY_DELAYS)


def test_a_permanent_refusal_fails_at_once_and_a_broken_configuration_stops_the_pass(
        conn: psycopg.Connection[Any]) -> None:
    bad, good = queue(conn), queue(conn)
    report = outbox.dispatch(conn, FakeProvider(ProviderError("permanent", "resend 422 validation_error"), "ok-2"),
                             at=NOW)
    assert report.failed == 1 and report.sent == 1
    assert message(conn, bad)["status"] == "failed" and message(conn, good)["status"] == "sent"
    first, second = queue(conn), queue(conn)
    fake = FakeProvider(ProviderError("config", "resend 403 validation_error"))
    report = outbox.dispatch(conn, fake, at=NOW)
    assert report.retried == 1 and report.stopped == "resend 403 validation_error" and len(fake.sent) == 1
    assert message(conn, first)["attempts"] == 1 and message(conn, second)["attempts"] == 0


def test_the_providers_daily_quota_waits_for_midnight_without_spending_an_attempt(
        conn: psycopg.Connection[Any]) -> None:
    mid, other = queue(conn), queue(conn)
    report = outbox.dispatch(conn, FakeProvider(ProviderError("quota_day", "resend 429 daily_quota_exceeded")), at=NOW)
    row = message(conn, mid)
    assert report.deferred == 1 and report.stopped == "resend 429 daily_quota_exceeded"
    assert row["attempts"] == 0 and row["status"] == "queued"
    assert row["next_attempt_at"] == datetime(2026, 10, 28, 0, 5, tzinfo=UTC)
    assert message(conn, other)["attempts"] == 0


def test_the_daily_cap_keeps_the_rest_queued(conn: psycopg.Connection[Any]) -> None:
    first, second = queue(conn), queue(conn)
    report = outbox.dispatch(conn, FakeProvider(), at=NOW, cap=1)
    assert report.sent == 1 and report.capped
    assert {message(conn, first)["status"], message(conn, second)["status"]} == {"sent", "queued"}
    assert outbox.dispatch(conn, FakeProvider(), at=NOW + timedelta(hours=1), cap=1).sent == 0
    assert outbox.dispatch(conn, FakeProvider(), at=NOW + timedelta(days=1), cap=1).sent == 1


def test_the_readers_choices_and_the_address_stop_what_they_must(
        conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    support = Template("test_support_note", "support", ("ticket",), "/profile",
                       es=Copy("Respuesta", ("Hola, {name}.", "Te respondimos ({ticket}).")),
                       en=Copy("Answer", ("Hello, {name}.", "We answered ({ticket}).")),
                       values=lambda p, _locale: {"ticket": p["ticket"]}, sample=(("ticket", "1"),))
    monkeypatch.setitem(templates.TEMPLATES, support.name, support)
    uid = user_id(conn, READER)

    def both() -> tuple[int, int]:
        return (queue(conn, template="test_support_note", params={"ticket": "1"}), queue(conn))

    conn.execute("INSERT INTO customer.preferences (user_id, email_off) VALUES (%s, '{support}')", (uid,))
    conn.commit()
    optional, mandatory = both()
    assert outbox.dispatch(conn, FakeProvider(), at=NOW).suppressed == 1
    assert message(conn, optional)["status"] == "suppressed"
    assert message(conn, optional)["last_error"] == "switched off by the reader"
    assert message(conn, mandatory)["status"] == "sent"

    conn.execute("UPDATE customer.preferences SET email_off = '{}', email_status = 'complained', "
                 "email_status_at = now() WHERE user_id = %s", (uid,))
    conn.commit()
    optional, mandatory = both()
    outbox.dispatch(conn, FakeProvider(), at=NOW)
    assert message(conn, optional)["last_error"] == "address complained"
    assert message(conn, mandatory)["status"] == "sent"

    conn.execute("UPDATE customer.preferences SET email_status = 'bounced' WHERE user_id = %s", (uid,))
    conn.commit()
    optional, mandatory = both()
    fake = FakeProvider()
    assert outbox.dispatch(conn, fake, at=NOW).suppressed == 2 and fake.sent == []
    assert message(conn, mandatory)["last_error"] == "address bounced"


def test_two_messengers_never_send_the_same_message(fresh: str, conn: psycopg.Connection[Any]) -> None:
    first, second = queue(conn), queue(conn)
    with psycopg.connect(fresh) as other:
        other.execute("SELECT 1 FROM customer.messages_outbox WHERE id = %s FOR UPDATE", (first,))
        fake = FakeProvider()
        report = outbox.dispatch(conn, fake, at=NOW)
        other.rollback()
    assert report.sent == 1 and message(conn, second)["status"] == "sent"
    assert message(conn, first)["status"] == "queued"


def test_the_messenger_runs_alone(fresh: str) -> None:
    lock = runner.try_lock(fresh)
    assert lock is not None
    try:
        assert runner.try_lock(fresh) is None
    finally:
        lock.close()
    again = runner.try_lock(fresh)
    assert again is not None
    again.close()


def test_a_cycle_is_one_row_of_the_ledger_and_sends_only_when_switched_on(
        fresh: str, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mid = queue(conn)
    stop = threading.Event()
    alive = tmp_path / "alive"
    fake = FakeProvider()
    totals = runner.run_cycle(fresh, fake, stop, tick_s=0.01, cycle_s=0.05, alive_file=alive)
    assert totals.sent == 0 and fake.sent == [] and message(conn, mid)["status"] == "queued"
    assert runner.alive(alive)
    monkeypatch.setenv("FBI_EMAIL_SEND", "1")
    totals = runner.run_cycle(fresh, fake, stop, tick_s=0.01, cycle_s=0.05, alive_file=alive)
    assert totals.sent == 1 and message(conn, mid)["status"] == "sent"
    stop.set()
    runner.run_cycle(fresh, fake, stop, tick_s=0.01, cycle_s=0.05, alive_file=alive)
    rows = conn.execute("SELECT status, notes, rows_updated FROM raw.ingestion_runs WHERE job_type = 'messenger_cycle' "
                        "ORDER BY id").fetchall()
    conn.commit()
    assert [r[0] for r in rows] == ["completed", "completed", "interrupted"]
    assert rows[0][1].startswith("sending off") and "sent 1" in rows[1][1] and rows[1][2] == 1


# ── the webhook ───────────────────────────────────────────────────────────────────────

def sent_message(conn: psycopg.Connection[Any], email: str = READER) -> tuple[int, str]:
    mid = queue(conn, email)
    provider_id = f"re-{uuid.uuid4().hex}"
    outbox.dispatch(conn, FakeProvider(provider_id), at=NOW)
    return mid, provider_id


def event(kind: str, provider_id: str, **data: Any) -> dict[str, Any]:
    return {"type": kind, "created_at": "2026-10-27T15:00:00Z",
            "data": {"email_id": provider_id, "to": [READER], "subject": "x", **data}}


def deliverability(conn: psycopg.Connection[Any], email: str = READER) -> str | None:
    row = conn.execute("SELECT email_status FROM customer.preferences WHERE user_id = %s",
                       (user_id(conn, email),)).fetchone()
    conn.commit()
    return str(row[0]) if row else None


def test_a_hard_bounce_is_recorded_once_and_stops_the_address(conn: psycopg.Connection[Any]) -> None:
    mid, provider_id = sent_message(conn)
    temporary = webhooks.apply_event(conn, event("email.bounced", provider_id, bounce={"type": "Temporary"}))
    conn.commit()
    assert not temporary.applied and message(conn, mid)["status"] == "sent" and deliverability(conn) is None
    outcome = webhooks.apply_event(conn, event("email.bounced", provider_id,
                                               bounce={"type": "Permanent", "subType": "Suppressed",
                                                       "message": f"{READER} does not exist"}))
    conn.commit()
    assert outcome.applied and outcome.status == "bounced"
    row = message(conn, mid)
    assert row["status"] == "bounced" and row["last_error"] == "bounced: Permanent/Suppressed"
    assert READER not in str(row)
    assert deliverability(conn) == "bounced"
    assert not webhooks.apply_event(conn, event("email.bounced", provider_id)).applied, "the same event twice"
    conn.commit()
    later = queue(conn)
    assert outbox.dispatch(conn, FakeProvider(), at=NOW).suppressed == 1
    assert message(conn, later)["last_error"] == "address bounced"


def test_a_complaint_stops_only_what_the_reader_can_switch_off_and_unknown_events_change_nothing(
        conn: psycopg.Connection[Any]) -> None:
    mid, provider_id = sent_message(conn)
    assert webhooks.apply_event(conn, event("email.complained", provider_id)).applied
    conn.commit()
    assert message(conn, mid)["status"] == "complained" and deliverability(conn) == "complained"
    for kind in ("email.delivered", "email.opened", "email.clicked", "email.sent"):
        assert not webhooks.apply_event(conn, event(kind, provider_id)).applied
    assert not webhooks.apply_event(conn, event("email.bounced", "re-nobody")).applied
    assert not webhooks.apply_event(conn, {"type": "email.bounced"}).applied
    conn.commit()
    _, other = sent_message(conn, READER_EN)
    assert webhooks.apply_event(conn, event("email.suppressed", other)).status == "suppressed"
    conn.commit()
    assert deliverability(conn, READER_EN) == "bounced"


def signed(body: bytes, *, ts: int | None = None) -> dict[str, str]:
    stamp = str(ts if ts is not None else int(time.time()))
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    return {**SAME_SITE, "svix-id": msg_id, "svix-timestamp": stamp,
            "svix-signature": f"v1,{webhooks.sign(WEBHOOK_SECRET, msg_id, stamp, body)}"}


def test_the_webhook_believes_only_signed_fresh_events(conn: psycopg.Connection[Any],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.app import create_app

    mid, provider_id = sent_message(conn)
    body = json.dumps(event("email.bounced", provider_id, bounce={"type": "Permanent"})).encode()
    api = TestClient(create_app())
    assert api.post("/api/v1/webhooks/resend", content=body, headers=signed(body)).status_code == 404
    monkeypatch.setenv("FBI_RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    assert api.post("/api/v1/webhooks/resend", content=body).status_code == 401
    assert api.post("/api/v1/webhooks/resend", content=body,
                    headers=signed(body, ts=int(time.time()) - 600)).status_code == 401
    tampered = body.replace(b"Permanent", b"Temporary")
    assert api.post("/api/v1/webhooks/resend", content=tampered, headers=signed(body)).status_code == 401
    assert message(conn, mid)["status"] == "sent"
    assert api.post("/api/v1/webhooks/resend", content=b"not json", headers=signed(b"not json")).status_code == 400
    r = api.post("/api/v1/webhooks/resend", content=body, headers=signed(body))
    assert r.status_code == 204, r.text
    assert message(conn, mid)["status"] == "bounced"


# ── the reader and the owner over HTTP ────────────────────────────────────────────────

def test_the_reader_chooses_the_optional_categories_only(fresh: str) -> None:
    c = client(READER)
    prefs = c.get("/api/v1/me/preferences").json()
    assert prefs["email_status"] == "ok" and prefs["email_status_at"] is None
    assert {e["category"]: (e["on"], e["locked"]) for e in prefs["email"]} == {
        "account": (True, True), "security": (True, True), "membership": (True, False), "support": (True, False),
        "privacy": (True, True), "legal": (True, True)}
    r = c.patch("/api/v1/me/preferences", json={"email": {"membership": False}})
    assert r.status_code == 200, r.text
    assert {e["category"]: e["on"] for e in r.json()["email"]}["membership"] is False
    refused = c.patch("/api/v1/me/preferences", json={"email": {"privacy": False}})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "mandatory_category"
    assert c.patch("/api/v1/me/preferences", json={"email": {"marketing": True}}).status_code == 422
    assert c.patch("/api/v1/me/preferences", json={"email": {"membership": True}}).json()["email"][2]["on"] is True
    no_header = TestClient(c.app)
    no_header.cookies = c.cookies
    assert no_header.patch("/api/v1/me/preferences", json={"email": {"support": False}}).status_code == 403
    assert TestClient(c.app, headers=SAME_SITE).get("/api/v1/me/preferences").status_code == 401


def test_a_privacy_request_and_its_answer_queue_their_messages_without_their_words(fresh: str) -> None:
    reader, owner = client(READER), client(OWNER)
    r = reader.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query", "message": SECRET_TEXT})
    assert r.status_code == 201, r.text
    ticket = r.json()
    a = owner.post(f"/api/v1/admin/privacy-requests/{ticket['id']}/answer",
                   json={"body": OWNER_TEXT, "status": "answered"})
    assert a.status_code == 200, a.text
    with psycopg.connect(fresh) as conn:
        rows = conn.execute("SELECT template, params, dedup_key FROM customer.messages_outbox ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["privacy_request_received", "privacy_request_answered"]
    assert rows[0][1] == {"request": "privacy_query", "ticket": str(ticket["id"]), "deadline": ticket["due_on"]}
    assert rows[0][2] == f"privacy_request_received:{ticket['id']}"
    assert rows[1][1] == {"request": "privacy_query", "ticket": str(ticket["id"])}
    assert SECRET_TEXT not in str(rows) and OWNER_TEXT not in str(rows)

    queue_view = owner.get("/api/v1/admin/messages").json()
    assert queue_view["sending"] is False and queue_view["counts"]["queued"] == 2
    assert [m["template"] for m in queue_view["messages"]] == ["privacy_request_answered", "privacy_request_received"]
    assert queue_view["messages"][0]["user_email"] == READER
    receipt = queue_view["messages"][1]["id"]
    preview = owner.get(f"/api/v1/admin/messages/{receipt}/preview").json()
    assert preview["link"] == "https://predigol.example/profile#privacy"
    assert READER_NAME in preview["text"] and SECRET_TEXT not in preview["text"] + preview["html"]
    assert owner.get("/api/v1/admin/messages", params={"status": "sent"}).json()["messages"] == []
    assert reader.get("/api/v1/admin/messages").status_code == 403
    assert owner.get("/api/v1/admin/messages/999999/preview").status_code == 404


# ── the owner's notices ───────────────────────────────────────────────────────────────

def synthetic_run(conn: psycopg.Connection[Any], status: str, at: datetime) -> None:
    conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, params, started_at, finished_at, status, "
                 "last_error) VALUES ('a5-synthetic', 'synthetic_journey', '{}'::jsonb, %s, %s, %s, %s)",
                 (at, at + timedelta(seconds=20), status, "home: HTTP 502" if status == "failed" else None))
    conn.commit()


def test_the_owners_notices_carry_counts_and_a_link_never_a_readers_data(fresh: str,
                                                                        conn: psycopg.Connection[Any]) -> None:
    privacy.open_request(user_id(conn, READER), "privacy_query", SECRET_TEXT)
    today = privacy.bogota_today(datetime.now(UTC))
    conn.execute("""
        INSERT INTO customer.support_tickets (user_id, kind, opened_at, due_on) VALUES (%s, 'privacy_claim', now(), %s)
    """, (user_id(conn, READER), workdays.add_business_days(today, 1)))
    failed = queue(conn)
    conn.execute("UPDATE customer.messages_outbox SET status = 'failed', attempts = 6, "
                 "last_error = 'resend 422 validation_error' WHERE id = %s", (failed,))
    conn.commit()
    stuck = queue(conn)
    with psycopg.connect(fresh) as maint:
        maint.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        maint.execute("UPDATE customer.messages_outbox SET created_at = now() - interval '2 hours' WHERE id = %s",
                      (stuck,))
    start = datetime.now(UTC) - timedelta(hours=1)
    synthetic_run(conn, "failed", start)
    synthetic_run(conn, "failed", start + timedelta(minutes=15))

    drafts = notices.collect(conn, at=datetime.now(UTC), sending=True, provider=False)
    conn.commit()
    assert sorted(d.kind for d in drafts) == ["outbox_failing", "privacy_due", "synthetic_failed", "ticket_new"]
    forbidden = (READER, READER.split("@")[0], READER_NAME, "Zacarías", SECRET_TEXT, "zzq-7781", READER_EN, OTHER)
    for d in drafts:
        text = " ".join((d.title, d.body, json.dumps(d.payload, ensure_ascii=False)))
        assert not [f for f in forbidden if f in text], (d.kind, text)
        assert "https://predigol.example/admin/" in d.body, d.kind
    by_kind = {d.kind: d for d in drafts}
    assert "2 solicitudes nuevas" in by_kind["ticket_new"].title
    assert "falta la clave o el remitente" in by_kind["outbox_failing"].body
    assert "1 correo falló" in by_kind["outbox_failing"].body and "1 correo espera" in by_kind["outbox_failing"].body
    assert "resend 422 validation_error" in by_kind["outbox_failing"].body
    assert "2 veces seguidas" in by_kind["synthetic_failed"].title
    assert notices.write(conn, drafts) == 4
    assert notices.write(conn, notices.collect(conn, at=datetime.now(UTC), sending=True, provider=False)) == 0
    rows = conn.execute("SELECT kind, status FROM audit.notifications WHERE kind IN ('ticket_new', 'privacy_due', "
                        "'outbox_failing', 'synthetic_failed')").fetchall()
    conn.commit()
    assert sorted(rows) == sorted((k, "queued") for k in by_kind), "queued for the worker's notifier"


def test_a_new_ticket_is_one_notice_and_the_journey_needs_two_failures_in_a_row(
        conn: psycopg.Connection[Any]) -> None:
    privacy.open_request(user_id(conn, READER), "privacy_query", "uno")
    assert notices.write(conn, notices.ticket_new(conn)) == 1
    assert notices.ticket_new(conn) == []
    privacy.open_request(user_id(conn, OTHER), "privacy_query", "dos")
    [second] = notices.ticket_new(conn)
    assert second.payload["count"] == 1 and "1 solicitud nueva" in second.title
    start = datetime.now(UTC) - timedelta(hours=2)
    synthetic_run(conn, "failed", start)
    assert notices.synthetic_failed(conn) == []
    synthetic_run(conn, "completed", start + timedelta(minutes=15))
    synthetic_run(conn, "failed", start + timedelta(minutes=30))
    assert notices.synthetic_failed(conn) == [], "a pass in between: no streak"
    synthetic_run(conn, "failed", start + timedelta(minutes=45))
    [streak] = notices.synthetic_failed(conn)
    synthetic_run(conn, "failed", start + timedelta(minutes=60))
    [longer] = notices.synthetic_failed(conn)
    assert streak.dedup_key == longer.dedup_key and longer.payload["runs"] == 3
    assert notices.outbox_failing(conn, at=datetime.now(UTC), sending=False, provider=False) == []


# ── a material change of a legal text ─────────────────────────────────────────────────

def test_a_published_material_change_is_one_message_per_reader_who_accepted_the_text_before(
        conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    real = legal.register()

    def published(*versions: tuple[str, bool]) -> tuple[legal.Version, ...]:
        base = real["terms"][0]
        return tuple(legal.Version(version=v, date=v[:10], draft=False, material=m, changes=base.changes,
                                   sha256=base.sha256) for v, m in versions)

    fake: dict[legal.DocumentName, tuple[legal.Version, ...]] = {
        "terms": published(("2026-11-01", True), ("2026-12-01", True)),
        "privacy": published(("2026-11-01", True)),
        "responsible_gaming": published(("2026-11-01", True)),
    }
    monkeypatch.setattr(legal, "register", lambda: fake)
    legal.load.cache_clear()  # load() is cached: the texts of the fake register must not outlive this test
    request.addfinalizer(legal.load.cache_clear)
    monkeypatch.setenv(consents.GATE_ENV, "1")
    accepted_before = (READER, READER_EN, OWNER, ROBOT)
    for email in accepted_before:
        conn.execute("""
            INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, statement, source)
            VALUES (%s, 'terms', true, 'terms', '2026-11-01', %s, 'es', 'Acepto', 'gate')
        """, (user_id(conn, email), "0" * 64))
    conn.execute("""
        INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, statement, source)
        VALUES (%s, 'terms', true, 'terms', '2026-12-01', %s, 'en', 'I accept', 'gate')
    """, (user_id(conn, READER_EN), "0" * 64))
    conn.commit()
    assert enqueue_legal_changes(conn) == 1
    conn.commit()
    rows = conn.execute("SELECT user_id, template, locale, params, dedup_key FROM customer.messages_outbox").fetchall()
    conn.commit()
    assert rows == [(user_id(conn, READER), "legal_change", "es", {"document": "terms", "version": "2026-12-01"},
                     f"legal_change:terms:2026-12-01:{user_id(conn, READER)}")]
    assert enqueue_legal_changes(conn) == 0, "once per reader and version"
    conn.rollback()
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    fake["terms"] = published(("2026-11-01", True), ("2026-12-01", False))
    assert enqueue_legal_changes(conn) == 0, "a change that is not material asks no one"
    fake["terms"] = published(("2026-12-01", True))
    assert enqueue_legal_changes(conn) == 0, "the first published version is not a change"
    monkeypatch.delenv(consents.GATE_ENV)
    fake["terms"] = published(("2026-11-01", True), ("2027-01-01", True))
    assert enqueue_legal_changes(conn) == 0, "without the gate the e-mail would promise what does not happen"
    conn.rollback()


def test_a_ticket_due_today_or_late_is_said_once_a_day(conn: psycopg.Connection[Any]) -> None:
    today = privacy.bogota_today(datetime.now(UTC))
    conn.execute("""
        INSERT INTO customer.support_tickets (user_id, kind, opened_at, due_on)
        VALUES (%s, 'privacy_query', now() - interval '20 days', %s), (%s, 'privacy_claim', now(), %s)
    """, (user_id(conn, READER), today - timedelta(days=1), user_id(conn, OTHER),
          workdays.add_business_days(today, 10)))
    conn.commit()
    [due] = notices.privacy_due(conn, at=datetime.now(UTC))
    assert due.payload == {"soon": 0, "late": 1} and "ya venció" in due.body
    assert due.dedup_key == f"privacy_due:{today.isoformat()}"
    assert isinstance(today, date)


def test_the_operators_real_test_goes_through_the_queue(fresh: str, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import email_test

    assert email_test.main(["queue", "--user", "nobody@example.org"]) == 1
    assert email_test.main(["queue", "--user", READER.upper()]) == 0
    out = capsys.readouterr().out
    assert "queued message" in out and "OFF" in out
    mid = int(out.split("queued message ")[1].split()[0])
    assert email_test.main(["status", str(mid)]) == 0
    status = capsys.readouterr().out
    assert "queued, 0 attempt(s)" in status and READER not in status and READER_NAME not in status
    assert email_test.main(["status", "999999"]) == 1

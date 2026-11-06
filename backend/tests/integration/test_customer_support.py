"""A reader's tickets and the owner's inbox against the migrated database (plan UX, A14; section 32 of the plan).

* A ticket over HTTP, signed in for real: its category, its first message and the context the page attached as the
  server keeps it - and, in the same transaction, the receipt queued for the e-mail and the product event.
* Each reader reads and touches only their own tickets (another reader's is «not found»); no session, 401; another site,
  403; the inbox is the owner's alone (403 for a reader).
* The thread: a reader's message makes it wait for PrediGol again; «Ya está resuelto» with how easy it was; that answer
  once; a closed ticket takes no message. The limits: 3 open, 10 in 24 hours.
* The owner: the support tickets and the privacy requests in one inbox, waiting first by priority, with their counts and
  filters; an answer written in PrediGol queues the e-mail, a note of a talk on WhatsApp does not; a privacy request keeps
  its own rules.
* The owner's notices: an urgent ticket at once, the others in the morning's count - never a reader's address or words.
* What the account keeps: the tickets in the reader's export; the open ones closed when the account is anonymised.
* The switch: FBI_SUPPORT=0 takes the writing away and leaves the reading.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import anonymize, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import privacy, support
from fbi.messaging import notices
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

READER = "lectora.a14@example.org"
OTHER = "otro.a14@example.org"
OWNER = "owner.a14@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
SECRET_TEXT = "El marcador del zzq-1414 está mal desde ayer"
"""Words of a reader that must never reach a notice or an e-mail's queue."""
CONTEXT = {"route": "/matches/1414", "request_id": "a1b2c3d4e5f6", "web_version": "2026.10.26+ab12cd3",
           "device": "phone", "pwa": True, "match_id": 1414}


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.messages_outbox", "customer.preferences",
                          "customer.favorites", "customer.ticket_messages", "customer.support_tickets",
                          "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind = 'ticket_new'")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_WEB_BASE_URL", "https://predigol.example")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email, role in ((READER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    with psycopg.connect(database, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.messages_outbox", "customer.ticket_messages",
                          "customer.support_tickets"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind = 'ticket_new'")
    for name in (support.SWITCH, "FBI_SUPPORT_WHATSAPP", "FBI_EMAIL_REPLY_TO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def code(r: Any) -> str:
    body = r.json()
    return str(body.get("error", {}).get("code") or body.get("detail"))


def open_one(c: TestClient, category: str = "technical", text: str = "No carga Inicio",
             context: dict[str, Any] | None = None) -> dict[str, Any]:
    r = c.post("/api/v1/me/support/tickets", json={"category": category, "text": text,
                                                   **({"context": context} if context else {})})
    assert r.status_code == 201, r.text
    return dict(r.json())


# ── a ticket ─────────────────────────────────────────────────────────────────────────


def test_a_ticket_arrives_with_its_context_its_receipt_and_its_event_in_one_go(fresh: str) -> None:
    reader = client(READER)
    created = open_one(reader, "wrong_data", SECRET_TEXT, CONTEXT)
    assert (created["category"], created["priority"], created["status"], created["answered"]) == (
        "wrong_data", "medium", "open", False)
    opened = datetime.fromisoformat(created["opened_at"])
    assert datetime.fromisoformat(created["respond_by"]) == opened + timedelta(hours=48), "medium: 48 hours"
    assert [(m["author"], m["body"], m["channel"]) for m in created["messages"]] == [("customer", SECRET_TEXT, "web")]
    with psycopg.connect(fresh) as conn:
        row = conn.execute("SELECT kind, category, context, effort FROM customer.support_tickets WHERE id = %s",
                           (created["id"],)).fetchone()
        assert row == ("support", "wrong_data", CONTEXT, None), "the context kept as the page sent it"
        queued = conn.execute("SELECT template, category, params, dedup_key FROM customer.messages_outbox").fetchall()
        assert len(queued) == 1
        template, category, params, key = queued[0]
        assert (template, category, key) == ("support_ticket_received", "support",
                                             f"support_ticket_received:{created['id']}")
        assert params == {"ticket": str(created["id"]), "category": "wrong_data",
                          "by": (opened + timedelta(hours=48)).isoformat()}
        assert SECRET_TEXT not in json.dumps(params), "the queue never keeps a word of the thread"
        events = conn.execute("SELECT name, props FROM customer.product_events").fetchall()
        assert events == [("ticket_created", {"kind": "wrong_data"})]
    state = reader.get("/api/v1/me/support").json()
    assert state["enabled"] is True and state["contact"] == {"whatsapp": None, "email": None, "channels": ["tickets"], "hours": None}
    assert [c["category"] for c in state["categories"]] == list(support.CATEGORIES)
    assert {c["category"]: c["first_answer"] for c in state["categories"]} == {
        "access": "same_day", "account": "24h", "technical": "24h", "wrong_data": "48h", "suggestion": "week",
        "complaint": "24h"}
    assert [t["id"] for t in state["tickets"]] == [created["id"]]
    assert (state["max_text"], state["max_open"]) == (2000, 3)


def test_the_context_refuses_what_is_not_its_own(fresh: str) -> None:
    reader = client(READER)
    for bad in ({"route": "/reset-password?token=abc"}, {"request_id": "not-an-id"}, {"email": READER},
                {"match_id": 0}, {"device": "watch"}):
        r = reader.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "x", "context": bad})
        assert r.status_code == 422, (bad, r.text)
    r = reader.post("/api/v1/me/support/tickets", json={"category": "privacy", "text": "¿Qué datos tienen de mí?"})
    assert r.status_code == 422, "a privacy question is a privacy request"
    link = open_one(reader, context={"route": "/reset-password/abc123"})
    with psycopg.connect(fresh) as conn:
        assert conn.execute("SELECT context FROM customer.support_tickets WHERE id = %s", (link["id"],)).fetchone() == (
            {"route": "/reset-password"},), "a one-use link's page keeps only its name"


def test_each_reader_reads_and_touches_only_their_own(fresh: str) -> None:
    reader, other = client(READER), client(OTHER)
    mine = open_one(reader)
    assert other.get("/api/v1/me/support").json()["tickets"] == []
    for path, body in (("/messages", {"text": "hola"}), ("/close", {}), ("/effort", {"effort": 3})):
        r = other.post(f"/api/v1/me/support/tickets/{mine['id']}{path}", json=body)
        assert (r.status_code, code(r)) == (404, "not_found"), path
    assert other.post("/api/v1/me/support/tickets/999999/close", json={}).status_code == 404, "the same as none"
    anonymous = TestClient(create_app(), headers=SAME_SITE)
    assert anonymous.get("/api/v1/me/support").status_code == 401
    assert anonymous.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "x"}).status_code == 401
    cross_site = TestClient(create_app())
    cross_site.cookies = reader.cookies
    r = cross_site.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "x"})
    assert r.status_code == 403, "another site cannot write for the reader"
    assert reader.get("/api/v1/admin/support").status_code == 403, "the inbox is the owner's alone"
    assert reader.post(f"/api/v1/admin/support/{mine['id']}/answer", json={"body": "x"}).status_code == 403


def test_the_thread_the_close_and_how_easy_it_was(fresh: str) -> None:
    reader, owner = client(READER), client(OWNER)
    t = open_one(reader)
    answered = owner.post(f"/api/v1/admin/support/{t['id']}/answer",
                          json={"body": "¿Desde qué teléfono?", "status": "answered"})
    assert answered.status_code == 200, answered.text
    mine = reader.get("/api/v1/me/support").json()["tickets"][0]
    assert (mine["status"], mine["answered"], mine["respond_by"]) == ("answered", True, None)
    again = reader.post(f"/api/v1/me/support/tickets/{t['id']}/messages", json={"text": "Un Android"}).json()
    assert again["status"] == "open", "the reader wrote: it waits for PrediGol again"
    assert [m["author"] for m in again["messages"]] == ["customer", "owner", "customer"]
    early = reader.post(f"/api/v1/me/support/tickets/{t['id']}/effort", json={"effort": 5})
    assert (early.status_code, code(early)) == (409, "not_closed")
    done = reader.post(f"/api/v1/me/support/tickets/{t['id']}/close", json={"effort": 4}).json()
    assert (done["status"], done["effort"]) == ("closed", 4) and done["closed_at"]
    for path, body, expected in (("/messages", {"text": "otra cosa"}, "ticket_closed"), ("/close", {}, "ticket_closed"),
                                 ("/effort", {"effort": 2}, "already_rated")):
        r = reader.post(f"/api/v1/me/support/tickets/{t['id']}{path}", json=body)
        assert (r.status_code, code(r)) == (409, expected), path
    closed_by_owner = open_one(reader, "suggestion", "Un modo oscuro más oscuro")
    owner.post(f"/api/v1/admin/support/{closed_by_owner['id']}/answer", json={"body": "Anotado", "status": "closed"})
    rated = reader.post(f"/api/v1/me/support/tickets/{closed_by_owner['id']}/effort", json={"effort": 5}).json()
    assert (rated["status"], rated["effort"]) == ("closed", 5), "asked once it is closed, by either side"
    assert reader.post(f"/api/v1/me/support/tickets/{t['id']}/close", json={"effort": 6}).status_code == 422


def test_three_open_and_ten_a_day(fresh: str) -> None:
    reader = client(READER)
    tickets = [open_one(reader, text=f"Problema {i}") for i in range(3)]
    r = reader.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "el cuarto"})
    assert (r.status_code, code(r)) == (409, "too_many_open")
    for t in tickets:
        reader.post(f"/api/v1/me/support/tickets/{t['id']}/close", json={})
    for i in range(7):
        t = open_one(reader, text=f"Otro {i}")
        reader.post(f"/api/v1/me/support/tickets/{t['id']}/close", json={})
    r = reader.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "el undécimo"})
    assert (r.status_code, code(r)) == (429, "too_many_tickets")


# ── the owner ────────────────────────────────────────────────────────────────────────


def test_the_inbox_waiting_first_by_priority_with_the_privacy_requests_and_their_deadline(fresh: str) -> None:
    reader, other, owner = client(READER), client(OTHER), client(OWNER)
    suggestion = open_one(reader, "suggestion", "Más ligas")
    technical = open_one(reader, "technical", "Un error")
    urgent = open_one(other, "access", "Pagué y no entro")
    request = privacy.open_request(uid(fresh, OTHER), "privacy_query", "¿Qué datos guardan?")
    answered = open_one(other, "complaint", "No me gustó")
    owner.post(f"/api/v1/admin/support/{answered['id']}/answer", json={"body": "Lo sentimos", "status": "answered"})
    inbox = owner.get("/api/v1/admin/support").json()
    order = [t["id"] for t in inbox["tickets"]]
    assert order == [urgent["id"], technical["id"], request.id, suggestion["id"], answered["id"]], (
        "waiting first; then urgent, high (the oldest first), low; the answered ones after")
    assert inbox["counts"] == {"open": 5, "waiting": 4, "late": 0, "urgent": 1}
    by_id = {t["id"]: t for t in inbox["tickets"]}
    assert by_id[urgent["id"]]["email"] == OTHER and by_id[urgent["id"]]["priority"] == "urgent"
    assert request.due_on is not None
    assert by_id[request.id]["category"] == "privacy" and by_id[request.id]["deadline"] == request.due_on.isoformat()
    assert by_id[request.id]["respond_by"] is None and by_id[technical["id"]]["respond_by"]
    filtered = owner.get("/api/v1/admin/support", params={"category": "privacy"}).json()["tickets"]
    assert [t["id"] for t in filtered] == [request.id]
    high = owner.get("/api/v1/admin/support", params={"priority": "high"}).json()["tickets"]
    assert {t["id"] for t in high} == {technical["id"], request.id, answered["id"]}
    waiting = owner.get("/api/v1/admin/support", params={"status": "waiting"}).json()["tickets"]
    assert answered["id"] not in [t["id"] for t in waiting]
    assert owner.get("/api/v1/admin/support", params={"status": "nope"}).status_code == 422
    r = owner.post(f"/api/v1/admin/support/{request.id}/answer", json={"body": "x"})
    assert (r.status_code, code(r)) == (409, "privacy_request"), "a privacy request is answered with its legal rules"


def test_an_answer_written_here_is_told_by_e_mail_a_note_of_whatsapp_is_not(fresh: str) -> None:
    reader, owner = client(READER), client(OWNER)
    t = open_one(reader)
    note = owner.post(f"/api/v1/admin/support/{t['id']}/answer",
                      json={"body": "Hablamos por WhatsApp: era la caché", "status": "open", "channel": "whatsapp"})
    assert note.status_code == 200, note.text
    assert note.json()["messages"][-1]["channel"] == "whatsapp" and note.json()["status"] == "open"
    with psycopg.connect(fresh) as conn:
        assert conn.execute("SELECT count(*) FROM customer.messages_outbox WHERE template = 'support_ticket_answered'"
                            ).fetchone() == (0,), "they talked already: no e-mail"
    done = owner.post(f"/api/v1/admin/support/{t['id']}/answer",
                      json={"body": "Ya quedó: borra la caché del navegador", "status": "closed"}).json()
    assert (done["status"], done["waiting"], done["late"]) == ("closed", False, False)
    with psycopg.connect(fresh) as conn:
        rows = conn.execute("SELECT params, dedup_key FROM customer.messages_outbox "
                            "WHERE template = 'support_ticket_answered'").fetchall()
    assert len(rows) == 1 and rows[0][0] == {"ticket": str(t["id"]), "category": "technical"}
    again = owner.post(f"/api/v1/admin/support/{t['id']}/answer", json={"body": "otra"})
    assert (again.status_code, code(again)) == (409, "ticket_closed")
    assert owner.post("/api/v1/admin/support/999999/answer", json={"body": "x"}).status_code == 404


def test_a_late_ticket_shows_as_late(fresh: str) -> None:
    reader, owner = client(READER), client(OWNER)
    t = open_one(reader, "account", "No veo mi membresía")
    with psycopg.connect(fresh, autocommit=True) as conn, conn.transaction():
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("UPDATE customer.support_tickets SET opened_at = now() - interval '25 hours' WHERE id = %s",
                     (t["id"],))
    inbox = owner.get("/api/v1/admin/support").json()
    assert inbox["tickets"][0]["late"] is True and inbox["counts"]["late"] == 1


# ── the owner's notices ──────────────────────────────────────────────────────────────


def test_an_urgent_ticket_is_told_at_once_the_rest_in_the_mornings_count(fresh: str) -> None:
    reader = client(READER)
    open_one(reader, "technical", SECRET_TEXT)
    with psycopg.connect(fresh) as conn:
        assert notices.ticket_new(conn) == [], "a technical ticket waits for the morning"
    open_one(reader, "access", SECRET_TEXT)
    with psycopg.connect(fresh) as conn:
        [now_] = notices.ticket_new(conn)
        assert "1 ticket urgente de acceso" in now_.body and "https://predigol.example/admin/support" in now_.body
        assert notices.write(conn, [now_]) == 1
        assert notices.ticket_new(conn) == [], "told once"
        early = datetime(2026, 10, 27, 11, 0, tzinfo=UTC)  # 06:00 in Bogotá
        assert notices.support_waiting(conn, at=early) == []
        # A fixed morning (08:00 in Bogotá) with the tickets opened half an hour before it: the test must not depend on
        # the hour it runs at (opened at 19:30 in Bogotá, an urgent ticket is due at 23:59 - before «the next morning» -
        # and the count rightly says it is late).
        morning = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("UPDATE customer.support_tickets SET opened_at = %s WHERE kind = 'support'",
                     (morning - timedelta(minutes=30),))
        [count] = notices.support_waiting(conn, at=morning)
        assert count.kind == "ticket_new" and count.payload == {"waiting": 2, "late": 0, "urgent": 1}
        assert "2 tickets de soporte esperan tu respuesta (1 urgente)" in count.body
        assert count.dedup_key == f"ticket_new:waiting:{morning.date().isoformat()}"
        assert notices.write(conn, [count]) == 1 and notices.write(conn, notices.support_waiting(conn, at=morning)) == 0
        forbidden = (READER, READER.split("@")[0], SECRET_TEXT, "zzq-1414")
        for d in (now_, count):
            text = " ".join((d.title, d.body, json.dumps(d.payload, ensure_ascii=False)))
            assert not [f for f in forbidden if f in text], text
        privacy.open_request(uid(fresh, READER), "privacy_query", SECRET_TEXT)
        [request] = notices.ticket_new(conn)
        assert "1 consulta" in request.body, "a privacy request is told at once too, after the watermark"


# ── what the account keeps ───────────────────────────────────────────────────────────


def test_the_export_carries_the_tickets_and_anonymising_closes_the_open_ones(fresh: str) -> None:
    leaving = "se.va.a14@example.org"
    service.create_user_unattended(email=leaving, display_name="se.va", role="USER", password=PASSWORD, language="es",
                                   timezone="America/Bogota")
    reader, owner = client(leaving), client(OWNER)
    t = open_one(reader, "wrong_data", SECRET_TEXT, CONTEXT)
    owner.post(f"/api/v1/admin/support/{t['id']}/answer", json={"body": "Gracias, lo corregimos", "status": "answered"})
    with psycopg.connect(fresh) as conn:
        document = privacy.export(conn, uid(fresh, leaving))
    [kept] = document["support_tickets"]
    assert (kept["category"], kept["context"], kept["status"]) == ("wrong_data", CONTEXT, "answered")
    assert [(m["author"], m["channel"]) for m in kept["messages"]] == [("customer", "web"), ("owner", "web")]
    done = anonymize.anonymise(principal("SUPER_ADMIN", uid(fresh, OWNER)), uid(fresh, leaving), confirm=leaving, ip=None)
    assert done.tickets_closed == 1
    with psycopg.connect(fresh) as conn:
        assert conn.execute("SELECT status, closed_at IS NOT NULL FROM customer.support_tickets WHERE id = %s",
                            (t["id"],)).fetchone() == ("closed", True)
        assert conn.execute("SELECT count(*) FROM customer.ticket_messages WHERE ticket_id = %s",
                            (t["id"],)).fetchone() == (2,), "the thread stays, as a privacy request's"


# ── the switch ───────────────────────────────────────────────────────────────────────


def test_with_the_switch_off_the_writing_goes_and_the_reading_stays(fresh: str,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    reader, owner = client(READER), client(OWNER)
    t = open_one(reader)
    monkeypatch.setenv(support.SWITCH, "0")
    monkeypatch.setenv("FBI_SUPPORT_WHATSAPP", "+57 300 123 4567")
    state = reader.get("/api/v1/me/support").json()
    assert state["enabled"] is False and [x["id"] for x in state["tickets"]] == [t["id"]], "what was written is read"
    assert state["contact"]["whatsapp"] == "573001234567", "the contact stays"
    assert reader.get("/api/v1/auth/me").json()["support"] is False
    r = reader.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "x"})
    assert (r.status_code, code(r)) == (404, "not_available")
    r = reader.post(f"/api/v1/me/support/tickets/{t['id']}/messages", json={"text": "x"})
    assert (r.status_code, code(r)) == (404, "not_available")
    assert owner.post(f"/api/v1/admin/support/{t['id']}/answer", json={"body": "Seguimos"}).status_code == 200, (
        "the owner can still answer what was written")
    public = TestClient(create_app()).get("/api/v1/support/contact")
    assert public.status_code == 200 and public.json() == {"whatsapp": "573001234567", "email": None,
                                                           "channels": ["whatsapp"], "hours": None}
    monkeypatch.setenv(support.HOURS_ENV, "Lun-Vie 9:00-18:00, hora de Bogotá")
    monkeypatch.setenv(support.CHANNELS_ENV, "tickets,whatsapp")
    again = TestClient(create_app()).get("/api/v1/support/contact").json()
    assert again["hours"] == "Lun-Vie 9:00-18:00, hora de Bogotá" and again["channels"] == ["whatsapp"], (
        "with the tickets off only the other named channel is offered")
    monkeypatch.delenv(support.SWITCH)
    assert reader.get("/api/v1/auth/me").json()["support"] is True

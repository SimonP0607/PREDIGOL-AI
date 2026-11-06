"""The account centre in one read (plan UX, B1; section 21 of the plan), against the migrated database and signed in for
real: GET /me/account says what each of the profile's eight blocks says while folded.

* A new reader: the alias, the address, the date the account was made; Spanish and Bogotá; the suggested football; every
  e-mail category on (none leaves while sending is off); no consent owed with the gate off, no request, one session, the
  trial of 14 days; no message; WhatsApp only once the owner gives it.
* What the reader does shows at once: an optional e-mail switched off, a privacy request with its legal deadline, a
  message to PrediGol waiting and then answered, a second session.
* Each reader reads only their own account; no session, 401; the owner's account says so and has no membership.
  Never an internal word in the answer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import membership, support
from tests.integration.helpers import forget_memberships, forget_sign_in_failures
from tests.integration.signed_in import SAME_SITE

pytestmark = pytest.mark.integration

READER = "lectora.b1@example.org"
OTHER = "otro.b1@example.org"
OWNER = "owner.b1@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
INTERNAL = ("ROLE_", "USER", "SUPER_ADMIN", "SHADOW", "QUALIFIED", "shadow", "qualified")
"""Words of the inside of PrediGol that never reach a reader's account centre (plan section 21)."""


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
        made = service.create_user_unattended(email=email, display_name="Lectora Bogotá" if email == READER else
                                              email.split("@")[0], role=role, password=PASSWORD, language="es",
                                              timezone="America/Bogota")
        if email == READER:  # as the console makes a reader (A8): the trial starts with the account
            membership.start_trial_for(int(made["id"]), actor=None)
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
                          "customer.support_tickets", "customer.preferences"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
    for name in (support.SWITCH, "FBI_SUPPORT_WHATSAPP", "FBI_EMAIL_SEND", "FBI_CONSENT_GATE"):
        monkeypatch.delenv(name, raising=False)
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def account(c: TestClient) -> dict[str, Any]:
    r = c.get("/api/v1/me/account")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_a_new_reader_reads_the_eight_blocks_folded(fresh: str) -> None:
    c = client(READER)
    body = account(c)
    assert set(body) == {"account", "region", "football", "notifications", "privacy", "security", "membership",
                         "help"}
    assert body["account"]["display_name"] == "Lectora Bogotá"
    assert body["account"]["email"] == READER
    assert body["account"]["admin"] is False
    assert body["account"]["created_at"]
    assert body["region"] == {"language": "es", "timezone": "America/Bogota"}
    assert body["football"]["suggested"] is True
    assert body["notifications"] == {"email_on": 7, "email_total": 7, "email_status": "ok", "sending": False}
    assert body["privacy"] == {"consents_due": [], "consents_at": None, "open_requests": 0, "next_deadline": None}
    assert body["security"]["mfa_enabled"] is False
    assert body["security"]["sessions"] == 1
    assert body["security"]["last_sign_in_at"]
    assert body["membership"]["state"] == "trial"
    assert body["membership"]["days_left"] == 20
    assert body["help"] == {"waiting": 0, "answered": 0, "whatsapp": False, "support": True}
    text = json.dumps(body)
    for word in INTERNAL:
        assert word not in text, f"«{word}» in a reader's account centre"


def test_what_the_reader_does_shows_at_once(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    c = client(READER)
    # an optional e-mail switched off: one category fewer
    assert c.patch("/api/v1/me/preferences", json={"email": {"membership": False}}).status_code == 200
    # a privacy request: open, with its legal deadline
    r = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query", "message": "¿Qué datos guardan?"})
    assert r.status_code == 201, r.text
    deadline = r.json()["due_on"]
    # a message to PrediGol: waiting, then answered by the owner
    t = c.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "No carga Inicio"})
    assert t.status_code == 201, t.text
    ticket_id = t.json()["id"]
    body = account(c)
    assert body["notifications"]["email_on"] == 6
    assert body["privacy"]["open_requests"] == 1
    assert body["privacy"]["next_deadline"] == deadline
    assert date.fromisoformat(body["privacy"]["next_deadline"]) >= datetime.now(UTC).date() - timedelta(days=1)
    assert body["help"]["waiting"] == 1
    assert body["help"]["answered"] == 0
    owner = client(OWNER)
    answered = owner.post(f"/api/v1/admin/support/{ticket_id}/answer",
                          json={"body": "Ya está: recarga la página.", "status": "answered"})
    assert answered.status_code == 200, answered.text
    body = account(c)
    assert (body["help"]["waiting"], body["help"]["answered"]) == (0, 1)
    # a second session elsewhere, and the owner's WhatsApp once given
    client(READER)
    monkeypatch.setenv("FBI_SUPPORT_WHATSAPP", "573001234567")
    body = account(c)
    assert body["security"]["sessions"] == 2
    assert body["help"]["whatsapp"] is True


def test_only_the_readers_own_account(fresh: str) -> None:
    reader = client(READER)
    reader.post("/api/v1/me/support/tickets", json={"category": "technical", "text": "No carga Inicio"})
    other = account(client(OTHER))
    assert other["account"]["email"] == OTHER
    assert other["help"]["waiting"] == 0
    assert other["security"]["sessions"] == 1
    anonymous = TestClient(create_app(), headers=SAME_SITE)
    assert anonymous.get("/api/v1/me/account").status_code == 401


def test_the_owners_account_says_so_and_has_no_membership(fresh: str) -> None:
    body = account(client(OWNER))
    assert body["account"]["admin"] is True
    assert body["membership"] is None

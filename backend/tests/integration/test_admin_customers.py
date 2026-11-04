"""The customer's card against the migrated database (plan UX, B10; section 26 of the plan).

* The owner alone: a reader gets 403 on every route, nobody signed in 401, a write from another site 403.
* The lists: the four views hold exactly who they should (cover ending in 7 days, 14 days unseen, an open ticket, an error
  in the last 24 hours), the owner is never a customer, the search finds by address.
* The card: identity, membership, use (counts of days), notices, consents, tickets, answers and notes - and nothing else:
  no IP, no token, no hash, no secret, no loose click.
* Each act leaves its event, with the reader it is about: a note, reading the consents' proof, reviewing a ticket, the
  copy of a reader's data (the owner's password first). A ticket of another reader is «not found».
* The trail's filter: every kind of event the trail holds.
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
from fbi.auth import crypto, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import membership, support
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE

pytestmark = pytest.mark.integration

ACTIVE = "activa.b10@example.org"
QUIET = "callada.b10@example.org"
TICKET = "ticket.b10@example.org"
ERRORS = "errores.b10@example.org"
ENDING = "vence.b10@example.org"
OWNER = "owner.b10@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
READERS = (ACTIVE, QUIET, TICKET, ERRORS, ENDING)


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.activity_daily", "customer.messages_outbox",
                          "customer.preferences", "customer.ticket_messages", "customer.support_tickets",
                          "customer.consents", "customer.feedback"):
                conn.execute(f"DELETE FROM {table}")
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
    for email in READERS:
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role="USER",
                                       password=PASSWORD, language="es", timezone="America/Bogota")
    service.create_user_unattended(email=OWNER, display_name="owner", role="SUPER_ADMIN", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


@pytest.fixture()
def world(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Five readers in five situations, set from the database as the passing of time would."""
    throttle.reset_all()
    forget_sign_in_failures()
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    now = datetime.now(UTC)
    with psycopg.connect(database, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.activity_daily", "customer.messages_outbox",
                          "customer.ticket_messages", "customer.support_tickets", "customer.feedback",
                          "customer.membership_events", "customer.membership_periods", "customer.payments"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        forget_memberships(conn)
        ids = {e: uid(database, e) for e in READERS}
        # every reader has been around for a month; the quiet one was last seen 20 days ago, the others today
        conn.execute("UPDATE auth.users SET created_at = %s WHERE role = 'USER'", (now - timedelta(days=30),))
        for email in READERS:
            seen = now - timedelta(days=20) if email == QUIET else now - timedelta(hours=2)
            conn.execute("INSERT INTO auth.sessions (id, user_id, expires_at, last_seen_at, stage) "
                         "VALUES (%s, %s, %s, %s, 'full')",
                         (f"{ids[email]:064x}", ids[email], now + timedelta(days=1), seen))
        # the reader with a cover that ends in 3 days; the others have a long one
        for email in READERS:
            ends = now + timedelta(days=3 if email == ENDING else 40)
            period = conn.execute("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, reason) "
                                  "VALUES (%s, 'courtesy', %s, %s, 'prueba de la ficha') RETURNING id",
                                  (ids[email], now - timedelta(days=20), ends)).fetchone()
            assert period is not None
        # an open ticket
        conn.execute("INSERT INTO customer.support_tickets (user_id, kind, category, status) "
                     "VALUES (%s, 'support', 'technical', 'open')", (ids[TICKET],))
        # an error shown to them, and a day of use for another
        subject = crypto.product_id(ids[ERRORS])
        assert subject is not None, "the tests carry the pseudonym's key"
        conn.execute("INSERT INTO customer.product_events (subject, name, props, at) VALUES (%s, 'error_shown', '{}', %s)",
                     (subject, now - timedelta(hours=3)))
        old = crypto.product_id(ids[ACTIVE])
        assert old is not None
        for days_ago in (1, 3, 10):
            conn.execute("INSERT INTO customer.activity_daily (day, subject, events, counts, first_at, last_at) "
                         "VALUES (%s, %s, 4, %s, %s, %s)",
                         ((now - timedelta(days=days_ago)).date(), old,
                          json.dumps({"match_opened": 3, "pick_opened": 1}), now - timedelta(days=days_ago),
                          now - timedelta(days=days_ago)))
    membership.forget()
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def trail(dsn: str, action: str, user_id: int | None = None) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT actor_user_id, target_user_id, ip, detail FROM auth.audit_events "
                            "WHERE action = %s AND (%s::bigint IS NULL OR target_user_id = %s) ORDER BY id",
                            (action, user_id, user_id)).fetchall()
    return [{"actor": r[0], "target": r[1], "ip": r[2], "detail": r[3]} for r in rows]


# ── the owner's alone ────────────────────────────────────────────────────────────────

def test_only_the_owner_reaches_the_cards(world: str) -> None:
    reader, owner = client(ACTIVE), client(OWNER)
    some = uid(world, QUIET)
    for method, path, body in (("get", "/api/v1/admin/customers", None),
                               ("get", f"/api/v1/admin/customers/{some}", None),
                               ("get", f"/api/v1/admin/customers/{some}/consents", None),
                               ("get", f"/api/v1/admin/customers/{some}/tickets/1", None),
                               ("post", f"/api/v1/admin/customers/{some}/notes", {"note": "llamar el lunes"}),
                               ("post", f"/api/v1/admin/customers/{some}/export", {"password": PASSWORD}),
                               ("get", "/api/v1/admin/audit/actions", None)):
        r = getattr(reader, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, (path, r.status_code)
        anonymous = TestClient(create_app(), headers=SAME_SITE)
        r = getattr(anonymous, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 401, (path, r.status_code)
    assert trail(world, "customer.note") == [] and trail(world, "customer.exported") == []
    cross_site = TestClient(create_app())
    cross_site.cookies = owner.cookies
    r = cross_site.post(f"/api/v1/admin/customers/{some}/notes", json={"note": "desde otro sitio"})
    assert r.status_code == 403
    assert owner.get("/api/v1/admin/customers").status_code == 200


# ── the lists ────────────────────────────────────────────────────────────────────────

def emails(owner: TestClient, view: str, **params: Any) -> list[str]:
    r = owner.get("/api/v1/admin/customers", params={"view": view, **params})
    assert r.status_code == 200, r.text
    return sorted(i["email"] for i in r.json()["items"])


def test_each_view_holds_exactly_who_it_should(world: str) -> None:
    owner = client(OWNER)
    assert emails(owner, "all") == sorted(READERS), "the owner is not a customer"
    assert emails(owner, "expiring") == [ENDING]
    assert emails(owner, "inactive") == [QUIET]
    assert emails(owner, "tickets") == [TICKET]
    assert emails(owner, "errors") == [ERRORS]
    counts = {v["view"]: v["count"] for v in owner.get("/api/v1/admin/customers").json()["views"]}
    assert counts == {"all": 5, "expiring": 1, "inactive": 1, "tickets": 1, "errors": 1, "at_risk": 0, "invited": 0}
    assert emails(owner, "all", q="VENCE") == [ENDING], "found by address, without regard to case"
    assert owner.get("/api/v1/admin/customers", params={"view": "nope"}).status_code == 422
    page = owner.get("/api/v1/admin/customers", params={"limit": 2, "offset": 4}).json()
    assert (len(page["items"]), page["total"]) == (1, 5)


def test_a_ticket_closed_or_an_error_a_day_old_leaves_the_view(world: str) -> None:
    owner = client(OWNER)
    ticket = uid(world, TICKET)
    with psycopg.connect(world, autocommit=True) as conn, conn.transaction():
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("UPDATE customer.support_tickets SET status = 'closed', closed_at = now() WHERE user_id = %s",
                     (ticket,))
        conn.execute("UPDATE customer.product_events SET at = now() - interval '25 hours'")
    assert emails(owner, "tickets") == [] and emails(owner, "errors") == []


# ── one card ─────────────────────────────────────────────────────────────────────────

def test_the_card_has_what_is_needed_and_nothing_more(world: str) -> None:
    owner = client(OWNER)
    active = uid(world, ACTIVE)
    r = owner.get(f"/api/v1/admin/customers/{active}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["identity"]["email"] == ACTIVE and card["identity"]["open_sessions"] == 1
    assert card["membership"]["kind"] == "courtesy" and card["membership"]["days_left"] >= 39
    assert (card["usage"]["active_days_7"], card["usage"]["active_days_30"]) == (2, 3)
    assert (card["usage"]["matches_viewed_30"], card["usage"]["picks_opened_30"]) == (9, 3)
    assert card["usage"]["measured"] is True
    assert set(card) == {"identity", "membership", "suspended_reason", "usage", "notifications", "consents",
                         "consents_due", "tickets", "feedback", "notes", "privacy_requests_open", "lifecycle",
                         "lifecycle_history"}
    text = json.dumps(card).lower()
    for forbidden in ("\"ip\"", "user_agent", "token", "password", "hash", "secret", "totp", "endpoint", "auth_key",
                      "phone", "whatsapp"):
        assert forbidden not in text, forbidden
    ticket = uid(world, TICKET)
    mine = owner.get(f"/api/v1/admin/customers/{ticket}").json()
    assert [t["status"] for t in mine["tickets"]] == ["open"]
    assert mine["tickets"][0]["messages"] == 0


def test_the_owner_and_strangers_have_no_card(world: str) -> None:
    owner = client(OWNER)
    assert owner.get(f"/api/v1/admin/customers/{uid(world, OWNER)}").status_code == 404
    assert owner.get("/api/v1/admin/customers/999999").status_code == 404
    assert owner.post("/api/v1/admin/customers/999999/notes", json={"note": "nada"}).status_code == 404
    assert trail(world, "customer.note") == []


# ── each act leaves its event ────────────────────────────────────────────────────────

def test_a_note_is_an_event_the_card_shows(world: str) -> None:
    owner = client(OWNER)
    quiet = uid(world, QUIET)
    r = owner.post(f"/api/v1/admin/customers/{quiet}/notes", json={"note": "  Pidió   más tiempo  para renovar "})
    assert r.status_code == 201, r.text
    events = trail(world, "customer.note", quiet)
    assert len(events) == 1 and events[0]["actor"] == uid(world, OWNER)
    assert events[0]["detail"] == {"note": "Pidió más tiempo para renovar"}
    notes = owner.get(f"/api/v1/admin/customers/{quiet}").json()["notes"]
    assert [(n["author"], n["note"]) for n in notes] == [(OWNER, "Pidió más tiempo para renovar")]
    for bad in ("", "ab", "x" * 501):
        assert owner.post(f"/api/v1/admin/customers/{quiet}/notes", json={"note": bad}).status_code == 422
    reader_view = client(QUIET).get("/api/v1/me/account").json()
    assert "Pidió" not in json.dumps(reader_view), "the reader never sees the owner's notes"


def test_reading_the_consents_and_reviewing_a_ticket_leave_their_events(world: str) -> None:
    owner = client(OWNER)
    reader = uid(world, TICKET)
    r = owner.get(f"/api/v1/admin/customers/{reader}/consents")
    assert r.status_code == 200, r.text
    assert [e["detail"] for e in trail(world, "customer.consents_viewed", reader)] == [{"rows": 0}]
    with psycopg.connect(world) as conn:
        ticket_id = int(scalar(conn.execute("SELECT id FROM customer.support_tickets WHERE user_id = %s", (reader,))))
    r = owner.get(f"/api/v1/admin/customers/{reader}/tickets/{ticket_id}")
    assert r.status_code == 200 and r.json()["category"] == "technical"
    assert [e["detail"] for e in trail(world, "customer.ticket_reviewed", reader)] == [
        {"ticket": ticket_id, "category": "technical"}]
    other = uid(world, ACTIVE)
    r = owner.get(f"/api/v1/admin/customers/{other}/tickets/{ticket_id}")
    assert r.status_code == 404, "another reader's ticket is not found through this card"
    assert trail(world, "customer.ticket_reviewed", other) == []


def test_the_copy_of_a_readers_data_needs_the_owners_password(world: str) -> None:
    owner = client(OWNER)
    reader = uid(world, ACTIVE)
    r = owner.post(f"/api/v1/admin/customers/{reader}/export", json={"password": "not-the-password-at-all"})
    assert r.status_code in (401, 403), r.text
    assert trail(world, "customer.exported") == []
    r = owner.post(f"/api/v1/admin/customers/{reader}/export", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"] and str(reader) in r.headers["content-disposition"]
    document = r.json()
    assert document["account"]["email"] == ACTIVE if "account" in document else ACTIVE in json.dumps(document)
    events = trail(world, "customer.exported", reader)
    assert [(e["actor"], e["target"]) for e in events] == [(uid(world, OWNER), reader)]
    assert len(trail(world, "customer.export")) == 1, "the owner's password check has its own trace"


def test_the_trails_filter_lists_every_kind_of_event(world: str) -> None:
    owner = client(OWNER)
    reader = uid(world, QUIET)
    owner.post(f"/api/v1/admin/customers/{reader}/notes", json={"note": "una nota cualquiera"})
    r = owner.get("/api/v1/admin/audit/actions")
    assert r.status_code == 200, r.text
    actions = {a["action"]: a["count"] for a in r.json()["data"]}
    assert actions["customer.note"] == 1 and "login.succeeded" in actions
    for action in ("customer.note", "membership.suspended"):
        assert owner.get("/api/v1/admin/audit", params={"action": action}).status_code == 200


def test_the_support_module_still_serves_the_inbox(world: str) -> None:
    """The card reads the tickets through the module the inbox uses: one source of truth."""
    owner = client(OWNER)
    assert owner.get("/api/v1/admin/support").status_code == 200
    assert hasattr(support, "owner_tickets_of")

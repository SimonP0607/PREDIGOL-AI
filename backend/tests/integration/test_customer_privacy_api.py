"""The consent gate, the reader's consents, the export of their own data and their privacy requests, over HTTP against
the migrated database (plan UX, A4; plan de seguridad, section 23).

* The gate: off by default; on (``FBI_CONSENT_GATE``), a reader without the four current consents reads no product
  route (403 ``consent_required``) and /auth/me says which ones are owed; accepting opens the product, withdrawing the
  processing authorisation closes it again, and a material change of a text asks for it again - only the purposes
  on that text. SUPER_ADMIN and the synthetic journey's account are exempt; ``1`` does nothing over draft texts.
* A decision names the version shown: an older one is refused (the proof would be wrong).
* The export needs the password, holds only the reader's own data and never a secret, three a day.
* A request gets its legal deadline; one open per kind; a deletion request needs the password; the owner answers,
  extends once, closes.
* The database keeps the evidence: consents and messages are append-only, a ticket's who/what/when cannot change, and
  no table of ``customer`` has a column for an IP, a card, a token or an article.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, legal, privacy
from tests.integration.conftest import Seed
from tests.integration.helpers import forget_memberships, forget_sign_in_failures

READER = "reader@predigol.test"
OTHER = "other@predigol.test"
OWNER = "owner@predigol.test"
ROBOT = "robot@predigol.test"
PASSWORD = "Pitch-side-2026-long"
SAME_SITE = {"x-requested-with": "predigol"}
PRODUCT = "/api/v1/me/picks"


def forget_customer_data(dsn: str) -> None:
    """The retention job's way (plan UX, A4): inside one transaction with the guard lifted."""
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.ticket_messages")
        conn.execute("DELETE FROM customer.support_tickets")
        conn.execute("DELETE FROM customer.consents")
        conn.execute("DELETE FROM customer.messages_outbox")  # A5: the receipts and answers a request queues
        conn.execute("DELETE FROM customer.preferences")
        conn.execute("DELETE FROM customer.product_events")  # A6
        conn.execute("DELETE FROM customer.activity_daily")


@pytest.fixture(scope="module")
def database(migrated_database: str, seed: Seed) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_SYNTHETIC_EMAIL", ROBOT)
    reset_cache()
    reset_session_settings()

    def wipe() -> None:
        forget_customer_data(migrated_database)
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM picks.user_picks")
            conn.execute("DELETE FROM auth.sessions")
            conn.execute("DELETE FROM auth.audit_events")
            forget_memberships(conn)
            conn.execute("DELETE FROM auth.users")

    wipe()
    for email, role in ((READER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN"), (ROBOT, "USER")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0].title(), role=role,
                                       password=PASSWORD, language="es", timezone="America/Bogota")
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for email, selection in ((READER, "Home"), (OTHER, "Away")):
            conn.execute("""
                INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, snapshot,
                                              saved_at)
                SELECT id, %s, '1X2', %s, 0, 'market', 2.1, %s::jsonb, now() FROM auth.users WHERE email = %s
            """, (seed.fixture_id, selection, json.dumps({"note": f"saved by {email}"}), email))
    yield migrated_database
    wipe()
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    forget_customer_data(database)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events WHERE action LIKE 'privacy.%%'")
    consents._clear.clear()
    monkeypatch.delenv(consents.GATE_ENV, raising=False)
    yield database
    consents._clear.clear()


def client(email: str) -> TestClient:
    from fbi.api.app import create_app

    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def accept(c: TestClient, kinds: list[str] | None = None, *, locale: str = "es") -> dict[str, object]:
    state = c.get("/api/v1/me/consents", params={"lang": locale}).json()
    chosen = [p for p in state["purposes"] if kinds is None or p["kind"] in kinds]
    r = c.post("/api/v1/me/consents", json={
        "decisions": [{"kind": p["kind"], "granted": True, "version": p["version"]} for p in chosen],
        "locale": locale, "source": "gate"})
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def test_the_gate_is_off_by_default_and_the_product_opens_without_consents(fresh: str) -> None:
    c = client(READER)
    assert c.get(PRODUCT).status_code == 200
    me = c.get("/api/v1/auth/me").json()
    assert me["consents_due"] == []
    state = c.get("/api/v1/me/consents").json()
    assert state["gate"] is False and state["due"] == []
    assert [p["kind"] for p in state["purposes"]] == ["terms", "privacy", "age_18", "risk_notice"]


def test_with_draft_texts_turning_the_gate_on_does_nothing(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "1")
    assert legal.any_draft()
    assert client(READER).get(PRODUCT).status_code == 200


def test_the_gate_asks_for_the_four_consents_and_opens_once_they_are_given(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    c = client(READER)
    refused = c.get(PRODUCT)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "consent_required"
    assert c.get("/api/v1/auth/me").json()["consents_due"] == ["terms", "privacy", "age_18", "risk_notice"]
    # the account, its rights and the texts stay open behind the gate
    assert c.get("/api/v1/auth/me/sessions").status_code == 200
    assert c.get("/api/v1/me/privacy-requests").status_code == 200
    assert c.get("/api/v1/legal/terms").status_code == 200
    accept(c, ["terms", "privacy", "age_18"])
    assert c.get(PRODUCT).status_code == 403, "three of four is not enough"
    state = accept(c, ["risk_notice"])
    assert state["due"] == []
    assert c.get(PRODUCT).status_code == 200
    assert c.get("/api/v1/auth/me").json()["consents_due"] == []
    with psycopg.connect(fresh) as conn:
        rows = conn.execute("""
            SELECT c.kind, c.granted, c.document, c.version, c.sha256, c.locale, c.statement, c.source
            FROM customer.consents c JOIN auth.users u ON u.id = c.user_id WHERE u.email = %s ORDER BY c.id
        """, (READER,)).fetchall()
    assert [r[0] for r in rows] == ["terms", "privacy", "age_18", "risk_notice"]
    for kind, granted, document, version, sha, locale, sentence, source in rows:
        doc, expected = legal.statement(kind, "es")
        assert (granted, document, version, sha, locale, sentence, source) == (
            True, doc.document, doc.version, doc.sha256, "es", expected, "gate")


def test_signing_in_says_at_once_what_is_owed(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Me of the sign-in itself carries the owed consents: the page shows the gate at once instead of opening the
    product and meeting a 403 on its first read (A4's e2e: a new account's first page)."""
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    from fbi.api.app import create_app

    c = TestClient(create_app(), headers=SAME_SITE)
    signed = c.post("/api/v1/auth/login", json={"email": READER, "password": PASSWORD})
    assert signed.status_code == 200
    assert signed.json()["consents_due"] == ["terms", "privacy", "age_18", "risk_notice"]
    accept(c)
    again = c.patch("/api/v1/auth/me/preferences", json={"timezone": "America/Bogota"})
    assert again.json()["consents_due"] == []
    owner = TestClient(create_app(), headers=SAME_SITE)
    assert owner.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}).json()["consents_due"] == []


def test_withdrawing_the_processing_authorisation_closes_the_product_until_it_is_given_again(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    c = client(READER)
    accept(c)
    assert c.get(PRODUCT).status_code == 200
    version = legal.current("privacy").version
    r = c.post("/api/v1/me/consents", json={"decisions": [{"kind": "privacy", "granted": False, "version": version}],
                                            "locale": "es", "source": "profile"})
    assert r.status_code == 200 and r.json()["due"] == ["privacy"]
    assert c.get(PRODUCT).status_code == 403
    history = r.json()["history"]
    assert history[0]["kind"] == "privacy" and history[0]["granted"] is False and history[0]["source"] == "profile"
    # the terms, the +18 declaration and the risk notice end with the account, not with a withdrawal
    current = {"terms": legal.current("terms").version, "age_18": legal.current("terms").version,
               "risk_notice": legal.current("responsible_gaming").version}
    for kind, shown in current.items():
        refused = c.post("/api/v1/me/consents", json={
            "decisions": [{"kind": kind, "granted": False, "version": shown}], "locale": "es", "source": "profile"})
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "not_withdrawable"
    accept(c, ["privacy"])
    assert c.get(PRODUCT).status_code == 200
    with psycopg.connect(fresh) as conn:
        chain = conn.execute("""
            SELECT c.id, c.granted, c.replaces_id FROM customer.consents c JOIN auth.users u ON u.id = c.user_id
            WHERE u.email = %s AND c.kind = 'privacy' ORDER BY c.id
        """, (READER,)).fetchall()
    assert [g for _, g, _ in chain] == [True, False, True]
    assert chain[1][2] == chain[0][0] and chain[2][2] == chain[1][0], "each decision names the one it replaces"


def test_accepting_again_the_same_text_adds_nothing(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    c = client(READER)
    accept(c)
    accept(c)
    with psycopg.connect(fresh) as conn:
        row = conn.execute("SELECT count(*) FROM customer.consents").fetchone()
    assert row == (4,)


def test_a_decision_on_a_text_that_is_no_longer_current_is_refused(fresh: str) -> None:
    c = client(READER)
    r = c.post("/api/v1/me/consents", json={
        "decisions": [{"kind": "terms", "granted": True, "version": "2026-01-01-old"}], "locale": "es"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "legal_text_changed"
    r = c.post("/api/v1/me/consents", json={
        "decisions": [{"kind": "marketing_email", "granted": True, "version": "2026-10-25-draft1"}], "locale": "es"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_offered", \
        "B8's box, refused while the weekly summary cannot reach anyone (FBI_DIGEST off)"
    r = c.post("/api/v1/me/consents", json={"decisions": [], "locale": "es"})
    assert r.status_code == 422


def test_a_material_change_asks_again_only_for_the_purposes_on_that_text(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    c = client(READER)
    accept(c)
    real = legal.register()
    terms = real["terms"]
    new = legal.Version(version="2026-12-01", date="2026-12-01", draft=True, material=True,
                        changes={"es": "La membresía, con precio y retracto.", "en": "Membership, with its price."},
                        sha256=terms[-1].sha256)
    monkeypatch.setattr(legal, "register", lambda: {**real, "terms": (*terms, new)})
    legal.load.cache_clear()
    try:
        assert c.get(PRODUCT).status_code == 403
        assert c.get("/api/v1/auth/me").json()["consents_due"] == ["terms", "age_18"]
        state = c.get("/api/v1/me/consents").json()
        by_kind = {p["kind"]: p for p in state["purposes"]}
        assert by_kind["terms"]["version"] == "2026-12-01"
        assert by_kind["terms"]["changes"] == "La membresía, con precio y retracto."
        assert by_kind["privacy"]["changes"] is None
        accept(c, ["terms", "age_18"])
        assert c.get(PRODUCT).status_code == 200
    finally:
        legal.load.cache_clear()


def test_the_owner_and_the_synthetic_journey_are_never_stopped(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    for email in (OWNER, ROBOT):
        c = client(email)
        assert c.get(PRODUCT).status_code == 200, email
        assert c.get("/api/v1/auth/me").json()["consents_due"] == []
        assert c.get("/api/v1/me/consents").json()["gate"] is False
    assert client(OTHER).get(PRODUCT).status_code == 403


def test_the_export_needs_the_password_and_holds_only_the_readers_own_data(fresh: str) -> None:
    c = client(READER)
    accept(c)
    other = client(OTHER)
    accept(other, locale="en")
    assert other.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query",
                                                           "message": "What do you keep about me?"}).status_code == 201
    wrong = c.post("/api/v1/me/export", json={"password": "not-my-password"})
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "wrong_password"
    r = c.post("/api/v1/me/export", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith('attachment; filename="predigol-datos-')
    data = r.json()
    raw = r.text
    assert data["format"] == privacy.EXPORT_FORMAT
    assert data["account"]["email"] == READER
    assert {c["kind"] for c in data["consents"]} == {"terms", "privacy", "age_18", "risk_notice"}
    assert [p["selection"] for p in data["saved_picks"]] == ["Home"]
    assert data["sessions"] and data["access_history"]
    assert OTHER not in raw and "saved by other" not in raw and "What do you keep" not in raw
    for secret in ("password_hash", "totp_secret", "totp_last_step", "pending_totp_secret", "code_hash", '"role"'):
        assert secret not in raw, secret
    with psycopg.connect(fresh) as conn:
        events = conn.execute("SELECT action FROM auth.audit_events WHERE action LIKE 'privacy.export%%' "
                              "ORDER BY id").fetchall()
    assert [e[0] for e in events] == ["privacy.export_refused", "privacy.export"]


def test_three_exports_a_day(fresh: str) -> None:
    c = client(READER)
    for _ in range(privacy.EXPORTS_PER_DAY):
        assert c.post("/api/v1/me/export", json={"password": PASSWORD}).status_code == 200
    limited = c.post("/api/v1/me/export", json={"password": PASSWORD})
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "daily_limit"


def test_a_privacy_request_gets_its_legal_deadline_and_one_open_per_kind(fresh: str) -> None:
    c = client(READER)
    r = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query", "message": "¿Qué datos guardan?"})
    assert r.status_code == 201, r.text
    ticket = r.json()
    expected = privacy.deadline_for("privacy_query", privacy.bogota_today())
    assert ticket["due_on"] == expected.isoformat() and ticket["deadline"] == expected.isoformat()
    assert ticket["status"] == "open" and ticket["messages"][0]["author"] == "customer"
    again = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query", "message": "¿Y ahora?"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "request_open"
    claim = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_claim", "message": "Corrijan mi alias"})
    assert claim.status_code == 201
    assert claim.json()["due_on"] == privacy.deadline_for("privacy_claim", privacy.bogota_today()).isoformat()
    no_pw = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_deletion", "message": "Bórrenme"})
    assert no_pw.status_code == 422 and no_pw.json()["error"]["code"] == "password_required"
    bad_pw = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_deletion", "message": "Bórrenme",
                                                         "password": "nope"})
    assert bad_pw.status_code == 403
    deletion = c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_deletion", "message": "Bórrenme",
                                                           "password": PASSWORD})
    assert deletion.status_code == 201
    mine = c.get("/api/v1/me/privacy-requests").json()
    assert sorted(t["kind"] for t in mine) == ["privacy_claim", "privacy_deletion", "privacy_query"]
    assert client(OTHER).get("/api/v1/me/privacy-requests").json() == [], "only the reader's own"


def test_the_owner_answers_extends_once_and_closes(fresh: str) -> None:
    reader = client(READER)
    opened = reader.post("/api/v1/me/privacy-requests", json={"kind": "privacy_claim", "message": "Corrijan mi alias"})
    tid = opened.json()["id"]
    assert reader.get("/api/v1/admin/privacy-requests").status_code == 403
    owner = client(OWNER)
    listed = owner.get("/api/v1/admin/privacy-requests").json()
    assert [(t["id"], t["email"]) for t in listed] == [(tid, READER)]
    r = owner.post(f"/api/v1/admin/privacy-requests/{tid}/answer",
                   json={"body": "Necesitamos 8 días hábiles más para revisar el historial; respondemos antes de la "
                                 "nueva fecha.", "status": "open", "extend": True})
    assert r.status_code == 200, r.text
    extended = r.json()
    due = datetime.fromisoformat(opened.json()["due_on"]).date()
    from fbi.customer import workdays
    assert extended["extended_to"] == workdays.add_business_days(due, 8).isoformat()
    assert extended["deadline"] == extended["extended_to"]
    twice = owner.post(f"/api/v1/admin/privacy-requests/{tid}/answer", json={"body": "Otra", "extend": True})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "already_extended"
    closed = owner.post(f"/api/v1/admin/privacy-requests/{tid}/answer",
                        json={"body": "Corregido tu alias.", "status": "closed"})
    assert closed.json()["status"] == "closed" and closed.json()["closed_at"]
    mine = reader.get("/api/v1/me/privacy-requests").json()[0]
    assert [m["author"] for m in mine["messages"]] == ["customer", "owner", "owner"], "a refused answer adds nothing"
    assert mine["status"] == "closed"
    assert owner.get("/api/v1/admin/privacy-requests").json() == []
    assert len(owner.get("/api/v1/admin/privacy-requests", params={"status": "all"}).json()) == 1
    late = owner.post(f"/api/v1/admin/privacy-requests/{tid}/answer", json={"body": "Algo más"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "request_closed"


def test_the_database_keeps_the_evidence(fresh: str) -> None:
    c = client(READER)
    accept(c)
    c.post("/api/v1/me/privacy-requests", json={"kind": "privacy_query", "message": "Hola"})
    with psycopg.connect(fresh, autocommit=True) as conn:
        for sql in ("UPDATE customer.consents SET granted = NOT granted",
                    "DELETE FROM customer.consents",
                    "UPDATE customer.ticket_messages SET body = 'otra cosa'",
                    "DELETE FROM customer.ticket_messages",
                    "DELETE FROM customer.support_tickets",
                    "UPDATE customer.support_tickets SET kind = 'privacy_claim'",
                    "UPDATE customer.support_tickets SET due_on = due_on + 30",
                    "UPDATE customer.support_tickets SET opened_at = now() - interval '1 year'"):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(sql)
        conn.execute("UPDATE customer.support_tickets SET status = 'answered'")  # the status may change
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            forget_memberships(conn)
            conn.execute("DELETE FROM auth.users WHERE email = %s", (READER,))


def test_no_table_of_the_customer_schema_has_room_for_an_ip_a_card_a_token_or_an_article(fresh: str) -> None:
    forbidden = ("ip", "ip_address", "card", "pan", "iban", "account_number", "token", "password", "secret",
                 "article", "user_agent", "device", "fingerprint", "location", "geo")
    with psycopg.connect(fresh) as conn:
        columns = conn.execute("""
            SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'customer'
        """).fetchall()
    assert {t for t, _ in columns} == {"consents", "support_tickets", "ticket_messages",
                                       "messages_outbox", "preferences",  # A5
                                       "product_events", "activity_daily",  # A6
                                       "payments", "membership_periods", "membership_events",  # A8
                                       "favorites",  # A13: leagues and teams only - never an amount or a bankroll
                                       "feedback",  # B6: a score, a comment without an address, where it was asked
                                       # B7: a browser's push address and the two values the W3C Push API gives to
                                       # encrypt a notice for it alone (p256dh, its public key; auth) - no credential:
                                       # they open nothing of PrediGol or of the reader, a push service takes nothing
                                       # sent to that address without PrediGol's own VAPID key, and they never leave
                                       # the database (not in the export, the logs or Sentry); the browser's family
                                       # and system as words, never its user agent. Then the bells and the queue.
                                       "push_subscriptions", "match_alerts", "push_notices",
                                       "lifecycle_snapshots"}  # B11: a state and its reason codes, never a word
    offending = [(t, c) for t, c in columns if any(c == f or c.startswith(f + "_") or c.endswith("_" + f)
                                                   for f in forbidden)]
    assert not offending, offending


def test_a_user_route_is_never_answered_from_another_readers_consents(fresh: str,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive cache is per reader: one reader's consents open nothing for another."""
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    reader = client(READER)
    accept(reader)
    assert reader.get(PRODUCT).status_code == 200
    assert client(OTHER).get(PRODUCT).status_code == 403

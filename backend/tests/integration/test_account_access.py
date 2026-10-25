"""Account and access without the owner, over HTTP against the migrated database (plan UX, A7), with the e-mail
provider simulated.

* The switch: off (FBI_SELF_SERVICE, born off) the routes do not exist, the owner cannot invite and no account e-mail
  is queued; the temporary password stays as the way in.
* An invitation: an invited account that cannot sign in, an e-mail whose link exists only in the e-mail (the database
  keeps a nonce and the link's SHA-256, set when the e-mail leaves), 7 days counted from then; activating sets the
  password, the language and the time zone and signs in; the link never works twice; the owner can resend it (the old
  one stops working) or give a temporary password (the backup); an expired link asks for a new one from its own page.
* A new password: the same answer whatever the address, at most three links an hour per account and ten requests an
  hour per client; the link works one hour, once; every session ends, the lock lifts, the second factor stays.
* Unlocking: a link only for an account locked right now; it ends the address's streak.
* What an account is told: a sign-in from a new browser family (never the IP), a change of its credentials; a
  message past its moment is not sent; without the server's key no link is made and the message waits.
* A link that does not work gets one answer, whatever the reason.
* Anonymising: only with the address typed again, never the owner's own account or a SUPER_ADMIN's; what goes, what
  stays (consents, privacy requests), the masked address in the sign-in trail, nothing sent afterwards.
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from fbi.auth import crypto, recovery, service, store, throttle, tokens, totp
from fbi.auth.db import write_connection
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from fbi.customer import consents
from fbi.messaging import outbox
from fbi.messaging.provider import Outgoing
from fbi.messaging.templates import PREVIEW_LINK
from tests.integration.conftest import Seed
from tests.integration.helpers import forget_sign_in_failures

DOMAIN = "a7.test"
OWNER = f"owner@{DOMAIN}"
ROBOT = f"robot@{DOMAIN}"
PASSWORD = "Pitch-side-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
NEW_PASSWORD = "Fresh-start-2026-xyz"  # gitleaks:allow - made up
SAME_SITE = {"x-requested-with": "predigol"}
BASE = "https://predigol.example"
LINK = re.compile(r"https://predigol\.example(/[a-z-]+)#t=([A-Za-z0-9_-]{43})")
FIREFOX_ANDROID = "Mozilla/5.0 (Android 14; Mobile; rv:131.0) Gecko/131.0 Firefox/131.0"
CHROME_WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Safari/537.36")


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.ticket_messages",
                      "customer.support_tickets", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM picks.user_parlays")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM auth.account_tokens")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users WHERE email NOT IN (%s, %s)", (OWNER, ROBOT))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_SYNTHETIC_EMAIL", ROBOT)
    mp.setenv("FBI_WEB_BASE_URL", BASE)
    reset_cache()
    reset_auth_settings()
    with psycopg.connect(migrated_database) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.ticket_messages",
                      "customer.support_tickets", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM picks.user_parlays")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM auth.users")
    for email, role in ((OWNER, "SUPER_ADMIN"), (ROBOT, "USER")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0].title(), role=role,
                                       password=PASSWORD, language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_auth_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    wipe(database)
    throttle.reset_all()
    recovery.reset_all()
    forget_sign_in_failures()
    consents._clear.clear()
    monkeypatch.setenv(tokens.SWITCH, "1")
    monkeypatch.delenv(consents.GATE_ENV, raising=False)
    monkeypatch.delenv("FBI_EMAIL_SEND", raising=False)
    yield database
    consents._clear.clear()


def anon(user_agent: str | None = None) -> TestClient:
    from fbi.api.app import create_app

    headers = dict(SAME_SITE)
    if user_agent:
        headers["user-agent"] = user_agent
    return TestClient(create_app(), headers=headers)


def signed_in(email: str, password: str = PASSWORD, *, user_agent: str | None = None) -> TestClient:
    c = anon(user_agent)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def account(email: str, *, role: str = "USER") -> int:
    row = service.create_user_unattended(email=email, display_name=email.split("@")[0].title(), role=role,
                                         password=PASSWORD, language="es", timezone="America/Bogota")
    return int(row["id"])


def one(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    assert row is not None, sql
    return dict(row)


def rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def queued(dsn: str) -> list[tuple[str, str, dict[str, str]]]:
    """(the account's address, the template, the parameters) of every queued message."""
    return [(r["email"], r["template"], r["params"]) for r in rows(dsn, """
        SELECT u.email, o.template, o.params FROM customer.messages_outbox o JOIN auth.users u ON u.id = o.user_id
         WHERE o.status = 'queued' ORDER BY o.id""")]


class Capture:
    name = "capture"

    def __init__(self) -> None:
        self.sent: list[Outgoing] = []

    def send(self, message: Outgoing) -> str:
        self.sent.append(message)
        return f"cap-{uuid.uuid4().hex}"


def deliver(dsn: str, *, at: datetime | None = None) -> list[Outgoing]:
    """What the messenger would hand to the provider now (or at ``at``)."""
    capture = Capture()
    with psycopg.connect(dsn) as conn:
        outbox.dispatch(conn, capture, at=at or datetime.now(UTC), cap=1000)
    return capture.sent


def link_in(message: Outgoing, path: str) -> str:
    found = [m.group(2) for m in LINK.finditer(message.text) if m.group(1) == path]
    assert found, message.text
    return found[0]


def error(r: Any) -> str:
    return str(r.json()["error"]["code"])


def invite_and_deliver(dsn: str, email: str, **extra: str) -> str:
    owner = signed_in(OWNER)
    r = owner.post("/api/v1/admin/users/invite", json={"email": email, **extra})
    assert r.status_code == 201, r.text
    sent = [m for m in deliver(dsn) if m.to == email]
    assert len(sent) == 1
    return link_in(sent[0], "/activate")


def activate(link: str, password: str = NEW_PASSWORD, *, user_agent: str | None = None) -> Any:
    return anon(user_agent).post("/api/v1/auth/activate", json={"token": link, "password": password,
                                                                "language": "es", "timezone": "America/Bogota"})


def lock(email: str) -> None:
    c = anon()
    for _ in range(5):
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123"})
    assert r.status_code == 429


# ── the switch ────────────────────────────────────────────────────────────────────────

def test_off_the_routes_do_not_exist_the_owner_cannot_invite_and_nothing_is_queued(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(tokens.SWITCH, "0")
    c = anon()
    assert c.get("/api/v1/auth/options").json() == {"self_service": False}
    link = secrets.token_urlsafe(32)
    for path, body in (("/api/v1/auth/password/forgot", {"email": f"x@{DOMAIN}"}),
                       ("/api/v1/auth/unlock/request", {"email": f"x@{DOMAIN}"}),
                       ("/api/v1/auth/activate/check", {"token": link}),
                       ("/api/v1/auth/activate/renew", {"token": link}),
                       ("/api/v1/auth/activate", {"token": link, "password": NEW_PASSWORD, "language": "es",
                                                  "timezone": "UTC"}),
                       ("/api/v1/auth/password/reset/check", {"token": link}),
                       ("/api/v1/auth/password/reset", {"token": link, "password": NEW_PASSWORD}),
                       ("/api/v1/auth/unlock", {"token": link})):
        assert c.post(path, json=body).status_code == 404, path
    owner = signed_in(OWNER)
    assert owner.get("/api/v1/admin/users/self-service").json() == {"self_service": False, "email_sending": False}
    r = owner.post("/api/v1/admin/users/invite", json={"email": f"new@{DOMAIN}"})
    assert r.status_code == 409 and error(r) == "self_service_off"
    account(f"reader@{DOMAIN}")
    reader = signed_in(f"reader@{DOMAIN}", user_agent=FIREFOX_ANDROID)
    assert reader.post("/api/v1/auth/me/password", json={"current_password": PASSWORD,
                                                         "new_password": NEW_PASSWORD}).status_code == 204
    signed_in(f"reader@{DOMAIN}", NEW_PASSWORD, user_agent=CHROME_WINDOWS)
    assert queued(fresh) == [], "no account e-mail while the switch is off"


# ── invitations ───────────────────────────────────────────────────────────────────────

def test_an_invitation_makes_an_invited_account_and_its_link_exists_only_in_the_email(fresh: str) -> None:
    owner = signed_in(OWNER)
    r = owner.post("/api/v1/admin/users/invite", json={"email": " Nueva@A7.test ", "display_name": "Nueva",
                                                       "language": "en", "timezone": "Europe/Madrid"})
    assert r.status_code == 201, r.text
    user = r.json()["data"]
    assert (user["status"], user["email"], user["language"], user["role"]) == ("invited", "nueva@a7.test", "en", "USER")
    assert owner.post("/api/v1/admin/users/invite", json={"email": "nueva@a7.test"}).status_code == 409
    # it cannot sign in, and is refused as an address without an account would be
    r = anon().post("/api/v1/auth/login", json={"email": "nueva@a7.test", "password": "anything-at-all-1"})
    assert r.status_code == 401 and error(r) == "invalid_credentials"
    token = one(fresh, "SELECT * FROM auth.account_tokens WHERE user_id = %s", (user["id"],))
    assert token["purpose"] == "invite" and token["token_hash"] is None and token["sent_at"] is None
    assert queued(fresh) == [("nueva@a7.test", "invitation", {"grant": str(token["id"])})]

    before = datetime.now(UTC)
    sent = deliver(fresh)
    assert [m.to for m in sent] == ["nueva@a7.test"]
    message = sent[0]
    assert message.subject == "Your invitation to PrediGol" and "Hello, Nueva." in message.text
    link = link_in(message, "/activate")
    assert f"{BASE}/activate#t={link}" in message.html
    armed = one(fresh, "SELECT * FROM auth.account_tokens WHERE id = %s", (token["id"],))
    assert armed["token_hash"] == tokens.token_id(link)
    assert armed["sent_at"] >= before and armed["expires_at"] - armed["sent_at"] == timedelta(days=7)
    # the link is nowhere in the database: not in the queue, not in the link's row, not in the trail
    with psycopg.connect(fresh) as conn:
        everything = json.dumps([list(map(str, r)) for table in ("customer.messages_outbox", "auth.account_tokens",
                                                                   "auth.audit_events")
                                 for r in conn.execute(f"SELECT * FROM {table}").fetchall()])
    assert link not in everything
    info = anon().post("/api/v1/auth/activate/check", json={"token": link})
    assert info.status_code == 200
    assert info.json() == {"email": "nueva@a7.test", "display_name": "Nueva", "language": "en",
                           "timezone": "Europe/Madrid"}


def test_activating_sets_the_password_and_signs_in_and_the_link_never_works_again(fresh: str) -> None:
    link = invite_and_deliver(fresh, f"act@{DOMAIN}", language="en")
    weak = activate(link, "short")
    assert weak.status_code == 422 and error(weak) == "weak_password"
    assert "password_too_short" in weak.json()["error"]["problems"]
    c = anon()
    r = c.post("/api/v1/auth/activate", json={"token": link, "password": NEW_PASSWORD, "language": "es",
                                              "timezone": "America/Bogota"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert (me["email"], me["stage"], me["language"], me["timezone"]) == (
        f"act@{DOMAIN}", "full", "es", "America/Bogota")
    assert c.get("/api/v1/auth/me").status_code == 200, "signed in by the cookie, as at sign-in"
    history = {e["action"] for e in c.get("/api/v1/auth/me/access").json()}
    assert {"user.activated", "login.succeeded"} <= history, "the account's own history shows its activation"
    user = one(fresh, "SELECT * FROM auth.users WHERE email = %s", (f"act@{DOMAIN}",))
    assert user["status"] == "active" and not user["must_change_password"]
    actions = [r["action"] for r in rows(fresh, "SELECT action FROM auth.audit_events WHERE target_user_id = %s "
                                                "ORDER BY id", (user["id"],))]
    assert actions[-2:] == ["user.activated", "login.succeeded"]
    for again in (activate(link), anon().post("/api/v1/auth/activate/check", json={"token": link})):
        assert again.status_code == 410 and error(again) == "link_invalid"
    signed_in(f"act@{DOMAIN}", NEW_PASSWORD)
    assert queued(fresh) == [], "the first sign-ins after the activation tell nothing"


def test_a_link_that_does_not_work_gets_one_answer_whatever_the_reason(fresh: str) -> None:
    expired = invite_and_deliver(fresh, f"late@{DOMAIN}")
    with psycopg.connect(fresh) as conn:
        conn.execute("UPDATE auth.account_tokens t SET sent_at = now() - interval '8 days', "
                     "expires_at = now() - interval '1 day' FROM auth.users u "
                     "WHERE u.id = t.user_id AND u.email = %s", (f"late@{DOMAIN}",))
    used = invite_and_deliver(fresh, f"used@{DOMAIN}")
    assert activate(used).status_code == 200
    replaced = invite_and_deliver(fresh, f"again@{DOMAIN}")
    uid = one(fresh, "SELECT id FROM auth.users WHERE email = %s", (f"again@{DOMAIN}",))["id"]
    assert signed_in(OWNER).post(f"/api/v1/admin/users/{uid}/invitation").status_code == 200
    candidates = {"expired": expired, "used": used, "replaced": replaced, "unknown": secrets.token_urlsafe(32),
                  "malformed": "not a link", "too long": "a" * 120}
    answers = {}
    for reason, link in candidates.items():
        r = anon().post("/api/v1/auth/activate/check", json={"token": link})
        body = r.json()
        body.pop("request_id", None)
        answers[reason] = (r.status_code, json.dumps(body, sort_keys=True))
    assert len(set(answers.values())) == 1, answers
    assert next(iter(answers.values()))[0] == 410
    # a link of another kind does not open this page either
    reset = anon().post("/api/v1/auth/password/reset/check", json={"token": invite_and_deliver(fresh, f"k@{DOMAIN}")})
    assert reset.status_code == 410


def test_an_expired_invitation_asks_for_a_new_one_from_its_page_at_most_three_an_hour(fresh: str) -> None:
    link = invite_and_deliver(fresh, f"renew@{DOMAIN}")
    with psycopg.connect(fresh) as conn:
        conn.execute("UPDATE auth.account_tokens SET sent_at = now() - interval '8 days', "
                     "expires_at = now() - interval '1 day'")
    assert anon().post("/api/v1/auth/activate/check", json={"token": link}).status_code == 410
    for _ in range(4):
        r = anon().post("/api/v1/auth/activate/renew", json={"token": link})
        assert r.status_code == 202 and r.json() == {"status": "accepted"}
    # the invitation and two new ones in the hour: the fourth ask is the same answer and nothing more
    assert one(fresh, "SELECT count(*) AS n FROM auth.account_tokens")["n"] == 3
    assert one(fresh, "SELECT count(*) AS n FROM auth.audit_events WHERE action = 'account.link_capped'")["n"] == 2
    sent = deliver(fresh)
    assert len(sent) == 1, "only the latest link leaves; the replaced ones are not sent"
    assert activate(link_in(sent[0], "/activate")).status_code == 200
    # a renewal for an account that is active (or a link nobody was sent) is the same answer and nothing at all
    assert anon().post("/api/v1/auth/activate/renew", json={"token": link}).status_code == 202
    assert anon().post("/api/v1/auth/activate/renew", json={"token": secrets.token_urlsafe(32)}).status_code == 202
    assert queued(fresh) == []


def test_the_owner_resends_an_invitation_or_gives_a_temporary_password_as_the_backup(fresh: str) -> None:
    first = invite_and_deliver(fresh, f"backup@{DOMAIN}")
    owner = signed_in(OWNER)
    uid = one(fresh, "SELECT id FROM auth.users WHERE email = %s", (f"backup@{DOMAIN}",))["id"]
    r = owner.post(f"/api/v1/admin/users/{uid}/invitation")
    assert r.status_code == 200 and r.json()["data"]["status"] == "invited"
    second = link_in(deliver(fresh)[0], "/activate")
    assert anon().post("/api/v1/auth/activate/check", json={"token": first}).status_code == 410
    assert anon().post("/api/v1/auth/activate/check", json={"token": second}).status_code == 200
    # an invited account's role or state is not patched: it is resent, given a password or withdrawn
    for patch in ({"status": "disabled"}, {"role": "SUPER_ADMIN"}):
        r = owner.patch(f"/api/v1/admin/users/{uid}", json=patch)
        assert r.status_code == 409 and error(r) == "account_invited"
    r = owner.post(f"/api/v1/admin/users/{uid}/password", json={})
    assert r.status_code == 200
    temporary = r.json()["data"]["temporary_password"]
    assert r.json()["data"]["user"]["status"] == "active"
    assert anon().post("/api/v1/auth/activate/check", json={"token": second}).status_code == 410
    staged = anon().post("/api/v1/auth/login", json={"email": f"backup@{DOMAIN}", "password": temporary})
    assert staged.status_code == 200 and staged.json()["stage"] == "password"
    # not an invited account any more: a resend is refused
    assert error(owner.post(f"/api/v1/admin/users/{uid}/invitation")) == "not_invited"


# ── a new password ────────────────────────────────────────────────────────────────────

def test_asking_for_a_new_password_answers_the_same_whatever_the_address(fresh: str) -> None:
    account(f"known@{DOMAIN}")
    account(f"off@{DOMAIN}")
    assert signed_in(OWNER).patch("/api/v1/admin/users/" + str(
        one(fresh, "SELECT id FROM auth.users WHERE email = %s", (f"off@{DOMAIN}",))["id"]),
        json={"status": "disabled"}).status_code == 200
    c = anon()
    answers = [c.post("/api/v1/auth/password/forgot", json={"email": e})
               for e in (f"known@{DOMAIN}", f"unknown@{DOMAIN}", "not-an-address", f"off@{DOMAIN}",
                         f" KNOWN@{DOMAIN.upper()} ")]
    assert {(a.status_code, json.dumps(a.json(), sort_keys=True)) for a in answers} == {
        (202, json.dumps({"status": "accepted"}))}
    assert [(e, t) for e, t, _ in queued(fresh)] == [(f"known@{DOMAIN}", "password_reset")] * 2
    sent = deliver(fresh)
    assert [m.to for m in sent] == [f"known@{DOMAIN}"], "the second link replaced the first: one e-mail leaves"
    assert one(fresh, "SELECT count(*) AS n FROM customer.messages_outbox WHERE status = 'suppressed'")["n"] == 1
    assert one(fresh, "SELECT count(*) AS n FROM auth.audit_events WHERE email LIKE %s",
               (f"%unknown@{DOMAIN}%",))["n"] == 0, "an address without an account leaves no trace"


def test_the_limits_per_client_and_per_account(fresh: str) -> None:
    account(f"cap@{DOMAIN}")
    c = anon()
    for i in range(10):
        assert c.post("/api/v1/auth/password/forgot", json={"email": f"cap@{DOMAIN}" if i < 5 else f"u{i}@x.y"}
                      ).status_code == 202
    r = c.post("/api/v1/auth/password/forgot", json={"email": f"another@{DOMAIN}"})
    assert r.status_code == 429 and error(r) == "too_many_attempts" and int(r.headers["retry-after"]) > 0
    issued = one(fresh, "SELECT count(*) AS n FROM auth.account_tokens WHERE purpose = 'reset'")["n"]
    assert issued == tokens.PER_HOUR, "three links an hour for one account, whoever asks"
    assert one(fresh, "SELECT count(*) AS n FROM auth.audit_events WHERE action = 'account.link_capped'")["n"] == 2


def test_a_new_password_ends_every_session_keeps_the_second_factor_and_lifts_the_lock(fresh: str) -> None:
    uid = account(f"reset@{DOMAIN}")
    before = signed_in(f"reset@{DOMAIN}")
    secret = totp.new_secret()
    with write_connection() as conn:
        store.set_totp(conn, uid, crypto.seal_totp(uid, secret), 1)
    enabled_at = one(fresh, "SELECT totp_enabled_at FROM auth.users WHERE id = %s", (uid,))["totp_enabled_at"]
    lock(f"reset@{DOMAIN}")
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"reset@{DOMAIN}"}).status_code == 202
    message = deliver(fresh)[0]
    assert message.subject == "Elige una contraseña nueva para PrediGol"
    link = link_in(message, "/reset-password")
    armed = one(fresh, "SELECT sent_at, expires_at FROM auth.account_tokens WHERE purpose = 'reset'")
    assert armed["expires_at"] - armed["sent_at"] == timedelta(minutes=30)
    assert anon().post("/api/v1/auth/password/reset/check", json={"token": link}).json() == {
        "email": f"reset@{DOMAIN}", "mfa": True}
    same = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": PASSWORD})
    assert same.status_code == 422 and "password_reused" in same.json()["error"]["problems"]
    # R25 of the security plan: the link alone does not change the password of an account with a second factor - even
    # while the address waits after five wrong passwords (the owner of the account must be able to finish)
    missing = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD})
    assert missing.status_code == 422 and error(missing) == "code_missing"
    wrong_code = totp.code_at(secret, totp.step_at() - 50)
    wrong = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD,
                                                              "code": wrong_code})
    assert wrong.status_code == 401 and error(wrong) == "invalid_code"
    assert wrong.json()["error"]["attempts_left"] == 4
    right = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD,
                                                              "code": totp.code_at(secret, totp.step_at())})
    assert right.status_code == 204, right.text
    assert before.get("/api/v1/auth/me").status_code == 401, "every session ended"
    old = anon().post("/api/v1/auth/login", json={"email": f"reset@{DOMAIN}", "password": PASSWORD})
    assert old.status_code == 401
    staged = anon().post("/api/v1/auth/login", json={"email": f"reset@{DOMAIN}", "password": NEW_PASSWORD})
    assert staged.status_code == 200 and staged.json()["stage"] == "mfa", "the lock lifted, the second factor stays"
    assert one(fresh, "SELECT totp_enabled_at FROM auth.users WHERE id = %s", (uid,))["totp_enabled_at"] == enabled_at
    again = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": "Yet-another-pass-77"})
    assert again.status_code == 410 and error(again) == "link_invalid"
    assert [(t, p["change"]) for _, t, p in queued(fresh)] == [("security_change", "password_reset")]
    trail = one(fresh, "SELECT email, detail FROM auth.audit_events WHERE action = 'password.reset'")
    assert trail["email"] == f"reset@{DOMAIN}" and trail["detail"]["by"] == "link"
    with write_connection() as conn:
        assert "password.reset" in {r["action"] for r in store.access_history(conn, uid, limit=20)}


def test_a_change_of_password_kills_the_recovery_links_asked_for_before(fresh: str) -> None:
    account(f"kill@{DOMAIN}")
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"kill@{DOMAIN}"}).status_code == 202
    link = link_in(deliver(fresh)[0], "/reset-password")
    reader = signed_in(f"kill@{DOMAIN}")
    assert reader.post("/api/v1/auth/me/password", json={"current_password": PASSWORD,
                                                         "new_password": NEW_PASSWORD}).status_code == 204
    assert anon().post("/api/v1/auth/password/reset/check", json={"token": link}).status_code == 410
    assert [(t, p["change"]) for _, t, p in queued(fresh)] == [("security_change", "password")]


# ── unlocking ─────────────────────────────────────────────────────────────────────────

def test_an_unlock_link_only_for_a_locked_account_and_it_ends_the_streak(fresh: str) -> None:
    account(f"lock@{DOMAIN}")
    c = anon()
    assert c.post("/api/v1/auth/unlock/request", json={"email": f"lock@{DOMAIN}"}).status_code == 202
    assert c.post("/api/v1/auth/unlock/request", json={"email": f"nobody@{DOMAIN}"}).status_code == 202
    assert queued(fresh) == [], "not locked, no account: the same answer and nothing sent"
    lock(f"lock@{DOMAIN}")
    assert c.post("/api/v1/auth/unlock/request", json={"email": f"lock@{DOMAIN}"}).status_code == 202
    message = deliver(fresh)[0]
    assert message.subject == "Desbloquea tu cuenta de PrediGol"
    link = link_in(message, "/unlock")
    assert anon().post("/api/v1/auth/unlock", json={"token": link}).status_code == 204
    signed_in(f"lock@{DOMAIN}")
    trail = one(fresh, "SELECT email, detail FROM auth.audit_events WHERE action = 'user.unlocked'")
    assert trail["email"] == f"lock@{DOMAIN}" and trail["detail"]["by"] == "link"
    history = {e["action"] for e in signed_in(f"lock@{DOMAIN}").get("/api/v1/auth/me/access").json()}
    assert "user.unlocked" in history
    assert anon().post("/api/v1/auth/unlock", json={"token": link}).status_code == 410


def test_one_client_presenting_links_that_do_not_work_is_capped(fresh: str,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    # first the API's own limiter of the sign-in routes, which the link routes join: 20 a minute per client
    c = anon()
    answers = [c.post("/api/v1/auth/unlock", json={"token": secrets.token_urlsafe(32)}).status_code
               for _ in range(21)]
    assert answers[:20] == [410] * 20 and answers[20] == 429
    # then, under a wider limiter, the links' own: 20 links that do not work in 15 minutes, per client
    recovery.reset_all()
    monkeypatch.setenv("FBI_API_LOGIN_RATE_LIMIT", "1000")
    c = anon()
    for _ in range(20):
        assert c.post("/api/v1/auth/unlock", json={"token": secrets.token_urlsafe(32)}).status_code == 410
    r = c.post("/api/v1/auth/password/reset/check", json={"token": secrets.token_urlsafe(32)})
    assert r.status_code == 429 and error(r) == "too_many_attempts"


def test_a_reset_link_takes_five_wrong_codes_then_stops_working(fresh: str) -> None:
    uid = account(f"codes@{DOMAIN}")
    secret = totp.new_secret()
    with write_connection() as conn:
        store.set_totp(conn, uid, crypto.seal_totp(uid, secret), 1)
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"codes@{DOMAIN}"}).status_code == 202
    link = link_in(deliver(fresh)[0], "/reset-password")
    for left in (4, 3, 2, 1):
        r = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD,
                                                              "recovery_code": "zzzzz-zzzzz"})
        assert r.status_code == 401 and r.json()["error"]["attempts_left"] == left
    fifth = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD,
                                                              "code": totp.code_at(secret, totp.step_at() - 50)})
    assert fifth.status_code == 410 and error(fifth) == "link_invalid"
    late = anon().post("/api/v1/auth/password/reset", json={"token": link, "password": NEW_PASSWORD,
                                                             "code": totp.code_at(secret, totp.step_at())})
    assert late.status_code == 410, "the right code after the fifth wrong one is too late: the link is over"
    assert one(fresh, "SELECT revoked_reason FROM auth.account_tokens")["revoked_reason"] == "too_many_codes"
    assert one(fresh, "SELECT count(*) AS n FROM auth.audit_events WHERE action = 'mfa.failed'")["n"] == 5
    old = anon().post("/api/v1/auth/login", json={"email": f"codes@{DOMAIN}", "password": PASSWORD})
    assert old.status_code == 429, "the wrong codes counted like wrong ones at sign-in: the address waits"


# ── what an account is told ───────────────────────────────────────────────────────────

def test_a_sign_in_from_a_new_browser_is_told_without_the_ip(fresh: str) -> None:
    account(f"dev@{DOMAIN}")
    signed_in(f"dev@{DOMAIN}", user_agent=FIREFOX_ANDROID)
    signed_in(f"dev@{DOMAIN}", user_agent=FIREFOX_ANDROID.replace("131.0", "132.0"))
    assert queued(fresh) == [], "the first sign-in, and the same browser on the same system again"
    signed_in(f"dev@{DOMAIN}", user_agent=CHROME_WINDOWS)
    [(email, template, params)] = queued(fresh)
    assert (email, template, params["browser"], params["system"]) == (f"dev@{DOMAIN}", "new_sign_in", "chrome",
                                                                       "windows")
    message = deliver(fresh)[0]
    assert "Alguien entró a tu cuenta desde Chrome en Windows el " in message.text
    assert "(hora de Bogota)" in message.text
    assert "testclient" not in message.text and "Mozilla" not in message.text, "never the IP, never the user agent"
    signed_in(ROBOT, user_agent=FIREFOX_ANDROID)
    signed_in(ROBOT, user_agent=CHROME_WINDOWS)
    assert queued(fresh) == [], "the synthetic journey's account is never told anything"


def test_the_owners_changes_to_an_account_are_told_to_it(fresh: str) -> None:
    uid = account(f"told@{DOMAIN}")
    with write_connection() as conn:
        store.set_totp(conn, uid, crypto.seal_totp(uid, totp.new_secret()), 1)
    owner = signed_in(OWNER)
    assert owner.post(f"/api/v1/admin/users/{uid}/mfa/reset").status_code == 200
    assert owner.post(f"/api/v1/admin/users/{uid}/password", json={}).status_code == 200
    assert [(t, p["change"]) for _, t, p in queued(fresh)] == [("security_change", "mfa_reset"),
                                                              ("security_change", "password_admin")]
    texts = [m.text for m in deliver(fresh)]
    assert any("El administrador quitó la verificación en dos pasos de tu cuenta el " in t for t in texts)


def test_a_message_past_its_moment_is_not_sent(fresh: str) -> None:
    account(f"slow@{DOMAIN}")
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"slow@{DOMAIN}"}).status_code == 202
    assert deliver(fresh, at=datetime.now(UTC) + timedelta(hours=2)) == []
    row = one(fresh, "SELECT status, last_error FROM customer.messages_outbox")
    assert row["status"] == "suppressed" and "too late" in row["last_error"]
    assert one(fresh, "SELECT token_hash FROM auth.account_tokens")["token_hash"] is None, "no link was made"


def test_without_the_servers_key_no_link_is_made_and_the_message_waits(fresh: str,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    account(f"nokey@{DOMAIN}")
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"nokey@{DOMAIN}"}).status_code == 202
    monkeypatch.delenv("FBI_AUTH_SECRET_KEY", raising=False)
    reset_auth_settings()
    try:
        capture = Capture()
        with psycopg.connect(fresh) as conn:
            report = outbox.dispatch(conn, capture, at=datetime.now(UTC), cap=1000)
        assert capture.sent == [] and report.stopped == "auth key unavailable" and report.deferred == 1
        row = one(fresh, "SELECT status, attempts FROM customer.messages_outbox")
        assert (row["status"], row["attempts"]) == ("queued", 0)
        assert one(fresh, "SELECT token_hash FROM auth.account_tokens")["token_hash"] is None
    finally:
        monkeypatch.undo()
        reset_auth_settings()


def test_the_consoles_preview_never_makes_a_link(fresh: str) -> None:
    owner = signed_in(OWNER)
    assert owner.post("/api/v1/admin/users/invite", json={"email": f"prev@{DOMAIN}"}).status_code == 201
    mid = one(fresh, "SELECT id FROM customer.messages_outbox")["id"]
    preview = owner.get(f"/api/v1/admin/messages/{mid}/preview")
    assert preview.status_code == 200, preview.text
    assert f"/activate#t={PREVIEW_LINK}" in preview.json()["text"]
    assert one(fresh, "SELECT token_hash FROM auth.account_tokens")["token_hash"] is None


# ── consents right after the activation ───────────────────────────────────────────────

def test_the_consents_given_right_after_the_activation_say_so(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    link = invite_and_deliver(fresh, f"gate@{DOMAIN}")
    c = anon()
    r = c.post("/api/v1/auth/activate", json={"token": link, "password": NEW_PASSWORD, "language": "es",
                                              "timezone": "America/Bogota"})
    assert r.status_code == 200 and r.json()["consents_due"], "the gate asks right after"
    state = c.get("/api/v1/me/consents", params={"lang": "es"}).json()
    decisions = [{"kind": p["kind"], "granted": True, "version": p["version"]} for p in state["purposes"]
                 if p["kind"] in r.json()["consents_due"]]
    assert c.post("/api/v1/me/consents", json={"decisions": decisions, "locale": "es",
                                               "source": "activation"}).status_code == 200
    assert {s["source"] for s in rows(fresh, "SELECT source FROM customer.consents")} == {"activation"}
    # an account that was not activated just now cannot say so
    account(f"old@{DOMAIN}")
    old = signed_in(f"old@{DOMAIN}")
    state = old.get("/api/v1/me/consents", params={"lang": "es"}).json()
    decisions = [{"kind": p["kind"], "granted": True, "version": p["version"]} for p in state["purposes"]
                 if p["kind"] in state["due"]]
    assert old.post("/api/v1/me/consents", json={"decisions": decisions, "locale": "es",
                                                 "source": "activation"}).status_code == 200
    sources = {s["source"] for s in rows(fresh, "SELECT c.source FROM customer.consents c JOIN auth.users u "
                                                "ON u.id = c.user_id WHERE u.email = %s", (f"old@{DOMAIN}",))}
    assert sources == {"gate"}


# ── anonymising ───────────────────────────────────────────────────────────────────────

def test_anonymising_an_account_with_its_address_typed_again(fresh: str, seed: Seed) -> None:
    uid = account(f"gone@{DOMAIN}")
    reader = signed_in(f"gone@{DOMAIN}")
    with psycopg.connect(fresh) as conn:
        conn.execute("INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, "
                     "snapshot, saved_at) VALUES (%s, %s, '1X2', 'Home', 0, 'market', 2.1, '{}'::jsonb, now())",
                     (uid, seed.fixture_id))
        conn.execute("INSERT INTO customer.preferences (user_id) VALUES (%s)", (uid,))
    consents.record(uid, [consents.Decision(p.kind, True, consents.legal.current(p.document).version)
                          for p in consents.legal.PURPOSES if p.required], locale="es", source="gate")
    assert reader.post("/api/v1/me/privacy-requests", json={"kind": "privacy_deletion", "message": "Borren mis datos",
                                                            "password": PASSWORD}).status_code in (200, 201)
    lock_until_wrong = anon().post("/api/v1/auth/login", json={"email": f"gone@{DOMAIN}", "password": "nope-nope-1"})
    assert lock_until_wrong.status_code == 401
    assert anon().post("/api/v1/auth/password/forgot", json={"email": f"gone@{DOMAIN}"}).status_code == 202
    consents_before = one(fresh, "SELECT count(*) AS n FROM customer.consents WHERE user_id = %s", (uid,))["n"]
    owner = signed_in(OWNER)

    r = owner.post(f"/api/v1/admin/users/{uid}/anonymise", json={"confirm": f"other@{DOMAIN}"})
    assert r.status_code == 422 and error(r) == "confirmation_mismatch"
    owner_id = one(fresh, "SELECT id FROM auth.users WHERE email = %s", (OWNER,))["id"]
    assert error(owner.post(f"/api/v1/admin/users/{owner_id}/anonymise", json={"confirm": OWNER})) == \
        "cannot_delete_self"
    admin_id = account(f"admin2@{DOMAIN}", role="SUPER_ADMIN")
    assert error(owner.post(f"/api/v1/admin/users/{admin_id}/anonymise", json={"confirm": f"admin2@{DOMAIN}"})) == \
        "cannot_delete_admin"

    r = owner.post(f"/api/v1/admin/users/{uid}/anonymise", json={"confirm": f" GONE@{DOMAIN.upper()} "})
    assert r.status_code == 200, r.text
    done = r.json()["data"]
    masked = f"deleted-{uid}@deleted.invalid"
    assert (done["user"]["status"], done["user"]["email"], done["user"]["display_name"]) == (
        "deleted", masked, f"deleted-{uid}")
    assert (done["picks"], done["messages_dropped"]) == (1, 2)  # the receipt of the request and the reset link
    assert done["sessions"] >= 1 and done["trail_rows"] >= 2
    counts = one(fresh, """
        SELECT (SELECT count(*) FROM picks.user_picks WHERE user_id = %(u)s) AS picks,
               (SELECT count(*) FROM customer.preferences WHERE user_id = %(u)s) AS preferences,
               (SELECT count(*) FROM auth.sessions WHERE user_id = %(u)s) AS sessions,
               (SELECT count(*) FROM auth.account_tokens WHERE user_id = %(u)s AND used_at IS NULL
                   AND revoked_at IS NULL) AS open_links,
               (SELECT count(*) FROM customer.consents WHERE user_id = %(u)s) AS consents,
               (SELECT count(*) FROM customer.support_tickets WHERE user_id = %(u)s) AS tickets,
               (SELECT count(*) FROM customer.messages_outbox WHERE user_id = %(u)s AND status = 'queued') AS queued,
               (SELECT count(*) FROM auth.audit_events WHERE email = %(a)s) AS typed,
               (SELECT count(*) FROM auth.audit_events WHERE email = %(m)s) AS masked
    """, {"u": uid, "a": f"gone@{DOMAIN}", "m": masked})
    assert counts == {"picks": 0, "preferences": 0, "sessions": 0, "open_links": 0, "consents": consents_before,
                      "tickets": 1, "queued": 0, "typed": 0, "masked": done["trail_rows"]}
    assert reader.get("/api/v1/auth/me").status_code == 401
    r = anon().post("/api/v1/auth/login", json={"email": f"gone@{DOMAIN}", "password": PASSWORD})
    assert r.status_code == 401 and error(r) == "invalid_credentials"
    assert deliver(fresh) == []
    trail = one(fresh, "SELECT email, detail FROM auth.audit_events WHERE action = 'user.anonymised'")
    assert trail["email"] is None and f"gone@{DOMAIN}" not in json.dumps(trail["detail"])
    for call in (lambda: owner.post(f"/api/v1/admin/users/{uid}/anonymise", json={"confirm": masked}),
                 lambda: owner.patch(f"/api/v1/admin/users/{uid}", json={"status": "active"}),
                 lambda: owner.post(f"/api/v1/admin/users/{uid}/password", json={})):
        r = call()
        assert r.status_code == 409 and error(r) == "account_deleted"
    # the address can be invited again: it is a new account
    assert owner.post("/api/v1/admin/users/invite", json={"email": f"gone@{DOMAIN}"}).status_code == 201


def test_an_invitation_is_withdrawn_by_anonymising_it(fresh: str) -> None:
    link = invite_and_deliver(fresh, f"typo@{DOMAIN}")
    uid = one(fresh, "SELECT id FROM auth.users WHERE email = %s", (f"typo@{DOMAIN}",))["id"]
    r = signed_in(OWNER).post(f"/api/v1/admin/users/{uid}/anonymise", json={"confirm": f"typo@{DOMAIN}"})
    assert r.status_code == 200
    assert anon().post("/api/v1/auth/activate/check", json={"token": link}).status_code == 410


# ── the table and its retention ───────────────────────────────────────────────────────

def test_old_links_are_counted_and_deleted_only_once_the_owner_says_so(fresh: str) -> None:
    uid = account(f"old.links@{DOMAIN}")
    with psycopg.connect(fresh) as conn:
        for age in (40, 35, 5):
            conn.execute("INSERT INTO auth.account_tokens (user_id, purpose, nonce, created_at, revoked_at, "
                         "revoked_reason) VALUES (%s, 'reset', %s, now() - make_interval(days => %s), "
                         "now() - make_interval(days => %s), 'superseded')", (uid, secrets.token_bytes(32), age, age))
    with psycopg.connect(fresh) as conn:
        assert tokens.purge(conn, at=datetime.now(UTC)) == ("dry", 2)
        conn.commit()
        assert one(fresh, "SELECT count(*) AS n FROM auth.account_tokens")["n"] == 3, "dry deletes nothing"
        assert tokens.purge(conn, at=datetime.now(UTC), mode="on") == ("on", 2)
        conn.commit()
    assert one(fresh, "SELECT count(*) AS n FROM auth.account_tokens")["n"] == 1


def test_the_options_say_whether_recovery_by_email_works(fresh: str) -> None:
    assert anon().get("/api/v1/auth/options").json() == {"self_service": True}
    owner = signed_in(OWNER)
    assert owner.get("/api/v1/admin/users/self-service").json() == {"self_service": True, "email_sending": False}
    assert anon().get("/api/v1/admin/users/self-service").status_code == 401
    reader_id = account(f"plain@{DOMAIN}")
    reader = signed_in(f"plain@{DOMAIN}")
    assert reader.get("/api/v1/admin/users/self-service").status_code == 403
    assert reader.post(f"/api/v1/admin/users/{reader_id}/anonymise", json={"confirm": f"plain@{DOMAIN}"}
                       ).status_code == 403

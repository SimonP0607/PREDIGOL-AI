"""A person opens their own account (tramo 1 of the user's flow, UX-038), over HTTP against the migrated database,
with the e-mail provider simulated.

* The switch and its locks: born off, the routes do not exist; on, it opens only with the e-mail working, the consent
  gate final and the membership enforced.
* Registering: a pending account that cannot sign in, with no membership and no trial, its four consents written with
  the account, and a confirmation link that exists only in the e-mail.
* The same answer whatever the address (new, awaiting its link, already registered); the nickname first, and unique.
* What the form is checked for: names, address, mobile (E.164), nickname, password, consents, language.
* Limits: five attempts an hour per client, a daily cap of new accounts.
* Confirming: the right password makes the account active and signed in, a wrong one does not; the link works once.
* A new link: for an address awaiting one, within its hourly cap.
* Unconfirmed accounts: counted (dry) or closed (on) after seven days.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from fbi.auth import recovery, service, signup, throttle, tokens
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, legal, membership
from fbi.messaging import outbox
from fbi.messaging.provider import Outgoing
from tests.integration.helpers import forget_memberships, forget_sign_in_failures

DOMAIN = "u36.test"
OWNER = f"owner@{DOMAIN}"
PASSWORD = "Pitch-side-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
CHOSEN = "Corner-flag-2026-xyz"  # gitleaks:allow - the password a test person chooses when registering
SAME_SITE = {"x-requested-with": "predigol"}
BASE = "https://predigol.example"
LINK = re.compile(r"https://predigol\.example(/[a-z-]+)#t=([A-Za-z0-9_-]{43})")
REQUIRED = ("terms", "privacy", "age_18", "risk_notice")


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.account_tokens")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users WHERE email <> %s", (OWNER,))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_WEB_BASE_URL", BASE)
    reset_cache()
    reset_auth_settings()
    with psycopg.connect(migrated_database) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")
    service.create_user_unattended(email=OWNER, display_name="Owner", role="SUPER_ADMIN", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")
    mp.undo()
    reset_cache()
    reset_auth_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The door open: the switch on and every lock behind it closed (the legal texts are made final)."""
    wipe(database)
    throttle.reset_all()
    recovery.reset_all()
    signup.reset_all()
    forget_sign_in_failures()
    consents._clear.clear()
    monkeypatch.setenv(signup.SWITCH, "1")
    monkeypatch.setenv(tokens.SWITCH, "1")
    monkeypatch.setenv(consents.GATE_ENV, "1")
    monkeypatch.setenv(membership.SWITCH, "1")
    monkeypatch.delenv(signup.DAILY_CAP_ENV, raising=False)
    monkeypatch.delenv(signup.PURGE_ENV, raising=False)
    monkeypatch.delenv("FBI_EMAIL_SEND", raising=False)
    monkeypatch.setattr(legal, "any_draft", lambda: False)
    yield database
    consents._clear.clear()


def anon() -> TestClient:
    from fbi.api.app import create_app

    return TestClient(create_app(), headers=dict(SAME_SITE))


def current_consents(**changes: bool) -> list[dict[str, Any]]:
    """The consents of the form, each on the version in force: the four required ones ticked, the optional ones off."""
    wanted = {"terms": True, "privacy": True, "age_18": True, "risk_notice": True, "marketing_email": False,
              "analytics": False} | changes
    return [{"kind": k, "granted": g, "version": legal.current(legal.BY_KIND[k].document).version}
            for k, g in wanted.items()]


def form(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"first_name": "María José", "last_name": "Pérez-Gómez", "email": f"maria@{DOMAIN}",
                            "phone": "300 123 4567", "nickname": "Maria10", "password": CHOSEN, "language": "es",
                            "timezone": "America/Bogota", "consents": current_consents()}
    return body | changes


def register(c: TestClient, **changes: Any) -> Any:
    signup.reset_all()  # the hourly window of the client is the subject of its own test
    return c.post("/api/v1/auth/signup", json=form(**changes))


def error(r: Any) -> str:
    return str(r.json()["error"]["code"])


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


class Capture:
    name = "capture"

    def __init__(self) -> None:
        self.sent: list[Outgoing] = []

    def send(self, message: Outgoing) -> str:
        self.sent.append(message)
        return f"cap-{uuid.uuid4().hex}"


def deliver(dsn: str) -> list[Outgoing]:
    capture = Capture()
    with psycopg.connect(dsn) as conn:
        outbox.dispatch(conn, capture, at=datetime.now(UTC), cap=1000)
    return capture.sent


def link_of(message: Outgoing) -> str:
    found = [m.group(2) for m in LINK.finditer(message.text) if m.group(1) == "/verify-email"]
    assert found, message.text
    return found[0]


def registered(dsn: str, c: TestClient | None = None, **changes: Any) -> str:
    """Registers and returns the confirmation link that left in the e-mail."""
    r = register(c or anon(), **changes)
    assert r.status_code == 202, r.text
    email = str(form(**changes)["email"]).strip().lower()
    sent = [m for m in deliver(dsn) if m.to == email]
    assert len(sent) == 1, sent
    return link_of(sent[0])


def no_membership(dsn: str, user_id: int) -> bool:
    """No period, no event, no payment: nothing that could give a reader a day of access."""
    return all(rows(dsn, f"SELECT 1 FROM customer.{t} WHERE user_id = %s", (user_id,)) == []
               for t in ("membership_periods", "membership_events", "payments"))


def user(dsn: str, email: str = f"maria@{DOMAIN}") -> dict[str, Any]:
    return one(dsn, "SELECT * FROM auth.users WHERE email = %s", (email,))


# ── the switch and its locks ──────────────────────────────────────────────────────────

SWITCHED_OFF_ROUTES = (("/api/v1/auth/signup", None), ("/api/v1/auth/verify/check", {"token": "x" * 43}),
                       ("/api/v1/auth/verify", {"token": "x" * 43, "password": CHOSEN}),
                       ("/api/v1/auth/verify/resend", {"email": f"maria@{DOMAIN}"}))


def closed_routes(c: TestClient) -> None:
    for path, body in SWITCHED_OFF_ROUTES:
        r = c.post(path, json=form() if body is None else body)
        assert r.status_code == 404, (path, r.status_code)


def test_born_off_the_routes_do_not_exist_and_the_options_say_so(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(signup.SWITCH)
    assert not signup.enabled() and not signup.is_open()
    c = anon()
    assert c.get("/api/v1/auth/options").json() == {"self_service": True, "signup": False}
    closed_routes(c)
    assert c.get("/api/v1/auth/signup/consents").status_code == 404
    assert rows(fresh, "SELECT 1 FROM auth.users WHERE email = %s", (f"maria@{DOMAIN}",)) == []


@pytest.mark.parametrize(("break_it", "missing"), [
    ("email", "email_off"), ("gate", "consent_gate_not_final"), ("draft", "consent_gate_not_final"),
    ("membership", "membership_not_enforced")])
def test_each_lock_keeps_the_door_shut_and_names_what_is_missing(
        fresh: str, monkeypatch: pytest.MonkeyPatch, break_it: str, missing: str) -> None:
    assert signup.locks() == [] and signup.is_open()
    if break_it == "email":
        monkeypatch.setenv(tokens.SWITCH, "0")
    elif break_it == "gate":
        monkeypatch.delenv(consents.GATE_ENV)
    elif break_it == "draft":
        monkeypatch.setattr(legal, "any_draft", lambda: True)
    else:
        monkeypatch.delenv(membership.SWITCH)
    assert signup.locks() == [missing] and not signup.is_open()
    c = anon()
    assert c.get("/api/v1/auth/options").json()["signup"] is False
    closed_routes(c)


def test_open_the_options_offer_the_registration(fresh: str) -> None:
    assert anon().get("/api/v1/auth/options").json() == {"self_service": True, "signup": True}


def test_the_form_gets_the_required_boxes_with_their_exact_sentences_and_versions(fresh: str) -> None:
    for lang in ("es", "en"):
        r = anon().get("/api/v1/auth/signup/consents", params={"lang": lang})
        assert r.status_code == 200, r.text
        boxes = r.json()["purposes"]
        assert [b["kind"] for b in boxes] == list(REQUIRED)
        for b in boxes:
            doc, sentence = legal.statement(b["kind"], lang)
            assert (b["version"], b["sha256"], b["statement"], b["required"]) == (doc.version, doc.sha256, sentence, True)
    assert anon().get("/api/v1/auth/signup/consents", params={"lang": "fr"}).status_code == 422


# ── registering ───────────────────────────────────────────────────────────────────────

def test_registering_makes_a_pending_account_with_no_access_and_one_link_by_email(fresh: str) -> None:
    r = register(anon(), email=" Maria@U36.test ")
    assert r.status_code == 202, r.text
    u = user(fresh)
    assert (u["status"], u["origin"], u["role"]) == ("pending", "signup", "USER")
    assert (u["first_name"], u["last_name"], u["phone_e164"], u["display_name"]) == (
        "María José", "Pérez-Gómez", "+573001234567", "Maria10")
    assert u["email_verified_at"] is None and (u["language"], u["timezone"]) == ("es", "America/Bogota")
    assert u["password_hash"] != CHOSEN and u["password_hash"].startswith("$argon2id$")
    # nothing that gives access: no membership, no trial, no period
    assert no_membership(fresh, u["id"])
    # the four consents are written with the account, on the text in force, from the form
    given = {c["kind"]: c for c in rows(fresh, "SELECT * FROM customer.consents WHERE user_id = %s", (u["id"],))}
    assert set(given) == {*REQUIRED, "marketing_email", "analytics"}
    for kind in REQUIRED:
        c = given[kind]
        assert c["granted"] and c["source"] == "signup" and c["locale"] == "es"
        assert c["version"] == legal.current(legal.BY_KIND[kind].document).version
        assert c["sha256"] and c["statement"]
    assert not given["marketing_email"]["granted"] and not given["analytics"]["granted"]
    # a single e-mail, the confirmation, whose link exists only there
    sent = deliver(fresh)
    assert [(m.to, m.subject) for m in sent] == [(f"maria@{DOMAIN}", "Confirma tu correo en PrediGol")]
    link = link_of(sent[0])
    stored = one(fresh, "SELECT * FROM auth.account_tokens WHERE user_id = %s", (u["id"],))
    assert stored["purpose"] == "verify" and stored["token_hash"] == tokens.token_id(link)
    assert stored["expires_at"] - stored["sent_at"] == timedelta(hours=24)
    trail = [e["action"] for e in rows(fresh, "SELECT action FROM auth.audit_events WHERE target_user_id = %s "
                                              "ORDER BY id", (u["id"],))]
    assert trail == ["user.registered"]


def test_a_pending_account_cannot_sign_in_and_is_told_why(fresh: str) -> None:
    registered(fresh)
    r = anon().post("/api/v1/auth/login", json={"email": f"maria@{DOMAIN}", "password": CHOSEN})
    assert r.status_code == 403 and error(r) == "email_not_verified"
    r = anon().post("/api/v1/auth/login", json={"email": f"maria@{DOMAIN}", "password": "wrong-password-123"})
    assert r.status_code == 401 and error(r) == "invalid_credentials", "a wrong password learns nothing"


def test_the_same_answer_whether_the_address_is_new_pending_or_already_registered(fresh: str) -> None:
    new = register(anon())
    deliver(fresh)
    pending = register(anon(), nickname="Maria11")
    active_email = f"vieja@{DOMAIN}"
    service.create_user_unattended(email=active_email, display_name="Vieja", role="USER", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    active = register(anon(), email=active_email, nickname="Maria12")
    answers = {(r.status_code, r.text.replace(r.json().get("request_id", ""), "")) for r in (new, pending, active)}
    assert {r.status_code for r in (new, pending, active)} == {202}
    assert len({r.json().get("accepted") for r in (new, pending, active)}) == 1, answers
    # what happened is told by e-mail, to the owner of the address only
    sent = {(m.to, m.subject) for m in deliver(fresh)}
    assert sent == {(f"maria@{DOMAIN}", "Confirma tu correo en PrediGol"),
                    (active_email, "Ya tienes una cuenta en PrediGol")}
    assert user(fresh)["display_name"] == "Maria10", "a second form did not change the pending account"
    assert user(fresh, active_email)["status"] == "active", "nor the active one"


def test_the_nickname_is_unique_ignoring_case_and_is_checked_before_the_address(fresh: str) -> None:
    registered(fresh)
    other = register(anon(), email=f"otra@{DOMAIN}", nickname="MARIA10")
    assert other.status_code == 409 and error(other) == "display_name_taken"
    same_address = register(anon(), nickname="maria10")
    assert same_address.status_code == 409 and error(same_address) == "display_name_taken", \
        "the same answer for an address that exists and one that does not"
    assert rows(fresh, "SELECT 1 FROM auth.users WHERE email = %s", (f"otra@{DOMAIN}",)) == []


@pytest.mark.parametrize(("changes", "code"), [
    ({"first_name": ""}, "invalid_first_name"), ({"first_name": "M4ria"}, "invalid_first_name"),
    ({"first_name": "<b>x</b>"}, "invalid_first_name"), ({"last_name": "  "}, "invalid_last_name"),
    ({"email": "not-an-address"}, "invalid_email"), ({"phone": "12345"}, "invalid_phone"),
    ({"phone": "+57 200 123 4567"}, "invalid_phone"), ({"phone": "abcdefghij"}, "invalid_phone"),
    ({"nickname": "ab"}, "invalid_nickname"), ({"nickname": "me@mail.com"}, "invalid_nickname"),
    ({"nickname": "Admin"}, "invalid_nickname"), ({"nickname": "P-r-e-d-i-G-o-l"}, "invalid_nickname"),
    ({"nickname": "x" * 25}, "invalid_nickname"), ({"language": "fr"}, "invalid_language"),
    ({"timezone": "Mars/Base"}, "invalid_timezone"), ({"password": "short"}, "weak_password"),
    ({"password": f"maria@{DOMAIN}"}, "weak_password")])
def test_what_the_form_is_checked_for(fresh: str, changes: dict[str, Any], code: str) -> None:
    r = register(anon(), **changes)
    assert r.status_code == 422, r.text
    assert error(r) == code, r.text
    assert rows(fresh, "SELECT 1 FROM auth.users WHERE email = %s", (f"maria@{DOMAIN}",)) == []


def test_the_phone_is_kept_in_e164_whatever_the_way_it_was_typed() -> None:
    for typed in ("3001234567", "300 123 4567", "(300) 123-4567", "+57 300 123 4567", "0057 300 123 4567"):
        assert signup.normalize_phone(typed) == "+573001234567", typed
    assert signup.normalize_phone("+1 415 555 2671") == "+14155552671"
    for typed in ("", "3001234", "2001234567", "+57 601 234 5678", "+0123456789", "hello", "+57300123456789"):
        assert signup.normalize_phone(typed) is None, typed


def test_every_required_consent_must_be_ticked_and_on_the_text_in_force(fresh: str) -> None:
    for kind in REQUIRED:
        r = register(anon(), consents=current_consents(**{kind: False}))
        assert r.status_code == 422 and error(r) == "consents_required", kind
        assert r.json()["error"]["missing"] == [kind]
    r = register(anon(), consents=[c for c in current_consents() if c["kind"] != "terms"])
    assert r.status_code == 422 and error(r) == "consents_required"
    stale = current_consents()
    stale[0]["version"] = "2020-01-01-v0"
    r = register(anon(), consents=stale)
    assert r.status_code == 409 and error(r) == "legal_text_changed"
    assert rows(fresh, "SELECT 1 FROM auth.users WHERE email = %s", (f"maria@{DOMAIN}",)) == []
    assert rows(fresh, "SELECT 1 FROM customer.consents") == [], "no consent without its account"


def test_the_optional_consents_are_recorded_as_chosen(fresh: str) -> None:
    registered(fresh, consents=current_consents(marketing_email=True, analytics=True))
    given = {c["kind"]: c["granted"] for c in rows(fresh, "SELECT kind, granted FROM customer.consents")}
    assert given["marketing_email"] and given["analytics"]


def attempt(c: TestClient, **changes: Any) -> Any:
    """A registration that keeps the client's hourly window as it is."""
    return c.post("/api/v1/auth/signup", json=form(**changes))


def test_a_client_may_try_five_times_an_hour_and_the_account_cap_pauses_the_door(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    c = anon()
    for n in range(5):
        assert attempt(c, email=f"n{n}@{DOMAIN}", nickname=f"Nick{n}x").status_code == 202
    sixth = attempt(c, email=f"n6@{DOMAIN}", nickname="Nick6x")
    assert sixth.status_code == 429 and error(sixth) == "too_many_attempts"
    assert int(sixth.headers["retry-after"]) > 0
    signup.reset_all()
    monkeypatch.setenv(signup.DAILY_CAP_ENV, "5")
    paused = attempt(c, email=f"n7@{DOMAIN}", nickname="Nick7x")
    assert paused.status_code == 503 and error(paused) == "signup_paused"
    assert rows(fresh, "SELECT 1 FROM auth.users WHERE email = %s", (f"n7@{DOMAIN}",)) == []
    assert user(fresh, f"n0@{DOMAIN}")["status"] == "pending", "the ones already in are untouched"


# ── confirming ────────────────────────────────────────────────────────────────────────

def test_the_link_shows_the_address_and_the_nickname(fresh: str) -> None:
    link = registered(fresh)
    r = anon().post("/api/v1/auth/verify/check", json={"token": link})
    assert r.status_code == 200
    assert r.json() == {"email": f"maria@{DOMAIN}", "display_name": "Maria10", "language": "es"}


def test_confirming_with_the_chosen_password_activates_signs_in_and_gives_no_access(fresh: str) -> None:
    link = registered(fresh)
    c = anon()
    r = c.post("/api/v1/auth/verify", json={"token": link, "password": CHOSEN})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == f"maria@{DOMAIN}" and me["stage"] == "full"
    assert c.get("/api/v1/auth/me").status_code == 200, "signed in by the cookie"
    u = user(fresh)
    assert u["status"] == "active" and u["email_verified_at"] is not None
    assert no_membership(fresh, u["id"]), "confirming the address gives no membership and no trial"
    trail = [e["action"] for e in rows(fresh, "SELECT action FROM auth.audit_events WHERE target_user_id = %s "
                                              "ORDER BY id", (u["id"],))]
    assert trail[-2:] == ["user.email_verified", "login.succeeded"]
    # the link works once; the account now signs in the ordinary way
    again = anon().post("/api/v1/auth/verify", json={"token": link, "password": CHOSEN})
    assert again.status_code == 410 and error(again) == "link_invalid"
    assert anon().post("/api/v1/auth/login", json={"email": f"maria@{DOMAIN}", "password": CHOSEN}
                       ).status_code == 200


def test_a_wrong_password_does_not_confirm_and_the_link_stays_good(fresh: str) -> None:
    link = registered(fresh)
    r = anon().post("/api/v1/auth/verify", json={"token": link, "password": "Not-the-one-2026-zzz"})
    assert r.status_code == 401 and error(r) == "invalid_credentials"
    assert user(fresh)["status"] == "pending"
    assert anon().post("/api/v1/auth/verify", json={"token": link, "password": CHOSEN}).status_code == 200


def test_repeated_wrong_passwords_slow_the_link_down_like_a_sign_in(fresh: str) -> None:
    link = registered(fresh)
    c = anon()
    last = None
    for _ in range(6):
        last = c.post("/api/v1/auth/verify", json={"token": link, "password": "Not-the-one-2026-zzz"})
    assert last is not None and last.status_code == 429
    assert user(fresh)["status"] == "pending"


def test_a_link_that_does_not_work_gets_one_answer_whatever_the_reason(fresh: str) -> None:
    expired = registered(fresh)
    with psycopg.connect(fresh) as conn:
        conn.execute("UPDATE auth.account_tokens SET sent_at = now() - interval '25 hours', "
                     "expires_at = now() - interval '1 hour'")
    used = registered(fresh, email=f"usada@{DOMAIN}", nickname="Usada1")
    assert anon().post("/api/v1/auth/verify", json={"token": used, "password": CHOSEN}).status_code == 200
    answers = set()
    for link in (expired, used, "a" * 43, "not a link"):
        r = anon().post("/api/v1/auth/verify/check", json={"token": link})
        body = r.json()
        body.pop("request_id", None)
        answers.add((r.status_code, str(sorted(body.items()))))
    assert len(answers) == 1 and next(iter(answers))[0] == 410


def test_an_invitation_link_does_not_confirm_a_registration(fresh: str) -> None:
    link = registered(fresh)
    r = anon().post("/api/v1/auth/activate/check", json={"token": link})
    assert r.status_code == 410 and error(r) == "link_invalid"


# ── a new link ────────────────────────────────────────────────────────────────────────

def test_a_new_link_for_an_address_awaiting_one_replaces_the_old_and_is_capped(fresh: str) -> None:
    first = registered(fresh)
    c = anon()
    newest = first
    for _ in range(2):  # the registration's own link was the first of the hour: two more are allowed
        signup.reset_all()
        recovery.reset_all()
        assert c.post("/api/v1/auth/verify/resend", json={"email": f"maria@{DOMAIN}"}).status_code == 202
        sent = deliver(fresh)
        assert len(sent) == 1
        assert link_of(sent[0]) != newest
        newest = link_of(sent[0])
    recovery.reset_all()
    assert c.post("/api/v1/auth/verify/resend", json={"email": f"maria@{DOMAIN}"}).status_code == 202
    assert deliver(fresh) == [], "the fourth link of the hour is not made, and the answer is the same"
    assert anon().post("/api/v1/auth/verify/check", json={"token": first}).status_code == 410, "the old one stopped"
    assert anon().post("/api/v1/auth/verify", json={"token": newest, "password": CHOSEN}).status_code == 200


def test_a_new_link_says_nothing_about_other_addresses(fresh: str) -> None:
    registered(fresh)
    service.create_user_unattended(email=f"vieja@{DOMAIN}", display_name="Vieja", role="USER", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    c = anon()
    for address in (f"maria@{DOMAIN}", f"vieja@{DOMAIN}", f"nadie@{DOMAIN}"):
        recovery.reset_all()
        assert c.post("/api/v1/auth/verify/resend", json={"email": address}).status_code == 202, address
    assert [m.to for m in deliver(fresh)] == [f"maria@{DOMAIN}"], "only the address awaiting its link was sent one"


# ── what the owner sees ───────────────────────────────────────────────────────────────

def test_the_owner_sees_the_pending_account_in_the_list(fresh: str) -> None:
    registered(fresh)
    owner = anon()
    assert owner.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}).status_code == 200
    r = owner.get("/api/v1/admin/users")
    assert r.status_code == 200, r.text
    listed = {u["email"]: u for u in r.json()["data"]}
    assert listed[f"maria@{DOMAIN}"]["status"] == "pending"


# ── closing what was never confirmed ──────────────────────────────────────────────────

def test_unconfirmed_accounts_are_counted_then_closed_after_seven_days(fresh: str) -> None:
    registered(fresh)
    registered(fresh, email=f"nueva@{DOMAIN}", nickname="Nueva1")
    with psycopg.connect(fresh) as conn:
        conn.execute("UPDATE auth.users SET created_at = now() - interval '8 days' WHERE email = %s",
                     (f"maria@{DOMAIN}",))
        at = datetime.now(UTC)
        assert signup.purge_unconfirmed(conn, at=at) == ("dry", 1), "born in dry: counts, closes nothing"
        conn.commit()
        assert user(fresh)["status"] == "pending"
        assert signup.purge_unconfirmed(conn, at=at, mode="off") == ("off", 0)
        assert signup.purge_unconfirmed(conn, at=at, mode="on") == ("on", 1)
        conn.commit()
    closed = one(fresh, "SELECT * FROM auth.users WHERE display_name LIKE 'deleted-%%'")
    assert closed["status"] == "deleted" and closed["email"].endswith("@deleted.invalid")
    assert closed["first_name"] is None and closed["last_name"] is None and closed["phone_e164"] is None
    assert user(fresh, f"nueva@{DOMAIN}")["status"] == "pending", "a recent one stays"
    # its consents stay (they point at the account); the nickname is free again
    assert rows(fresh, "SELECT 1 FROM customer.consents WHERE user_id = %s", (closed["id"],)) != []
    assert registered(fresh, email=f"otra@{DOMAIN}", nickname="Maria10")
    # and the link it had no longer works
    sent_left = rows(fresh, "SELECT 1 FROM auth.account_tokens WHERE user_id = %s AND revoked_at IS NULL "
                            "AND used_at IS NULL", (closed["id"],))
    assert sent_left == []


def test_the_purge_mode_is_born_dry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(signup.PURGE_ENV, raising=False)
    assert signup.purge_mode() == "dry"
    for raw, mode in (("on", "on"), ("1", "on"), ("off", "off"), ("0", "off"), ("whatever", "dry")):
        monkeypatch.setenv(signup.PURGE_ENV, raw)
        assert signup.purge_mode() == mode

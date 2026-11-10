"""The membership against PostgreSQL and the API (plan UX, A8): the trial at the activation, the owner's payment and
extension (idempotent, chained from the end in force, never an account number), the gate with its limited access and
its exemptions, the notices of a period's end (once each), the owner's morning count and the reader's export.

Periods are written in the past where a test needs a moment the clock has not reached: the state is computed from
dates, never stored, so a trial that ended 20 days ago is a trial that ended 20 days ago."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from fbi.auth import recovery, service, store, throttle, tokens
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, membership
from fbi.customer.db import CustomerError
from fbi.messaging import notices, outbox
from fbi.messaging.templates import check_params, render
from tests.integration.helpers import forget_memberships, forget_sign_in_failures

DOMAIN = "a8.test"
OWNER = f"owner@{DOMAIN}"
ROBOT = f"robot@{DOMAIN}"
PASSWORD = "Season-pass-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
SAME_SITE = {"x-requested-with": "predigol"}
DAY = timedelta(days=1)


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        forget_memberships(conn)
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.product_events",
                      "customer.activity_daily"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind = 'membership_due'")
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
    reset_cache()
    reset_auth_settings()
    with psycopg.connect(migrated_database) as conn:
        forget_memberships(conn)
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.preferences", "customer.ticket_messages",
                      "customer.support_tickets", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM picks.user_parlays")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM auth.account_tokens")
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
    membership.forget()
    monkeypatch.delenv(consents.GATE_ENV, raising=False)
    monkeypatch.delenv(membership.SWITCH, raising=False)
    monkeypatch.delenv("FBI_TRIAL_DAYS", raising=False)
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    yield database
    membership.forget()


def client() -> TestClient:
    from fbi.api.app import create_app

    return TestClient(create_app(), headers=SAME_SITE)


def signed_in(email: str) -> TestClient:
    c = client()
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def account(email: str) -> int:
    row = service.create_user_unattended(email=email, display_name=email.split("@")[0].title(), role="USER",
                                         password=PASSWORD, language="es", timezone="America/Bogota")
    return int(row["id"])


def uid_of(email: str, dsn: str) -> int:
    return int(one(dsn, "SELECT id FROM auth.users WHERE email = %s", (email,))["id"])


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


def backdated(dsn: str, user_id: int, kind: str, *, ended_days_ago: float, days: int = 14) -> int:
    """A period that ended ``ended_days_ago`` (negative: still running), written as the owner's code would."""
    end = datetime.now(UTC) - timedelta(days=ended_days_ago)
    start = end - timedelta(days=days)
    with psycopg.connect(dsn) as conn:
        payment = None
        if kind == "paid":
            payment = conn.execute("""
                INSERT INTO customer.payments (user_id, amount, currency, method, idempotency_key, recorded_at)
                VALUES (%s, 50000, 'COP', 'nequi', %s, %s) RETURNING id
            """, (user_id, uuid.uuid4().hex, start)).fetchone()[0]  # type: ignore[index]
        row = conn.execute("""
            INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, payment_id, created_at, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, kind, start, end, payment, start, "por la prueba" if kind == "courtesy" else None)).fetchone()
    assert row is not None
    return int(row[0])


def pay(owner: TestClient, user_id: int, **extra: Any) -> Any:
    body = {"amount": "50000", "currency": "COP", "method": "nequi", "reference": "Nequi 25 oct", "months": 1,
            "idempotency_key": uuid.uuid4().hex, **extra}
    return owner.post(f"/api/v1/admin/users/{user_id}/membership/payments", json=body)


def error(r: Any) -> str:
    return str(r.json()["error"]["code"])


def server_events(dsn: str, name: str) -> int:
    return int(one(dsn, "SELECT count(*) AS n FROM customer.product_events WHERE name = %s", (name,))["n"])


# ── the trial ───────────────────────────────────────────────────────────────────────────

def test_an_invitation_plans_the_trial_and_the_activation_starts_it(fresh: str, monkeypatch: pytest.MonkeyPatch,
                                                                   ) -> None:
    monkeypatch.setenv(tokens.SWITCH, "1")
    owner = signed_in(OWNER)
    r = owner.post("/api/v1/admin/users/invite", json={"email": f"inv@{DOMAIN}", "trial_days": 10})
    assert r.status_code == 201, r.text
    assert owner.post("/api/v1/admin/users/invite", json={"email": f"bad@{DOMAIN}", "trial_days": 30}
                      ).status_code == 422
    user_id = int(r.json()["data"]["id"])
    assert one(fresh, "SELECT detail FROM customer.membership_events WHERE user_id = %s AND kind = 'trial_planned'",
               (user_id,))["detail"] == {"days": 10}
    # the activation (A7) in its own transaction, as the API does it
    from fbi.auth import invitations

    with psycopg.connect(fresh) as conn:
        grant = tokens.issue(conn, user_id, "invite")
        assert grant is not None
        armed = tokens.arm(conn, grant, user_id=user_id, purpose="invite", at=datetime.now(UTC))
        assert armed is not None
        conn.commit()
    invitations.activate(armed.link, password="La-final-se-juega-en-mayo", language="es",
                         timezone="America/Bogota", ip=None, user_agent=None)
    trial = one(fresh, "SELECT kind, ends_at - starts_at AS length FROM customer.membership_periods "
                       "WHERE user_id = %s", (user_id,))
    assert (trial["kind"], trial["length"]) == ("trial", 10 * DAY)
    assert server_events(fresh, "trial_started") == 1
    # one e-mail tells the account is active and when its trial ends (closing plan 4.1), not two
    ends = one(fresh, "SELECT ends_at FROM customer.membership_periods WHERE user_id = %s", (user_id,))["ends_at"]
    welcome = [(r["template"], r["params"], r["dedup_key"]) for r in rows(
        fresh, "SELECT template, params, dedup_key FROM customer.messages_outbox WHERE user_id = %s "
               "AND template <> 'invitation'", (user_id,))]
    assert welcome == [("welcome", {"ends": ends.astimezone(UTC).isoformat(timespec="seconds")},
                        f"welcome:{user_id}")]
    me = client()
    assert me.post("/api/v1/auth/login", json={"email": f"inv@{DOMAIN}",
                                               "password": "La-final-se-juega-en-mayo"}).status_code == 200
    summary = me.get("/api/v1/auth/me").json()["membership"]
    assert (summary["state"], summary["kind"], summary["days_left"], summary["limited"]) == ("trial", "trial", 10,
                                                                                            False)


def test_the_console_starts_a_trial_for_a_reader_it_creates_and_none_for_the_owners(fresh: str) -> None:
    owner = signed_in(OWNER)
    base = {"password": "Harbour-lights-2026-xy", "language": "es", "timezone": "America/Bogota"}  # gitleaks:allow
    reader = owner.post("/api/v1/admin/users", json={"email": f"temp@{DOMAIN}", "role": "USER", **base})
    admin = owner.post("/api/v1/admin/users", json={"email": f"boss@{DOMAIN}", "role": "SUPER_ADMIN", **base})
    assert reader.status_code == 201 and admin.status_code == 201, (reader.text, admin.text)
    periods = rows(fresh, "SELECT u.email, p.kind, p.ends_at - p.starts_at AS length FROM customer.membership_periods p "
                          "JOIN auth.users u ON u.id = p.user_id")
    assert periods == [{"email": f"temp@{DOMAIN}", "kind": "trial", "length": 20 * DAY}]
    listed = {u["email"]: u["membership"] for u in owner.get("/api/v1/admin/users").json()["data"]}
    assert listed[f"temp@{DOMAIN}"]["state"] == "trial"
    assert listed[OWNER] is None and listed[ROBOT] is None, "the owner and the robot have no membership"
    # one trial per account: the owner's «start a trial» is for an account that never had one
    temp_id = uid_of(f"temp@{DOMAIN}", fresh)
    assert queued(fresh) == [], "an account the owner created with a password is told nothing by e-mail"
    again = owner.post(f"/api/v1/admin/users/{temp_id}/membership/trial", json={"days": 7})
    assert again.status_code == 409 and error(again) == "trial_used"
    legacy = account(f"legacy@{DOMAIN}")
    started = owner.post(f"/api/v1/admin/users/{legacy}/membership/trial", json={"days": 7})
    assert started.status_code == 200, started.text
    assert started.json()["membership"]["state"] == "trial"
    # the trial the owner starts for an account that already existed is told once, with its end (closing plan 4.1)
    [(email, template, params)] = queued(fresh)
    assert (email, template) == (f"legacy@{DOMAIN}", "trial_started")
    end = one(fresh, "SELECT ends_at FROM customer.membership_periods WHERE user_id = %s", (legacy,))["ends_at"]
    assert params == {"ends": end.astimezone(UTC).isoformat(timespec="seconds")}


# ── the owner's payment ─────────────────────────────────────────────────────────────────

def test_a_payment_extends_from_the_end_in_force_once_per_key(fresh: str) -> None:
    reader = account(f"payer@{DOMAIN}")
    trial = backdated(fresh, reader, "trial", ended_days_ago=-2)  # two days left
    owner = signed_in(OWNER)
    key = uuid.uuid4().hex
    first = pay(owner, reader, idempotency_key=key, months=1)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True
    again = pay(owner, reader, idempotency_key=key, months=1)
    assert again.status_code == 200 and again.json()["created"] is False, "a repeated click records one payment"
    assert [t for _, t, _ in queued(fresh)] == ["payment_recorded"], "and tells the reader once (closing plan 4.1)"
    assert one(fresh, "SELECT count(*) AS n FROM customer.payments WHERE user_id = %s", (reader,))["n"] == 1
    trial_end = one(fresh, "SELECT ends_at FROM customer.membership_periods WHERE id = %s", (trial,))["ends_at"]
    paid = one(fresh, "SELECT starts_at, ends_at FROM customer.membership_periods WHERE user_id = %s AND kind = 'paid'",
               (reader,))
    assert paid["starts_at"] == trial_end, "the new period starts where the trial ends"
    assert paid["ends_at"] == membership.add_months(trial_end, 1)
    view = first.json()["membership"]
    assert view["membership"]["state"] == "active", "the first payment after the trial: active, never renewed"
    assert [p["kind"] for p in view["periods"]] == ["paid", "trial"]
    assert view["periods"][0]["reference"] == "Nequi 25 oct"
    trail = one(fresh, "SELECT detail FROM auth.audit_events WHERE action = 'membership.payment_recorded'")["detail"]
    assert trail == {"amount": "50000.00", "currency": "COP", "method": "nequi", "months": 1, "renewal": False}
    assert "Nequi" not in str(trail), "the reference stays out of the trail"
    renewal = pay(owner, reader, months=2)
    assert renewal.json()["membership"]["membership"]["state"] == "renewed"
    told = queued(fresh)
    assert [t for _, t, _ in told] == ["payment_recorded", "payment_recorded"]
    renewed_to = one(fresh, "SELECT max(ends_at) AS e FROM customer.membership_periods WHERE user_id = %s",
                     (reader,))["e"]
    assert told[1][2] == {"ends": renewed_to.astimezone(UTC).isoformat(timespec="seconds")}
    assert all(email == f"payer@{DOMAIN}" for email, _, _ in told)
    assert server_events(fresh, "membership_renewed") == 2
    # someone else's key, a card number, a bad amount
    other = account(f"other@{DOMAIN}")
    clash = pay(owner, other, idempotency_key=key)
    assert clash.status_code == 409 and error(clash) == "idempotency_conflict"
    card = pay(owner, other, reference="tarjeta 4111 1111 1111 1111")
    assert card.status_code == 422 and error(card) == "reference_has_number"
    assert pay(owner, other, amount="-5").status_code == 422
    assert pay(owner, other, method="bitcoin").status_code == 422
    assert one(fresh, "SELECT count(*) AS n FROM customer.payments WHERE user_id = %s", (other,))["n"] == 0


def test_only_the_owner_records_and_a_reader_reads_only_their_own(fresh: str) -> None:
    reader = account(f"reader@{DOMAIN}")
    victim = account(f"victim@{DOMAIN}")
    backdated(fresh, victim, "trial", ended_days_ago=-5)
    c = signed_in(f"reader@{DOMAIN}")
    for path, body in ((f"/api/v1/admin/users/{victim}/membership/payments",
                        {"amount": "1", "currency": "COP", "method": "cash", "months": 1,
                         "idempotency_key": uuid.uuid4().hex}),
                       (f"/api/v1/admin/users/{reader}/membership/courtesy", {"days": 30, "reason": "por mí"})):
        assert c.post(path, json=body).status_code == 403
    assert c.get(f"/api/v1/admin/users/{victim}/membership").status_code == 403
    mine = c.get("/api/v1/me/membership").json()
    assert mine["membership"]["state"] == "none" and mine["periods"] == []
    assert mine["plan"] == {
        "trial_days": 20,
        "prices": [{"currency": "COP", "amount": "150000"}, {"currency": "USD", "amount": "50"}],
    }, "the one plan: the owner's price in both currencies and the 20-day trial (UX-004)"
    owner = signed_in(OWNER)
    exempt = owner.post(f"/api/v1/admin/users/{uid_of(OWNER, fresh)}/membership/courtesy",
                        json={"days": 5, "reason": "a mí mismo"})
    assert exempt.status_code == 409 and error(exempt) == "membership_exempt"
    assert owner.get("/api/v1/me/membership").json()["membership"] is None


def test_courtesy_suspension_and_will_not_renew(fresh: str) -> None:
    reader = account(f"court@{DOMAIN}")
    owner = signed_in(OWNER)
    r = owner.post(f"/api/v1/admin/users/{reader}/membership/courtesy", json={"days": 20, "reason": "error nuestro"})
    assert r.status_code == 200 and r.json()["membership"]["state"] == "active"
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/courtesy", json={"days": 0, "reason": "x"}
                      ).status_code == 422
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/lift", json={"reason": "nada que levantar"}
                      ).status_code == 409
    s = owner.post(f"/api/v1/admin/users/{reader}/membership/suspend", json={"reason": "revisión de pago"})
    assert s.json()["membership"]["state"] == "suspended" and s.json()["suspended_reason"] == "revisión de pago"
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/suspend", json={"reason": "otra vez"}
                      ).status_code == 409
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/suspend", json={}).status_code == 422
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/lift", json={"reason": "aclarado"}
                      ).json()["membership"]["state"] == "active"
    n = owner.post(f"/api/v1/admin/users/{reader}/membership/renewal", json={"will_renew": False})
    assert n.status_code == 422 and error(n) == "reason_required"
    n = owner.post(f"/api/v1/admin/users/{reader}/membership/renewal",
                   json={"will_renew": False, "reason": "se muda de país"})
    assert n.json()["membership"]["will_not_renew"] is True
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/renewal",
                      json={"will_renew": False, "reason": "otra"}).status_code == 409
    actions = [r["action"] for r in rows(fresh, "SELECT action FROM auth.audit_events WHERE target_user_id = %s "
                                                "AND action LIKE 'membership.%%' ORDER BY id", (reader,))]
    assert actions == ["membership.courtesy_granted", "membership.suspended", "membership.suspension_lifted",
                       "membership.will_not_renew"]


# ── the gate ────────────────────────────────────────────────────────────────────────────

def test_an_ended_membership_reads_only_its_own_records_once_the_switch_is_on(fresh: str,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    reader = account(f"late@{DOMAIN}")
    backdated(fresh, reader, "trial", ended_days_ago=5)
    c = signed_in(f"late@{DOMAIN}")
    assert c.get("/api/v1/home").status_code == 200, "the switch off limits nobody"
    assert c.get("/api/v1/auth/me").json()["membership"]["state"] == "expired"
    monkeypatch.setenv(membership.SWITCH, "1")
    membership.forget()
    refused = c.get("/api/v1/home")
    assert refused.status_code == 403 and error(refused) == "membership_expired"
    write = c.post("/api/v1/me/picks", json={"fixture_id": 1, "market_key": "1X2", "selection": "Home"})
    assert write.status_code == 403, "its records are read, never changed"
    for path in ("/api/v1/me/picks", "/api/v1/me/parlays", "/api/v1/me/history", "/api/v1/me/membership",
                 "/api/v1/me/consents", "/api/v1/auth/me", "/api/v1/me/preferences"):
        assert c.get(path).status_code == 200, path
    assert c.get("/api/v1/auth/me").json()["membership"]["limited"] is True
    # the owner renews: everything is back at once in the process that recorded it
    assert pay(signed_in(OWNER), reader).status_code == 200
    assert c.get("/api/v1/home").status_code == 200
    # the robot and the owner are never limited
    robot = uid_of(ROBOT, fresh)
    backdated(fresh, robot, "trial", ended_days_ago=10)
    assert signed_in(ROBOT).get("/api/v1/home").status_code == 200
    assert signed_in(OWNER).get("/api/v1/home").status_code == 200
    # without any period (a registered reader has no trial): limited like an ended one, with its own code
    account(f"old@{DOMAIN}")
    waiting = signed_in(f"old@{DOMAIN}")
    refused = waiting.get("/api/v1/home")
    assert refused.status_code == 403 and error(refused) == "membership_required"
    assert waiting.get("/api/v1/auth/me").json()["membership"]["state"] == "none"
    assert waiting.get("/api/v1/auth/me").json()["membership"]["limited"] is True
    assert waiting.post("/api/v1/me/picks", json={"fixture_id": 1, "market_key": "1X2", "selection": "Home"}
                        ).status_code == 403
    for path in ("/api/v1/me/picks", "/api/v1/me/history", "/api/v1/me/membership", "/api/v1/me/consents",
                 "/api/v1/me/preferences"):
        assert waiting.get(path).status_code == 200, path
    # the owner gives it its period: the door opens at once
    assert pay(signed_in(OWNER), uid_of(f"old@{DOMAIN}", fresh)).status_code == 200
    assert waiting.get("/api/v1/home").status_code == 200


def test_a_reader_without_a_period_is_not_limited_while_the_switch_is_off(fresh: str) -> None:
    account(f"free@{DOMAIN}")
    c = signed_in(f"free@{DOMAIN}")
    me = c.get("/api/v1/auth/me").json()["membership"]
    assert (me["state"], me["limited"]) == ("none", False)
    assert c.get("/api/v1/home").status_code == 200


def test_a_suspended_membership_says_so(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(membership.SWITCH, "1")
    reader = account(f"susp@{DOMAIN}")
    backdated(fresh, reader, "trial", ended_days_ago=-7)
    c = signed_in(f"susp@{DOMAIN}")
    owner = signed_in(OWNER)
    owner.post(f"/api/v1/admin/users/{reader}/membership/suspend", json={"reason": "uso indebido"})
    refused = c.get("/api/v1/home")
    assert refused.status_code == 403 and error(refused) == "membership_suspended"
    assert c.get("/api/v1/auth/me").status_code == 200, "suspended is not disabled: the session stays"
    no_reason = owner.post(f"/api/v1/admin/users/{reader}/membership/lift", json={})
    assert no_reason.status_code == 422 and error(no_reason) == "reason_required"
    owner.post(f"/api/v1/admin/users/{reader}/membership/lift", json={"reason": "aclarado"})
    assert c.get("/api/v1/home").status_code == 200


# ── the messenger's notices ─────────────────────────────────────────────────────────────

def remind(dsn: str, at: datetime | None = None) -> int:
    with psycopg.connect(dsn) as conn:
        return membership.remind(conn, at=at or datetime.now(UTC))


def queued(dsn: str) -> list[tuple[str, str, dict[str, str]]]:
    return [(r["email"], r["template"], r["params"]) for r in rows(dsn, """
        SELECT u.email, o.template, o.params FROM customer.messages_outbox o JOIN auth.users u ON u.id = o.user_id
         WHERE o.status = 'queued' ORDER BY o.id""")]


def test_each_end_is_told_once_before_at_the_end_and_after_the_grace(fresh: str) -> None:
    soon = account(f"soon@{DOMAIN}")
    backdated(fresh, soon, "trial", ended_days_ago=-2)          # 2 days left of a trial: «before»
    due = account(f"due@{DOMAIN}")
    backdated(fresh, due, "paid", ended_days_ago=1, days=30)    # ended yesterday: «due», three days of grace
    gone = account(f"gone@{DOMAIN}")
    backdated(fresh, gone, "paid", ended_days_ago=4, days=30)   # grace over: «grace_end», the app only
    quiet = account(f"quiet@{DOMAIN}")
    backdated(fresh, quiet, "trial", ended_days_ago=-1)
    signed_in(OWNER).post(f"/api/v1/admin/users/{quiet}/membership/renewal",
                          json={"will_renew": False, "reason": "no le sirve"})
    far = account(f"far@{DOMAIN}")
    backdated(fresh, far, "trial", ended_days_ago=-10)          # nothing yet
    backdated(fresh, uid_of(ROBOT, fresh), "trial", ended_days_ago=-1)  # exempt: never told
    assert remind(fresh) == 4
    assert remind(fresh) == 0, "once per period and milestone"
    assert sorted((e, t) for e, t, _ in queued(fresh)) == [(f"due@{DOMAIN}", "membership_grace"),
                                                           (f"soon@{DOMAIN}", "membership_expiring")]
    notices_ = {(r["email"], r["milestone"], r["detail"]["email"]) for r in rows(fresh, """
        SELECT u.email, e.milestone, e.detail FROM customer.membership_events e JOIN auth.users u ON u.id = e.user_id
         WHERE e.kind = 'notice'""")}
    assert notices_ == {(f"soon@{DOMAIN}", "before", True), (f"due@{DOMAIN}", "due", True),
                        (f"gone@{DOMAIN}", "grace_end", False), (f"quiet@{DOMAIN}", "before", False)}
    assert server_events(fresh, "membership_expired") == 1
    # the messages render in the reader's words, and one past its moment is not sent
    for _, template, params in queued(fresh):
        check_params(template, params)
        text = render(template, "es", params, {"name": "Ana"}, zone="America/Bogota").text
        assert "Para renovar" in text and "{" not in text
    expiring = next(params for _, template, params in queued(fresh) if template == "membership_expiring")
    row = {"email": f"soon@{DOMAIN}", "template": "membership_expiring", "email_status": None, "email_off": None,
           "category": "membership", "created_at": datetime.now(UTC), "params": expiring}
    ends = datetime.fromisoformat(expiring["ends"])
    assert outbox.suppression(row, at=ends - timedelta(minutes=1)) is None
    assert outbox.suppression(row, at=ends) == "too late: its moment has passed"


def test_the_owners_morning_count_says_numbers_never_names(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    grace = account(f"grace@{DOMAIN}")
    backdated(fresh, grace, "trial", ended_days_ago=1)
    late = account(f"limited@{DOMAIN}")
    backdated(fresh, late, "trial", ended_days_ago=3.5)  # its grace ended twelve hours ago
    now = datetime.now(UTC)
    with psycopg.connect(fresh) as conn:
        monkeypatch.setattr(notices, "MORNING_HOUR", 24)
        assert notices.membership_due(conn, at=now) == [], "before the morning in Bogotá: nothing"
        monkeypatch.setattr(notices, "MORNING_HOUR", 0)
        drafts = notices.membership_due(conn, at=now)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.kind == "membership_due" and d.dedup_key.startswith("membership_due:")
    assert (d.payload["in_grace"], d.payload["expired_today"]) == (1, 1)
    assert "grace@" not in d.body and "limited@" not in d.body and "/admin/users?membership=due" in d.body


def test_the_readers_export_holds_their_membership(fresh: str) -> None:
    reader = account(f"export@{DOMAIN}")
    backdated(fresh, reader, "trial", ended_days_ago=-3)
    owner = signed_in(OWNER)
    pay(owner, reader, reference="Daviplata 24 oct")
    from fbi.customer import privacy

    with psycopg.connect(fresh) as conn:
        document = privacy.export(conn, reader)
    assert [p["kind"] for p in document["membership_periods"]] == ["paid", "trial"]
    assert document["payments"][0]["reference"] == "Daviplata 24 oct"
    assert {"recorded_by", "actor_user_id"}.isdisjoint(document["payments"][0])
    assert any(e["kind"] == "payment_recorded" for e in document["membership_events"])


def test_the_access_trail_names_the_owners_membership_actions(fresh: str) -> None:
    reader = account(f"trail@{DOMAIN}")
    owner = signed_in(OWNER)
    owner.post(f"/api/v1/admin/users/{reader}/membership/trial", json={"days": 14})
    with psycopg.connect(fresh) as conn:
        found = [r["action"] for r in store.access_history(conn, reader, limit=10)]
    assert "membership.trial_started" not in found, "the reader's own access history is about signing in"
    actions = [r["action"] for r in rows(fresh, "SELECT action FROM auth.audit_events WHERE target_user_id = %s",
                                         (reader,))]
    assert "membership.trial_started" in actions


# ── the temporary trial for the accounts that exist (tramo 1) ───────────────────────────

def test_the_existing_accounts_get_a_temporary_trial_and_nothing_else_moves(fresh: str,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(membership.SWITCH, "1")
    bare = account(f"bare@{DOMAIN}")
    paid = account(f"paid@{DOMAIN}")
    on_trial = account(f"trial@{DOMAIN}")
    gone = account(f"gone@{DOMAIN}")
    owner_id = uid_of(OWNER, fresh)
    assert pay(signed_in(OWNER), paid).status_code == 200
    backdated(fresh, on_trial, "trial", ended_days_ago=-5)
    with psycopg.connect(fresh) as conn:
        conn.execute("UPDATE auth.users SET status = 'disabled' WHERE id = %s", (gone,))
    before = {r["user_id"]: r["n"] for r in rows(fresh, "SELECT user_id, count(*) n FROM customer.membership_periods "
                                                       "GROUP BY 1")}
    # the day before the trial: the account is limited, the enforced membership gives it nothing
    waiting = signed_in(f"bare@{DOMAIN}")
    assert error(waiting.get("/api/v1/home")) == "membership_required"

    dry = {o.user_id: o for o in membership.grant_existing_trials(days=20, reason="account before the registration",
                                                                  apply=False)}
    assert dry[bare].result == "would_grant" and dry[paid].result == "has_period"
    assert dry[on_trial].result == "has_period" and owner_id not in dry and gone not in dry
    assert dry[uid_of(ROBOT, fresh)].result == "exempt"
    assert rows(fresh, "SELECT 1 FROM customer.membership_periods WHERE user_id = %s", (bare,)) == [], "a count writes nothing"

    done = {o.user_id: o for o in membership.grant_existing_trials(days=20, reason="account before the registration",
                                                                   apply=True)}
    assert done[bare].result == "granted" and done[paid].result == "has_period"
    period = one(fresh, "SELECT * FROM customer.membership_periods WHERE user_id = %s", (bare,))
    assert period["kind"] == "trial" and period["ends_at"] - period["starts_at"] == timedelta(days=20)
    assert abs((period["starts_at"] - datetime.now(UTC)).total_seconds()) < 60
    audit = one(fresh, "SELECT * FROM auth.audit_events WHERE action = 'membership.trial_started' AND target_user_id = %s",
                (bare,))
    assert audit["actor_user_id"] is None
    assert audit["detail"] == {"days": 20, "source": "existing_accounts", "reason": "account before the registration"}
    assert waiting.get("/api/v1/home").status_code == 200, "the door opens at once"
    assert waiting.get("/api/v1/auth/me").json()["membership"]["state"] == "trial"
    # nothing else moved: the paid and the running trial keep their only period, the disabled one has none, no e-mail left
    after = {r["user_id"]: r["n"] for r in rows(fresh, "SELECT user_id, count(*) n FROM customer.membership_periods "
                                                      "GROUP BY 1")}
    assert after == {**before, bare: 1}
    assert rows(fresh, "SELECT 1 FROM customer.messages_outbox WHERE user_id = %s AND template = 'trial_started'",
                (bare,)) == []
    # twice grants nothing
    again = membership.grant_existing_trials(days=20, reason="again", apply=True)
    assert [o.result for o in again if o.user_id == bare] == ["has_period"]
    assert len(rows(fresh, "SELECT 1 FROM customer.membership_periods WHERE user_id = %s", (bare,))) == 1


def test_when_the_temporary_trial_ends_only_the_benefit_goes(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(membership.SWITCH, "1")
    bare = account(f"ends@{DOMAIN}")
    # granted 12 days ago for 7: the week passed and the 3 days of grace too (periods are append-only: the past is
    # written as the past, never edited)
    membership.grant_existing_trials(days=7, reason="temporary", apply=True, at=datetime.now(UTC) - timedelta(days=12))
    c = signed_in(f"ends@{DOMAIN}")
    membership.forget()
    refused = c.get("/api/v1/home")
    assert refused.status_code == 403 and error(refused) == "membership_expired"
    me = c.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["membership"]["state"] == "expired", "the account and its data stay"
    assert one(fresh, "SELECT status FROM auth.users WHERE id = %s", (bare,))["status"] == "active"
    # the normal flow now: the owner records a payment and the door opens
    assert pay(signed_in(OWNER), bare).status_code == 200
    assert c.get("/api/v1/home").status_code == 200


def test_the_temporary_trial_asks_for_an_explicit_length_and_a_reason(fresh: str) -> None:
    for days in (0, 6, 21):
        with pytest.raises(CustomerError) as err:
            membership.grant_existing_trials(days=days, reason="x", apply=False)
        assert err.value.code == "invalid_trial_days"
    with pytest.raises(CustomerError) as err2:
        membership.grant_existing_trials(days=14, reason="  ", apply=False)
    assert err2.value.status == 422

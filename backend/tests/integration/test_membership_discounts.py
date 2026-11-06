"""The coupons and the loyalty discount against PostgreSQL and the API (UX-005): the owner creates and disables a coupon, a
reader holds it by its code, the console proposes the discount and the payment keeps it; the larger discount wins and they
never add up; a coupon is used once; and the tables refuse what is not creating or disabling a coupon.

The accounts, the owner and the helpers are those of the membership's own tests (A8)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.auth import throttle
from fbi.customer import discounts, membership, privacy
from tests.integration.test_membership import (  # noqa: F401  (the fixtures are used by name)
    DOMAIN,
    OWNER,
    account,
    backdated,
    database,
    error,
    fresh,
    one,
    pay,
    rows,
    signed_in,
    uid_of,
)


class RollbackError(Exception):
    """Ends a transaction a test only wanted to look inside of."""


COUPONS = "/api/v1/admin/coupons"
ME = "/api/v1/me/membership"


@pytest.fixture()
def clean(fresh: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:  # noqa: F811
    for name in ("FBI_LOYALTY_PERCENT", "FBI_LOYALTY_AFTER_MONTHS", "FBI_MEMBERSHIP_PRICE_COP",
                 "FBI_MEMBERSHIP_PRICE_USD"):
        monkeypatch.delenv(name, raising=False)
    import fbi.api.routers.membership as router

    router.CODE_TRIES = throttle.FailureWindow(max_failures=10, window_s=900)
    yield fresh


def coupon(owner: Any, code: str = "BIENVENIDA", percent: int = 30, **extra: Any) -> dict[str, Any]:
    r = owner.post(COUPONS, json={"code": code, "percent": percent, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def redeem(reader: Any, code: str) -> Any:
    return reader.post(f"{ME}/coupon", json={"code": code})


def standing(reader: Any) -> dict[str, Any]:
    return reader.get(ME).json()["discounts"]


def paid_for(owner: Any, user_id: int, months: int, **extra: Any) -> Any:
    r = pay(owner, user_id, months=months, **extra)
    assert r.status_code == 200, r.text
    return r


def maintenance(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> None:
    """A change the tables refuse an ordinary session, under the documented switch - to put a coupon in a past the clock has
    not reached."""
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute(sql, params)


# ── the coupon ──────────────────────────────────────────────────────────────────────────

def test_a_reader_holds_a_coupon_and_the_payment_keeps_the_discount_once(clean: str) -> None:
    reader = account(f"holder@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"holder@{DOMAIN}")
    made = coupon(owner, "bienvenida", 30, note="Para los primeros lectores")
    assert made["code"] == "BIENVENIDA" and made["active"] is True and made["redemptions"] == 0
    assert standing(mine) == {"offer": None, "coupons": [], "loyalty": {
        "percent": 20, "after_months": 2, "paid_months": 0, "active": False}}
    got = redeem(mine, " bienvenida ")
    assert got.status_code == 200, got.text
    body = got.json()
    assert (body["code"], body["percent"]) == ("BIENVENIDA", 30)
    assert body["discounts"]["offer"] == {
        "kind": "coupon", "percent": 30, "code": "BIENVENIDA",
        "prices": [{"currency": "COP", "amount": "105000"}, {"currency": "USD", "amount": "35"}]}
    assert body["discounts"]["coupons"] == [{"code": "BIENVENIDA", "percent": 30}]
    again = redeem(mine, "BIENVENIDA")
    assert again.status_code == 409 and error(again) == "coupon_already_yours"
    # the console proposes it and the payment keeps it
    view = owner.get(f"/api/v1/admin/users/{reader}/membership").json()
    assert view["discount"]["percent"] == 30 and view["discount"]["code"] == "BIENVENIDA"
    assert [p["amount"] for p in view["prices"]] == ["150000", "50"]
    recorded = pay(owner, reader, amount="105000", apply_discount=True)
    assert recorded.status_code == 200, recorded.text
    paid = recorded.json()["membership"]["periods"][0]
    assert (paid["discount_percent"], paid["discount_kind"], paid["coupon_code"]) == (30, "coupon", "BIENVENIDA")
    assert recorded.json()["membership"]["discount"] is None, "a coupon is used once"
    trail = one(clean, "SELECT detail FROM auth.audit_events WHERE action = 'membership.payment_recorded'")["detail"]
    assert trail["discount"] == {"kind": "coupon", "percent": 30}
    assert standing(mine)["offer"] is None and standing(mine)["coupons"] == []
    assert mine.get(ME).json()["periods"][0]["discount_percent"] == 30
    listed = owner.get(COUPONS).json()["coupons"]
    assert [(c["code"], c["redemptions"], c["used"]) for c in listed] == [("BIENVENIDA", 1, 1)]
    nothing = pay(owner, reader, apply_discount=True)
    assert nothing.status_code == 409 and error(nothing) == "no_discount"
    assert one(clean, "SELECT count(*) AS n FROM customer.payments WHERE user_id = %s", (reader,))["n"] == 1


def test_a_payment_without_the_flag_carries_no_discount_and_leaves_the_coupon_held(clean: str) -> None:
    reader = account(f"plain@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"plain@{DOMAIN}")
    coupon(owner, "SOLO10", 10)
    assert redeem(mine, "SOLO10").status_code == 200
    recorded = pay(owner, reader)
    period = recorded.json()["membership"]["periods"][0]
    assert (period["discount_percent"], period["discount_kind"], period["coupon_code"]) == (None, None, None)
    assert standing(mine)["coupons"] == [{"code": "SOLO10", "percent": 10}], "the owner did not use it"
    trail = one(clean, "SELECT detail FROM auth.audit_events WHERE action = 'membership.payment_recorded'")["detail"]
    assert "discount" not in trail


def test_a_coupon_that_is_not_valid_says_so_and_nobody_learns_which_codes_exist(clean: str) -> None:
    account(f"reader@{DOMAIN}")
    owner, mine = signed_in(OWNER), signed_in(f"reader@{DOMAIN}")
    live, off = coupon(owner, "VIVO", 10), coupon(owner, "APAGADO", 10)
    assert owner.post(f"{COUPONS}/{off['id']}/disable").status_code == 200
    unknown, disabled = redeem(mine, "NOEXISTE"), redeem(mine, "APAGADO")
    assert (unknown.status_code, error(unknown)) == (404, "coupon_invalid")
    assert (disabled.status_code, disabled.json()["error"]) == (unknown.status_code, unknown.json()["error"]), \
        "the same answer"
    assert redeem(mine, "x").status_code == 422 and redeem(mine, "con espacio").status_code == 422
    maintenance(clean, "UPDATE customer.coupons SET valid_until = now() - interval '1 day' WHERE id = %s", (live["id"],))
    expired = redeem(mine, "VIVO")
    assert (expired.status_code, error(expired)) == (410, "coupon_expired")
    assert standing(mine)["coupons"] == []


def test_a_coupon_has_room_for_as_many_readers_as_its_ceiling_says(clean: str) -> None:
    first, second = account(f"first@{DOMAIN}"), account(f"second@{DOMAIN}")
    owner = signed_in(OWNER)
    made = coupon(owner, "DOSLUGARES", 25, max_redemptions=1)
    assert redeem(signed_in(f"first@{DOMAIN}"), "DOSLUGARES").status_code == 200
    late = redeem(signed_in(f"second@{DOMAIN}"), "DOSLUGARES")
    assert (late.status_code, error(late)) == (410, "coupon_exhausted")
    listed = owner.get(COUPONS).json()["coupons"][0]
    assert (listed["id"], listed["redemptions"], listed["active"]) == (made["id"], 1, False)
    assert {first, second} and one(clean, "SELECT count(*) AS n FROM customer.coupon_redemptions")["n"] == 1


def test_disabling_stops_the_coupon_for_those_who_hold_it_too(clean: str) -> None:
    reader = account(f"revoked@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"revoked@{DOMAIN}")
    made = coupon(owner, "REVOCADO", 40)
    assert redeem(mine, "REVOCADO").status_code == 200
    off = owner.post(f"{COUPONS}/{made['id']}/disable")
    assert off.status_code == 200 and off.json()["active"] is False and off.json()["disabled_at"] is not None
    assert standing(mine)["offer"] is None and standing(mine)["coupons"] == []
    assert pay(owner, reader, apply_discount=True).status_code == 409
    twice = owner.post(f"{COUPONS}/{made['id']}/disable")
    assert (twice.status_code, error(twice)) == (409, "coupon_disabled")
    assert owner.post(f"{COUPONS}/99999/disable").status_code == 404
    assert [c["code"] for c in owner.get(COUPONS).json()["coupons"]] == ["REVOCADO"], "it stays in the list"


def test_only_the_owner_makes_coupons_and_a_code_is_made_once(clean: str) -> None:
    account(f"reader@{DOMAIN}")
    owner, mine = signed_in(OWNER), signed_in(f"reader@{DOMAIN}")
    body = {"code": "UNICO", "percent": 10}
    assert mine.post(COUPONS, json=body).status_code == 403
    assert mine.get(COUPONS).status_code == 403
    made = owner.post(COUPONS, json=body)
    assert made.status_code == 201
    assert mine.post(f"{COUPONS}/{made.json()['id']}/disable").status_code == 403
    twice = owner.post(COUPONS, json={**body, "code": "unico"})
    assert (twice.status_code, error(twice)) == (409, "coupon_exists")
    for bad in ({"code": "ab", "percent": 10}, {"code": "BUENO", "percent": 0}, {"code": "BUENO", "percent": 101},
                {"code": "BUENO", "percent": 10, "note": "x"},
                {"code": "BUENO", "percent": 10, "valid_until": "2020-01-01T00:00:00Z"},
                {"code": "BUENO", "percent": 10, "max_redemptions": 0}):
        assert owner.post(COUPONS, json=bad).status_code == 422, bad
    trail = [r["action"] for r in rows(clean, "SELECT action FROM auth.audit_events WHERE action LIKE %s ORDER BY id",
                                       ("membership.coupon%",))]
    assert trail == ["membership.coupon_created"]


def test_the_owners_own_accounts_hold_no_coupon(clean: str) -> None:
    owner = signed_in(OWNER)
    coupon(owner, "PARAELDUENO", 10)
    held = redeem(owner, "PARAELDUENO")
    assert (held.status_code, error(held)) == (409, "membership_exempt")
    assert owner.get(ME).json()["discounts"] == {"offer": None, "coupons": [], "loyalty": None}


def test_ten_codes_that_are_not_valid_make_the_account_wait(clean: str) -> None:
    account(f"guesser@{DOMAIN}")
    owner, mine = signed_in(OWNER), signed_in(f"guesser@{DOMAIN}")
    coupon(owner, "REAL", 10)
    for n in range(10):
        assert redeem(mine, f"NOPE{n}").status_code == 404
    blocked = redeem(mine, "REAL")
    assert (blocked.status_code, error(blocked)) == (429, "rate_limited") and "retry-after" in blocked.headers


# ── loyalty ─────────────────────────────────────────────────────────────────────────────

def test_after_two_months_paid_the_reader_gets_twenty_percent_and_a_trial_is_not_a_month(clean: str) -> None:
    reader = account(f"loyal@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"loyal@{DOMAIN}")
    assert owner.post(f"/api/v1/admin/users/{reader}/membership/courtesy",
                      json={"days": 60, "reason": "regalo del dueño"}).status_code == 200
    assert standing(mine)["offer"] is None and standing(mine)["loyalty"]["paid_months"] == 0, "trial and courtesy"
    paid_for(owner, reader, 1)
    assert standing(mine)["offer"] is None, "one month paid is not past the two"
    assert standing(mine)["loyalty"] == {"percent": 20, "after_months": 2, "paid_months": 1, "active": False}
    paid_for(owner, reader, 1)
    now = standing(mine)
    assert now["loyalty"]["active"] is True and now["loyalty"]["paid_months"] == 2
    assert now["offer"] == {"kind": "loyalty", "percent": 20, "code": None,
                            "prices": [{"currency": "COP", "amount": "120000"}, {"currency": "USD", "amount": "40"}]}
    third = pay(owner, reader, amount="120000", apply_discount=True)
    assert third.status_code == 200, third.text
    period = third.json()["membership"]["periods"][0]
    assert (period["discount_percent"], period["discount_kind"], period["coupon_code"]) == (20, "loyalty", None)
    assert standing(mine)["offer"]["percent"] == 20, "loyalty stays for every payment from then on"
    assert third.json()["membership"]["discount"]["percent"] == 20


def test_the_larger_of_loyalty_and_a_coupon_applies_and_the_smaller_stays(clean: str) -> None:
    reader = account(f"both@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"both@{DOMAIN}")
    paid_for(owner, reader, 2)
    coupon(owner, "CHICO", 10), coupon(owner, "IGUAL", 20), coupon(owner, "GRANDE", 50)
    assert redeem(mine, "CHICO").status_code == 200 and redeem(mine, "IGUAL").status_code == 200
    assert standing(mine)["offer"]["kind"] == "loyalty", "10 and 20 never beat 20, and never add up to 30"
    assert redeem(mine, "GRANDE").status_code == 200
    best = standing(mine)["offer"]
    assert (best["kind"], best["percent"], best["code"]) == ("coupon", 50, "GRANDE")
    assert [c["code"] for c in standing(mine)["coupons"]] == ["GRANDE", "IGUAL", "CHICO"]
    used = pay(owner, reader, amount="75000", apply_discount=True)
    assert used.json()["membership"]["periods"][0]["coupon_code"] == "GRANDE"
    after = standing(mine)
    assert after["offer"]["kind"] == "loyalty", "with the big coupon used, loyalty is the best again"
    assert [c["code"] for c in after["coupons"]] == ["IGUAL", "CHICO"], "the others stay with the reader"


def test_the_owner_can_turn_loyalty_off_or_change_it(clean: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = account(f"switch@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"switch@{DOMAIN}")
    paid_for(owner, reader, 3)
    monkeypatch.setenv("FBI_LOYALTY_PERCENT", "0")
    assert standing(mine) == {"offer": None, "coupons": [], "loyalty": None}
    assert pay(owner, reader, apply_discount=True).status_code == 409
    monkeypatch.setenv("FBI_LOYALTY_PERCENT", "10")
    monkeypatch.setenv("FBI_LOYALTY_AFTER_MONTHS", "4")
    assert standing(mine)["offer"] is None and standing(mine)["loyalty"]["after_months"] == 4
    monkeypatch.setenv("FBI_LOYALTY_AFTER_MONTHS", "3")
    assert standing(mine)["offer"]["percent"] == 10


# ── what the tables allow ───────────────────────────────────────────────────────────────

def test_the_tables_refuse_what_is_not_creating_or_disabling_a_coupon(clean: str) -> None:
    reader = account(f"guard@{DOMAIN}")
    owner = signed_in(OWNER)
    made = coupon(owner, "GUARDADO", 15)
    assert redeem(signed_in(f"guard@{DOMAIN}"), "GUARDADO").status_code == 200
    with psycopg.connect(clean) as conn:
        for sql in ("UPDATE customer.coupons SET percent = 99",
                    "UPDATE customer.coupons SET code = 'OTRO'",
                    "UPDATE customer.coupons SET valid_until = now() + interval '1 year'",
                    "UPDATE customer.coupons SET max_redemptions = 1000",
                    "DELETE FROM customer.coupons",
                    "UPDATE customer.coupon_redemptions SET user_id = user_id",
                    "DELETE FROM customer.coupon_redemptions"):
            with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                conn.execute(sql)
        conn.execute("UPDATE customer.coupons SET disabled_at = now(), disabled_by = %s WHERE id = %s",
                     (uid_of(OWNER, clean), made["id"]))
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute("UPDATE customer.coupons SET disabled_at = NULL, disabled_by = NULL")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO customer.coupons (code, percent) VALUES ('ab', 10)")
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO customer.coupons (code, percent) VALUES ('OKCODE', 0)")
        conn.rollback()
        # a payment says all of its discount or none, and a coupon only with a coupon's discount
        insert = ("INSERT INTO customer.payments (user_id, amount, currency, method, idempotency_key, {cols}) "
                  "VALUES (%s, 1, 'COP', 'cash', %s, {values})")
        coupon_id = "(SELECT id FROM customer.coupons LIMIT 1)"
        for cols, values in (("discount_percent", "10"), ("discount_kind", "'loyalty'"),
                             ("discount_percent, discount_kind", "10, 'coupon'"),
                             ("discount_percent, discount_kind, coupon_id", f"10, 'loyalty', {coupon_id}"),
                             ("discount_percent, discount_kind", "0, 'loyalty'"),
                             ("discount_percent, discount_kind", "101, 'loyalty'"),
                             ("discount_percent, discount_kind", "10, 'gift'")):
            with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                conn.execute(insert.format(cols=cols, values=values), (reader, uuid.uuid4().hex))
        for cols, values in (("discount_percent, discount_kind", "10, 'loyalty'"),
                             ("discount_percent, discount_kind, coupon_id", f"10, 'coupon', {coupon_id}")):
            with pytest.raises(RollbackError), conn.transaction():  # well formed, the same statement is accepted
                conn.execute(insert.format(cols=cols, values=values), (reader, uuid.uuid4().hex))
                raise RollbackError


def test_the_export_holds_the_coupons_a_reader_redeemed_and_the_discount_a_payment_carried(clean: str) -> None:
    reader = account(f"export@{DOMAIN}")
    backdated(clean, reader, "trial", ended_days_ago=-5)
    owner, mine = signed_in(OWNER), signed_in(f"export@{DOMAIN}")
    coupon(owner, "EXPORTADO", 25, note="una nota solo para el dueño")
    assert redeem(mine, "EXPORTADO").status_code == 200
    pay(owner, reader, apply_discount=True)
    with psycopg.connect(clean) as conn:
        document = privacy.export(conn, reader)
    assert [(c["code"], c["percent"]) for c in document["coupon_redemptions"]] == [("EXPORTADO", 25)]
    assert (document["payments"][0]["discount_percent"], document["payments"][0]["coupon_code"]) == (25, "EXPORTADO")
    assert "nota" not in str(document["coupon_redemptions"]), "the owner's note stays with the owner"


def test_the_price_a_reader_sees_follows_the_owners_settings(clean: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = account(f"price@{DOMAIN}")
    owner, mine = signed_in(OWNER), signed_in(f"price@{DOMAIN}")
    coupon(owner, "MITAD", 50)
    assert redeem(mine, "MITAD").status_code == 200
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_USD", "0")
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_COP", "99900")
    assert standing(mine)["offer"]["prices"] == [{"currency": "COP", "amount": "49950"}]
    assert membership.prices() == [{"currency": "COP", "amount": "99900"}] and reader
    assert discounts.discounted("99900", 50) == "49950"
    assert datetime.now(UTC) - timedelta(seconds=1) < datetime.now(UTC)

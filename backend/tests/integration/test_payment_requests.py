"""The manual payment request «ya pagué» against PostgreSQL and the API (UX-090): closed until the owner's details, the
price and the final terms are in place; one open notice per reader; the owner's approval makes the payment and the period
in one step, once; a refusal tells the reader; an approval that was a mistake is annulled without deleting anything; a
reference is never kept whole. The state is computed from dates, so what each step does to access is read from the
membership itself."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.customer import legal, membership, payment_requests
from tests.integration import test_membership as membership_tests
from tests.integration.test_membership import (
    OWNER,
    account,
    client,
    error,
    one,
    rows,
    signed_in,
    uid_of,
)

database = membership_tests.database  # the module's fixtures, shared with the membership's tests
fresh = membership_tests.fresh

EMAIL = "lector@a8.test"
URL = "/api/v1/me/payment-request"
ADMIN = "/api/v1/admin/payment-requests"


@pytest.fixture()
def opened(fresh: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Every lock open: the owner's details, a price and terms that are no longer a draft."""
    monkeypatch.setenv("FBI_PAYMENT_HOLDER", "Titular de Prueba")
    monkeypatch.setenv("FBI_PAYMENT_BREB_KEY", "@predigol-prueba")
    monkeypatch.setenv("FBI_MEMBERSHIP_PRICE_COP", "150000")
    monkeypatch.setenv(membership.SWITCH, "1")
    real = legal.current

    def final(document: str) -> Any:
        return replace(real(document), draft=False)  # type: ignore[arg-type]

    monkeypatch.setattr(legal, "current", final)
    yield fresh


def body(**extra: Any) -> dict[str, Any]:
    terms = legal.load("terms", "es")
    today = datetime.now(payment_requests.BOGOTA).date()
    return {"amount": "150000", "paid_on": today.isoformat(), "method": "nequi", "reference": "M1234567",
            "payer_name": "Ana Pérez", "note": None, "accept_terms": True, "terms_version": terms.version, **extra}


def reader() -> tuple[Any, int]:
    uid = account(EMAIL)
    return signed_in(EMAIL), uid


def test_nothing_opens_until_the_owner_has_published_his_details(fresh: str) -> None:
    c, _ = reader()
    view = c.get(URL).json()
    assert view["available"] is False and view["pay"] is None, "no data of payment is shown before it is real"
    assert set(view["locks"]) >= {"payment_not_configured", "terms_draft"}
    r = c.post(URL, json=body())
    assert r.status_code == 409 and error(r) in ("payment_not_configured", "price_not_set", "terms_draft")
    assert rows(fresh, "SELECT id FROM customer.payment_requests") == []


def test_a_reader_without_access_sends_a_notice_and_waits(opened: str) -> None:
    c, uid = reader()
    assert c.get("/api/v1/me/membership").json()["membership"]["limited"] is True
    view = c.get(URL).json()
    assert view["available"] is True and view["pay"] == {"holder": "Titular de Prueba",
                                                           "breb_key": "@predigol-prueba", "has_qr": False}
    assert view["price"]["expected"] == "150000"
    r = c.post(URL, json=body())
    assert r.status_code == 201, r.text
    sent = r.json()
    assert sent["status"] == "submitted" and sent["reference_last4"] == "4567"
    assert "M1234567" not in r.text, "the reference is never given back whole"
    stored = one(opened, "SELECT reference_last4, reference_hmac, terms_version, terms_sha256 "
                         "FROM customer.payment_requests")
    assert len(stored["reference_hmac"]) == 64 and stored["terms_sha256"] == legal.load("terms", "es").sha256
    assert c.get(URL).json()["open"]["id"] == sent["id"], "«pago en verificación»: the open notice"
    kinds = [e["kind"] for e in rows(opened, "SELECT kind FROM customer.membership_events WHERE user_id = %s", (uid,))]
    assert kinds == ["payment_requested"]
    mail = rows(opened, "SELECT template, params FROM customer.messages_outbox WHERE user_id = %s", (uid,))
    assert [m["template"] for m in mail] == ["payment_request_received"], "the acknowledgement, at once"
    assert "150000" not in str(mail) and "M1234567" not in str(mail)
    assert one(opened, "SELECT count(*) AS n FROM audit.notifications WHERE kind = 'payment_request_new'")["n"] == 1
    again = c.post(URL, json=body(reference="OTRA1234"))
    assert again.status_code == 409 and error(again) == "request_open"
    # still without access: sending a notice grants nothing
    assert c.get("/api/v1/me/membership").json()["membership"]["limited"] is True


def test_the_notice_is_checked_before_it_is_kept(opened: str) -> None:
    c, _ = reader()
    today = datetime.now(payment_requests.BOGOTA).date()
    bad = {
        "future": body(paid_on=(today + timedelta(days=1)).isoformat()),
        "old": body(paid_on=(today - timedelta(days=45)).isoformat()),
        "card": body(reference="4111 1111 1111 1111"),
        "no_terms": body(accept_terms=False),
        "zero": body(amount="0"),
        "text": body(amount="mucho"),
    }
    for name, payload in bad.items():
        r = c.post(URL, json=payload)
        assert r.status_code in (409, 422), (name, r.text)
    stale = c.post(URL, json=body(terms_version="2020-01-01"))
    assert stale.status_code == 409 and error(stale) == "terms_changed"
    assert rows(opened, "SELECT id FROM customer.payment_requests") == []


def test_cancelling_frees_the_reader_to_send_another(opened: str) -> None:
    c, uid = reader()
    first = c.post(URL, json=body()).json()
    r = c.post(f"{URL}/{first['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert c.post(f"{URL}/{first['id']}/cancel").json()["status"] == "cancelled", "cancelling twice answers the same"
    second = c.post(URL, json=body(reference="N7654321"))
    assert second.status_code == 201
    kinds = [e["kind"] for e in rows(opened, "SELECT kind FROM customer.membership_events WHERE user_id = %s "
                                             "ORDER BY id", (uid,))]
    assert kinds == ["payment_requested", "payment_request_cancelled", "payment_requested"]
    other = signed_in(OWNER)
    assert c.post(f"{URL}/999999/cancel").status_code == 404
    del other


def test_a_notice_of_another_reader_cannot_be_cancelled(opened: str) -> None:
    mine, _ = reader()
    sent = mine.post(URL, json=body()).json()
    account("otro@a8.test")
    theirs = signed_in("otro@a8.test")
    assert theirs.post(f"{URL}/{sent['id']}/cancel").status_code == 404
    assert one(opened, "SELECT status FROM customer.payment_requests")["status"] == "submitted"


def test_only_the_owner_reaches_the_queue(opened: str) -> None:
    c, _ = reader()
    sent = c.post(URL, json=body()).json()
    assert c.get(ADMIN).status_code == 403
    assert c.post(f"{ADMIN}/{sent['id']}/approve", json={}).status_code == 403
    owner = signed_in(OWNER)
    queue = owner.get(ADMIN).json()
    assert queue["waiting"] == 1 and queue["requests"][0]["email"] == EMAIL
    assert queue["requests"][0]["amount_matches"] is True and queue["requests"][0]["overdue"] is False


def test_the_approval_makes_the_payment_and_the_period_once(opened: str) -> None:
    c, uid = reader()
    sent = c.post(URL, json=body()).json()
    owner = signed_in(OWNER)
    r = owner.post(f"{ADMIN}/{sent['id']}/approve", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    mine = c.get("/api/v1/me/membership").json()
    assert mine["membership"]["state"] in ("active", "renewed") and mine["membership"]["limited"] is False
    pays = rows(opened, "SELECT amount, currency, method, reference, idempotency_key FROM customer.payments")
    assert len(pays) == 1 and str(pays[0]["amount"]) == "150000.00" and pays[0]["method"] == "nequi"
    assert "M1234567" not in pays[0]["reference"], "the reference never reaches the payment"
    assert len(rows(opened, "SELECT id FROM customer.membership_periods WHERE user_id = %s", (uid,))) == 1
    second = owner.post(f"{ADMIN}/{sent['id']}/approve", json={})
    assert second.status_code == 409 and error(second) == "request_decided", "two clicks decide once"
    assert len(rows(opened, "SELECT id FROM customer.payments")) == 1
    kinds = {e["kind"] for e in rows(opened, "SELECT kind FROM customer.membership_events WHERE user_id = %s", (uid,))}
    assert {"payment_requested", "payment_request_approved", "payment_recorded"} <= kinds
    trail = rows(opened, "SELECT action FROM auth.audit_events WHERE action LIKE 'membership.payment%%'")
    assert {t["action"] for t in trail} >= {"membership.payment_requested", "membership.payment_request_approved"}
    sent_mail = [m["template"] for m in rows(opened, "SELECT template FROM customer.messages_outbox WHERE user_id = %s",
                                             (uid,))]
    assert sorted(sent_mail) == ["payment_recorded", "payment_request_received"]
    assert c.get(URL).json()["open"] is None


def test_a_payment_already_approved_cannot_be_approved_again_with_the_same_reference(opened: str) -> None:
    c, _ = reader()
    first = c.post(URL, json=body()).json()
    owner = signed_in(OWNER)
    assert owner.post(f"{ADMIN}/{first['id']}/approve", json={}).status_code == 200
    again = c.post(URL, json=body())
    assert again.status_code == 409 and error(again) == "reference_used"
    other = c.post(URL, json=body(reference="DISTINTA99"))
    assert other.status_code == 201


def test_the_owner_may_receive_another_amount_and_more_months(opened: str) -> None:
    c, _ = reader()
    sent = c.post(URL, json=body(amount="300000")).json()
    owner = signed_in(OWNER)
    queue = owner.get(ADMIN).json()["requests"][0]
    assert queue["amount_matches"] is False, "the console warns when the amount is not the price"
    r = owner.post(f"{ADMIN}/{sent['id']}/approve", json={"received_amount": "300000", "months": 2})
    assert r.status_code == 200
    period = one(opened, "SELECT starts_at, ends_at FROM customer.membership_periods")
    assert (period["ends_at"] - period["starts_at"]).days in range(59, 63)


def test_a_refusal_has_its_code_its_note_and_tells_the_reader(opened: str) -> None:
    c, uid = reader()
    sent = c.post(URL, json=body()).json()
    owner = signed_in(OWNER)
    assert owner.post(f"{ADMIN}/{sent['id']}/reject", json={"code": "not_received", "note": "x"}).status_code == 422
    r = owner.post(f"{ADMIN}/{sent['id']}/reject", json={"code": "not_received", "note": "no aparece en Nequi"})
    assert r.status_code == 200 and r.json()["decision_code"] == "not_received"
    assert rows(opened, "SELECT id FROM customer.payments") == []
    assert c.get("/api/v1/me/membership").json()["membership"]["limited"] is True
    mail = rows(opened, "SELECT template, params FROM customer.messages_outbox WHERE user_id = %s ORDER BY id", (uid,))
    assert [m["template"] for m in mail][-1] == "payment_request_rejected"
    assert mail[-1]["params"] == {"reason": "not_received"}, "a code, never the owner's note"
    decided = owner.post(f"{ADMIN}/{sent['id']}/reject", json={"code": "other", "note": "otra vez"})
    assert decided.status_code == 409 and error(decided) == "request_decided"
    assert c.post(f"{URL}/{sent['id']}/cancel").status_code == 409, "a decided notice cannot be cancelled"
    assert c.post(URL, json=body(reference="CORREGIDA1")).status_code == 201, "and the reader may try again"


def test_an_approval_that_was_a_mistake_is_annulled_and_nothing_is_deleted(opened: str) -> None:
    c, uid = reader()
    sent = c.post(URL, json=body()).json()
    owner = signed_in(OWNER)
    assert owner.post(f"{ADMIN}/{sent['id']}/annul", json={"reason": "no era el pago"}).status_code == 409
    assert owner.post(f"{ADMIN}/{sent['id']}/approve", json={}).status_code == 200
    assert c.get("/api/v1/me/membership").json()["membership"]["limited"] is False
    r = owner.post(f"{ADMIN}/{sent['id']}/annul", json={"reason": "el dinero nunca llegó"})
    assert r.status_code == 200 and r.json()["annulled"] is True
    mine = c.get("/api/v1/me/membership").json()
    assert mine["membership"]["limited"] is True and mine["periods"] == [], "the annulled period no longer counts"
    assert len(rows(opened, "SELECT id FROM customer.payments")) == 1
    assert len(rows(opened, "SELECT id FROM customer.membership_periods")) == 1, "nothing is deleted"
    again = owner.post(f"{ADMIN}/{sent['id']}/annul", json={"reason": "otra vez"})
    assert again.status_code == 409 and error(again) == "already_annulled"
    history = owner.get(f"/api/v1/admin/users/{uid}/membership").json()
    assert history["periods"][0]["annulled"] is True and history["membership"]["limited"] is True
    assert "period_annulled" in [e["kind"] for e in history["events"]]
    # and the reader may ask again, paying from now
    assert c.post(URL, json=body(reference="NUEVA12345")).status_code == 201


def test_a_suspended_reader_cannot_send_a_notice(opened: str) -> None:
    c, uid = reader()
    owner = signed_in(OWNER)
    assert owner.post(f"/api/v1/admin/users/{uid}/membership/suspend", json={"reason": "revisión"}).status_code == 200
    r = c.post(URL, json=body())
    assert r.status_code == 409 and error(r) == "membership_suspended"


def test_the_owners_qr_is_served_only_while_open_and_never_cached(opened: str, tmp_path: Any,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = reader()
    assert c.get(f"{URL}/qr").status_code == 404
    png = tmp_path / "nequi.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setenv("FBI_PAYMENT_QR_FILE", str(png))
    assert c.get(URL).json()["pay"]["has_qr"] is True
    r = c.get(f"{URL}/qr")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    monkeypatch.setenv("FBI_PAYMENT_QR_FILE", str(tmp_path / "missing.png"))
    assert c.get(f"{URL}/qr").status_code == 404
    anonymous = client()
    assert anonymous.get(f"{URL}/qr").status_code in (401, 403)


def test_the_queue_flags_a_reference_seen_before_and_an_overdue_notice(opened: str) -> None:
    c, uid = reader()
    sent = c.post(URL, json=body()).json()
    owner = signed_in(OWNER)
    far = datetime.now(UTC) + timedelta(days=5)
    from fbi.customer.db import write_connection

    with write_connection() as conn:
        late = payment_requests.queue(conn, at=far)["requests"][0]
    assert late["overdue"] is True and late["id"] == sent["id"]
    account("segundo@a8.test")
    other = signed_in("segundo@a8.test")
    assert other.post(URL, json=body()).status_code == 201
    flagged = next(q for q in owner.get(ADMIN).json()["requests"] if q["email"] == "segundo@a8.test")
    assert flagged["same_reference"] == 1
    del uid


def test_the_reader_export_carries_the_notices_and_never_the_reference(opened: str) -> None:
    c, uid = reader()
    c.post(URL, json=body())
    from fbi.customer.db import write_connection

    with write_connection() as conn:
        exported = payment_requests.export_rows(conn, uid)
    assert exported[0]["reference_last4"] == "4567" and "reference_hmac" not in exported[0]
    assert uid_of(EMAIL, opened) == uid


def test_two_simultaneous_approvals_make_one_payment_and_one_period(opened: str) -> None:
    """Two owners' tabs (or a double click that outruns the screen) approve the same notice at once: the account is
    locked first, the first decides, the second is told it was decided, and money is recorded once."""
    import threading

    c, uid = reader()
    sent = c.post(URL, json=body()).json()
    actor = uid_of(OWNER, opened)
    outcomes: list[str] = []
    gate = threading.Barrier(2)

    def press() -> None:
        gate.wait()
        try:
            payment_requests.approve(actor, int(sent["id"]))
            outcomes.append("approved")
        except Exception as exc:  # the loser's refusal is a CustomerError with the 409 code
            outcomes.append(getattr(exc, "code", type(exc).__name__))

    threads = [threading.Thread(target=press) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["approved", "request_decided"], outcomes
    assert len(rows(opened, "SELECT id FROM customer.payments")) == 1
    assert len(rows(opened, "SELECT id FROM customer.membership_periods WHERE user_id = %s", (uid,))) == 1

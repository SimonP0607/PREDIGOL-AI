"""The manual payment request, «ya pagué» (plan del flujo de usuario, tramo 1; UX-090).

PrediGol has no payment gateway. A reader pays outside it - a Nequi QR or a Bre-B key the owner publishes - and tells us:
the amount, the day, the way and, if they want, the last digits of the reference. The owner looks at his own account and
approves or refuses. Only his approval creates the payment and the membership period.

* **Closed until it can work.** Requests are accepted only while the owner's payment details are set (the holder and the
  Bre-B key or the Nequi QR), a price in pesos is set, and the terms of purchase are no longer a draft (the reader
  accepts them on the request, with their version and sha256, and a draft is never accepted as final). ``locks()`` names
  what is missing, and the web shows no payment data and takes no request meanwhile.
* **One open request per reader** (the database's unique index) and a reference already approved cannot be used again.
  The reference is never kept whole: its last four characters and an HMAC (``crypto.payment_reference_mac``).
* **«Pago en verificación»** is not a membership state: it is an open request (``status = 'submitted'``) read beside the
  membership. The reader may cancel it while it is open; nothing else changes it but the owner.
* **The deadline** is one business day (Colombia): the first business day after the day of the request - the
  time within which the owner promises to check, never a time for the e-mail.
* **Decisions** (all in one transaction, with the account locked, so two clicks decide once): approve (the payment and
  its period - ``membership.record_payment_in`` - and the request closed), reject (a code and a note, the reader told),
  annul an approval that was a mistake (an event ``period_annulled``; the period and the payment stay, the period stops
  counting). Every step leaves an event of the membership, a line of the access trail and, when the reader must know it,
  an e-mail.

Nothing here reads or writes what PrediGol Intelligence computes, and nothing is charged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import structlog
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.auth import crypto
from fbi.customer import discounts, legal, membership
from fbi.customer.db import CustomerError, write_connection

log = structlog.get_logger(__name__)

BOGOTA = ZoneInfo("America/Bogota")
CURRENCY = "COP"
"""What Nequi and Bre-B move: pesos. The USD price stays for whatever the owner offers outside this flow."""
METHODS = ("nequi", "transfer", "other")
DECISION_CODES = ("amount_mismatch", "not_received", "duplicate", "unreadable", "other")
PAID_ON_WINDOW_DAYS = 30
DAILY_REQUESTS_MAX = 5
"""Requests one reader may open in 24 hours (cancelled ones count): a loop of send-and-cancel stops here."""
QR_MAX_BYTES = 2_000_000
QR_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{2,39}$")
NOTE_MAX = 300
NAME_MAX = 80
NEW_ACCOUNT_HOURS = 24
"""An account created less than this long before its notice is flagged in the owner's queue (a notice from a brand-new
account deserves a second look at his own bank)."""


# ── the owner's payment details ───────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PayInfo:
    holder: str
    breb_key: str | None
    qr_file: Path | None

    @property
    def has_qr(self) -> bool:
        return self.qr_file is not None


def _clean_line(raw: str, limit: int) -> str | None:
    text = " ".join(raw.split())
    return text if 1 <= len(text) <= limit and text.isprintable() else None


def info() -> PayInfo | None:
    """What the owner published to be paid: the holder's name (FBI_PAYMENT_HOLDER) and at least one of the Bre-B key
    (FBI_PAYMENT_BREB_KEY) or the Nequi QR (FBI_PAYMENT_QR_FILE, an image of at most 2 MB inside the API's container).
    None until he gives them: nothing is invented."""
    holder = _clean_line(os.environ.get("FBI_PAYMENT_HOLDER", ""), 80)
    key = _clean_line(os.environ.get("FBI_PAYMENT_BREB_KEY", ""), 60)
    qr: Path | None = None
    raw = os.environ.get("FBI_PAYMENT_QR_FILE", "").strip()
    if raw:
        path = Path(raw)
        try:
            if (path.suffix.lower() in QR_TYPES and path.is_file()
                    and 0 < path.stat().st_size <= QR_MAX_BYTES):
                qr = path
        except OSError:
            qr = None
    if holder is None or (key is None and qr is None):
        return None
    return PayInfo(holder, key, qr)


def qr_bytes() -> tuple[bytes, str] | None:
    found = info()
    if found is None or found.qr_file is None:
        return None
    try:
        return found.qr_file.read_bytes(), QR_TYPES[found.qr_file.suffix.lower()]
    except OSError:
        return None


def price() -> Decimal | None:
    """The monthly price in pesos (membership.prices(); none while the owner sets none)."""
    for p in membership.prices():
        if p["currency"] == CURRENCY:
            return Decimal(p["amount"])
    return None


def locks() -> list[str]:
    """What must be in place before a reader can send a request and does not (closed list; empty: it is open)."""
    missing: list[str] = []
    if info() is None:
        missing.append("payment_not_configured")
    if price() is None:
        missing.append("price_not_set")
    if legal.current("terms").draft:
        missing.append("terms_draft")
    if not crypto.key_available():
        missing.append("key_unavailable")
    return missing


# ── one business day ──────────────────────────────────────────────────────────────────

def _easter(year: int) -> date:
    """Western Easter (Meeus' algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = (h + el - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _next_monday(day: date) -> date:
    """The Monday on or after ``day`` (the Emiliani law moves a holiday there)."""
    return day + timedelta(days=(7 - day.weekday()) % 7)


def holidays(year: int) -> frozenset[date]:
    """Colombia's public holidays (Ley 51 de 1983, «Emiliani»): fixed days, days moved to the next Monday and the ones that
    follow Easter."""
    fixed = [date(year, 1, 1), date(year, 5, 1), date(year, 7, 20), date(year, 8, 7), date(year, 12, 8),
             date(year, 12, 25)]
    moved = [date(year, 1, 6), date(year, 3, 19), date(year, 6, 29), date(year, 8, 15), date(year, 10, 12),
             date(year, 11, 1), date(year, 11, 11)]
    easter = _easter(year)
    following = [easter - timedelta(days=3), easter - timedelta(days=2),  # Holy Thursday and Good Friday
                 _next_monday(easter + timedelta(days=39)),  # Ascension
                 _next_monday(easter + timedelta(days=60)),  # Corpus Christi
                 _next_monday(easter + timedelta(days=68))]  # Sacred Heart
    return frozenset([*fixed, *(_next_monday(d) for d in moved), *following])


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in holidays(day.year)


def due_on(created_at: datetime) -> date:
    """The day by whose end the owner verifies: the first business day after the day of the request (Bogotá)."""
    day = created_at.astimezone(BOGOTA).date() + timedelta(days=1)
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def due_at(created_at: datetime) -> datetime:
    """The end of that day, as a moment."""
    end = datetime.combine(due_on(created_at) + timedelta(days=1), datetime.min.time(), tzinfo=BOGOTA)
    return end.astimezone(UTC)


# ── what a reader types ───────────────────────────────────────────────────────────────

def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def clean_reference(raw: str | None) -> tuple[str, str] | None:
    """A reference as the reader typed it -> (its last four characters, its HMAC), or None when they typed none. The
    whole reference is never kept. A card number (13 to 19 digits that pass Luhn) is refused."""
    text = " ".join((raw or "").split())
    if not text:
        return None
    if not REFERENCE_RE.match(text):
        raise CustomerError(422, "invalid_reference", "a reference of 3 to 40 letters, digits, dots, dashes or spaces")
    digits = re.sub(r"[ .-]", "", text)
    if digits.isdigit() and 13 <= len(digits) <= 19 and _luhn_ok(digits):
        raise CustomerError(422, "reference_has_number", "that looks like a card number: type the payment's reference")
    normal = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    mac = crypto.payment_reference_mac(normal)
    if mac is None:
        raise CustomerError(503, "key_unavailable", "the reference cannot be kept safely right now")
    return normal[-4:], mac


def _optional_text(raw: str | None, limit: int, code: str) -> str | None:
    text = " ".join((raw or "").split())
    if not text:
        return None
    if len(text) > limit:
        raise CustomerError(422, code, f"at most {limit} characters")
    return text


def _decision_note(raw: str | None, *, required: bool) -> str | None:
    text = " ".join((raw or "").split())
    if not text:
        if required:
            raise CustomerError(422, "note_required", "say why, in a few words")
        return None
    if not 3 <= len(text) <= 200:
        raise CustomerError(422, "invalid_note", "a note of 3 to 200 characters")
    return text


# ── the reader's view ─────────────────────────────────────────────────────────────────

_COLUMNS = """r.id, r.user_id, r.status, r.expected_amount, r.currency, r.coupon_id, r.discount_percent,
              r.declared_amount, r.declared_paid_on, r.method, r.reference_last4, r.payer_name, r.note,
              r.terms_version, r.accepted_at, r.created_at, r.decided_at, r.decision_code, r.decision_note,
              r.payment_id"""


def _shape(row: dict[str, Any], *, annulled: bool = False) -> dict[str, Any]:
    out = dict(row)
    out["expected_amount"] = str(row["expected_amount"])
    out["declared_amount"] = str(row["declared_amount"])
    out["declared_paid_on"] = row["declared_paid_on"].isoformat()
    out["due_on"] = due_on(row["created_at"]).isoformat()
    out["due_at"] = due_at(row["created_at"])
    out["annulled"] = annulled
    return out


def _annulled_ids(conn: psycopg.Connection[Any], payment_ids: list[int]) -> set[int]:
    if not payment_ids:
        return set()
    rows = conn.execute("""
        SELECT p.payment_id FROM customer.membership_periods p
          JOIN customer.membership_events e ON e.period_id = p.id AND e.kind = 'period_annulled'
         WHERE p.payment_id = ANY(%s)
    """, (payment_ids,)).fetchall()
    return {int(r[0]) for r in rows}


def mine(conn: psycopg.Connection[Any], user_id: int, *, locale: legal.Locale = "es") -> dict[str, Any]:
    """The reader's side: whether a request can be sent, the owner's details (only when it can), the price they would
    pay with their discount, the terms they would accept, and their requests (the open one first, then the last ones)."""
    missing = locks()
    paying = info() if not missing else None
    amount = price()
    offer = discounts.offer(conn, user_id)
    expected = discounts.discounted(amount, offer.percent) if amount is not None and offer is not None else (
        format(amount.normalize(), "f") if amount is not None else None)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM customer.payment_requests r WHERE r.user_id = %s "
                    "ORDER BY r.created_at DESC, r.id DESC LIMIT 10", (user_id,))
        rows = cur.fetchall()
    annulled = _annulled_ids(conn, [int(r["payment_id"]) for r in rows if r["payment_id"] is not None])
    requests = [_shape(r, annulled=r["payment_id"] in annulled) for r in rows]
    terms = legal.load("terms", locale)
    return {
        "available": not missing,
        "locks": missing,
        "pay": ({"holder": paying.holder, "breb_key": paying.breb_key, "has_qr": paying.has_qr}
                if paying is not None else None),
        "price": ({"currency": CURRENCY, "amount": format(amount.normalize(), "f"), "expected": expected,
                   "discount_percent": offer.percent if offer else None} if amount is not None else None),
        "terms": {"version": terms.version, "sha256": terms.sha256, "draft": terms.draft},
        "whatsapp": membership.whatsapp(),
        "open": next((r for r in requests if r["status"] == "submitted"), None),
        "requests": requests,
    }


# ── events, trail, e-mail, owner's notice ─────────────────────────────────────────────

def _log(conn: psycopg.Connection[Any], kind: str, *, actor: int | None, user_id: int, request_id: int,
         detail: dict[str, Any], reason: str | None = None, period_id: int | None = None) -> None:
    membership._event(conn, user_id, kind, period_id=period_id, reason=reason,
                      detail={"request_id": request_id, **detail}, actor=actor)
    membership._audit(conn, kind, actor=actor, user_id=user_id, detail={"request_id": request_id, **detail})


def _tell(conn: psycopg.Connection[Any], user_id: int, template: str, key: str, params: dict[str, str]) -> None:
    from fbi.messaging import outbox  # the messaging package imports this module's neighbours

    outbox.enqueue(conn, user_id=user_id, template=template, params=params, dedup_key=key)


def _alert_owner(conn: psycopg.Connection[Any], request_id: int) -> None:
    from fbi.notify.service import WEB_BASE

    waiting = conn.execute("SELECT count(*) FROM customer.payment_requests WHERE status = 'submitted'").fetchone()
    count = int(waiting[0]) if waiting else 1
    body = (f"Hay {count} aviso{'s' if count != 1 else ''} de pago por verificar. Cada uno se revisa dentro de un día "
            f"hábil. Consola: {WEB_BASE}/admin/payments")
    conn.execute("""
        INSERT INTO audit.notifications (kind, dedup_key, title, body, payload)
        VALUES ('payment_request_new', %s, %s, %s, %s) ON CONFLICT (dedup_key) DO NOTHING
    """, (f"payment_request_new:{request_id}", "Nuevo aviso de pago por verificar", body,
          Json({"request_id": request_id, "waiting": count})))


# ── the reader sends and cancels ──────────────────────────────────────────────────────

def create(user_id: int, *, amount: str, paid_on: date, method: str, reference: str | None, payer_name: str | None,
           note: str | None, accept_terms: bool, terms_version: str, locale: legal.Locale = "es",
           at: datetime | None = None) -> dict[str, Any]:
    """«Ya pagué»: the reader's declaration and their acceptance of the terms of purchase, kept as they saw them."""
    moment = at or datetime.now(UTC)
    missing = locks()
    if missing:
        raise CustomerError(409, missing[0], "payments by request are not open yet")
    if method not in METHODS:
        raise CustomerError(422, "invalid_method", "nequi, transfer or other")
    if not accept_terms:
        raise CustomerError(422, "terms_not_accepted", "accept the terms of purchase to send the notice")
    declared = membership._amount(amount)
    today = moment.astimezone(BOGOTA).date()
    if paid_on > today:
        raise CustomerError(422, "invalid_paid_on", "the day of the payment cannot be in the future")
    if paid_on < today - timedelta(days=PAID_ON_WINDOW_DAYS):
        raise CustomerError(422, "invalid_paid_on", f"a payment made in the last {PAID_ON_WINDOW_DAYS} days")
    ref = clean_reference(reference)
    name = _optional_text(payer_name, NAME_MAX, "invalid_payer_name")
    comment = _optional_text(note, NOTE_MAX, "invalid_note")
    terms = legal.load("terms", locale)
    if terms_version != terms.version:
        raise CustomerError(409, "terms_changed", "the terms of purchase changed: read them again")
    list_price = price()
    assert list_price is not None
    with write_connection() as conn:
        membership._account(conn, user_id)  # also locks the account: two clicks create one
        state = membership._state_now(conn, user_id)
        if state.state == "suspended":
            raise CustomerError(409, "membership_suspended", "this account is suspended: write to support")
        recent = conn.execute("SELECT count(*) FROM customer.payment_requests WHERE user_id = %s AND created_at > %s",
                              (user_id, moment - timedelta(hours=24))).fetchone()
        if recent and int(recent[0]) >= DAILY_REQUESTS_MAX:
            raise CustomerError(429, "rate_limited", "too many notices today: write to support")
        if ref is not None:
            used = conn.execute("SELECT 1 FROM customer.payment_requests WHERE reference_hmac = %s "
                                "AND status = 'approved'", (ref[1],)).fetchone()
            if used:
                raise CustomerError(409, "reference_used", "that payment was already recorded")
        offer = discounts.offer(conn, user_id)
        expected = Decimal(discounts.discounted(list_price, offer.percent)) if offer else list_price
        coupon_id = offer.coupon_id if offer and offer.kind == "coupon" else None
        percent = offer.percent if coupon_id is not None and offer else None
        try:
            with conn.transaction():
                row = conn.execute("""
                    INSERT INTO customer.payment_requests
                        (user_id, expected_amount, currency, coupon_id, discount_percent, declared_amount,
                         declared_paid_on, method, reference_last4, reference_hmac, payer_name, note,
                         terms_version, terms_sha256, accepted_at, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """, (user_id, expected, CURRENCY, coupon_id, percent, declared, paid_on, method,
                      ref[0] if ref else None, ref[1] if ref else None, name, comment, terms.version, terms.sha256,
                      moment, moment)).fetchone()
        except pg_errors.UniqueViolation as exc:
            raise CustomerError(409, "request_open", "there is a notice waiting to be verified already") from exc
        assert row is not None
        request_id = int(row[0])
        due = due_on(moment)
        same_reference = 0
        if ref is not None:
            found = conn.execute("SELECT count(*) FROM customer.payment_requests WHERE reference_hmac = %s AND id <> %s",
                                 (ref[1], request_id)).fetchone()
            same_reference = int(found[0]) if found else 0
        _log(conn, "payment_requested", actor=None, user_id=user_id, request_id=request_id,
             detail={"expected": str(expected), "declared": str(declared), "method": method,
                     "due_on": due.isoformat(), "terms_version": terms.version, "reference_seen": same_reference})
        _tell(conn, user_id, "payment_request_received", f"payment_request_received:{request_id}",
              {"due": due.isoformat()})
        _alert_owner(conn, request_id)
        result = _one(conn, request_id)
    membership.forget(user_id)
    log.info("payment_request.created", user_id=user_id, request_id=request_id, method=method)
    return result


def _one(conn: psycopg.Connection[Any], request_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM customer.payment_requests r WHERE r.id = %s", (request_id,))
        row = cur.fetchone()
    if row is None:
        raise CustomerError(404, "request_not_found", "no such notice")
    return _shape(row, annulled=row["payment_id"] in _annulled_ids(
        conn, [int(row["payment_id"])] if row["payment_id"] is not None else []))


def cancel(user_id: int, request_id: int, *, at: datetime | None = None) -> dict[str, Any]:
    """The reader withdraws a notice nobody has decided yet. Cancelling it again answers the same; a decided one cannot."""
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        membership._account(conn, user_id)
        row = conn.execute("SELECT status FROM customer.payment_requests WHERE id = %s AND user_id = %s FOR UPDATE",
                           (request_id, user_id)).fetchone()
        if row is None:
            raise CustomerError(404, "request_not_found", "no such notice")
        if row[0] == "cancelled":
            return _one(conn, request_id)
        if row[0] != "submitted":
            raise CustomerError(409, "request_decided", "this notice was decided already")
        conn.execute("UPDATE customer.payment_requests SET status = 'cancelled', decided_at = %s WHERE id = %s",
                     (moment, request_id))
        _log(conn, "payment_request_cancelled", actor=None, user_id=user_id, request_id=request_id, detail={})
        result = _one(conn, request_id)
    membership.forget(user_id)
    return result


# ── the owner's queue and decisions ───────────────────────────────────────────────────

def queue(conn: psycopg.Connection[Any], *, status: str = "submitted", limit: int = 100,
          at: datetime | None = None) -> dict[str, Any]:
    """The requests for the console, oldest first when open (the one waiting longest first) and newest first otherwise,
    each with the account that sent it (its name, address and mobile), whether the amount matches, how many other
    requests carry the same reference, whether its deadline passed and what makes the owner look twice at the person
    (UX-098, the plan's «avisos» of the queue): notices of theirs refused before, an account made less than a day
    before the notice, and a mobile number that other accounts carry too."""
    moment = at or datetime.now(UTC)
    if status not in ("submitted", "all"):
        raise CustomerError(422, "invalid_status", "submitted or all")
    where = "WHERE r.status = 'submitted'" if status == "submitted" else ""
    order = "r.created_at, r.id" if status == "submitted" else "r.created_at DESC, r.id DESC"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"""
            SELECT {_COLUMNS}, u.email, u.display_name, u.first_name, u.last_name, u.phone_e164 AS phone,
                   (SELECT c.code FROM customer.coupons c WHERE c.id = r.coupon_id) AS coupon_code,
                   (SELECT count(*) FROM customer.payment_requests o
                     WHERE o.reference_hmac IS NOT NULL AND o.reference_hmac = r.reference_hmac AND o.id <> r.id)
                       AS same_reference,
                   (SELECT count(*) FROM customer.payment_requests o
                     WHERE o.user_id = r.user_id AND o.status = 'rejected' AND o.id < r.id) AS previous_rejections,
                   (r.created_at - u.created_at) < make_interval(hours => {NEW_ACCOUNT_HOURS}) AS new_account,
                   (SELECT count(*) FROM auth.users o
                     WHERE u.phone_e164 IS NOT NULL AND o.phone_e164 = u.phone_e164 AND o.id <> u.id
                       AND o.status <> 'deleted') AS phone_elsewhere
              FROM customer.payment_requests r JOIN auth.users u ON u.id = r.user_id
              {where} ORDER BY {order} LIMIT %s
        """, (max(1, min(limit, 200)),))
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM customer.payment_requests WHERE status = 'submitted'")
        waiting = cur.fetchone()
    annulled = _annulled_ids(conn, [int(r["payment_id"]) for r in rows if r["payment_id"] is not None])
    items: list[dict[str, Any]] = []
    for r in rows:
        extra = {k: r.pop(k) for k in ("email", "display_name", "first_name", "last_name", "phone", "coupon_code",
                                       "same_reference", "previous_rejections", "new_account", "phone_elsewhere")}
        item = _shape(r, annulled=r["payment_id"] in annulled)
        item.update(extra)
        item["amount_matches"] = Decimal(item["declared_amount"]) == Decimal(item["expected_amount"])
        item["overdue"] = item["status"] == "submitted" and moment > item["due_at"]
        items.append(item)
    return {"waiting": int(waiting["count"]) if waiting else 0, "requests": items}


def _locked(conn: psycopg.Connection[Any], request_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS}, r.reference_hmac FROM customer.payment_requests r WHERE r.id = %s FOR UPDATE",
                    (request_id,))
        row = cur.fetchone()
    if row is None:
        raise CustomerError(404, "request_not_found", "no such notice")
    return dict(row)


def approve(actor: int, request_id: int, *, received_amount: str | None = None, months: int = 1,
            at: datetime | None = None) -> dict[str, Any]:
    """The owner saw the money: the payment (what he received) and the period (from the end of the cover in force),
    and the request closed, in one transaction. The request is decided once; a second click answers 409."""
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        first = conn.execute("SELECT user_id FROM customer.payment_requests WHERE id = %s", (request_id,)).fetchone()
        if first is None:
            raise CustomerError(404, "request_not_found", "no such notice")
        user_id = int(first[0])
        membership._account(conn, user_id)  # the account first, as everywhere: the same order never deadlocks
        req = _locked(conn, request_id)
        if req["status"] != "submitted":
            raise CustomerError(409, "request_decided", "this notice was decided already")
        received = membership._amount(received_amount if received_amount else req["declared_amount"])
        if req["reference_hmac"]:
            used = conn.execute("SELECT 1 FROM customer.payment_requests WHERE reference_hmac = %s "
                                "AND status = 'approved' AND id <> %s", (req["reference_hmac"], request_id)).fetchone()
            if used:
                raise CustomerError(409, "reference_used", "that payment was approved on another notice")
        offer = discounts.offer(conn, user_id)
        carried = offer is not None and Decimal(discounts.discounted(price() or Decimal(0), offer.percent)) == Decimal(
            req["expected_amount"])
        reference = f"aviso {request_id}" + (f" ...{req['reference_last4']}" if req["reference_last4"] else "")
        recorded = membership.record_payment_in(
            conn, actor, user_id, amount=received, currency_code=req["currency"], method=req["method"],
            reference=reference, months=months, idempotency_key=f"payment-request-{request_id}",
            apply_discount=carried, at=moment)
        conn.execute("""
            UPDATE customer.payment_requests
               SET status = 'approved', decided_at = %s, decided_by = %s, payment_id = %s WHERE id = %s
        """, (moment, actor, recorded.payment_id, request_id))
        _log(conn, "payment_request_approved", actor=actor, user_id=user_id, request_id=request_id,
             detail={"payment_id": recorded.payment_id, "received": str(received), "months": months,
                     "matches_expected": received == Decimal(req["expected_amount"])}, period_id=recorded.period.id)
        result = _one(conn, request_id)
    membership.forget(user_id)
    log.info("payment_request.approved", request_id=request_id, user_id=user_id, months=months)
    return result


def reject(actor: int, request_id: int, *, code: str, note: str | None, at: datetime | None = None) -> dict[str, Any]:
    """The owner could not confirm the payment: a code, a note for the record, and the reader told the reason."""
    if code not in DECISION_CODES:
        raise CustomerError(422, "invalid_decision_code", "a reason of the list")
    text = _decision_note(note, required=True)
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        first = conn.execute("SELECT user_id FROM customer.payment_requests WHERE id = %s", (request_id,)).fetchone()
        if first is None:
            raise CustomerError(404, "request_not_found", "no such notice")
        user_id = int(first[0])
        membership._account(conn, user_id)
        req = _locked(conn, request_id)
        if req["status"] != "submitted":
            raise CustomerError(409, "request_decided", "this notice was decided already")
        conn.execute("""
            UPDATE customer.payment_requests
               SET status = 'rejected', decided_at = %s, decided_by = %s, decision_code = %s, decision_note = %s
             WHERE id = %s
        """, (moment, actor, code, text, request_id))
        _log(conn, "payment_request_rejected", actor=actor, user_id=user_id, request_id=request_id,
             detail={"code": code}, reason=text)
        _tell(conn, user_id, "payment_request_rejected", f"payment_request_rejected:{request_id}", {"reason": code})
        result = _one(conn, request_id)
    membership.forget(user_id)
    return result


def annul(actor: int, request_id: int, *, reason: str, at: datetime | None = None) -> dict[str, Any]:
    """An approval that was a mistake: the period stops counting (an event; the period and the payment stay) and the
    reader is told. Only an approved request can be annulled, and only once."""
    text = _decision_note(reason, required=True)
    assert text is not None
    with write_connection() as conn:
        first = conn.execute("SELECT user_id FROM customer.payment_requests WHERE id = %s", (request_id,)).fetchone()
        if first is None:
            raise CustomerError(404, "request_not_found", "no such notice")
        user_id = int(first[0])
        membership._account(conn, user_id)
        req = _locked(conn, request_id)
        if req["status"] != "approved":
            raise CustomerError(409, "request_not_approved", "only an approved notice can be annulled")
        period = conn.execute("SELECT id FROM customer.membership_periods WHERE payment_id = %s",
                              (req["payment_id"],)).fetchone()
        if period is None:
            raise CustomerError(409, "period_not_found", "the approval has no period")
        if conn.execute("SELECT 1 FROM customer.membership_events WHERE kind = 'period_annulled' AND period_id = %s",
                        (period[0],)).fetchone():
            raise CustomerError(409, "already_annulled", "this approval was annulled already")
        membership._event(conn, user_id, "period_annulled", period_id=int(period[0]), reason=text,
                          detail={"request_id": request_id, "payment_id": req["payment_id"]}, actor=actor)
        membership._audit(conn, "period_annulled", actor=actor, user_id=user_id,
                          detail={"request_id": request_id, "payment_id": req["payment_id"]})
        _tell(conn, user_id, "payment_request_annulled", f"payment_request_annulled:{request_id}", {})
        result = _one(conn, request_id)
    membership.forget(user_id)
    log.info("payment_request.annulled", request_id=request_id, user_id=user_id)
    return result


def export_rows(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    """The reader's own notices for their export (UX-098): all that they see of each - what they declared (the amount,
    the day, the way, the payer's name, their note, the last four of the reference), the discount and the terms they
    accepted, what the owner decided (the code and the note) and whether an approval was annulled later. Never the
    whole reference nor its HMAC, and never who in the console decided or the payment's own id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id, status, expected_amount, currency, discount_percent, declared_amount, declared_paid_on, method,
                   reference_last4, payer_name, note, terms_version, terms_sha256, accepted_at, created_at, decided_at,
                   decision_code, decision_note, payment_id
              FROM customer.payment_requests WHERE user_id = %s ORDER BY created_at DESC, id DESC
        """, (user_id,))
        found = cur.fetchall()
    annulled = _annulled_ids(conn, [int(r["payment_id"]) for r in found if r["payment_id"] is not None])
    out: list[dict[str, Any]] = []
    for r in found:
        row = {k: v for k, v in r.items() if k != "payment_id"}
        row["expected_amount"] = str(r["expected_amount"])
        row["declared_amount"] = str(r["declared_amount"])
        row["annulled"] = r["payment_id"] is not None and int(r["payment_id"]) in annulled
        out.append(row)
    return out

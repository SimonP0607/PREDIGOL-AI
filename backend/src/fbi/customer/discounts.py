"""Discounts of the membership (plan UX, UX-005): the owner's coupons and the loyalty discount.

Two owner decisions of 5-nov-2026 live here. First, the owner can create a coupon whenever he wants one, and a reader
can hold it by typing its code in the Membership section of their profile. Second, a reader who has paid for more than
two months gets 20% off from then on, for loyalty.

Nothing is charged by PrediGol - there is no payment gateway - so a discount is a number: the reader sees what their
next renewal costs, the owner's console proposes that amount when he records the payment, and the payment keeps what
was applied (``customer.payments.discount_*``). The rules, all of them in this file:

* A coupon takes a percentage (1 to 100) off ONE payment of the reader who holds it. It is redeemed once per reader, until
  its last day (if it has one) and while its ceiling of redemptions (if it has one) is not reached; it is used when a
  payment records it. Disabling a coupon stops it being redeemed and applied from then on; nothing else about it ever
  changes and it is never deleted.
* Loyalty takes ``FBI_LOYALTY_PERCENT`` (20; 0/off turns it off) off every payment once the reader has paid for
  ``FBI_LOYALTY_AFTER_MONTHS`` months (2 by default) - the months of the payments the owner recorded: a trial or a
  courtesy is not a month paid.
* They do not add up: the larger percentage applies, and when they are equal the loyalty one does, so the coupon stays
  with the reader for later.

Nothing here reads or writes what PrediGol Intelligence computes, and nothing here limits what a reader may open: a
discount is only a price.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

import psycopg
import structlog
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from fbi.customer.db import CustomerError, write_connection

log = structlog.get_logger(__name__)

Kind = Literal["coupon", "loyalty"]

LOYALTY_PERCENT_DEFAULT = 20
LOYALTY_AFTER_MONTHS_DEFAULT = 2
LOYALTY_AFTER_MONTHS_MAX = 24
CODE = re.compile(r"^[A-Z0-9_-]{3,32}$")
NOTE_MAX = 120
MAX_REDEMPTIONS_CEILING = 100_000
_OFF = ("0", "off", "false", "no")


# ── settings ──────────────────────────────────────────────────────────────────────────

def loyalty_percent() -> int:
    """FBI_LOYALTY_PERCENT: 20 without the line, 0 when it says 0/off (no loyalty discount), 1 to 100 otherwise; a
    value that is not a whole number of that range is ignored (the default stands)."""
    raw = os.environ.get("FBI_LOYALTY_PERCENT", "").strip().lower()
    if not raw:
        return LOYALTY_PERCENT_DEFAULT
    if raw in _OFF:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return LOYALTY_PERCENT_DEFAULT
    return value if 1 <= value <= 100 else LOYALTY_PERCENT_DEFAULT


def loyalty_after_months() -> int:
    """FBI_LOYALTY_AFTER_MONTHS: the months paid from which the loyalty discount applies, 2 by default (1 to 24)."""
    raw = os.environ.get("FBI_LOYALTY_AFTER_MONTHS", "").strip()
    try:
        value = int(raw) if raw else LOYALTY_AFTER_MONTHS_DEFAULT
    except ValueError:
        return LOYALTY_AFTER_MONTHS_DEFAULT
    return value if 1 <= value <= LOYALTY_AFTER_MONTHS_MAX else LOYALTY_AFTER_MONTHS_DEFAULT


# ── the arithmetic ────────────────────────────────────────────────────────────────────

def discounted(amount: str | Decimal, percent: int) -> str:
    """An amount with a percentage taken off, as a decimal string without trailing zeros: 150000 at 20 -> '120000',
    50 at 15 -> '42.5'. Rounded to the cent, half up."""
    value = (Decimal(str(amount)) * (100 - percent) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(value.normalize(), "f") if value != 0 else "0"


def clean_code(raw: str) -> str:
    """A coupon's code as it is kept: capitals, 3 to 32 letters, digits, - or _ (spaces at the ends are ignored)."""
    code = raw.strip().upper()
    if not CODE.match(code):
        raise CustomerError(422, "invalid_coupon_code", "a code of 3 to 32 letters, digits, - or _")
    return code


# ── what a reader is offered ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Offer:
    """The discount a reader's next payment gets: its kind, its percentage and, for a coupon, its code."""

    kind: Kind
    percent: int
    code: str | None = None
    coupon_id: int | None = None


def paid_months(conn: psycopg.Connection[Any], user_id: int) -> int:
    """The months the owner recorded payments for: a trial or a courtesy is not a month paid."""
    row = conn.execute(
        "SELECT coalesce(sum((detail->>'months')::int), 0) FROM customer.membership_events "
        "WHERE user_id = %s AND kind = 'payment_recorded' AND NOT EXISTS (SELECT 1 FROM customer.membership_events a WHERE a.kind = 'period_annulled' AND a.period_id = membership_events.period_id)", (user_id,)).fetchone()
    return int(row[0]) if row else 0


def held(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    """The coupons the reader holds and has not used, best first: id, code and percentage (the owner's note stays with
    the owner). A disabled coupon is not held any more."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT c.id, c.code, c.percent, r.redeemed_at
              FROM customer.coupon_redemptions r
              JOIN customer.coupons c ON c.id = r.coupon_id
             WHERE r.user_id = %s AND c.disabled_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM customer.payments p WHERE p.user_id = r.user_id AND p.coupon_id = c.id)
             ORDER BY c.percent DESC, r.redeemed_at, c.id
        """, (user_id,))
        return list(cur.fetchall())


def offer(conn: psycopg.Connection[Any], user_id: int) -> Offer | None:
    """The discount the reader's next payment gets, or None. The larger of loyalty and the best coupon held; equal,
    loyalty (the coupon stays for later)."""
    return _best(paid_months(conn, user_id), held(conn, user_id))


def _best(months: int, coupons: list[dict[str, Any]]) -> Offer | None:
    loyal = loyalty_percent()
    best: Offer | None = None
    if loyal and months >= loyalty_after_months():
        best = Offer("loyalty", loyal)
    if coupons and (best is None or coupons[0]["percent"] > best.percent):
        top = coupons[0]
        best = Offer("coupon", int(top["percent"]), str(top["code"]), int(top["id"]))
    return best


def standing(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    """What the reader's Membership section says about discounts: the offer in force (an ``Offer`` or None, for the
    caller to put prices on), the coupons held and the loyalty rule with where the reader stands in it (None while the
    owner has it off)."""
    months = paid_months(conn, user_id)
    coupons = held(conn, user_id)
    loyal = loyalty_percent()
    after = loyalty_after_months()
    return {
        "offer": _best(months, coupons),
        "coupons": [{"code": c["code"], "percent": int(c["percent"])} for c in coupons],
        "loyalty": None if not loyal else
        {"percent": loyal, "after_months": after, "paid_months": months, "active": months >= after},
    }


# ── what a reader does ────────────────────────────────────────────────────────────────

def redeem(user_id: int, raw_code: str, *, at: datetime | None = None) -> dict[str, Any]:
    """The reader holds a coupon by its code. Unknown and disabled codes answer the same (nobody learns which codes
    exist); an expired one, one at its ceiling and one the reader already redeemed say so. The coupon's row is locked
    while its redemptions are counted, so two readers never take the last place."""
    code = clean_code(raw_code)
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        _reader(conn, user_id)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, code, percent, valid_until, max_redemptions, disabled_at
                  FROM customer.coupons WHERE code = %s FOR UPDATE
            """, (code,))
            coupon = cur.fetchone()
        if coupon is None or coupon["disabled_at"] is not None:
            raise CustomerError(404, "coupon_invalid", "this code is not valid")
        if coupon["valid_until"] is not None and coupon["valid_until"] <= moment:
            raise CustomerError(410, "coupon_expired", "this code is no longer valid")
        if conn.execute("SELECT 1 FROM customer.coupon_redemptions WHERE coupon_id = %s AND user_id = %s",
                        (coupon["id"], user_id)).fetchone():
            raise CustomerError(409, "coupon_already_yours", "you already have this coupon")
        if coupon["max_redemptions"] is not None:
            row = conn.execute("SELECT count(*) FROM customer.coupon_redemptions WHERE coupon_id = %s",
                               (coupon["id"],)).fetchone()
            if row is not None and int(row[0]) >= int(coupon["max_redemptions"]):
                raise CustomerError(410, "coupon_exhausted", "this code has no places left")
        conn.execute("INSERT INTO customer.coupon_redemptions (coupon_id, user_id, redeemed_at) VALUES (%s, %s, %s)",
                     (coupon["id"], user_id, moment))
        _audit(conn, "coupon_redeemed", actor=user_id, user_id=user_id,
               detail={"coupon_id": int(coupon["id"]), "percent": int(coupon["percent"])})
    log.info("membership.coupon_redeemed", user_id=user_id, coupon_id=int(coupon["id"]))
    return {"code": str(coupon["code"]), "percent": int(coupon["percent"])}


def _reader(conn: psycopg.Connection[Any], user_id: int) -> None:
    """The account must be a reader's: the owner's accounts have no membership, a deleted one has nothing."""
    row = conn.execute("SELECT role, status FROM auth.users WHERE id = %s FOR SHARE", (user_id,)).fetchone()
    if row is None or row[1] == "deleted":
        raise CustomerError(404, "user_not_found", "no such account")
    if row[0] == "SUPER_ADMIN":
        raise CustomerError(409, "membership_exempt", "the owner's accounts have no membership")


def _audit(conn: psycopg.Connection[Any], action: str, *, actor: int | None, user_id: int | None,
           detail: dict[str, Any]) -> None:
    """``membership.*`` in the access trail the console shows (a coupon's id and percentage, never a person's data)."""
    from fbi.auth import store  # imported here: fbi.auth imports the membership at the activation

    store.record_event(conn, f"membership.{action}", actor_user_id=actor, target_user_id=user_id, detail=detail)


# ── what the owner does ───────────────────────────────────────────────────────────────

_COLUMNS = """c.id, c.code, c.percent, c.note, c.valid_until, c.max_redemptions, c.created_at, c.disabled_at,
              (SELECT count(*) FROM customer.coupon_redemptions r WHERE r.coupon_id = c.id) AS redemptions,
              (SELECT count(*) FROM customer.payments p WHERE p.coupon_id = c.id) AS used"""


def _shape(row: dict[str, Any], at: datetime) -> dict[str, Any]:
    """A coupon's row with its counts as numbers and whether a reader can still redeem it at ``at``."""
    redemptions = int(row["redemptions"])
    open_ = (row["disabled_at"] is None
             and (row["valid_until"] is None or row["valid_until"] > at)
             and (row["max_redemptions"] is None or redemptions < int(row["max_redemptions"])))
    return {**row, "redemptions": redemptions, "used": int(row["used"]), "active": open_}


def list_coupons(conn: psycopg.Connection[Any], *, at: datetime | None = None) -> list[dict[str, Any]]:
    """Every coupon, newest first, with how many readers hold it, how many payments used it and whether it can still be
    redeemed."""
    moment = at or datetime.now(UTC)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM customer.coupons c ORDER BY c.created_at DESC, c.id DESC LIMIT 500")
        return [_shape(r, moment) for r in cur.fetchall()]


def _coupon(conn: psycopg.Connection[Any], coupon_id: int, at: datetime) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM customer.coupons c WHERE c.id = %s", (coupon_id,))
        row = cur.fetchone()
    if row is None:
        raise CustomerError(404, "coupon_not_found", "no such coupon")
    return _shape(row, at)


def create_coupon(actor: int, *, code: str, percent: int, note: str | None = None,
                  valid_until: datetime | None = None, max_redemptions: int | None = None,
                  at: datetime | None = None) -> dict[str, Any]:
    """A coupon the owner creates: its code, the percentage, and optionally a note for himself, a last moment to redeem
    it and a ceiling of redemptions. The code is unique."""
    clean = clean_code(code)
    if not 1 <= percent <= 100:
        raise CustomerError(422, "invalid_percent", "a percentage from 1 to 100")
    text = " ".join((note or "").split()) or None
    if text is not None and not 3 <= len(text) <= NOTE_MAX:
        raise CustomerError(422, "invalid_note", f"a note of 3 to {NOTE_MAX} characters")
    moment = at or datetime.now(UTC)
    if valid_until is not None and valid_until <= moment:
        raise CustomerError(422, "invalid_valid_until", "a last day in the future")
    if max_redemptions is not None and not 1 <= max_redemptions <= MAX_REDEMPTIONS_CEILING:
        raise CustomerError(422, "invalid_max_redemptions", f"1 to {MAX_REDEMPTIONS_CEILING} redemptions")
    with write_connection() as conn:
        try:
            row = conn.execute("""
                INSERT INTO customer.coupons (code, percent, note, valid_until, max_redemptions, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (clean, percent, text, valid_until, max_redemptions, actor, moment)).fetchone()
        except pg_errors.UniqueViolation as exc:
            raise CustomerError(409, "coupon_exists", "there is a coupon with that code") from exc
        assert row is not None
        coupon_id = int(row[0])
        _audit(conn, "coupon_created", actor=actor, user_id=None, detail={"coupon_id": coupon_id, "percent": percent})
        created = _coupon(conn, coupon_id, moment)
    log.info("membership.coupon_created", coupon_id=coupon_id, percent=percent)
    return created


def disable_coupon(actor: int, coupon_id: int, *, at: datetime | None = None) -> dict[str, Any]:
    """Stops a coupon being redeemed or applied from now on. It stays in the list, with the redemptions and payments it
    had; there is no way back (create another)."""
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, disabled_at FROM customer.coupons WHERE id = %s FOR UPDATE", (coupon_id,))
            found = cur.fetchone()
        if found is None:
            raise CustomerError(404, "coupon_not_found", "no such coupon")
        if found["disabled_at"] is not None:
            raise CustomerError(409, "coupon_disabled", "this coupon is already disabled")
        conn.execute("UPDATE customer.coupons SET disabled_at = %s, disabled_by = %s WHERE id = %s",
                     (moment, actor, coupon_id))
        _audit(conn, "coupon_disabled", actor=actor, user_id=None, detail={"coupon_id": coupon_id})
        disabled = _coupon(conn, coupon_id, moment)
    log.info("membership.coupon_disabled", coupon_id=coupon_id)
    return disabled

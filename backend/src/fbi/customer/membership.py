"""Membership (plan UX, A8; section 22): one full plan, a trial of 20 days (the owner's decision of 5-nov-2026; it was 14), seven states computed from dates, the
notices around a period's end, and the owner's manual renewal - the reader pays outside PrediGol, the owner records it
here in under a minute, in rows a payment gateway (C4) could write later.

The state is never stored. It is computed, at a moment, from the account's periods (``customer.membership_periods``:
trial, paid, courtesy) and events (``customer.membership_events``: a suspension, «will not renew»):

    trial      a trial covers the account, more than 3 days left               full access
    active     a paid period or a courtesy covers it, more than 7 days left     full access
    expiring   7 days or less left (3 in a trial)                               full access, a quiet notice
    grace      the cover ended less than 3 days ago                             full access, a fixed notice
    expired    the grace ended                                                  limited
    renewed    a paid period that follows a paid one, recorded < 7 days ago     full access
    suspended  the owner suspended it, with a reason, until lifted              limited

Limited is: the profile, my picks and parlays to read, help, the legal texts, support and the export. The first payment
after the trial leads to ``active`` whenever it comes; ``renewed`` exists only when a paid period follows a paid one. A
new period starts at the end of the one in force, or now when that one has ended. Expiring never deletes anything.
Suspending is not disabling: a disabled account cannot sign in (a security measure that ends its sessions); a suspended
one signs in and reads what a limited account reads.

Two more states the reader never sees as a membership: ``none`` - no period at all: the account of a person who
registered on their own and has not been given access yet (UX-063), or one from before A8 the owner has not given a
period -, flagged in the console, limited like an ended one once the membership is enforced; and ``exempt`` - the owner
(SUPER_ADMIN) and the synthetic journey's account, never limited and never told. Registering gives no trial: a trial
is for an invitation, a courtesy or a coupon.

FBI_MEMBERSHIP_ENFORCE (born off): only when it is on does ``none``, ``expired`` or ``suspended`` limit anything; off,
every account has full access and the states are still shown as they are. Before turning it on, give every live
account its period: the console lists who has none. Nothing of PrediGol Intelligence is read or
written here: a membership decides what a reader may open, never what the system computes.
"""

from __future__ import annotations

import calendar
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.customer import consents, discounts, events
from fbi.customer.db import CustomerError, write_connection

log = structlog.get_logger(__name__)

State = Literal["trial", "active", "expiring", "grace", "expired", "renewed", "suspended", "none", "exempt"]
Kind = Literal["trial", "paid", "courtesy"]
Milestone = Literal["before", "due", "grace_end"]

LIMITED: frozenset[str] = frozenset({"none", "expired", "suspended"})
TRIAL_WARN = timedelta(days=3)
WARN = timedelta(days=7)
GRACE = timedelta(days=3)
RENEWED_FOR = timedelta(days=7)
TRIAL_DAYS_MIN, TRIAL_DAYS_MAX, TRIAL_DAYS_DEFAULT = 7, 20, 20
COURTESY_DAYS_MAX = 90
MONTHS_MAX = 12
METHODS: tuple[str, ...] = ("transfer", "nequi", "daviplata", "cash", "card", "paypal", "other")
"""How the reader paid (P6 of the plan decides which the owner offers): the database refuses any other."""
AMOUNT_MAX = Decimal("1000000000")
REFERENCE_MAX = 120
LONG_NUMBER = re.compile(r"[0-9]{10}")
"""A run of ten digits or more - a card's or an account's number - once spaces, dots and dashes are taken out."""
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
SWITCH = "FBI_MEMBERSHIP_ENFORCE"


# ── settings ──────────────────────────────────────────────────────────────────────────

def enforced() -> bool:
    """FBI_MEMBERSHIP_ENFORCE, born off: on only once every live account has its period (plan UX, section 22)."""
    return os.environ.get(SWITCH, "0").strip().lower() in ("1", "true", "yes", "on")


def trial_days() -> int:
    """FBI_TRIAL_DAYS: 20 unless the owner says otherwise, between 7 and 20."""
    raw = os.environ.get("FBI_TRIAL_DAYS", "").strip()
    try:
        days = int(raw) if raw else TRIAL_DAYS_DEFAULT
    except ValueError:
        return TRIAL_DAYS_DEFAULT
    return min(max(days, TRIAL_DAYS_MIN), TRIAL_DAYS_MAX)


def currency() -> str:
    """The currency the console's payment form proposes (FBI_MEMBERSHIP_CURRENCY; P6 of the plan): COP by default."""
    raw = os.environ.get("FBI_MEMBERSHIP_CURRENCY", "COP").strip().upper()
    return raw if re.fullmatch(r"[A-Z]{3}", raw) else "COP"


PRICE_SETTINGS: tuple[tuple[str, str, Decimal], ...] = (
    ("COP", "FBI_MEMBERSHIP_PRICE_COP", Decimal("150000")),
    ("USD", "FBI_MEMBERSHIP_PRICE_USD", Decimal("50")),
)
"""The monthly price in each currency a reader may pay in, with the owner's decision of 5-nov-2026 as the default:
150,000 COP or 50 USD, whichever the reader prefers."""
_PRICE_OFF = ("0", "off", "false", "no")


def prices() -> list[dict[str, str]]:
    """The monthly price a reader sees, one entry per currency the owner offers (FBI_MEMBERSHIP_PRICE_COP and
    FBI_MEMBERSHIP_PRICE_USD): the default without the line, nothing for a currency set to 0/off/false/no or to a value
    that is not a positive amount (a wrong price is never shown). No payment gateway is behind it: the reader pays
    outside PrediGol and the owner records it."""
    found: list[dict[str, str]] = []
    for code, name, default in PRICE_SETTINGS:
        raw = os.environ.get(name, "").strip()
        if raw.lower() in _PRICE_OFF:
            continue
        try:
            amount = Decimal(raw) if raw else default
        except InvalidOperation:
            continue
        if not amount.is_finite() or not 0 < amount <= AMOUNT_MAX:
            continue
        found.append({"currency": code, "amount": format(amount.normalize(), "f")})
    return found


def whatsapp() -> str | None:
    """The WhatsApp Business number readers write to for renewing (FBI_SUPPORT_WHATSAPP; P7 of the plan), digits
    only with the country code; None until the owner gives it."""
    digits = re.sub(r"[^0-9]", "", os.environ.get("FBI_SUPPORT_WHATSAPP", ""))
    return digits if 8 <= len(digits) <= 15 else None


def reply_address() -> str | None:
    """The address a reader's answer to a membership e-mail reaches (FBI_EMAIL_REPLY_TO of A5), if any."""
    raw = os.environ.get("FBI_EMAIL_REPLY_TO", "").strip()
    match = re.search(r"[^<>\s]+@[^<>\s]+", raw)
    return match.group(0) if match else None


# ── the state ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Period:
    id: int
    kind: Kind
    starts_at: datetime
    ends_at: datetime
    created_at: datetime
    payment_id: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    kind: str
    at: datetime
    reason: str | None = None
    period_id: int | None = None
    milestone: str | None = None


@dataclass(frozen=True, slots=True)
class Membership:
    state: State
    ends_at: datetime | None
    """When the cover ends (the last period's end); None without a period."""
    grace_until: datetime | None
    kind: Kind | None
    """The kind of the period that ends last."""
    period_id: int | None
    will_not_renew: bool
    suspended_reason: str | None
    limited: bool
    """Whether this account reads only what a limited one reads, right now (the switch included)."""

    def days_left(self, at: datetime) -> int | None:
        if self.ends_at is None:
            return None
        seconds = (self.ends_at - at).total_seconds()
        return max(0, -(-int(seconds) // 86_400))  # whole days, rounded up: «3 days left» until the last hour


EXEMPT = Membership("exempt", None, None, None, None, False, None, False)


def _follows_paid(current: Period, periods: Sequence[Period]) -> bool:
    """Whether a paid period follows a paid one: the period in force before it was recorded was paid."""
    before = [p for p in periods if (p.created_at, p.id) < (current.created_at, current.id)]
    if not before:
        return False
    previous = max(before, key=lambda p: (p.ends_at, p.created_at, p.id))
    return previous.kind == "paid"


def compute(periods: Sequence[Period], events_: Iterable[Event], at: datetime, *, enforce: bool) -> Membership:
    """The membership at ``at``: pure, the clock is the caller's (the tests move it day by day)."""
    suspended: str | None = None
    will_not = False
    for e in sorted(events_, key=lambda e: (e.at, e.id)):
        if e.kind == "suspended":
            suspended = e.reason or "-"
        elif e.kind == "suspension_lifted":
            suspended = None
        elif e.kind == "will_not_renew":
            will_not = True
        elif e.kind == "will_renew":
            will_not = False
    if not periods:
        state: State = "suspended" if suspended is not None else "none"
        return Membership(state, None, None, None, None, will_not, suspended, enforce and state in LIMITED)
    current = max(periods, key=lambda p: (p.ends_at, p.created_at, p.id))
    end = current.ends_at
    grace_until = end + GRACE
    if suspended is not None:
        state = "suspended"
    elif at < end:
        if end - at <= (TRIAL_WARN if current.kind == "trial" else WARN):
            state = "expiring"
        elif current.kind == "paid" and at < current.created_at + RENEWED_FOR and _follows_paid(current, periods):
            state = "renewed"
        else:
            state = "trial" if current.kind == "trial" else "active"
    elif at < grace_until:
        state = "grace"
    else:
        state = "expired"
    return Membership(state, end, grace_until, current.kind, current.id, will_not, suspended,
                      enforce and state in LIMITED)


def add_months(moment: datetime, months: int) -> datetime:
    """The same day and time ``months`` later; the last day of a shorter month when that day does not exist."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


# ── reading ───────────────────────────────────────────────────────────────────────────

_PERIOD_COLUMNS = "id, user_id, kind, starts_at, ends_at, created_at, payment_id, reason"
_STATE_EVENTS = ("suspended", "suspension_lifted", "will_not_renew", "will_renew")


def load(conn: psycopg.Connection[Any], user_ids: Sequence[int]) -> dict[int, tuple[list[Period], list[Event]]]:
    """Each account's periods and the events its state depends on, in two queries whatever the number of accounts."""
    out: dict[int, tuple[list[Period], list[Event]]] = {uid: ([], []) for uid in user_ids}
    if not user_ids:
        return out
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_PERIOD_COLUMNS} FROM customer.membership_periods WHERE user_id = ANY(%s)",
                    (list(user_ids),))
        for r in cur.fetchall():
            uid = int(r.pop("user_id"))
            out[uid][0].append(Period(**r))
        cur.execute("""
            SELECT id, user_id, kind, at, reason, period_id, milestone FROM customer.membership_events
             WHERE user_id = ANY(%s) AND kind = ANY(%s)
        """, (list(user_ids), list(_STATE_EVENTS)))
        for r in cur.fetchall():
            uid = int(r.pop("user_id"))
            out[uid][1].append(Event(**r))
    return out


def of(conn: psycopg.Connection[Any], user_id: int, *, email: str, super_admin: bool,
       at: datetime | None = None) -> Membership:
    """One account's membership now (or at ``at``)."""
    if consents.exempt(email, super_admin=super_admin):
        return EXEMPT
    periods, events_ = load(conn, [user_id])[user_id]
    return compute(periods, events_, at or datetime.now(UTC), enforce=enforced())


def of_many(conn: psycopg.Connection[Any], users: Sequence[Mapping[str, Any]],
            at: datetime | None = None) -> dict[int, Membership]:
    """Many accounts at once (the console's list): rows with id, email and role."""
    moment = at or datetime.now(UTC)
    enforce = enforced()
    loaded = load(conn, [int(u["id"]) for u in users])
    out: dict[int, Membership] = {}
    for u in users:
        uid = int(u["id"])
        if consents.exempt(str(u["email"]), super_admin=u["role"] == "SUPER_ADMIN"):
            out[uid] = EXEMPT
        else:
            periods, events_ = loaded[uid]
            out[uid] = compute(periods, events_, moment, enforce=enforce)
    return out


# The gate's memory, per process: a limited account is checked again at most every LIMIT_TTL_S, so a renewal reaches
# every process of the API within that time (the process that recorded it forgets at once).
LIMIT_TTL_S = 20.0
_memory: dict[int, tuple[float, Membership]] = {}
_memory_lock = threading.Lock()


def gate_cached(conn: psycopg.Connection[Any], user_id: int, *, email: str, super_admin: bool) -> Membership:
    now = time.monotonic()
    with _memory_lock:
        hit = _memory.get(user_id)
        if hit is not None and hit[0] > now:
            return hit[1]
    found = of(conn, user_id, email=email, super_admin=super_admin)
    with _memory_lock:
        if len(_memory) > 10_000:
            _memory.clear()
        _memory[user_id] = (now + LIMIT_TTL_S, found)
    return found


def forget(user_id: int | None = None) -> None:
    with _memory_lock:
        if user_id is None:
            _memory.clear()
        else:
            _memory.pop(user_id, None)


# ── what the reader sees ──────────────────────────────────────────────────────────────

def summary(m: Membership, at: datetime | None = None) -> dict[str, Any] | None:
    """The membership as the reader's pages and the console read it; None for an exempt account."""
    if m.state == "exempt":
        return None
    moment = at or datetime.now(UTC)
    return {"state": m.state, "ends_at": m.ends_at, "grace_until": m.grace_until, "kind": m.kind,
            "days_left": m.days_left(moment), "limited": m.limited, "will_not_renew": m.will_not_renew}


def mine(conn: psycopg.Connection[Any], user_id: int, *, email: str, super_admin: bool) -> dict[str, Any]:
    """The reader's own membership: its state, its periods and their payments (amount, currency, method, date - the
    owner's reference stays in the export), and how to renew."""
    m = of(conn, user_id, email=email, super_admin=super_admin)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT p.kind, p.starts_at, p.ends_at, pay.amount, pay.currency, pay.method, pay.discount_percent
              FROM customer.membership_periods p
              LEFT JOIN customer.payments pay ON pay.id = p.payment_id
             WHERE p.user_id = %s ORDER BY p.ends_at DESC, p.id DESC LIMIT 50
        """, (user_id,))
        periods = [{**r, "amount": str(r["amount"]) if r["amount"] is not None else None} for r in cur.fetchall()]
    return {"membership": summary(m), "enforced": enforced(), "periods": periods,
            "renew": {"whatsapp": whatsapp(), "email": reply_address()},
            "plan": {"trial_days": trial_days(), "prices": prices()},
            "discounts": discount_view(conn, user_id) if m.state != "exempt" else _NO_DISCOUNTS}


_NO_DISCOUNTS: dict[str, Any] = {"offer": None, "coupons": [], "loyalty": None}


def offer_view(found: discounts.Offer | None) -> dict[str, Any] | None:
    """A discount as the pages say it: its kind, its percentage, a coupon's code and what the monthly price comes to
    with it, in each currency the owner offers."""
    if found is None:
        return None
    return {"kind": found.kind, "percent": found.percent, "code": found.code,
            "prices": [{"currency": p["currency"], "amount": discounts.discounted(p["amount"], found.percent)}
                       for p in prices()]}


def discount_view(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    """What the reader's Membership section says about discounts (UX-005): the one their next payment gets, the coupons
    they hold and the loyalty rule with where they stand in it."""
    found = discounts.standing(conn, user_id)
    return {**found, "offer": offer_view(found["offer"])}


# ── what the owner does ───────────────────────────────────────────────────────────────

def _clean_reason(reason: str | None, *, required: bool) -> str | None:
    text = " ".join((reason or "").split())
    if not text:
        if required:
            raise CustomerError(422, "reason_required", "say why, in a few words")
        return None
    if not 3 <= len(text) <= 200:
        raise CustomerError(422, "invalid_reason", "a reason of 3 to 200 characters")
    return text


def _account(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    """The account, locked for the rest of the transaction: two clicks on «extend» never compute the same start."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, email, role, status FROM auth.users WHERE id = %s FOR UPDATE", (user_id,))
        row = cur.fetchone()
    if row is None:
        raise CustomerError(404, "user_not_found", "no such account")
    if row["status"] == "deleted":
        raise CustomerError(409, "account_deleted", "this account was deleted")
    if row["status"] == "invited":
        raise CustomerError(409, "account_invited", "this account has not been activated yet")
    if row["role"] == "SUPER_ADMIN":
        raise CustomerError(409, "membership_exempt", "the owner's accounts have no membership")
    return dict(row)


def _cover_end(conn: psycopg.Connection[Any], user_id: int) -> datetime | None:
    row = conn.execute("SELECT max(ends_at) FROM customer.membership_periods WHERE user_id = %s",
                       (user_id,)).fetchone()
    return row[0] if row else None


def _insert_period(conn: psycopg.Connection[Any], user_id: int, kind: Kind, start: datetime, end: datetime, *,
                   payment_id: int | None = None, reason: str | None = None, actor: int | None = None) -> Period:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"""
            INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, payment_id, reason, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_PERIOD_COLUMNS}
        """, (user_id, kind, start, end, payment_id, reason, actor))
        row = cur.fetchone()
    assert row is not None
    row.pop("user_id")
    return Period(**row)


def _event(conn: psycopg.Connection[Any], user_id: int, kind: str, *, period_id: int | None = None,
           reason: str | None = None, detail: Mapping[str, Any] | None = None, actor: int | None = None) -> None:
    conn.execute("""
        INSERT INTO customer.membership_events (user_id, kind, period_id, reason, detail, actor_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (user_id, kind, period_id, reason, Json(dict(detail or {})), actor))


def _audit(conn: psycopg.Connection[Any], action: str, *, actor: int | None, user_id: int,
           detail: Mapping[str, Any]) -> None:
    """``membership.*`` in the access trail the console shows (never a payment's reference)."""
    # The account's trail, imported here: fbi.auth imports this module at the activation.
    from fbi.auth import store

    store.record_event(conn, f"membership.{action}", actor_user_id=actor, target_user_id=user_id, detail=dict(detail))


def tell(conn: psycopg.Connection[Any], user_id: int, template: str, key: str, period: Period) -> None:
    """The e-mail of a membership's beginning (closing plan 4.1: the welcome at the activation, the trial the owner
    started, a payment recorded): until when the reader has access, written in the transaction that made the period, so the e-mail exists only if it happened. Once per ``key``. Nothing is sent from here: the
    messenger sends the queue, and only while FBI_EMAIL_SEND is on."""
    # The queue (A5), imported here: the messaging package imports this module for the owner's notices.
    from fbi.messaging import outbox

    outbox.enqueue(conn, user_id=user_id, template=template,
                   params={"ends": period.ends_at.astimezone(UTC).isoformat(timespec="seconds")}, dedup_key=key)


def plan_trial(conn: psycopg.Connection[Any], user_id: int, days: int, *, actor: int | None) -> None:
    """The trial the owner chose at the invitation (7 to 20 days), started when the account is activated."""
    if not TRIAL_DAYS_MIN <= days <= TRIAL_DAYS_MAX:
        raise CustomerError(422, "invalid_trial_days", f"a trial of {TRIAL_DAYS_MIN} to {TRIAL_DAYS_MAX} days")
    _event(conn, user_id, "trial_planned", detail={"days": days}, actor=actor)


def start_trial(conn: psycopg.Connection[Any], user_id: int, *, at: datetime | None = None, days: int | None = None,
                actor: int | None = None) -> Period | None:
    """The account's one trial, from now: the days the owner chose at the invitation, else FBI_TRIAL_DAYS. None when
    the account had its trial already. In the caller's transaction (the activation's)."""
    moment = at or datetime.now(UTC)
    if conn.execute("SELECT 1 FROM customer.membership_periods WHERE user_id = %s AND kind = 'trial'",
                    (user_id,)).fetchone():
        return None
    if days is None:
        row = conn.execute("""
            SELECT (detail->>'days')::int FROM customer.membership_events
             WHERE user_id = %s AND kind = 'trial_planned' ORDER BY at DESC, id DESC LIMIT 1
        """, (user_id,)).fetchone()
        days = int(row[0]) if row and row[0] is not None else trial_days()
    start = max(moment, _cover_end(conn, user_id) or moment)
    period = _insert_period(conn, user_id, "trial", start, start + timedelta(days=days), actor=actor)
    _event(conn, user_id, "trial_started", period_id=period.id, detail={"days": days}, actor=actor)
    events.record_server(conn, user_id, "trial_started")
    forget(user_id)
    return period


def start_trial_for(user_id: int, *, actor: int | None) -> Period | None:
    """The trial of an account just created by the owner with a temporary password, in a transaction of its own."""
    with write_connection() as conn:
        return start_trial(conn, user_id, actor=actor)


def start_trial_by_owner(actor: int, user_id: int, *, days: int) -> Period:
    """A trial for an account that has none (one created before A8, or with a temporary password)."""
    if not TRIAL_DAYS_MIN <= days <= TRIAL_DAYS_MAX:
        raise CustomerError(422, "invalid_trial_days", f"a trial of {TRIAL_DAYS_MIN} to {TRIAL_DAYS_MAX} days")
    with write_connection() as conn:
        _account(conn, user_id)
        period = start_trial(conn, user_id, days=days, actor=actor)
        if period is None:
            raise CustomerError(409, "trial_used", "this account had its trial already")
        _audit(conn, "trial_started", actor=actor, user_id=user_id, detail={"days": days})
        tell(conn, user_id, "trial_started", f"trial_started:{period.id}", period)
    return period


@dataclass(frozen=True, slots=True)
class Recorded:
    payment_id: int
    period: Period
    created: bool
    """False when the idempotency key was recorded before: the same payment, nothing new."""


def _amount(raw: str | int | float | Decimal) -> Decimal:
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise CustomerError(422, "invalid_amount", "an amount like 50000 or 19.90") from exc
    if not Decimal("0") < value < AMOUNT_MAX:
        raise CustomerError(422, "invalid_amount", "an amount greater than zero")
    return value


def check_reference(reference: str) -> str:
    """A reference in words; never an account's or a card's number (a run of ten digits or more)."""
    text = " ".join(reference.split())
    if len(text) > REFERENCE_MAX:
        raise CustomerError(422, "invalid_reference", f"a reference of at most {REFERENCE_MAX} characters")
    if LONG_NUMBER.search(re.sub(r"[\s.\-]", "", text)):
        raise CustomerError(422, "reference_has_number",
                            "no account or card numbers: a few words or the last 4 digits are enough")
    return text


def record_payment(actor: int, user_id: int, *, amount: str | int | float | Decimal, currency_code: str,
                   method: str, reference: str, months: int, idempotency_key: str, apply_discount: bool = False,
                   at: datetime | None = None) -> Recorded:
    """«Record payment and extend»: the payment and its period - from the end of the one in force, or now when that one
    has ended - in one transaction. The same idempotency key records one payment, whoever clicks twice. With
    ``apply_discount`` the payment keeps the discount the reader's next payment is offered at this moment (UX-005: the
    larger of the loyalty one and the best coupon they hold; a coupon is then used) - the amount is what the owner
    received, the discount is what the payment says it carried; 409 ``no_discount`` when there is none."""
    value = _amount(amount)
    code = currency_code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise CustomerError(422, "invalid_currency", "a currency code like COP or USD")
    if method not in METHODS:
        raise CustomerError(422, "invalid_method", "a payment method of the list")
    text = check_reference(reference)
    if not 1 <= months <= MONTHS_MAX:
        raise CustomerError(422, "invalid_months", f"1 to {MONTHS_MAX} months")
    if not IDEMPOTENCY_KEY.match(idempotency_key):
        raise CustomerError(422, "invalid_idempotency_key", "8 to 80 letters, digits, - or _")
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        _account(conn, user_id)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, user_id FROM customer.payments WHERE idempotency_key = %s", (idempotency_key,))
            seen = cur.fetchone()
            if seen is not None:
                if int(seen["user_id"]) != user_id:
                    raise CustomerError(409, "idempotency_conflict", "this key recorded another account's payment")
                cur.execute(f"SELECT {_PERIOD_COLUMNS} FROM customer.membership_periods WHERE payment_id = %s",
                            (seen["id"],))
                row = cur.fetchone()
                assert row is not None
                row.pop("user_id")
                return Recorded(int(seen["id"]), Period(**row), created=False)
        periods, _ = load(conn, [user_id])[user_id]
        end = _cover_end(conn, user_id)
        start = max(moment, end) if end is not None else moment
        carried = discounts.offer(conn, user_id) if apply_discount else None
        if apply_discount and carried is None:
            raise CustomerError(409, "no_discount", "this account has no discount to apply")
        payment = conn.execute("""
            INSERT INTO customer.payments (user_id, provider, amount, currency, method, reference, idempotency_key,
                                           recorded_by, recorded_at, discount_percent, discount_kind, coupon_id)
            VALUES (%s, 'manual', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, value, code, method, text, idempotency_key, actor, moment,
              carried.percent if carried else None, carried.kind if carried else None,
              carried.coupon_id if carried else None)).fetchone()
        assert payment is not None
        period = _insert_period(conn, user_id, "paid", start, add_months(start, months), payment_id=int(payment[0]),
                                actor=actor)
        renewal = _follows_paid(period, [*periods, period])
        detail: dict[str, Any] = {"amount": str(value), "currency": code, "method": method, "months": months,
                                  "renewal": renewal}
        if carried is not None:
            detail["discount"] = {"kind": carried.kind, "percent": carried.percent}
        _event(conn, user_id, "payment_recorded", period_id=period.id, detail=detail, actor=actor)
        _audit(conn, "payment_recorded", actor=actor, user_id=user_id, detail=detail)
        events.record_server(conn, user_id, "membership_renewed")
        if period.ends_at > moment:
            tell(conn, user_id, "payment_recorded", f"payment_recorded:{payment[0]}", period)
    forget(user_id)
    log.info("membership.payment_recorded", user_id=user_id, months=months, renewal=renewal)
    return Recorded(int(payment[0]), period, created=True)


def grant_courtesy(actor: int, user_id: int, *, days: int, reason: str, at: datetime | None = None) -> Period:
    """Days given by the owner, with the reason, from the end of the cover in force (or now)."""
    if not 1 <= days <= COURTESY_DAYS_MAX:
        raise CustomerError(422, "invalid_days", f"1 to {COURTESY_DAYS_MAX} days")
    text = _clean_reason(reason, required=True)
    moment = at or datetime.now(UTC)
    with write_connection() as conn:
        _account(conn, user_id)
        end = _cover_end(conn, user_id)
        start = max(moment, end) if end is not None else moment
        period = _insert_period(conn, user_id, "courtesy", start, start + timedelta(days=days), reason=text,
                                actor=actor)
        _event(conn, user_id, "courtesy_granted", period_id=period.id, reason=text, detail={"days": days},
               actor=actor)
        _audit(conn, "courtesy_granted", actor=actor, user_id=user_id, detail={"days": days})
    forget(user_id)
    return period


def _state_now(conn: psycopg.Connection[Any], user_id: int) -> Membership:
    periods, events_ = load(conn, [user_id])[user_id]
    return compute(periods, events_, datetime.now(UTC), enforce=enforced())


def suspend(actor: int, user_id: int, *, reason: str) -> None:
    """Limited access until the owner lifts it, with the reason (the reader is told to write). The sessions stay."""
    text = _clean_reason(reason, required=True)
    with write_connection() as conn:
        _account(conn, user_id)
        if _state_now(conn, user_id).suspended_reason is not None:
            raise CustomerError(409, "already_suspended", "this membership is suspended already")
        _event(conn, user_id, "suspended", reason=text, actor=actor)
        _audit(conn, "suspended", actor=actor, user_id=user_id, detail={})
    forget(user_id)


def lift(actor: int, user_id: int, *, reason: str | None) -> None:
    """The suspension ends, with the reason (section 22: «suspender o levantar con motivo»)."""
    text = _clean_reason(reason, required=True)
    with write_connection() as conn:
        _account(conn, user_id)
        if _state_now(conn, user_id).suspended_reason is None:
            raise CustomerError(409, "not_suspended", "this membership is not suspended")
        _event(conn, user_id, "suspension_lifted", reason=text, actor=actor)
        _audit(conn, "suspension_lifted", actor=actor, user_id=user_id, detail={})
    forget(user_id)


def renewal_intent(actor: int, user_id: int, *, will_renew: bool, reason: str | None) -> None:
    """«Will not renew» with its reason (it stops the e-mails before and at the end), or its withdrawal."""
    text = _clean_reason(reason, required=not will_renew)
    with write_connection() as conn:
        _account(conn, user_id)
        current = _state_now(conn, user_id).will_not_renew
        if current == (not will_renew):
            raise CustomerError(409, "no_change", "the membership says that already")
        kind = "will_renew" if will_renew else "will_not_renew"
        _event(conn, user_id, kind, reason=text, actor=actor)
        _audit(conn, kind, actor=actor, user_id=user_id, detail={})
    forget(user_id)


def history(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    """The console's view of one account: its periods with their payments and every event, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT p.id, p.kind, p.starts_at, p.ends_at, p.reason, p.created_at,
                   pay.amount, pay.currency, pay.method, pay.reference, pay.provider,
                   pay.discount_percent, pay.discount_kind, cp.code AS coupon_code
              FROM customer.membership_periods p
              LEFT JOIN customer.payments pay ON pay.id = p.payment_id
              LEFT JOIN customer.coupons cp ON cp.id = pay.coupon_id
             WHERE p.user_id = %s ORDER BY p.ends_at DESC, p.id DESC
        """, (user_id,))
        periods = [{**r, "amount": str(r["amount"]) if r["amount"] is not None else None} for r in cur.fetchall()]
        cur.execute("""
            SELECT kind, at, reason, milestone, detail FROM customer.membership_events
             WHERE user_id = %s ORDER BY at DESC, id DESC LIMIT 200
        """, (user_id,))
        events_ = cur.fetchall()
    return {"periods": periods, "events": events_}


def export_rows(conn: psycopg.Connection[Any], user_id: int) -> dict[str, list[dict[str, Any]]]:
    """The reader's export (plan UX, A4): every period, payment and event of their membership - the payments' reference
    and the discount each carried included, never who in the console recorded them - and the coupons they redeemed."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT kind, starts_at, ends_at, reason, created_at FROM customer.membership_periods
             WHERE user_id = %s ORDER BY ends_at DESC, id DESC
        """, (user_id,))
        periods = cur.fetchall()
        cur.execute("""
            SELECT pay.provider, pay.amount, pay.currency, pay.method, pay.reference, pay.recorded_at,
                   pay.discount_percent, pay.discount_kind, cp.code AS coupon_code
              FROM customer.payments pay LEFT JOIN customer.coupons cp ON cp.id = pay.coupon_id
             WHERE pay.user_id = %s ORDER BY pay.recorded_at DESC, pay.id DESC
        """, (user_id,))
        payments = [{**r, "amount": str(r["amount"])} for r in cur.fetchall()]
        cur.execute("""
            SELECT kind, milestone, reason, at FROM customer.membership_events
             WHERE user_id = %s ORDER BY at DESC, id DESC
        """, (user_id,))
        events_ = cur.fetchall()
        cur.execute("""
            SELECT c.code, c.percent, r.redeemed_at FROM customer.coupon_redemptions r
              JOIN customer.coupons c ON c.id = r.coupon_id
             WHERE r.user_id = %s ORDER BY r.redeemed_at DESC, r.id DESC
        """, (user_id,))
        coupons = cur.fetchall()
    return {"membership_periods": periods, "payments": payments, "membership_events": events_,
            "coupon_redemptions": coupons}


# ── the messenger: the notices around a period's end ─────────────────────────────────

@dataclass(frozen=True, slots=True)
class Notice:
    user_id: int
    period_id: int
    milestone: Milestone
    ends_at: datetime
    kind: Kind
    email: bool


def due_notices(m: Membership, user_id: int) -> list[Notice]:
    """The notices owed for the cover's end at this state: 7 days before (3 in a trial) an e-mail; at the end an
    e-mail (three days of grace with everything); at the grace's end only the app (and the event). «Will not renew»
    keeps the app's notices and stops the e-mails."""
    if m.period_id is None or m.ends_at is None or m.kind is None or m.state in ("suspended", "exempt", "none"):
        return []
    email = not m.will_not_renew
    if m.state == "expiring":
        return [Notice(user_id, m.period_id, "before", m.ends_at, m.kind, email)]
    if m.state == "grace":
        return [Notice(user_id, m.period_id, "due", m.ends_at, m.kind, email)]
    if m.state == "expired":
        return [Notice(user_id, m.period_id, "grace_end", m.ends_at, m.kind, False)]
    return []


TEMPLATE_FOR: dict[str, str] = {"before": "membership_expiring", "due": "membership_grace"}


def remind(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Every account whose cover ends within the warning or ended within the grace (and a week more, should the
    messenger have stopped for a while): the notice it is
    owed, once per period and milestone - the unique index of the events is the guard, so two messengers or a
    repeated cycle add nothing. Returns the notices recorded. Exempt and suspended accounts are told nothing."""
    # The queue (A5), imported here: the messaging package imports this module for the owner's notices.
    from fbi.messaging import outbox

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT u.id, u.email, u.role FROM auth.users u
             WHERE u.status = 'active'
               AND EXISTS (SELECT 1 FROM customer.membership_periods p WHERE p.user_id = u.id)
               AND (SELECT max(ends_at) FROM customer.membership_periods p WHERE p.user_id = u.id)
                   BETWEEN %s AND %s
        """, (at - GRACE - timedelta(days=7), at + WARN))
        users = cur.fetchall()
    done = 0
    for user_id, m in of_many(conn, users, at).items():
        for n in due_notices(m, user_id):
            row = conn.execute("""
                INSERT INTO customer.membership_events (user_id, kind, period_id, milestone, detail)
                VALUES (%s, 'notice', %s, %s, %s)
                ON CONFLICT (period_id, milestone) WHERE kind = 'notice' DO NOTHING RETURNING id
            """, (n.user_id, n.period_id, n.milestone, Json({"email": n.email}))).fetchone()
            if row is None:
                continue
            done += 1
            if n.email:
                outbox.enqueue(conn, user_id=n.user_id, template=TEMPLATE_FOR[n.milestone],
                               params={"ends": n.ends_at.astimezone(UTC).isoformat(timespec="seconds"),
                                       "kind": n.kind},
                               dedup_key=f"membership:{n.period_id}:{n.milestone}")
            if n.milestone == "grace_end":
                events.record_server(conn, n.user_id, "membership_expired")
    conn.commit()
    return done


def owner_counts(conn: psycopg.Connection[Any], *, at: datetime, today_bounds: tuple[datetime, datetime]
                 ) -> dict[str, int]:
    """For the owner's morning notice (membership_due): how many covers end today, how many accounts are in their
    grace, how many became limited in the last day, and how many said they will not renew - counts, never names."""
    start, end = today_bounds
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT u.id, u.email, u.role FROM auth.users u
             WHERE u.status = 'active' AND EXISTS (SELECT 1 FROM customer.membership_periods p WHERE p.user_id = u.id)
        """)
        users = cur.fetchall()
    counts = {"ending_today": 0, "in_grace": 0, "expired_today": 0, "will_not_renew": 0}
    for m in of_many(conn, users, at).values():
        if m.state == "exempt" or m.ends_at is None:
            continue
        if start <= m.ends_at < end:
            counts["ending_today"] += 1
        if m.state == "grace":
            counts["in_grace"] += 1
        if m.grace_until is not None and m.state == "expired" and at - timedelta(days=1) <= m.grace_until <= at:
            counts["expired_today"] += 1
        if m.will_not_renew and m.state in ("expiring", "grace"):
            counts["will_not_renew"] += 1
    return counts

"""Each customer's state of the day, with its reasons (plan UX, B11; section 23).

Once a day, for every reader, PrediGol keeps where they stand and why:

    invited    the account exists and was never activated
    activated  activated, with some use but not yet a habit
    habitual   used on 3 of the last 7 days (and nothing worse below)
    at_risk    nothing for 7 days, or the last survey was 2 or less, or a request waiting 72 hours
    expiring   the cover ends within 7 days (3 in a trial) or its grace runs
    renewed    a paid period that follows a paid one was recorded less than 7 days ago
    expired    the cover and its grace ended

Precedence (the first that holds): expired > expiring > renewed > at_risk > habitual > activated > invited. The state of
the membership decides the first three - the same ``membership.compute`` the reader's pages use - and the use decides
the rest. Every state carries reason codes from a closed list (``REASONS``), never a word the reader wrote, an amount
or an address.

It is read by the support queue (an at-risk reader's request goes up), the owner's morning notice (counts and a link,
never names), the console's customers and the product page's metrics. It is never used to send campaigns: the only
automatic messages to readers stay the membership's four notices and the security ones. Nothing of PrediGol Intelligence
is read or written here.

FBI_LIFECYCLE: on unless set to 0/off/false (``=0`` stops the daily calculation; the table and its history stay).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, Literal, get_args

import psycopg
from psycopg.rows import dict_row

from fbi.auth import crypto
from fbi.customer import consents, events, feedback, membership
from fbi.customer.events import PurgeMode

State = Literal["invited", "activated", "habitual", "at_risk", "expiring", "renewed", "expired"]
STATES: Final[tuple[str, ...]] = get_args(State)
SWITCH: Final = "FBI_LIFECYCLE"
HABIT_DAYS: Final = 3
HABIT_WINDOW: Final = 7
SILENT_DAYS: Final = 7
TICKET_WAIT: Final = timedelta(hours=72)
RETENTION: Final = timedelta(days=730)
"""24 months (the customer data's table of the plan)."""

REASONS: Final[frozenset[str]] = frozenset({
    "membership_expired", "membership_grace", "membership_expiring", "membership_renewed",
    "silent_7d", "low_survey", "ticket_waiting_72h", "used_3_of_7_days", "some_use", "never_used",
    "account_invited", "account_activated",
})
"""The closed list of reason codes: the console and the notice write each one in words."""


def enabled() -> bool:
    return os.environ.get(SWITCH, "1").strip().lower() not in ("0", "off", "false", "no")


@dataclass(frozen=True, slots=True)
class Inputs:
    """What one reader's day needs; pure data, so the transitions are proved with synthetic stories."""

    account_status: str
    """auth.users.status: invited, active, disabled."""
    created_at: datetime
    membership: str
    """membership.State of the day."""
    active_days_7: int
    active_days_14: int
    low_survey: bool
    ticket_waiting: bool


@dataclass(frozen=True, slots=True)
class Judgement:
    state: State
    reasons: tuple[str, ...]


def judge(i: Inputs, at: datetime) -> Judgement | None:
    """The reader's state at ``at``; None for an account that has no state (the owner, the synthetic account, a
    disabled or suspended one: nothing is kept for them)."""
    if i.membership in ("exempt", "suspended") or i.account_status not in ("active", "invited"):
        return None
    if i.membership == "expired":
        return Judgement("expired", ("membership_expired",))
    if i.membership == "expiring":
        return Judgement("expiring", ("membership_expiring",))
    if i.membership == "grace":
        return Judgement("expiring", ("membership_grace",))
    if i.membership == "renewed":
        return Judgement("renewed", ("membership_renewed",))
    if i.account_status == "invited":
        return Judgement("invited", ("account_invited",))
    reasons: list[str] = []
    old_enough = i.created_at <= at - timedelta(days=SILENT_DAYS)
    if old_enough and i.active_days_7 == 0:
        reasons.append("silent_7d")
    if i.low_survey:
        reasons.append("low_survey")
    if i.ticket_waiting:
        reasons.append("ticket_waiting_72h")
    if reasons:
        return Judgement("at_risk", tuple(reasons))
    if i.active_days_7 >= HABIT_DAYS:
        return Judgement("habitual", ("used_3_of_7_days",))
    if i.active_days_14 > 0 or i.active_days_7 > 0:
        return Judgement("activated", ("account_activated", "some_use"))
    return Judgement("activated", ("account_activated", "never_used"))


# ── the day's calculation ─────────────────────────────────────────────────────────────

_ACCOUNTS_SQL = """
    SELECT id, email, role, status, created_at FROM auth.users
     WHERE role = 'USER' AND status IN ('active', 'invited') ORDER BY id
"""


def _active_days(conn: psycopg.Connection[Any], subjects: dict[int, str], day: date, window: int) -> dict[int, int]:
    if not subjects:
        return {}
    by_subject = {s: i for i, s in subjects.items()}
    rows = conn.execute("SELECT subject, count(*) FROM customer.activity_daily WHERE day > %s AND day <= %s "
                        "AND subject = ANY(%s) GROUP BY subject",
                        (day - timedelta(days=window), day, list(by_subject))).fetchall()
    return {by_subject[str(r[0])]: int(r[1]) for r in rows}


def _waiting(conn: psycopg.Connection[Any], at: datetime) -> set[int]:
    rows = conn.execute("SELECT DISTINCT user_id FROM customer.support_tickets WHERE status = 'open' "
                        "AND opened_at <= %s", (at - TICKET_WAIT,)).fetchall()
    return {int(r[0]) for r in rows}


def compute_day(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Writes the Bogota day's snapshot for every reader that has none yet (one row each, never rewritten: a second call
    the same day adds nothing). The caller commits. Returns the rows written."""
    day = events.bogota_day(at)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ACCOUNTS_SQL)
        accounts = list(cur.fetchall())
    done = {int(r[0]) for r in conn.execute("SELECT user_id FROM customer.lifecycle_snapshots WHERE day = %s",
                                            (day,)).fetchall()}
    accounts = [a for a in accounts if int(a["id"]) not in done]
    if not accounts:
        return 0
    ids = [int(a["id"]) for a in accounts]
    members = membership.of_many(conn, accounts, at)
    subjects: dict[int, str] = {}
    for uid in ids:
        subject = crypto.product_id(uid)
        if subject is not None:
            subjects[uid] = subject
    d7 = _active_days(conn, subjects, day, HABIT_WINDOW)
    d14 = _active_days(conn, subjects, day, 14)
    risky = set(feedback.at_risk(conn, at=at))
    waiting = _waiting(conn, at)
    rows: list[tuple[int, date, str, list[str]]] = []
    for a in accounts:
        uid = int(a["id"])
        if consents.exempt(str(a["email"]), super_admin=False):
            continue
        judged = judge(Inputs(account_status=a["status"], created_at=a["created_at"],
                              membership=members[uid].state, active_days_7=d7.get(uid, 0),
                              active_days_14=d14.get(uid, 0), low_survey=uid in risky,
                              ticket_waiting=uid in waiting), at)
        if judged is not None:
            rows.append((uid, day, judged.state, list(judged.reasons)))
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, day) DO NOTHING", rows)
    return len(rows)


# ── reading ───────────────────────────────────────────────────────────────────────────

LATEST_SQL = """
    SELECT DISTINCT ON (user_id) user_id, day, state, reasons FROM customer.lifecycle_snapshots
     WHERE user_id = ANY(%s) ORDER BY user_id, day DESC
"""


def latest_states(conn: psycopg.Connection[Any], user_ids: list[int]) -> dict[int, tuple[str, list[str], date]]:
    """Each reader's newest snapshot: state, reasons and the day it was written."""
    if not user_ids:
        return {}
    rows = conn.execute(LATEST_SQL, (user_ids,)).fetchall()
    return {int(r[0]): (str(r[2]), list(r[3]), r[1]) for r in rows}


def history(conn: psycopg.Connection[Any], user_id: int, *, limit: int = 60) -> list[dict[str, Any]]:
    """One reader's changes of state, newest first: a day is listed only when its state differs from the day before."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT day, state, reasons FROM customer.lifecycle_snapshots WHERE user_id = %s "
                    "ORDER BY day", (user_id,))
        rows = list(cur.fetchall())
    changes: list[dict[str, Any]] = []
    previous: str | None = None
    for r in rows:
        if r["state"] != previous:
            changes.append({"day": r["day"], "state": r["state"], "reasons": list(r["reasons"])})
            previous = r["state"]
    return list(reversed(changes))[:limit]


def counts(conn: psycopg.Connection[Any], *, day: date) -> dict[str, int]:
    """How many readers are in each state on a day (the owner's morning notice and the console's views)."""
    rows = conn.execute("SELECT state, count(*) FROM customer.lifecycle_snapshots WHERE day = %s GROUP BY state",
                        (day,)).fetchall()
    out = dict.fromkeys(STATES, 0)
    for state, n in rows:
        out[str(state)] = int(n)
    return out


def at_risk_ids(conn: psycopg.Connection[Any], *, day: date) -> set[int]:
    """The readers at risk on a day: the support queue puts their requests first."""
    rows = conn.execute("SELECT user_id FROM customer.lifecycle_snapshots WHERE day = %s AND state = 'at_risk'",
                        (day,)).fetchall()
    return {int(r[0]) for r in rows}


def export_rows(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    """The reader's own copy of their states (A4): each day with its state and the reason codes, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        return list(cur.execute("SELECT day, state, reasons FROM customer.lifecycle_snapshots WHERE user_id = %s "
                                "ORDER BY day DESC", (user_id,)).fetchall())


# ── retention ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PurgeReport:
    mode: PurgeMode
    rows: int


def purge(conn: psycopg.Connection[Any], *, at: datetime, mode: PurgeMode) -> PurgeReport:
    """Snapshots older than 24 months: counted (``dry``) or deleted (``on``) under the maintenance switch - the same
    FBI_EVENTS_PURGE as the analytics' retention (the owner's decision). The caller commits."""
    before = events.bogota_day(at - RETENTION)
    if mode == "off":
        return PurgeReport("off", 0)
    if mode == "dry":
        row = conn.execute("SELECT count(*) FROM customer.lifecycle_snapshots WHERE day < %s", (before,)).fetchone()
        return PurgeReport("dry", int(row[0]) if row else 0)
    conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
    n = conn.execute("DELETE FROM customer.lifecycle_snapshots WHERE day < %s", (before,)).rowcount
    return PurgeReport("on", max(n, 0))


def forget(conn: psycopg.Connection[Any], user_id: int) -> int:
    """The account's anonymisation (A7): its snapshots go with it. Runs in the anonymisation's transaction."""
    conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
    return max(conn.execute("DELETE FROM customer.lifecycle_snapshots WHERE user_id = %s", (user_id,)).rowcount, 0)


# ── the owner's metrics (the product page) ────────────────────────────────────────────

COHORT_MIN: Final = 30
"""A rate over fewer readers than this is not shown: «datos insuficientes», never a percentage of three people."""
COHORT_LOOKBACK: Final = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class Rate:
    """A share of a cohort: ``value`` is None while the cohort is under COHORT_MIN."""

    n: int
    of: int
    value: float | None


def rate(n: int, of: int) -> Rate:
    return Rate(n, of, round(n / of, 3) if of >= COHORT_MIN else None)


@dataclass(frozen=True, slots=True)
class Metrics:
    day: date | None
    states: dict[str, int]
    renewal_30d: Rate
    """Of the periods that ended in the last 30 days, the readers who have a later period (a renewal)."""
    activation_7d: Rate
    """Of the accounts created 7 to 90 days ago, those that activated within 7 days."""
    retention_d7: Rate
    """Of the accounts created 14 to 90 days ago, those active on some day between their 7th and 13th."""
    retention_d30: Rate
    """Of the accounts created 37 to 90 days ago, those active on some day between their 30th and 36th."""


def metrics(conn: psycopg.Connection[Any], *, at: datetime) -> Metrics:
    """The lifecycle's figures for the owner. Counts and shares of cohorts only, never a name; these are measures to
    watch - nothing optimises them (no message, no nudge is sent because of them)."""
    day = events.bogota_day(at)
    newest = conn.execute("SELECT max(day) FROM customer.lifecycle_snapshots").fetchone()
    last_day = newest[0] if newest else None
    states = counts(conn, day=last_day) if last_day is not None else dict.fromkeys(STATES, 0)

    row = conn.execute("""
        WITH ended AS (
            SELECT DISTINCT p.user_id, max(p.ends_at) AS ends_at FROM customer.live_membership_periods p
              JOIN auth.users u ON u.id = p.user_id AND u.role = 'USER' AND u.status <> 'deleted'
             WHERE p.ends_at > %(since)s AND p.ends_at <= %(at)s GROUP BY p.user_id
        )
        SELECT count(*), count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM customer.live_membership_periods n
                    WHERE n.user_id = ended.user_id AND n.ends_at > ended.ends_at))
          FROM ended
    """, {"since": at - timedelta(days=30), "at": at}).fetchone()
    renewal = rate(int(row[1]) if row else 0, int(row[0]) if row else 0)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, created_at FROM auth.users WHERE role = 'USER' AND status <> 'deleted' "
                    "AND created_at >= %s AND created_at <= %s", (at - COHORT_LOOKBACK, at - timedelta(days=7)))
        accounts = list(cur.fetchall())
    subjects = {}
    for a in accounts:
        subject = crypto.product_id(int(a["id"]))
        if subject is not None:
            subjects[int(a["id"])] = subject
    activated_rows = conn.execute("SELECT subject, min(at) FROM customer.product_events WHERE name = 'account_activated' "
                                  "AND subject = ANY(%s) GROUP BY subject", (list(subjects.values()),)).fetchall() \
        if subjects else []
    activated_at = {str(r[0]): r[1] for r in activated_rows}
    act_n = act_of = 0
    for a in accounts:
        subject = subjects.get(int(a["id"]))
        if subject is None:
            continue
        act_of += 1
        first = activated_at.get(subject)
        if first is not None and first <= a["created_at"] + timedelta(days=7):
            act_n += 1
    days_rows = conn.execute("SELECT subject, day FROM customer.activity_daily WHERE subject = ANY(%s)",
                             (list(subjects.values()),)).fetchall() if subjects else []
    active_days: dict[str, set[date]] = {}
    for subject, d in days_rows:
        active_days.setdefault(str(subject), set()).add(d)

    def retained(lo: int, hi: int, minimum_age: int) -> Rate:
        n = of = 0
        for a in accounts:
            subject = subjects.get(int(a["id"]))
            created = events.bogota_day(a["created_at"])
            if subject is None or created > day - timedelta(days=minimum_age):
                continue
            of += 1
            if any(created + timedelta(days=lo) <= d <= created + timedelta(days=hi)
                   for d in active_days.get(subject, ())):
                n += 1
        return rate(n, of)

    return Metrics(day=last_day, states=states, renewal_30d=renewal, activation_7d=rate(act_n, act_of),
                   retention_d7=retained(7, 13, 14), retention_d30=retained(30, 36, 37))

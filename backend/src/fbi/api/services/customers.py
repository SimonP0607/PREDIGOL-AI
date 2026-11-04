"""The customer's card (plan UX, B10): the owner's view of one reader and the lists that tell who needs attention.

Only reads, from what PrediGol already keeps: the account, its membership (computed from dates, fbi.customer.membership),
the daily counts of their use (``customer.activity_daily``, by the reader's pseudonym), their tickets, answers, consents
and notices. Minimised on purpose: no IP, no token, no loose click - the use is counts of days; a phone number is not
kept anywhere in PrediGol, so the card has none to show. The views are pure functions of the card's numbers
(``in_view``) so they are proved with synthetic readers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, get_args

import psycopg
from psycopg.rows import dict_row

from fbi.api.contracts.customers import (
    Customer,
    CustomerConsent,
    CustomerDevice,
    CustomerFeedback,
    CustomerFeedbackSummary,
    CustomerIdentity,
    CustomerList,
    CustomerNote,
    CustomerNotifications,
    CustomerRow,
    CustomerTicket,
    CustomerUsage,
    CustomerView,
    CustomerViewCount,
)
from fbi.api.contracts.membership import MembershipSummary
from fbi.auth import crypto
from fbi.customer import consents, events, membership, push, support
from fbi.customer.db import CustomerError

VIEWS: Final[tuple[str, ...]] = get_args(CustomerView)
EXPIRING_DAYS: Final = 7
INACTIVE_DAYS: Final = 14
ERRORS_WINDOW: Final = timedelta(hours=24)
NOTE_ACTION: Final = "customer.note"
AUDIT_ACTIONS: Final = {
    "note": NOTE_ACTION,
    "consents": "customer.consents_viewed",
    "ticket": "customer.ticket_reviewed",
    "export": "customer.exported",
    "export_reauth": "customer.export",
}
"""What the card records in the access trail (``auth.audit_events``), each with the account it is about."""


@dataclass(frozen=True, slots=True)
class Facts:
    """What a view needs of one customer."""

    status: str
    created_at: datetime
    last_seen_at: datetime | None
    ends_at: datetime | None
    grace_until: datetime | None
    suspended: bool
    open_tickets: int
    errors_24h: int


def in_view(view: str, f: Facts, at: datetime) -> bool:
    """Whether a customer belongs to a view at this moment.

    * expiring - their cover ends within 7 days, or has ended and the grace still runs; not a suspended account.
    * inactive - an activated account that has not been seen for 14 days (since the invitation when never seen).
    * tickets - at least one ticket or request not closed.
    * errors - at least one error shown to them in the last 24 hours.
    """
    if view == "all":
        return True
    if view == "expiring":
        if f.suspended or f.ends_at is None:
            return False
        return f.ends_at <= at + timedelta(days=EXPIRING_DAYS) and (f.grace_until or f.ends_at) >= at
    if view == "inactive":
        if f.status != "active":
            return False
        return (f.last_seen_at or f.created_at) < at - timedelta(days=INACTIVE_DAYS)
    if view == "tickets":
        return f.open_tickets > 0
    if view == "errors":
        return f.errors_24h > 0
    raise CustomerError(422, "unknown_view", "no such view")


# ── the numbers, in a few queries for many readers ────────────────────────────────────

_ACCOUNTS_SQL = """
    SELECT u.id, u.email, u.display_name, u.role, u.status, u.language, u.timezone, u.created_at, u.last_login_at,
           (SELECT max(s.last_seen_at) FROM auth.sessions s WHERE s.user_id = u.id) AS last_seen_at,
           (u.totp_enabled_at IS NOT NULL) AS mfa_enabled
      FROM auth.users u
     WHERE u.role = 'USER' AND u.status <> 'deleted'{one}
     ORDER BY u.created_at DESC, u.id DESC
"""


def _accounts(conn: psycopg.Connection[Any], user_id: int | None = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ACCOUNTS_SQL.format(one=" AND u.id = %s" if user_id is not None else ""),
                    (user_id,) if user_id is not None else ())
        return list(cur.fetchall())


def _open_tickets(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = conn.execute("SELECT user_id, count(*) FROM customer.support_tickets WHERE status <> 'closed' "
                        "AND user_id = ANY(%s) GROUP BY user_id", (ids,)).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _subjects(ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i in ids:
        subject = crypto.product_id(i)
        if subject is not None:
            out[i] = subject
    return out


def _errors_24h(conn: psycopg.Connection[Any], subjects: dict[int, str], at: datetime) -> dict[int, int]:
    if not subjects:
        return {}
    by_subject = {s: i for i, s in subjects.items()}
    rows = conn.execute("SELECT subject, count(*) FROM customer.product_events WHERE name = 'error_shown' "
                        "AND at >= %s AND at <= %s AND subject = ANY(%s) GROUP BY subject",
                        (at - ERRORS_WINDOW, at, list(by_subject))).fetchall()
    return {by_subject[str(r[0])]: int(r[1]) for r in rows}


def _active_days(conn: psycopg.Connection[Any], subjects: dict[int, str], at: datetime, days: int
                 ) -> dict[int, int]:
    if not subjects:
        return {}
    by_subject = {s: i for i, s in subjects.items()}
    first = events.bogota_day(at) - timedelta(days=days - 1)
    rows = conn.execute("SELECT subject, count(*) FROM customer.activity_daily WHERE day >= %s AND subject = ANY(%s) "
                        "GROUP BY subject", (first, list(by_subject))).fetchall()
    return {by_subject[str(r[0])]: int(r[1]) for r in rows}


def _last_csat(conn: psycopg.Connection[Any], ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = conn.execute("SELECT DISTINCT ON (user_id) user_id, score FROM customer.feedback "
                        "WHERE kind = 'csat' AND user_id = ANY(%s) ORDER BY user_id, created_at DESC, id DESC",
                        (ids,)).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _summary(m: membership.Membership, at: datetime) -> MembershipSummary | None:
    found = membership.summary(m, at)
    return MembershipSummary(**found) if found is not None else None


def is_customer(conn: psycopg.Connection[Any], user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM auth.users WHERE id = %s AND role = 'USER' AND status <> 'deleted'",
                        (user_id,)).fetchone() is not None


def listing(conn: psycopg.Connection[Any], *, view: str, query: str | None, limit: int, offset: int,
            at: datetime | None = None) -> CustomerList:
    """The customers of a view, newest accounts first, with how many each view holds."""
    if view not in VIEWS:
        raise CustomerError(422, "unknown_view", "no such view")
    moment = at or datetime.now(UTC)
    accounts = _accounts(conn)
    ids = [int(a["id"]) for a in accounts]
    members = membership.of_many(conn, accounts, moment)
    tickets = _open_tickets(conn, ids)
    subjects = _subjects(ids)
    errors = _errors_24h(conn, subjects, moment)
    active7 = _active_days(conn, subjects, moment, 7)
    csat = _last_csat(conn, ids)

    rows: list[tuple[CustomerRow, Facts]] = []
    for a in accounts:
        uid = int(a["id"])
        m = members[uid]
        facts = Facts(status=a["status"], created_at=a["created_at"], last_seen_at=a["last_seen_at"],
                      ends_at=m.ends_at, grace_until=m.grace_until, suspended=m.state == "suspended",
                      open_tickets=tickets.get(uid, 0), errors_24h=errors.get(uid, 0))
        rows.append((CustomerRow(
            id=uid, email=a["email"], display_name=a["display_name"], status=a["status"],
            created_at=a["created_at"], last_seen_at=a["last_seen_at"], membership=_summary(m, moment),
            open_tickets=facts.open_tickets, errors_24h=facts.errors_24h, active_days_7=active7.get(uid, 0),
            last_csat=csat.get(uid)), facts))

    counts = [CustomerViewCount(view=v, count=sum(1 for _, f in rows if in_view(v, f, moment)))  # type: ignore[arg-type]
              for v in VIEWS]
    needle = (query or "").strip().lower()
    chosen = [r for r, f in rows if in_view(view, f, moment)
              and (not needle or needle in r.email.lower() or needle in (r.display_name or "").lower())]
    return CustomerList(view=view, items=chosen[offset:offset + limit], total=len(chosen),  # type: ignore[arg-type]
                        views=counts, limit=limit, offset=offset)


# ── one card ──────────────────────────────────────────────────────────────────────────

def _notes(conn: psycopg.Connection[Any], user_id: int) -> list[CustomerNote]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT e.id, e.at, a.email AS author, e.detail->>'note' AS note
              FROM auth.audit_events e LEFT JOIN auth.users a ON a.id = e.actor_user_id
             WHERE e.action = %s AND e.target_user_id = %s ORDER BY e.at DESC, e.id DESC LIMIT 50
        """, (NOTE_ACTION, user_id))
        return [CustomerNote(id=r["id"], at=r["at"], author=r["author"], note=str(r["note"] or "")) for r in cur]


def _notifications(conn: psycopg.Connection[Any], user_id: int, at: datetime) -> CustomerNotifications:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT email_status, email_status_at, email_off FROM customer.preferences WHERE user_id = %s",
                    (user_id,))
        prefs = cur.fetchone() or {"email_status": "ok", "email_status_at": None, "email_off": []}
        devices = [CustomerDevice(**r) for r in cur.execute(push.DEVICES_SQL, (user_id,)).fetchall()]
        cur.execute("SELECT status, count(*) AS n FROM customer.messages_outbox WHERE user_id = %s "
                    "AND created_at >= %s GROUP BY status", (user_id, at - timedelta(days=30)))
        by_status = {r["status"]: int(r["n"]) for r in cur.fetchall()}
    return CustomerNotifications(
        email_status=prefs["email_status"], email_status_at=prefs["email_status_at"],
        email_off=sorted(prefs["email_off"] or []), push_off=sorted(push.push_off(conn, user_id)), devices=devices,
        sent_30=by_status.get("sent", 0), failed_30=by_status.get("failed", 0),
        bounced_30=by_status.get("bounced", 0) + by_status.get("complained", 0),
        suppressed_30=by_status.get("suppressed", 0))


def _usage(conn: psycopg.Connection[Any], user_id: int, at: datetime) -> CustomerUsage:
    subject = crypto.product_id(user_id)
    saved = conn.execute("SELECT count(*) FROM picks.user_picks WHERE user_id = %s", (user_id,)).fetchone()
    parlays = conn.execute("SELECT count(*) FROM picks.user_parlays WHERE user_id = %s", (user_id,)).fetchone()
    picks_saved = int(saved[0]) if saved else 0
    parlays_saved = int(parlays[0]) if parlays else 0
    if subject is None:
        return CustomerUsage(active_days_7=0, active_days_30=0, matches_viewed_30=0, picks_opened_30=0,
                             picks_saved=picks_saved, parlays_saved=parlays_saved, errors_24h=0, measured=False)
    subjects = {user_id: subject}
    first = events.bogota_day(at) - timedelta(days=29)
    row = conn.execute("""
        SELECT coalesce(sum((counts->>'match_opened')::int), 0), coalesce(sum((counts->>'pick_opened')::int), 0)
          FROM customer.activity_daily WHERE subject = %s AND day >= %s
    """, (subject, first)).fetchone()
    days30 = _active_days(conn, subjects, at, 30).get(user_id, 0)
    days7 = _active_days(conn, subjects, at, 7).get(user_id, 0)
    return CustomerUsage(
        active_days_7=days7, active_days_30=days30, matches_viewed_30=int(row[0]) if row else 0,
        picks_opened_30=int(row[1]) if row else 0, picks_saved=picks_saved, parlays_saved=parlays_saved,
        errors_24h=_errors_24h(conn, subjects, at).get(user_id, 0), measured=True)


def _feedback(conn: psycopg.Connection[Any], user_id: int) -> CustomerFeedbackSummary:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT kind, score, helpful, subject, created_at FROM customer.feedback
             WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT 200
        """, (user_id,))
        rows = list(cur.fetchall())
    csat = [r for r in rows if r["kind"] == "csat"]
    return CustomerFeedbackSummary(
        last_csat=int(csat[0]["score"]) if csat else None, last_csat_at=csat[0]["created_at"] if csat else None,
        survey_answers=len(csat),
        helpful_yes=sum(1 for r in rows if r["kind"] == "helpful" and r["helpful"]),
        helpful_no=sum(1 for r in rows if r["kind"] == "helpful" and r["helpful"] is False),
        recent=[CustomerFeedback(kind=r["kind"], score=r["score"], helpful=r["helpful"], subject=r["subject"],
                                 created_at=r["created_at"]) for r in rows[:5]])


def card(conn: psycopg.Connection[Any], user_id: int, *, at: datetime | None = None) -> Customer:
    """One reader's card (404 ``not_found`` for an account that is not a reader: the owner's own is not a customer)."""
    moment = at or datetime.now(UTC)
    found = _accounts(conn, user_id)
    if not found:
        raise CustomerError(404, "not_found", "no such customer")
    a = found[0]
    m = membership.of(conn, user_id, email=str(a["email"]), super_admin=False)
    sessions = conn.execute("SELECT count(*) FROM auth.sessions WHERE user_id = %s AND revoked_at IS NULL "
                            "AND expires_at > %s", (user_id, moment)).fetchone()
    latest = consents.latest(conn, user_id)
    tickets = support.owner_tickets_of(conn, user_id)
    requests = [t for t in tickets if t.kind != "support" and t.status != "closed"]
    return Customer(
        identity=CustomerIdentity(
            id=user_id, email=a["email"], display_name=a["display_name"], status=a["status"],
            language=a["language"], timezone=a["timezone"], created_at=a["created_at"],
            last_login_at=a["last_login_at"], last_seen_at=a["last_seen_at"], mfa_enabled=bool(a["mfa_enabled"]),
            open_sessions=int(sessions[0]) if sessions else 0),
        membership=_summary(m, moment), suspended_reason=m.suspended_reason,
        usage=_usage(conn, user_id, moment), notifications=_notifications(conn, user_id, moment),
        consents=[CustomerConsent(kind=c.kind, granted=c.granted, version=c.version, at=c.at)
                  for c in sorted(latest.values(), key=lambda c: c.kind)],
        consents_due=consents.due(conn, user_id) if consents.gate_enabled() else [],
        tickets=[CustomerTicket(id=t.id, kind=t.kind, category=t.category, status=t.status, opened_at=t.opened_at,
                                closed_at=t.closed_at, messages=len(t.messages), late=t.late(moment))
                 for t in tickets[:20]],
        feedback=_feedback(conn, user_id), notes=_notes(conn, user_id), privacy_requests_open=len(requests))

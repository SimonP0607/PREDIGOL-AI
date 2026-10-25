"""A reader's rights over their data (plan UX, A4; plan de seguridad, section 23; Ley 1581 de 2012, arts. 8, 14, 15).

* **Export:** a copy of everything PrediGol keeps about the reader - the account, its sessions and access history,
  the consents, the privacy requests, the picks and parlays they saved - as one JSON document, read only with their
  own id (never a join that could bring another account's row). The API asks for the password first and allows
  ``EXPORTS_PER_DAY`` a day.
* **Requests:** a query (10 business days, extendable by 5), a claim - a correction or an update - or a deletion
  (15, extendable by 8), as a ticket of ``customer.support_tickets`` with its legal deadline in Colombian business
  days, counted from the day after it arrives in Bogotá. One open request of each kind at a time. The owner answers
  from the Admin Console; the deletion itself (anonymisation) is A7's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from fbi.customer import consents, workdays
from fbi.customer.db import CustomerError, write_connection

BOGOTA = ZoneInfo("America/Bogota")
EXPORT_FORMAT = "predigol-export/1"
EXPORTS_PER_DAY = 3
RequestKind = Literal["privacy_query", "privacy_claim", "privacy_deletion"]
DEADLINES: dict[str, tuple[int, int]] = {
    "privacy_query": (workdays.QUERY_DAYS, workdays.QUERY_EXTENSION),
    "privacy_claim": (workdays.CLAIM_DAYS, workdays.CLAIM_EXTENSION),
    "privacy_deletion": (workdays.CLAIM_DAYS, workdays.CLAIM_EXTENSION),
}
MAX_MESSAGE = 4000


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    author: str
    body: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    user_id: int
    kind: str
    status: str
    opened_at: datetime
    due_on: date | None
    extended_to: date | None
    closed_at: datetime | None
    messages: list[Message] = field(default_factory=list)
    email: str | None = None
    """Only on the owner's list (the Admin Console), never on the reader's own."""

    @property
    def deadline(self) -> date | None:
        return self.extended_to or self.due_on


def bogota_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(BOGOTA).date()


def deadline_for(kind: str, opened: date) -> date:
    days, _ = DEADLINES[kind]
    return workdays.add_business_days(opened, days)


def _all(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _tickets(conn: psycopg.Connection[Any], where: str, params: tuple[Any, ...], *,
             with_email: bool = False) -> list[Ticket]:
    email = ", u.email" if with_email else ""
    join = " JOIN auth.users u ON u.id = t.user_id" if with_email else ""
    rows = _all(conn, f"""
        SELECT t.id, t.user_id, t.kind, t.status, t.opened_at, t.due_on, t.extended_to, t.closed_at{email}
        FROM customer.support_tickets t{join} WHERE {where}
        ORDER BY (t.status = 'closed'), coalesce(t.extended_to, t.due_on) NULLS LAST, t.opened_at DESC, t.id DESC
        LIMIT 200
    """, params)
    ids = [r["id"] for r in rows]
    messages: dict[int, list[Message]] = {i: [] for i in ids}
    if ids:
        for m in _all(conn, "SELECT id, ticket_id, author, body, at FROM customer.ticket_messages "
                            "WHERE ticket_id = ANY(%s) ORDER BY at, id", (ids,)):
            messages[m["ticket_id"]].append(Message(id=m["id"], author=m["author"], body=m["body"], at=m["at"]))
    return [Ticket(**r, messages=messages[r["id"]]) for r in rows]


def requests_of(conn: psycopg.Connection[Any], user_id: int) -> list[Ticket]:
    """The reader's own privacy requests, open first by deadline."""
    return _tickets(conn, "t.user_id = %s AND t.kind LIKE 'privacy\\_%%'", (user_id,))


def open_request(user_id: int, kind: RequestKind, message: str, *, now: datetime | None = None) -> Ticket:
    if kind not in DEADLINES:
        raise CustomerError(422, "unknown_request", f"no request {kind!r}")
    body = message.strip()
    if not body or len(body) > MAX_MESSAGE:
        raise CustomerError(422, "invalid_message", f"a message of 1 to {MAX_MESSAGE} characters")
    opened = now or datetime.now(UTC)
    due_on = deadline_for(kind, bogota_today(opened))
    with write_connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (consents.LOCK_KEY + 1, user_id))
        existing = _tickets(conn, "t.user_id = %s AND t.kind = %s AND t.status <> 'closed'", (user_id, kind))
        if existing:
            raise CustomerError(409, "request_open", "a request of this kind is already open")
        row = conn.execute("""
            INSERT INTO customer.support_tickets (user_id, kind, opened_at, due_on) VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (user_id, kind, opened, due_on)).fetchone()
        assert row is not None
        conn.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, at) VALUES (%s, 'customer', %s, %s)",
                     (row[0], body, opened))
        return _tickets(conn, "t.id = %s", (row[0],))[0]


# ── the owner (Admin Console) ─────────────────────────────────────────────────────────

def all_requests(conn: psycopg.Connection[Any], *, status: Literal["open", "all"] = "open") -> list[Ticket]:
    where = "t.kind LIKE 'privacy\\_%%'" + (" AND t.status <> 'closed'" if status == "open" else "")
    return _tickets(conn, where, (), with_email=True)


def answer(ticket_id: int, *, body: str, status: Literal["open", "answered", "closed"],
           extend: bool = False, now: datetime | None = None) -> Ticket:
    """The owner's message on a request; it may also change the status or use the one extension the law allows
    (the message says why and until when, as the law asks)."""
    text = body.strip()
    if not text or len(text) > MAX_MESSAGE:
        raise CustomerError(422, "invalid_message", f"a message of 1 to {MAX_MESSAGE} characters")
    at = now or datetime.now(UTC)
    with write_connection() as conn:
        found = _tickets(conn, "t.id = %s AND t.kind LIKE 'privacy\\_%%'", (ticket_id,))
        if not found:
            raise CustomerError(404, "not_found", "no such request")
        ticket = found[0]
        if ticket.status == "closed":
            raise CustomerError(409, "request_closed", "the request is closed")
        extended_to = ticket.extended_to
        if extend:
            if ticket.extended_to is not None or ticket.due_on is None:
                raise CustomerError(409, "already_extended", "the law allows one extension")
            extended_to = workdays.add_business_days(ticket.due_on, DEADLINES[ticket.kind][1])
        conn.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, at) VALUES (%s, 'owner', %s, %s)",
                     (ticket_id, text, at))
        conn.execute("""
            UPDATE customer.support_tickets SET status = %s, extended_to = %s,
                   closed_at = CASE WHEN %s = 'closed' THEN %s ELSE NULL END
            WHERE id = %s
        """, (status, extended_to, status, at, ticket_id))
        return _tickets(conn, "t.id = %s", (ticket_id,), with_email=True)[0]


# ── export ───────────────────────────────────────────────────────────────────────────

def _iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value if value is None or isinstance(value, str | int | float | bool) else str(value)


def export(conn: psycopg.Connection[Any], user_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Everything PrediGol keeps about one reader, read by their id alone. Never the password's hash, the second
    factor's secret, a session's token, the account's role (plan UX, A1) or what another person did with their IP."""
    account = _all(conn, """
        SELECT id, email, display_name, status, language, timezone, created_at, last_login_at, password_changed_at,
               totp_enabled_at IS NOT NULL AS second_factor, totp_enabled_at AS second_factor_since
        FROM auth.users WHERE id = %s
    """, (user_id,))
    if not account:
        raise CustomerError(404, "not_found", "no such account")
    sessions = _all(conn, """
        SELECT created_at, last_seen_at, expires_at, revoked_at, revoked_reason, ip, user_agent
        FROM auth.sessions WHERE user_id = %s ORDER BY created_at DESC
    """, (user_id,))
    # An action someone else took on the account (the owner changing a role) is the reader's data; that person's
    # address and browser are not.
    access = _all(conn, """
        SELECT at, action,
               CASE WHEN actor_user_id IS NULL OR actor_user_id = target_user_id THEN ip END AS ip,
               CASE WHEN actor_user_id IS NULL OR actor_user_id = target_user_id THEN detail->>'user_agent' END
                   AS user_agent,
               detail->>'reason' AS reason
        FROM auth.audit_events WHERE target_user_id = %s ORDER BY at DESC, id DESC
    """, (user_id,))
    consent_rows = [
        {"kind": c.kind, "granted": c.granted, "document": c.document, "version": c.version, "sha256": c.sha256,
         "locale": c.locale, "statement": c.statement, "source": c.source, "at": c.at}
        for c in consents.history(conn, user_id, limit=10_000)
    ]
    tickets = [
        {"kind": t.kind, "status": t.status, "opened_at": t.opened_at, "due_on": t.due_on,
         "extended_to": t.extended_to, "closed_at": t.closed_at,
         "messages": [{"author": m.author, "body": m.body, "at": m.at} for m in t.messages]}
        for t in requests_of(conn, user_id)
    ]
    picks = _all(conn, """
        SELECT fixture_id, market_key, selection, line, origin, odds, bookmaker, price_at, user_odds, snapshot,
               saved_at, status, profit_units, settled_at
        FROM picks.user_picks WHERE user_id = %s ORDER BY saved_at DESC
    """, (user_id,))
    parlays = _all(conn, """
        SELECT id, name, created_at, combined_odds, validation, status, profit_units, settled_at
        FROM picks.user_parlays WHERE user_id = %s ORDER BY created_at DESC
    """, (user_id,))
    legs: dict[int, list[dict[str, Any]]] = {p["id"]: [] for p in parlays}
    if legs:
        for leg in _all(conn, """
            SELECT l.user_parlay_id, l.leg_no, l.fixture_id, l.market_key, l.selection, l.line, l.odds, l.snapshot,
                   l.status, l.settled_at
            FROM picks.user_parlay_legs l JOIN picks.user_parlays p ON p.id = l.user_parlay_id
            WHERE p.user_id = %s ORDER BY l.user_parlay_id, l.leg_no
        """, (user_id,)):
            legs[leg.pop("user_parlay_id")].append(leg)
    parlay_rows = [{**{k: v for k, v in p.items() if k != "id"}, "legs": legs[p["id"]]} for p in parlays]
    document: dict[str, Any] = _iso({
        "format": EXPORT_FORMAT,
        "generated_at": now or datetime.now(UTC),
        "account": account[0],
        "sessions": sessions,
        "access_history": access,
        "consents": consent_rows,
        "privacy_requests": tickets,
        "saved_picks": picks,
        "saved_parlays": parlay_rows,
    })
    return document

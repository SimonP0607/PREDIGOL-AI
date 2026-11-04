"""A reader's questions to PrediGol and the owner's inbox (plan UX, A14; section 32 of the plan).

With 10 to 200 readers support is human: a help centre, tickets that arrive with their context, and WhatsApp for what
is urgent. A ticket is a row of ``customer.support_tickets`` of kind ``support`` (A4 built the table for the privacy
requests, which keep their own path: ``fbi.customer.privacy``) and its messages.

    category    what the reader chose; it sets the priority and the target of the first answer (section 32):
                    access       urgent  the same day (opened from 20:00 in Bogotá: the next day by noon), and the owner
                                         is told at once (``ticket_new``)
                    account      high    24 h          technical   high    24 h          complaint   high   24 h
                    wrong_data   medium  48 h          suggestion  low     a week
                A privacy question goes to the privacy requests, with their legal deadline (``fbi.customer.privacy``).
    context     what the web attaches so the owner does not have to ask (``clean_context``): the screen's route
                without its query, the request id of the last error, the web's version, the device's class, the installed
                app or a tab, and the match of a «wrong data» report. Never a password, a token, an address, what a form
                held or another person's data; at most 2 KB, fixed once written.
    status      open: waiting for PrediGol - answered: PrediGol answered - closed. A reader's message opens it again; a
                closed ticket stays closed (another one is opened).
    effort      «¿Qué tan fácil fue resolverlo?», 1 to 5, optional and once, on a closed ticket.
    channel     where a message was said: written in PrediGol (``web``), or noted by the owner from WhatsApp or an e-mail
                so the thread stays whole.
    e-mail      the receipt and each answer written in PrediGol queue a message in the same transaction
                (``fbi.messaging.outbox``): the number, the category and the moment of the promised answer - never the
                words of either side, which the reader reads in PrediGol (as the privacy requests, A5). The reader may
                switch support e-mails off (A5: an optional category).

Limits on free text (section 32): 2,000 characters a message from a reader, no attachments in block A, at most
``MAX_OPEN`` open tickets and ``MAX_PER_DAY`` new ones in 24 hours per reader, ``MAX_MESSAGES`` messages a thread.
``FBI_SUPPORT=0`` takes the tickets away without a deploy (the API recreated): the help centre, its contact (WhatsApp, a
reply address) and the privacy requests stay.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.core import clock
from fbi.core.env import environment
from fbi.customer import events
from fbi.customer.db import CustomerError, write_connection
from fbi.messaging import outbox

Category = Literal["access", "account", "technical", "wrong_data", "suggestion", "complaint"]
Priority = Literal["urgent", "high", "medium", "low"]
Status = Literal["open", "answered", "closed"]
Channel = Literal["web", "email", "whatsapp"]
InboxStatus = Literal["open", "waiting", "answered", "closed", "all"]

SWITCH: Final = "FBI_SUPPORT"
_ON: Final = frozenset({"1", "on", "true", "yes"})
BOGOTA: Final = events.BOGOTA


@dataclass(frozen=True, slots=True)
class Rule:
    priority: Priority
    target: timedelta | None
    """How soon the first answer is due; None: the same day (section 32: «el mismo día»)."""


RULES: Final[dict[str, Rule]] = {
    "access": Rule("urgent", None),
    "account": Rule("high", timedelta(hours=24)),
    "technical": Rule("high", timedelta(hours=24)),
    "wrong_data": Rule("medium", timedelta(hours=48)),
    "suggestion": Rule("low", timedelta(days=7)),
    "complaint": Rule("high", timedelta(hours=24)),
}
CATEGORIES: Final[tuple[str, ...]] = tuple(RULES)
"""The order the reader is offered them in."""
URGENT: Final = frozenset(c for c, r in RULES.items() if r.priority == "urgent")
PRIORITY_RANK: Final[dict[str, int]] = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
PRIVACY_PRIORITY: Final[Priority] = "high"
"""A privacy request (section 32): high, with its legal deadline instead of a target in hours."""
LATE_HOUR: Final = 20
"""An urgent ticket opened from this hour (Bogotá) is due the next day by ``NEXT_DAY_BY``: «the same day» at 23:50 is no
promise anyone keeps."""
NEXT_DAY_BY: Final = time(12, 0)
SAME_DAY_BY: Final = time(23, 59)
"""«The same day» said as a moment a person reads: 23:59 of that day in Bogotá (not «00:00 of the next one»)."""

MAX_TEXT: Final = 2000
"""A reader's message (section 32: «el texto libre tiene un máximo de 2.000 caracteres»)."""
MAX_OWNER_TEXT: Final = 4000
"""The owner's message: what the table holds (``customer.ticket_messages.body``), as for a privacy request."""
MAX_OPEN: Final = 3
MAX_PER_DAY: Final = 10
MAX_MESSAGES: Final = 50
MAX_CONTEXT_BYTES: Final = 2048
EFFORT: Final = range(1, 6)

CONTEXT_KEYS: Final = ("route", "request_id", "web_version", "device", "pwa", "match_id")
DEVICES: Final = ("phone", "tablet", "desktop")
ROUTE = re.compile(r"/[A-Za-z0-9/_.$-]{0,199}")
REQUEST_ID = re.compile(r"[A-Za-z0-9]{1,32}")
VERSION = re.compile(r"[A-Za-z0-9._+-]{1,40}")
LINK_PAGES: Final = ("/activate", "/reset-password", "/unlock")
"""The pages of the one-use links (plan UX, A7): only the page is kept, never what follows it."""

LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('customer.support'), %s)"


def support_on() -> bool:
    """``FBI_SUPPORT``: ON while the line is absent or empty (the plan approved it); =0 takes the tickets away without a
    deploy; a value it cannot read counts as off."""
    raw = environment().get(SWITCH)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _ON


# ── the rules ─────────────────────────────────────────────────────────────────────────

def priority_of(category: str) -> Priority:
    return PRIVACY_PRIORITY if category == "privacy" else RULES[category].priority


def respond_by(category: str, opened_at: datetime) -> datetime:
    """When the first answer to a support ticket is due (UTC)."""
    rule = RULES[category]
    if rule.target is not None:
        return opened_at + rule.target
    local = opened_at.astimezone(BOGOTA)
    if local.hour >= LATE_HOUR:
        return datetime.combine(local.date() + timedelta(days=1), NEXT_DAY_BY, tzinfo=BOGOTA).astimezone(UTC)
    return datetime.combine(local.date(), SAME_DAY_BY, tzinfo=BOGOTA).astimezone(UTC)


def _text(raw: str, limit: int) -> str:
    text = raw.strip()
    if not text or len(text) > limit:
        raise CustomerError(422, "invalid_message", f"a message of 1 to {limit} characters")
    return text


def clean_context(raw: Mapping[str, object] | None) -> dict[str, Any] | None:
    """What the web attached, checked again here: only the known keys, each in its shape. The route keeps no query
    (the page sends none; one here is refused) and a one-use link's page keeps only its name."""
    if not raw:
        return None
    unknown = sorted(set(raw) - set(CONTEXT_KEYS))
    if unknown:
        raise CustomerError(422, "invalid_context", f"unknown context keys: {unknown}")
    out: dict[str, Any] = {}
    route = raw.get("route")
    if route is not None:
        if not isinstance(route, str) or not ROUTE.fullmatch(route):
            raise CustomerError(422, "invalid_context", "a route is a path of at most 200 characters, no query")
        out["route"] = next((p for p in LINK_PAGES if route == p or route.startswith(p + "/")), route)
    for key, pattern in (("request_id", REQUEST_ID), ("web_version", VERSION)):
        value = raw.get(key)
        if value is not None:
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise CustomerError(422, "invalid_context", f"{key} has the wrong shape")
            out[key] = value
    device = raw.get("device")
    if device is not None:
        if device not in DEVICES:
            raise CustomerError(422, "invalid_context", f"a device is one of {DEVICES}")
        out["device"] = device
    pwa = raw.get("pwa")
    if pwa is not None:
        if not isinstance(pwa, bool):
            raise CustomerError(422, "invalid_context", "pwa is true or false")
        out["pwa"] = pwa
    match_id = raw.get("match_id")
    if match_id is not None:
        if isinstance(match_id, bool) or not isinstance(match_id, int) or not 1 <= match_id < 10**12:
            raise CustomerError(422, "invalid_context", "a match is a positive number")
        out["match_id"] = match_id
    if len(json.dumps(out).encode()) > MAX_CONTEXT_BYTES:
        raise CustomerError(422, "invalid_context", f"a context of at most {MAX_CONTEXT_BYTES} bytes")
    return out or None


# ── reading ───────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Message:
    id: int
    author: str
    body: str
    at: datetime
    channel: str


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    user_id: int
    kind: str
    category: str
    status: str
    opened_at: datetime
    due_on: date | None
    extended_to: date | None
    closed_at: datetime | None
    context: dict[str, Any] | None
    effort: int | None
    messages: list[Message] = field(default_factory=list)
    email: str | None = None
    """The owner's inbox only, never the reader's own view."""
    display_name: str | None = None
    account_status: str | None = None
    at_risk: bool = False
    """The owner's inbox only: the reader is AT RISK in the newest day of the lifecycle (plan UX, B11)."""

    @property
    def priority(self) -> Priority:
        return priority_of(self.category)

    @property
    def respond_by(self) -> datetime | None:
        """A support ticket's target for its first answer; None for a privacy request (its deadline is a day)."""
        return respond_by(self.category, self.opened_at) if self.kind == "support" else None

    @property
    def deadline(self) -> date | None:
        return self.extended_to or self.due_on

    @property
    def first_answer_at(self) -> datetime | None:
        return next((m.at for m in self.messages if m.author == "owner"), None)

    @property
    def waiting(self) -> bool:
        """Waiting for PrediGol."""
        return self.status == "open"

    def late(self, at: datetime) -> bool:
        """A support ticket past the target of its first answer with none yet; a privacy request past its deadline."""
        if self.status == "closed":
            return False
        if self.kind != "support":
            return self.deadline is not None and self.deadline < events.bogota_day(at)
        due = self.respond_by
        return self.first_answer_at is None and due is not None and due < at


SELECT_SQL = """
    SELECT t.id, t.user_id, t.kind, t.category, t.status, t.opened_at, t.due_on, t.extended_to, t.closed_at,
           t.context, t.effort{extra}
      FROM customer.support_tickets t{join}
     WHERE {where}
     ORDER BY {order}
     LIMIT %s
"""
AT_RISK_SQL = ("EXISTS (SELECT 1 FROM customer.lifecycle_snapshots l WHERE l.user_id = t.user_id "
               "AND l.state = 'at_risk' AND l.day = (SELECT max(day) FROM customer.lifecycle_snapshots))")
"""Whether the ticket's reader is at risk on the newest day the lifecycle computed (plan UX, B11)."""
QUEUE_ORDER = ("(t.status = 'closed'), (t.status <> 'open'), CASE WHEN t.category = 'access' THEN 0 "
               "WHEN t.category = 'wrong_data' THEN 2 WHEN t.category = 'suggestion' THEN 3 ELSE 1 END, "
               f"(NOT {AT_RISK_SQL}), t.opened_at, t.id")
"""Waiting first, then by priority, then the readers at risk (B11), then the oldest: the order the owner answers in."""
READER_ORDER = "(t.status = 'closed'), t.opened_at DESC, t.id DESC"


def _rows(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _tickets(conn: psycopg.Connection[Any], where: str, params: tuple[Any, ...], *, owner: bool = False,
             order: str = READER_ORDER, limit: int = 200) -> list[Ticket]:
    extra = f", u.email, u.display_name, u.status AS account_status, {AT_RISK_SQL} AS at_risk" if owner else ""
    join = " JOIN auth.users u ON u.id = t.user_id" if owner else ""
    rows = _rows(conn, SELECT_SQL.format(extra=extra, join=join, where=where, order=order), (*params, limit))
    ids = [r["id"] for r in rows]
    messages: dict[int, list[Message]] = {i: [] for i in ids}
    if ids:
        for m in _rows(conn, "SELECT id, ticket_id, author, body, at, channel FROM customer.ticket_messages "
                             "WHERE ticket_id = ANY(%s) ORDER BY at, id", (ids,)):
            messages[m["ticket_id"]].append(Message(id=m["id"], author=m["author"], body=m["body"], at=m["at"],
                                                    channel=m["channel"]))
    return [Ticket(**r, messages=messages[r["id"]]) for r in rows]


def tickets_of(conn: psycopg.Connection[Any], user_id: int) -> list[Ticket]:
    """The reader's own support tickets, open first, newest first."""
    return _tickets(conn, "t.user_id = %s AND t.kind = 'support'", (user_id,))


def ticket_of(conn: psycopg.Connection[Any], user_id: int, ticket_id: int) -> Ticket:
    """One of the reader's own tickets; another reader's is «not found», the same as one that does not exist."""
    found = _tickets(conn, "t.id = %s AND t.user_id = %s AND t.kind = 'support'", (ticket_id, user_id))
    if not found:
        raise CustomerError(404, "not_found", "no such ticket")
    return found[0]


# ── the reader ────────────────────────────────────────────────────────────────────────

def _off() -> CustomerError:
    return CustomerError(404, "not_available", "support tickets are switched off (FBI_SUPPORT)")


def _locked(conn: psycopg.Connection[Any], user_id: int, ticket_id: int) -> Ticket:
    row = conn.execute("SELECT 1 FROM customer.support_tickets WHERE id = %s AND user_id = %s AND kind = 'support' "
                       "FOR UPDATE", (ticket_id, user_id)).fetchone()
    if row is None:
        raise CustomerError(404, "not_found", "no such ticket")
    return ticket_of(conn, user_id, ticket_id)


def open_ticket(user_id: int, category: str, text: str, context: Mapping[str, object] | None = None, *,
                now: datetime | None = None) -> Ticket:
    """A reader's ticket with its context, its first message, the receipt by e-mail and the product event - one
    transaction."""
    if not support_on():
        raise _off()
    if category == "privacy":
        raise CustomerError(422, "use_privacy_request", "a privacy question is a privacy request, with its deadline")
    if category not in RULES:
        raise CustomerError(422, "unknown_category", f"a category is one of {CATEGORIES}")
    body = _text(text, MAX_TEXT)
    ctx = clean_context(context)
    opened = now or clock.now()
    with write_connection() as conn:
        conn.execute(LOCK_SQL, (user_id % 2**31,))
        row = conn.execute("""
            SELECT count(*) FILTER (WHERE status <> 'closed'), count(*) FILTER (WHERE opened_at > %s)
              FROM customer.support_tickets WHERE user_id = %s AND kind = 'support'
        """, (opened - timedelta(hours=24), user_id)).fetchone()
        open_now, today = (int(row[0]), int(row[1])) if row else (0, 0)
        if open_now >= MAX_OPEN:
            raise CustomerError(409, "too_many_open", f"at most {MAX_OPEN} open tickets: add to one of them")
        if today >= MAX_PER_DAY:
            raise CustomerError(429, "too_many_tickets", f"at most {MAX_PER_DAY} new tickets in 24 hours")
        created = conn.execute("""
            INSERT INTO customer.support_tickets (user_id, kind, category, context, opened_at)
            VALUES (%s, 'support', %s, %s, %s) RETURNING id
        """, (user_id, category, Jsonb(ctx) if ctx else None, opened)).fetchone()
        assert created is not None
        ticket_id = int(created[0])
        conn.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, at, channel) "
                     "VALUES (%s, 'customer', %s, %s, 'web')", (ticket_id, body, opened))
        outbox.enqueue(conn, user_id=user_id, template="support_ticket_received",
                       params={"ticket": str(ticket_id), "category": category,
                               "by": respond_by(category, opened).isoformat()},
                       dedup_key=f"support_ticket_received:{ticket_id}")
        events.record_server(conn, user_id, "ticket_created", {"kind": category})
        return ticket_of(conn, user_id, ticket_id)


def reply(user_id: int, ticket_id: int, text: str, *, now: datetime | None = None) -> Ticket:
    """The reader's message on their open ticket: it waits for PrediGol again."""
    if not support_on():
        raise _off()
    body = _text(text, MAX_TEXT)
    at = now or clock.now()
    with write_connection() as conn:
        ticket = _locked(conn, user_id, ticket_id)
        if ticket.status == "closed":
            raise CustomerError(409, "ticket_closed", "the ticket is closed: open another one")
        if len(ticket.messages) >= MAX_MESSAGES:
            raise CustomerError(409, "thread_full", f"a ticket holds {MAX_MESSAGES} messages: open another one")
        conn.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, at, channel) "
                     "VALUES (%s, 'customer', %s, %s, 'web')", (ticket_id, body, at))
        conn.execute("UPDATE customer.support_tickets SET status = 'open' WHERE id = %s AND status <> 'open'",
                     (ticket_id,))
        return ticket_of(conn, user_id, ticket_id)


def _effort(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or value not in EFFORT:
        raise CustomerError(422, "invalid_effort", "an answer from 1 (very hard) to 5 (very easy)")
    return value


def close(user_id: int, ticket_id: int, *, effort: int | None = None, now: datetime | None = None) -> Ticket:
    """«Ya está resuelto»: the reader closes their ticket, with how easy it was if they want to say."""
    if not support_on():
        raise _off()
    score = _effort(effort)
    at = now or clock.now()
    with write_connection() as conn:
        ticket = _locked(conn, user_id, ticket_id)
        if ticket.status == "closed":
            raise CustomerError(409, "ticket_closed", "the ticket is already closed")
        conn.execute("UPDATE customer.support_tickets SET status = 'closed', closed_at = %s, effort = %s WHERE id = %s",
                     (at, score, ticket_id))
        return ticket_of(conn, user_id, ticket_id)


def rate(user_id: int, ticket_id: int, effort: int) -> Ticket:
    """How easy it was, once, on a closed ticket."""
    score = _effort(effort)
    with write_connection() as conn:
        ticket = _locked(conn, user_id, ticket_id)
        if ticket.status != "closed":
            raise CustomerError(409, "not_closed", "the question comes once the ticket is closed")
        if ticket.effort is not None:
            raise CustomerError(409, "already_rated", "it was answered already")
        conn.execute("UPDATE customer.support_tickets SET effort = %s WHERE id = %s", (score, ticket_id))
        return ticket_of(conn, user_id, ticket_id)


# ── the owner (Admin Console) ─────────────────────────────────────────────────────────

PRIORITY_CATEGORIES: Final[dict[str, tuple[str, ...]]] = {
    p: tuple(c for c in (*CATEGORIES, "privacy") if priority_of(c) == p) for p in PRIORITY_RANK
}


def inbox(conn: psycopg.Connection[Any], *, status: InboxStatus = "open", category: str | None = None,
          priority: str | None = None, limit: int = 200) -> list[Ticket]:
    """Every ticket and privacy request for the owner, with the reader's address: waiting first, by priority, the
    oldest first (closed ones: the newest closed first)."""
    where = ["TRUE"]
    params: list[Any] = []
    if status == "open":
        where.append("t.status <> 'closed'")
    elif status in ("waiting", "answered", "closed"):
        where.append("t.status = %s")
        params.append("open" if status == "waiting" else status)
    if category is not None:
        if category not in (*CATEGORIES, "privacy"):
            raise CustomerError(422, "unknown_category", "no such category")
        where.append("t.category = %s")
        params.append(category)
    if priority is not None:
        if priority not in PRIORITY_RANK:
            raise CustomerError(422, "unknown_priority", "no such priority")
        where.append("t.category = ANY(%s)")
        params.append(list(PRIORITY_CATEGORIES[priority]))
    order = "t.closed_at DESC, t.id DESC" if status == "closed" else QUEUE_ORDER
    return _tickets(conn, " AND ".join(where), tuple(params), owner=True, order=order, limit=limit)


def counts(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, int]:
    """The inbox's header: open, waiting for PrediGol, late and urgent - over every ticket not closed."""
    live = _tickets(conn, "t.status <> 'closed'", (), owner=True, order=QUEUE_ORDER, limit=10_000)
    return {
        "open": len(live),
        "waiting": sum(1 for t in live if t.waiting),
        "late": sum(1 for t in live if t.late(at)),
        "urgent": sum(1 for t in live if t.waiting and t.priority == "urgent"),
    }


def owner_tickets_of(conn: psycopg.Connection[Any], user_id: int, *, limit: int = 50) -> list[Ticket]:
    """Every ticket and privacy request of one reader, for the owner's card (plan UX, B10): open first, newest first."""
    return _tickets(conn, "t.user_id = %s", (user_id,), owner=True, order=READER_ORDER, limit=limit)


def owner_ticket(conn: psycopg.Connection[Any], ticket_id: int) -> Ticket:
    found = _tickets(conn, "t.id = %s", (ticket_id,), owner=True)
    if not found:
        raise CustomerError(404, "not_found", "no such ticket")
    return found[0]


def answer(ticket_id: int, *, body: str, status: Status, channel: Channel = "web",
           now: datetime | None = None) -> Ticket:
    """The owner's message on a support ticket - written in PrediGol (the reader is told by e-mail) or noted from a
    talk on WhatsApp or an e-mail (no e-mail then: they talked already) - with its new status. A privacy request is
    answered with its own rules (``fbi.customer.privacy.answer``: the one extension the law allows)."""
    text = _text(body, MAX_OWNER_TEXT)
    if status not in ("open", "answered", "closed"):
        raise CustomerError(422, "invalid_status", "a status is open, answered or closed")
    if channel not in ("web", "email", "whatsapp"):
        raise CustomerError(422, "invalid_channel", "a channel is web, email or whatsapp")
    at = now or clock.now()
    with write_connection() as conn:
        row = conn.execute("SELECT kind, status FROM customer.support_tickets WHERE id = %s FOR UPDATE",
                           (ticket_id,)).fetchone()
        if row is None:
            raise CustomerError(404, "not_found", "no such ticket")
        if row[0] != "support":
            raise CustomerError(409, "privacy_request", "a privacy request is answered with its legal rules")
        ticket = owner_ticket(conn, ticket_id)
        if ticket.status == "closed":
            raise CustomerError(409, "ticket_closed", "the ticket is closed")
        if len(ticket.messages) >= MAX_MESSAGES:
            raise CustomerError(409, "thread_full", f"a ticket holds {MAX_MESSAGES} messages")
        message = conn.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, at, channel) "
                               "VALUES (%s, 'owner', %s, %s, %s) RETURNING id", (ticket_id, text, at, channel)).fetchone()
        assert message is not None
        if channel == "web":
            outbox.enqueue(conn, user_id=ticket.user_id, template="support_ticket_answered",
                           params={"ticket": str(ticket_id), "category": ticket.category},
                           dedup_key=f"support_ticket_answered:{message[0]}")
        conn.execute("UPDATE customer.support_tickets SET status = %s, "
                     "closed_at = CASE WHEN %s = 'closed' THEN %s::timestamptz ELSE NULL END WHERE id = %s",
                     (status, status, at, ticket_id))
        return owner_ticket(conn, ticket_id)


def export_rows(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    """The reader's support tickets for their export (fbi.customer.privacy.export): everything kept, their own words
    and PrediGol's, the context attached and their answer on the effort."""
    return [{"category": t.category, "status": t.status, "opened_at": t.opened_at, "closed_at": t.closed_at,
             "context": t.context, "effort": t.effort,
             "messages": [{"author": m.author, "body": m.body, "at": m.at, "channel": m.channel} for m in t.messages]}
            for t in _tickets(conn, "t.user_id = %s AND t.kind = 'support'", (user_id,), limit=10_000)]

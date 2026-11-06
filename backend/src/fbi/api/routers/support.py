"""A reader's questions to PrediGol and the owner's inbox over HTTP (plan UX, A14; section 32 of the plan).

* ``GET /support/contact`` - public: the WhatsApp number and the reply address, when the owner has given them, for
  whoever cannot sign in (the urgent «access» case of section 32).
* ``GET /me/support`` - the help centre's state: whether tickets are on, the contact, the categories with their priority
  and first answer, and the reader's own tickets with their threads.
* ``POST /me/support/tickets`` - a ticket: a category, up to 2,000 characters and the context the page attaches.
* ``POST /me/support/tickets/{id}/messages`` / ``.../close`` / ``.../effort`` - a reader's message, «Ya está
  resuelto», and how easy it was (once, on a closed ticket).
* ``GET /admin/support`` / ``POST /admin/support/{id}/answer`` - the owner's inbox (support tickets and privacy
  requests together, waiting first by priority) and an answer to a support ticket; a privacy request is answered at
  ``/admin/privacy-requests/{id}/answer`` with its legal rules.

The reader's routes sit outside the consent and the membership gates - a limited reader still reaches Ayuda, as the
plan asks - and only ever read or touch the reader's own tickets: another reader's is «not found».
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.support import (
    AdminInbox,
    AdminTicket,
    InboxStatus,
    Priority,
    SupportCategoryInfo,
    SupportContact,
    SupportContext,
    SupportCounts,
    SupportMessage,
    SupportState,
    SupportTicket,
    TicketAnswerIn,
    TicketCategory,
    TicketCloseIn,
    TicketEffortIn,
    TicketIn,
    TicketReplyIn,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.core.clock import now
from fbi.customer import membership, support
from fbi.customer.db import CustomerError

public_router = APIRouter(prefix="/support", tags=["support"], dependencies=[Depends(same_site_only)])
router = APIRouter(prefix="/me/support", tags=["support"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/support", tags=["admin"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
TicketId = Annotated[int, Path(ge=1)]

FIRST_ANSWER = {None: "same_day", 24: "24h", 48: "48h", 168: "week"}


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _contact() -> SupportContact:
    whatsapp, email = membership.whatsapp(), membership.reply_address()
    return SupportContact(whatsapp=whatsapp, email=email, hours=support.contact_hours(),
                          channels=support.contact_channels(whatsapp=whatsapp, email=email))


def _messages(t: support.Ticket) -> list[SupportMessage]:
    return [SupportMessage(author=m.author, body=m.body, at=m.at, channel=m.channel)  # type: ignore[arg-type]
            for m in t.messages]


def _ticket(t: support.Ticket) -> SupportTicket:
    answered = t.first_answer_at is not None
    return SupportTicket(id=t.id, category=t.category, priority=t.priority,  # type: ignore[arg-type]
                         status=t.status, opened_at=t.opened_at,  # type: ignore[arg-type]
                         respond_by=None if answered or t.status == "closed" else t.respond_by,
                         answered=answered, closed_at=t.closed_at, effort=t.effort, messages=_messages(t))


def _categories() -> list[SupportCategoryInfo]:
    out = []
    for category in support.CATEGORIES:
        rule = support.RULES[category]
        hours = None if rule.target is None else int(rule.target.total_seconds() // 3600)
        out.append(SupportCategoryInfo(category=category, priority=rule.priority,  # type: ignore[arg-type]
                                       first_answer=FIRST_ANSWER[hours]))  # type: ignore[arg-type]
    return out


@public_router.get("/contact", response_model=SupportContact)
def contact() -> SupportContact:
    """How to reach PrediGol without signing in: the WhatsApp Business number and the reply address, when the owner has
    given them (P7, FBI_EMAIL_REPLY_TO); nulls otherwise. Public data by design."""
    return _contact()


@router.get("", response_model=SupportState)
def my_support(conn: Db, principal: App) -> SupportState:
    return SupportState(enabled=support.support_on(), contact=_contact(), categories=_categories(),
                        tickets=[_ticket(t) for t in support.tickets_of(conn, principal.user_id)],
                        max_text=support.MAX_TEXT, max_open=support.MAX_OPEN)


@router.post("/tickets", response_model=SupportTicket, status_code=201)
def open_ticket(body: TicketIn, principal: App) -> SupportTicket:
    """A ticket with its context; the receipt goes by e-mail. At most 3 open and 10 a day (409 ``too_many_open``,
    429 ``too_many_tickets``); 404 ``not_available`` while FBI_SUPPORT is off."""
    try:
        context = body.context.model_dump(exclude_none=True) if body.context else None
        return _ticket(support.open_ticket(principal.user_id, body.category, body.text, context))
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.post("/tickets/{ticket_id}/messages", response_model=SupportTicket)
def reply(body: TicketReplyIn, ticket_id: TicketId, principal: App) -> SupportTicket:
    try:
        return _ticket(support.reply(principal.user_id, ticket_id, body.text))
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.post("/tickets/{ticket_id}/close", response_model=SupportTicket)
def close(body: TicketCloseIn, ticket_id: TicketId, principal: App) -> SupportTicket:
    try:
        return _ticket(support.close(principal.user_id, ticket_id, effort=body.effort))
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.post("/tickets/{ticket_id}/effort", response_model=SupportTicket)
def rate(body: TicketEffortIn, ticket_id: TicketId, principal: App) -> SupportTicket:
    try:
        return _ticket(support.rate(principal.user_id, ticket_id, body.effort))
    except CustomerError as exc:
        raise _refused(exc) from exc


# ── the owner ────────────────────────────────────────────────────────────────────────

def _admin_ticket(t: support.Ticket) -> AdminTicket:
    at = now()
    return AdminTicket(
        id=t.id, user_id=t.user_id, email=t.email or "", display_name=t.display_name or "",
        account_status=t.account_status or "", kind=t.kind, category=t.category,  # type: ignore[arg-type]
        priority=t.priority, status=t.status, opened_at=t.opened_at,  # type: ignore[arg-type]
        closed_at=t.closed_at, respond_by=t.respond_by, deadline=t.deadline, extended=t.extended_to is not None,
        first_answer_at=t.first_answer_at, waiting=t.waiting, late=t.late(at),
        context=SupportContext(**t.context) if t.context else None, effort=t.effort, at_risk=t.at_risk,
        messages=_messages(t))


@admin_router.get("", response_model=AdminInbox)
def inbox(conn: Db, status: Annotated[InboxStatus, Query()] = "open",
          category: Annotated[TicketCategory | None, Query()] = None,
          priority: Annotated[Priority | None, Query()] = None) -> AdminInbox:
    """Every ticket and privacy request, with the reader's address: waiting first, by priority, the oldest first."""
    try:
        tickets = support.inbox(conn, status=status, category=category, priority=priority)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return AdminInbox(counts=SupportCounts(**support.counts(conn, at=now())),
                      tickets=[_admin_ticket(t) for t in tickets])


@admin_router.post("/{ticket_id}/answer", response_model=AdminTicket)
def answer(body: TicketAnswerIn, ticket_id: TicketId) -> AdminTicket:
    """The owner's message on a support ticket with its new status: written here (the reader is told by e-mail) or a
    note of what was said on WhatsApp or by e-mail (no e-mail)."""
    try:
        return _admin_ticket(support.answer(ticket_id, body=body.body, status=body.status, channel=body.channel))
    except CustomerError as exc:
        raise _refused(exc) from exc

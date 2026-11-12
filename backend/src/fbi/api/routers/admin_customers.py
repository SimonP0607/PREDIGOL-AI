"""The customer's card - SUPER_ADMIN only (plan UX, B10).

``/admin/customers`` lists the readers with four views (cover ending in 7 days, 14 days unseen, open tickets, errors in
the last 24 hours) and opens one card per reader. Only reads here, and the owner's few acts that leave their own trail
in the access trail (``auth.audit_events``): a note, reading a consent's proof, reviewing a ticket and handing over a
copy of the reader's data (the owner's password first). The membership's own acts (activate, suspend, renew, extend)
and the invitation's resending are the routes that already record theirs (``/admin/users/...``). The card holds no
IP, no token and no loose click.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from fbi.api.contracts.customers import (
    AuditActionCount,
    ConsentRecord,
    Customer,
    CustomerList,
    CustomerNote,
    CustomerView,
    NoteIn,
    ReauthExportIn,
    TicketMessageView,
    TicketReview,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, listing, ok
from fbi.api.errors import ApiError
from fbi.api.security import UsersAdmin, client_ip, same_site_only
from fbi.api.services import customers
from fbi.auth import service as auth_service
from fbi.auth import store
from fbi.customer import consents, privacy, support
from fbi.customer.db import CustomerError, write_connection

router = APIRouter(prefix="/customers", tags=["admin: customers"], dependencies=[Depends(same_site_only)])
audit_router = APIRouter(tags=["admin: customers"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
UserId = Annotated[int, Path(ge=1)]
EXPORTS_PER_DAY = 10
"""Copies of readers' data the owner can hand out in 24 hours (counted in the trail, shared by both API processes)."""


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _record(actor: int, user_id: int, action: str, ip: str | None, detail: dict[str, Any] | None = None) -> None:
    with write_connection() as conn:
        store.record_event(conn, action, actor_user_id=actor, target_user_id=user_id, ip=ip, detail=detail or {})


def _exists(conn: psycopg.Connection[Any], user_id: int) -> None:
    """The reader must exist and be a reader (404 otherwise): nothing is recorded about a stranger."""
    if not customers.is_customer(conn, user_id):
        raise ApiError(404, "not_found", "no such customer")


@router.get("", response_model=CustomerList)
def list_customers(
    conn: Db,
    _: UsersAdmin,
    view: Annotated[CustomerView, Query()] = "all",
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerList:
    """The readers of a view (all, cover ending in 7 days, 14 days unseen, open tickets, errors in 24 h), newest
    account first, with how many each view holds."""
    try:
        return customers.listing(conn, view=view, query=q, limit=limit, offset=offset)
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.get("/{user_id}", response_model=Customer)
def customer_card(conn: Db, _: UsersAdmin, user_id: UserId) -> Customer:
    try:
        return customers.card(conn, user_id)
    except CustomerError as exc:
        raise _refused(exc) from exc


@router.post("/{user_id}/notes", response_model=Envelope[CustomerNote], status_code=201)
def add_note(body: NoteIn, request: Request, actor: UsersAdmin, user_id: UserId, conn: Db) -> Envelope[CustomerNote]:
    """An internal note about a reader: a line in the access trail (``customer.note``), never shown to the reader.
    Notes are not for sensitive data: the card says so."""
    _exists(conn, user_id)
    text = " ".join(body.note.split())
    if len(text) < 3:
        raise ApiError(422, "note_empty", "write the note")
    with write_connection() as w:
        store.record_event(w, customers.AUDIT_ACTIONS["note"], actor_user_id=actor.user_id, target_user_id=user_id,
                           ip=client_ip(request), detail={"note": text})
        row = w.execute("SELECT id, at FROM auth.audit_events WHERE action = %s AND target_user_id = %s "
                        "ORDER BY id DESC LIMIT 1", (customers.AUDIT_ACTIONS["note"], user_id)).fetchone()
    assert row is not None
    return ok(CustomerNote(id=int(row[0]), at=row[1], author=actor.email, note=text))


@router.get("/{user_id}/consents", response_model=Envelope[list[ConsentRecord]])
def consent_proofs(request: Request, actor: UsersAdmin, user_id: UserId, conn: Db) -> Envelope[list[ConsentRecord]]:
    """Reading a reader's consents with their proof (document, version, text's hash, source): recorded in the trail."""
    _exists(conn, user_id)
    rows = [ConsentRecord(kind=c.kind, granted=c.granted, document=c.document, version=c.version, sha256=c.sha256,
                          locale=c.locale, source=c.source, at=c.at) for c in consents.history(conn, user_id)]
    _record(actor.user_id, user_id, customers.AUDIT_ACTIONS["consents"], client_ip(request), {"rows": len(rows)})
    return listing(rows, empty_reason="This reader has not decided anything yet.")


@router.get("/{user_id}/tickets/{ticket_id}", response_model=TicketReview)
def review_ticket(request: Request, actor: UsersAdmin, user_id: UserId,
                  ticket_id: Annotated[int, Path(ge=1)], conn: Db) -> TicketReview:
    """A reader's ticket or privacy request with its messages: reviewing it is recorded in the trail."""
    try:
        t = support.owner_ticket(conn, ticket_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    if t.user_id != user_id:
        raise ApiError(404, "not_found", "no such ticket")
    _record(actor.user_id, user_id, customers.AUDIT_ACTIONS["ticket"], client_ip(request),
            {"ticket": t.id, "category": t.category})
    return TicketReview(id=t.id, kind=t.kind, category=t.category, status=t.status, opened_at=t.opened_at,
                        due_on=t.due_on, closed_at=t.closed_at, effort=t.effort,
                        messages=[TicketMessageView(author=m.author, body=m.body, at=m.at) for m in t.messages])


@router.post("/{user_id}/export")
def export_customer(body: ReauthExportIn, request: Request, actor: UsersAdmin, user_id: UserId,
                    conn: Db) -> JSONResponse:
    """A copy of everything PrediGol keeps about one reader (the same document the reader can download), handed over
    by the owner when the reader asks for it by a channel the product does not have. The owner's password first (and
    the second factor's code), ten a day; recorded in the trail with the reader it is about."""
    _exists(conn, user_id)
    auth_service.reauthenticate(actor, password=body.password, code=body.code, ip=client_ip(request),
                                action=customers.AUDIT_ACTIONS["export_reauth"], per_day=EXPORTS_PER_DAY)
    conn.rollback()
    try:
        document = privacy.export(conn, user_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    _record(actor.user_id, user_id, customers.AUDIT_ACTIONS["export"], client_ip(request))
    name = f"predigol-datos-{user_id}-{datetime.now(UTC):%Y-%m-%d}.json"
    return JSONResponse(document, headers={"content-disposition": f'attachment; filename="{name}"'})


@audit_router.get("/audit/actions", response_model=Envelope[list[AuditActionCount]])
def audit_actions(
    conn: Db,
    _: UsersAdmin,
    since: Annotated[datetime | None, Query()] = None,
) -> Envelope[list[AuditActionCount]]:
    """Every kind of event the trail holds, with how many (the console's filter lists them all: B10). With `since`,
    only what was recorded from that instant on: «Hoy en cifras» (decision 12) counts the day with it."""
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    rows = conn.execute(
        "SELECT action, count(*) FROM auth.audit_events WHERE (%s::timestamptz IS NULL OR at >= %s) "
        "GROUP BY action ORDER BY action", (since, since)).fetchall()
    return listing([AuditActionCount(action=str(r[0]), count=int(r[1])) for r in rows],
                   empty_reason="Nothing has been recorded yet.")

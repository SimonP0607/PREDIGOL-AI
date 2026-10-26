"""The legal texts (public), a reader's consents, the export of their own data and their privacy requests (plan UX,
A4), the owner's answers to those requests (Admin Console) and the reader's account centre in one read (B1).

None of these routes sits behind the consent gate: a reader who has not accepted the current texts can still read
them, accept them, withdraw an authorisation, take a copy of their data or ask for its deletion.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from fbi.api.contracts.account import AccountSummary
from fbi.api.contracts.customer import (
    AdminPrivacyRequest,
    ConsentPurpose,
    ConsentRecord,
    ConsentsIn,
    ConsentState,
    LegalDocument,
    LegalDocumentName,
    LegalSection,
    LegalVersion,
    PrivacyAnswerIn,
    PrivacyRequest,
    PrivacyRequestIn,
    ReauthIn,
    TicketMessage,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, client_ip, same_site_only
from fbi.auth import service as auth_service
from fbi.auth.service import Principal
from fbi.customer import account as account_centre
from fbi.customer import consents, legal, privacy
from fbi.customer.db import CustomerError

public_router = APIRouter(prefix="/legal", tags=["legal"])
router = APIRouter(prefix="/me", tags=["privacy"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/privacy-requests", tags=["admin"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Lang = Annotated[Literal["es", "en"] | None, Query(description="The text's language; the account's by default.")]


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _locale(lang: str | None, principal: Principal | None = None) -> legal.Locale:
    if lang in legal.LOCALES:
        return lang
    if principal is not None and principal.language in legal.LOCALES:
        return principal.language
    return "es"


@public_router.get("/{document}", response_model=LegalDocument)
def legal_document(document: Annotated[LegalDocumentName, Path()],
                   lang: Annotated[Literal["es", "en"], Query()] = "es") -> LegalDocument:
    """A legal text as a reader sees it, with its version, its sha256 and its history. Public: anyone may read the
    terms before having an account."""
    doc = legal.load(document, lang)
    history = [LegalVersion(version=v.version, date=date.fromisoformat(v.date), draft=v.draft, material=v.material,
                            changes=v.changes[lang], sha256=v.sha256[lang])
               for v in reversed(legal.register()[document])]
    return LegalDocument(document=document, locale=lang, version=doc.version, date=date.fromisoformat(doc.date),
                         draft=doc.draft, title=doc.title, summary=doc.summary,
                         sections=[LegalSection.model_validate(s) for s in doc.sections], sha256=doc.sha256,
                         history=history)


def consent_state(conn: psycopg.Connection[Any], principal: Principal, locale: legal.Locale) -> ConsentState:
    latest = consents.latest(conn, principal.user_id)
    gate = consents.gate_enabled() and not consents.exempt(principal.email, super_admin=principal.is_super_admin)
    owed = legal.due({k: (c.granted, c.version) for k, c in latest.items()})
    purposes: list[ConsentPurpose] = []
    for purpose in legal.PURPOSES:
        doc, sentence = legal.statement(purpose.kind, locale)
        prev = latest.get(purpose.kind)
        replaced = prev is not None and prev.granted and prev.version not in legal.valid_versions(purpose.document)
        purposes.append(ConsentPurpose(
            kind=purpose.kind,  # type: ignore[arg-type]
            document=purpose.document, version=doc.version, sha256=doc.sha256, statement=sentence,
            required=purpose.required, withdrawable=purpose.withdrawable,
            changes=legal.current(purpose.document).changes[locale] if replaced else None))
    history = [ConsentRecord(kind=c.kind, granted=c.granted, document=c.document, version=c.version,
                             sha256=c.sha256, locale=c.locale, statement=c.statement, source=c.source, at=c.at)
               for c in consents.history(conn, principal.user_id)]
    return ConsentState(gate=gate, due=owed if gate else [], purposes=purposes,  # type: ignore[arg-type]
                        history=history)


@router.get("/account", response_model=AccountSummary)
def my_account(conn: Db, principal: App) -> AccountSummary:
    """The profile's eight blocks, folded (plan UX, B1; section 21): the account, its football, language and zone,
    e-mails, privacy, security, membership and help, in one read of the reader's own rows. Outside the consent and
    membership gates, as the profile is: a limited account reads its own account."""
    return AccountSummary.model_validate(account_centre.summary(conn, principal))


@router.get("/consents", response_model=ConsentState)
def my_consents(conn: Db, principal: App, lang: Lang = None) -> ConsentState:
    """What the reader has accepted, what the gate asks of them now, and the boxes with their exact sentences."""
    return consent_state(conn, principal, _locale(lang, principal))


@router.post("/consents", response_model=ConsentState)
def decide(body: ConsentsIn, conn: Db, principal: App) -> ConsentState:
    """Accepts or withdraws purposes, each on the version of the text the reader was shown (409
    ``legal_text_changed`` when a newer one exists: the page reloads it)."""
    source = body.source
    if source == "activation":
        # The proof says where the boxes were ticked: «activation» only right after the account's activation (plan UX,
        # A7) - not because a page says so.
        row = conn.execute("SELECT 1 FROM auth.audit_events WHERE action = 'user.activated' AND target_user_id = %s "
                           "AND at > now() - interval '1 hour' LIMIT 1", (principal.user_id,)).fetchone()
        source = "activation" if row is not None else "gate"
    try:
        consents.record(principal.user_id, [consents.Decision(d.kind, d.granted, d.version) for d in body.decisions],
                        locale=body.locale, source=source)
    except CustomerError as exc:
        raise _refused(exc) from exc
    conn.rollback()  # a fresh snapshot: the decisions were written by another connection
    return consent_state(conn, principal, body.locale)


@router.post("/export")
def export_my_data(body: ReauthIn, request: Request, conn: Db, principal: App) -> JSONResponse:
    """A copy of everything PrediGol keeps about the reader, as a JSON file. The password first (and the second
    factor's code when the account has one); three a day."""
    auth_service.reauthenticate(principal, password=body.password, code=body.code, ip=client_ip(request),
                                action="privacy.export", per_day=privacy.EXPORTS_PER_DAY)
    conn.rollback()
    try:
        document = privacy.export(conn, principal.user_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    name = f"predigol-datos-{datetime.now(UTC):%Y-%m-%d}.json"
    return JSONResponse(document, headers={"content-disposition": f'attachment; filename="{name}"'})


def _request(t: privacy.Ticket) -> PrivacyRequest:
    return PrivacyRequest(id=t.id, kind=t.kind, status=t.status,  # type: ignore[arg-type]
                          opened_at=t.opened_at, due_on=t.due_on, extended_to=t.extended_to, deadline=t.deadline,
                          closed_at=t.closed_at,
                          messages=[TicketMessage(author=m.author, body=m.body, at=m.at)  # type: ignore[arg-type]
                                    for m in t.messages])


@router.get("/privacy-requests", response_model=list[PrivacyRequest])
def my_privacy_requests(conn: Db, principal: App) -> list[PrivacyRequest]:
    return [_request(t) for t in privacy.requests_of(conn, principal.user_id)]


@router.post("/privacy-requests", response_model=PrivacyRequest, status_code=201)
def open_privacy_request(body: PrivacyRequestIn, request: Request, principal: App) -> PrivacyRequest:
    """A query (10 business days), a claim (15) or a deletion request (15, the password first) about the reader's
    data, with its legal deadline. One open request of each kind at a time (409 ``request_open``)."""
    if body.kind == "privacy_deletion":
        if not body.password:
            raise ApiError(422, "password_required", "a deletion request needs the account's password")
        auth_service.reauthenticate(principal, password=body.password, code=body.code, ip=client_ip(request),
                                    action="privacy.deletion_request")
    try:
        return _request(privacy.open_request(principal.user_id, body.kind, body.message))
    except CustomerError as exc:
        raise _refused(exc) from exc


def _admin_request(t: privacy.Ticket) -> AdminPrivacyRequest:
    return AdminPrivacyRequest(**_request(t).model_dump(), user_id=t.user_id, email=t.email or "")


@admin_router.get("", response_model=list[AdminPrivacyRequest])
def privacy_requests(conn: Db, status: Annotated[Literal["open", "all"], Query()] = "open") -> list[AdminPrivacyRequest]:
    """The readers' privacy requests, open first by deadline (the legal one: 10 or 15 business days)."""
    return [_admin_request(t) for t in privacy.all_requests(conn, status=status)]


@admin_router.post("/{ticket_id}/answer", response_model=AdminPrivacyRequest)
def answer_privacy_request(body: PrivacyAnswerIn, ticket_id: Annotated[int, Path(ge=1)]) -> AdminPrivacyRequest:
    """The owner's message on a request, with its new status or the one extension (the message says why)."""
    try:
        return _admin_request(privacy.answer(ticket_id, body=body.body, status=body.status, extend=body.extend))
    except CustomerError as exc:
        raise _refused(exc) from exc

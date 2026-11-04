"""Account and access without the owner (plan UX, A7): activating an invitation, choosing a new password, unlocking an
account - public, same-site, and only while FBI_SELF_SERVICE is on (404 otherwise).

A link's token travels in the body, read by the page from the link's fragment: it is never in a URL the server, its
access log or a referrer sees. Asking for a link answers 202 ``accepted`` at once, whatever the address, and does the
work after the answer has left (fbi.auth.recovery).
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from fbi.api.contracts.auth import (
    Accepted,
    AccountOptions,
    ActivateIn,
    ActivationInfo,
    EmailIn,
    Me,
    ResetIn,
    ResetInfo,
    TokenIn,
)
from fbi.api.deps import get_db
from fbi.api.routers.auth import _signed_in
from fbi.api.security import client_ip, same_site_only
from fbi.auth import invitations, recovery, tokens

router = APIRouter(prefix="/auth", tags=["account"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/options", response_model=AccountOptions)
def options() -> AccountOptions:
    """What the sign-in page may offer: recovery and unlocking by e-mail only while they work."""
    return AccountOptions(self_service=tokens.self_service_enabled())


@router.post("/activate/check", response_model=ActivationInfo)
def check_invitation(body: TokenIn, request: Request) -> ActivationInfo:
    """Whether an invitation link works (410 ``link_invalid`` otherwise, whatever the reason)."""
    return ActivationInfo(**invitations.check(body.token, ip=client_ip(request)))


@router.post("/activate", response_model=Me)
def activate(body: ActivateIn, request: Request, response: Response, conn: Db) -> Me:
    """The account's own password, language and time zone: it becomes active and is signed in (an HttpOnly cookie,
    as at sign-in). Its consents are owed next (``consents_due``)."""
    issued = invitations.activate(body.token, password=body.password, language=body.language,
                                  timezone=body.timezone, ip=client_ip(request),
                                  user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued, conn)


@router.post("/activate/renew", response_model=Accepted, status_code=202)
def renew_invitation(body: TokenIn, request: Request, background: BackgroundTasks) -> Accepted:
    """A new invitation for the account of a link that no longer works, while it is still invited (at most three an
    hour). The same answer whatever happens."""
    ip = client_ip(request)
    recovery.accept_request(ip)
    background.add_task(invitations.renew, body.token, ip=ip)
    return Accepted()


@router.post("/password/forgot", response_model=Accepted, status_code=202)
def forgot_password(body: EmailIn, request: Request, background: BackgroundTasks) -> Accepted:
    """A link to choose a new password, valid 30 minutes, if the address has an active account (an invited one gets its
    invitation again). The same answer, at once, whatever the address."""
    ip = client_ip(request)
    recovery.accept_request(ip)
    background.add_task(recovery.request_reset, body.email, ip=ip)
    return Accepted()


@router.post("/password/reset/check", response_model=ResetInfo)
def check_reset(body: TokenIn, request: Request) -> ResetInfo:
    return ResetInfo(**recovery.check_reset(body.token, ip=client_ip(request)))


@router.post("/password/reset", status_code=204)
def reset_password(body: ResetIn, request: Request) -> Response:
    """The new password: every session of the account ends; the second factor stays - and its code is asked first
    when the account has one (``ResetInfo.mfa``). The reader signs in again."""
    recovery.reset_password(body.token, body.password, code=body.code, recovery_code=body.recovery_code,
                            ip=client_ip(request))
    return Response(status_code=204)


@router.post("/unlock/request", response_model=Accepted, status_code=202)
def request_unlock(body: EmailIn, request: Request, background: BackgroundTasks) -> Accepted:
    """A link to lift the lock, valid one hour, if the address has an active account locked right now. The same
    answer, at once, whatever the address."""
    ip = client_ip(request)
    recovery.accept_request(ip)
    background.add_task(recovery.request_unlock, body.email, ip=ip)
    return Accepted()


@router.post("/unlock", status_code=204)
def unlock(body: TokenIn, request: Request) -> Response:
    recovery.unlock(body.token, ip=client_ip(request))
    return Response(status_code=204)

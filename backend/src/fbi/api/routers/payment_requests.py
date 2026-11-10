"""The manual payment request (UX-090): the reader's «ya pagué» and the owner's queue. Never behind the membership gate:
a limited reader is exactly who asks for access. Every decision is the owner's; each leaves an event and a line of the
access trail (``membership.payment_request*``)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response

from fbi.api.contracts.payment_requests import (
    AdminPaymentRequest,
    AdminPaymentRequests,
    AnnulIn,
    ApproveIn,
    MyPaymentRequests,
    PaymentRequestIn,
    PaymentRequestView,
    RejectIn,
)
from fbi.api.errors import ApiError
from fbi.api.security import App, UsersAdmin, same_site_only
from fbi.auth import throttle
from fbi.customer import legal, payment_requests
from fbi.customer.db import CustomerError, write_connection

router = APIRouter(prefix="/me/payment-request", tags=["membership"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/payment-requests", tags=["admin"])
SENDS = throttle.FailureWindow(max_failures=8, window_s=3600)
"""Notices a reader tried to send in an hour, valid or not: the daily cap of the database counts only the accepted."""
RequestId = Annotated[int, Path(ge=1)]


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _locale(principal: Any) -> legal.Locale:
    return principal.language if principal.language in legal.LOCALES else "es"


@router.get("", response_model=MyPaymentRequests)
def my_requests(principal: App) -> MyPaymentRequests:
    """Whether the reader can send a notice, what the owner published to be paid, the price they pay, the terms they would
    accept and their notices. The owner's details are sent only while the notices are open."""
    with write_connection() as conn:  # read after the write, on the same primary
        return MyPaymentRequests.model_validate(payment_requests.mine(conn, principal.user_id,
                                                                      locale=_locale(principal)))


@router.get("/qr", response_class=Response, responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}})
def qr(principal: App) -> Response:
    """The Nequi QR image, only while the notices are open and only for a signed-in reader. Never cached."""
    del principal
    found = payment_requests.qr_bytes() if not payment_requests.locks() else None
    if found is None:
        raise ApiError(404, "not_found", "no QR is published")
    body, media = found
    return Response(content=body, media_type=media, headers={"cache-control": "no-store",
                                                             "content-disposition": 'inline; filename="qr"',
                                                             "x-content-type-options": "nosniff"})


@router.post("", response_model=PaymentRequestView, status_code=201)
def send(body: PaymentRequestIn, principal: App) -> PaymentRequestView:
    """«Ya pagué»: 409 ``request_open`` when a notice waits, ``payment_not_configured`` / ``price_not_set`` /
    ``terms_draft`` while the owner has not opened the payments, ``terms_changed`` when the terms moved since the reader
    read them, ``reference_used`` for a payment already recorded."""
    key = str(principal.user_id)
    if SENDS.blocked(key):
        raise ApiError(429, "rate_limited", "too many tries: wait a while", headers={
            "retry-after": str(SENDS.retry_after(key))})
    SENDS.fail(key)
    try:
        created = payment_requests.create(
            principal.user_id, amount=body.amount, paid_on=body.paid_on, method=body.method, reference=body.reference,
            payer_name=body.payer_name, note=body.note, accept_terms=body.accept_terms,
            terms_version=body.terms_version, locale=_locale(principal))
    except CustomerError as exc:
        raise _refused(exc) from exc
    return PaymentRequestView.model_validate(created)


@router.post("/{request_id}/cancel", response_model=PaymentRequestView)
def cancel(principal: App, request_id: RequestId) -> PaymentRequestView:
    """The reader withdraws a notice nobody decided yet (409 ``request_decided`` otherwise)."""
    try:
        return PaymentRequestView.model_validate(payment_requests.cancel(principal.user_id, request_id))
    except CustomerError as exc:
        raise _refused(exc) from exc


@admin_router.get("", response_model=AdminPaymentRequests)
def queue(_: UsersAdmin, status: Annotated[str, Query(pattern="^(submitted|all)$")] = "submitted",
          limit: Annotated[int, Query(ge=1, le=200)] = 100) -> AdminPaymentRequests:
    """The notices waiting for the owner, the one waiting longest first (or the last ones with ``status=all``)."""
    try:
        with write_connection() as conn:
            return AdminPaymentRequests.model_validate(payment_requests.queue(conn, status=status, limit=limit))
    except CustomerError as exc:
        raise _refused(exc) from exc


def _admin_one(request_id: int) -> AdminPaymentRequest:
    with write_connection() as conn:
        found = payment_requests.queue(conn, status="all", limit=200)["requests"]
        for item in found:
            if item["id"] == request_id:
                return AdminPaymentRequest.model_validate(item)
    raise ApiError(404, "request_not_found", "no such notice")


@admin_router.post("/{request_id}/approve", response_model=AdminPaymentRequest)
def approve(body: ApproveIn, actor: UsersAdmin, request_id: RequestId) -> AdminPaymentRequest:
    """The owner saw the money: the payment and the period, in one step; the notice is decided once (409
    ``request_decided`` for a second click)."""
    try:
        payment_requests.approve(actor.user_id, request_id, received_amount=body.received_amount, months=body.months)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_one(request_id)


@admin_router.post("/{request_id}/reject", response_model=AdminPaymentRequest)
def reject(body: RejectIn, actor: UsersAdmin, request_id: RequestId) -> AdminPaymentRequest:
    try:
        payment_requests.reject(actor.user_id, request_id, code=body.code, note=body.note)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_one(request_id)


@admin_router.post("/{request_id}/annul", response_model=AdminPaymentRequest)
def annul(body: AnnulIn, actor: UsersAdmin, request_id: RequestId) -> AdminPaymentRequest:
    """An approval that was a mistake: its period stops counting (nothing is deleted)."""
    try:
        payment_requests.annul(actor.user_id, request_id, reason=body.reason)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_one(request_id)

"""Membership (plan UX, A8): the reader's own (never behind the gates: a limited reader still sees why and how to
renew) and the owner's actions in the console - record a payment and extend, a courtesy, a trial, a suspension and its
lifting, «will not renew». Only a SUPER_ADMIN records anything; each action is in the access trail (membership.*).
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.membership import (
    AdminMembership,
    AdminMembershipEvent,
    AdminPeriod,
    CourtesyIn,
    MembershipSummary,
    MyMembership,
    MyPeriod,
    PaymentIn,
    PaymentRecorded,
    ReasonIn,
    RenewalIntentIn,
    RenewContact,
    TrialIn,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, UsersAdmin, same_site_only
from fbi.customer import membership
from fbi.customer.db import CustomerError, write_connection

router = APIRouter(prefix="/me", tags=["membership"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/users", tags=["admin"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
UserId = Annotated[int, Path(ge=1)]


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _summary(m: membership.Membership) -> MembershipSummary | None:
    found = membership.summary(m)
    return MembershipSummary(**found) if found is not None else None


@router.get("/membership", response_model=MyMembership)
def my_membership(conn: Db, principal: App) -> MyMembership:
    """The reader's membership: its state now, its periods with their payments, and how to renew."""
    mine = membership.mine(conn, principal.user_id, email=principal.email, super_admin=principal.is_super_admin)
    return MyMembership(membership=MembershipSummary(**mine["membership"]) if mine["membership"] else None,
                        enforced=mine["enforced"], periods=[MyPeriod(**p) for p in mine["periods"]],
                        renew=RenewContact(**mine["renew"]))


def _admin_view(user_id: int) -> AdminMembership:
    with write_connection() as conn:  # read after the write, on the same primary
        row = conn.execute("SELECT email, role FROM auth.users WHERE id = %s", (user_id,)).fetchone()
        if row is None:
            raise ApiError(404, "user_not_found", "no such account")
        m = membership.of(conn, user_id, email=str(row[0]), super_admin=row[1] == "SUPER_ADMIN")
        found = membership.history(conn, user_id)
    return AdminMembership(
        membership=_summary(m), suspended_reason=m.suspended_reason,
        periods=[AdminPeriod(**p) for p in found["periods"]],
        events=[AdminMembershipEvent(**e) for e in found["events"]],
        currency=membership.currency(), trial_days=membership.trial_days(), enforced=membership.enforced())


@admin_router.get("/{user_id}/membership", response_model=AdminMembership)
def admin_membership(_: UsersAdmin, user_id: UserId) -> AdminMembership:
    """One account's membership for the console: the state, every period with its payment, every event."""
    return _admin_view(user_id)


@admin_router.post("/{user_id}/membership/payments", response_model=PaymentRecorded)
def record_payment(body: PaymentIn, actor: UsersAdmin, user_id: UserId) -> PaymentRecorded:
    """«Record payment and extend»: the payment (amount, currency, method, a reference in words) and its months, from
    the end of the cover in force or from now. The same idempotency key records one payment."""
    try:
        recorded = membership.record_payment(actor.user_id, user_id, amount=body.amount, currency_code=body.currency,
                                             method=body.method, reference=body.reference, months=body.months,
                                             idempotency_key=body.idempotency_key)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return PaymentRecorded(created=recorded.created, membership=_admin_view(user_id))


@admin_router.post("/{user_id}/membership/courtesy", response_model=AdminMembership)
def grant_courtesy(body: CourtesyIn, actor: UsersAdmin, user_id: UserId) -> AdminMembership:
    try:
        membership.grant_courtesy(actor.user_id, user_id, days=body.days, reason=body.reason)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_view(user_id)


@admin_router.post("/{user_id}/membership/trial", response_model=AdminMembership)
def start_trial(body: TrialIn, actor: UsersAdmin, user_id: UserId) -> AdminMembership:
    """A trial for an account that never had one (409 ``trial_used`` otherwise)."""
    try:
        membership.start_trial_by_owner(actor.user_id, user_id, days=body.days)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_view(user_id)


@admin_router.post("/{user_id}/membership/suspend", response_model=AdminMembership)
def suspend(body: ReasonIn, actor: UsersAdmin, user_id: UserId) -> AdminMembership:
    try:
        membership.suspend(actor.user_id, user_id, reason=body.reason or "")
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_view(user_id)


@admin_router.post("/{user_id}/membership/lift", response_model=AdminMembership)
def lift(body: ReasonIn, actor: UsersAdmin, user_id: UserId) -> AdminMembership:
    try:
        membership.lift(actor.user_id, user_id, reason=body.reason)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_view(user_id)


@admin_router.post("/{user_id}/membership/renewal", response_model=AdminMembership)
def renewal_intent(body: RenewalIntentIn, actor: UsersAdmin, user_id: UserId) -> AdminMembership:
    """«Will not renew» with its reason, or its withdrawal."""
    try:
        membership.renewal_intent(actor.user_id, user_id, will_renew=body.will_renew, reason=body.reason)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return _admin_view(user_id)

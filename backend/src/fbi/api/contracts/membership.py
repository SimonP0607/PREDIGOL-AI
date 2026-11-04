"""Membership (plan UX, A8): the reader's own and what the owner records - periods, payments and their events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

MembershipState = Literal["trial", "active", "expiring", "grace", "expired", "renewed", "suspended", "none"]
PeriodKind = Literal["trial", "paid", "courtesy"]
PaymentMethod = Literal["transfer", "nequi", "daviplata", "cash", "card", "paypal", "other"]


class MembershipSummary(Contract):
    """The state at this moment, computed from dates (never stored). ``none``: no period yet (full access)."""

    state: MembershipState
    ends_at: datetime | None = Field(description="When the cover ends: the last period's end.")
    grace_until: datetime | None = Field(description="The end plus the 3 days of grace with full access.")
    kind: PeriodKind | None = Field(description="The kind of the period that ends last.")
    days_left: int | None = Field(description="Whole days until the end, rounded up; 0 once it has ended.")
    limited: bool = Field(description="Whether the account reads only what a limited one reads, right now - "
                                      "always false while FBI_MEMBERSHIP_ENFORCE is off.")
    will_not_renew: bool


class RenewContact(Contract):
    whatsapp: str | None = Field(description="The WhatsApp Business number, digits with the country code (P7).")
    email: str | None = Field(description="The address a reader's answer reaches (FBI_EMAIL_REPLY_TO).")


class MyPeriod(Contract):
    kind: PeriodKind
    starts_at: datetime
    ends_at: datetime
    amount: str | None = Field(description="The payment of a paid period, as a decimal string.")
    currency: str | None
    method: PaymentMethod | None


class MyMembership(Contract):
    membership: MembershipSummary | None = Field(description="None for the owner's accounts: no membership.")
    enforced: bool = Field(description="FBI_MEMBERSHIP_ENFORCE: whether an ended membership limits anything.")
    periods: list[MyPeriod]
    renew: RenewContact


class AdminPeriod(Contract):
    id: int
    kind: PeriodKind
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    created_at: datetime
    amount: str | None
    currency: str | None
    method: PaymentMethod | None
    reference: str | None
    provider: str | None


class AdminMembershipEvent(Contract):
    kind: str
    at: datetime
    reason: str | None
    milestone: str | None
    detail: dict[str, Any]


class AdminMembership(Contract):
    membership: MembershipSummary | None
    suspended_reason: str | None
    periods: list[AdminPeriod]
    events: list[AdminMembershipEvent]
    currency: str = Field(description="The currency the payment form proposes (FBI_MEMBERSHIP_CURRENCY).")
    trial_days: int = Field(description="FBI_TRIAL_DAYS: the trial a new account gets unless the invitation says.")
    enforced: bool = Field(description="FBI_MEMBERSHIP_ENFORCE: whether an ended membership limits anything.")


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(min_length=1, max_length=20, description="A decimal: 50000 or 19.90.")
    currency: str = Field(min_length=3, max_length=3)
    method: PaymentMethod
    reference: str = Field(default="", max_length=120,
                           description="A few words: never an account's or a card's number.")
    months: int = Field(default=1, ge=1, le=12)
    idempotency_key: str = Field(min_length=8, max_length=80,
                                 description="One per payment the owner records: a repeated click records one.")


class CourtesyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=90)
    reason: str = Field(min_length=3, max_length=200)


class TrialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=7, le=14)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


class RenewalIntentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    will_renew: bool
    reason: str | None = Field(default=None, max_length=200)


class PaymentRecorded(Contract):
    created: bool = Field(description="False: this idempotency key was recorded before - the same payment.")
    membership: AdminMembership

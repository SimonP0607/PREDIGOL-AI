"""Membership (plan UX, A8): the reader's own and what the owner records - periods, payments and their events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

MembershipState = Literal["trial", "active", "expiring", "grace", "expired", "renewed", "suspended", "none"]
PeriodKind = Literal["trial", "paid", "courtesy"]
PaymentMethod = Literal["transfer", "nequi", "daviplata", "cash", "card", "paypal", "other"]
DiscountKind = Literal["coupon", "loyalty"]


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


class PlanPrice(Contract):
    currency: str = Field(description="ISO 4217 code: COP or USD.")
    amount: str = Field(description="The monthly price as a decimal string, e.g. 150000.")


class MembershipPlan(Contract):
    """The one plan, as the reader's membership block shows it (UX-004): the trial and the monthly price per currency.
    ``prices`` is empty while the owner has not set one (FBI_MEMBERSHIP_PRICE_COP / FBI_MEMBERSHIP_PRICE_USD)."""

    trial_days: int = Field(description="FBI_TRIAL_DAYS: the trial a new account gets, 20 by default.")
    prices: list[PlanPrice]


class DiscountOffer(Contract):
    """The discount a reader's next payment gets (UX-005): the larger of the loyalty one and the best coupon held."""

    kind: DiscountKind
    percent: int = Field(description="1 to 100.")
    code: str | None = Field(description="The coupon's code; None for the loyalty discount.")
    prices: list[PlanPrice] = Field(description="The monthly price with the discount taken off, per currency.")


class HeldCoupon(Contract):
    code: str
    percent: int


class LoyaltyRule(Contract):
    """The loyalty discount and where the reader stands (shown only while FBI_LOYALTY_PERCENT is not 0)."""

    percent: int
    after_months: int = Field(description="The months paid from which it applies: FBI_LOYALTY_AFTER_MONTHS, 2 by default.")
    paid_months: int = Field(description="The months of the payments the owner recorded; a trial is not one.")
    active: bool


class MyDiscounts(Contract):
    offer: DiscountOffer | None = Field(description="What the next payment gets, or None.")
    coupons: list[HeldCoupon] = Field(description="The coupons held and not used yet.")
    loyalty: LoyaltyRule | None


class MyPeriod(Contract):
    kind: PeriodKind
    starts_at: datetime
    ends_at: datetime
    amount: str | None = Field(description="The payment of a paid period, as a decimal string.")
    currency: str | None
    method: PaymentMethod | None
    discount_percent: int | None = Field(description="The discount that payment carried; None when it had none.")


class MyMembership(Contract):
    membership: MembershipSummary | None = Field(description="None for the owner's accounts: no membership.")
    enforced: bool = Field(description="FBI_MEMBERSHIP_ENFORCE: whether an ended membership limits anything.")
    periods: list[MyPeriod]
    renew: RenewContact
    plan: MembershipPlan
    discounts: MyDiscounts


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
    discount_percent: int | None
    discount_kind: DiscountKind | None
    coupon_code: str | None
    annulled: bool = Field(default=False, description="The owner annulled this period (UX-087): it no longer counts.")


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
    prices: list[PlanPrice] = Field(description="The monthly price per currency, for the payment form to propose.")
    discount: DiscountOffer | None = Field(description="The discount this account's next payment gets, or None.")


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
    apply_discount: bool = Field(default=False,
                                 description="Record the discount the account's next payment is offered (409 "
                                             "no_discount when there is none); a coupon is then used.")


class CourtesyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=90)
    reason: str = Field(min_length=3, max_length=200)


class TrialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=7, le=20)


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


class CouponIn(BaseModel):
    """A reader types a code: capitals or not, spaces at the ends ignored."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)


class CouponRedeemed(Contract):
    code: str
    percent: int
    discounts: MyDiscounts


class AdminCoupon(Contract):
    id: int
    code: str
    percent: int
    note: str | None
    valid_until: datetime | None
    max_redemptions: int | None
    created_at: datetime
    disabled_at: datetime | None
    redemptions: int = Field(description="Readers holding it.")
    used: int = Field(description="Payments that carried it.")
    active: bool = Field(description="Can still be redeemed: not disabled, not past its last day, not at its ceiling.")


class AdminCoupons(Contract):
    coupons: list[AdminCoupon]


class CouponCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    percent: int = Field(ge=1, le=100)
    note: str | None = Field(default=None, max_length=200)
    valid_until: datetime | None = Field(default=None, description="The last moment a reader may redeem it.")
    max_redemptions: int | None = Field(default=None, ge=1, le=100000)

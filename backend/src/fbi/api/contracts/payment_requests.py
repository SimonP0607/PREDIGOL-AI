"""The manual payment request, «ya pagué» (UX-090): the reader's side and the owner's queue."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

RequestStatus = Literal["submitted", "approved", "rejected", "cancelled"]
RequestMethod = Literal["nequi", "transfer", "other"]
DecisionCode = Literal["amount_mismatch", "not_received", "duplicate", "unreadable", "other"]
Lock = Literal["payment_not_configured", "price_not_set", "terms_draft", "key_unavailable"]


class PayDetails(Contract):
    """What the owner published to be paid - shown only while requests are open."""

    holder: str
    breb_key: str | None = Field(description="The Bre-B key to copy; None when the owner only gave the QR.")
    has_qr: bool = Field(description="Whether the Nequi QR image can be fetched (GET /me/payment-request/qr).")


class RequestPrice(Contract):
    currency: str
    amount: str = Field(description="The monthly price in pesos.")
    expected: str = Field(description="What the reader pays: the price with their discount taken off.")
    discount_percent: int | None


class RequestTerms(Contract):
    version: str
    sha256: str
    draft: bool


class PaymentRequestView(Contract):
    id: int
    status: RequestStatus
    expected_amount: str
    currency: str
    discount_percent: int | None
    declared_amount: str
    declared_paid_on: date
    method: RequestMethod
    reference_last4: str | None
    payer_name: str | None
    note: str | None
    terms_version: str
    accepted_at: datetime
    created_at: datetime
    decided_at: datetime | None
    decision_code: DecisionCode | None
    decision_note: str | None
    due_on: date = Field(description="The business day by whose end the owner verifies (Colombia).")
    due_at: datetime
    annulled: bool = Field(description="An approved notice whose period the owner annulled later.")


class MyPaymentRequests(Contract):
    available: bool = Field(description="Whether a notice can be sent: false while the owner's details, the price or the "
                                        "final terms of purchase are missing (``locks``).")
    locks: list[Lock]
    pay: PayDetails | None
    price: RequestPrice | None
    terms: RequestTerms
    whatsapp: str | None
    open: PaymentRequestView | None = Field(description="The notice waiting to be verified, if any: «pago en verificación».")
    requests: list[PaymentRequestView]


class PaymentRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(min_length=1, max_length=20, description="What the reader paid, a decimal: 150000.")
    paid_on: date
    method: RequestMethod
    reference: str | None = Field(default=None, max_length=60,
                                  description="The payment's reference. Only its last four characters are kept.")
    payer_name: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=400)
    accept_terms: bool
    terms_version: str = Field(min_length=1, max_length=40, description="The version of the terms the reader was shown.")


class AdminPaymentRequest(PaymentRequestView):
    user_id: int
    email: str
    display_name: str
    first_name: str | None
    last_name: str | None
    coupon_code: str | None
    same_reference: int = Field(description="Other notices carrying the same reference.")
    amount_matches: bool
    overdue: bool


class AdminPaymentRequests(Contract):
    waiting: int
    requests: list[AdminPaymentRequest]


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_amount: str | None = Field(default=None, max_length=20,
                                        description="What reached the owner's account; the declared amount by default.")
    months: int = Field(default=1, ge=1, le=12)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: DecisionCode
    note: str = Field(min_length=3, max_length=200)


class AnnulIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=200)

"""The customer's card for the owner (plan UX, B10): who a reader is, how they use the product and what they asked,
and nothing more - no address of theirs on the network, no token, no loose click (the card holds counts of days)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.membership import MembershipSummary

CustomerView = Literal["all", "expiring", "inactive", "tickets", "errors", "at_risk", "invited"]
LifecycleState = Literal["invited", "activated", "habitual", "at_risk", "expiring", "renewed", "expired"]


class CustomerRow(Contract):
    id: int
    email: str
    display_name: str | None
    status: Literal["active", "disabled", "invited"]
    created_at: datetime
    last_seen_at: datetime | None = Field(description="The last time any of their sessions was used.")
    membership: MembershipSummary | None
    open_tickets: int
    errors_24h: int = Field(description="The `error_shown` events of the last 24 hours.")
    active_days_7: int
    last_csat: int | None
    lifecycle: LifecycleState | None = Field(default=None, description="Their state on the newest day computed (B11); "
                                                                       "None before the first calculation.")
    lifecycle_reasons: list[str] = Field(default_factory=list, description="Why, in codes from a closed list.")


class CustomerViewCount(Contract):
    view: CustomerView
    count: int


class CustomerList(Contract):
    view: CustomerView
    items: list[CustomerRow]
    total: int
    views: list[CustomerViewCount] = Field(description="How many customers each view holds right now.")
    limit: int
    offset: int


class CustomerIdentity(Contract):
    id: int
    email: str
    display_name: str | None
    status: Literal["active", "disabled", "invited"]
    language: str
    timezone: str
    created_at: datetime
    last_login_at: datetime | None
    last_seen_at: datetime | None
    mfa_enabled: bool
    open_sessions: int


class CustomerUsage(Contract):
    active_days_7: int
    active_days_30: int
    matches_viewed_30: int
    picks_opened_30: int
    picks_saved: int = Field(description="Picks they keep now.")
    parlays_saved: int
    errors_24h: int
    measured: bool = Field(description="False when they have not accepted the analytics or the key is missing: the "
                                       "counts above are then zero because nothing is recorded, not because of "
                                       "no use.")


class CustomerDevice(Contract):
    id: int
    family: str
    system: str
    installed: bool
    created_at: datetime
    last_ok_at: datetime | None


class CustomerNotifications(Contract):
    email_status: Literal["ok", "bounced", "complained"]
    email_status_at: datetime | None
    email_off: list[str]
    push_off: list[str]
    devices: list[CustomerDevice]
    sent_30: int
    failed_30: int
    bounced_30: int
    suppressed_30: int


class CustomerConsent(Contract):
    kind: str
    granted: bool
    version: str
    at: datetime


class CustomerTicket(Contract):
    id: int
    kind: str
    category: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    messages: int
    late: bool


class CustomerFeedback(Contract):
    kind: str
    score: int | None
    helpful: bool | None
    subject: str | None
    created_at: datetime


class CustomerFeedbackSummary(Contract):
    last_csat: int | None
    last_csat_at: datetime | None
    survey_answers: int
    helpful_yes: int
    helpful_no: int
    recent: list[CustomerFeedback]


class CustomerNote(Contract):
    id: int
    at: datetime
    author: str | None
    note: str


class LifecycleChange(Contract):
    day: date
    state: LifecycleState
    reasons: list[str]


class Customer(Contract):
    identity: CustomerIdentity
    membership: MembershipSummary | None
    suspended_reason: str | None
    usage: CustomerUsage
    notifications: CustomerNotifications
    consents: list[CustomerConsent]
    consents_due: list[str]
    tickets: list[CustomerTicket]
    feedback: CustomerFeedbackSummary
    notes: list[CustomerNote]
    privacy_requests_open: int
    lifecycle: LifecycleChange | None = Field(default=None, description="Their newest state and why (B11).")
    lifecycle_history: list[LifecycleChange] = Field(default_factory=list, description="Their changes of state, newest first.")


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


class ReauthExportIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=20)


class ConsentRecord(Contract):
    kind: str
    granted: bool
    document: str
    version: str
    sha256: str
    locale: str
    source: str
    at: datetime


class TicketMessageView(Contract):
    author: str
    body: str
    at: datetime


class TicketReview(Contract):
    id: int
    kind: str
    category: str
    status: str
    opened_at: datetime
    due_on: date | None
    closed_at: datetime | None
    effort: int | None
    messages: list[TicketMessageView]


class AuditActionCount(Contract):
    action: str
    count: int

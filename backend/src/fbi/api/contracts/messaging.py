"""The reader's notification preferences and the owner's view of the queue of messages (plan UX, A5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

MessageCategory = Literal["account", "security", "membership", "support", "privacy", "legal"]
"""The account's e-mails: what the reader's choices speak of."""
OutboxCategory = Literal["account", "security", "membership", "support", "privacy", "legal", "marketing"]
"""What the queue holds: the account's e-mails and commercial e-mail (plan UX, B8: the weekly summary, with consent)."""
EmailStatus = Literal["ok", "bounced", "complained"]
MessageStatus = Literal["queued", "sent", "failed", "bounced", "complained", "suppressed"]


class EmailCategory(Contract):
    category: MessageCategory
    on: bool
    locked: bool = Field(description="Always sent (the account, its security, privacy requests, legal changes).")


class NotificationPreferences(Contract):
    email: list[EmailCategory]
    email_status: EmailStatus = Field(description="ok, or why e-mail stopped: a hard bounce or a complaint.")
    email_status_at: datetime | None


class NotificationPreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: dict[MessageCategory, bool] = Field(description="Categories to switch on (true) or off (false).")


class OutboxMessage(Contract):
    id: int
    user_id: int
    user_email: str
    category: OutboxCategory
    template: str
    locale: Literal["es", "en"]
    status: MessageStatus
    attempts: int
    created_at: datetime
    next_attempt_at: datetime | None = Field(description="Only while queued.")
    sent_at: datetime | None
    last_error: str | None = Field(description="A short code: the provider's status and error name, never its text.")


class OutboxSummary(Contract):
    sending: bool = Field(description="FBI_EMAIL_SEND: off, messages wait in the queue.")
    provider: bool = Field(description="The provider's key and sender are set (never shown).")
    daily_cap: int
    sent_today: int = Field(description="Accepted by the provider since 00:00 UTC.")
    counts: dict[MessageStatus, int] = Field(description="Messages of the last 7 days by status.")
    messages: list[OutboxMessage]


class OutboxPreview(Contract):
    subject: str
    text: str
    html: str
    link: str | None = Field(description="Where the message's button leads.")


class UnsubscribeIn(BaseModel):
    """The page of PrediGol the weekly summary's link opens (plan UX, B8): the token from the address's fragment."""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=26, max_length=60)


class UnsubscribeResult(Contract):
    """The one-click leaving of the weekly summary (plan UX, B8; RFC 8058)."""

    left: bool = Field(description="True when this click withdrew the consent; false when the reader had already left "
                                   "(the link still works, and changes nothing).")

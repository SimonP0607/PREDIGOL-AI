"""The reader's notification preferences and the owner's view of the queue of messages (plan UX, A5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

MessageCategory = Literal["account", "security", "membership", "support", "privacy", "legal"]
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
    category: MessageCategory
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

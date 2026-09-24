from __future__ import annotations

from datetime import datetime

from pydantic import Field

from fbi.api.contracts.common import Contract


class NotificationRow(Contract):
    id: int
    kind: str
    title: str
    body: str
    created_at: datetime
    channel: str | None
    status: str
    attempts: int
    sent_at: datetime | None
    last_error: str | None


class NotificationsOverview(Contract):
    channel_configured: bool = Field(description="Whether the API host sees a Telegram token and chat id. Never values.")
    by_status: dict[str, int]
    recent: list[NotificationRow]

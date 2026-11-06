"""The owner's communiqués (closing plan 4.3): what the console writes and reads, and what readers see."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

AnnouncementKind = Literal["maintenance", "incident", "update", "general"]
"""Four closed kinds. There is no «promotion»."""
AnnouncementStatus = Literal["draft", "published", "retracted"]


class AnnouncementIn(Contract):
    kind: AnnouncementKind
    title_es: str = Field(min_length=3, max_length=80)
    title_en: str = Field(min_length=3, max_length=80)
    body_es: str = Field(min_length=3, max_length=600)
    body_en: str = Field(min_length=3, max_length=600)
    starts_at: datetime
    ends_at: datetime
    to_banner: bool = True
    to_updates: bool = Field(default=False, description="Novedades: only an update.")
    to_telegram: bool = Field(default=False, description="The channel, when one is configured.")
    to_email: bool = Field(default=False, description="Only a critical communiqué (maintenance or incident).")
    critical: bool = False


class Announcement(Contract):
    id: int
    kind: AnnouncementKind
    status: AnnouncementStatus
    title_es: str
    title_en: str
    body_es: str
    body_en: str
    starts_at: datetime
    ends_at: datetime
    to_banner: bool
    to_updates: bool
    to_telegram: bool
    to_email: bool
    critical: bool
    created_at: datetime
    published_at: datetime | None
    retracted_at: datetime | None


class AnnouncementList(Contract):
    telegram_configured: bool
    daily_cap: int
    published_today: int
    items: list[Announcement]


class AnnouncementLogLine(Contract):
    action: str
    actor_user_id: int | None
    detail: dict[str, Any]
    at: datetime


class AnnouncementPreview(Contract):
    id: int
    code: str = Field(description="Shown once; step two needs it with the word PUBLICAR. Lives ten minutes.")
    expires_at: datetime
    destinations: dict[str, Any]
    published_today: int
    daily_cap: int


class PublishIn(Contract):
    code: str = Field(min_length=8, max_length=64)
    phrase: str = Field(max_length=20)


class AnnouncementPublished(Contract):
    id: int
    emails_queued: int
    telegram: Literal["sent", "failed", "not_configured", "not_requested"]


class PublicNotice(Contract):
    id: int
    kind: AnnouncementKind
    title_es: str
    title_en: str
    body_es: str
    body_en: str
    starts_at: datetime
    ends_at: datetime
    critical: bool


class PublicUpdate(Contract):
    id: int
    title_es: str
    title_en: str
    body_es: str
    body_en: str
    starts_at: datetime


class ActiveAnnouncements(Contract):
    banners: list[PublicNotice]
    updates: list[PublicUpdate]

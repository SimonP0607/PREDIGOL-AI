"""Who is signed in, their preferences, and the accounts the Admin Console manages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

Language = Literal["es", "en"]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Me(Contract):
    id: int
    email: str
    display_name: str
    role: str
    permissions: list[str]
    language: Language
    timezone: str = Field(description="IANA time zone every time on screen is shown in. Stored data stays UTC.")
    session_expires_at: datetime


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AdminUser(Contract):
    id: int
    email: str
    display_name: str
    role: str
    status: Literal["active", "disabled"]
    language: Language
    timezone: str
    created_at: datetime
    last_login_at: datetime | None
    active_sessions: int


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=80)
    role: str = Field(default="USER", max_length=32)
    password: str = Field(min_length=1, max_length=256)
    language: Language = "es"
    timezone: str = Field(default="UTC", max_length=64)


class AdminUserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(default=None, max_length=32)
    status: Literal["active", "disabled"] | None = None


class AuditEvent(Contract):
    id: int
    at: datetime
    action: str
    actor_email: str | None
    target_email: str | None
    email: str | None = Field(description="The address that was tried, for sign-ins of unknown accounts.")
    ip: str | None
    detail: dict[str, Any]

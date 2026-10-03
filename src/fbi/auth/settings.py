"""Session settings. Defaults suit one machine on http://localhost; a deployment behind
HTTPS sets FBI_SESSION_COOKIE_SECURE=1."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FBI_SESSION_", env_file=".env", extra="ignore")

    cookie_name: str = Field(default="predigol_session", pattern=r"^[A-Za-z0-9_\-]{3,40}$")
    cookie_secure: bool = False
    ttl_hours: int = Field(default=168, ge=1, le=24 * 90)
    """Absolute lifetime: a session ends this long after sign-in whatever happens."""
    idle_hours: int = Field(default=72, ge=1, le=24 * 30)
    """A session not used for this long ends early."""
    touch_minutes: int = Field(default=5, ge=1, le=60)
    """How stale last_seen_at may get before a request writes it again."""


@lru_cache(maxsize=1)
def session_settings() -> SessionSettings:
    return SessionSettings()


def reset() -> None:
    session_settings.cache_clear()

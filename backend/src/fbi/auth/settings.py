"""Session and sign-in settings. Defaults suit one machine on http://localhost; a deployment behind
HTTPS sets FBI_SESSION_COOKIE_SECURE=1, a __Host- cookie name and SameSite=strict (deploy/vps/docker-compose.yml)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FBI_SESSION_", env_file=".env", extra="ignore")

    cookie_name: str = Field(default="predigol_session", pattern=r"^[A-Za-z0-9_\-]{3,40}$")
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict"] = "lax"
    """strict in production: every API call is a same-origin fetch, so nothing legitimate needs the cookie on a
    cross-site request - not even the first page load, which renders without it and then asks /auth/me."""
    ttl_hours: int = Field(default=168, ge=1, le=24 * 90)
    """Absolute lifetime: a session ends this long after sign-in whatever happens."""
    idle_hours: int = Field(default=72, ge=1, le=24 * 30)
    """A session not used for this long ends early."""
    admin_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    """The same two limits for a SUPER_ADMIN, shorter: that session can manage accounts and see everything."""
    admin_idle_hours: int = Field(default=8, ge=1, le=24 * 7)
    touch_minutes: int = Field(default=5, ge=1, le=60)
    """How stale last_seen_at may get before a request writes it again."""
    staged_minutes: int = Field(default=10, ge=2, le=60)
    """A session that still owes a second factor, an enrolment or a new password lives this long, at most."""


class AuthSettings(BaseSettings):
    """Second factor, lock-out and the key that protects second-factor secrets at rest."""

    model_config = SettingsConfigDict(env_prefix="FBI_AUTH_", env_file=".env", extra="ignore")

    secret_key: SecretStr | None = None
    """32 random bytes, base64. Encrypts TOTP secrets (AES-256-GCM) and keys the recovery-code hashes, so a copy of
    the database alone cannot produce a code. Lives only in the env file (deploy/vps: /etc/predigol, mode 600)."""
    mfa_roles: str = "SUPER_ADMIN"
    """Roles that must use a second factor (comma separated). Any account can be required individually too."""
    mfa_issuer: str = Field(default="PrediGol", min_length=1, max_length=40)
    mfa_max_attempts: int = Field(default=5, ge=1, le=20)
    """Wrong codes allowed on one staged session before it is revoked."""
    lock_threshold: int = Field(default=5, ge=1, le=50)
    """Consecutive failures (wrong password or wrong code) that lock an account for lock_minutes."""
    lock_minutes: int = Field(default=15, ge=1, le=1440)
    lock_max_minutes: int = Field(default=1440, ge=1, le=10080)
    """Each further failure while the streak goes on doubles the lock, up to this."""
    recovery_codes: int = Field(default=10, ge=4, le=20)

    def required_roles(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.mfa_roles.split(",") if r.strip())


@lru_cache(maxsize=1)
def session_settings() -> SessionSettings:
    return SessionSettings()


@lru_cache(maxsize=1)
def auth_settings() -> AuthSettings:
    return AuthSettings()


def reset() -> None:
    session_settings.cache_clear()
    auth_settings.cache_clear()

"""Session tokens. The browser holds the token; the database holds only its SHA-256."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_token(value: str | None) -> bool:
    """A cookie that cannot be one of ours is rejected before the database is asked."""
    if not value or not (32 <= len(value) <= 64):
        return False
    return all(c.isalnum() or c in "-_" for c in value)


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

"""Secrets at rest for the second factor.

* A TOTP secret is stored encrypted with AES-256-GCM under FBI_AUTH_SECRET_KEY, with the user's id as associated
  data: a row copied onto another account does not decrypt.
* A recovery code is stored as an HMAC-SHA256 keyed from the same secret: fast to check (ten codes per attempt),
  and a stolen dump cannot be brute-forced without the key.

The key never touches the database. Without it no second factor can be enrolled or checked, and the API says so
(``mfa_unavailable``) instead of guessing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fbi.auth.settings import auth_settings

VERSION = b"\x01"
NONCE_BYTES = 12
RECOVERY_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
"""No 0/o, 1/l/i: a code read off paper is typed back right."""


class KeyUnavailableError(RuntimeError):
    """FBI_AUTH_SECRET_KEY is missing or is not 32 bytes of base64."""


def _master_key() -> bytes:
    raw = auth_settings().secret_key
    if raw is None:
        raise KeyUnavailableError("FBI_AUTH_SECRET_KEY is not set")
    try:
        key = base64.b64decode(raw.get_secret_value().strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise KeyUnavailableError("FBI_AUTH_SECRET_KEY is not base64") from exc
    if len(key) != 32:
        raise KeyUnavailableError("FBI_AUTH_SECRET_KEY must be 32 bytes")
    return key


def key_available() -> bool:
    try:
        _master_key()
    except KeyUnavailableError:
        return False
    return True


def _subkey(purpose: bytes) -> bytes:
    return hmac.new(_master_key(), b"predigol/" + purpose, hashlib.sha256).digest()


def new_key_b64() -> str:
    """A fresh FBI_AUTH_SECRET_KEY value (for install scripts)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _aad(user_id: int) -> bytes:
    return f"predigol-totp:{user_id}".encode()


def seal_totp(user_id: int, secret: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return VERSION + nonce + AESGCM(_subkey(b"totp")).encrypt(nonce, secret, _aad(user_id))


def open_totp(user_id: int, sealed: bytes) -> bytes:
    """The secret, or KeyUnavailableError when it cannot be opened with this key (wrong key, wrong user, tampered)."""
    if len(sealed) < 1 + NONCE_BYTES + 16 or sealed[:1] != VERSION:
        raise KeyUnavailableError("unknown sealed-secret format")
    nonce, body = sealed[1:1 + NONCE_BYTES], sealed[1 + NONCE_BYTES:]
    try:
        return AESGCM(_subkey(b"totp")).decrypt(nonce, body, _aad(user_id))
    except Exception as exc:  # InvalidTag: another key, another user or a modified row
        raise KeyUnavailableError("the stored second-factor secret does not open with this key") from exc


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.strip().lower() if ch.isalnum())


def hash_recovery_code(user_id: int, code: str) -> str:
    msg = f"{user_id}:{normalize_recovery_code(code)}".encode()
    return hmac.new(_subkey(b"recovery"), msg, hashlib.sha256).hexdigest()


def new_recovery_code() -> str:
    """Ten characters (~49 bits) as xxxxx-xxxxx."""
    chars = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
    return f"{chars[:5]}-{chars[5:]}"


def new_temporary_password() -> str:
    """For an administrator's reset: 16 characters from the same unambiguous alphabet, upper and lower case."""
    alphabet = RECOVERY_ALPHABET + RECOVERY_ALPHABET.upper().replace("L", "").replace("I", "").replace("O", "")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw

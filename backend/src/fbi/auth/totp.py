"""Time-based one-time passwords (RFC 6238, HMAC-SHA1, 6 digits, 30 s): what Google Authenticator, Microsoft
Authenticator and every other authenticator app speak.

A code is accepted for the current step and one step either side (a phone clock a little off), and never twice: the
step of the last accepted code is stored and anything at or before it is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote, urlencode

import segno

DIGITS = 6
PERIOD = 30
SECRET_BYTES = 20
WINDOW = 1

_clock = time.time
"""The clock codes are checked against (tests move it forward instead of waiting 30 s)."""


def new_secret() -> bytes:
    return os.urandom(SECRET_BYTES)


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def grouped(secret_b32: str) -> str:
    """ABCD EFGH ... - what a person types into an app that cannot scan."""
    return " ".join(secret_b32[i:i + 4] for i in range(0, len(secret_b32), 4))


def step_at(at: float | None = None) -> int:
    return int((_clock() if at is None else at) // PERIOD)


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return f"{value:0{DIGITS}d}"


def normalize(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def matching_step(secret: bytes, code: str, *, last_step: int | None, at: float | None = None) -> int | None:
    """The step the code belongs to, or None. Codes at or before last_step are refused (no replay)."""
    digits = normalize(code)
    if len(digits) != DIGITS:
        return None
    now = step_at(at)
    found: int | None = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        # Compare every candidate: the time taken does not say which one matched.
        if hmac.compare_digest(code_at(secret, step), digits) and found is None:
            found = step
    if found is None or (last_step is not None and found <= last_step):
        return None
    return found


def provisioning_uri(secret: bytes, *, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode({"secret": b32(secret), "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS,
                       "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"


def qr_svg_data_uri(uri: str) -> str:
    """The provisioning URI as a QR code, an SVG data URI the page shows as an image: drawn here, so the secret never
    goes to a third-party QR service."""
    return str(segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#0d1512", light="#ffffff"))

"""TOTP against RFC 6238, the sealed secrets, recovery codes, and the request limits - without a database."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest

from fbi.api.limits import BodyLimit, SlidingWindow
from fbi.auth import crypto, totp
from fbi.auth.settings import reset as reset_auth_settings

RFC_SECRET = b"12345678901234567890"


@pytest.mark.parametrize(("t", "code"), [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"),
    (2000000000, "279037"), (20000000000, "353130"),
])
def test_codes_match_the_rfc_6238_vectors(t: int, code: str) -> None:
    # RFC 6238 appendix B (SHA-1), last six of the eight digits.
    assert totp.code_at(RFC_SECRET, totp.step_at(t)) == code


def test_a_code_is_accepted_one_step_either_side_and_never_twice() -> None:
    now = 1_800_000_000.0
    step = totp.step_at(now)
    for s in (step - 1, step, step + 1):
        assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, s), last_step=None, at=now) == s
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 2), last_step=None, at=now) is None
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step), last_step=step, at=now) is None
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), last_step=step, at=now) == step + 1
    assert totp.matching_step(RFC_SECRET, "12345", last_step=None, at=now) is None
    spaced = totp.code_at(RFC_SECRET, step)
    assert totp.matching_step(RFC_SECRET, f"{spaced[:3]} {spaced[3:]}", last_step=None, at=now) == step


def test_the_provisioning_uri_and_qr_carry_the_secret_for_any_authenticator() -> None:
    secret = totp.new_secret()
    uri = totp.provisioning_uri(secret, account="owner@predigol.test", issuer="PrediGol")
    assert uri.startswith("otpauth://totp/PrediGol:owner@predigol.test?")
    assert f"secret={totp.b32(secret)}" in uri and "issuer=PrediGol" in uri and "digits=6" in uri
    assert totp.qr_svg_data_uri(uri).startswith("data:image/svg+xml")
    assert totp.grouped("ABCDEFGHIJ") == "ABCD EFGH IJ"


def test_a_sealed_secret_opens_only_for_its_own_account_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = totp.new_secret()
    sealed = crypto.seal_totp(7, secret)
    assert secret not in sealed and crypto.open_totp(7, sealed) == secret
    with pytest.raises(crypto.KeyUnavailableError):
        crypto.open_totp(8, sealed)
    tampered = sealed[:-1] + bytes([sealed[-1] ^ 1])
    with pytest.raises(crypto.KeyUnavailableError):
        crypto.open_totp(7, tampered)
    monkeypatch.setenv("FBI_AUTH_SECRET_KEY", base64.b64encode(b"x" * 32).decode())
    reset_auth_settings()
    try:
        with pytest.raises(crypto.KeyUnavailableError):
            crypto.open_totp(7, sealed)
    finally:
        monkeypatch.undo()
        reset_auth_settings()


def test_without_a_valid_key_nothing_is_sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "not base64!", base64.b64encode(b"short").decode()):
        monkeypatch.setenv("FBI_AUTH_SECRET_KEY", value)
        reset_auth_settings()
        assert not crypto.key_available()
        with pytest.raises(crypto.KeyUnavailableError):
            crypto.seal_totp(1, b"x" * 20)
    monkeypatch.undo()
    reset_auth_settings()
    assert crypto.key_available()


def test_recovery_codes_are_unambiguous_and_hashed_per_account() -> None:
    codes = {crypto.new_recovery_code() for _ in range(200)}
    assert len(codes) == 200
    for c in codes:
        assert len(c) == 11 and c[5] == "-" and not set(c) & set("01ilo")
    code = next(iter(codes))
    h = crypto.hash_recovery_code(3, code)
    assert len(h) == 64 and code.replace("-", "") not in h
    assert crypto.hash_recovery_code(3, code.upper().replace("-", " ")) == h
    assert crypto.hash_recovery_code(4, code) != h


def test_temporary_passwords_are_strong() -> None:
    for _ in range(50):
        pw = crypto.new_temporary_password()
        assert len(pw) == 16 and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)


def test_the_sliding_window_counts_per_key_and_forgets_idle_keys() -> None:
    t = [0.0]
    w = SlidingWindow(per_window=3, window_s=60, clock=lambda: t[0])
    assert all(w.allow("a") for _ in range(3))
    assert not w.allow("a") and w.allow("b")
    t[0] = 61.0
    assert w.allow("a")
    w.PRUNE_EVERY = 1
    t[0] = 500.0
    w.allow("c")
    assert w.keys() == 1


def _call(app: BodyLimit, body: bytes, *, declared: bool, chunks: int = 1) -> tuple[int, bytes]:
    sent: list[dict[str, object]] = []
    parts = [body[i::chunks] for i in range(chunks)] if chunks > 1 else [body]
    queue = [{"type": "http.request", "body": p, "more_body": i < len(parts) - 1} for i, p in enumerate(parts)]
    headers = [(b"content-length", str(len(body)).encode())] if declared else []

    async def receive() -> dict[str, object]:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app({"type": "http", "method": "POST", "headers": headers}, receive, send))  # type: ignore[arg-type]
    status = next(int(m["status"]) for m in sent if m["type"] == "http.response.start")  # type: ignore[call-overload]
    return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")  # type: ignore[misc]


async def _echo(scope: dict[str, object], receive: Any, send: Any) -> None:
    total = b""
    while True:
        m = await receive()
        total += m.get("body", b"")
        if not m.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(len(total)).encode()})


def test_a_body_over_the_limit_is_refused_before_the_app_reads_it() -> None:
    app = BodyLimit(_echo, max_bytes=100)  # type: ignore[arg-type]
    assert _call(app, b"x" * 100, declared=True) == (200, b"100")
    status, body = _call(app, b"x" * 101, declared=True)
    assert status == 413 and b"payload_too_large" in body
    status, _ = _call(app, b"x" * 300, declared=False, chunks=3)
    assert status == 413
    assert _call(app, b"x" * 90, declared=False, chunks=3)[0] == 200

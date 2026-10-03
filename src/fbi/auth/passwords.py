"""Password hashing: Argon2id, parameters stored inside every hash.

The parameters are the RFC 9106 "second recommended option" scaled to an interactive
login on one machine: 64 MiB, three passes, two lanes. A hash made with weaker
parameters is upgraded the next time its owner signs in (``needs_rehash``).
"""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 128

_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16,
                         type=Type.ID)


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True only for the right password. A malformed hash is a mismatch, never an error page."""
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash("not-a-password-anybody-has")


def burn_verification_time(password: str) -> None:
    """Spend what a real verification costs, so an unknown address is not faster to reject
    than a wrong password - the difference would tell an attacker which addresses exist."""
    verify_password(_dummy_hash(), password)


def password_problems(password: str, *, email: str | None = None) -> list[str]:
    """Machine-readable reasons a new password is refused; empty when it is acceptable."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append("password_too_short")
    if len(password) > MAX_LENGTH:
        problems.append("password_too_long")
    if password.strip() != password:
        problems.append("password_edge_whitespace")
    if email and password.strip().lower() in {email.lower(), email.split("@", 1)[0].lower()}:
        problems.append("password_is_email")
    if len(set(password)) < 4:
        problems.append("password_too_simple")
    return problems

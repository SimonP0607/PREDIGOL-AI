"""Passwords: Argon2id hashing and the one rule every new password meets.

Hashing: the parameters are the RFC 9106 "second recommended option" scaled to an interactive login on one machine:
64 MiB, three passes, two lanes. A hash made with weaker parameters is upgraded the next time its owner signs in
(``needs_rehash``).

The rule (R11 of the security plan, built with plan UX A7 - the phase that comes first meets both): at least 15
characters, or 12 when the account uses a second factor; at most 128, so long phrases fit; no composition rules and no
periodic expiry; not one of the common passwords of a breach corpus (``common_passwords.txt``), not the service's name,
the address or the name of the account, and not a trivial repetition or run. One validator for every way a password is
chosen: activation, change, recovery, the owner's temporary password and the command line. Pasting and password
managers are welcome; the pages show a meter.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 15
"""Without a second factor (R11)."""
MIN_LENGTH_WITH_MFA = 12
MAX_LENGTH = 128
CONTEXT_WORDS = ("predigol",)
"""Words of the service a password may not contain, besides the account's own address and name."""
COMMON_FILE = Path(__file__).resolve().parent / "common_passwords.txt"

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


def unusable_hash() -> str:
    """An Argon2id hash of a random password nobody is told (plan UX, A7): the hash of an invited account before it
    chooses its own, and of an anonymised one. It satisfies the rule of ``auth.users.password_hash`` and verifies
    nothing anybody can type."""
    return _HASHER.hash(secrets.token_urlsafe(48))


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash("not-a-password-anybody-has")


def burn_verification_time(password: str) -> None:
    """Spend what a real verification costs, so an unknown address is not faster to reject
    than a wrong password - the difference would tell an attacker which addresses exist."""
    verify_password(_dummy_hash(), password)


def min_length(*, has_mfa: bool) -> int:
    return MIN_LENGTH_WITH_MFA if has_mfa else MIN_LENGTH


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    """The breach corpus' common passwords long enough to pass the length rule, lower-cased."""
    lines = COMMON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def _folded(text: str) -> str:
    """Lower case, accents off, letters and digits only: «María-José» -> «mariajose»."""
    plain = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in plain if not unicodedata.combining(c)))


def _context_words(email: str | None, name: str | None) -> list[str]:
    words = list(CONTEXT_WORDS)
    if email:
        words.append(_folded(email.split("@", 1)[0]))
    if name:
        words.extend(_folded(part) for part in re.split(r"\W+", name))
    return [w for w in words if len(w) >= 4]


def _step(a: str, b: str) -> int | None:
    """+1 or -1 when ``b`` follows ``a`` in a run of letters or digits (``9`` then ``0`` counts as one more)."""
    if a.isdigit() and b.isdigit():
        d = (int(b) - int(a)) % 10
        return 1 if d == 1 else -1 if d == 9 else None
    if a.isalpha() and b.isalpha() and a.isascii() and b.isascii():
        d = ord(b.lower()) - ord(a.lower())
        return d if d in (1, -1) else None
    return None


def _trivial(password: str) -> bool:
    """Too few different characters, one short unit repeated (three times at least), or one run of letters or digits
    from end to end (``abcdefghijklmno``, ``123456789012345``)."""
    if len(set(password)) < 4:
        return True
    n = len(password)
    for unit in range(1, n // 3 + 1):
        if all(password[i] == password[i % unit] for i in range(n)):
            return True
    steps = {_step(a, b) for a, b in pairwise(password)}
    return n > 2 and len(steps) == 1 and None not in steps


def password_problems(password: str, *, email: str | None = None, name: str | None = None,
                      has_mfa: bool = False) -> list[str]:
    """Machine-readable reasons a new password is refused; empty when it is acceptable. ``has_mfa``: the account uses
    a second factor (then 12 characters are enough instead of 15)."""
    problems: list[str] = []
    if len(password) < min_length(has_mfa=has_mfa):
        problems.append("password_too_short")
    if len(password) > MAX_LENGTH:
        problems.append("password_too_long")
    if password.strip() != password:
        problems.append("password_edge_whitespace")
    lowered = password.strip().lower()
    if email and lowered in {email.lower(), email.split("@", 1)[0].lower()}:
        problems.append("password_is_email")
    elif any(word in _folded(password) for word in _context_words(email, name)):
        problems.append("password_has_context")
    if _trivial(password):
        problems.append("password_too_simple")
    if lowered in common_passwords():
        problems.append("password_common")
    return problems

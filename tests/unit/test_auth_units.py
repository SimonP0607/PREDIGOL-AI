"""Passwords, tokens, roles and the sign-in throttle - without a database."""

from __future__ import annotations

import pytest

from fbi.auth import passwords, tokens
from fbi.auth.roles import Permission, Role, permissions_for
from fbi.auth.throttle import FailureWindow


def test_a_password_hash_is_argon2id_and_verifies_only_the_right_password() -> None:
    h = passwords.hash_password("correct horse battery")
    assert h.startswith("$argon2id$") and "correct horse" not in h
    assert passwords.verify_password(h, "correct horse battery")
    assert not passwords.verify_password(h, "correct horse battery ")
    assert not passwords.verify_password("not-a-hash", "anything")
    assert not passwords.needs_rehash(h)


def test_two_hashes_of_one_password_differ() -> None:
    assert passwords.hash_password("same password 1") != passwords.hash_password("same password 1")


@pytest.mark.parametrize(("pw", "problem"), [
    ("short1A", "password_too_short"),
    (" leading-space-pw", "password_edge_whitespace"),
    ("aaaaaaaaaaaa", "password_too_simple"),
    ("someone@example.com", "password_is_email"),
    ("x" * 129, "password_too_long"),
])
def test_weak_passwords_are_refused_with_a_code(pw: str, problem: str) -> None:
    assert problem in passwords.password_problems(pw, email="someone@example.com")


def test_a_reasonable_password_passes() -> None:
    assert passwords.password_problems("Tr4ck-the-line-2026", email="a@b.co") == []


def test_tokens_are_random_and_stored_only_as_their_hash() -> None:
    a, b = tokens.new_token(), tokens.new_token()
    assert a != b and tokens.looks_like_token(a)
    assert tokens.token_id(a) != a and len(tokens.token_id(a)) == 64
    assert not tokens.looks_like_token("short") and not tokens.looks_like_token(None)
    assert not tokens.looks_like_token("x" * 40 + "'; DROP TABLE")


def test_a_user_reaches_the_product_and_nothing_else() -> None:
    assert permissions_for("USER") == frozenset({Permission.APP})
    assert permissions_for("SUPER_ADMIN") == frozenset(Permission)
    assert permissions_for("SOMETHING_NEW") == frozenset()
    assert {r.value for r in Role} == {"SUPER_ADMIN", "USER"}


def test_only_failures_count_towards_the_throttle() -> None:
    t = [0.0]
    w = FailureWindow(max_failures=3, window_s=60, clock=lambda: t[0])
    for _ in range(3):
        assert not w.blocked("a@b.co")
        w.fail("a@b.co")
    assert w.blocked("a@b.co") and w.retry_after("a@b.co") > 0
    assert not w.blocked("other@b.co")
    t[0] = 61.0
    assert not w.blocked("a@b.co")
    w.fail("a@b.co")
    w.clear("a@b.co")
    assert not w.blocked("a@b.co")

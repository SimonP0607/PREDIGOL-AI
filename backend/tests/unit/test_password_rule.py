"""The one rule every new password meets (R11 of the security plan, built with plan UX A7): long rather than complex,
not from a breach corpus, not the service's or the account's own words, not a trivial repetition or run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fbi.auth import passwords
from fbi.auth.passwords import MAX_LENGTH, common_passwords, min_length, password_problems


def test_fifteen_characters_or_twelve_with_a_second_factor_and_never_more_than_128() -> None:
    assert (min_length(has_mfa=False), min_length(has_mfa=True), MAX_LENGTH) == (15, 12, 128)
    assert "password_too_short" in password_problems("Tiene-12-car")  # 12 characters, no second factor
    assert "password_too_short" not in password_problems("Tiene-12-car", has_mfa=True)
    assert "password_too_short" in password_problems("Once-11-car", has_mfa=True)
    assert password_problems("quince letras ok") == []  # 16, with spaces inside: phrases are welcome
    assert "password_too_long" in password_problems("una frase muy larga " * 7)


@pytest.mark.parametrize("password", ["password1234", "Password1234", "iloveyou1234", "123456789012"])
def test_a_common_password_is_refused_whatever_its_case(password: str) -> None:
    assert "password_common" in password_problems(password, has_mfa=True)


def test_the_corpus_is_loaded_lower_cased_and_only_what_the_length_rule_lets_through() -> None:
    corpus = common_passwords()
    assert len(corpus) > 1000
    assert all(12 <= len(p) <= 128 and p == p.lower() for p in corpus)
    assert not any(p.startswith("#") for p in corpus), "the file's header is not a password"


@pytest.mark.parametrize(("password", "email", "name"), [
    ("mi-predigol-favorito-2026", None, None),                   # the service's name
    ("Simon.Perez-cuenta-2026", "simon.perez@example.com", None),  # the address, separators aside
    ("Golazo-de-Mariajose-2026", "x@example.com", "María José"),     # the name, accents aside
])
def test_the_services_name_and_the_accounts_address_and_name_are_refused(password: str, email: str | None,
                                                                         name: str | None) -> None:
    assert "password_has_context" in password_problems(password, email=email, name=name)


def test_short_parts_of_a_name_or_an_address_are_not_words_to_refuse() -> None:
    assert password_problems("ana-y-el-golazo-26", email="ana@example.com", name="Ana Li") == []
    assert password_problems("anita@example.com", email="anita@example.com") == ["password_is_email"]


@pytest.mark.parametrize("password", ["aaaaaaaaaaaaaaaa", "abababababababab", "abcabcabcabcabca", "abcdefghijklmnop",
                                      "123456789012345", "9876543210987654", "zyxwvutsrqponmlk"])
def test_a_trivial_repetition_or_run_is_refused(password: str) -> None:
    assert "password_too_simple" in password_problems(password)


def test_a_good_phrase_passes_and_every_reason_is_a_known_code() -> None:
    for phrase in ("correct horse battery staple", "Tr4ck-the-line-2026", "la-final-se-juega-en-mayo"):
        assert password_problems(phrase, email="someone@example.com", name="Someone Else") == [], phrase
    codes = {"password_too_short", "password_too_long", "password_edge_whitespace", "password_is_email",
             "password_has_context", "password_too_simple", "password_common"}
    seen = set(password_problems(" predigol "))
    assert seen <= codes and {"password_too_short", "password_edge_whitespace", "password_has_context"} <= seen


def test_the_owners_generated_temporary_password_meets_the_rule() -> None:
    from fbi.auth import crypto

    for _ in range(50):
        assert password_problems(crypto.new_temporary_password()) == []
    assert passwords.MIN_LENGTH <= 16


CASES = json.loads((Path(__file__).with_name("password_rule_cases.json")).read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["password"][:24] for c in CASES])
def test_the_backend_and_the_page_agree_case_by_case(case: dict[str, object]) -> None:
    """The same cases web/src/lib/auth/passwordRule.test.ts checks: the page's meter says what the server will say
    (the common-password list aside, which only the server has)."""
    email = str(case["email"]) if "email" in case else None
    name = str(case["name"]) if "name" in case else None
    found = [p for p in password_problems(str(case["password"]), email=email, name=name,
                                          has_mfa=bool(case.get("has_mfa"))) if p != "password_common"]
    assert found == case["problems"]

"""How a referee's name is read and when two spellings can be one person (plan F3, the words of ``refid-v1``)."""

from __future__ import annotations

import pytest

from fbi.people import referee_names as rn
from fbi.people.countries import UNKNOWN_SCOPE, country_key, country_name, plain, scope_of

# ── the four shapes the provider writes ──────────────────────────────────────────────────────────────────────────────


def test_a_name_with_an_initial() -> None:
    p = rn.parse_referee("M. Oliver")
    assert p is not None
    assert (p.display, p.key, p.country, p.layout) == ("M. Oliver", "m oliver", None, "name")


def test_a_name_and_its_country() -> None:
    p = rn.parse_referee("Michael Oliver", "England")
    assert p is not None
    assert (p.display, p.key, p.country, p.layout) == ("Michael Oliver", "michael oliver", "england", "name_country")


def test_surname_first_arrives_cut_at_the_first_comma_and_is_put_back() -> None:
    """``split_referee`` cut 'Brooks, John, England' into referee 'Brooks' and country 'John, England': 291 rows in the
    history. The two columns put back together are the string the provider wrote."""
    assert rn.provider_string("Brooks", "John, England") == "Brooks, John, England"
    p = rn.parse_referee("Brooks", "John, England")
    assert p is not None
    assert (p.display, p.key, p.country, p.layout) == ("John Brooks", "john brooks", "england", "surname_given_country")


def test_surname_first_with_two_given_names_and_a_country() -> None:
    p = rn.parse_referee("Hilfer", "Leandro Rey, Argentina")
    assert p is not None
    assert (p.display, p.key, p.country) == ("Leandro Rey Hilfer", "leandro rey hilfer", "argentina")


def test_surname_first_without_a_country() -> None:
    p = rn.parse_referee("Brooks", "John")
    assert p is not None
    assert (p.display, p.country, p.layout) == ("John Brooks", None, "surname_given")
    # ...and the same person written given-name first is the same key
    q = rn.parse_referee("John Brooks", "England")
    assert q is not None and q.key == p.key


def test_the_country_is_read_through_its_other_spellings() -> None:
    for written in ("Türkiye", "Turkey", "turkiye"):
        p = rn.parse_referee("Cüneyt Çak\u0131r", written)
        assert p is not None and p.country == "turkey", written
    p = rn.parse_referee("Karel Petrik", "Czech-Republic")
    assert p is not None and p.country == "czech republic"


def test_accents_case_and_spacing_do_not_make_a_new_name() -> None:
    a = rn.parse_referee("  Antonio   Miguel Mateu  Lahoz ", "Spain")
    b = rn.parse_referee("ANTONIO MIGUEL MATEU LAHOZ")
    assert a is not None and b is not None and a.key == b.key == "antonio miguel mateu lahoz"
    c = rn.parse_referee("Cüneyt Çak\u0131r")
    assert c is not None and c.key == "cuneyt cakir"
    d = rn.parse_referee("Jean-Claude D'Amico")
    assert d is not None and d.key == "jean claude damico"  # an apostrophe leaves no gap: "D'Amico" is not an initial


@pytest.mark.parametrize("referee", [None, "", "   ", ",", " , "])
def test_no_name_is_no_referee(referee: str | None) -> None:
    assert rn.parse_referee(referee) is None
    assert rn.parse_referee(referee, "England") is None


def test_a_word_that_is_not_a_country_is_a_given_name() -> None:
    p = rn.parse_referee("Smith", "Jonathan")
    assert p is not None and p.country is None and p.key == "jonathan smith"


# ── the countries ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_country_keys_and_names() -> None:
    assert country_key("Türkiye") == country_key("Turkey") == "turkey"
    assert country_key("Czech-Republic") == country_key("Czechia") == "czech republic"
    assert country_key("USA") == country_key("United States") == "usa"
    assert country_key("Côte d'Ivoire") == country_key("Ivory Coast") == "ivory coast"
    assert country_key("Nowhere") is None
    assert country_key("") is None and country_key(None) is None
    assert country_name("czech republic") == "Czech Republic"
    assert country_name(None) is None and country_name(UNKNOWN_SCOPE) is None


def test_the_scope_of_an_observation() -> None:
    # the provider wrote a country: it wins, even in a domestic league of another one
    assert scope_of("Australia", "England", "domestic_league") == "australia"
    # no country: the country of a domestic competition
    assert scope_of(None, "England", "domestic_league") == "england"
    assert scope_of(None, "Czech-Republic", "domestic_cup") == "czech republic"
    # a country this list does not know still makes a scope: two spellings of it agree with each other
    assert scope_of(None, "Atlantis", "domestic_league") == "atlantis"
    # a competition that belongs to no country says nothing
    assert scope_of(None, "World", "continental") == UNKNOWN_SCOPE
    assert scope_of(None, "England", "international") == UNKNOWN_SCOPE
    assert scope_of(None, "World", "domestic_league") == UNKNOWN_SCOPE
    assert scope_of(None, None, None) == UNKNOWN_SCOPE


def test_plain() -> None:
    assert plain("Türkiye") == "turkiye"
    assert plain("Côte d'Ivoire") == "cote divoire"
    assert plain("  A--B ") == "a b"
    assert plain(None) == ""


# ── the relations between two spellings ──────────────────────────────────────────────────────────────────────────────


def test_initial_forms() -> None:
    assert rn.is_initial_form("m oliver")
    assert rn.is_initial_form("j m oliver")
    assert not rn.is_initial_form("michael oliver")
    assert not rn.is_initial_form("oliver")
    assert not rn.is_initial_form("m")


def test_an_initial_is_a_spelling_of_a_full_name_that_begins_with_it_and_ends_like_it() -> None:
    assert rn.initial_matches_full("m oliver", "michael oliver")
    assert rn.initial_matches_full("m oliver", "mark oliver")  # the rule alone cannot tell: the identity layer asks for ONE
    assert rn.initial_matches_full("j sanchez martinez", "jose maria sanchez martinez")
    assert not rn.initial_matches_full("m oliver", "oliver michael")
    assert not rn.initial_matches_full("m oliver", "michael taylor")
    assert not rn.initial_matches_full("m oliver", "n oliver")
    assert not rn.initial_matches_full("m oliver", "m oliver")  # an initial is not a full name
    assert not rn.initial_matches_full("michael oliver", "michael oliver")


def test_a_longer_name_is_the_same_name_with_a_middle_name() -> None:
    assert rn.is_extension("danny makkelie", "danny desmond makkelie")
    assert rn.is_extension("danny desmond makkelie", "danny makkelie")
    assert rn.is_extension("luca pairetto", "luca j pairetto")
    assert rn.is_extension("jose sanchez", "jose maria sanchez")
    assert not rn.is_extension("danny makkelie", "danny makkelie")
    assert not rn.is_extension("michael oliver", "mark oliver")
    assert not rn.is_extension("jose maria sanchez", "jose carlos sanchez")
    assert not rn.is_extension("m oliver", "m j oliver")  # initials say too little to be called the same name
    assert not rn.is_extension("jose sanchez", "jose sanchez martinez")  # the surname has to end alike


def test_a_typing_variant_differs_in_one_word_by_a_couple_of_letters() -> None:
    assert rn.is_spelling_variant("christian ballweg", "cristian ballweg")
    assert rn.is_spelling_variant("vassilios fotias", "vassilis fotias")
    assert rn.is_spelling_variant("eric lambrechts", "erik lambrechts")
    assert not rn.is_spelling_variant("michael oliver", "michael oliver")
    assert not rn.is_spelling_variant("mark clattenburg", "mike clattenburg")
    assert not rn.is_spelling_variant("m oliver", "n oliver")
    assert not rn.is_spelling_variant("john smith", "jon smyth")  # two words differ


def test_two_full_names_conflict_when_nothing_relates_them() -> None:
    assert rn.names_conflict("andres rojas", "antonio rojas")
    assert rn.names_conflict("mohamed hassan", "muhammad hassan")
    assert not rn.names_conflict("danny makkelie", "danny desmond makkelie")
    assert not rn.names_conflict("eric lambrechts", "erik lambrechts")
    assert not rn.names_conflict("michael oliver", "michael oliver")
    # an initial says too little to contradict anything
    assert not rn.names_conflict("a rojas", "antonio rojas")
    assert not rn.names_conflict("a rojas", "andres rojas")

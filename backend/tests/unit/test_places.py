"""How a ground and a city are read from a payload and compared (fbi.core.places)."""

from __future__ import annotations

import pytest

from fbi.core.places import cities_agree, cities_compatible, place_key, same_place, split_place


@pytest.mark.parametrize("name, city, expected", [
    # the provider writes the city in brackets after the name, with no city beside it
    ("Stadion Feijenoord (Rotterdam)", None, ("Stadion Feijenoord", "Rotterdam")),
    ("Estadio Universitario de Nuevo León (San Nicolás de los Garza)", None,
     ("Estadio Universitario de Nuevo León", "San Nicolás de los Garza")),
    ("Toyota Stadium(Texas)", None, ("Toyota Stadium", "Texas")),
    # a local spelling with the usual one inside: the last top-level group is the city
    ("New Suez Stadium (as-Suways (Suez))", None, ("New Suez Stadium", "as-Suways (Suez)")),
    # a city that is given wins; the bracket is dropped from the name all the same
    ("Estadio Universitario (UANL)", "Monterrey", ("Estadio Universitario", "Monterrey")),
    ("Stade Sébastien-Charléty (Paris)", "Paris", ("Stade Sébastien-Charléty", "Paris")),
    # nothing to take out
    ("Wembley Stadium", "London", ("Wembley Stadium", "London")),
    ("Estadio (Norte) Grande", None, ("Estadio (Norte) Grande", None)),
    # degenerate input is returned as it came, never as an empty name
    ("(Rotterdam)", None, ("(Rotterdam)", None)),
    ("Unbalanced (Rotterdam", None, ("Unbalanced (Rotterdam", None)),
    ("Name ()", None, ("Name ()", None)),
    ("  Spaced  ", "  Town ", ("Spaced", "Town")),
    ("  ", "  ", (None, None)),
    (None, None, (None, None)),
])
def test_the_bracket_after_a_ground_s_name_is_its_city(name: str | None, city: str | None,
                                                       expected: tuple[str | None, str | None]) -> None:
    assert split_place(name, city) == expected


def test_a_split_ground_is_the_same_place_as_its_plain_spelling() -> None:
    name, city = split_place("Stadion Feijenoord (Rotterdam)")
    assert same_place(name, "Stadion Feijenoord")
    assert cities_agree(city, "Rotterdam")
    name, city = split_place("New Suez Stadium (as-Suways (Suez))")
    assert same_place(name, "New Suez Stadium") and cities_agree(city, "Suez"), "the usual spelling is inside the local one"


def test_cities_that_do_not_contradict_each_other() -> None:
    assert cities_compatible("Newcastle", "Newcastle upon Tyne")
    assert cities_compatible("Saint-Denis", "saint denis")
    assert cities_compatible(None, "Rotterdam") and cities_compatible("", "Rotterdam")
    assert not cities_compatible("Lyon", "Décines-Charpieu")
    assert not cities_compatible("Torino", "Turin"), "a name in another language is not guessed"


def test_a_missing_city_is_not_agreement() -> None:
    assert cities_agree("Birmingham", "Birmingham")
    assert not cities_agree(None, "Birmingham") and not cities_agree("Birmingham", None)


def test_the_comparison_key_ignores_case_accents_and_punctuation() -> None:
    assert place_key("İstanbul") == place_key("Istanbul") == "istanbul"
    assert place_key("Ciudad de Lanús - Néstor") == "ciudad de lanus nestor"
    assert place_key(None) == "" and place_key("!!") == ""

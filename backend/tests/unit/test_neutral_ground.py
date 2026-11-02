"""Which country a ground is in, and which countries it may be in (fbi.catalog.neutral_store.ground_of).

The venues table has a few wrong countries, the teams filed under a ground can be wrong with it, and the provider labels a
few clubs with another country. A country is used only where every source that answers says the same; where they do not,
the ground has no country, but it keeps the countries the sources name - the net a host nation is looked for in."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fbi.catalog.neutral_store import DISPUTED, Reference, VenueIndex, ground_of, possible_countries
from fbi.core.places import place_key

LABELS = frozenset({"England", "Kenya", "Uganda", "Saudi-Arabia", "United-Arab-Emirates", "Qatar", "USA", "Spain"})


def reference(venues: list[tuple[int, str, str | None, str]] | None = None,
              league: dict[tuple[str, str], dict[str, int]] | None = None,
              team_home: dict[int, dict[str, int]] | None = None,
              cities: dict[str, dict[str, int]] | None = None,
              labels: frozenset[str] = LABELS) -> Reference:
    return Reference(
        labels=labels,
        venues=VenueIndex(venues or []),
        league={k: Counter(v) for k, v in (league or {}).items()},
        team_home={k: Counter(v) for k, v in (team_home or {}).items()},
        cities={place_key(k): Counter(v) for k, v in (cities or {}).items()},
    )


def row(name: str, city: str | None, *, venue_id: int | None = None, v_name: str | None = None,
        v_city: str | None = None, v_country: str | None = None) -> dict[str, Any]:
    return {"venue_id": venue_id, "venue_name": name, "venue_city": city, "v_name": v_name, "v_city": v_city,
            "v_country": v_country}


def key(name: str, city: str) -> tuple[str, str]:
    return place_key(name), place_key(city)


def test_a_ground_every_source_places_in_one_country_has_that_country() -> None:
    ref = reference(venues=[(1, "Wembley Stadium", "London", "England")],
                    league={key("Wembley Stadium", "London"): {"England": 12}},
                    team_home={1: {"England": 1}},
                    cities={"London": {"England": 900}})
    g = ground_of(row("Wembley Stadium", "London"), ref)
    assert (g.country, g.country_basis) == ("England", "venues_table+league_home_matches+team_home_venue")
    assert g.countries == frozenset(), "a settled country is the country: nothing else to look in"
    assert g.possible_countries == frozenset({"England"})


def test_sources_that_disagree_leave_no_country_but_keep_every_country_they_name() -> None:
    # Dammam: the table says Saudi Arabia; the league matches there were played by Saudi sides and by Al Khaleej Saihat,
    # whom the provider files under the Emirates
    ref = reference(venues=[(3279, "Prince Mohamed bin Fahd Stadium", "Dammam", "Saudi-Arabia")],
                    league={key("Prince Mohamed bin Fahd Stadium", "Dammam"):
                            {"Saudi-Arabia": 89, "United-Arab-Emirates": 68}},
                    team_home={3279: {"United-Arab-Emirates": 1, "Saudi-Arabia": 1}},
                    cities={"Dammam": {"Saudi-Arabia": 158, "United-Arab-Emirates": 68}})
    g = ground_of(row("Prince Mohamed bin Fahd Stadium", "Dammam"), ref)
    assert (g.country, g.country_basis) == (None, DISPUTED)
    assert g.countries == frozenset({"Saudi-Arabia", "United-Arab-Emirates"})
    assert g.possible_countries == g.countries


def test_a_few_league_matches_are_not_enough_to_name_a_country_but_they_are_a_place_to_look() -> None:
    # La Cartuja: two league matches only (a ground used for a final and a Supercopa): the country is "disputed" only
    # because there is too little to say; the countries it may be in are still those
    ref = reference(league={key("Estadio de la Cartuja", "Seville"): {"Spain": 2}}, cities={"Seville": {"Spain": 45}})
    g = ground_of(row("Estadio de la Cartuja", "Seville"), ref)
    assert (g.country, g.country_basis) == (None, DISPUTED)
    assert g.countries == frozenset({"Spain"})


def test_a_wrong_country_in_the_table_is_vetoed_by_the_city_and_both_countries_are_kept() -> None:
    # a stadium of Kampala filed under Kenya (the Kenyan national side's "home"), in a city whose league matches were
    # played in Uganda
    ref = reference(venues=[(9, "Mandela National Stadium", "Kampala", "Kenya")],
                    team_home={9: {"Kenya": 1}},
                    cities={"Kampala": {"Uganda": 120}})
    g = ground_of(row("Mandela National Stadium", "Kampala"), ref)
    assert (g.country, g.country_basis) == (None, DISPUTED)
    assert g.countries == frozenset({"Kenya", "Uganda"})


def test_a_ground_no_source_names_takes_the_countries_its_city_was_played_in() -> None:
    # Hard Rock Stadium: no league match, nothing in the table, but league matches were played in cities of that name
    ref = reference(cities={"Miami Gardens, Florida": {"USA": 41}})
    g = ground_of(row("Hard Rock Stadium", "Miami Gardens, Florida"), ref)
    assert (g.country, g.country_basis) == (None, None)
    assert g.countries == frozenset({"USA"})


def test_a_city_with_a_few_matches_only_is_not_a_witness() -> None:
    ref = reference(cities={"Pasadena": {"USA": 2}})
    assert ground_of(row("Rose Bowl", "Pasadena"), ref).countries == frozenset()


def test_a_ground_nothing_says_anything_about_has_no_countries_at_all() -> None:
    g = ground_of(row("Estadio X", "Ciudad Y"), reference())
    assert (g.country, g.country_basis, g.countries) == (None, None, frozenset())
    assert g.possible_countries == frozenset()


def test_only_countries_some_team_carries_as_its_label_are_kept() -> None:
    # a side can only be compared with a label it carries
    ref = reference(cities={"Doha": {"Qatar": 700, "World": 5}}, labels=frozenset({"Qatar"}))
    assert ground_of(row("Education City Stadium", "Doha"), ref).countries == frozenset({"Qatar"})


def test_the_possible_countries_are_a_union_never_a_vote() -> None:
    # a single league match by a Saudi-labelled side is enough for Saudi Arabia to be among them: a wider net only turns a
    # neutral into "no evidence"
    ref = reference(league={key("Stadium", "Town"): {"Qatar": 50, "Saudi-Arabia": 1}})
    assert possible_countries(ref, "Stadium", "Town", (), {}) == frozenset({"Qatar", "Saudi-Arabia"})
    assert ground_of(row("Stadium", "Town"), ref).country_basis == "league_home_matches", "the majority still names it"

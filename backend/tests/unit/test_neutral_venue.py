"""Whether a match is at a neutral venue (fbi.catalog.neutral, rule neutral-v1; plan F0, defect 1).

The rule is precision first: it says neutral only on positive evidence, and every doubt reads "not neutral". These
tests are the cases that taught that: finals and semi-finals at a stadium of neither side, a host nation, a club at a
ground of its own city, a venue id that points at another ground, a league match abroad, and every way the evidence can
be missing."""

from __future__ import annotations

import pytest

from fbi.catalog.neutral import (
    MIN_COUNT,
    MIN_HISTORY,
    RULE_VERSION,
    FixtureFacts,
    Ground,
    Presence,
    Shared,
    Side,
    classify,
    is_final,
    is_semi,
    presence,
    same_ground,
    usual_grounds,
)


def home_matches(name: str, city: str, n: int = 20, *, venue_id: int | None = None) -> tuple[Ground, ...]:
    return tuple(Ground(name, city, venue_id) for _ in range(n))


def club(team_id: int, country: str, name: str, city: str, *, n: int = 20) -> Side:
    return Side(team_id, country, False, home_matches(name, city, n))


def national(team_id: int, country: str | None) -> Side:
    return Side(team_id, country, True)


def facts(competition_type: str, rnd: str | None, ground: Ground, home: Side, away: Side,
          *, shared: Shared | None = None, legs: int = 1) -> FixtureFacts:
    return FixtureFacts(1, competition_type, rnd, ground, home, away, shared, legs)


WEMBLEY = Ground("Wembley Stadium", "London", 1, "England", "venue_id")
REAL = club(1, "Spain", "Estadio Santiago Bernabéu", "Madrid")
DORTMUND = club(2, "Germany", "Signal Iduna Park", "Dortmund")
CHELSEA = club(3, "England", "Stamford Bridge", "London")
ARSENAL = club(4, "England", "Emirates Stadium", "London")
EVERTON = club(5, "England", "Goodison Park", "Liverpool")
WIGAN = club(6, "England", "DW Stadium", "Wigan")


def test_a_final_in_a_third_country_is_neutral() -> None:
    v = classify(facts("continental", "Final", WEMBLEY, REAL, DORTMUND))
    assert (v.neutral, v.basis, v.rule) == (True, "third_country", RULE_VERSION)
    assert v.evidence["home"]["presence"] == "elsewhere"


def test_a_semi_final_is_neutral_only_when_its_twin_is_played_at_the_same_ground() -> None:
    # FA Cup: both semi-finals at Wembley on one weekend. The round alone says nothing - a single-match semi-final is
    # drawn at one side's own ground as often as it is played at a neutral one.
    twin = Shared(matches=2, home_sides=2, twins=1)
    v = classify(facts("domestic_cup", "Semi-finals", WEMBLEY, EVERTON, WIGAN, shared=twin))
    assert (v.neutral, v.basis) == (True, "semi_pair_ground")
    assert v.evidence["shared"] == {"matches": 2, "twins": 1}
    for alone in (Shared(matches=1, home_sides=1), Shared(matches=2, home_sides=2), None):
        v = classify(facts("domestic_cup", "Semi-finals", WEMBLEY, EVERTON, WIGAN, shared=alone))
        assert (v.neutral, v.basis) == (False, "no_evidence"), alone


def test_a_semi_final_at_a_ground_the_history_spells_otherwise_is_not_called_neutral() -> None:
    # Lyon v Rennes, Coupe de France semi-final, at 'Parc Olympique Lyonnais': the league matches say 'Groupama
    # Stadium', in another town. No twin semi-final there: nothing says neutral
    lyon = club(70, "France", "Groupama Stadium", "Décines-Charpieu")
    rennes = club(71, "France", "Roazhon Park", "Rennes")
    here = Ground("Parc Olympique Lyonnais", "Lyon")
    alone = Shared(matches=1, home_sides=1)
    v = classify(facts("domestic_cup", "Semi-finals", here, lyon, rennes, shared=alone))
    assert (v.neutral, v.basis) == (False, "no_evidence")


def test_the_ground_the_provider_gives_as_a_side_s_own_is_its_home_whatever_the_history_calls_it() -> None:
    # KNVB Beker final at 'Stadion Feijenoord': Feyenoord's league matches call it 'De Kuip'; the provider's own venue for
    # Feyenoord is 'Stadion Feijenoord'
    feyenoord = Side(75, "Netherlands", False, home_matches("De Kuip", "Rotterdam"),
                     homes=(Ground("Stadion Feijenoord", "Rotterdam", 359),))
    ajax = club(76, "Netherlands", "Johan Cruijff ArenA", "Amsterdam")
    kuip = Ground("Stadion Feijenoord", "Rotterdam")
    v = classify(facts("domestic_cup", "Final", kuip, feyenoord, ajax))
    assert (v.neutral, v.basis) == (False, "home_ground")
    assert v.evidence["home"]["why"].startswith("the ground the provider gives")
    assert classify(facts("domestic_cup", "Final", kuip, ajax, feyenoord)).basis == "away_ground"
    # the same final between two other clubs is neutral there
    psv = club(77, "Netherlands", "Philips Stadion", "Eindhoven")
    assert classify(facts("domestic_cup", "Final", kuip, psv, ajax)).basis == "decider_ground"
    # a side whose history says nothing is still known to be at home at the ground the provider gives as its own, and is
    # still not said to be away from anywhere else
    promoted = Side(78, "Netherlands", False, (), homes=(Ground("Stadion Feijenoord", "Rotterdam"),))
    assert classify(facts("domestic_cup", "Final", kuip, promoted, ajax)).basis == "home_ground"
    elsewhere = Ground("Wembley Stadium", "London")
    v = classify(facts("domestic_cup", "Final", elsewhere, promoted, ajax))
    assert (v.neutral, v.evidence["home"]["presence"]) == (False, "unknown")


def test_a_final_at_a_finalist_s_ground_under_another_name_is_a_known_limit() -> None:
    # 2023 Libertadores final at the Maracanã with Fluminense, whose league matches call the ground 'Jornalista Mário
    # Filho' and for which the provider names no venue: called neutral. Documented in fbi.catalog.neutral; a finalist
    # whose declared ground matches is caught (the test above). This test pins the limit so that it is not forgotten
    fluminense = club(79, "Brazil", "Estadio Jornalista Mário Filho", "Rio de Janeiro")
    boca = club(80, "Argentina", "Estadio Alberto José Armando", "Buenos Aires")
    maracana = Ground("Estádio do Maracanã", "Rio de Janeiro", None, "Brazil", "venues_table")
    v = classify(facts("continental", "Final", maracana, boca, fluminense))
    assert (v.neutral, v.basis) == (True, "decider_ground")
    assert v.evidence["away"]["presence"] == "elsewhere"


def test_the_two_legs_of_a_tie_are_never_a_decider_ground() -> None:
    # Copa do Brasil final 2025 (two legs): the second leg at the Maracanã with Vasco as the home side
    maracana = Ground("Estádio do Maracanã", "Rio de Janeiro")
    vasco = club(72, "Brazil", "Estádio São Januário", "Rio de Janeiro")
    corinthians = club(73, "Brazil", "Neo Química Arena", "São Paulo")
    one_match = classify(facts("domestic_cup", "Final", maracana, vasco, corinthians))
    assert (one_match.neutral, one_match.basis) == (True, "decider_ground")
    two_legs = classify(facts("domestic_cup", "Final", maracana, vasco, corinthians, legs=2))
    assert (two_legs.neutral, two_legs.basis) == (False, "no_evidence")
    assert two_legs.evidence["legs"] == 2
    # a semi-final whose twin is at the same ground is a final four only if it is one match
    twin = Shared(matches=2, home_sides=2, twins=1)
    assert classify(facts("domestic_cup", "Semi-finals", maracana, vasco, corinthians,
                          shared=twin)).basis == "semi_pair_ground"
    assert classify(facts("domestic_cup", "Semi-finals", maracana, vasco, corinthians, shared=twin,
                          legs=2)).basis == "no_evidence"


def test_a_final_between_two_clubs_of_the_same_city_is_neutral_at_the_big_ground() -> None:
    # Chelsea v Arsenal at Wembley: both are in London, neither plays at Wembley. The same-city leniency is for a tie that
    # is not a decider (a ground under works), not for a final.
    v = classify(facts("domestic_cup", "Final", WEMBLEY, CHELSEA, ARSENAL))
    assert (v.neutral, v.basis) == (True, "decider_ground")


def test_a_final_at_the_ground_of_one_finalist_is_not_neutral() -> None:
    home = Ground("Stamford Bridge", "London")
    assert classify(facts("domestic_cup", "Final", home, CHELSEA, EVERTON)).basis == "home_ground"
    assert classify(facts("domestic_cup", "Final", home, EVERTON, CHELSEA)).basis == "away_ground", \
        "the nominal home side plays at the other side's ground"


def test_a_semi_final_at_a_club_ground_is_a_home_match() -> None:
    ground = Ground("Emirates Stadium", "London")
    v = classify(facts("continental", "Semi-finals", ground, ARSENAL, REAL, legs=2))
    assert (v.neutral, v.basis) == (False, "home_ground")


def test_a_cup_tie_that_is_not_a_decider_needs_other_evidence() -> None:
    v = classify(facts("domestic_cup", "Round of 16", WEMBLEY, EVERTON, WIGAN))
    assert (v.neutral, v.basis) == (False, "no_evidence")


def test_a_club_at_another_ground_of_its_own_city_is_still_at_home() -> None:
    # Chelsea play a round-of-16 tie at Wembley while the Bridge is under works: same city, not a neutral ground.
    v = classify(facts("domestic_cup", "Round of 16", WEMBLEY, CHELSEA, EVERTON))
    assert (v.neutral, v.basis) == (False, "home_ground")
    assert v.evidence["home"]["why"].startswith("the same city")


def test_a_ground_in_a_third_country_is_neutral_but_a_usual_ground_vetoes_it() -> None:
    # Cardiff are labelled by the provider with the country of the league they play in; their own ground is in Wales
    ground = Ground("Cardiff City Stadium", "Cardiff", None, "Wales", "venues_table")
    cardiff = club(7, "England", "Cardiff City Stadium", "Cardiff")
    assert classify(facts("continental", "Round of 32", ground, cardiff, EVERTON)).basis == "home_ground"
    unknown_home = Side(8, "England", False, ())  # a side with no league history: nothing to veto with
    v = classify(facts("continental", "Round of 32", ground, unknown_home, EVERTON))
    assert (v.neutral, v.basis) == (True, "third_country"), "a competition of clubs of several countries"


def test_two_clubs_of_one_country_in_its_cup_need_their_homes_known_to_be_abroad() -> None:
    # Coupe de France: a club of Martinique at home. The data puts the ground in 'Martinique', the club in 'France', and
    # nothing is known of its league: that is not evidence of a neutral ground
    ground = Ground("Stade Municipal Pierre-Aliker", "Fort-de-France", None, "Martinique", "venues_table")
    islander = Side(60, "France", False, ())
    visitor = Side(61, "France", False, ())
    v = classify(facts("domestic_cup", "7th Round", ground, islander, visitor))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    # the Spanish Supercopa in Saudi Arabia: both sides have a league, neither plays there
    jeddah = Ground("King Abdullah Sports City", "Jeddah", None, "Saudi-Arabia", "venues_table")
    madrid, barca = club(62, "Spain", "Santiago Bernabéu", "Madrid"), club(63, "Spain", "Camp Nou", "Barcelona")
    v = classify(facts("domestic_cup", "Final", jeddah, madrid, barca))
    assert (v.neutral, v.basis) == (True, "third_country")


def test_a_league_match_is_never_neutral_even_abroad() -> None:
    perth = Ground("Optus Stadium", "Perth", None, "Australia", "venues_table")
    v = classify(facts("domestic_league", "Regular Season - 23", perth, club(9, "Italy", "San Siro", "Milano"),
                       club(10, "Italy", "Giuseppe Sinigaglia", "Como")))
    assert (v.neutral, v.basis) == (False, "league")


def test_national_sides_in_a_third_country_are_neutral_and_the_host_is_at_home() -> None:
    usa_stadium = Ground("MetLife Stadium", "East Rutherford", None, "USA", "venues_table")
    brazil, morocco, usa = national(10, "Brazil"), national(11, "Morocco"), national(12, "USA")
    v = classify(facts("international", "Group Stage - 1", usa_stadium, brazil, morocco))
    assert (v.neutral, v.basis) == (True, "third_country")
    host = classify(facts("international", "Group Stage - 1", usa_stadium, usa, morocco))
    assert (host.neutral, host.basis) == (False, "home_country")
    visiting = classify(facts("international", "Group Stage - 1", usa_stadium, morocco, usa))
    assert (visiting.neutral, visiting.basis) == (False, "away_country")


def test_national_sides_with_a_missing_country_are_not_neutral() -> None:
    no_country = Ground("Estadio Nacional", "Lima")
    assert classify(facts("international", "Friendly International", no_country, national(1, "Peru"),
                          national(2, "Chile"))).basis == "venue_country_unknown"
    assert classify(facts("international", "Friendly International", Ground("Estadio Nacional", "Lima", None, "Peru"),
                          national(1, None), national(2, "Chile"))).basis == "country_unknown"


def test_a_competition_played_at_shared_neutral_grounds_is_neutral_once_it_shows() -> None:
    # Copa Argentina: ties at a ground of neither side, the same ground for several ties of different clubs
    ground = Ground("Estadio Madre de Ciudades", "Santiago del Estero")
    home = club(20, "Argentina", "Estadio Ciudad de Lanús - Néstor Díaz Pérez", "Lanús")
    away = club(21, "Argentina", "Estadio Diego Armando Maradona", "Buenos Aires")
    shows = facts("domestic_cup", "Round of 32", ground, home, away, shared=Shared(matches=3, home_sides=3))
    assert (classify(shows).neutral, classify(shows).basis) == (True, "shared_ground")
    for thin in (Shared(2, 2), Shared(3, 2), Shared(2, 3), None):
        v = classify(facts("domestic_cup", "Round of 32", ground, home, away, shared=thin))
        assert (v.neutral, v.basis) == (False, "no_evidence"), thin


def test_a_national_stadium_borrowed_by_clubs_of_one_country_is_where_they_are_at_home() -> None:
    # Libertadores: Always Ready (El Alto) host their group at the Hernando Siles of La Paz, as do the other Bolivian
    # clubs: three different home sides at one ground, but the ground is in the club's own country
    siles = Ground("Estadio Hernando Siles", "La Paz", None, "Bolivia", "venues_table")
    always_ready = club(22, "Bolivia", "Estadio Municipal de El Alto", "El Alto")
    inter = club(23, "Brazil", "Estádio Beira-Rio", "Porto Alegre")
    borrowed = Shared(matches=4, home_sides=3)
    v = classify(facts("continental", "Group Stage - 1", siles, always_ready, inter, shared=borrowed))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    assert v.evidence["shared"]["host_country"] is True
    # the visiting side is the host's
    v = classify(facts("continental", "Group Stage - 2", siles, inter, always_ready, shared=borrowed))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    # the same ground for two clubs of other countries is not the host's
    v = classify(facts("continental", "Group Stage - 3", siles, inter, club(24, "Paraguay", "Estadio Defensores", "Asunción"),
                       shared=borrowed))
    assert v.basis in {"third_country", "shared_ground"} and v.neutral is True
    # a ground whose country is not known cannot be the host's: shared evidence stands
    nowhere = Ground("Jassim Bin Hamad Stadium", "Doha")
    v = classify(facts("continental", "Group Stage - 4", nowhere, always_ready, inter, shared=borrowed))
    assert (v.neutral, v.basis) == (True, "shared_ground")
    assert v.evidence["shared"]["host_country"] is False


def test_a_ground_whose_country_is_in_doubt_is_tested_against_every_country_it_may_be_in() -> None:
    # Dammam: the provider files a Saudi club (Al Khaleej Saihat) under the Emirates, so the league matches played at the
    # ground name two countries and its own is "disputed" - a Saudi side that plays there is still the host
    dammam = Ground("Prince Mohamed bin Fahd Stadium", "Dammam", None, None, "disputed",
                    frozenset({"Saudi-Arabia", "United-Arab-Emirates"}))
    al_faisaly = club(60, "Saudi-Arabia", "Prince Faisal bin Fahd Stadium", "Al Majma'ah")
    al_sadd = club(61, "Qatar", "Jassim Bin Hamad Stadium", "Doha")
    group = Shared(matches=4, home_sides=3)
    v = classify(facts("continental", "Group Stage - 1", dammam, al_faisaly, al_sadd, shared=group))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    assert v.evidence["shared"]["host_country"] is True
    assert v.evidence["ground"]["countries"] == ["Saudi-Arabia", "United-Arab-Emirates"]
    # the same from the visiting side, and for a side of the other country the ground may be in
    v = classify(facts("continental", "Group Stage - 2", dammam, al_sadd, al_faisaly, shared=group))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    emirati = club(62, "United-Arab-Emirates", "Sharjah Stadium", "Sharjah")
    assert classify(facts("continental", "Group Stage - 3", dammam, emirati, al_sadd, shared=group)).basis == "no_evidence"
    # Doha, where the Palestinian national side once had its "home": no side of those countries, so the evidence stands
    doha = Ground("Jassim Bin Hamad Stadium", "Doha", None, None, "disputed", frozenset({"Qatar", "Palestine"}))
    al_nassr = club(63, "Saudi-Arabia", "Al-Awwal Park", "Riyadh")
    v = classify(facts("continental", "Group Stage - 4", doha, al_nassr, club(64, "Australia", "AAMI Park", "Melbourne"),
                       shared=group))
    assert (v.neutral, v.basis) == (True, "shared_ground")
    assert v.evidence["shared"]["host_country"] is False
    # the doubt only matters where a host nation does: a cup of one country is played at grounds chosen for it
    v = classify(facts("domestic_cup", "Round of 16", dammam, al_faisaly, club(65, "Saudi-Arabia", "Al-Madina", "Medina"),
                       shared=group))
    assert (v.neutral, v.basis) == (True, "shared_ground")
    # a ground nothing names a country for has no country to be the host's
    v = classify(facts("continental", "Group Stage - 5", Ground("Estadio Y", "Z", None, None, None), al_faisaly, al_sadd,
                       shared=group))
    assert (v.neutral, v.basis) == (True, "shared_ground")


def test_a_new_stadium_is_not_a_neutral_ground() -> None:
    # A side's first home matches at a new ground: one home side in every match, so the shared-ground evidence never
    # reaches three different home sides
    ground = Ground("Estadio Nuevo", "Madrid")
    home = club(30, "Spain", "Estadio Viejo", "Madrid")
    away = club(31, "Spain", "Estadio Otro", "Sevilla")
    v = classify(facts("domestic_cup", "Round of 32", ground, home, away, shared=Shared(matches=4, home_sides=1)))
    assert (v.neutral, v.basis) == (False, "home_ground"), "same city"
    elsewhere = Ground("Estadio Nuevo", "Valencia")
    v = classify(facts("domestic_cup", "Round of 32", elsewhere, home, away, shared=Shared(matches=4, home_sides=1)))
    assert (v.neutral, v.basis) == (False, "no_evidence")


def test_a_side_whose_home_is_not_known_is_never_away_from_it() -> None:
    thin = Side(40, "Spain", False, home_matches("Campo X", "Y", MIN_HISTORY - 1))
    ground = Ground("Wembley Stadium", "London")
    v = classify(facts("domestic_cup", "Final", ground, thin, REAL))
    assert (v.neutral, v.basis) == (False, "no_evidence")
    assert v.evidence["home"]["presence"] == "unknown"


def test_no_ground_no_kind_and_mixed_sides_are_not_neutral() -> None:
    assert classify(facts("domestic_cup", "Final", Ground(), REAL, DORTMUND)).basis == "no_venue"
    unknown_kind = Side(50, "Spain", None, home_matches("A", "B"))
    assert classify(facts("domestic_cup", "Final", WEMBLEY, unknown_kind, DORTMUND)).basis == "kind_unknown"
    assert classify(facts("international", "Friendly International", WEMBLEY, national(1, "England"),
                          REAL)).basis == "mixed_sides"


def test_the_verdict_names_the_rule_and_carries_the_ground() -> None:
    v = classify(facts("continental", "Final", WEMBLEY, REAL, DORTMUND))
    assert v.rule == "neutral-v1"
    assert v.evidence["ground"]["name"] == "Wembley Stadium"
    assert v.evidence["ground"]["country_basis"] == "venue_id"


# ------------------------------------------------------------------------------------------ the pieces


@pytest.mark.parametrize("text, final, semi", [
    ("Final", True, False), ("final", True, False), ("3rd Place Final", True, False), ("5th Place Final", True, False),
    ("Third Place", True, False), ("Semi-finals", False, True), ("Semi-Finals", False, True), ("semi finals", False, True),
    ("Semi-final", False, True), ("Quarter-finals", False, False), ("Round of 16", False, False),
    ("Final Round - 3", False, False), ("1st Round - Finals", False, False), ("Play-offs - Finals", False, False),
    ("Group Stage - 6", False, False), ("16th Finals", False, False), ("", False, False), (None, False, False),
])
def test_which_rounds_are_one_match_at_a_ground_chosen_for_it(text: str | None, final: bool, semi: bool) -> None:
    assert (is_final(text), is_semi(text)) == (final, semi)


def test_one_ground_by_its_checked_id_or_by_name_and_compatible_city() -> None:
    assert same_ground(Ground("Allianz Stadium", "Torino", 7), Ground("Allianz Stadium", "Turin", 7)), \
        "the same checked id: two spellings of one city"
    assert same_ground(Ground("St James Park", "Newcastle"), Ground("St. James' Park", "Newcastle upon Tyne"))
    assert not same_ground(Ground("St James Park", "Exeter"), Ground("St. James' Park", "Newcastle upon Tyne"))
    assert not same_ground(Ground("Allianz Stadium", "Torino"), Ground("Allianz Stadium", "Sydney")), \
        "the same name in two cities"
    assert same_ground(Ground("Stadionul Municipal", "Botosani"), Ground("Stadionul Municipal", "Botosani")), \
        "a name of generic words is equal to itself, and the city says which"
    assert not same_ground(Ground("Stadionul Municipal", "Botosani"), Ground("Stadionul Municipal", "Sibiu"))
    assert not same_ground(Ground(None, "London"), Ground(None, "London")), "no name, no ground"


def test_a_ground_is_a_side_s_home_only_with_enough_of_its_matches() -> None:
    bridge, wembley = Ground("Stamford Bridge", "London"), Ground("Wembley Stadium", "London")
    twenty = (bridge,) * 19 + (wembley,)
    assert usual_grounds(twenty) is not None and len(usual_grounds(twenty) or []) == 1, "1 of 20 is not a home"
    both = (bridge,) * 10 + (wembley,) * 10
    assert len(usual_grounds(both) or []) == 2, "a side with two homes"
    assert MIN_COUNT == 2
    few = (bridge,) * (MIN_HISTORY - 1)
    assert usual_grounds(few) is None, "too little history to say"
    nomad = tuple(Ground(f"Ground {i}", "Somewhere") for i in range(10))
    assert usual_grounds(nomad) is None, "no ground reaches the bar: no home to be away from"


def test_presence_reads_the_side_s_own_history() -> None:
    history = home_matches("Estadio Monumental Presidente José Fierro", "San Miguel de Tucumán")
    here = Ground("Estadio Monumental Jose Fierro", "San Miguel de Tucumán")
    assert presence(history, here, decider=False)[0] is Presence.HOME
    assert presence(history, Ground("Estadio Cementerio de los Elefantes", "San Miguel de Tucumán"),
                    decider=False)[0] is Presence.HOME, "same city, not a decider"
    assert presence(history, Ground("Estadio Cementerio de los Elefantes", "San Miguel de Tucumán"),
                    decider=True)[0] is Presence.ELSEWHERE
    assert presence(history, Ground(None, "San Miguel de Tucumán"), decider=False)[0] is Presence.UNKNOWN
    assert presence((), here, decider=False)[0] is Presence.UNKNOWN


def test_presence_reads_the_ground_the_provider_gives_as_the_side_s_own() -> None:
    history = home_matches("De Kuip", "Rotterdam")
    declared = (Ground("Stadion Feijenoord", "Rotterdam", 359),)
    kuip = Ground("Stadion Feijenoord", "Rotterdam")
    assert presence(history, kuip, decider=True)[0] is Presence.ELSEWHERE, "the history alone does not know the alias"
    assert presence(history, kuip, decider=True, homes=declared)[0] is Presence.HOME
    assert presence((), kuip, decider=True, homes=declared)[0] is Presence.HOME, "no history is still a declared home"
    assert presence((), Ground("Wembley Stadium", "London"), decider=True, homes=declared)[0] is Presence.UNKNOWN
    # a checked venue id is the same ground whatever it is called
    renamed = Ground("Nieuw Stadion", "Rotterdam", 359)
    assert presence(history, renamed, decider=True, homes=declared)[0] is Presence.HOME
    # the same city as the declared ground counts as home off a final, never in one
    other = Ground("Sparta Stadion", "Rotterdam")
    assert presence(history, other, decider=False, homes=declared)[0] is Presence.HOME
    assert presence(history, other, decider=True, homes=declared)[0] is Presence.ELSEWHERE

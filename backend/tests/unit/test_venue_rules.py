"""IA-076 (AD-H04): which Wikidata item is one of our stadiums (venue-geo-v1) and which stadium a match without a provider id
is played at (venue-link-v1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fbi.venues.rules import (
    Ground,
    LinkIndex,
    OurVenue,
    Question,
    Unlinked,
    country_key,
    current_homes,
    elevation_check,
    km_between,
    link_all,
    link_fixture,
    match_all,
    match_venue,
)
from fbi.venues.wikidata import HomeStatement, Snapshot, WdVenue


def snap(homes: dict[str, list[tuple[str, str, str | None]]], venues: Iterable[WdVenue]) -> Snapshot:
    s = Snapshot(sha256="0" * 64, fetched_at=datetime(2026, 11, 17, tzinfo=UTC), query_version="venue-wd-v1")
    for team, rows in homes.items():
        s.homes[team] = [HomeStatement(team, v, rank, None, end) for v, rank, end in rows]
    s.venues = {v.qid: v for v in venues}
    return s


def wd(qid: str, names: set[str], places: set[str], coords: set[tuple[float, float]] | None = None,
       country: str = "Spain", caps: set[int] | None = None, elev: set[float] | None = None) -> WdVenue:
    return WdVenue(qid, names, places, {country}, coords or {(40.45, -3.69)}, caps or set(), elev or set())


BERNABEU = wd("Q164027", {"Estadio Santiago Bernabéu", "Bernabeu"}, {"Madrid", "Chamartín"}, caps={83186})


def test_current_homes_drop_ended_and_deprecated_statements_and_prefer_the_preferred_one() -> None:
    rows = [HomeStatement("Q1", "Q10", "normal", None, "2017-05-01"), HomeStatement("Q1", "Q11", "deprecated", None, None),
            HomeStatement("Q1", "Q12", "normal", None, None), HomeStatement("Q1", "Q13", "preferred", None, None)]
    assert current_homes(rows) == ["Q13"]
    assert current_homes(rows[:3]) == ["Q12"]


def test_a_stadium_is_matched_through_its_club_and_confirmed_by_its_name() -> None:
    ours = OurVenue(1, "Estadio Santiago Bernabéu", "Madrid", "Spain", ("Q8682",))
    got = match_venue(ours, snap({"Q8682": [("Q164027", "normal", None)]}, [BERNABEU]))
    assert not isinstance(got, Question) and got is not None
    assert (got.qid, got.method, got.confidence, got.capacity) == ("Q164027", "home_venue_name", 0.95, 83186)
    assert got.coords == (40.45, -3.69)


def test_a_sponsor_name_is_matched_by_the_single_home_venue_in_the_same_city_with_less_confidence() -> None:
    ours = OurVenue(2, "Mercari Stadium", "Kashima", "Japan", ("Q1",))
    v = wd("Q2", {"Kashima Soccer Stadium"}, {"Kashima"}, country="Japan")
    got = match_venue(ours, snap({"Q1": [("Q2", "normal", None)]}, [v]))
    assert not isinstance(got, Question) and got is not None
    assert (got.method, got.confidence) == ("home_venue_city", 0.8)


def test_one_candidate_that_neither_the_name_nor_the_city_confirms_is_a_question() -> None:
    ours = OurVenue(3, "Campo Municipal", "Alcorcón", "Spain", ("Q1",))
    got = match_venue(ours, snap({"Q1": [("Q2", "normal", None)]}, [wd("Q2", {"Estadio X"}, {"Getafe"})]))
    assert isinstance(got, Question) and got.reason == "unconfirmed_single" and got.candidates == ("Q2",)


def test_two_named_candidates_and_a_country_that_differs_are_questions() -> None:
    a, b = wd("Q2", {"Estadio Anxo Carro"}, {"Lugo"}), wd("Q3", {"Anxo Carro"}, {"Lugo"})
    ours = OurVenue(4, "Estadio Anxo Carro", "Lugo", "Spain", ("Q1",))
    got = match_venue(ours, snap({"Q1": [("Q2", "normal", None), ("Q3", "normal", None)]}, [a, b]))
    assert isinstance(got, Question) and got.reason == "several_named"
    vale = OurVenue(5, "The Vale Stadium", "Birmingham", "England", ("Q1",))
    got = match_venue(vale, snap({"Q1": [("Q9", "normal", None)]}, [wd("Q9", {"Vale Stadium"}, {"Porto"},
                                                                            country="Portugal")]))
    assert isinstance(got, Question) and got.reason == "country_differs"


def test_england_is_in_the_united_kingdom_and_no_club_item_means_nothing_to_ask() -> None:
    assert country_key("England") == country_key("United Kingdom") == "united kingdom"
    ours = OurVenue(6, "Old Trafford", "Manchester", "England", ("Q18656",))
    ot = wd("Q83457", {"Old Trafford"}, {"Manchester", "Trafford"}, country="United Kingdom")
    got = match_venue(ours, snap({"Q18656": [("Q83457", "normal", None)]}, [ot]))
    assert got is not None and not isinstance(got, Question)
    assert match_venue(OurVenue(7, "X", None, None, ("Q404",)), snap({}, [])) is None


def test_coordinates_that_disagree_keep_the_item_without_coordinates() -> None:
    v = wd("Q2", {"Estadio Nuevo"}, {"Sevilla"}, coords={(37.38, -5.97), (37.50, -5.90)})
    got = match_venue(OurVenue(8, "Estadio Nuevo", "Sevilla", "Spain", ("Q1",)), snap({"Q1": [("Q2", "normal", None)]},
                                                                                     [v]))
    assert got is not None and not isinstance(got, Question)
    assert got.coords is None and got.evidence["coords"] == "coords_disagree"
    assert km_between((37.38, -5.97), (37.50, -5.90)) > 1


def test_an_item_matched_to_two_of_our_stadiums_is_kept_only_where_the_name_matched() -> None:
    v = wd("Q2", {"Estadio Uno"}, {"Lima"}, country="Peru")
    named = OurVenue(10, "Estadio Uno", "Lima", "Peru", ("Q1",))
    other = OurVenue(11, "Cancha Dos", "Lima", "Peru", ("Q5",))
    s = snap({"Q1": [("Q2", "normal", None)], "Q5": [("Q2", "normal", None)]}, [v])
    kept, questions = match_all([other, named], s)
    assert [m.venue_id for m in kept] == [10]
    assert [(q.subject_id, q.reason) for q in questions] == [(11, "shared_qid")]


def test_elevation_check() -> None:
    assert elevation_check(None, 10) == "no_dem" and elevation_check(2240, None) == "no_wikidata"
    assert elevation_check(2240, 2200) == "agrees" and elevation_check(2240, 1500) == "disagrees"


# ── links ──

GROUNDS = [Ground(1, "Estadio Municipal", "Lugo"), Ground(2, "Estadio Municipal", "Toledo"),
           Ground(3, "Kashima Soccer Stadium", "Kashima"), Ground(4, "Estadio La Cartuja de Sevilla", "Sevilla"),
           Ground(5, "Estadio Benito Villamarín", "Sevilla"), Ground(6, "Kashima Field", "Kashima")]


def index(history: list[tuple[int, str | None, str | None, int, int]] | None = None) -> LinkIndex:
    return LinkIndex.build(GROUNDS, {100: 3, 200: 5, 300: 1}, history or [])


def test_the_same_name_in_two_cities_is_linked_by_the_city_and_never_without_it() -> None:
    ix = index()
    got = link_fixture(Unlinked(1, 999, "Estadio Municipal", "Toledo", False), ix)
    assert got is not None and not isinstance(got, Question)
    assert (got.venue_id, got.method) == (2, "venue_name_city")
    q = link_fixture(Unlinked(2, 999, "Estadio Municipal", None, False), ix)
    assert isinstance(q, Question) and q.reason == "name_without_city" and set(q.candidates) == {"1", "2"}
    q = link_fixture(Unlinked(3, 999, "Estadio Municipal", "Cuenca", False), ix)
    assert isinstance(q, Question) and q.reason == "name_other_city"


def test_a_sponsor_name_is_linked_by_what_the_provider_called_the_ground_before() -> None:
    ix = index([(100, "Mercari Stadium", "Kashima", 3, 12)])
    got = link_fixture(Unlinked(4, 100, "Mercari Stadium", "Kashima", False), ix)
    assert got is not None and not isinstance(got, Question)
    assert (got.venue_id, got.method, got.confidence) == (3, "provider_history_team", 0.97)
    assert got.evidence["matches"] == 12


def test_history_by_name_and_city_and_its_ambiguity() -> None:
    ix = index([(555, "Arena X", "Sevilla", 4, 3)])
    got = link_fixture(Unlinked(5, 999, "Arena X", "Sevilla", False), ix)
    assert got is not None and not isinstance(got, Question) and got.method == "provider_history_city"
    # the provider once gave this name and city the id of a ground filed in another city: a question, never a link
    other = link_fixture(Unlinked(5, 999, "Arena X", "Riga", False), index([(555, "Arena X", "Riga", 4, 3)]))
    assert isinstance(other, Question) and other.reason == "city_differs" and other.candidates == ("4",)
    ix = index([(100, "Stadion", "Kashima", 3, 2), (100, "Stadion", "Kashima", 6, 2), (100, "Stadion", "Kashima", 1, 1)])
    q = link_fixture(Unlinked(6, 100, "Stadion", "Kashima", False), ix)
    assert isinstance(q, Question) and q.reason == "history_ambiguous" and q.candidates == ("3", "6")
    # the id the provider gave the name for a ground in another city is not a candidate (Lugo is not Kashima)


def test_the_home_ground_is_used_only_under_its_name_and_never_at_a_neutral_venue() -> None:
    ix = index()
    got = link_fixture(Unlinked(7, 200, "Benito Villamarín", "Sevilla", False), ix)
    assert got is not None and not isinstance(got, Question) and (got.venue_id, got.method) == (5, "home_ground")
    neutral = link_fixture(Unlinked(8, 200, "Benito Villamarín", "Sevilla", True), ix)
    assert neutral is None or isinstance(neutral, Question) or neutral.method != "home_ground"
    other = link_fixture(Unlinked(9, 200, "Estadio de La Cartuja", "Sevilla", False), ix)
    assert other is None or isinstance(other, Question) or other.venue_id != 5


def test_a_home_ground_under_another_name_in_the_same_city_is_a_question_and_no_name_is_nothing() -> None:
    ix = index()
    q = link_fixture(Unlinked(10, 100, "Mercari Stadium", "Kashima", False), ix)
    assert isinstance(q, Question) and q.reason == "home_ground_other_name" and q.candidates == ("3",)
    assert link_fixture(Unlinked(11, 100, None, "Kashima", False), ix) is None
    links, questions, nothing = link_all([Unlinked(11, 100, None, None, False), Unlinked(12, 300, "Estadio Municipal",
                                                                                         "Lugo", False)], ix)
    assert nothing == 1 and [k.venue_id for k in links] == [1] and questions == []

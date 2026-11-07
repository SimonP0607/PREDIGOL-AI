"""The venue control: a ground's city and country against its competition, its matches, the provider and the other
grounds (BE-005; 7 Nov 2026, Valencia v Real Madrid shown at "Estadio de Mestalla, Valdivia")."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from scripts.repair_venue_city import Plan, plan_ground

from fbi.truth.findings import Kind, Severity
from fbi.truth.venues import (
    Atlas,
    FixtureCity,
    Ground,
    ProviderVenue,
    judge,
    judge_city,
    judge_country,
    odd_fixtures,
    reference_city,
    venue_in,
)

VALENCIA = 532
AT = datetime(2026, 10, 1, tzinfo=UTC)

ATLAS_ROWS: list[dict[str, Any]] = [
    {"id": 80, "name": "Estadio de Mestalla", "city": "Valdivia", "country": "Spain"},
    {"id": 81, "name": "Estadio Ciutat de València", "city": "Valencia", "country": "Spain"},
    {"id": 90, "name": "Estadio Parque Municipal", "city": "Valdivia", "country": "Chile"},
    {"id": 91, "name": "Estadio Félix Gallardo", "city": "Valdivia", "country": "Chile"},
    {"id": 70, "name": "Estadio Nuevo Arcángel", "city": "Córdoba", "country": "Spain"},
    {"id": 71, "name": "Estadio Mario Alberto Kempes", "city": "Córdoba", "country": "Argentina"},
]


def provider(city: str | None, endpoint: str = "/venues") -> ProviderVenue:
    return ProviderVenue(city=city, country="Spain", name="Estadio de Mestalla", endpoint=endpoint, fetched_at=AT,
                         payload_hash="ab" * 32, file_path="api-football/2026/10/01/venues__abababababab.json.gz")


def mestalla(city: str | None = "Valdivia", *, fixtures: tuple[FixtureCity, ...] | None = None,
             record: ProviderVenue | None = None, country: str | None = "Spain") -> Ground:
    if fixtures is None:
        fixtures = (FixtureCity(VALENCIA, "Estadio de Mestalla", "Valencia", 18, tuple(range(1000, 1018))),)
    return Ground(venue_id=80, provider_venue_id=1460, name="Estadio de Mestalla", city=city, country=country,
                  competitions=(("La Liga", "Spain"),), home_countries=("Spain",), fixture_cities=fixtures,
                  provider=record)


ATLAS = Atlas.of(ATLAS_ROWS)


def test_mestalla_in_valdivia_is_flagged_against_the_provider_record() -> None:
    v = judge_city(mestalla(record=provider("Valencia")), ATLAS)
    assert v.finding is not None and v.provider_disagrees and v.fixtures_disagree
    f = v.finding
    assert (f.dataset, f.field, f.kind, f.severity) == ("venues", "city", Kind.MISMATCH, Severity.MEDIUM)
    assert (f.api, f.db) == ("Valencia", "Valdivia")
    assert f.entity == "venue 1460 (Estadio de Mestalla; core.venues 80)"
    assert "Chile" in f.note and "/venues payload" in f.note and "0 of the 18 fixture payloads" in f.note
    assert "Not corrected here" in f.note


def test_without_a_provider_record_the_matches_and_the_other_grounds_still_flag_it() -> None:
    v = judge_city(mestalla(), ATLAS)
    assert v.finding is not None and not v.provider_disagrees
    assert (v.finding.kind, v.finding.severity, v.finding.api) == (Kind.INCONSISTENT, Severity.MEDIUM, "Valencia")


def test_the_provider_repeating_the_wrong_city_does_not_hide_it() -> None:
    v = judge_city(mestalla(record=provider("Valdivia")), ATLAS)
    assert v.finding is not None and v.finding.severity is Severity.MEDIUM, "the city is Chile's, not Spain's"
    assert "says the same" in v.finding.note


def test_a_city_only_in_other_countries_is_enough_when_no_match_names_one() -> None:
    v = judge_city(mestalla(fixtures=()), ATLAS)
    assert v.finding is not None and v.foreign == ["Chile"] and v.finding.api == "a city in Spain"


def test_one_wrong_match_payload_does_not_vouch_for_the_wrong_city() -> None:
    fixtures = (FixtureCity(VALENCIA, "Estadio de Mestalla", "Valencia", 18, tuple(range(1000, 1018))),
                FixtureCity(VALENCIA, "Mestalla", "Valdivia", 1, (9207,)))
    g = mestalla(fixtures=fixtures)
    v = judge_city(g, ATLAS)
    assert v.finding is not None and v.fixtures_disagree and v.expected == "Valencia"
    odd = odd_fixtures(g, reference_city(g, v))
    assert [(o.provider_fixture_id, o.city, o.expected, o.others) for o in odd] == [(9207, "Valdivia", "Valencia", 18)]


def test_a_right_venue_with_one_odd_match_flags_only_the_match() -> None:
    fixtures = (FixtureCity(VALENCIA, "Estadio de Mestalla", "Valencia", 18, tuple(range(1000, 1018))),
                FixtureCity(VALENCIA, "Estadio de Mestalla", "Valdivia", 1, (9207,)))
    found = judge(mestalla("Valencia", fixtures=fixtures, record=provider("Valencia")), ATLAS)
    assert [(f.entity.split(" at ")[0], f.field, f.api, f.db) for f in found] == \
        [("fixture 9207", "venue_city", "Valencia", "Valdivia")]
    assert found[0].severity is Severity.MEDIUM and "shows this fixture's own city" in found[0].note


def test_agreement_is_not_a_finding() -> None:
    assert judge(mestalla("Valencia", record=provider("Valencia")), ATLAS) == []
    assert judge(mestalla("València"), ATLAS) == [], "accents aside, one city"


def test_a_city_shared_by_two_countries_is_not_flagged_when_its_matches_confirm_it() -> None:
    cordoba = Ground(venue_id=70, provider_venue_id=7, name="Estadio Nuevo Arcángel", city="Córdoba", country="Spain",
                     competitions=(("Segunda División", "Spain"),), home_countries=("Spain",),
                     fixture_cities=(FixtureCity(1, "Nuevo Arcángel", "Córdoba", 21, (1,)),))
    assert ATLAS.elsewhere(cordoba) == ["Argentina"]
    assert judge(cordoba, ATLAS) == []


def test_only_the_fixtures_against_the_provider_record_is_low() -> None:
    turin = Ground(venue_id=5, provider_venue_id=5, name="Allianz Stadium", city="Turin", country="Italy",
                   competitions=(("Serie A", "Italy"),), home_countries=("Italy",),
                   fixture_cities=(FixtureCity(496, "Allianz Stadium", "Torino", 19, (2,)),),
                   provider=ProviderVenue("Turin", "Italy", "Allianz Stadium", "/teams", AT, "cd" * 32, "x"))
    v = judge_city(turin, ATLAS)
    assert v.finding is not None and v.finding.severity is Severity.LOW


def test_a_ground_abroad_is_flagged_unless_the_club_is_from_there() -> None:
    abroad = mestalla("Valencia", country="Chile")
    f = judge_country(abroad)
    assert f is not None and (f.field, f.kind, f.severity, f.api, f.db) == \
        ("country", Kind.INCONSISTENT, Severity.MEDIUM, "Spain (La Liga)", "Chile")
    cardiff = Ground(venue_id=6, provider_venue_id=6, name="Cardiff City Stadium", city="Cardiff", country="Wales",
                     competitions=(("Championship", "England"),), home_countries=("Wales",))
    assert judge_country(cardiff) is None, "a Welsh club plays the English league at home in Wales"
    world = Ground(venue_id=7, provider_venue_id=7, name="X", city="Y", country="Chile",
                   competitions=(("Friendlies", "World"),), home_countries=("Spain",))
    assert judge_country(world) is None


def test_the_venue_block_is_found_in_either_answer() -> None:
    teams = {"response": [{"team": {"id": 532}, "venue": {"id": 1460, "city": "Valencia"}}]}
    venues = {"response": [{"id": 1460, "city": "Valencia"}]}
    assert venue_in(teams, 1460) == {"id": 1460, "city": "Valencia"}
    assert venue_in(venues, 1460) == {"id": 1460, "city": "Valencia"}
    assert venue_in(venues, 1) is None


def test_the_repair_restores_from_the_provider_record_and_lists_what_it_cannot() -> None:
    plan = Plan()
    g = mestalla(record=provider("Valencia"))
    plan_ground(g, judge_city(g, ATLAS), plan)
    assert [(v.venue_id, v.before, v.after) for v in plan.venues] == [(80, "Valdivia", "Valencia")]
    assert plan.fixtures == [] and plan.undecided == []

    plan = Plan()
    g = mestalla(record=provider("Valdivia"))
    plan_ground(g, judge_city(g, ATLAS), plan)
    assert plan.venues == [] and len(plan.undecided) == 1 and "says the same" in plan.undecided[0]

    plan = Plan()
    g = mestalla()
    plan_ground(g, judge_city(g, ATLAS), plan)
    assert plan.venues == [] and "no stored provider record" in plan.undecided[0]


def test_the_repair_does_not_follow_a_provider_record_the_matches_contradict() -> None:
    plan = Plan()
    g = mestalla("Valdivia", record=provider("Paterna"))
    plan_ground(g, judge_city(g, ATLAS), plan)
    assert plan.venues == [] and "most fixture payloads" in plan.undecided[0]


def test_the_repair_sets_the_odd_match_to_the_city_its_siblings_give() -> None:
    fixtures = (FixtureCity(VALENCIA, "Estadio de Mestalla", "Valencia", 18, tuple(range(1000, 1018))),
                FixtureCity(VALENCIA, "Estadio de Mestalla", "Valdivia", 1, (9207,)))
    plan = Plan()
    g = mestalla("Valdivia", fixtures=fixtures, record=provider("Valencia"))
    plan_ground(g, judge_city(g, ATLAS), plan)
    assert [(v.before, v.after) for v in plan.venues] == [("Valdivia", "Valencia")]
    assert [(f.provider_fixture_id, f.before, f.after) for f in plan.fixtures] == [(9207, "Valdivia", "Valencia")]

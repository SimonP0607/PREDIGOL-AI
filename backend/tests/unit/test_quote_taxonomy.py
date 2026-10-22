"""The registry of the provider's bets (plan F1, the price clock)."""

from __future__ import annotations

import json
from pathlib import Path

from fbi.odds.quote_parse import SCHEMAS
from fbi.odds.quote_taxonomy import (
    EXTRACTED,
    PERIODS,
    STATUSES,
    SUBJECTS,
    extracted_specs,
    known_bet_ids,
    same_name,
    spec_for,
)
from fbi.providers.api_football.normalize import PREMATCH_BETS

CATALOGUE = Path(__file__).parents[2] / "docs" / "api-football" / "catalogues" / "bets_prematch.json"


def catalogue() -> dict[int, str]:
    return {int(b["id"]): str(b["name"]) for b in json.loads(CATALOGUE.read_text())}


def test_every_bet_of_the_providers_catalogue_is_classified() -> None:
    """A bet the taxonomy has not seen would arrive as 'unclassified': visible, but not a decision. Today the registry
    says something about each of the 338, so a gap here means the catalogue moved and the taxonomy did not."""
    missing = sorted(set(catalogue()) - known_bet_ids())
    assert not missing, f"bets in the provider's catalogue that the taxonomy does not classify: {missing}"


def test_the_taxonomy_knows_no_bet_the_catalogue_does_not() -> None:
    """A typo in an id would silently classify (and maybe extract) somebody else's bet."""
    extra = sorted(known_bet_ids() - set(catalogue()))
    assert not extra, f"bet ids in the taxonomy that the provider's catalogue does not list: {extra}"


def test_the_names_of_the_extracted_bets_are_the_catalogue_names() -> None:
    """The extractor refuses a bet whose name in the payload is not the one registered (a provider renumbering must refuse
    prices, never relabel them). A hand-typed name that is not the catalogue's would refuse every price of the bet."""
    names = catalogue()
    wrong = [(s.bet_id, s.name, names.get(s.bet_id)) for s in EXTRACTED if not same_name(s.name, names.get(s.bet_id, ""))]
    assert not wrong, wrong


def test_the_five_bets_the_live_pipeline_reads_are_extracted_under_its_own_ids_and_names() -> None:
    by_key = {s.market_key: s for s in EXTRACTED if s.market_key}
    assert set(by_key) == set(PREMATCH_BETS)
    for key, bet in PREMATCH_BETS.items():
        spec = by_key[key]
        assert (spec.bet_id, spec.name) == (bet.bet_id, bet.name), key
        assert spec.schema == "legacy", "the five are read by the pipeline's own function, so the two series cannot disagree"


def test_every_extracted_bet_has_a_reader_and_a_consistent_line_policy() -> None:
    for spec in extracted_specs():
        assert spec.extract
        assert spec.schema in SCHEMAS, spec
        assert spec.period in PERIODS and spec.subject in SUBJECTS and spec.status in STATUSES, spec
        lined = spec.schema in {"ou", "ah"} or (spec.schema == "legacy" and spec.market_key in {"OU", "AH"})
        assert spec.has_line == lined, f"{spec.bet_id} {spec.name}: has_line must follow its schema"
        if spec.line_is_signed:
            assert spec.has_line, spec
        if spec.away_line_negated:
            assert spec.line_is_signed, spec


def test_no_bet_is_extracted_twice() -> None:
    ids = [s.bet_id for s in EXTRACTED]
    assert len(ids) == len(set(ids))


def test_the_extracted_set_is_the_plans_families_and_nothing_else() -> None:
    """Result and goals markets around the five, goals by half, corners, cards and team shots. Players, goalkeepers,
    timing and the other sports stay in RAW (extracting is a cost, not-extracting loses nothing)."""
    families = {s.family for s in EXTRACTED}
    assert families <= {"result", "goals", "goals_half", "corners", "cards", "shots"}, families
    for spec in EXTRACTED:
        assert spec.subject in {"match", "home", "away"}, f"a player or a goalkeeper must not be extracted: {spec}"


def test_a_bet_nobody_classified_is_unclassified_and_not_extracted() -> None:
    spec = spec_for(99999, "Something New")
    assert spec.family == "unclassified" and not spec.extract and spec.status == "NOT_MODELABLE"
    assert spec.name == "Something New"


def test_a_parked_bet_takes_its_period_and_subject_from_its_name() -> None:
    spec = spec_for(73, "Goal Line (2nd Half)")
    assert spec.period == "2H" and not spec.extract
    assert spec_for(72, "Goal Line (1st Half)").period == "1H"
    assert spec_for(264, "Player Shots").subject == "player"


def test_the_names_compare_without_caring_for_case_or_spacing() -> None:
    assert same_name("Goals  Over/Under", "goals over/under")
    assert not same_name("Goals Over/Under", "Goals Over/Under First Half")


def test_the_handicaps_by_half_are_extracted_with_the_convention_measured_on_their_own_prices() -> None:
    """Bets 19 and 104 repeat the HOME handicap on both rows exactly like bet 4 (measured on the server on 22 Oct 2026), so they
    are extracted with the away row negated; the other relatives of bet 4 stay parked until someone measures them."""
    for bet_id, name, period in ((4, "Asian Handicap", "FT"), (19, "Asian Handicap First Half", "1H"),
                                 (104, "Asian Handicap (2nd Half)", "2H")):
        spec = spec_for(bet_id, name)
        assert spec.extract and spec.name == name and spec.period == period, bet_id
        assert (spec.schema == "ah" or bet_id == 4) and spec.line_is_signed and spec.away_line_negated, bet_id
    assert spec_for(19).family == spec_for(104).family == "goals_half"
    assert not spec_for(56).extract and not spec_for(81).extract, "corner and card handicaps wait for their own measurement"

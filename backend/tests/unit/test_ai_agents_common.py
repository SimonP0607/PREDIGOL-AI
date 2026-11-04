"""The names of the candidates (``c1``...) the agents of phase 3 share, and the references an answer may make."""

from __future__ import annotations

import dataclasses
import itertools
import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.ai.agents import common
from fbi.ai.contracts.assessment import CANDIDATES_MAX
from fbi.ai.contracts.base import CANDIDATE, COUNTS, REF, parse_ref
from fbi.ai.review import Candidate

KICKOFF = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)


def cand(market: str, selection: str, line: str = "0", *, ev: str | None = "0.05", fixture: int = 7) -> Candidate:
    return Candidate(fixture_id=fixture, market_key=market, selection=selection, line=Decimal(line), p_model=Decimal("0.5"),
                     kickoff_at=KICKOFF, ev=None if ev is None else Decimal(ev))


BASE = [cand("1X2", "Home"), cand("1X2", "Draw"), cand("DC", "1X"), cand("AH", "Home", "-0.5"), cand("OU", "Over", "2.5"),
        cand("OU", "Under", "2.5"), cand("BTTS", "Yes")]


def test_the_names_follow_the_order_of_the_families_then_market_selection_and_line() -> None:
    naming = common.name_candidates(BASE)
    assert naming.keys == ("c1", "c2", "c3", "c4", "c5", "c6", "c7")
    assert [(n.family, n.candidate.selection) for n in naming.named] == [
        ("1X2", "Draw"), ("1X2", "Home"), ("DC", "1X"), ("AH", "Home"), ("OU", "Over"), ("OU", "Under"), ("BTTS", "Yes")]
    assert all(CANDIDATE.match(key) for key in naming.keys)
    assert naming.version == common.NAMING_VERSION == "cand-names-v1"


def test_the_same_candidates_in_any_order_give_the_same_names() -> None:
    reference = common.name_candidates(BASE)
    rng = random.Random(7)
    for _ in range(25):
        shuffled = list(BASE)
        rng.shuffle(shuffled)
        again = common.name_candidates(shuffled)
        assert [(n.key, n.candidate.key) for n in again.named] == [(n.key, n.candidate.key) for n in reference.named]


def test_a_candidate_seen_twice_is_named_once() -> None:
    twice = common.name_candidates([*BASE, cand("1X2", "Home", ev="0.9")])
    assert len(twice.named) == len(BASE)
    assert twice.left_out == ()


def test_a_family_nobody_of_the_phase_reads_is_left_out_and_said() -> None:
    corners = cand("CORNERS_OU", "Over", "9.5")
    halves = cand("1X2_HT", "Home")  # no agent of this plan reads the halves
    naming = common.name_candidates([*BASE, corners, halves])
    assert naming.keys == common.name_candidates(BASE).keys
    assert {(c.market_key, why) for c, why in naming.left_out} == {("CORNERS_OU", "family_not_read"), ("1X2_HT", "family_not_read")}
    counts = common.name_candidates([corners, *BASE], families=COUNTS)
    assert [n.candidate.market_key for n in counts.named] == ["CORNERS_OU"] and counts.keys == ("c1",)


def test_when_there_are_more_than_the_contract_takes_the_larger_expected_value_stays() -> None:
    many = [cand("OU", "Over", f"{i}.5", ev=f"0.{i:02d}") for i in range(1, CANDIDATES_MAX + 3)]
    naming = common.name_candidates(many)
    assert len(naming.named) == CANDIDATES_MAX
    assert naming.keys == tuple(f"c{i}" for i in range(1, CANDIDATES_MAX + 1))
    assert sorted(why for _, why in naming.left_out) == ["beyond_the_limit"] * 2
    assert sorted(c.ev for c, _ in naming.left_out if c.ev is not None) == [Decimal("0.01"), Decimal("0.02")]
    # and the choice does not depend on the order they came in
    for order in itertools.islice(itertools.permutations(many[:4]), 6):
        again = common.name_candidates([*order, *many[4:]])
        assert [n.candidate.key for n in again.named] == [n.candidate.key for n in naming.named]


def test_a_candidate_without_a_value_is_the_first_to_leave() -> None:
    many = [cand("OU", "Over", f"{i}.5", ev=None if i == 3 else "0.04") for i in range(1, CANDIDATES_MAX + 2)]
    naming = common.name_candidates(many)
    assert [c.line for c, _ in naming.left_out] == [Decimal("3.5")]


def test_a_name_resolves_to_its_candidate_and_a_name_the_match_does_not_have_to_nothing() -> None:
    naming = common.name_candidates(BASE)
    first = naming.resolve("c1")
    assert first is not None and first.candidate.market_key == "1X2"
    assert naming.resolve("c8") is None and naming.resolve("c0") is None and naming.resolve("home") is None
    assert [n.family for n in naming.of_family({"OU", "BTTS"})] == ["OU", "OU", "BTTS"]


def test_no_candidates_is_an_empty_naming() -> None:
    naming = common.name_candidates([])
    assert naming.named == () and naming.left_out == () and naming.keys == ()


def test_an_assessment_is_cited_by_its_agent_and_its_mode() -> None:
    label = common.assessment_label("match", "EVALUATION")
    assert label == "match_evaluation"
    assert common.assessment_label("stats", "CONTEXT") == "stats_context"
    ref = parse_ref(f"A:{label}")
    assert ref is not None and ref.kind == "A" and REF.match(f"A:{label}") is not None


def test_the_ids_and_the_paths_a_slice_has_are_what_a_reference_may_name() -> None:
    document = {"header": {"fixture_id": 7}, "shared": {"absences": {"home": [], "away": []}}, "evidence": [{"id": 12}, {"id": 40}, {"id": "x"}, 3]}
    ids, paths = common.known_refs(document)
    assert ids == frozenset({12, 40})
    assert {"header", "shared", "shared.absences", "shared.absences.home", "evidence"} <= paths
    assert common.known_refs({}) == (frozenset(), frozenset())
    assert common.known_refs({"evidence": "12"})[0] == frozenset()


# ---- what the agents read of each other -----------------------------------------------------------------------------------------------

def test_every_contradiction_of_the_catalogue_says_what_it_obliges() -> None:
    assert common.CONTRA_CODES == ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08")
    assert set(common.REQUIRES) == set(common.CONTRA_CODES)
    assert common.REQUIRES["C06"] == "escalate" and common.REQUIRES["C07"] == "research_first" and common.REQUIRES["C08"] == "resolve_in_writing"
    assert {common.REQUIRES[c] for c in ("C01", "C02", "C03", "C04", "C05")} == {"cite_and_explain"}


def test_a_contradiction_is_kept_as_codes_names_references_and_numbers() -> None:
    plain = common.Contradiction("C07", "player:9", ("c1", "c2"), ("E:12", "E:40"))
    assert plain.requires == "research_first"
    assert plain.to_json() == {"code": "C07", "subject": "player:9", "candidates": ["c1", "c2"], "refs": ["E:12", "E:40"],
                               "requires": "research_first"}
    full = common.Contradiction("C03", "team:home", ("c3",), ("P:shared.lineups",), official_lineup=True, starters_out=4,
                                detail=(("days_since", "2"),))
    assert full.to_json()["official_lineup"] is True and full.to_json()["starters_out"] == 4 and full.to_json()["detail"] == {"days_since": "2"}
    gap = common.Contradiction("C06", "pair:c1+c1", ("c1",), gap=Decimal("0.2310"))
    assert gap.to_json()["gap"] == "0.2310" and gap.requires == "escalate"
    assert "confirmed" not in gap.to_json()
    news = common.Contradiction("C01", "player:4", ("c5",), ("E:3",), confirmed=True)
    assert news.to_json()["confirmed"] is True


def test_a_contradiction_cannot_be_changed_once_made() -> None:
    item = common.Contradiction("C02", "team:away", ("c6",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(item, "code", "C01")  # noqa: B010

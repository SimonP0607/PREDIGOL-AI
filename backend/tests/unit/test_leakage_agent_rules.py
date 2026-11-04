"""The pure parts of the leak rules of the agents and of the shadow (plan IA, phase 3): ``agent_known`` and ``shadow_review_known``.

The rules read rows of the database (``tests/integration/test_agent_shadow_leak_audit.py`` runs them against PostgreSQL); what decides a verdict is
pure and is held here, one way of being wrong at a time: what a run or a review cites (``cited_evidence``), the evidence against a moment
(``evidence_problems``), a run against the package, the evidence and the run it says it read (``run_problems``), a review of the shadow against its
packet (``review_problems``), and what Gate B asks of a night (``passes_gate``: no violation, and for ``shadow_review_known`` more than 0 rows)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.ai.config import SHADOW_ENGINES
from fbi.api.services import ai_agents
from fbi.intel import leakage

H = timedelta(hours=1)
KICKOFF = datetime(2026, 9, 15, 19, tzinfo=UTC)
KNOWN = KICKOFF - 6 * H
START = KNOWN + H
HASH = "a" * 64


def run(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"id": 1, "fixture_id": 7, "parent_run_id": None, "started_at": START, "finished_at": START + timedelta(seconds=9),
                           "known_at": KNOWN, "package_hash": HASH, "slice_hash": None, "evidence_ids": [], "data_refs": [], "output": None,
                           "kickoff_at": KICKOFF}
    return row | over


def state(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"fixture_id": 7, "package_hash": HASH, "known_at": KNOWN, "packet_fixture": 7, "packet_built_at": KNOWN + timedelta(minutes=1)}
    return row | over


def problems(row: dict[str, Any], *, times: dict[int, leakage.Times] | None = None, packages: list[dict[str, Any]] | None = None,
             parents: dict[int, dict[str, Any]] | None = None) -> list[str]:
    return leakage.run_problems(row, times=times or {}, packages=[state()] if packages is None else packages, parents=parents or {})


def review(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"id": 1, "fixture_id": 7, "reviewed_at": START, "packet_id": 3, "evidence_ids": [], "packet_fixture": 7,
                           "packet_as_of": KNOWN, "packet_built_at": KNOWN + timedelta(minutes=1), "kickoff_at": KICKOFF}
    return row | over


# ── the registry of the rules ────────────────────────────────────────────────────────────────────────────────────────

def test_both_rules_are_rules_that_run_code_after_slice_known_and_the_text_names_them() -> None:
    assert list(leakage.PYTHON_RULES)[-3:] == ["slice_known", "agent_known", "shadow_review_known"]
    assert leakage.RULE_NAMES[-2:] == ("agent_known", "shadow_review_known")
    assert leakage.PYTHON_RULES["agent_known"] is leakage.agent_known and leakage.PYTHON_RULES["shadow_review_known"] is leakage.shadow_review_known
    for rule in ("agent_known", "shadow_review_known"):
        assert rule not in leakage.RULES and f"    {rule} " in (leakage.__doc__ or "")
    assert len(set(leakage.RULE_NAMES)) == len(leakage.RULE_NAMES)


def test_the_version_is_not_bumped_by_two_rules_that_read_nothing_of_the_decisions() -> None:
    assert leakage.VERSION == "leak-audit-v8"


def test_the_console_audits_the_plans_four_rules_and_leaves_memory_known_unaudited() -> None:
    assert ai_agents.AUDIT_RULES == ("slice_known", "agent_known", "review_known", "shadow_review_known")
    assert "memory_known" in ai_agents.PLAN_AUDIT_RULES and "memory_known" not in ai_agents.AUDIT_RULES


def test_the_engines_the_rule_reads_are_the_shadow_ones_and_never_the_production_ones() -> None:
    assert SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1")
    assert not {"rules", "llm", "combined"} & set(SHADOW_ENGINES)
    named = re.search(r"r\.engine IN \(([^)]*)\)", leakage.SHADOW_REVIEWS)
    assert named and tuple(e.strip().strip("'") for e in named.group(1).split(",")) == SHADOW_ENGINES


def test_a_database_from_before_the_tables_has_nothing_to_read() -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: object = None) -> None:
            self.sql = sql

        def fetchone(self) -> tuple[bool]:
            return (False,)

    class Conn:
        def cursor(self, **kwargs: object) -> Cursor:
            return Cursor()

    start = KICKOFF - 24 * H
    assert leakage.agent_known(Conn(), start, KICKOFF) == (0, 0, [])  # type: ignore[arg-type]
    assert leakage.shadow_review_known(Conn(), start, KICKOFF) == (0, 0, [])  # type: ignore[arg-type]


# ── what a run cites ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_run_cites_its_ids_the_evidence_of_its_data_refs_and_the_references_inside_its_output() -> None:
    row = run(evidence_ids=[5, 6], data_refs=["E:7", "P:shared.absences", "A:match_1", "garbage"],
              output={"drivers": [{"refs": ["E:8", "P:market"]}], "nested": {"deep": ["E:9"]}, "text": "see E:10 and E:11", "n": 12})
    assert leakage.cited_evidence(row) == {5, 6, 7, 8, 9}, "a number or a mention in a sentence is not a reference"


def test_a_run_with_nothing_cited_and_a_document_nested_without_end_are_read_without_trouble() -> None:
    assert leakage.cited_evidence(run()) == set()
    deep: Any = ["E:99"]
    for _ in range(40):
        deep = [deep]
    assert leakage.cited_evidence(run(output={"x": deep})) == set(), "past the depth the contracts allow nothing is read (and nothing loops)"
    assert leakage.cited_evidence(run(evidence_ids=None, data_refs=None)) == set()


# ── the evidence against a moment ────────────────────────────────────────────────────────────────────────────────────

def test_evidence_must_exist_and_be_retrieved_and_published_by_the_moment() -> None:
    times: dict[int, leakage.Times] = {1: (KNOWN, KNOWN - H), 2: (KNOWN + timedelta(seconds=1), None), 3: (KNOWN - H, KNOWN + H), 4: (KNOWN - H, None)}
    assert leakage.evidence_problems({1, 4}, times, KNOWN) == [], "the very moment is known"
    assert leakage.evidence_problems({2}, times, KNOWN) == ["evidence_late"], "retrieved a second after"
    assert leakage.evidence_problems({3}, times, KNOWN) == ["evidence_late"], "published after"
    assert leakage.evidence_problems({9}, times, KNOWN) == ["evidence_missing"], "a row that is not there cannot be proved"
    assert leakage.evidence_problems({2, 9}, times, KNOWN) == ["evidence_missing", "evidence_late"]
    assert leakage.evidence_problems(set(), times, KNOWN) == []


# ── a run ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_honest_run_has_no_problem_and_a_run_that_read_nothing_is_honest_without_a_moment() -> None:
    times: dict[int, leakage.Times] = {5: (KNOWN - H, KNOWN - 2 * H)}
    assert problems(run(evidence_ids=[5], output={"refs": ["E:5"]}), times=times) == []
    assert problems(run(package_hash=None, known_at=None)) == [], "a skipped run that read nothing"


def test_a_moment_of_knowledge_after_the_run_or_after_the_kickoff_is_a_leak() -> None:
    assert problems(run(known_at=START + timedelta(seconds=1)), packages=[state(known_at=START + timedelta(seconds=1))]) == ["known_after_start"]
    assert problems(run(known_at=START)) == ["package_unknown"], "the package says another moment"
    late = KICKOFF + timedelta(minutes=1)
    assert "known_after_kickoff" in problems(run(known_at=KICKOFF, started_at=late), packages=[state(known_at=KICKOFF)])
    assert problems(run(known_at=KICKOFF - timedelta(seconds=1), started_at=KICKOFF), packages=[state(known_at=KICKOFF - timedelta(seconds=1))]) == []
    assert problems(run(kickoff_at=None)) == [], "a run of no match has no kick-off to be before"


def test_a_reference_with_no_moment_cannot_be_proved() -> None:
    assert problems(run(known_at=None)) == ["no_known_at", "package_unknown"]
    assert problems(run(package_hash=None, known_at=None, slice_hash=HASH)) == ["no_known_at"]
    assert problems(run(package_hash=None, known_at=None, evidence_ids=[5]), times={5: (KNOWN, None)}) == ["no_known_at"]


def test_the_package_a_run_names_is_one_of_its_own_match_at_its_moment_from_a_packet_stored_by_its_start() -> None:
    assert problems(run(), packages=[]) == ["package_unknown"]
    assert problems(run(), packages=[state(fixture_id=8)]) == ["package_unknown"], "the same hash, another match"
    assert problems(run(), packages=[state(package_hash="b" * 64)]) == ["package_unknown"]
    assert problems(run(), packages=[state(packet_built_at=START + timedelta(seconds=1))]) == ["package_late"], "stored after the run began"
    assert problems(run(), packages=[state(packet_built_at=START)]) == [], "stored the very moment it began"
    assert problems(run(), packages=[state(packet_fixture=8)]) == ["package_late"], "the packet is another match's"
    assert problems(run(), packages=[state(packet_built_at=START + H), state()]) == [], "one honest state of the package is enough"


def test_evidence_a_run_cites_is_judged_at_the_moment_of_its_knowledge_not_at_its_start() -> None:
    after_known = (KNOWN + timedelta(minutes=5), None)  # before the run began, after the package's moment
    assert problems(run(evidence_ids=[5]), times={5: after_known}) == ["evidence_late"]
    assert problems(run(evidence_ids=[5]), times={}) == ["evidence_missing"]
    assert problems(run(output={"refs": ["E:5"]}), times={5: after_known}) == ["evidence_late"], "a reference inside the output counts as much"
    assert problems(run(data_refs=["E:5"]), times={5: after_known}) == ["evidence_late"]


def test_the_assessment_the_council_reads_must_be_a_run_of_the_same_match_that_had_finished() -> None:
    parent = {"id": 1, "fixture_id": 7, "finished_at": START}
    assert problems(run(parent_run_id=1), parents={1: parent}) == [], "finished the very moment the council began"
    assert problems(run(parent_run_id=1), parents={1: parent | {"finished_at": START + timedelta(seconds=1)}}) == ["parent_after"]
    assert problems(run(parent_run_id=1), parents={1: parent | {"fixture_id": 8}}) == ["parent_other_match"]
    assert problems(run(parent_run_id=1), parents={}) == ["parent_missing"]
    assert problems(run(parent_run_id=1, fixture_id=None), parents={1: parent | {"fixture_id": None}}, packages=[]) == ["package_unknown"]


def test_every_problem_of_a_run_is_reported_and_none_hides_another() -> None:
    row = run(known_at=START + H, evidence_ids=[5, 6], parent_run_id=2)
    got = problems(row, times={5: (START + 2 * H, None)}, packages=[], parents={})
    assert got == ["known_after_start", "package_unknown", "evidence_missing", "evidence_late", "parent_missing"]


# ── a review of the shadow ───────────────────────────────────────────────────────────────────────────────────────────

def test_an_honest_review_cites_a_packet_of_its_match_and_evidence_known_at_the_moment_of_the_packet() -> None:
    times: dict[int, leakage.Times] = {5: (KNOWN, KNOWN - H)}
    assert leakage.review_problems(review(evidence_ids=[5]), times=times) == []
    assert leakage.review_problems(review(evidence_ids=[]), times={}) == [], "a review that cites nothing is honest: it has nothing to leak"


def test_a_review_with_no_packet_or_with_another_matchs_or_a_later_one_is_a_leak() -> None:
    assert leakage.review_problems(review(packet_id=None, packet_fixture=None, packet_as_of=None, packet_built_at=None), times={}) == ["packet_unknown"]
    assert leakage.review_problems(review(packet_fixture=None, packet_as_of=None, packet_built_at=None), times={}) == ["packet_unknown"], "named, not there"
    assert leakage.review_problems(review(packet_fixture=8), times={}) == ["packet_unknown"]
    assert leakage.review_problems(review(packet_built_at=START + timedelta(seconds=1)), times={}) == ["packet_late"]
    assert leakage.review_problems(review(packet_built_at=START), times={}) == []
    assert leakage.review_problems(review(packet_as_of=START + timedelta(seconds=1)), times={}) == ["moment_late"]


def test_a_review_written_at_or_after_the_kickoff_is_a_leak() -> None:
    assert leakage.review_problems(review(reviewed_at=KICKOFF), times={}) == ["after_kickoff"]
    assert leakage.review_problems(review(reviewed_at=KICKOFF - timedelta(seconds=1)), times={}) == []
    assert leakage.review_problems(review(kickoff_at=None, reviewed_at=KICKOFF + H), times={}) == []


def test_evidence_known_after_the_review_or_after_the_moment_of_its_packet_is_a_leak() -> None:
    after_review: dict[int, leakage.Times] = {5: (START + timedelta(seconds=1), None)}
    after_packet: dict[int, leakage.Times] = {5: (KNOWN + timedelta(minutes=5), None)}  # before the review, after the packet
    assert leakage.review_problems(review(evidence_ids=[5]), times=after_review) == ["evidence_late"]
    assert leakage.review_problems(review(evidence_ids=[5]), times=after_packet) == ["evidence_late"]
    assert leakage.review_problems(review(evidence_ids=[5]), times={5: (KNOWN, KNOWN + timedelta(seconds=1))}) == ["evidence_late"], "published later"
    assert leakage.review_problems(review(evidence_ids=[5, 6]), times={5: (KNOWN, None)}) == ["evidence_missing"]
    no_packet = review(packet_id=None, packet_fixture=None, packet_as_of=None, packet_built_at=None, evidence_ids=[5])
    assert leakage.review_problems(no_packet, times=after_packet) == ["packet_unknown"], "with no packet the review itself is the moment, and it saw that"
    assert leakage.review_problems(no_packet, times=after_review) == ["packet_unknown", "evidence_late"]


# ── Gate B reads the night ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("rule", "checked", "violations", "clean"), [
    ("shadow_review_known", 12, 0, True),
    ("shadow_review_known", 0, 0, False),
    ("shadow_review_known", 12, 1, False),
    ("shadow_review_known", 0, 1, False),
    ("agent_known", 0, 0, True),
    ("agent_known", 3, 1, False),
    ("slice_known", 0, 0, True),
    ("review_known", 0, 0, True),
])
def test_a_night_is_clean_when_it_has_no_violation_and_the_shadow_review_saw_rows(rule: str, checked: int, violations: int, clean: bool) -> None:
    assert leakage.passes_gate(rule, checked, violations) is clean


def test_only_the_shadow_review_needs_data() -> None:
    assert {"shadow_review_known"} == leakage.NEEDS_DATA
    assert set(leakage.RULE_NAMES) >= leakage.NEEDS_DATA

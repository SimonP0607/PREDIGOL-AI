"""What the research of an entity does (plan IA, phase 2): the owner's word, and ``on`` only while the newest evidence of the ``research_v2`` gate says
it passed. ``off`` and ``shadow`` need no evidence, and no evidence turns anything on by itself."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import gates
from fbi.ai.config import AiSettings

pytestmark = pytest.mark.integration

AT = datetime(2032, 9, 9, 17, 0, tzinfo=UTC)
EVIDENCE = {"gate": "research-v2-gate", "comparison_days": 7}


def settings(word: str) -> AiSettings:
    return AiSettings(research_v2=word)  # type: ignore[arg-type]


def record(db: psycopg.Connection[Any], *, passed: bool, at: datetime = AT, evidence: dict[str, Any] | None = None) -> int:
    return gates.record_gate(db, gate="research_v2", passed=passed, at=at, evidence=evidence or EVIDENCE)


def test_without_evidence_on_is_shadow_and_the_other_words_are_what_they_say(db: psycopg.Connection[Any]) -> None:
    assert gates.gate_state(db, "research_v2").passed is False
    assert [gates.research_mode(db, settings(w)) for w in ("off", "shadow", "on")] == ["off", "shadow", "shadow"]


def test_with_a_passed_gate_on_stands_and_nothing_else_changes(db: psycopg.Connection[Any]) -> None:
    record(db, passed=True)
    assert [gates.research_mode(db, settings(w)) for w in ("off", "shadow", "on")] == ["off", "shadow", "on"], \
        "the gate lets ``on`` stand; it never turns ``off`` or ``shadow`` into anything"


def test_the_newest_row_decides_so_a_failing_rerun_takes_it_back_to_shadow(db: psycopg.Connection[Any]) -> None:
    record(db, passed=True, at=AT)
    assert gates.research_mode(db, settings("on")) == "on"
    record(db, passed=False, at=AT + timedelta(days=1), evidence={**EVIDENCE, "verdict": "NO PASA"})
    assert gates.research_mode(db, settings("on")) == "shadow"
    record(db, passed=True, at=AT + timedelta(days=2))
    assert gates.research_mode(db, settings("on")) == "on"


def test_an_older_passed_row_does_not_outvote_a_newer_failed_one(db: psycopg.Connection[Any]) -> None:
    record(db, passed=False, at=AT + timedelta(days=3))
    record(db, passed=True, at=AT)  # written later, but measured earlier: the newest by ``at`` decides
    assert gates.research_mode(db, settings("on")) == "shadow"


def test_another_gate_passing_is_not_this_gate(db: psycopg.Connection[Any]) -> None:
    for gate in gates.GATES:
        if gate != "research_v2":
            gates.record_gate(db, gate=gate, passed=True, at=AT, evidence={"note": gate})
    assert gates.research_mode(db, settings("on")) == "shadow"


def test_the_description_says_what_was_asked_what_runs_and_why(db: psycopg.Connection[Any]) -> None:
    off = gates.research_describe(db, settings("off"))
    assert (off["asked"], off["mode"]) == ("off", "off") and "does not know" in off["why"]
    shadow = gates.research_describe(db, settings("shadow"))
    assert (shadow["asked"], shadow["mode"]) == ("shadow", "shadow") and "v1 decides" in shadow["why"]
    waiting = gates.research_describe(db, settings("on"))
    assert (waiting["asked"], waiting["mode"]) == ("on", "shadow") and "waiting for the research_v2 gate" in waiting["why"]
    assert waiting["gate"] == {"gate": "research_v2", "passed": False, "at": None, "evidence_hash": None, "models": None}
    record(db, passed=True)
    stands = gates.research_describe(db, settings("on"))
    assert (stands["asked"], stands["mode"]) == ("on", "on") and "replaces v1" in stands["why"]
    assert stands["gate"]["passed"] is True and stands["gate"]["evidence_hash"] == gates.evidence_hash(EVIDENCE)


def test_the_phase_zero_description_is_what_it_was_plus_the_gate_in_its_map(db: psycopg.Connection[Any]) -> None:
    """``gates.describe`` feeds the cost panel of phase 0: no new switch there (research v2 is not a two-state optimisation), the new gate only as a
    key of ``gates``."""
    described = gates.describe(db, settings("on"))
    assert set(described) == {"cache", "batch", "native_schema", "brief_material", "budget_v3", "cache_layout", "gates"}
    assert set(described["gates"]) == set(gates.GATES) - {gates.SWITCHES}, "the ledger of the owner's words is not a gate: the panel does not show it"
    assert described["gates"]["research_v2"]["passed"] is False
    record(db, passed=True)
    assert gates.describe(db, settings("on"))["gates"]["research_v2"]["passed"] is True


def test_the_gate_is_recorded_like_any_other_and_a_name_nobody_knows_is_still_refused(db: psycopg.Connection[Any]) -> None:
    row = record(db, passed=True)
    assert isinstance(row, int) and row > 0
    with pytest.raises(ValueError, match="unknown gate"):
        gates.record_gate(db, gate="research_v3", passed=True, at=AT, evidence=EVIDENCE)
    with pytest.raises(ValueError, match="unknown gate"):
        gates.gate_state(db, "research")

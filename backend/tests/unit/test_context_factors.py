"""The registry of context factors without a database (plan F6): the catalogue, what a packet says of a standing, and the rules a decision
has to meet before it is written."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fbi.competitions import team_calendar
from fbi.intel import factors, h2h, scenarios, tactics

WHEN = datetime(2034, 4, 12, 9, 30, tzinfo=UTC)


def decision(status: str = factors.VALIDATED, **change: Any) -> factors.Decision:
    base: dict[str, Any] = {
        "id": 7, "factor": factors.H2H, "version": h2h.VERSION, "status": status, "decided_at": WHEN, "decided_by": "owner",
        "who": "Simon", "reason": "the experiment of the weighted record beat the form", "previous_id": None,
        "evidence": {"factor": factors.H2H, "version": h2h.VERSION, "experiment": "F12-h2h-01", "result": {"delta_logloss": -0.004}}}
    return factors.Decision(**(base | change))


# ── the catalogue ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_context_factor_of_the_packet_is_in_the_catalogue_at_the_version_in_force() -> None:
    assert {f.key: f.version for f in factors.CATALOGUE} == {
        "h2h_weighted": h2h.VERSION, "scenarios": scenarios.VERSION, "tactics_profile": tactics.VERSION,
        "rest_congestion": team_calendar.VERSION}


def test_the_keys_are_unique_and_may_be_stored() -> None:
    keys = [f.key for f in factors.CATALOGUE]
    assert len(keys) == len(set(keys)) and {f.key: f for f in factors.CATALOGUE} == factors.BY_KEY
    for key in keys:
        assert key not in factors.RESERVED, "a factor cannot be called like another key of the packet block"
        assert 2 <= len(key) <= 63 and key[0].isalpha() and key == key.lower() and all(c.isalnum() or c == "_" for c in key), \
            "the database accepts [a-z][a-z0-9_]{1,62}"


def test_each_factor_says_in_spanish_what_it_is_and_what_an_experiment_would_have_to_show() -> None:
    for f in factors.CATALOGUE:
        assert f.label and f.claim.startswith("que "), f.key
        assert f.block and all(f.block), f.key
    assert factors.BY_KEY["tactics_profile"].where == "dossier.tactics"
    assert factors.BY_KEY["rest_congestion"].where == "schedule"


def test_the_blocks_that_say_their_own_status_are_the_three_that_carry_one() -> None:
    assert {f.key for f in factors.CATALOGUE if f.states} == {"h2h_weighted", "scenarios", "tactics_profile"}


def test_a_factor_the_registry_does_not_know_is_refused_by_name() -> None:
    assert factors.known("h2h_weighted").version == h2h.VERSION
    with pytest.raises(LookupError, match="not a context factor"):
        factors.known("moon_phase")


# ── what the packet says ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_factor_with_no_decision_is_descriptive() -> None:
    entry = factors.unread()
    assert set(entry) == set(factors.BY_KEY)
    assert all(s.status == factors.DESCRIPTIVE and s.decision is None for s in entry.values())
    assert entry["h2h_weighted"].as_packet() == {"version": h2h.VERSION, "block": "h2h", "status": "DESCRIPTIVE", "decision": None}


def test_a_validated_factor_says_when_and_by_which_experiment_but_not_who_or_why() -> None:
    s = factors.Standing(factors.BY_KEY[factors.H2H], decision())
    assert s.status == factors.VALIDATED
    assert s.as_packet() == {"version": h2h.VERSION, "block": "h2h", "status": "VALIDATED",
                             "decision": {"id": 7, "decided_at": WHEN.isoformat(), "experiment": "F12-h2h-01"}}
    text = repr(s.as_packet())
    assert "Simon" not in text and "weighted record" not in text, "the packet goes to a language model: no names, no free text"


def test_a_validation_taken_back_is_descriptive_with_the_decision_that_says_so() -> None:
    back = decision(factors.DESCRIPTIVE, id=8, previous_id=7, evidence={"retired_decision": 7, "retired_experiment": "F12-h2h-01"})
    s = factors.Standing(factors.BY_KEY[factors.H2H], back)
    assert s.status == factors.DESCRIPTIVE and back.experiment is None
    assert s.as_packet()["decision"] == {"id": 8, "decided_at": WHEN.isoformat(), "experiment": None}


def test_the_block_lists_every_factor_with_its_note_and_names_a_registry_it_could_not_read() -> None:
    got = factors.block(factors.unread())
    assert list(got) == ["version", "note", *factors.BY_KEY]
    assert got["version"] == factors.VERSION and "DESCRIPTIVE" in got["note"] and "VALIDATED" in got["note"]
    broken = factors.block(factors.unread(), error="UndefinedTable")
    assert broken["error"] == "UndefinedTable" and all(broken[k]["status"] == "DESCRIPTIVE" for k in factors.BY_KEY)


# ── what a decision has to meet ────────────────────────────────────────────────────────────────────────────────────────


def test_a_reason_says_something_and_is_kept_without_its_padding() -> None:
    assert factors.check_reason("   the experiment beat the form   ") == "the experiment beat the form"
    for short in ("", "   ", "too short"):
        with pytest.raises(ValueError, match="at least 10"):
            factors.check_reason(short)


def test_a_decision_names_its_person() -> None:
    assert factors.check_who("  Simon ") == "Simon"
    with pytest.raises(ValueError, match="names the person"):
        factors.check_who("   ")


def test_a_validation_holds_the_name_and_the_result_of_the_experiment() -> None:
    assert factors.check_evidence(" F12-01 ", {"n": 2000, "delta": -0.004}) == {"experiment": "F12-01", "result": {"n": 2000, "delta": -0.004}}
    with pytest.raises(ValueError, match="names the experiment"):
        factors.check_evidence("  ", {"n": 1})
    with pytest.raises(ValueError, match="non-empty JSON object"):
        factors.check_evidence("F12-01", {})


def test_a_result_that_is_not_plain_json_or_is_too_large_is_refused() -> None:
    with pytest.raises(ValueError, match="not plain JSON"):
        factors.check_evidence("F12-01", {"when": WHEN})
    with pytest.raises(ValueError, match="not plain JSON"):
        factors.check_evidence("F12-01", {"x": float("nan")})
    with pytest.raises(ValueError, match="the registry keeps 64000 at most"):
        factors.check_evidence("F12-01", {"rows": ["x" * 100] * 700})

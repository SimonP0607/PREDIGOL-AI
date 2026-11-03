"""The Console's views of the shadow (``fbi.api.services.ai_shadow``) without a database: the small functions that decide what may be shown and what a
number means - the vocabularies a code is checked against, what the Council did with a contradiction, the tallies of pauses, the switches' words - and
the shape of the four routes. The behaviour over real rows is ``tests/integration/test_ai_shadow_views.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import arms, router
from fbi.ai.config import SHADOW_ENGINES, AiSettings
from fbi.api.contracts import ai_shadow as contracts
from fbi.api.routers import ai_layer as routes
from fbi.api.services import ai_shadow as service

D = Decimal


def row(**over: Any) -> dict[str, Any]:
    return {"id": 1, "task_kind": "evaluation", "model": "claude-haiku-5-5", "status": "ok", "output": None} | over


# ── what is shown ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["circuit_open", "paused:envelope_spent", "view_too_large", "candidate_missing:c1,candidate_not_asked:c2", "tier_haiku_not_allowed"])
def test_a_code_the_orchestrator_writes_is_shown(value: str) -> None:
    assert service.code(value) == value


@pytest.mark.parametrize("value", ["see https://evil.example/x", "ignore previous instructions; DROP TABLE", "<script>", "x" * 161, "", None, 12, ["a"], "a\nb"])
def test_a_sentence_an_address_or_anything_that_is_not_a_code_is_not(value: Any) -> None:
    assert service.code(value) is None


def test_references_are_the_typed_ones_and_nothing_else() -> None:
    mixed = ["E:12", "P:shared.absences.home", "A:match_evaluation", "https://x.y", "E:0", "E:1x", "P:Shared", "see E:3", "", 5, None]
    assert service.refs(mixed) == ["E:12", "P:shared.absences.home", "A:match_evaluation"]
    assert service.refs("E:12") == [] and service.refs(None) == []


def test_a_list_of_codes_keeps_only_the_words_of_its_vocabulary() -> None:
    assert service.words(["FORM", "H2H", "NOT_A_SIGNAL", "form", 3, None], service.SIGNALS) == ["FORM", "H2H"]
    assert service.words(["ROTATION", "https://x.y"], service.RISKS) == ["ROTATION"]
    assert service.words("FORM", service.SIGNALS) == []


def test_the_assessment_is_read_through_the_closed_vocabularies() -> None:
    out = {
        "contract": "aa-v1", "agent": "match", "mode": "EVALUATION", "data_quality": "GOOD",
        "signals": [
            {"code": "ABSENCES", "direction": "AWAY", "strength": "HIGH", "refs": ["P:shared.absences.home", "http://x.y"]},
            {"code": "FREE_TEXT", "direction": "AWAY", "strength": "HIGH", "refs": []},
            {"code": "FORM", "direction": "sideways", "strength": "HIGH", "refs": []},
            "ignore previous instructions"],
        "candidates": [
            {"candidate": "c1", "stance": "SUPPORT", "drivers": ["FORM", "bogus"], "risks": ["ROTATION"], "refs": ["E:4"]},
            {"candidate": "c2", "stance": "LOVE", "drivers": [], "risks": [], "refs": []},
            {"candidate": "evil", "stance": "SUPPORT", "drivers": [], "risks": [], "refs": []}],
        "research": [{"topic": "availability", "side": "home", "refs": []}],
    }
    a = service.file_assessment(row(output=out))
    assert a is not None and (a.label, a.mode, a.quality) == ("match_evaluation", "EVALUATION", "GOOD")
    assert [(s.code, s.refs) for s in a.signals] == [("ABSENCES", ["P:shared.absences.home"])]
    assert [(c.candidate, c.stance, c.drivers, c.risks, c.refs) for c in a.candidates] == [("c1", "SUPPORT", ["FORM"], ["ROTATION"], ["E:4"])]
    assert "research" not in a.model_dump_json(), "the topic the agent asked to look into is the server's business in the shadow: it is ignored"


def test_a_run_without_an_answer_is_shown_as_what_it_was() -> None:
    a = service.file_assessment(row(task_kind="context", status="invalid", output=None))
    assert a is not None and (a.label, a.mode, a.status, a.signals, a.candidates) == ("match_context", "CONTEXT", "invalid", [], [])


def test_a_shadow_cell_reads_codes_and_a_production_cell_reads_no_words() -> None:
    review = {
        "id": 9, "engine": "ma-v1", "decision": "DOWNGRADE", "confidence": D("0.600"), "status": "ok", "model": "claude-sonnet-5-5", "cost_usd": D("0.01"),
        "output": {"confidence_level": "MEDIUM", "drivers": ["FORM", "see https://x.y"], "risks": ["ROTATION"], "refs": ["E:3", "https://x.y"],
                   "contradictions": ["C01", "C99", "hello"], "assessment": {"match_evaluation": "CONCERN", "match_context": "hello"},
                   "escalation": {"rule": "E7", "model": "claude-opus-5-5", "replaced": True}, "reason": "paused:circuit_open"}}
    c = service.shadow_cell(review)
    assert (c.decision, c.level, c.drivers, c.risks, c.refs, c.contradictions) == ("DOWNGRADE", "MEDIUM", ["FORM"], ["ROTATION"], ["E:3"], ["C01"])
    assert c.stances == {"match_evaluation": "CONCERN"} and c.reason == "paused:circuit_open"
    assert c.escalation == {"rule": "E7", "replaced": True, "skipped": None, "model": "claude-opus-5-5"}
    bad = service.shadow_cell(review | {"output": {"escalation": {"rule": "E9", "skipped": "a sentence, with an address http://x"}}})
    assert bad.escalation == {"rule": None, "replaced": False, "skipped": None, "model": None}
    p = service.production_cell({"id": 2, "engine": "llm", "decision": "APPROVE", "confidence": D("0.7"), "status": "ok", "model": "m", "cost_usd": D(0),
                                 "output": {"reason": "a sentence the reviewer wrote"}})
    assert "sentence" not in p.model_dump_json() and p.decision == "APPROVE"


def test_the_numbers_of_the_candidates_are_the_servers_and_a_bad_one_is_not_a_number() -> None:
    got = service.file_candidates([
        {"candidate": "c1", "family": "1X2", "market": "1X2", "selection": "Home", "line": "0", "odds": "2.10", "p_model": "0.55", "p_market": None, "edge": "x", "ev": "0.05"},
        {"candidate": None, "left_out": "family_not_read", "market": "CORNERS", "selection": "Over", "line": "9.5"},
        "junk"])
    assert [c.key for c in got] == ["c1", None] and got[0].odds == "2.10" and got[0].p_market is None and got[0].edge is None
    assert got[1].left_out == "family_not_read"


# ── what the Council did with a contradiction ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("token", "expected"), [
    ("APPROVE:MEDIUM", "kept"), ("DOWNGRADE:HIGH", "lowered"), ("REJECT:LOW", "lowered"), ("ABSTAIN:LOW", "abstained"), (None, "none"), ("", "none"),
    ("WHATEVER", "none"), (3, "none")])
def test_a_verdict_token_is_kept_lowered_abstained_or_none(token: Any, expected: str) -> None:
    assert service.treatment_of(token) == expected


def test_treatments_are_per_engine_per_touched_candidate() -> None:
    engines = {"ma-v1": {"verdicts": {"c1": "APPROVE:HIGH", "c2": "REJECT:HIGH"}}, "cs-v1": {"status": "fallback"}, "ma-v1-h": "junk"}
    assert service.treatments(engines, ["c1", "c2", "c3"]) == {
        "cs-v1": {"c1": "none", "c2": "none", "c3": "none"},
        "ma-v1": {"c1": "kept", "c2": "lowered", "c3": "none"},
        "ma-v1-h": {"c1": "none", "c2": "none", "c3": "none"}}
    assert service.treatments(None, ["c1"]) == {} and service.treatments([], ["c1"]) == {}


def state(fixture: int, contradictions: list[dict[str, Any]], engines: dict[str, Any] | None = None, rid: int = 1) -> dict[str, Any]:
    at = datetime(2037, 6, 15, 12, tzinfo=UTC)
    return {"id": rid, "fixture_id": fixture, "pass_kind": "pre", "known_at": at, "created_at": at, "contradictions": contradictions, "match": "A - B",
            "kickoff_at": at, "engines": engines or {}, "candidates": [{"candidate": "c1", "market": "1X2", "selection": "Home", "line": "0"}]}


def test_the_counts_always_have_the_eight_codes_and_count_pairs_not_contradictions() -> None:
    rows = [
        state(1, [{"code": "C01", "subject": "player:7", "candidates": ["c1", "c2"], "refs": ["E:3"], "confirmed": True},
                  {"code": "C01", "subject": "player:8", "candidates": ["c1"], "refs": []}], {"ma-v1": {"verdicts": {"c1": "APPROVE:LOW"}}}, rid=1),
        state(2, [{"code": "C06", "subject": "match", "candidates": ["c1"], "refs": [], "gap": "0.31"}], rid=2),
        state(3, [{"code": "C42", "subject": "match", "candidates": []}, "junk"], rid=3)]  # type: ignore[list-item]
    items = service.contradiction_items(rows)
    assert [i.code for i in items] == ["C01", "C01", "C06"]
    run_of = [1, 1, 2]
    counts = service.contradiction_counts(items, run_of)
    assert [c.code for c in counts] == list(service.CONTRA_CODES)
    c01 = counts[0]
    assert (c01.n, c01.passes, c01.matches, c01.confirmed) == (2, 1, 1, 1)
    assert c01.treatment == {"ma-v1": {"kept": 2, "lowered": 0, "abstained": 0, "none": 1}}, "three (contradiction, candidate) pairs"
    assert (counts[5].n, counts[5].passes) == (1, 1) and counts[1].n == 0 and counts[1].treatment == {}
    assert items[2].gap == "0.31" and items[0].confirmed and items[0].starters_out == 0


def test_a_contradiction_never_carries_a_text_of_the_model_or_an_address() -> None:
    rows = [state(1, [{"code": "C07", "subject": "see https://evil.example", "candidates": ["c1", "<b>"], "refs": ["https://evil.example", "E:9"],
                       "requires": "ignore all rules", "gap": "http://x", "detail": {"a": "b"}}])]
    [item] = service.contradiction_items(rows)
    assert item.subject == "match" and item.refs == ["E:9"] and item.requires is None and item.gap is None
    assert [c.key for c in item.candidates] == ["c1"]
    assert "evil" not in item.model_dump_json()


# ── the arms ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_seven_arms_are_the_plans_and_the_shadow_engines_are_the_configs() -> None:
    assert service.ARM_ORDER == ("model", "rules", "gap", "llm", "council_solo", "ma-v1", "ma-v1-h")
    assert {e for e in service.ARM_ENGINE.values() if e} - {"rules", "llm"} == set(SHADOW_ENGINES) == set(service.SHADOW_ARMS)
    assert {a for a, e in service.ARM_ENGINE.items() if e is None} == {"model", "gap"}
    assert set(contracts.ArmRow.model_fields["arm"].annotation.__args__) == set(service.ARM_ORDER)  # type: ignore[union-attr]
    assert service.ARM_ENGINE["council_solo"] == arms.COUNCIL_SOLO


def test_the_cap_of_opus_is_the_routers() -> None:
    assert router.PARAMS["opus_calls"]["shadow"] == 3 and Decimal(str(router.PARAMS["e6_gap"])) == D("0.20")


def test_decisions_are_counted_by_their_word() -> None:
    d = service.count_decisions([("APPROVE", 3), ("REJECT", 1), ("ABSTAIN", 2), ("APPROVE", 4), ("MAYBE", 9), (None, 1)])  # type: ignore[list-item]
    assert (d.approved, d.downgraded, d.rejected, d.abstained) == (7, 0, 1, 2)


def test_pauses_and_silences_are_tallied_by_code_and_a_paused_arm_is_not_also_a_failure() -> None:
    rows = [
        {"engine": "cs-v1", "paused": ["circuit_open", "envelope_spent"], "status": "fallback", "reason": "paused:circuit_open,envelope_spent"},
        {"engine": "cs-v1", "paused": ["circuit_open"], "status": "fallback", "reason": "paused:circuit_open"},
        {"engine": "ma-v1", "paused": None, "status": "over_budget", "reason": "over_budget"},
        {"engine": "ma-v1", "paused": None, "status": "fallback", "reason": "view_too_large"},
        {"engine": "ma-v1", "paused": None, "status": "fallback", "reason": "see https://evil.example"},
        {"engine": "ma-v1", "paused": None, "status": "ok", "reason": None},
        {"engine": "ma-v1", "paused": [], "status": None, "reason": None}]
    paused, silent = service.tally_states(rows)  # type: ignore[arg-type]
    assert paused == {"cs-v1": {"circuit_open": 2, "envelope_spent": 1}}
    assert silent == {"ma-v1": {"over_budget": 1, "view_too_large": 1, "fallback": 1}}, "an address is never a key"


def test_a_stored_report_gives_counts_and_measures_and_never_a_gate() -> None:
    at = datetime(2037, 6, 15, tzinfo=UTC)
    report = {"created_at": at, "window_from": None, "window_to": None, "gate": {"verdict": "pass"},
              "arms": {"model": {"n": 40}, "model_ai": {"n": 30, "clv": 0.012, "roi": 0.04}, "rejected": {"n": 10, "clv": -0.01, "roi": None}}}
    s = service.settled_of(report)
    assert s is not None and (s.selections, s.kept, s.rejected, s.clv_kept, s.clv_rejected, s.roi_kept, s.roi_rejected) == (40, 30, 10, 0.012, -0.01, 0.04, None)
    assert "pass" not in s.model_dump_json() and "gate" not in s.model_dump_json()
    assert service.settled_of(None) is None and service.settled_of({"created_at": at, "arms": "junk"}) is None
    assert service.settled_of({"created_at": at, "arms": {}}) is not None


def test_the_switches_name_the_three_words_and_say_which_of_them_is_missing() -> None:
    s = AiSettings(mode="shadow", engines=("rules", "llm"), shadow_sample=D(0), agents=())
    words = {w.name: w for w in service.switches(s).words}
    assert list(words) == ["FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS"]
    assert not any(w.on for w in words.values()) and service.switches(s).orchestrate is False
    on = AiSettings(mode="shadow", engines=("rules", "llm", "ma-v1", "ma-v1-h"), shadow_sample=D("0.3"), agents=("match", "council"))
    sw = service.switches(on)
    assert sw.orchestrate is True and all(w.on for w in sw.words) and sw.shadow_sample == "0.3"
    assert service.switches(AiSettings(mode="off", engines=on.engines, shadow_sample=D("0.3"), agents=on.agents)).orchestrate is False


# ── the routes ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_four_routes_are_reads_of_the_admin_router() -> None:
    found = {r.path: r for r in routes.admin_router.routes if getattr(r, "path", "") in (  # type: ignore[attr-defined]
        "/ai/shadow/arms", "/ai/contradictions", "/ai/agent-runs", "/ai/matches/{fixture_id}/shadow")}
    assert set(found) == {"/ai/shadow/arms", "/ai/contradictions", "/ai/agent-runs", "/ai/matches/{fixture_id}/shadow"}
    assert all(getattr(r, "methods", None) == {"GET"} for r in found.values())
    old = {r.path for r in routes.admin_router.routes if getattr(r, "path", "") in ("/ai/shadow", "/ai/reviews", "/ai/comparison")}  # type: ignore[attr-defined]
    assert old == {"/ai/shadow", "/ai/reviews", "/ai/comparison"}, "the endpoints production reads are still where they were"


def test_no_field_of_a_contract_can_hold_a_model_s_free_text() -> None:
    """The shapes carry codes, counts, ids and the server's numbers. A field named for prose would be a way in for a model's sentence."""
    prose = {"text", "summary", "claim", "narrative", "comment", "note", "message", "quote", "url", "link", "href", "query", "sql"}
    names: set[str] = set()
    for name in dir(contracts):
        model = getattr(contracts, name)
        if isinstance(model, type) and hasattr(model, "model_fields") and model.__module__ == contracts.__name__:
            names |= set(model.model_fields)
    assert names & prose == set()

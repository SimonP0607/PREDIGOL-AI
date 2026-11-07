"""ctx-adj-v1 (plan IA, P0): the typed Council -> decision contract, in shadow. The rows are shaped as ``fbi.ai.orchestrator.review_rows`` writes
them (its own ``engine_version``, ``CONFIDENCE`` and ``VERSION``), and the cd-v1 answers go through the contract's own parser."""

from __future__ import annotations

import itertools
import typing
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import arms, orchestrator
from fbi.ai.agents.common import assessment_label
from fbi.ai.contracts.base import RISK_CODES, SIGNAL_CODES, Verdict
from fbi.ai.contracts.council import CouncilOut, check
from fbi.intel import context_adjustment as ctx
from fbi.intel import decision

AT = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
STATES = (*decision.RANK, "PICK_PREMIUM", "CANDIDATO_PARLAY", "PICK_DEL_DIA")


def base_output(engine: str = "ma-v1") -> dict[str, Any]:
    return {"version": orchestrator.VERSION, "engine": engine, "arm": engine, "contract": "cd-v1", "candidate": "c1", "round": 1,
            "prompts": {"council": "council-v1", "match_context": "match-context-v2", "match_assess": "match-assess-v2"},
            "contradictions": ["C03"], "fair_odds": 1.92, "minimum_playable_odds": 2.01, "research_ask_ignored": 0,
            "assessment": {"match_context": "NEUTRAL", "match_evaluation": "CONCERN"}}


def ok_row(verdict: str = "APPROVE", *, level: str = "HIGH", engine: str = "ma-v1", stats: bool = False, **extra: Any) -> dict[str, Any]:
    out = base_output(engine) | {
        "verdict": verdict, "confidence_level": level, "confidence": str(orchestrator.confidence_value(level)), "drivers": ["FORM", "ABSENCES"],
        "risks": ["LINEUP_UNCONFIRMED"], "refs": ["A:match_evaluation", "E:12", "P:shared.absences"], "model": "claude-sonnet-5-5",
        "paths": ["shared.absences"]} | extra
    return {"id": 501, "engine": engine, "engine_version": orchestrator.engine_version(engine, with_stats=stats), "fixture_id": 77,
            "market_key": "1X2", "selection": "Home", "line": Decimal("0.00"), "decision": verdict,
            "confidence": orchestrator.confidence_value(level), "reviewed_at": AT, "output": out, "evidence_ids": [12], "mode": "shadow",
            "status": "ok", "model": "claude-sonnet-5-5"}


def fallback_row(status: str = "fallback", engine: str = "ma-v1-h") -> dict[str, Any]:
    out = base_output(engine) | {"verdict": "ABSTAIN", "confidence": "0", "reason": "paused:budget", "status": status}
    return {"id": 502, "engine": engine, "engine_version": orchestrator.engine_version(engine, with_stats=False), "fixture_id": 77,
            "market_key": "1X2", "selection": "Home", "line": Decimal("0.00"), "decision": "ABSTAIN", "confidence": Decimal(0),
            "reviewed_at": AT, "output": out, "evidence_ids": [], "mode": "shadow", "status": status, "model": None}


def adj(verdict: ctx.AdjVerdict) -> ctx.ContextAdjustment:
    return ctx.ContextAdjustment(verdict, "bloqueante" if verdict == "BLOQUEA" else "baja", ctx.Source("ma-v1"), AT)


# -- the mapping --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("verdict", "expected", "severity"), [
    ("APPROVE", "CONFIRMA", "baja"), ("DOWNGRADE", "RESERVA", "alta"), ("REJECT", "BLOQUEA", "bloqueante"), ("ABSTAIN", "FALTA_INFO", "alta")])
def test_an_answered_verdict_maps_to_its_word(verdict: str, expected: str, severity: str) -> None:
    a = ctx.from_review(ok_row(verdict))
    assert (a.verdict, a.severity, a.council_verdict, a.confidence) == (expected, severity, verdict, "HIGH")
    assert a.factor_codes == ("FORM", "ABSENCES", "LINEUP_UNCONFIRMED")
    assert a.contradictions == ("C03",) and a.evidence_ids == (12,)
    assert a.source == ctx.Source("ma-v1", review_id=501, engine_version=orchestrator.engine_version("ma-v1", with_stats=False),
                                  council_version="council-v1", model="claude-sonnet-5-5")
    assert a.known_at == AT


@pytest.mark.parametrize(("level", "severity"), [("LOW", "baja"), ("MEDIUM", "media"), ("HIGH", "alta")])
def test_the_severity_of_a_reservation_is_the_councils_confidence_in_words(level: str, severity: str) -> None:
    assert ctx.from_review(ok_row("DOWNGRADE", level=level)).severity == severity
    assert ctx.from_review(ok_row("REJECT", level=level)).severity == "bloqueante"
    assert ctx.from_review(ok_row("APPROVE", level=level)).severity == "baja"


@pytest.mark.parametrize("status", sorted(ctx.UNANSWERED))
def test_a_row_the_council_did_not_answer_is_sin_council(status: str) -> None:
    a = ctx.from_review(fallback_row(status))
    assert (a.verdict, a.severity, a.council_verdict, a.factor_codes, a.dissents) == ("SIN_COUNCIL", "baja", None, (), ())
    assert a.source.engine == "ma-v1-h" and a.source.review_id == 502


def test_the_mapping_table_covers_every_cd_v1_verdict_once_answered() -> None:
    assert {v for v, kind in ctx.VERDICT_MAP if kind == "answered"} == set(typing.get_args(Verdict))
    assert set(ctx.VERDICT_MAP.values()) == set(ctx.VERDICTS)
    for verdict in ("APPROVE", "DOWNGRADE", "REJECT"):
        with pytest.raises(ctx.UnknownCouncilOutputError):
            ctx.map_verdict(verdict, answered=False)


def test_the_constants_are_the_codes_and_engines_of_the_shadow() -> None:
    assert ctx.ENGINES == (arms.MULTIAGENT, arms.MULTIAGENT_HAIKU)
    assert {assessment_label(a, m) for a in ("match", "stats") for m in ("CONTEXT", "EVALUATION")} == ctx.ASSESSMENT_LABELS
    assert ctx.UNANSWERED | {ctx.ANSWERED} == {orchestrator.STATUS_OK, orchestrator.STATUS_FALLBACK, orchestrator.STATUS_INVALID,
                                              orchestrator.STATUS_FAILED, orchestrator.STATUS_OVER_BUDGET}
    for engine in ctx.ENGINES:
        for stats in (False, True):
            assert ctx.council_version_of(engine, orchestrator.engine_version(engine, with_stats=stats)) == "council-v1"


def test_the_server_demotions_are_the_ones_the_contract_makes() -> None:
    """``check`` turns an approval without data and a rejection without a reference into ABSTAIN; their codes are ``CHANGE_CODES``."""
    out = CouncilOut.model_validate({"contract": "cd-v1", "research": [], "verdicts": [
        {"candidate": "c1", "verdict": "APPROVE", "confidence": "HIGH", "drivers": [], "risks": [], "refs": []},
        {"candidate": "c2", "verdict": "REJECT", "confidence": "HIGH", "drivers": [], "risks": [], "refs": []}]})
    got = check(out, asked=["c1", "c2"], evidence_ids=[], paths=[], assessments=[])
    assert {c.why for c in got.changes} == ctx.CHANGE_CODES
    a = ctx.from_review(ok_row("ABSTAIN", changes=["approve_without_data_in_its_favour"]))
    assert a.verdict == "FALTA_INFO" and a.server_changes == ("approve_without_data_in_its_favour",)


# -- dissents and escalation ------------------------------------------------------------------------------------------------------

def test_a_dissent_is_an_assessment_that_pulls_against_the_verdict() -> None:
    assert ctx.from_review(ok_row("APPROVE")).dissents == (ctx.Dissent("match_evaluation", "CONCERN"),)
    assert ctx.from_review(ok_row("REJECT")).dissents == ()
    support = ok_row("DOWNGRADE")
    support["output"]["assessment"] = {"match_context": "SUPPORT", "match_evaluation": "SUPPORT", "stats_evaluation": "NEUTRAL"}
    assert [d.agent for d in ctx.from_review(support).dissents] == ["match_context", "match_evaluation"]
    assert ctx.from_review(ok_row("ABSTAIN")).dissents == ()


def test_the_escalation_rule_is_kept_with_the_source() -> None:
    a = ctx.from_review(ok_row("REJECT", escalation={"rule": "E2", "model": "claude-opus-5-5", "replaced": True}))
    assert a.source.escalation_rule == "E2"
    skipped = ctx.from_review(ok_row("APPROVE", escalation={"rule": "E7", "skipped": "allowance_spent"}))
    assert skipped.source.escalation_rule == "E7"


# -- refusals ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("change", "where"), [
    ({"engine": "cs-v1"}, "engine"), ({"engine": "combined"}, "engine"), ({"mode": "enforce"}, "mode"), ({"status": "pending"}, "status"),
    ({"decision": "MAYBE"}, "verdict"), ({"engine_version": "ma-v1+match-v2+council-v9+contra-v1+router-v1"}, "council version"),
    ({"engine_version": "ma-v1-h+match-v2+council-v1"}, "engine_version"), ({"reviewed_at": datetime(2026, 11, 5, 15)}, "reviewed_at"),  # noqa: DTZ001
    ({"evidence_ids": ["12"]}, "evidence_ids")])
def test_a_row_this_version_does_not_know_is_refused(change: dict[str, Any], where: str) -> None:
    with pytest.raises(ctx.UnknownCouncilOutputError, match=where):
        ctx.from_review(ok_row("APPROVE") | change)


@pytest.mark.parametrize(("change", "where"), [
    ({"drivers": ["VIBES"]}, "drivers"), ({"risks": ["BAD_LUCK"]}, "risks"), ({"contradictions": ["C99"]}, "contradictions"),
    ({"confidence_level": "SURE"}, "confidence_level"), ({"contract": "cd-v2"}, "contract"), ({"verdict": "REJECT"}, "output.verdict"),
    ({"refs": ["https://x"]}, "refs"), ({"changes": ["it_felt_wrong"]}, "changes"), ({"assessment": {"oracle_evaluation": "SUPPORT"}}, "label"),
    ({"assessment": {"match_context": "LOVE"}}, "stance"), ({"escalation": {"rule": "E9"}}, "escalation"), ({"engine": "ma-v1-h"}, "output.engine")])
def test_an_unknown_cd_v1_code_or_field_value_is_refused(change: dict[str, Any], where: str) -> None:
    r = ok_row("APPROVE")
    r["output"] |= change
    with pytest.raises(ctx.UnknownCouncilOutputError, match=where):
        ctx.from_review(r)


def test_an_unanswered_row_that_carries_a_verdict_or_codes_is_refused() -> None:
    with pytest.raises(ctx.UnknownCouncilOutputError):
        ctx.from_review(fallback_row() | {"decision": "REJECT"})
    bad = fallback_row()
    bad["output"]["drivers"] = ["FORM"]
    with pytest.raises(ctx.UnknownCouncilOutputError):
        ctx.from_review(bad)


# -- a cd-v1 answer ---------------------------------------------------------------------------------------------------------------

ANSWER: dict[str, Any] = {"contract": "cd-v1", "research": [], "verdicts": [
    {"candidate": "c1", "verdict": "DOWNGRADE", "confidence": "MEDIUM", "drivers": ["ABSENCES"], "risks": ["KEY_ABSENCE_OPEN"],
     "refs": ["E:5", "E:9", "P:shared.absences"]},
    {"candidate": "c2", "verdict": "APPROVE", "confidence": "LOW", "drivers": ["FORM"], "risks": [], "refs": ["A:match_evaluation"]}]}


def test_a_cd_v1_answer_is_read_through_the_contracts_parser() -> None:
    a = ctx.from_council_output(ANSWER, candidate="c1", engine="ma-v1", known_at=AT, run_id=88)
    assert (a.verdict, a.severity, a.factor_codes, a.evidence_ids, a.dissents) == (
        "RESERVA", "media", ("ABSENCES", "KEY_ABSENCE_OPEN"), (5, 9), ())
    assert a.source == ctx.Source("ma-v1", run_id=88, council_version="council-v1")
    assert ctx.from_council_output(ANSWER, candidate="c2", engine="ma-v1-h", known_at=AT).verdict == "CONFIRMA"


@pytest.mark.parametrize("payload", [
    ANSWER | {"contract": "cd-v2"}, {"contract": "cd-v1", "research": [], "verdicts": [dict(ANSWER["verdicts"][0]) | {"verdict": "VETO"}]},
    {"contract": "cd-v1", "research": [], "verdicts": [dict(ANSWER["verdicts"][0]) | {"drivers": ["VIBES"]}]},
    {"contract": "cd-v1", "research": [], "verdicts": [dict(ANSWER["verdicts"][0]) | {"p_model": 0.6}]}, "not json"])
def test_a_cd_v1_answer_the_contract_refuses_is_refused(payload: Any) -> None:
    with pytest.raises(ctx.UnknownCouncilOutputError):
        ctx.from_council_output(payload, candidate="c1", engine="ma-v1", known_at=AT)


def test_a_missing_candidate_an_unknown_engine_or_version_is_refused() -> None:
    for kw in ({"candidate": "c7"}, {"engine": "cs-v1"}, {"council_version": "council-v2"}):
        with pytest.raises(ctx.UnknownCouncilOutputError):
            ctx.from_council_output(ANSWER, **({"candidate": "c1", "engine": "ma-v1", "known_at": AT} | kw))  # type: ignore[arg-type]


# -- no number ----------------------------------------------------------------------------------------------------------------------

def test_an_adjustment_carries_no_number_a_decision_could_compute_with() -> None:
    """The only integers are ids (of the review, of the run, of the evidence); no float and no Decimal anywhere."""
    def leaves(t: Any) -> set[Any]:
        args = typing.get_args(t)
        return set().union(*(leaves(a) for a in args)) if args and typing.get_origin(t) is not typing.Literal else {t}

    ints: set[str] = set()
    for cls in (ctx.ContextAdjustment, ctx.Source, ctx.Dissent):
        assert is_dataclass(cls)
        hints = typing.get_type_hints(cls)
        for f in fields(cls):
            kinds = leaves(hints[f.name])
            assert not kinds & {float, Decimal, complex}, f"{cls.__name__}.{f.name}"
            if int in kinds:
                ints.add(f"{cls.__name__}.{f.name}")
    assert ints == {"ContextAdjustment.evidence_ids", "Source.review_id", "Source.run_id"}
    for name in ("p_model", "p_market", "odds", "ev", "edge", "stake", "fair_odds", "minimum_playable_odds"):
        assert all(f.name != name for f in fields(ctx.ContextAdjustment))
    assert "confidence" not in ctx.from_review(ok_row("REJECT")).as_json()["source"]


# -- the effect -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("state", "verdict"), list(itertools.product(STATES, ctx.VERDICTS)))
def test_the_effect_is_monotone_it_never_raises_a_state(state: str, verdict: ctx.AdjVerdict) -> None:
    proposed = ctx.proposed_effect(adj(verdict), state)
    assert decision.RANK[ctx.base_state(proposed)] <= decision.RANK[ctx.base_state(state)]
    target = ctx.EFFECT[verdict]
    if target is None:
        assert proposed == state, "a confirmation or no Council leaves the state - label included - as it was"
    else:
        assert decision.RANK[ctx.base_state(proposed)] <= decision.RANK[target]


def test_the_effect_table() -> None:
    e = ctx.proposed_effect
    assert [e(adj("BLOQUEA"), s) for s in STATES] == ["RECHAZADO"] * len(STATES)
    assert e(adj("RESERVA"), "PICK_PREMIUM") == "CAUTELA" and e(adj("RESERVA"), "APROBADO") == "CAUTELA"
    assert e(adj("RESERVA"), "INVESTIGACION") == "INVESTIGACION" and e(adj("RESERVA"), "RECHAZADO") == "RECHAZADO"
    assert e(adj("FALTA_INFO"), "CAUTELA") == "INVESTIGACION" and e(adj("FALTA_INFO"), "CANDIDATO_PARLAY") == "INVESTIGACION"
    assert e(adj("FALTA_INFO"), "RECHAZADO") == "RECHAZADO"
    assert e(adj("CONFIRMA"), "INVESTIGACION") == "INVESTIGACION", "a confirmation never promotes"
    assert e(adj("SIN_COUNCIL"), "PICK_DEL_DIA") == "PICK_DEL_DIA"
    with pytest.raises(ValueError):
        e(adj("CONFIRMA"), "MAYBE")


def test_the_codes_it_accepts_are_cd_v1s() -> None:
    a = ctx.from_review(ok_row("APPROVE", drivers=list(SIGNAL_CODES), risks=list(RISK_CODES)))
    assert a.factor_codes == tuple(SIGNAL_CODES) + tuple(RISK_CODES)


def test_the_decision_layer_does_not_know_this_module() -> None:
    from pathlib import Path

    source = Path(decision.__file__).read_text(encoding="utf-8")
    assert "context_adjustment" not in source and "state_v2" not in source

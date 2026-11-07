"""``council-protocol-v1``'s baseline without a database: what the deterministic layer would propose without the judge, that it is a
``ctx-adj-v1`` adjustment with no number in it, that it can never raise a state, and how the stored pass is read."""

from __future__ import annotations

import itertools
import typing
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fbi.council import contradictions as c
from fbi.council import protocol as p
from fbi.council import weights as w
from fbi.intel import context_adjustment as ctx
from fbi.intel import decision

AT = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
D = Decimal
SEL = c.Selection("c1", "1X2", "1X2", "Home", D(0), D("0.55"), D("0.50"), D("0.05"), D("0.08"), ("C01",))


def pos(agent: str, stance: str, weight: str = "1", drivers: tuple[str, ...] = ("ABSENCES",), *, refs: tuple[str, ...] = ("E:5", "P:market"),
        risks: tuple[str, ...] = ("KEY_ABSENCE_OPEN",)) -> c.Position:
    return c.Position(agent, f"{agent}-v2", f"{agent}_evaluation", "c1", stance, drivers, risks, refs, 1 if agent == "match" else 2, D(weight))


def base(*positions: c.Position, research: bool = False) -> p.Baseline:
    return p.baseline(SEL, positions, research_requested=research, at=AT)


def test_no_voice_that_weighs_is_no_council_at_all() -> None:
    b = base(pos("match", "REJECT_SIGNAL", "0"), pos("stats", "CONCERN", "0"))
    assert b.adjustment.verdict == "SIN_COUNCIL" and b.score is None and b.reasons == ("no_weighted_voice",)
    assert b.adjustment.contradictions == ("C01",) and b.adjustment.source.engine == p.ENGINE


@pytest.mark.parametrize(("stances", "word", "verdict"), [
    (("SUPPORT", "SUPPORT"), "APPROVE", "CONFIRMA"),
    (("SUPPORT", "NEUTRAL"), "APPROVE", "CONFIRMA"),
    (("SUPPORT", "CONCERN"), "ABSTAIN", "FALTA_INFO"),
    (("CONCERN", "NEUTRAL"), "DOWNGRADE", "RESERVA"),
    (("CONCERN", "CONCERN"), "DOWNGRADE", "RESERVA"),
    (("REJECT_SIGNAL", "CONCERN"), "REJECT", "BLOQUEA"),
    (("REJECT_SIGNAL", "REJECT_SIGNAL"), "REJECT", "BLOQUEA"),
    (("NEUTRAL", "NEUTRAL"), "ABSTAIN", "FALTA_INFO"),
])
def test_the_score_is_read_into_a_cd_v1_word_and_mapped_by_ctx_adj_v1(stances: tuple[str, str], word: str, verdict: str) -> None:
    b = base(pos("match", stances[0]), pos("stats", stances[1]))
    assert (b.word, b.adjustment.verdict) == (word, verdict)
    assert b.adjustment.council_verdict == word and b.adjustment.verdict == ctx.map_verdict(word, answered=True)
    assert b.adjustment.confidence == "HIGH" and b.weight_heard == D(2)


def test_the_confidence_is_the_weight_heard_and_the_severity_follows_it() -> None:
    low = base(pos("match", "CONCERN", "0.5"), pos("stats", "CONCERN", "0"))
    assert low.adjustment.confidence == "LOW" and low.adjustment.severity == "baja"
    mid = base(pos("match", "CONCERN", "1.2"))
    assert mid.adjustment.confidence == "MEDIUM" and mid.adjustment.severity == "media"
    blocked = base(pos("match", "REJECT_SIGNAL", "0.6"))
    assert blocked.adjustment.verdict == "BLOQUEA" and blocked.adjustment.severity == "bloqueante"


def test_a_stance_the_model_already_priced_weighs_nothing() -> None:
    known = base(pos("match", "SUPPORT"), pos("stats", "REJECT_SIGNAL", drivers=("FORM", "VENUE")))
    assert known.score == D("0.5000") and known.word == "APPROVE", "counted twice, form and venue would have made it (1 - 2) / 2: a DOWNGRADE"
    assert known.weight_heard == D(2), "the known stance is still a voice heard: it dilutes, it does not pull"


def test_novelty_scales_the_pull() -> None:
    half = base(pos("match", "REJECT_SIGNAL", drivers=("FORM", "ABSENCES")))
    assert half.score == D("-1.0000") and half.word == "DOWNGRADE", "half of a rejection signal: a reservation, not a block"
    whole = base(pos("match", "REJECT_SIGNAL", drivers=("ABSENCES",)))
    assert whole.score == D("-2.0000") and whole.word == "REJECT"


def test_a_requested_round_makes_the_information_missing_and_the_more_conservative_wins() -> None:
    approve = base(pos("match", "SUPPORT"), pos("stats", "SUPPORT"), research=True)
    assert approve.adjustment.verdict == "FALTA_INFO" and "research_round_requested" in approve.reasons
    downgrade = base(pos("match", "CONCERN"), pos("stats", "CONCERN"), research=True)
    assert downgrade.adjustment.verdict == "FALTA_INFO", "INVESTIGACION is lower than CAUTELA"
    reject = base(pos("match", "REJECT_SIGNAL"), pos("stats", "REJECT_SIGNAL"), research=True)
    assert reject.adjustment.verdict == "BLOQUEA" and "research_round_requested" not in reject.reasons


def test_the_codes_evidence_and_dissents_are_the_winning_sides() -> None:
    b = base(pos("match", "SUPPORT", drivers=("LINEUP",), refs=("E:9",), risks=()), pos("stats", "SUPPORT", drivers=("RATE",), refs=("E:3",), risks=()),
             pos("council", "CONCERN", "0.5", drivers=("NEWS",), refs=("E:4",)))
    assert b.adjustment.verdict == "CONFIRMA"
    assert b.adjustment.factor_codes == ("LINEUP", "RATE"), "the drivers of the supporters, not of the objector"
    assert b.adjustment.evidence_ids == (3, 9)
    assert [(d.agent, d.stance) for d in b.adjustment.dissents] == [("council_evaluation", "CONCERN")]


def test_the_adjustment_carries_no_number_a_decision_could_compute_with() -> None:
    allowed = {int, str, bool, type(None), datetime}

    def check(obj: Any, where: str) -> None:
        if is_dataclass(obj) and not isinstance(obj, type):
            hints = typing.get_type_hints(type(obj))
            for f in fields(obj):
                check(getattr(obj, f.name), f"{where}.{f.name}")
                assert "Decimal" not in str(hints[f.name]) and "float" not in str(hints[f.name]), f"{where}.{f.name}"
        elif isinstance(obj, tuple):
            for i, x in enumerate(obj):
                check(x, f"{where}[{i}]")
        else:
            assert type(obj) in allowed, f"{where} is a {type(obj).__name__}"
            if isinstance(obj, int) and not isinstance(obj, bool):
                assert where.startswith(("adj.evidence_ids", "adj.source.review_id", "adj.source.run_id")), where

    b = base(pos("match", "SUPPORT"), pos("stats", "CONCERN", "0.4"))
    check(b.adjustment, "adj")


STATES = (*decision.RANK, *sorted(decision.APPROVED))
STANCES = ("SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL")
WEIGHTS = ("0", "0.5", "1.5")
DRIVERS = (("ABSENCES",), ("FORM",), ())


def test_nothing_the_baseline_proposes_can_raise_a_state() -> None:
    seen: set[str] = set()
    for (s1, w1, d1), (s2, w2, d2), research, state in itertools.product(
            itertools.product(STANCES, WEIGHTS, DRIVERS), itertools.product(STANCES, WEIGHTS, DRIVERS), (False, True), STATES):
        b = base(pos("match", s1, w1, d1), pos("stats", s2, w2, d2), research=research)
        seen.add(b.adjustment.verdict)
        after = ctx.proposed_effect(b.adjustment, state)
        assert decision.RANK[ctx.base_state(after)] <= decision.RANK[ctx.base_state(state)], (s1, w1, s2, w2, research, state)
        if b.adjustment.verdict in ("CONFIRMA", "SIN_COUNCIL"):
            assert after == state
    assert seen == set(ctx.VERDICTS), "every word of ctx-adj-v1 is reachable, and none other"


def test_the_agreement_with_a_judge() -> None:
    b = base(pos("match", "CONCERN"), pos("stats", "CONCERN")).adjustment
    reserve = ctx.ContextAdjustment("RESERVA", "media", ctx.Source("ma-v1"), AT, council_verdict="DOWNGRADE", confidence="MEDIUM")
    confirm = ctx.ContextAdjustment("CONFIRMA", "baja", ctx.Source("ma-v1"), AT, council_verdict="APPROVE", confidence="HIGH")
    assert p.agreement("ma-v1", b, reserve) == p.Agreement("ma-v1", "compared", True, True)
    assert p.agreement("ma-v1", b, confirm) == p.Agreement("ma-v1", "compared", False, False)
    assert p.agreement("ma-v1", b, None).status == "no_judge"
    assert p.agreement("ma-v1", b, ctx.ContextAdjustment.absent("ma-v1", at=AT)).status == "judge_sin_council"
    silent = base(pos("match", "CONCERN", "0")).adjustment
    assert p.agreement("ma-v1", silent, reserve).status == "baseline_sin_council"


def test_the_candidates_and_contradictions_of_a_pass_are_read_strictly() -> None:
    candidates = [{"candidate": "c2", "family": "OU", "market": "OU", "selection": "Over", "line": "2.5", "p_model": "0.6", "p_market": "0.52",
                   "edge": "0.08", "ev": "0.12", "odds": "1.95"},
                  {"candidate": "c1", "family": "1X2", "market": "1X2", "selection": "Home", "line": "0", "p_model": "0.5", "p_market": None,
                   "edge": None, "ev": None},
                  {"candidate": None, "left_out": "beyond_the_limit", "market": "1X2", "selection": "Away", "line": "0"},
                  {"candidate": "c3", "market": "HT_FT", "selection": "x", "line": "0"},
                  {"candidate": "c4", "family": "1X2", "market": "1X2", "selection": "Draw", "line": "nan?"}]
    contradictions = [{"code": "C06", "candidates": ["c2"]}, {"code": "C07", "candidates": ["c1", "c2"]}, "garbage"]
    got = p.selections_of(candidates, contradictions)
    assert [s.key for s in got] == ["c1", "c2"]
    assert got[1].contra == ("C06", "C07") and got[1].line == D("2.5") and got[1].ev == D("0.12")
    assert got[0].p_market is None and got[0].contra == ("C07",)
    assert p.selections_of(None, None) == []


def assessment(agent: str = "match", mode: str = "EVALUATION", **over: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"contract": "aa-v1", "agent": agent, "mode": mode, "data_quality": "GOOD", "signals": [], "research": [],
                           "candidates": [{"candidate": "c1", "stance": "CONCERN", "drivers": ["ABSENCES"], "risks": [], "refs": ["E:5"]},
                                          {"candidate": "c9", "stance": "SUPPORT", "drivers": ["FORM"], "risks": [], "refs": ["P:market"]}]}
    return out | over


def test_a_stored_evaluation_becomes_weighed_positions_of_the_candidates_of_the_pass() -> None:
    book = w.Book(AT, {}, {"1X2": None})
    positions, used, problem = p.positions_of(41, "match", "match-v2", assessment(), [SEL], book)
    assert problem is None and [(x.candidate, x.stance, x.weight, x.label, x.run_id) for x in positions] == [
        ("c1", "CONCERN", D(0), "match_evaluation", 41)], "c9 is not a candidate of the pass; nobody is promoted"
    assert [(x.agent, x.family, x.promoted) for x in used] == [("match", "1X2", False)]
    assert p.positions_of(41, "match", "match-v2", {"contract": "aa-v1"}, [SEL], book)[2] == "run_unreadable:41"
    assert p.positions_of(41, "stats", "stats-v2", assessment(), [SEL], book)[2] == "run_not_an_evaluation_of_its_agent:41"
    assert p.positions_of(41, "match", "match-v2", assessment(mode="CONTEXT", candidates=[]), [SEL], book)[2] == \
        "run_not_an_evaluation_of_its_agent:41"


def test_a_deliberation_needs_a_moment_with_its_zone() -> None:
    with pytest.raises(ValueError):
        p.deliberate(None, 1, at=datetime(2026, 11, 6, 18, 0))  # type: ignore[arg-type]  # noqa: DTZ001


def test_the_constants_are_reported() -> None:
    got = p.constants()
    assert got["weights"]["min_weight"] == "0.5" and got["weights"]["max_weight"] == "1.5"
    assert got["research"]["min_ev"] == str(Decimal(str(decision.EV_MIN)))
    assert set(got["contradictions"]["model_knows"]) == set(c.MODEL_KNOWS)

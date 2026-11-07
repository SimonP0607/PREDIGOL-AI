"""The Narrator of a pick (``narrator-v1``, IA-017): its facts come from the trace and nothing else, the verifier drops what they
do not support, it is off by default, and a fake provider goes through it end to end. Pure: no database, no network, no key."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai.config import AiSettings
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import CallOutcome
from fbi.narrator import VERSION, facts, job, prompt, verify
from fbi.narrator.facts import Identity, PickFacts
from fbi.observability import trace as tr

KO = datetime(2026, 11, 8, 19, tzinfo=UTC)
T24, T6 = KO - timedelta(hours=24), KO - timedelta(hours=6)
PICK = 11
IDENTITY = Identity("Atlético Nacional", "Millonarios", "Liga BetPlay")
CLAIM = "Nacional recupera a su goleador Dorlan Pabón tras dos semanas fuera."
RUMOUR = "Se habla de que el portero de Millonarios no viajó."


def filters(*, risk_ok: bool = False) -> list[dict[str, Any]]:
    return [{"n": 1, "key": "data", "ok": True, "why": "datos MODEL_READY"},
            {"n": 2, "key": "model", "ok": True, "why": "dixon_coles: p 0.341"},
            {"n": 3, "key": "market", "ok": True, "why": "6 casas, cuota 3.40, margen 4.1 %"},
            {"n": 4, "key": "calibration", "ok": True, "why": "calibrador isotonic #12 (champion)"},
            {"n": 5, "key": "ev", "ok": True, "why": "EV calibrado +15.9%, edge +0.051"},
            {"n": 6, "key": "context", "ok": True, "why": "contexto FULL; revisión APPROVE"},
            {"n": 7, "key": "risk", "ok": risk_ok, "why": "sin riesgo cuantitativo" if risk_ok else "cuota 3.40 > 3.00",
             "effect": "CAUTELA"},
            {"n": 9, "key": "price", "ok": None, "why": "sin precio"},
            {"n": 10, "key": "final", "ok": False, "why": "edge no validado", "effect": "INVESTIGACION"}]


def decision(row: int, at: datetime, *, odds: float = 3.4, pick: int | None = PICK, evidence: list[int] | None = None,
             flt: list[dict[str, Any]] | None = None) -> tr.Span:
    return tr.Span("decision", tr.PRESENT, "intel.decisions", (str(row),), at,
                   {"decision": "decision-v1", "code": "abc", "calibrator": "cal-v1"},
                   {"checkpoint": "T-6h", "state": "CAUTELA", "reasons": ["risk", "edge_not_validated", "a_code_nobody_knows"],
                    "pick_id": pick, "odds": odds, "n_bookmakers": 6, "p_model": 0.33, "p_cal": 0.341, "p_market": 0.29,
                    "ev_cal": 0.159, "edge_cal": 0.051, "score": 64.0, "stake_units": 0.5, "context_status": "FULL",
                    "review_id": 5, "evidence_ids": [103, 101, 100] if evidence is None else evidence,
                    "filters": tr.compact_filters(filters() if flt is None else flt)})


def spans(*, extra: list[tr.Span] | None = None, order: int = 0) -> tuple[tr.Span, ...]:
    out = [
        tr.Span("fixture", tr.PRESENT, "core.fixtures", ("77",), KO, payload={"status_group": "scheduled"}),
        decision(1, T24, odds=3.1),
        decision(2, T6),
        tr.Span("pick", tr.PRESENT, "picks.picks", (str(PICK),), T24, {"rule": "shadow-rule-v2"},
                {"prediction_id": 9, "market_odds": 3.4, "stake_units": 1.0, "status": "published"}),
        tr.Span("forecast", tr.PRESENT, "models.predictions", ("9",), T24, payload={"p_lo": 0.29, "p_hi": 0.39, "pick_id": PICK}),
        tr.Span("review", tr.PRESENT, "ai.pick_reviews", ("5",), T24, {"engine": "combined-v1"},
                {"engine": "combined", "decision": "APPROVE", "confidence": 0.7, "status": "ok", "cited_by": ["decision 2"]}),
        tr.Span("review", tr.PRESENT, "ai.pick_reviews", ("6",), T24, {"engine": "ma-v1"},
                {"engine": "ma-v1", "decision": "REJECT", "confidence": 0.9, "status": "ok", "shadow": True}),
        tr.Span("evidence", tr.PRESENT, "ai.evidence", ("100",), T24,
                payload={"kind": "lineup", "status": "CONFIRMED", "claim": CLAIM, "source_domain": "elcolombiano.com"}),
        tr.Span("evidence", tr.PRESENT, "ai.evidence", ("101",), T24,
                payload={"kind": "other", "status": "RUMOR", "claim": RUMOUR, "source_domain": "blog.example"}),
        tr.Span("evidence", tr.PRESENT, "ai.evidence", ("102",), T24,
                payload={"kind": "injury", "status": "CONFIRMED", "claim": "Only an agent run cites this.", "cited_by": ["agent run 3"]}),
        tr.Span("evidence", tr.PRESENT, "ai.evidence", ("103",), T24,
                payload={"kind": "injury", "status": "OUTDATED", "claim": "An old injury report."}),
        tr.Span("settlement", tr.NOT_APPLICABLE, "picks.pick_results", note="the match is not finished"),
        *(extra or []),
    ]
    if order:
        random.Random(order).shuffle(out)
    return tr.order(out)


def trace_json(**kw: Any) -> dict[str, Any]:
    t = tr.Trace(tr.VERSION, f"pick:{PICK}", "selection", tr.selection_trace_id(77, "1X2", "Home", 0), tr.match_trace_id(77), 77,
                 "1X2", "Home", "0.00", "decision-v1", spans(**kw))
    return t.as_json()


def pick_facts(**kw: Any) -> PickFacts:
    pf = facts.from_trace(trace_json(**kw), pick_id=PICK, identity=IDENTITY)
    assert isinstance(pf, PickFacts)
    return pf


# ── the facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_facts_are_the_closed_list_of_what_the_pick_s_decision_used() -> None:
    pf = pick_facts()
    assert [f.id for f in pf.facts] == [
        "F:match", "F:pick", "F:probability", "F:interval", "F:market_probability", "F:odds", "F:value", "F:verdict", "F:score",
        "F:stake", "F:filter.data", "F:filter.model", "F:filter.market", "F:filter.calibration", "F:filter.ev", "F:filter.context",
        "F:filter.risk", "F:risk.long_odds", "F:filter.final", "F:risk.edge_not_validated", "F:review", "F:evidence.100",
        "F:evidence.101"]
    by = pf.by_id()
    assert pf.decision_id == 2 and pf.pick_status == "published", "the newest decision that names the pick"
    assert by["F:odds"].params == {"odds": 3.4, "bookmakers": 6}
    assert by["F:probability"].params == {"probability": 0.341, "calibrated": True}
    assert by["F:risk.long_odds"].params == {"odds": 3.4, "limit": 3.0}
    assert by["F:stake"].params == {"units": 0.5}, "the decision's stake, not the pick's row"
    assert by["F:review"].params == {"verdict": "APPROVE", "confidence": 0.7} and by["F:review"].role == "reason"
    assert by["F:evidence.100"].role == "reason" and by["F:evidence.101"].role == "risk"
    text = json.dumps(pf.as_json(), ensure_ascii=False)
    assert "REJECT" not in text, "a shadow review the decision did not cite is never a fact"
    assert "Only an agent run" not in text and "An old injury" not in text, "uncited and outdated evidence are not facts"
    assert "a_code_nobody_knows" not in text and "isotonic" not in text, "an unknown code is never guessed; a filter's why is not told"
    assert all(f.role in facts.ROLES for f in pf.facts)


def test_the_same_trace_gives_the_same_facts_and_the_same_hash_whatever_the_order() -> None:
    a, b = pick_facts(), pick_facts(order=7)
    assert a == b and a.hash == b.hash
    assert facts.from_trace(trace_json(), pick_id=PICK, identity=IDENTITY) == a
    shuffled = trace_json()
    for s in shuffled["spans"]:
        if s["kind"] == "decision":
            s["payload"]["evidence_ids"] = list(reversed(s["payload"]["evidence_ids"]))
            s["payload"]["filters"] = list(reversed(s["payload"]["filters"]))
    again = facts.from_trace(shuffled, pick_id=PICK, identity=IDENTITY)
    assert again == a and isinstance(again, PickFacts) and again.hash == a.hash


def test_another_decision_is_another_input_and_the_narrative_is_written_again() -> None:
    first = pick_facts()
    newer = pick_facts(extra=[decision(3, T6 + timedelta(hours=4), odds=3.2, flt=filters(risk_ok=True))])
    assert newer.decision_id == 3 and newer.hash != first.hash
    assert newer.by_id()["F:odds"].params["odds"] == 3.2 and "F:risk.long_odds" not in newer.by_id()


def test_without_its_pick_or_a_decision_there_are_no_facts() -> None:
    assert facts.from_trace({"version": "trace-v0"}, pick_id=PICK) == "not_trace_v1"
    assert facts.from_trace(trace_json(), pick_id=999) == "no_pick"
    bare = trace_json()
    bare["spans"] = [s for s in bare["spans"] if s["kind"] != "decision"]
    assert facts.from_trace(bare, pick_id=PICK) == "no_decision"
    other = trace_json(extra=[])
    for s in other["spans"]:
        if s["kind"] == "decision":
            s["payload"]["pick_id"] = None
    assert isinstance(facts.from_trace(other, pick_id=PICK), PickFacts), "a selection's decision serves when none names the pick"


def test_every_code_a_fact_may_have_is_explained_to_the_model() -> None:
    codes = {f.code for f in pick_facts().facts} | set(facts.REASON_RISKS.values()) | {c for c, _, _ in facts.RISK_PATTERNS} \
        | {"context_limited"}
    assert codes <= set(prompt.GLOSSARY), sorted(codes - set(prompt.GLOSSARY))
    for code in prompt.GLOSSARY:
        assert f"- {code}: " in prompt.SYSTEM


# ── the verifier ──────────────────────────────────────────────────────────────────────────────────────────────────────

def s(text: str, *ids: str) -> dict[str, Any]:
    return {"text": text, "facts": list(ids)}


GOOD_WHY = [
    (s("PrediGol da a Atlético Nacional un 34 % de ganar, más de lo que pagan las casas con una cuota de 3,40.",
       "F:match", "F:probability", "F:odds"),
     s("PrediGol gives Atlético Nacional a 34% chance to win, more than the bookmakers imply at odds of 3.40.",
       "F:match", "F:probability", "F:odds")),
    (s("Según elcolombiano.com, Nacional recupera a Dorlan Pabón, y la revisión de PrediGol Intelligence aprobó el pick.",
       "F:evidence.100", "F:review"),
     s("According to elcolombiano.com, Nacional gets Dorlan Pabón back, and PrediGol Intelligence's review approved the pick.",
       "F:evidence.100", "F:review")),
]
GOOD_RISKS = [
    (s("La cuota de 3,40 está por encima del límite de 3,00 que PrediGol marca como riesgo.", "F:risk.long_odds"),
     s("The price of 3.40 is above the 3.00 limit PrediGol flags as a risk.", "F:risk.long_odds")),
]


def answer(why: list[tuple[dict[str, Any], dict[str, Any]]] | None = None,
           risks: list[tuple[dict[str, Any], dict[str, Any]]] | None = None) -> dict[str, Any]:
    why = GOOD_WHY if why is None else why
    risks = GOOD_RISKS if risks is None else risks
    return {"es": {"why": [a for a, _ in why], "risks": [a for a, _ in risks]},
            "en": {"why": [b for _, b in why], "risks": [b for _, b in risks]}}


def checked(data: dict[str, Any]) -> verify.Verdict:
    return verify.verify(verify.NarratorOut.model_validate(data), pick_facts())


def test_a_narrative_the_facts_support_stands_whole() -> None:
    v = checked(answer())
    assert v.status == "ok" and v.dropped == [] and v.kept == 3
    assert v.content is not None and v.content["es"]["why"][0]["facts"] == ["F:match", "F:probability", "F:odds"]
    assert verify.facts_cited(v.content) == ["F:match", "F:probability", "F:odds", "F:evidence.100", "F:review", "F:risk.long_odds"]


@pytest.mark.parametrize(("es", "en", "why"), [
    (s("Nacional gana el 62 % de sus partidos en casa y PrediGol le da un 34 %.", "F:probability"),
     s("Nacional wins 62% of its home games and PrediGol gives it 34%.", "F:probability"), "numbers no cited fact has: 62"),
    (s("Con cinco victorias seguidas, PrediGol le da un 34 % a Nacional.", "F:probability", "F:match"),
     s("After five wins in a row, PrediGol gives Nacional 34%.", "F:probability", "F:match"), "numbers no cited fact has: cinco"),
    (s("La cuota de 3,40 es buena aunque Dorlan Pabón no juegue.", "F:odds"),
     s("The 3.40 price is good even if Dorlan Pabón does not play.", "F:odds"), "names no cited fact has: Dorlan, Pabón"),
    (s("La cuota de 3,40 paga más que el riesgo.", "F:odds", "F:form.home"),
     s("The 3.40 price pays more than the risk.", "F:odds", "F:form.home"), "cites facts that do not exist: F:form.home"),
    (s("La cuota de 3,40 está por encima del límite de 3,00.", "F:risk.long_odds"),
     s("The 3.40 price is above the 3.00 limit.", "F:risk.long_odds"), "a risk cited as a reason: F:risk.long_odds"),
    (s("Con un 34 % de PrediGol es un pick seguro.", "F:probability"),
     s("With PrediGol's 34% it is a sure pick.", "F:probability"), "certainty: 'seguro'"),
    (s("El partido lo juega Atlético Nacional ante Millonarios.", "F:match"),
     s("Atlético Nacional face Millonarios in this one.", "F:match"), "cites only the match's identity: no fact of the pick"),
])
def test_an_unsupported_sentence_is_dropped_and_the_rest_stands(es: dict[str, Any], en: dict[str, Any], why: str) -> None:
    v = checked(answer(why=[*GOOD_WHY, (es, en)]))
    assert v.status == "partial" and v.kept == 3, v.dropped
    assert v.content is not None and es["text"] not in json.dumps(v.content, ensure_ascii=False)
    assert v.dropped[0].where == "es.why[2]" and v.dropped[0].why == why


def test_a_rumour_is_a_risk_called_so_and_the_languages_must_agree() -> None:
    rumour = (s("Hay un rumor sin confirmar sobre el portero de Millonarios.", "F:evidence.101"),
              s("There is an unconfirmed rumour about the Millonarios goalkeeper.", "F:evidence.101"))
    told_as_fact = (s("El portero de Millonarios no viajó.", "F:evidence.101"),
                    s("The Millonarios goalkeeper did not travel.", "F:evidence.101"))
    v = checked(answer(risks=[rumour, told_as_fact]))
    assert v.content is not None and len(v.content["es"]["risks"]) == 1
    assert [d.why for d in v.dropped] == ["a rumour or a contradiction not called one"] * 2
    other_numbers = (GOOD_WHY[0][0], s("PrediGol gives Atlético Nacional a 40% chance at odds of 3.40.", "F:match",
                                        "F:probability", "F:odds"))
    v = checked(answer(why=[other_numbers, GOOD_WHY[1]]))
    assert any("numbers no cited fact has: 40" in d.why for d in v.dropped) and v.kept == 2
    lone = answer()
    lone["es"]["why"].append(s("PrediGol le da a Nacional un 34 %.", "F:probability", "F:match"))
    v = checked(lone)
    assert v.dropped[-1].why == "no counterpart in the other language" and v.kept == 3


def test_no_why_sentence_standing_is_no_narrative() -> None:
    bad = (s("Nacional ganará seguro con un 34 %.", "F:probability"), s("Nacional will win for sure at 34%.", "F:probability"))
    v = checked(answer(why=[bad]))
    assert v.status == "rejected" and v.content is None and v.kept == 0 and len(v.dropped) == 2


def test_an_uncalibrated_probability_says_so() -> None:
    data = trace_json()
    for sp in data["spans"]:
        if sp["kind"] == "decision":
            for f in sp["payload"]["filters"]:
                if f["key"] == "calibration":
                    f["ok"] = False
    pf = facts.from_trace(data, pick_id=PICK, identity=IDENTITY)
    assert isinstance(pf, PickFacts) and pf.by_id()["F:probability"].params["calibrated"] is False
    assert verify.check_sentence("PrediGol le da un 34 % a este pick.", ["F:probability"], lang="es", section="why", pf=pf) \
        == "an uncalibrated probability without its label"
    assert verify.check_sentence("PrediGol le da un 34 %, aún sin calibrar.", ["F:probability"], lang="es", section="why",
                                 pf=pf) is None


# ── off by default ────────────────────────────────────────────────────────────────────────────────────────────────────

class Untouchable:
    """A connection that fails the test the moment anything uses it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the Narrator touched the database while off ({name})")


def test_the_narrator_is_off_by_default_and_then_reads_calls_and_spends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "environment", lambda: {})
    assert job.narrator_mode() == "off" and job.narrator_mode({"FBI_NARRATOR": "typo"}) == "off"
    assert job.narrator_mode({"FBI_NARRATOR": " Shadow "}) == "shadow" and job.narrator_mode({"FBI_NARRATOR": "1"}) == "on"
    provider = FakeProvider(lambda r: answer())
    report = job.run(Untouchable(), AiSettings(), pick_ids=[PICK], at=KO, provider=(provider, "fake-model"))  # type: ignore[arg-type]
    assert report.status == "off" and report.cost_usd == 0 and report.outcomes == [] and provider.requests == []
    broke = job.run(Untouchable(), AiSettings(), pick_ids=[PICK], at=KO, mode="shadow", monthly=Decimal(0),  # type: ignore[arg-type]
                    provider=(provider, "fake-model"))
    assert broke.status == "no_budget" and provider.requests == [], "the readers' budget at 0 is off too"


def test_the_tier_is_analysis_unless_the_owner_says_another() -> None:
    assert job.narrator_tier({}) == "analysis" and job.narrator_tier({"FBI_NARRATOR_TIER": "bulk"}) == "bulk"
    assert job.narrator_tier({"FBI_NARRATOR_TIER": "opus please"}) == "analysis"


# ── end to end with the fake provider ─────────────────────────────────────────────────────────────────────────────────

def fake_caller(provider: FakeProvider, cost: str = "0.012") -> job.Caller:
    def call(req: JsonRequest, pf: PickFacts) -> CallOutcome:
        result = provider.complete_json("fake-sonnet", req)
        return CallOutcome(result, None, "analysis", provider.name, result.model, Decimal(cost))
    return call


def test_a_fake_provider_goes_through_facts_prompt_call_and_verifier() -> None:
    data = answer(why=[*GOOD_WHY, (s("Nacional llega con cuatro victorias seguidas.", "F:match", "F:value"),
                                   s("Nacional arrive on four straight wins.", "F:match", "F:value"))])
    provider = FakeProvider(lambda r: data)
    pf = pick_facts()
    out = job.narrate(pf, call=fake_caller(provider))
    assert out.status == "partial" and out.cost == Decimal("0.012") and out.input_hash == pf.hash
    assert out.content is not None and len(out.content["es"]["why"]) == 2 and len(out.content["en"]["risks"]) == 1
    assert [d.why for d in out.dropped] == ["numbers no cited fact has: cuatro", "numbers no cited fact has: four"]
    (req,) = provider.requests
    assert req.schema == prompt.SCHEMA and req.schema_name == "submit_pick_why" and req.system == prompt.SYSTEM
    sent = json.loads(req.user)
    assert [f["id"] for f in sent["facts"]] == [f.id for f in pf.facts] and sent["limits"] == prompt.LIMITS
    assert "REJECT" not in req.user and "Only an agent run" not in req.user, "the model sees the decision's facts only"
    doc = out.as_json()
    assert doc["version"] == VERSION and doc["prompt_version"] == "pick-why-v1" and doc["cost_usd"] == "0.012"


def test_a_broken_answer_or_a_failed_call_is_no_narrative() -> None:
    out = job.narrate(pick_facts(), call=fake_caller(FakeProvider(lambda r: {"es": {"why": []}})))
    assert out.status == "invalid_output" and out.content is None and out.error
    failed = FakeProvider(lambda r: answer(), fail="timeout")

    def call(req: JsonRequest, pf: PickFacts) -> CallOutcome:
        try:
            failed.complete_json("m", req)
        except Exception:
            return CallOutcome(None, None, None, "fake", "m", Decimal(0), "timeout")
        raise AssertionError("the scripted failure did not happen")

    out = job.narrate(pick_facts(), call=call)
    assert out.status == "timeout" and out.content is None and out.cost == 0

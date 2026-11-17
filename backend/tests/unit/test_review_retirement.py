"""The conditioned retirement of ``review-v2`` (IA-125, AD-D11): ``review-retire-v1``. Prepared, never executed: the criterion preregistered,
the comparison, the effect of removing the model review and the switch whose ``on`` (the default) is today's path. No database, no model."""

from __future__ import annotations

import ast
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.ai import cycle
from fbi.ai import review as rv
from fbi.ai import review_retirement as rr
from fbi.ai.config import AiSettings

D = Decimal
CYCLE = Path(cycle.__file__).read_text(encoding="utf-8")


# -- the switch -------------------------------------------------------------------------------------------------------------------------

def test_the_switch_is_on_unless_it_names_a_step(monkeypatch: pytest.MonkeyPatch) -> None:
    assert rr.STEPS == ("on", "no_opus", "sample", "off") and rr.DEFAULT == "on"
    assert [rr.step_of(w) for w in (None, "", "ON", " no_opus ", "sample", "off", "retire", "0")] == [
        "on", "on", "on", "no_opus", "sample", "off", "on", "on"]
    monkeypatch.delenv("FBI_REVIEW_V2", raising=False)
    assert AiSettings.from_env().review_v2 == "on" == AiSettings().review_v2
    monkeypatch.setenv("FBI_REVIEW_V2", "no_opus")
    assert AiSettings.from_env().review_v2 == "no_opus" and AiSettings.from_env().public()["review_v2"] == "no_opus"


def test_on_is_todays_path_and_each_step_takes_one_more_thing_away() -> None:
    key = (77, "1X2", "Home", D(0))
    assert (rr.tier_for("on", "final"), rr.tier_for("on", "analysis"), rr.escalates("on"), rr.model_reviews("on", *key), rr.carries("on")) == (
        "final", "analysis", True, True, True), "on: L3, the arbitration, the model and the carried review, as today"
    assert (rr.tier_for("no_opus", "final"), rr.escalates("no_opus"), rr.model_reviews("no_opus", *key), rr.carries("no_opus")) == (
        "analysis", False, True, True), "step 1: no Opus"
    assert not rr.escalates("sample") and rr.tier_for("sample", "final") == "analysis" and rr.carries("sample")
    assert rr.model_reviews("sample", *key) is rr.in_sample(*key)
    assert (rr.model_reviews("off", *key), rr.carries("off"), rr.escalates("off")) == (False, False, False), "step 3: the rules alone"


def test_the_control_group_is_a_fixed_share_with_no_state() -> None:
    keys = [(f, m, s, D(line)) for f in range(1000, 1400) for m, s, line in (("1X2", "Home", "0"), ("OU", "Over", "2.5"), ("AH", "Away", "-0.5"))]
    share = sum(rr.in_sample(*k) for k in keys) / len(keys)
    assert abs(share - float(rr.SAMPLE_SHARE)) < 0.03, share
    assert [rr.in_sample(*k) for k in keys[:50]] == [rr.in_sample(*k) for k in keys[:50]]
    assert rr.bucket(1, "OU", "Over", D("2.50")) == rr.bucket(1, "OU", "Over", D("2.5")), "the line is read as a number"


def test_the_cycle_reads_the_step_wherever_the_model_review_is_asked() -> None:
    tree = ast.parse(CYCLE)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "review_candidate"]
    assert len(calls) == 5
    assert CYCLE.count("retire.escalates(step)") == 2, "both arbitrations by the strong model"
    assert "retire.tier_for(step," in CYCLE and CYCLE.count("retire.model_reviews(") == 2 and CYCLE.count("retire.carries(") == 2
    assert "step = settings.review_v2" in CYCLE


# -- the criterion and the comparison ---------------------------------------------------------------------------------------------------

def test_the_protocol_is_written_before_anything_is_measured() -> None:
    p = rr.PROTOCOL
    assert p["version"] == rr.VERSION == "review-retire-v1" and p["status"].startswith("propuesto")
    assert (D("0.005"), 300, 14, 20261117, 2000) == (rr.MARGIN, rr.MIN_SELECTIONS, rr.MIN_DAYS, rr.SEED, rr.REPLICATES)
    assert {"population", "reference", "new_path", "metric", "interval", "rule", "window"} <= set(p)


def pairs(n: int, days: int, *, new_keeps: float, ref_keeps: float, clv: float = 0.05) -> list[rr.Pair]:
    out: list[rr.Pair] = []
    for i in range(n):
        value = clv if i % 2 == 0 else -clv / 2
        out.append(rr.Pair(date(2026, 12, 1) + timedelta(days=i % days), value, (i % 100) < ref_keeps * 100, (i % 100) < new_keeps * 100))
    return out


def test_the_verdicts_of_the_comparison() -> None:
    small = rr.compare(pairs(120, 20, new_keeps=0.5, ref_keeps=0.5))
    assert small["verdict"] == "INSUFICIENTE" and small["reasons"] == ["selections_below_300"] and small["decides"] is False
    few_days = rr.compare(pairs(400, 7, new_keeps=0.5, ref_keeps=0.5))
    assert few_days["verdict"] == "INSUFICIENTE" and few_days["reasons"] == ["days_below_14"]
    same = rr.compare(pairs(400, 20, new_keeps=0.5, ref_keeps=0.5))
    assert same["verdict"] == "NO_INFERIOR" and same["difference"]["mean"] == 0 and same["discordant"] == {"only_new": 0, "only_reference": 0}
    worse = [rr.Pair(p.day, p.clv, True, p.kept_new and p.clv < 0) for p in pairs(400, 20, new_keeps=1.0, ref_keeps=1.0, clv=0.2)]
    judged = rr.compare(worse)
    assert judged["verdict"] == "INFERIOR" and judged["difference"]["high"] < 0, judged["difference"]
    assert rr.compare(worse) == judged, "the same seed, the same interval"


# -- what removing the model changes ----------------------------------------------------------------------------------------------------

def test_the_effect_of_removal_is_the_combined_review_without_the_model() -> None:
    reviews = [rr.Review("APPROVE", "REJECT"), rr.Review("APPROVE", "DOWNGRADE"), rr.Review("APPROVE", "APPROVE"), rr.Review("REJECT", "APPROVE"),
               rr.Review("APPROVE", None), rr.Review("DOWNGRADE", "ABSTAIN"), rr.Review("ABSTAIN", "REJECT")]
    e = rr.effect_of_removal(reviews)
    assert (e["reviews"], e["with_model"], e["changed"]) == (7, 6, 3)
    assert e["moves"] == {"DOWNGRADE->APPROVE": 1, "REJECT->ABSTAIN": 1, "REJECT->APPROVE": 1} and e["raised"] == 3 and e["lowered"] == 0
    for r in reviews:
        engines = [rv.EngineResult("rules", "rules-review-v1", r.rules, {})] + ([] if r.model is None else [rv.EngineResult("llm", "review-v2", r.model, {})])  # type: ignore[arg-type]
        assert rr.combined([x.decision for x in engines]) == rv.combine(engines), "the same rule as the production review"

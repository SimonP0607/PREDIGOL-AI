"""The LAB's experiments, the parts that are pure (Plan Maestro IA, Phase 0).

What opens a gate is a RULE written before the data, and the rule has to be right on its own: the verdict change of a variant against the
change of repeating the same call, the size it needs, the invalid answers it may have, what a probe has to see for the cache and for
the Message Batches API to be called working. Nothing here touches a database or a network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import lab
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.lab import (
    MIN_INPUTS,
    VARIANT_KEY,
    Rows,
    assess,
    batch_evidence,
    blockers,
    cache_verdict,
    equivalence_requests,
    equivalence_rows,
    equivalence_tasks,
    experiment_id,
    filler,
    probe_batch_tasks,
)
from fbi.ai.pricing import approx_tokens
from fbi.ai.providers.base import LlmUsage

from .test_review_layout import AT, candidate, packet_of

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET),
         "final": TierModel("anthropic", OPUS)}


def rows_of(n: int, *, repeat: int = 0, changed: int = 0, variant: str = "native_schema", bad_variant: int = 0,
            bad_base: int = 0) -> Rows:
    """``n`` inputs approved by the first call. The first ``repeat`` are downgraded by the second identical call, the first
    ``changed`` by the variant; the LAST ``bad_variant`` inputs have no valid variant answer, the last ``bad_base`` no valid second call."""
    key = VARIANT_KEY[variant]
    rows: Rows = {}
    for i in range(n):
        rows[f"p{i}"] = {"A1": "A", "A2": "D" if i < repeat else "A", key: "D" if i < changed else "A"}
    for i in range(n - bad_variant, n):
        rows[f"p{i}"][key] = None
    for i in range(n - bad_base, n):
        rows[f"p{i}"]["A2"] = None
    return rows


# ── the verdict change ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_variant_that_changes_nothing_passes_with_the_inputs_the_plan_asks() -> None:
    a = assess(rows_of(MIN_INPUTS), "native_schema")
    assert a["passed"] is True and a["verdict"] == "PASA" and a["reasons"] == [] and a["complete_inputs"] == MIN_INPUTS
    assert a["change_repeat"] == 0 == a["change_variant"] and a["insufficient"] is False


def test_the_plan_asks_for_200_stored_packets() -> None:
    assert MIN_INPUTS == 200


def test_fewer_inputs_than_the_plan_asks_are_insufficient_and_never_a_pass() -> None:
    a = assess(rows_of(MIN_INPUTS - 1), "native_schema")
    assert a["passed"] is False and a["verdict"] == "INSUFICIENTE" and a["insufficient"] is True
    assert a["reasons"][0].startswith("insufficient: 199 complete inputs, 200 needed")


def test_a_variant_that_changes_as_many_verdicts_as_repeating_the_call_passes() -> None:
    a = assess(rows_of(210, repeat=12, changed=12), "native_schema")
    assert a["passed"] is True and a["changed_repeat"] == 12 == a["changed_variant"] and a["verdict"] == "PASA"


def test_a_variant_that_changes_fewer_verdicts_than_repeating_the_call_passes() -> None:
    a = assess(rows_of(210, repeat=12, changed=5), "native_schema")
    assert a["passed"] is True and a["changed_variant"] == 5


def test_one_more_verdict_changed_than_by_repeating_the_call_does_not_pass() -> None:
    a = assess(rows_of(210, repeat=12, changed=13), "native_schema")
    assert a["passed"] is False and a["verdict"] == "NO PASA"
    assert any("changes more verdicts (13) than repeating the same call (12)" in r for r in a["reasons"])


def test_a_variant_is_judged_against_the_repeat_on_the_same_inputs() -> None:
    rows = rows_of(205, repeat=0, changed=0)
    for i in range(5):  # five inputs where the second identical call is not valid: out of the comparison for everyone
        rows[f"p{i}"]["A2"] = None
        rows[f"p{i}"]["B"] = "R"
    a = assess(rows, "native_schema")
    assert a["complete_inputs"] == 200 and a["changed_variant"] == 0 and a["passed"] is True
    assert a["invalid_baseline"] == pytest.approx(5 / 410, abs=1e-4), "the invalid second calls are counted as invalid"


def test_the_two_variants_use_their_own_asks() -> None:
    rows = rows_of(210, variant="native_schema", changed=30)
    for r in rows.values():
        r["C"] = "A"
    assert assess(rows, "native_schema")["passed"] is False
    assert assess(rows, "shared_layout")["passed"] is True


# ── invalid answers ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_more_than_three_percent_invalid_does_not_pass() -> None:
    a = assess(rows_of(210, bad_variant=7), "native_schema")  # 3,3 % of the variant's answers; 203 inputs are complete
    assert a["complete_inputs"] == 203 and a["invalid_variant"] == pytest.approx(7 / 210, abs=1e-4)
    assert a["passed"] is False and "invalid more often than allowed" in a["reasons"][-1]


def test_invalid_answers_more_than_a_point_above_the_calls_made_today_do_not_pass() -> None:
    a = assess(rows_of(210, bad_variant=5), "native_schema")  # 2,4 %: under 3 % but production's calls had none
    assert a["invalid_baseline"] == 0.0 and a["passed"] is False


def test_invalid_answers_as_frequent_as_the_calls_made_today_pass() -> None:
    a = assess(rows_of(210, bad_variant=2, bad_base=2), "native_schema")
    assert a["invalid_baseline"] == pytest.approx(2 / 420, abs=1e-4) and a["invalid_variant"] == pytest.approx(2 / 210, abs=1e-4)
    assert a["passed"] is True


# ── what is reported and not decided on ─────────────────────────────────────────────────────────────────────────────

def test_the_direction_of_the_changes_is_reported() -> None:
    rows = rows_of(210)
    for i in range(10):  # the variant restricts ten approvals
        rows[f"p{i}"]["B"] = "R"
    for i in range(10, 14):  # ... and the repeat restricts four of them
        rows[f"p{i}"]["A2"] = "D"
    for i in range(20, 23):  # the first call did not approve three; the variant does
        rows[f"p{i}"]["A1"], rows[f"p{i}"]["A2"], rows[f"p{i}"]["B"] = "D", "D", "A"
    a = assess(rows, "native_schema")
    assert a["toward_restriction"] == {"repeat": 4, "variant": 10}
    assert a["toward_approve"] == {"repeat": 0, "variant": 3}
    assert a["moves"] == {"repeat": {"A>D": 4}, "variant": {"A>R": 10, "D>A": 3}}
    assert a["approve_share"]["A1"] == pytest.approx(207 / 210, abs=1e-4)


def test_the_interval_of_the_difference_says_how_much_of_a_result_can_be_luck() -> None:
    worse = assess(rows_of(200, repeat=0, changed=20), "native_schema")
    assert worse["difference"] == 0.1 and worse["difference_ci95"][0] > 0 and worse["passed"] is False
    better = assess(rows_of(200, repeat=20, changed=0), "native_schema")
    assert better["difference"] == -0.1 and better["difference_ci95"][1] < 0 and better["passed"] is True
    same = assess(rows_of(200, repeat=10, changed=10), "native_schema")
    assert same["difference"] == 0.0 and same["difference_ci95"] == [0.0, 0.0]


def test_a_smaller_bar_is_only_for_tests_and_still_not_a_pass_below_it() -> None:
    assert assess(rows_of(30), "native_schema", min_inputs=30)["passed"] is True
    assert assess(rows_of(29), "native_schema", min_inputs=30)["passed"] is False


def test_nothing_to_measure_is_insufficient() -> None:
    a = assess({}, "native_schema")
    assert a["passed"] is False and a["complete_inputs"] == 0 and a["verdict"] == "INSUFICIENTE" and "difference" not in a


# ── what each result row becomes ────────────────────────────────────────────────────────────────────────────────────

def _item(status: str, decision: Any, *, variant: str = "A1", ref: str = "1:1") -> dict[str, Any]:
    return {"status": status, "context": {"input": ref, "variant": variant, "result": {"decision": decision}}}


def test_the_rows_hold_the_letter_of_each_valid_review_and_none_for_the_rest() -> None:
    items = [_item("succeeded", "APPROVE", variant="A1"), _item("late", "REJECT", variant="A2"),
             _item("succeeded", "DOWNGRADE", variant="B"), _item("succeeded", "ABSTAIN", variant="C"),
             _item("succeeded", None, ref="2:2"), _item("invalid", "APPROVE", variant="A2", ref="2:2"),
             _item("errored", None, variant="B", ref="2:2"), _item("expired", None, variant="C", ref="2:2"),
             _item("succeeded", "MAYBE", variant="A1", ref="3:3")]
    assert equivalence_rows(items) == {"1:1": {"A1": "A", "A2": "R", "B": "D", "C": "S"},
                                       "2:2": {"A1": None, "A2": None, "B": None, "C": None},
                                       "3:3": {"A1": None}}


def test_an_item_without_a_result_is_not_a_review() -> None:
    assert equivalence_rows([{"status": "succeeded", "context": {"input": "1:1", "variant": "A1"}}]) == {"1:1": {"A1": None}}


# ── the cache ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_cache_works_when_the_second_call_reads_what_the_first_wrote() -> None:
    v = cache_verdict(LlmUsage(input_tokens=3300, cache_write_5m_tokens=1600, cache_write_1h_tokens=1600),
                      LlmUsage(input_tokens=3300, cached_tokens=3200))
    assert v["ok"] is True and v["wrote"] and v["read"] and v["both_ttls"] and v["read_what_was_written"]
    assert v["wrote_tokens"] == 3200 and v["wrote_5m_tokens"] == 1600 and v["wrote_1h_tokens"] == 1600 and v["read_tokens"] == 3200


def test_a_first_call_that_wrote_nothing_is_no_cache_even_if_the_second_read_something() -> None:
    v = cache_verdict(LlmUsage(input_tokens=3300), LlmUsage(input_tokens=3300, cached_tokens=3000))
    assert v["ok"] is False and v["wrote"] is False and v["read"] is True


def test_a_second_call_that_read_little_of_what_was_written_is_not_a_cache() -> None:
    first = LlmUsage(input_tokens=3300, cache_write_5m_tokens=1000)
    assert cache_verdict(first, LlmUsage(input_tokens=3300, cached_tokens=899))["ok"] is False
    assert cache_verdict(first, LlmUsage(input_tokens=3300, cached_tokens=900))["ok"] is True
    assert cache_verdict(first, LlmUsage(input_tokens=3300))["ok"] is False


# ── the Message Batches API ─────────────────────────────────────────────────────────────────────────────────────────

T0 = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)


def probe_item(model: str, variant: str, *, status: str = "succeeded", valid: bool = True, read: int = 0) -> dict[str, Any]:
    return {"model": model, "status": status, "error": None if status == "succeeded" else "overloaded_error",
            "context": {"variant": variant, "result": {"valid": valid, "stop_reason": "tool_use"}}, "cached_tokens": read,
            "cache_write_tokens": 0, "input_tokens": 3300, "output_tokens": 30, "cost_usd": Decimal("0.0016"),
            "batch_created": T0, "batch_ended": T0 + timedelta(minutes=27)}


def run_of(*models: str, bad: tuple[str, str] | None = None, native_bad: str | None = None, read: str | None = None) -> list[dict[str, Any]]:
    out = []
    for m in models:
        for variant in ("tool", "native", "tool2"):
            failed = bad == (m, variant) or (native_bad == m and variant == "native")
            out.append(probe_item(m, variant, status="errored" if failed else "succeeded", valid=not failed,
                                  read=1500 if read == m and variant == "tool2" else 0))
    return out


def test_the_batch_probe_waits_for_every_result() -> None:
    items = run_of(HAIKU, SONNET)
    items[2]["status"] = "submitted"
    passed, evidence = batch_evidence(items)
    assert passed is None and evidence == {"state": "waiting", "open": 1}


def test_the_batch_gate_names_the_models_whose_tool_call_came_back_inside_the_schema() -> None:
    passed, evidence = batch_evidence(run_of(HAIKU, SONNET))
    assert passed is True and evidence["models"] == [HAIKU, SONNET] and evidence["failed_models"] == []
    assert evidence["state"] == "ended" and evidence["elapsed_minutes"] == 27.0 and evidence["probe"] == "probe-batch-v1"
    assert evidence["native_in_batch"] == {HAIKU: True, SONNET: True}


def test_a_model_whose_batch_probe_failed_is_not_covered_but_the_others_are() -> None:
    passed, evidence = batch_evidence(run_of(HAIKU, SONNET, bad=(SONNET, "tool")))
    assert passed is True and evidence["models"] == [HAIKU] and evidence["failed_models"] == [SONNET]
    assert evidence["items"][SONNET]["tool"] == {
        "ok": False, "status": "errored", "error": "overloaded_error", "stop_reason": "tool_use", "read_tokens": 0,
        "wrote_tokens": 0, "input_tokens": 3300, "output_tokens": 30, "cost_usd": "0.0016"}


def test_no_model_covered_is_a_failed_gate() -> None:
    items = run_of(HAIKU, bad=(HAIKU, "tool"))
    passed, evidence = batch_evidence(items)
    assert passed is False and evidence["models"] == [] and evidence["failed_models"] == [HAIKU]


def test_an_answer_that_does_not_fit_its_schema_is_not_a_working_batch() -> None:
    items = run_of(HAIKU)
    items[0]["context"]["result"] = {"valid": False, "error": "schema"}
    passed, _ = batch_evidence(items)
    assert passed is False


def test_structured_outputs_and_the_cache_are_said_per_model_inside_the_batch() -> None:
    _, evidence = batch_evidence(run_of(HAIKU, SONNET, native_bad=HAIKU, read=SONNET))
    assert evidence["native_in_batch"] == {HAIKU: False, SONNET: True}
    assert evidence["cache_read_in_batch"] == {HAIKU: False, SONNET: True}


# ── what is needed to run ───────────────────────────────────────────────────────────────────────────────────────────

def test_without_a_lab_key_or_envelope_the_lab_says_which_variable_and_which_owner_action() -> None:
    cfg = AiSettings(tiers=dict(TIERS), keys={"anthropic": "sk-prod-secret"})
    out = blockers(cfg, ["bulk", "analysis"])
    assert len(out) == 2 and "FBI_AI_KEY_ANTHROPIC_LAB" in out[0] and "owner actions 5 and 7" in out[0]
    assert "FBI_AI_LAB_MONTHLY_BUDGET_USD" in out[1] and "owner action 7" in out[1]
    assert "sk-prod-secret" not in " ".join(out), "a blocker names a variable, never a value"


def test_with_a_key_and_an_envelope_nothing_blocks() -> None:
    cfg = AiSettings(tiers=dict(TIERS), keys={"anthropic": "sk-prod"}, lab_keys={"anthropic": "sk-lab-secret"},
                     lab_monthly_budget=Decimal(15))
    assert blockers(cfg, ["bulk", "analysis"]) == []


def test_a_tier_without_a_model_for_the_lab_blocks() -> None:
    cfg = AiSettings(tiers={"bulk": TierModel("anthropic", HAIKU)}, lab_keys={"anthropic": "sk-lab"}, lab_monthly_budget=Decimal(15))
    out = blockers(cfg, ["bulk", "analysis"])
    assert out == ["the analysis tier has no Anthropic model for the LAB"]


# ── the requests ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_probe_blocks_are_over_the_size_a_cache_needs_and_the_same_every_time() -> None:
    assert filler("S", 100) == filler("S", 100) and filler("S", 100) != filler("M", 100)
    assert approx_tokens(lab.PROBE_SYSTEM, "anthropic") > 1024 and approx_tokens(lab.PROBE_SHARED, "anthropic") > 1024
    assert len(filler("S", 100)) >= 400


def test_a_probe_request_is_pinned_and_marked_for_the_cache() -> None:
    r = lab.probe_request("hi")
    assert r.pinned and r.cache and r.shared == lab.PROBE_SHARED and r.native_schema is False
    assert lab.probe_request("hi", native=True, shared=False).shared == ""
    assert lab.probe_request("hi", native=True).native_schema is True


def test_the_batch_probe_has_three_asks_per_model_and_one_probe_when_two_tiers_share_a_model() -> None:
    cfg = AiSettings(tiers={"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", HAIKU),
                            "final": TierModel("anthropic", OPUS)}, lab_keys={"anthropic": "sk-lab"}, lab_monthly_budget=Decimal(15))
    tasks = probe_batch_tasks(cfg, run="2032-08-01", tiers=["bulk", "analysis", "final"])
    assert [(t.tier, t.context["variant"]) for t in tasks] == [("bulk", "tool"), ("bulk", "native"), ("bulk", "tool2"),
                                                                ("final", "tool"), ("final", "native"), ("final", "tool2")]
    assert all(t.lab and t.purpose == "other" and t.request.pinned and t.context["lab"] == "probe" for t in tasks)
    assert all(t.typical_output == lab.PROBE_TYPICAL_OUTPUT and t.fixture_id is None for t in tasks)
    assert len({t.input_hash for t in tasks}) == 6, "each ask is its own task"
    assert [t.request.native_schema for t in tasks[:3]] == [False, True, False]
    again = probe_batch_tasks(cfg, run="2032-08-02", tiers=["bulk", "analysis", "final"])
    assert {t.input_hash for t in again}.isdisjoint({t.input_hash for t in tasks}), "another day, another probe"


def test_the_four_asks_of_an_input_are_what_production_asks_and_what_each_variant_changes() -> None:
    packet = packet_of()
    cand = candidate()
    inp = lab.EquivInput("1:1", cand, 1, AT)
    asks = equivalence_requests(inp, packet)
    assert list(asks) == ["A1", "A2", "B", "C"]
    assert all(r.pinned for r in asks.values()), "production's switches neither add nor take away what is measured"
    a1 = asks["A1"]
    assert a1 == asks["A2"] and a1.cache is True and a1.native_schema is False and a1.shared == ""
    assert a1.schema_name == "submit_review" and a1.max_tokens == 8000
    assert asks["B"].native_schema is True and asks["B"].shared == "" and asks["B"].user == a1.user
    assert a1.split is not None
    assert (asks["C"].shared, asks["C"].user) == a1.split and asks["C"].native_schema is False and asks["C"].cache is True


def test_the_tasks_of_an_input_are_four_distinct_lab_items_that_name_no_match() -> None:
    packet = packet_of()
    inp = lab.EquivInput("9:77", candidate(), 9, AT)
    tasks = equivalence_tasks(inp, packet, tier="analysis", experiment="exp-1")
    assert [t.context["variant"] for t in tasks] == ["A1", "A2", "B", "C"]
    assert len({t.input_hash for t in tasks}) == 4, "the two identical calls are two asks: the second is the yardstick"
    assert all(t.lab and t.purpose == "other" and t.fixture_id is None and t.typical_output == 1000 for t in tasks)
    ctx = tasks[0].context
    assert ctx["lab"] == "equivalence" and ctx["experiment"] == "exp-1" and ctx["input"] == "9:77" and ctx["packet_id"] == 9
    assert ctx["candidate"]["selection"] == "Home" and ctx["at"] == AT.isoformat()
    assert tasks[3].request.shared and not tasks[0].request.shared, "the queue notes the layout in the item when the request has the block first"
    assert tasks[0].input_hash != equivalence_tasks(inp, packet, tier="analysis", experiment="exp-2")[0].input_hash


def test_an_experiment_is_named_by_model_seed_and_day() -> None:
    assert experiment_id(SONNET, "equiv-v1", AT) == "equiv-v1:claude-sonnet-5-5:equiv-v1:2032-08-01"
    assert experiment_id(SONNET, "equiv-v1", AT + timedelta(days=1)) != experiment_id(SONNET, "equiv-v1", AT)

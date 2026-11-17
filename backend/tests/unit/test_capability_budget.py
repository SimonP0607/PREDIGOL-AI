"""IA-058 (AD-A06): the register of what each new capability may spend a month, the warnings at 80 and 95 %, the three envelopes of
decision 12 with the readers' chronicle in production's, the joint ceiling that still applies and Exa's price shown unverified.
Pure: no database."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import budget_v3, capability_budget, costs_v3, envelopes_readers, pricing
from fbi.ai.capability_budget import (
    CAPABILITIES,
    DECISION_12,
    Row,
    capability_of,
    declared,
    get,
    level,
    report,
    spend,
)
from fbi.ai.config import AiSettings

D = Decimal
AT = datetime(2032, 8, 15, 17, 0, tzinfo=UTC)


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"monthly_budget": D(185), "lab_monthly_budget": D(55), "exa_monthly_budget": D(35),
                            "joint_ceiling": D(190)}
    return AiSettings(**(base | kw))


# ── the register ───────────────────────────────────────────────────────────────────────────────────────────────


def test_decision_12_is_185_for_production_35_for_exa_and_55_for_the_lab() -> None:
    assert {"production": D(185), "exa": D(35), "lab": D(55)} == DECISION_12
    assert capability_budget.ALERT_AT == budget_v3.ENVELOPE_ALERTS == (80, 95)


def test_every_capability_has_one_key_an_envelope_a_positive_cap_and_where_its_figure_comes_from() -> None:
    keys = [c.key for c in CAPABILITIES]
    assert len(keys) == len(set(keys)), "a key is never reused"
    for c in CAPABILITIES:
        assert c.envelope in capability_budget.ENVELOPES, c.key
        assert c.monthly_usd > 0 and c.monthly_usd == c.monthly_usd.quantize(D("0.01")), c.key
        assert c.piece.startswith("AD-") and c.source.strip(), c.key


def test_the_caps_of_each_envelope_fit_inside_it() -> None:
    for envelope, row in declared().items():
        assert D(row["declared_usd"]) <= D(row["envelope_usd"]) == DECISION_12[envelope], envelope
    assert declared()["production"] == {"declared_usd": "46.90", "envelope_usd": "185.00"}


def test_no_prompt_prefix_belongs_to_two_capabilities_of_one_envelope() -> None:
    for envelope in capability_budget.ENVELOPES:
        prefixes = [(c.key, p) for c in CAPABILITIES if c.envelope == envelope for p in c.prompts]
        for key, p in prefixes:
            others = [k for k, q in prefixes if k != key and (q.startswith(p) or p.startswith(q))]
            assert not others, f"{key}'s {p} overlaps {others}"


def test_a_capability_is_looked_up_by_its_key() -> None:
    chronicle = get("chronicle_v4")
    assert chronicle is not None and (chronicle.piece, chronicle.envelope, chronicle.monthly_usd) == ("AD-F02", "production", D("14.00"))
    assert get("replay_regression") is not None and get("nothing") is None


def test_a_call_counts_only_against_a_capability_of_its_own_envelope() -> None:
    assert capability_of("lab", "battery-v4", "lab_battery") == "battery_v4"
    assert capability_of("production", "battery-v4", "pick_review") is None, "production's money is not the LAB's battery"
    assert capability_of("lab", "battery-v3", "lab_battery") is None, "the old battery is not a new capability"
    assert capability_of("lab", "replay-bank-v1", None) == "replay_regression"
    assert capability_of("production", "chronicle-v4-es", "user_narrative") == "chronicle_v4"
    assert capability_of("production", "chronicle-review-v1", None) is None
    assert capability_of("exa", None, "web_search") is None, "a capability not built yet has nothing to find"


def test_a_capabilitys_spend_is_the_sum_of_its_rows_and_zero_without_calls() -> None:
    rows = [Row("lab", "replay-bank-v1", None, D("1.20")), Row("lab", "replay-bank-v2", None, D("0.30")),
            Row("production", "review-v2", "pick_review", D("40")), Row("production", "chronicle-v4", "user_narrative", D("0.50"))]
    out = spend(rows)
    assert out["replay_regression"] == D("1.50") and out["chronicle_v4"] == D("0.50")
    assert out["news_summaries"] == 0 and set(out) == {c.key for c in CAPABILITIES}


# ── the warnings at 80 and 95 % ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("spent", "expected"), [
    ("147.99", None), ("148.00", 80), ("175.74", 80), ("175.75", 95), ("185.00", 95), ("300", 95), ("0", None)])
def test_the_warning_of_an_envelope_at_its_edges(spent: str, expected: int | None) -> None:
    assert level(D(spent), D(185)) == expected  # 80 % of 185 is 148.00; 95 % is 175.75


def test_a_cap_of_zero_warns_of_nothing() -> None:
    assert level(D(5), D(0)) is None and budget_v3.crossed(D(5), D(0), budget_v3.ENVELOPE_ALERTS) == []


def test_the_report_of_a_capability_is_its_cap_its_spend_and_its_warning() -> None:
    rows = [Row("lab", "replay-bank-v1", None, D("2.35"))]  # 80.2 % of 2.93
    item = {c["key"]: c for c in report(rows)}["replay_regression"]
    assert item == {"key": "replay_regression", "piece": "AD-K04", "envelope": "lab", "monthly_usd": "2.93", "spent_usd": "2.35",
                    "share": 0.802, "alert": 80, "tagged": True, "prompts": ["replay-bank-"], "purposes": [],
                    "source": item["source"]}
    assert {c["key"]: c for c in report(rows)}["news_summaries"]["tagged"] is False


# ── the envelopes of decision 12 ───────────────────────────────────────────────────────────────────────────────


def test_production_is_intelligences_claude_and_the_readers_chronicle() -> None:
    prod, exa, lab = budget_v3.figures_of(intelligence=D("144"), readers=D("4"), lab=D("10"), exa=D("33.25"), settings=settings())
    assert (prod.scope, prod.spent, prod.alert) == ("production", D(148), 80), "144 + 4 = 148, 80 % of 185"
    assert prod.parts == {"intelligence": D(144), "readers": D(4)}
    assert (exa.scope, exa.alert, lab.scope, lab.alert) == ("exa", 95, "lab", None)
    assert prod.as_json() == {"scope": "production", "spent_usd": "148.0000", "budget_usd": "185", "decided_usd": "185",
                              "matches_decision": True, "share": 0.8, "alert": 80,
                              "parts_usd": {"intelligence": "144.0000", "readers": "4.0000"}}


def test_an_envelope_configured_apart_from_decision_12_says_so() -> None:
    lab = budget_v3.figures_of(intelligence=D(0), readers=D(0), lab=D(0), exa=D(0), settings=settings(lab_monthly_budget=D(15)))[2]
    assert lab.as_json()["matches_decision"] is False and lab.as_json()["decided_usd"] == "55"


def test_the_warnings_are_each_threshold_reached_by_an_envelope_or_a_capability() -> None:
    figures = budget_v3.figures_of(intelligence=D(170), readers=D("6"), lab=D(0), exa=D(0), settings=settings())
    caps = report([Row("lab", "battery-v4", None, D("2.40"))])  # 80 % of 3
    found = {(w.kind, w.name, w.threshold) for w in budget_v3.warnings_of(date(2032, 8, 1), figures, caps)}
    assert found == {("envelope", "production", 80), ("envelope", "production", 95), ("capability", "battery_v4", 80)}


def test_each_warning_is_logged_once_per_process_and_month(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(envelopes_readers, "_LOGGED", set())
    monkeypatch.setattr(envelopes_readers.log, "disabled", False)
    caplog.set_level(logging.WARNING, logger="fbi.ai.envelopes")
    figures = budget_v3.figures_of(intelligence=D(150), readers=D(0), lab=D(0), exa=D(0), settings=settings())
    august = budget_v3.warnings_of(date(2032, 8, 1), figures, report([]))
    first = envelopes_readers.log_warnings(august)
    assert [(w.name, w.threshold) for w in first] == [("production", 80)]
    assert [r.getMessage() for r in caplog.records] == [
        "IA-058 envelope production reached 80 % of its month: US$150.0000 of US$185 (2032-08-01)"]
    assert envelopes_readers.log_warnings(august) == [], "once per process and month"
    september = budget_v3.warnings_of(date(2032, 9, 1), figures, report([]))
    assert len(envelopes_readers.log_warnings(september)) == 1, "a new month warns again"


# ── the joint ceiling, kept ────────────────────────────────────────────────────────────────────────────────────


def test_the_joint_ceiling_still_cuts_the_lab_unless_the_prepared_switch_says_independent() -> None:
    assert budget_v3.lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(173)) == 17, "as today"
    assert budget_v3.lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(173), independent=True) == 55
    assert budget_v3.lab_allocation(envelope=D(55), joint_ceiling=D(190), projected_production=D(200), independent=True) == 55
    assert budget_v3.lab_allocation(envelope=D(0), joint_ceiling=D(190), projected_production=D(0), independent=True) == 0
    assert budget_v3.JOINT_CEILING_PENDING is True


def test_the_switch_is_off_by_default_and_only_a_clear_word_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def env_of(**env: str) -> AiSettings:
        monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
        return AiSettings.from_env()

    assert AiSettings().envelopes_independent is False and env_of().envelopes_independent is False
    assert env_of(FBI_AI_ENVELOPES_INDEPENDENT="on").envelopes_independent is True
    assert env_of(FBI_AI_ENVELOPES_INDEPENDENT="yes please").envelopes_independent is False
    assert env_of().joint_ceiling == D(190), "the ceiling itself is not changed"
    assert env_of().public()["envelopes_independent"] is False


def test_the_panel_says_the_joint_ceiling_applies_pending_the_owner() -> None:
    lab = budget_v3.LabDay(True, D(17), D(5), D(12), D("0.5"), "ok")
    out = costs_v3.joint_ceiling_json(settings=settings(), lab=lab, projected_at_dawn=D(173))
    assert out == {"usd": "190", "applies": True, "pending_owner": True,
                   "note": "techo conjunto 190 vigente; pendiente de confirmación del dueño", "switch": "FBI_AI_ENVELOPES_INDEPENDENT",
                   "independent": False, "lab_allocation_usd": "17.0000", "lab_allocation_joint_usd": "17.0000",
                   "lab_allocation_independent_usd": "55.0000", "envelopes_sum_usd": "240"}


# ── Exa's price ────────────────────────────────────────────────────────────────────────────────────────────────


def test_exas_price_stays_the_codes_and_the_published_one_is_shown_unverified() -> None:
    assert pricing.SEARCH_PRICES["exa"] == D(15) and pricing.SEARCH_PRICES["exa"] / 1000 == budget_v3.EXA_SEARCH_USD
    assert D(7) == pricing.EXA_PUBLISHED_PER_K and pricing.EXA_PRICE_VERIFIED_BY_INVOICE is False
    out = costs_v3.exa_price_json(940, D("14.10"))  # the month in production on 16 Nov 2026
    assert (out["code_usd_per_search"], out["published_usd_per_search"]) == ("0.015", "0.007")
    assert (out["month_at_code_usd"], out["month_at_published_usd"], out["difference_usd"]) == ("14.1000", "6.5800", "7.5200")
    assert out["status"] == "sin verificar hasta la factura" and out["verified_by_invoice"] is False


def test_the_alerts_of_the_panel_never_notify_a_reader() -> None:
    figures = budget_v3.figures_of(intelligence=D(0), readers=D(0), lab=D(50), exa=D(0), settings=settings())
    out = costs_v3.alerts_json(figures, report([]))
    assert out["thresholds"] == [80, 95] and out["notifies_readers"] is False and out["capabilities"] == []
    assert [e["alert"] for e in out["envelopes"]] == [None, None, 80]

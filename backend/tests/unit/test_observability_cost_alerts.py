"""The cost alerts (``fbi.observability.cost_alerts``, cost-alerts-v1) without a database, and ``scripts.ia_alerts``' exit status: each rule
on crafted data, the minimums, and no alert on healthy data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from scripts import ia_alerts

from fbi.ai import eval_bench
from fbi.ai.config import AiSettings
from fbi.observability import cost_alerts as ca
from fbi.observability import drift as dr

D = Decimal
DAY = date(2026, 11, 6)


def steady(days: int = 14, cost: str = "10", matches: int = 100) -> dict[date, tuple[Decimal, int]]:
    return {DAY - timedelta(days=k): (D(cost), matches) for k in range(1, days + 1)}


# ── cost per match ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_day_like_its_fortnight_is_ok() -> None:
    f = ca.cost_jump("cost_per_match_production", "production", day=DAY, today=(D("12"), 100), history=steady())
    assert f.status == ca.OK and f.evidence["baseline_median_usd"] == "0.100000" and f.evidence["baseline_days"] == 14


def test_more_than_twice_the_median_is_an_alert_and_exactly_twice_is_not() -> None:
    hist = steady()
    assert ca.cost_jump("r", "s", day=DAY, today=(D("20"), 100), history=hist).status == ca.OK
    f = ca.cost_jump("r", "s", day=DAY, today=(D("20.01"), 100), history=hist)
    assert f.status == ca.ALERT and "2 x the 14-day median" in f.summary and f.evidence["threshold_usd"] == "0.200000"


def test_the_median_resists_one_expensive_day_of_the_baseline() -> None:
    hist = steady() | {DAY - timedelta(days=3): (D("500"), 100)}
    assert ca.cost_jump("r", "s", day=DAY, today=(D("15"), 100), history=hist).status == ca.OK


def test_the_baseline_is_the_fourteen_days_before_and_needs_seven_with_matches() -> None:
    hist = steady(days=6) | {DAY - timedelta(days=15): (D("1"), 100), DAY - timedelta(days=7): (D("3"), 0)}
    f = ca.cost_jump("r", "s", day=DAY, today=(D("99"), 100), history=hist)
    assert f.status == ca.INSUFFICIENT and f.evidence["baseline_days"] == 6 and "7 needed" in f.summary
    assert ca.cost_jump("r", "s", day=DAY, today=(D("99"), 100), history=steady(days=7)).status == ca.ALERT


def test_a_day_with_too_few_matches_is_insufficient() -> None:
    f = ca.cost_jump("r", "s", day=DAY, today=(D("9"), ca.MIN_DAY_MATCHES - 1), history=steady())
    assert f.status == ca.INSUFFICIENT and "matches on the day" in f.summary


def test_each_agent_version_is_judged_against_its_own_history_with_its_figures() -> None:
    days = [ca.AgentDay("match", "match-v3", DAY - timedelta(days=k), 40, D("2"), 20) for k in range(1, 15)]
    days += [ca.AgentDay("match", "match-v3", DAY, 50, D("9"), 20)]
    days += [ca.AgentDay("council", "council-v1", DAY - timedelta(days=k), 10, D("5"), 10) for k in range(1, 15)]
    days += [ca.AgentDay("council", "council-v1", DAY, 10, D("5"), 10)]
    days += [ca.AgentDay("stats", "stats-v1", DAY - timedelta(days=1), 3, D("1"), 3)]  # did not run today: no finding
    out = {f.subject: f for f in ca.agent_findings(days, day=DAY, useful={("match", "match-v3"): (30, D("1.2"))})}
    assert set(out) == {"match match-v3", "council council-v1"}
    m = out["match match-v3"]
    assert m.status == ca.ALERT and m.evidence["today"]["cost_per_run_usd"] == "0.180000"
    assert m.evidence["window_useful_signals"] == 30 and m.evidence["window_cost_per_useful_signal_usd"] == "1.200000"
    assert out["council council-v1"].status == ca.OK and out["council council-v1"].evidence["window_cost_per_useful_signal_usd"] is None


def test_agent_days_carry_the_bench_s_cost_and_runs_and_the_matches() -> None:
    cell = eval_bench.Cell("match", "match-v3", DAY, runs=12, cost=D("0.6"))
    (a,) = ca.agent_days([cell], {("match", "match-v3", DAY): 4})
    assert (a.runs, a.cost, a.matches) == (12, D("0.6"), 4) and a.as_json()["cost_per_match_usd"] == "0.150000"
    assert ca.agent_days([cell], {})[0].as_json()["cost_per_match_usd"] is None


# ── cache ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def cache(*hits: float, total: int = 100_000) -> dict[date, tuple[int, int]]:
    return {DAY - timedelta(days=len(hits) - 1 - i): (int(total * h), total - int(total * h)) for i, h in enumerate(hits)}


def test_three_days_under_forty_percent_is_an_alert() -> None:
    f = ca.cache_streak(day=DAY, per_day=cache(0.39, 0.2, 0.1))
    assert f.status == ca.ALERT and f.evidence["days"][DAY.isoformat()]["hit_rate_pct"] == "10.00"


def test_two_low_days_or_a_healthy_cache_is_not() -> None:
    assert ca.cache_streak(day=DAY, per_day=cache(0.5, 0.2, 0.1)).status == ca.OK
    assert ca.cache_streak(day=DAY, per_day=cache(0.1, 0.2, 0.4)).status == ca.OK
    assert ca.cache_streak(day=DAY, per_day=cache(0.6, 0.7, 0.8)).status == ca.OK
    assert ca.cache_streak(day=DAY, per_day=cache(0.9, 0.1, 0.1, 0.1)).status == ca.ALERT  # only the last three count


def test_a_day_without_enough_cacheable_input_measured_nothing() -> None:
    per_day = cache(0.1, 0.1, 0.1) | {DAY - timedelta(days=1): (10, ca.MIN_CACHEABLE_TOKENS - 11)}
    f = ca.cache_streak(day=DAY, per_day=per_day)
    assert f.status == ca.INSUFFICIENT and "2 of the last 3 days" in f.summary
    assert ca.cache_streak(day=DAY, per_day={}).status == ca.INSUFFICIENT


# ── envelopes ───────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("projected", "status"), [("150", ca.OK), ("175.74", ca.OK), ("175.75", ca.WATCH), ("184.99", ca.WATCH),
                                                   ("185", ca.ALERT), ("300", ca.ALERT)])
def test_the_projection_against_the_envelope(projected: str, status: str) -> None:
    f = ca.envelope("production month", projected=D(projected), cap=D("185"), evidence={})
    assert f.status == status and f.evidence["thresholds_pct"] == [95, 100]


def test_no_envelope_is_insufficient_not_an_alert() -> None:
    assert ca.envelope("LAB month", projected=D("3"), cap=D(0), evidence={}).status == ca.INSUFFICIENT


def test_the_lab_projection_adds_a_typical_day_for_each_day_left() -> None:
    assert ca.lab_projection(spent_month=D("5"), typical_day=D("0.5"), day=date(2026, 11, 6)) == D("17")
    assert ca.lab_projection(spent_month=D("5"), typical_day=D("0.5"), day=date(2026, 11, 30)) == D("5")


def test_the_report_lists_only_alerts_worst_first() -> None:
    fs = (ca.Finding("a", "x", ca.OK, ""), ca.Finding("b", "y", ca.WATCH, ""), ca.Finding("c", "z", ca.ALERT, ""),
          ca.Finding("d", "w", ca.INSUFFICIENT, ""))
    rep = ca.CostReport(DAY, datetime(2026, 11, 7, 5, tzinfo=UTC), fs, ())
    assert [a["rule"] for a in rep.alerts()] == ["c", "b"] and rep.alerts()[0]["version"] == "cost-alerts-v1"


# ── the script ──────────────────────────────────────────────────────────────────────────────────────────────────────


def stub(monkeypatch: pytest.MonkeyPatch, *, drift_cells: tuple[Any, ...] = (), findings: tuple[ca.Finding, ...] = ()) -> None:
    monkeypatch.setattr(dr, "report", lambda conn, *, day, at: dr.DriftReport(day, at, drift_cells, ()))
    monkeypatch.setattr(ca, "report", lambda conn, *, day, at, settings: ca.CostReport(day, at, findings, ()))


NOW = datetime(2026, 11, 7, 15, tzinfo=UTC)


def test_the_script_exits_0_without_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, findings=(ca.Finding("cache_hit_low", "p", ca.INSUFFICIENT, "few"),))
    doc, code = ia_alerts.run(object(), day=DAY, now=NOW, settings=AiSettings())  # type: ignore[arg-type]
    assert code == ia_alerts.NONE and doc["alerts"] == [] and doc["complete_day"] is True and doc["insufficient"] == 1
    assert "Sin alertas." in doc["lines"] and doc["report_only"] is True


def test_the_script_exits_1_with_alerts_and_their_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, findings=(ca.Finding("cache_hit_low", "p", ca.ALERT, "low", {"days": {}}),))
    doc, code = ia_alerts.run(object(), day=DAY, now=NOW, settings=AiSettings())  # type: ignore[arg-type]
    assert code == ia_alerts.ALERTS and doc["alerts"][0]["evidence"] == {"days": {}}
    assert any(line.startswith("[ALERT] cache_hit_low") for line in doc["lines"])


def test_the_script_reads_an_unfinished_day_as_of_now_and_refuses_a_future_one(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch)
    doc, _ = ia_alerts.run(object(), day=date(2026, 11, 7), now=NOW, settings=AiSettings())  # type: ignore[arg-type]
    assert doc["complete_day"] is False and doc["as_of"] == NOW.isoformat() and "DÍA SIN TERMINAR" in doc["lines"][0]
    doc, code = ia_alerts.run(object(), day=date(2026, 11, 9), now=NOW, settings=AiSettings())  # type: ignore[arg-type]
    assert code == ia_alerts.CANNOT and "not started" in doc["error"]


def test_the_script_refuses_a_day_that_is_not_one() -> None:
    with pytest.raises(SystemExit) as exc:
        ia_alerts.main(["day", "--day", "2026-13-01"])
    assert exc.value.code == 2

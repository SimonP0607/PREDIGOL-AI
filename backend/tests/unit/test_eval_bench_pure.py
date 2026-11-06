"""The aggregations of the agent evaluation bench (``fbi.ai.eval_bench``, ``eval-bench-v1``) that need no database. The bench on a built world is
``tests/integration/test_gate_b_bench.py``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fbi.ai import eval_bench as b

D = Decimal
NOW = datetime(2032, 9, 30, 17, 0, tzinfo=UTC)
D1, D2 = date(2032, 9, 20), date(2032, 9, 21)


@pytest.mark.parametrize(("values", "q", "want"), [([], 0.5, None), ([7], 0.95, 7), ([1, 2, 3, 4], 0.5, 2), ([5, 1, 3, 2, 4], 0.5, 3),
                                                   (list(range(1, 101)), 0.95, 95), (list(range(1, 21)), 0.95, 19)])
def test_the_nearest_rank_percentile(values: list[int], q: float, want: int | None) -> None:
    assert b.percentile(values, q) == want


def cell(day: date, **kw: object) -> b.Cell:
    base: dict[str, object] = {"agent": "match", "version": "match-v2", "day": day, "runs": 10, "first_attempts": 9, "first_valid": 8,
                               "retries": 1, "cost": D("0.10"), "input_tokens": 1000, "output_tokens": 100, "cached_tokens": 600,
                               "cache_write_tokens": 50, "thinking_tokens": 0, "latencies": (100, 200)}
    return b.Cell(**(base | kw))  # type: ignore[arg-type]


def test_the_window_sums_the_days_and_keeps_every_latency() -> None:
    c1 = replace(cell(D1), by_status={"ok": 8, "invalid": 1, "skipped": 1}, invalid_by_code={"bad_ref": 1})
    c2 = replace(cell(D2, latencies=(300,)), by_status={"ok": 10}, invalid_by_code={})
    t = b.combine([c1, c2], agent="match", version="match-v2")
    assert (t.runs, t.first_attempts, t.first_valid, t.retries, t.cost, t.input_tokens) == (20, 18, 16, 2, D("0.20"), 2000)
    assert t.latencies == (100, 200, 300) and t.by_status == {"ok": 18, "invalid": 1, "skipped": 1}
    assert t.valid_first_attempt == D("0.8889") and t.day is None
    j = t.as_json(latency=True)
    assert j["latency_ms"] == {"n": 3, "p50": 200, "p95": 300} and "day" not in j
    assert "latency_ms" not in t.as_json(latency=False)


def test_the_statuses_and_the_codes_go_to_their_day() -> None:
    cells = b.with_statuses([cell(D1), cell(D2)], [("match", "match-v2", D1, "ok", None, 7), ("match", "match-v2", D1, "invalid", "a,b", 2),
                                                   ("match", "match-v2", D2, "timeout", None, 1), ("council", "council-v1", D1, "ok", None, 3)])
    assert cells[0].by_status == {"ok": 7, "invalid": 2} and cells[0].invalid_by_code == {"a": 2, "b": 2}
    assert cells[1].by_status == {"timeout": 1} and cells[1].invalid_by_code == {}


def test_stability_counts_the_repeats_that_gave_the_most_frequent_output() -> None:
    s = b.stability({"i1": {"h1": 3, "h2": 1}, "i2": {"h1": 2}, "i3": {"h9": 1}})
    assert (s.inputs, s.repeats, s.same) == (2, 4, 3) and s.rate == D("0.75")
    assert b.stability({"i1": {"h": 1}}).rate is None


def test_a_useful_signal_is_a_hit_that_is_not_the_verdict() -> None:
    s = b.signals([(False, "HIT", 6), (False, "MISS", 2), (False, "VOID", 5), (True, "HIT", 1), (True, "MISS", 3)])
    assert (s.useful, s.precision, s.verdict_precision) == (6, D("0.75"), D("0.25"))
    assert s.cost_per_useful(D("0.30")) == D("0.05")
    assert b.signals([(True, "HIT", 4)]).cost_per_useful(D("1")) is None


def test_what_the_rows_cannot_support_is_omitted_and_said() -> None:
    a = b.AgentBench("match", "match-v2", (cell(D1, latencies=()),), b.combine([cell(D1, latencies=())], agent="match", version="match-v2"))
    rep = b.BenchReport(D1, D1, None, NOW, (a,), None)
    doc = rep.as_json()
    assert doc["method"] == "eval-bench-v1" and doc["complete_days_only"] is True
    assert {o.split(":")[0] for o in doc["omitted"]} == {"latency", "coverage", "stability", "attribution"}
    agent = doc["agents"][0]
    assert "latency_ms" not in agent["totals"] and "coverage" not in agent and "stability" not in agent and "attribution" not in agent
    assert rep.lines()[0].startswith("BANCO DE EVALUACIÓN · eval-bench-v1")


def test_coverage_stability_and_attribution_appear_when_they_exist() -> None:
    a = b.AgentBench("match", "match-v2", (cell(D1),), b.combine([cell(D1)], agent="match", version="match-v2"), coverage=(3, 4),
                     stability=b.Stability(1, 2, 2), signals=b.signals([(False, "HIT", 2)]))
    doc = b.BenchReport(D1, D1, "match", NOW, (a,), 4).as_json()
    agent = doc["agents"][0]
    assert agent["coverage"]["rate_pct"] == "75.00" and agent["stability"]["rate_pct"] == "100.00"
    assert agent["attribution"]["cost_per_useful_signal_usd"] == "0.050000" and doc["omitted"] == []

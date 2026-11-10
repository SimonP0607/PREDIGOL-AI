"""The intervals beside the rates of the reports (IA-027): known values, the edges and what a ``Proportion`` says - and that it decides nothing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.ai.intervals import Proportion, exact, wilson


def close(a: float, b: float, tol: float = 5e-4) -> bool:
    return abs(a - b) <= tol


def test_wilson_matches_the_textbook_values() -> None:
    lo, hi = wilson(4, 44) or (0.0, 0.0)
    assert close(lo, 0.0359) and close(hi, 0.2116)
    lo, hi = wilson(9, 443) or (0.0, 0.0)
    assert close(lo, 0.0107) and close(hi, 0.0381)
    lo, hi = wilson(0, 90) or (1.0, 1.0)
    assert lo == 0.0 and close(hi, 0.0409)
    lo, hi = wilson(90, 90) or (0.0, 0.0)
    assert close(lo, 0.9591) and hi == 1.0


def test_clopper_pearson_matches_the_binomial() -> None:
    lo, hi = exact(0, 90) or (1.0, 1.0)
    assert lo == 0.0 and close(hi, 1 - 0.025 ** (1 / 90))
    lo, hi = exact(1, 10) or (0.0, 0.0)
    assert close(lo, 0.00253) and close(hi, 0.44502)
    lo, hi = exact(10, 10) or (0.0, 0.0)
    assert close(lo, 0.025 ** (1 / 10)) and hi == 1.0


def test_inside_the_range_the_exact_interval_is_the_wider_one() -> None:
    for k, n in ((4, 44), (9, 116), (87, 127)):
        w, e = wilson(k, n), exact(k, n)
        assert w is not None and e is not None and e[0] <= w[0] and e[1] >= w[1], (k, n, w, e)


def test_no_cases_no_interval_and_impossible_counts_are_refused() -> None:
    assert wilson(0, 0) is None and exact(0, 0) is None
    for k, n in ((-1, 3), (4, 3), (0, -1)):
        with pytest.raises(ValueError):
            wilson(k, n)
        with pytest.raises(ValueError):
            Proportion(k, n)


def test_a_proportion_places_its_interval_against_the_threshold_and_decides_nothing() -> None:
    three = Decimal("0.03")
    assert Proportion(9, 116, three).relation == "above"           # match-v4 on 9 Nov: 4.1-14.1 %, wholly above 3 %
    assert Proportion(9, 443, three).relation == "straddles"       # the Council: 2.0 % but up to 3.8 %
    assert Proportion(0, 400, three).relation == "below"
    assert Proportion(87, 127, Decimal("0.95"), kind="min").relation == "below"
    assert Proportion(990, 1000, Decimal("0.95"), kind="min").relation == "above"
    assert Proportion(3, 10).relation == "no_threshold" and Proportion(0, 0, three).relation == "no_cases"
    j = Proportion(9, 116, three).as_json()
    assert j["cases"] == 116 and j["counted"] == 9 and j["others"] == 107 and j["pct"] == "7.8"
    assert j["ci95_wilson_pct"] == ["4.1", "14.1"] and j["threshold_pct"] == "3.0" and j["decides"] is False


def test_the_line_of_a_report() -> None:
    assert Proportion(9, 116, Decimal("0.03")).text() == "9/116 · 7.8 % · IC95 4.1-14.1 % · umbral ≤ 3.0 % · el intervalo queda por encima"
    assert Proportion(0, 0).text() == "0 casos"


def test_the_reports_of_gate_b_carry_the_interval_and_keep_their_verdicts() -> None:
    from fbi.ai import gate_b as g

    tally = g.AgentTally("stats", "stats-v3", {"ok": 40, "invalid": 4}, {"schema": 4})
    j = tally.as_json()
    assert j["interval"]["cases"] == 44 and j["interval"]["counted"] == 4 and j["interval"]["interval_vs_threshold"] == "above"
    check = g.judge_invalid([tally])
    assert check.verdict == g.FAIL, "the verdict is the rate's against 3 %, as before: the interval only informs"
    lines = g.evidence_lines(check)
    assert lines == ["stats stats-v3: 4/44 · 9.1 % · IC95 3.6-21.2 % · umbral ≤ 3.0 % · resultado del check: NO PASA"]
    att = g.judge_attribution(127, 87, [7643])
    assert att.verdict == g.FAIL and att.detail["interval"]["ci95_wilson_pct"] == ["60.0", "75.9"]
    assert g.evidence_lines(att) == ["atribuidos: 87/127 · 68.5 % · IC95 60.0-75.9 % · umbral ≥ 95.0 % · resultado del check: NO PASA"]

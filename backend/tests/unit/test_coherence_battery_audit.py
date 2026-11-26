"""The audit links every violation of the coherence battery to the seal of the figures it compares (RP-2.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fbi.forecasting import battery_audit
from fbi.forecasting import single_figure as sf
from fbi.forecasting.market_view import CALIBRATED

D = Decimal
CUT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def fig(market: str, sel: str, line: str, p: float, push: float = 0.0, hash_: str = "abc") -> sf.Figure:
    return sf.Figure(7, market, sel, sf.line_of(line), p, push, None, None, p, "poisson", 3, CUT, CALIBRATED, "champion", 9, CUT,
                     sf.SOURCE_STORED, hash_)


def figure_set(draw: float) -> sf.FigureSet:
    figs = [fig("1X2", "Home", "0", 0.45, hash_="h1"), fig("1X2", "Draw", "0", draw, hash_="h1"), fig("1X2", "Away", "0", 0.30, hash_="h1")]
    return sf.FigureSet(7, {f.key: f for f in figs})


def test_a_coherent_match_is_publishable_and_has_no_violation() -> None:
    a = battery_audit.audit_match(figure_set(0.25))
    assert a["publishable"] and a["violations"] == [] and a["fixture_id"] == 7 and a["figures"] == 3


def test_a_violation_is_linked_to_the_seal_of_each_figure_it_compares() -> None:
    a = battery_audit.audit_match(figure_set(0.40))
    assert not a["publishable"]
    [v] = a["violations"]
    assert v["test"] == 2 and v["rule"] == "results_add_up" and v["gap"] > 0
    assert {f["selection"] for f in v["figures"]} == {"Home", "Draw", "Away"}
    one = v["figures"][0]
    assert one["set_hash"] == "h1" and one["model_version_id"] == 3 and one["calibration"] == CALIBRATED and one["source"] == sf.SOURCE_STORED
    assert len(one["reading_id"]) == 12


def test_the_summary_counts_matches_violations_and_the_tests_that_could_not_run() -> None:
    s = battery_audit.summary([battery_audit.audit_match(figure_set(0.25)), battery_audit.audit_match(figure_set(0.40))])
    assert s["matches"] == 2 and s["not_publishable"] == 1 and s["figures"] == 6
    assert s["tests"]["2"] == {"name": "resultados exhaustivos suman uno", "tolerance": 0.000001, "comparisons": 2, "violations": 1, "ran": True}
    assert s["tests"]["6"]["ran"] is False and s["tests"]["3"]["tolerance"] == "strict"

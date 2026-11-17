"""AD-B04 (IA-074): one score matrix per match, every goals market from it, coherent by construction (``matrix-v1``).

The proofs: the seven rows the models store today come out identical; every complete market adds up to one and every ladder is monotone
for any expected goals a league can produce; the full-time markets are the joint simulator's to the last bit when both read the same
distribution; a Dixon-Coles rho the model would refuse is refused; and the shadow check finds an incoherence planted in published numbers.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import numpy as np
import pytest

from fbi.forecasting import score_matrix as sm
from fbi.models.goals import InvalidCorrectionError
from fbi.models.lines import LineOutcome
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.simulator import joint as jt
from fbi.simulator.markets import Selection, price

CASES = [(1.55, 1.20, None), (1.55, 1.20, -0.04), (0.35, 0.30, None), (0.6, 2.8, 0.05), (3.4, 0.4, -0.08), (1.0, 1.0, 0.0),
         (2.1, 1.9, -0.12)]


def params(lh: float, la: float, rho: float | None) -> sm.Params:
    return sm.Params(lh, la, rho, "dixon_coles" if rho is not None else "poisson", 1)


@pytest.mark.parametrize(("lh", "la", "rho"), CASES)
def test_the_seven_stored_rows_come_out_identical(lh: float, la: float, rho: float | None) -> None:
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    today = from_matrix(m, lh, la).as_rows()
    mine = sm.market_rows(sm.derive(sm.build(params(lh, la, rho))))
    assert [round(x, 6) for x in mine] == [round(x, 6) for x in today]
    assert max(abs(a - b) for a, b in zip(mine, today, strict=True)) < 1e-12


@pytest.mark.parametrize(("lh", "la", "rho"), CASES)
def test_every_market_is_coherent_by_construction(lh: float, la: float, rho: float | None) -> None:
    prices = sm.derive(sm.build(params(lh, la, rho)))
    assert sm.coherence(prices) == []


def test_a_grid_of_expected_goals_is_coherent_everywhere() -> None:
    for lh, la in itertools.product((0.2, 0.7, 1.3, 2.0, 3.0, 4.2), repeat=2):
        assert sm.coherence(sm.derive(sm.build(sm.Params(lh, la)))) == [], (lh, la)


def test_the_menu_is_the_one_the_plan_names() -> None:
    assert len(sm.OU_LINES) == 26 and sm.OU_LINES[0] == Decimal("0.5") and sm.OU_LINES[-1] == Decimal("6.75")
    assert len(sm.AH_LINES) == 45 and sm.AH_LINES[0] == Decimal("-5.5") and sm.AH_LINES[-1] == Decimal("5.5")
    prices = sm.derive(sm.build(sm.Params(1.4, 1.1)))
    markets = {k[0] for k in prices}
    assert markets == {"1X2", "DC", "DNB", "OU", "BTTS", "OU_HOME", "OU_AWAY", "AH", "EH"}
    assert sum(1 for k in prices if k[0] == "AH") == 90, "45 lines, each a complete pair"
    assert ("AH", "Away", Decimal("0")) in prices and ("AH", "Away", Decimal("-0")) in prices


def test_a_quarter_line_is_half_the_stake_on_each_neighbour() -> None:
    prices = sm.derive(sm.build(sm.Params(1.6, 1.0, -0.05)))
    q, a, b = (prices[("AH", "Home", Decimal(x))] for x in ("-0.25", "0", "-0.5"))
    assert q.win == pytest.approx((a.win + b.win) / 2, abs=1e-15)
    assert q.push == pytest.approx((a.push + b.push) / 2, abs=1e-15)
    o = prices[("OU", "Over", Decimal("2.25"))]
    assert o.push > 0 and o.win + o.push + prices[("OU", "Under", Decimal("2.25"))].win == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize(("lh", "la", "rho"), CASES)
def test_full_time_markets_are_the_simulators_on_the_same_distribution(lh: float, la: float, rho: float | None) -> None:
    joint = jt.build(jt.split_full_time(lh, la), rho=rho, max_goals=6)
    prices = sm.derive(sm.from_array(joint.score_matrix("FT")))
    names = {"OU_HOME": "TT_HOME", "OU_AWAY": "TT_AWAY"}
    checked = 0
    for (market, sel, line), mine in prices.items():
        theirs = price(joint, Selection(names.get(market, market), sel, float(line)))
        assert mine.win == pytest.approx(theirs.win, abs=1e-12), (market, sel, line)
        assert mine.push == pytest.approx(theirs.push, abs=1e-12), (market, sel, line)
        checked += 1
    assert checked == len(prices) > 200


def test_the_models_matrix_and_the_simulators_differ_only_by_their_truncation() -> None:
    lh, la, rho = 1.55, 1.20, -0.04
    joint = jt.build(jt.split_full_time(lh, la), rho=rho)
    mine = sm.derive(sm.build(sm.Params(lh, la, rho)))
    for (market, sel, line), o in mine.items():
        name = {"OU_HOME": "TT_HOME", "OU_AWAY": "TT_AWAY"}.get(market, market)
        assert o.win == pytest.approx(price(joint, Selection(name, sel, float(line))).win, abs=1e-5)


def test_a_rho_the_model_refuses_is_refused_never_clipped() -> None:
    with pytest.raises(InvalidCorrectionError):
        sm.build(sm.Params(3.0, 2.5, 0.9))
    with pytest.raises(ValueError, match="positive"):
        sm.Params(0.0, 1.0)
    with pytest.raises(ValueError, match="finite"):
        sm.Params(1.0, 1.0, float("nan"))


def test_a_matrix_must_be_a_distribution() -> None:
    with pytest.raises(ValueError):
        sm.from_array(np.array([[0.5, -0.1], [0.3, 0.3]]))
    with pytest.raises(ValueError):
        sm.from_array(np.zeros((3, 3)))
    with pytest.raises(ValueError):
        sm.from_array(np.ones((2, 3)))
    built = sm.build(sm.Params(1.5, 1.2))
    assert float(built.p.sum()) == pytest.approx(1.0, abs=1e-12) and 0 < built.truncated_mass < 1e-4


def test_lines_must_be_quarters_and_a_european_handicap_whole() -> None:
    m = sm.build(sm.Params(1.2, 1.2))
    with pytest.raises(ValueError, match=r"multiple of 0\.25"):
        sm.derive(m, ou_lines=[Decimal("2.3")])
    with pytest.raises(ValueError, match="whole number"):
        sm.derive(m, eh_lines=[Decimal("0.5")])


def test_the_shadow_check_finds_what_is_planted() -> None:
    prices = sm.derive(sm.build(sm.Params(1.5, 1.1)))
    h, d, a = (prices[("1X2", s, Decimal(0))].win for s in ("Home", "Draw", "Away"))
    published = [sm.Published("1X2", "Home", Decimal(0), round(h, 6)), sm.Published("1X2", "Draw", Decimal(0), round(d, 6)),
                 sm.Published("1X2", "Away", Decimal(0), round(a, 6)),
                 sm.Published("DC", "1X", Decimal(0), round(h + d, 6) + 0.03),  # calibrated on its own
                 sm.Published("OU", "Over", Decimal("2.5"), 0.50), sm.Published("OU", "Over", Decimal("3.5"), 0.55)]
    rules = {v.rule for v in sm.published_coherence(published, tol=2e-6)}
    assert rules == {"dc_is_1x2_sum", "ladder_monotone"}
    diffs, missing = sm.compare(prices, [*published, sm.Published("CS", "1-0", Decimal(0), 0.1)])
    assert missing == 1 and len(diffs) == len(published)
    assert max(d.abs_diff for d in diffs[:3]) < 1e-6


def test_compare_can_read_a_number_stated_given_settlement() -> None:
    prices = {("AH", "Home", Decimal(0)): LineOutcome(0.4, 0.3)}
    (diff,), _ = sm.compare(prices, [sm.Published("AH", "Home", Decimal("0.00"), 0.57)], conditional=True)
    assert diff.matrix == pytest.approx(0.4 / 0.7)


def test_the_regression_holds_for_every_stored_row_order() -> None:
    assert [(m, s) for m, s, _ in MARKET_ROWS] == [("1X2", "Home"), ("1X2", "Draw"), ("1X2", "Away"), ("OU", "Over"),
                                                   ("OU", "Under"), ("BTTS", "Yes"), ("BTTS", "No")]


def test_the_page_and_decision_versions_named_by_the_command_are_the_real_ones() -> None:
    from scripts import ia_score_matrix

    from fbi.core.decision_versions import DECISION_CORE
    from fbi.forecasting.market_view import VERSION

    assert ia_score_matrix.PAGE_VERSION == VERSION and ia_score_matrix.DECISION_VERSION == DECISION_CORE


def test_the_command_is_read_only() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "scripts" / "ia_score_matrix.py").read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in text
    assert not any(w in text.upper() for w in ("INSERT INTO", "UPDATE ", "DELETE FROM", ".COMMIT("))

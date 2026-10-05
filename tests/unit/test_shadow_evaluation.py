"""Shadow picks are judged by fixture-clustered intervals, closing-line value and calibration - not by ROI alone."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from decimal import Decimal

from scripts.shadow_evaluation import (
    calibration,
    clv,
    edge_reliability,
    ev_at_pinnacle_close,
    evaluate,
    fair_close,
    roi_with_interval,
)

KO = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)


def pick(fixture: int, status: str, profit: str, odds: str = "2.00", close: str | None = "1.90") -> dict:
    return {"fixture_id": fixture, "result_status": status, "profit_units": Decimal(profit), "stake_units": Decimal(1),
            "market_odds": Decimal(odds), "close_same_book": None if close is None else Decimal(close),
            "close_pinnacle": None, "p_calibrated": Decimal("0.55"), "p_market_fair": Decimal("0.50"),
            "market_key": "OU", "selection": "Under", "bookmaker": "Pinnacle", "kickoff_at": KO}


def test_ten_lines_of_one_match_are_one_bet_for_the_interval() -> None:
    one_match = [pick(1, "win", "1") for _ in range(10)] + [pick(2, "loss", "-1") for _ in range(10)]
    r = roi_with_interval(one_match, random.Random(1))
    assert (r["picks"], r["fixtures"], r["roi"]) == (20, 2, 0.0)
    assert r["ci95"][0] <= -0.99 and r["ci95"][1] >= 0.99, "two independent outcomes say almost nothing"


def test_closing_line_value_is_the_price_taken_over_the_close() -> None:
    c = clv([pick(1, "win", "1", odds="2.10", close="2.00"), pick(2, "loss", "-1", odds="1.90", close="2.00")],
            "close_same_book")
    assert c["n"] == 2 and c["mean"] == 0.0 and c["positive_share"] == 0.5
    assert clv([pick(1, "win", "1", close=None)], "close_same_book")["n"] == 0


def test_calibration_counts_decided_bets_only() -> None:
    cal = calibration([pick(1, "win", "1"), pick(2, "loss", "-1"), pick(3, "push", "0")])
    assert cal == {"n": 2, "model_p": 0.55, "market_p": 0.5, "observed": 0.5}


def test_the_report_splits_by_market_band_side_and_bookmaker() -> None:
    out = evaluate([pick(1, "win", "1"), pick(2, "loss", "-1", odds="3.00")])
    assert set(out) >= {"overall", "by_market", "by_odds_band", "by_market_side", "by_bookmaker", "period"}
    assert set(out["by_odds_band"]) == {"2.00-2.49", "2.50-3.49"}


def test_edge_reliability_is_zero_when_the_market_was_right() -> None:
    rows = []
    for i in range(200):  # model says 0.55, market 0.50, and half of them win: the market was right
        rows.append(pick(i, "win" if i % 2 else "loss", "1" if i % 2 else "-1"))
    r = edge_reliability(rows, random.Random(3))
    assert r["n"] == 200 and r["lambda"] == 0.0 and r["ci95"][0] < 0 < r["ci95"][1]


def test_pinnacles_close_is_de_vigged_before_it_judges_a_price() -> None:
    d = Decimal
    book = {("OU", "Over", d("2.5")): 1.95, ("OU", "Under", d("2.5")): 1.95,
            ("AH", "Home", d("-0.5")): 2.00, ("AH", "Away", d("0.5")): 1.90, ("AH", "Away", d("-0.5")): 3.40,
            ("1X2", "Home", d("0")): 2.0, ("1X2", "Draw", d("0")): 3.5}
    assert fair_close(book, "OU", "Over", d("2.5")) == 0.5, "a symmetric two-way book: 50/50 once the margin goes"
    p_home = fair_close(book, "AH", "Home", d("-0.5"))
    assert p_home is not None and abs(p_home - (1 / 2.0) / (1 / 2.0 + 1 / 1.90)) < 1e-12, (
        "Home -0.5 pairs with Away +0.5, not with Away -0.5 (a 79% 'book')")
    assert fair_close(book, "1X2", "Home", d("0")) is None, "an incomplete book is not guessed"
    assert fair_close(book, "DC", "1X", d("0")) is None
    rows = [{**pick(1, "win", "1", odds="2.10"), "line": d("2.5"), "selection": "Over"},
            {**pick(2, "loss", "-1", odds="1.90"), "line": d("2.5"), "selection": "Over"}]
    ev = ev_at_pinnacle_close(rows, {1: book, 2: book}, random.Random(1))
    assert ev["n"] == 2 and ev["fixtures"] == 2 and ev["mean"] == 0.0, "2.10 x 0.5 - 1 = +5%, 1.90 x 0.5 - 1 = -5%"
    assert ev_at_pinnacle_close(rows, {}, random.Random(1))["n"] == 0

"""Shadow picks are judged by fixture-clustered intervals, closing-line value and calibration - not by ROI alone."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from decimal import Decimal

from scripts.shadow_evaluation import (
    calibration,
    clv,
    edge_reliability,
    evaluate,
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

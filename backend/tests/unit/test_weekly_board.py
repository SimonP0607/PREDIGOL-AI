"""PM-12-01: the weekly private board - Murphy's split of the Brier score checked on synthetic forecasts (exact when every forecast of a
bin is the same; a perfectly calibrated forecast has no reliability term, a forecast of the base rate no resolution), the scores of a
source, the paired differences and their word, the provider's percents, the last whole week, the matches all sources share, the
contract reading a board, and the switch (off by default)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from fbi.api.contracts.evaluation_board import MarketBoard
from fbi.coverage import weekly_board as wb
from fbi.models.metrics import brier, log_loss

DAY = date(2026, 11, 9)


def binary(p: list[float], o: list[int]) -> tuple[np.ndarray, np.ndarray]:
    return np.array([[q, 1 - q] for q in p]), np.array([0 if x else 1 for x in o], dtype=np.int64)


def test_the_split_is_exact_with_one_value_per_bin() -> None:
    # 0.2 said 10 times (2 happened), 0.8 said 10 times (6 happened): bins 2 and 8
    p, y = binary([0.2] * 10 + [0.8] * 10, [1] * 2 + [0] * 8 + [1] * 6 + [0] * 4)
    m = wb.murphy(p, y)
    assert m["residual"] == pytest.approx(0, abs=1e-12)
    assert m["brier"] == pytest.approx(brier(p, y))
    assert m["brier"] == pytest.approx(m["reliability"] - m["resolution"] + m["uncertainty"])
    # by hand, for the event «yes» (and the same for «no»): REL = (10·(0.2-0.2)² + 10·(0.8-0.6)²)/20 = 0.02;
    # base rate 0.4: RES = (10·(0.2-0.4)² + 10·(0.6-0.4)²)/20 = 0.04; UNC = 0.4·0.6 = 0.24
    assert m["reliability"] == pytest.approx(2 * 0.02) and m["resolution"] == pytest.approx(2 * 0.04)
    assert m["uncertainty"] == pytest.approx(2 * 0.24)


def test_calibrated_and_climatological_forecasts() -> None:
    p, y = binary([0.25] * 4 + [0.75] * 4, [1, 0, 0, 0, 1, 1, 1, 0])
    assert wb.murphy(p, y)["reliability"] == pytest.approx(0, abs=1e-12)
    q, z = binary([0.5] * 8, [1, 0, 1, 0, 1, 0, 1, 0])
    m = wb.murphy(q, z)
    assert m["resolution"] == pytest.approx(0, abs=1e-12) and m["reliability"] == pytest.approx(0, abs=1e-12)
    assert m["brier"] == pytest.approx(m["uncertainty"]) == pytest.approx(0.5)


def test_the_split_of_a_three_way_market_with_continuous_forecasts() -> None:
    rnd = np.random.default_rng(3)
    p = rnd.dirichlet([2, 1, 1.5], size=400)
    y = np.array([rnd.choice(3, p=row) for row in p], dtype=np.int64)
    m = wb.murphy(p, y)
    assert m["brier"] == pytest.approx(brier(p, y))
    assert m["brier"] == pytest.approx(m["reliability"] - m["resolution"] + m["uncertainty"] + m["residual"])
    assert abs(m["residual"]) < 0.01  # what ten bins cannot see is small


def test_the_scores_of_a_source_and_the_pairs() -> None:
    rnd = np.random.default_rng(5)
    y = rnd.integers(0, 3, size=300).astype(np.int64)
    sharp = np.full((300, 3), 0.15)
    sharp[np.arange(300), y] = 0.7
    flat = np.full((300, 3), 1 / 3)
    days = [DAY + timedelta(days=i % 20) for i in range(300)]
    s = wb.score("modelo", sharp, y, days, draws=50)
    assert s["n"] == 300 and s["days"] == 20
    assert s["log_loss"]["value"] == pytest.approx(log_loss(sharp, y), abs=1e-6)
    assert s["log_loss"]["low"] <= s["log_loss"]["value"] <= s["log_loss"]["high"]
    assert s["reliability"]["low"] is not None and s["resolution"]["value"] > 0
    pairs = {d["metric"]: d for d in wb.paired("modelo", "mercado", sharp, flat, y, days)}
    assert pairs["log_loss"]["verdict"] == "modelo_mejor" and pairs["brier"]["verdict"] == "modelo_mejor"
    worse = {d["metric"]: d for d in wb.paired("modelo", "mercado", flat, sharp, y, days)}
    assert worse["log_loss"]["verdict"] == "modelo_peor"
    few = wb.paired("modelo", "mercado", sharp[:10], flat[:10], y[:10], days[:10])
    assert {d["verdict"] for d in few} == {"insuficiente"}


def test_the_providers_percents_and_the_last_week() -> None:
    assert wb.provider_set(45, 45, 10) == pytest.approx((0.45, 0.45, 0.10))
    assert wb.provider_set(50, 50, 10) == pytest.approx((50 / 110, 50 / 110, 10 / 110))
    assert wb.provider_set(None, 50, 50) is None and wb.provider_set(0, 0, 0) is None
    assert wb.last_week(datetime(2026, 11, 21, 12, tzinfo=UTC)) == (date(2026, 11, 9), date(2026, 11, 15))
    assert wb.last_week(datetime(2026, 11, 16, 6, tzinfo=UTC)) == (date(2026, 11, 9), date(2026, 11, 15))  # still Sunday in Bogotá
    assert wb.last_week(datetime(2026, 11, 16, 12, tzinfo=UTC)) == (date(2026, 11, 9), date(2026, 11, 15))


def test_the_window_scores_the_matches_every_source_shares_and_the_contract_reads_it() -> None:
    ms = []
    for i in range(60):
        y = i % 3
        p = [0.2, 0.2, 0.2]
        p[y] = 0.6
        sources = {"modelo": tuple(p), "mercado": (0.4, 0.3, 0.3)}
        if i % 2:
            sources["proveedor"] = (0.45, 0.45, 0.10)
        ms.append(wb.Match(i, DAY + timedelta(days=i % 7), y, sources))
    w = wb.window("1X2", ms, start=DAY, end=DAY + timedelta(days=6))
    assert w["matches"] == 60 and w["common"] == 30 and w["with_each"] == {"modelo": 60, "mercado": 60, "proveedor": 30}
    assert [s["source"] for s in w["sources"]] == ["modelo", "mercado", "proveedor"] and {s["n"] for s in w["sources"]} == {30}
    assert [(d["b"], d["n"]) for d in w["pairs"]] == [("mercado", 60), ("mercado", 60), ("proveedor", 30), ("proveedor", 30)]
    board = MarketBoard.model_validate({"market": "1X2", "line": 0.0, "week": w, "cumulative": w})
    assert board.week.common == 30 and board.week.sources[0].reliability.value is not None
    assert "from" in board.model_dump(by_alias=True)["week"]


def test_the_switch_is_off_by_default() -> None:
    assert wb.mode({}) == "off" and wb.mode({"FBI_EVALUATION_BOARD": "1"}) == "on"
    from fbi.api import switches

    assert switches.EVALUATION_BOARD == wb.SWITCH

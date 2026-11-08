"""The ROI interval on the Performance page is clustered by match, and withheld below 20 matches."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.api.services.analytics import _clustered_ci


def test_the_interval_grows_with_the_spread_of_match_profits_not_with_the_number_of_picks() -> None:
    # 100 matches, per-match profit sd 3 units, 1,500 units staked: 1.96 * 3 * sqrt(100) / 1500 = 3.92%
    assert _clustered_ci(100, 3.0, Decimal(1500)) == Decimal("3.92")
    # the same profits spread over 15 matches: too few independent outcomes to say anything
    assert _clustered_ci(15, 3.0, Decimal(1500)) is None
    assert _clustered_ci(100, None, Decimal(1500)) is None and _clustered_ci(100, 3.0, None) is None


def test_the_console_may_take_longer_than_the_boards_and_builds_every_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan PICKS, R1: the console answered 500 with a real sample. Only this request lifts the API's ten seconds,
    inside its own transaction, and the full branch (not only the small-sample one) builds its slices."""
    from fbi.api.repositories import analytics as repo
    from fbi.api.services import analytics

    executed: list[str] = []

    class Conn:
        def execute(self, sql: str, *_a: object) -> None:
            executed.append(sql)

    summary = {"settled": 40, "pending": 2, "staked": Decimal(38), "profit": Decimal("-1.50"), "wins": 15,
               "fixtures": 40, "fixture_profit_sd": Decimal("0.9")}
    row = {"dimension": "odds_band", "key": "2: 1.70-2.49", "settled": 20, "staked": Decimal(19),
           "profit": Decimal("1.00"), "fixtures": 20, "fixture_profit_sd": Decimal("1.1"), "wins": 9,
           "mean_odds": Decimal("2.3"), "expected_profit": Decimal("2.85")}
    monkeypatch.setattr(repo, "settled_summary", lambda _c: summary)
    monkeypatch.setattr(repo, "performance_slices", lambda _c: [row])
    env = analytics.performance(Conn())  # type: ignore[arg-type]
    assert executed == [f"SET LOCAL statement_timeout = '{analytics.PERFORMANCE_TIMEOUT}'"]
    assert env.data is not None and env.data.roi_pct == Decimal("-3.95") and env.data.roi_ci95_pct is not None
    (s,) = env.data.slices
    assert s.key == "1.70-2.49" and s.roi_pct == Decimal("5.26") and s.hit_rate == Decimal("45.00")

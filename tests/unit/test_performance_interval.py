"""The ROI interval on the Performance page is clustered by match, and withheld below 20 matches."""

from __future__ import annotations

from decimal import Decimal

from fbi.api.services.analytics import _clustered_ci


def test_the_interval_grows_with_the_spread_of_match_profits_not_with_the_number_of_picks() -> None:
    # 100 matches, per-match profit sd 3 units, 1,500 units staked: 1.96 * 3 * sqrt(100) / 1500 = 3.92%
    assert _clustered_ci(100, 3.0, Decimal(1500)) == Decimal("3.92")
    # the same profits spread over 15 matches: too few independent outcomes to say anything
    assert _clustered_ci(15, 3.0, Decimal(1500)) is None
    assert _clustered_ci(100, None, Decimal(1500)) is None and _clustered_ci(100, 3.0, None) is None

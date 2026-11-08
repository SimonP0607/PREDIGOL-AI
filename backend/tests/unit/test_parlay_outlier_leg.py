"""A user's parlay refuses a leg at an outlier price (plan Cuotas, ola 0, E2; ``fbi.userdata.records.outlier_price``).

The threshold is the one the Cuotas page flags «atípico» and the value gate refuses: a best price more than 25% above its fair
price (best_odds x p_fair - 1). The refusal over HTTP is ``tests/integration/test_records_api.py``.
"""

from __future__ import annotations

from decimal import Decimal

from fbi.api.services import product
from fbi.parlays.engine import GateConfig
from fbi.userdata import records


def test_the_parlay_refuses_exactly_what_the_cuotas_page_flags() -> None:
    assert records.OUTLIER_EDGE == product.OUTLIER_EDGE == GateConfig().max_price_edge == Decimal("0.25")


def test_past_25_percent_above_fair_is_an_outlier_and_25_itself_is_not() -> None:
    def price(odds: str, p_fair: str | None) -> dict[str, object]:
        return {"best_odds": Decimal(odds), "p_fair": None if p_fair is None else Decimal(p_fair)}

    assert records.outlier_price(price("4.00", "0.33")), "+32 %"
    assert not records.outlier_price(price("3.75", "0.33")), "+23.75 %: high, under the limit"
    assert not records.outlier_price(price("2.50", "0.50")), "+25 % exactly: the limit, not past it"
    assert records.outlier_price(price("2.51", "0.50"))
    assert not records.outlier_price(price("9.00", None)), "no fair price: nothing to judge it by"

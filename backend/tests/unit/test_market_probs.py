"""C-14's pieces (plan EA, EA-201) and the rule of what Mi parlay takes (EA-501)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.services.market_probs import history
from fbi.market.eligibility import verdict
from fbi.market.in_force import implied
from fbi.odds.quote_current import CurrentQuote
from fbi.odds.quote_taxonomy import spec_for

AT = datetime(2034, 3, 1, 12, tzinfo=UTC)


def q(book: int, selection: str, odds: str, *, line: str = "0", kind: str = "one_x_two", bet: int = 1,
      family: str = "result", subject: str = "match") -> CurrentQuote:
    return CurrentQuote(bookmaker_id=book, bookmaker=f"Casa {book}", bet_id=bet, family=family, period="FT", subject=subject, kind=kind,
                        has_line=line != "0", market_key="1X2" if bet == 1 else None, provider_name="", selection=selection,
                        line=Decimal(line), odds=Decimal(odds), captured_at=AT, since=AT)


def test_implied_normalises_each_house_and_averages() -> None:
    quotes = [q(1, "Home", "2.0"), q(1, "Draw", "3.0"), q(1, "Away", "6.0"),
              q(2, "Home", "2.5"), q(2, "Draw", "2.5"), q(2, "Away", "5.0")]
    out = implied(quotes)
    p1 = (0.5 / (0.5 + 1 / 3 + 1 / 6)) / 2 + (0.4 / (0.4 + 0.4 + 0.2)) / 2
    assert out[("Home", Decimal("0"))][0] == pytest.approx(p1)
    assert out[("Home", Decimal("0"))][1] == 2


def test_a_house_that_misses_a_selection_is_left_out_of_its_line() -> None:
    quotes = [q(1, "Home", "2.0"), q(1, "Draw", "3.0"), q(1, "Away", "6.0"), q(2, "Home", "1.5")]
    assert implied(quotes)[("Home", Decimal("0"))][1] == 1


def test_an_asian_handicap_pairs_the_away_row_with_the_negated_line() -> None:
    quotes = [q(1, "Home", "1.9", line="-0.5", kind="asian_handicap", bet=4), q(1, "Away", "1.9", line="0.5", kind="asian_handicap", bet=4)]
    out = implied(quotes)
    assert out[("Home", Decimal("-0.5"))][0] == pytest.approx(0.5)
    assert out[("Away", Decimal("0.5"))][0] == pytest.approx(0.5)


def _row(gh: int, ga: int, ch: int | None = 5, ca: int | None = 6) -> dict[str, int | None]:
    return {"goals_ft_home": gh, "goals_ft_away": ga, "corners_ft_home": ch, "corners_ft_away": ca}


def test_history_settles_with_the_rule_of_the_market() -> None:
    home = [_row(2, 1), _row(0, 0), _row(3, 1)]
    away = [_row(1, 2), _row(1, 1)]
    over = q(1, "Over", "1.9", line="2.5", kind="over_under", bet=5, family="goals")
    h = history(home, away, over)
    assert not isinstance(h, Missing) and (h.hits, h.n) == (3, 5) and h.rule_key == "goals_ft@v1"
    corners = q(1, "Over", "1.9", line="10.5", kind="over_under", bet=45, family="corners")
    hc = history([_row(1, 0, None, None), _row(1, 0, 6, 6)], [], corners)
    assert not isinstance(hc, Missing) and (hc.hits, hc.n) == (1, 1), "a match without corners is not counted"


def test_history_of_one_side_reads_only_that_side() -> None:
    home_total = q(1, "Over", "1.9", line="0.5", kind="over_under", bet=16, family="goals", subject="home")
    h = history([_row(1, 0), _row(0, 0)], [_row(5, 5)], home_total)
    assert not isinstance(h, Missing) and (h.hits, h.n) == (1, 2)


@pytest.mark.parametrize(("bet", "line", "books", "state", "switch", "expected"), [
    (1, "0", 1, "evaluable", False, "ok"),
    (4, "-0.25", 5, "evaluable", True, "linea_de_cuarto"),
    (45, "9.5", 5, "en_calibracion", False, "interruptor_apagado"),
    (45, "9.5", 5, "en_calibracion", True, "ok"),
    (45, "9.5", 2, "en_calibracion", True, "menos_de_3_casas"),
    (45, "9.5", 5, "no_ofrecer", True, "no_ofrecer"),
])
def test_what_mi_parlay_takes(bet: int, line: str, books: int, state: str, switch: bool, expected: str) -> None:
    v = verdict(spec_for(bet), line=Decimal(line), books=books, state=state, started=False, switch_on=switch)
    assert v.reason == expected and v.allowed == (expected == "ok")


def test_a_market_without_a_settlement_rule_is_never_taken() -> None:
    v = verdict(spec_for(240), line=Decimal("0.5"), books=8, state="en_calibracion", started=False, switch_on=True)
    assert v.reason == "sin_regla"


def test_nothing_is_taken_once_the_match_started() -> None:
    assert verdict(spec_for(1), line=Decimal(0), books=9, state="evaluable", started=True, switch_on=True).reason == "empezado"


def test_the_service_shows_a_refundable_pair_without_its_refund() -> None:
    """BE-049: a whole goal line's model figures are put on the terms of the implied probability; a quarter line shows none."""
    from fbi.api.contracts.intelligence.base import Probability
    from fbi.api.contracts.intelligence.market_probs import ParlayFlag, SelectionMarksPrivate
    from fbi.api.services.market_probs import _coherent

    def sel(name: str, line: float, p: float | None) -> SelectionMarksPrivate:
        prob = Missing.model_validate({"missing_reason": "sin_datos"}) if p is None else Probability.of(
            p, calibration="sin_calibrar", as_of=AT, origin="forecast-v2", evaluation=Missing.model_validate({"missing_reason": "sin_datos"}),
            evaluation_version=Missing.model_validate({"missing_reason": "sin_datos"}), interval=(max(0, int(p * 100) - 5), min(100, int(p * 100) + 5)))
        return SelectionMarksPrivate(selection=name, line=line, best_odds=1.9, bookmaker="Casa", model=Missing.model_validate(
            {"missing_reason": "sin_datos"}), implied=Missing.model_validate({"missing_reason": "sin_datos"}),
            history=Missing.model_validate({"missing_reason": "sin_datos"}), parlay=ParlayFlag(allowed=False, reason="sin_regla"),
            model_shadow=prob)

    out = _coherent("over_under", [sel("Over", 1.0, 0.792), sel("Under", 1.0, 0.039), sel("Over", 2.25, 0.6), sel("Under", 2.25, 0.3)])
    over = out[0].model_shadow
    assert not isinstance(over, Missing) and over.pct == 95
    assert isinstance(out[2].model_shadow, Missing) and isinstance(out[3].model_shadow, Missing)


def test_a_double_chance_of_a_family_is_read_from_its_outcomes() -> None:
    from fbi.api.services.market_probs import _one_x_two_unit
    from fbi.api.services.market_status import load_catalogue

    cat = load_catalogue()
    corners_dc = cat.for_bet(spec_for(307).bet_id).entry
    unit = _one_x_two_unit(cat, corners_dc.family, corners_dc.period, corners_dc.subject)
    assert unit is not None and cat.status(unit).entry.kind == "one_x_two" and cat.status(unit).entry.family == "corners"

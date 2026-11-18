"""Mi parlay with the markets of the catalogue (plan EA, EA-501 and EA-502): the server takes a leg on any market with a settlement rule,
a price in force of three houses and the switch on - and only then - and settles it by its rule once the match is final. The five
markets of today keep exactly their behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from fbi.market.eligibility import spec_for_key
from fbi.odds.quote_current import CurrentQuote
from fbi.picks import settlement
from fbi.picks.product_settlement import settle_single
from fbi.picks.rule_settlement import NO_DATA_BASIS, settle_by_rule
from fbi.userdata import records

KO = datetime(2034, 5, 1, 20, tzinfo=UTC)
AT = KO - timedelta(hours=5)


def test_a_leg_names_its_market_by_the_catalogues_key() -> None:
    spec = spec_for_key("corners_over_under.FT.match")
    assert spec is not None and spec.bet_id == 45
    assert spec_for_key("corners_double_chance.FT.match").bet_id == 307  # type: ignore[union-attr]
    assert spec_for_key("1X2").bet_id == 1  # type: ignore[union-attr]
    assert spec_for_key("nothing.FT.match") is None


def _quote(book: int, selection: str, odds: str, line: str = "9.5") -> CurrentQuote:
    return CurrentQuote(bookmaker_id=book, bookmaker=f"Casa {book}", bet_id=45, family="corners", period="FT", subject="match",
                        kind="over_under", has_line=True, market_key=None, provider_name="Corners Over Under", selection=selection,
                        line=Decimal(line), odds=Decimal(odds), captured_at=AT, since=AT)


def _fixture() -> dict[str, Any]:
    return {"kickoff_at": KO, "status_group": "scheduled", "home_team_id": 1, "away_team_id": 2, "competition_id": 3}


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = [q for b in (1, 2, 3) for q in (_quote(b, "Over", "1.90"), _quote(b, "Under", "1.90"))]
    monkeypatch.setattr("fbi.market.in_force.book", lambda conn, fid: SimpleNamespace(quotes=quotes))


def _leg(selection: str = "Over", line: str = "9.5") -> records.LegIn:
    return records.LegIn(fixture_id=1, market_key="corners_over_under.FT.match", selection=selection, line=Decimal(line))


def test_with_the_switch_off_the_catalogue_markets_are_refused(priced: None) -> None:
    refused, price = records._catalogue_leg(None, _leg(), _fixture(), AT, records.MarketPolicy())  # type: ignore[arg-type]
    assert refused == "invalid_selection" and price is None


def test_with_the_switch_on_a_priced_leg_is_taken_with_its_rule(priced: None) -> None:
    policy = records.MarketPolicy(enabled=True, state_of=lambda bet: "en_calibracion")
    refused, price = records._catalogue_leg(None, _leg(), _fixture(), AT, policy)  # type: ignore[arg-type]
    assert refused is None and price is not None
    assert price["rule_key"] == "corners_ft@v1" and price["settles_with"] == "estadisticas" and price["n_bookmakers"] == 3
    assert price["p_fair"] == Decimal("0.5")


def test_a_market_out_of_the_catalogue_or_a_wrong_word_is_refused(priced: None) -> None:
    policy = records.MarketPolicy(enabled=True, state_of=lambda bet: "no_ofrecer")
    assert records._catalogue_leg(None, _leg(), _fixture(), AT, policy)[0] == "invalid_selection"  # type: ignore[arg-type]
    policy = records.MarketPolicy(enabled=True, state_of=lambda bet: "en_calibracion")
    assert records._catalogue_leg(None, _leg("Home"), _fixture(), AT, policy)[0] == "invalid_selection"  # type: ignore[arg-type]


def test_fewer_than_three_houses_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = [_quote(1, "Over", "1.9"), _quote(1, "Under", "1.9")]
    monkeypatch.setattr("fbi.market.in_force.book", lambda conn, fid: SimpleNamespace(quotes=quotes))
    policy = records.MarketPolicy(enabled=True, state_of=lambda bet: "en_calibracion")
    assert records._catalogue_leg(None, _leg(), _fixture(), AT, policy)[0] == "market_not_priced"  # type: ignore[arg-type]


def _state(status: str = "FT", home: int | None = 2, away: int | None = 1) -> settlement.MatchState:
    return settlement.MatchState(status, home, away, None, None, None, None, KO)


def test_a_finished_match_settles_the_leg_by_its_rule() -> None:
    outcome = {"corners_ft_home": 6, "corners_ft_away": 5}
    won = settle_by_rule("corners_over_under.FT.match", "Over", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state(), outcome,
                         at=KO + timedelta(hours=3))
    assert won.status is settlement.Status.WIN and won.profit_units == Decimal("0.9000")
    lost = settle_by_rule("corners_over_under.FT.match", "Under", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state(), outcome,
                          at=KO + timedelta(hours=3))
    assert lost.status is settlement.Status.LOSS


def test_an_unknown_count_waits_and_is_void_after_72_hours() -> None:
    outcome = {"corners_ft_home": None, "corners_ft_away": None}
    waiting = settle_by_rule("corners_over_under.FT.match", "Over", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state(), outcome,
                             at=KO + timedelta(hours=3))
    assert waiting.status is settlement.Status.PENDING
    void = settle_by_rule("corners_over_under.FT.match", "Over", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state(), outcome,
                          at=KO + timedelta(hours=73))
    assert void.status is settlement.Status.VOID and void.basis == NO_DATA_BASIS


def test_a_cancelled_or_unfinished_match_is_the_matchs_rule() -> None:
    assert settle_by_rule("corners_over_under.FT.match", "Over", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state("CANC", None, None),
                          None, at=KO).status is settlement.Status.VOID
    assert settle_by_rule("corners_over_under.FT.match", "Over", Decimal("9.5"), Decimal("1.9"), Decimal(1), _state("NS", None, None),
                          None, at=KO).status is settlement.Status.PENDING


def test_the_five_markets_settle_as_they_always_did() -> None:
    row = {"market_key": "1X2", "selection": "Home", "line": Decimal(0), "status_short": "FT", "reg_goals_home": 2, "reg_goals_away": 1,
           "taken_kickoff": KO}
    assert settle_single(row, Decimal("2.0"), at=KO + timedelta(hours=3)).status is settlement.Status.WIN
    leg = {**row, "market_key": "corners_over_under.FT.match", "selection": "Over", "line": Decimal("9.5"),
           "outcome": {"corners_ft_home": 6, "corners_ft_away": 5}}
    assert settle_single(leg, Decimal("1.9"), at=KO + timedelta(hours=3)).status is settlement.Status.WIN

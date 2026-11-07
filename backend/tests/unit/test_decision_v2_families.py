"""The families of decision-v2 as plug-ins (``fbi.decision.families``): each adapter of today, what it owns and how it settles, the
differences between decision-v1 and decision-fam-v1 written as parameters, and a toy family plugged in with no change to the engine."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.core.decision_versions import (
    DECISION_CORE,
    DECISION_FAMILIES,
    OUTCOME_CORE,
    OUTCOME_FAMILIES,
)
from fbi.decision import engine
from fbi.decision import families as fam
from fbi.decision.families import (
    CORE,
    FAMILIES,
    FORECAST_FAMILIES,
    Candidate,
    FamilyParams,
    GateStatus,
    MarketFamily,
    SettlementRule,
)
from fbi.familydecisions import decide as fd
from fbi.intel import decision
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.picks.rules import CURRENT_RULE

AT = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def test_the_families_of_today_are_core_and_the_four_of_f10_and_each_is_a_market_family() -> None:
    assert [f.name for f in FAMILIES] == ["core", "CARDS", "CORNERS", "GOALS_HALF", "YELLOW"]
    assert {f.name for f in FORECAST_FAMILIES} == set(fd.SPECS)
    for f in FAMILIES:
        assert isinstance(f, MarketFamily), f.name
        assert f.markets(), f.name


@pytest.mark.parametrize(("family", "key", "owned"), [
    ("core", "1X2", True), ("core", "AH", True), ("core", "CORNERS_OU", False),
    ("CORNERS", "CORNERS_OU", True), ("CORNERS", "CORNERS_OU_HOME", True), ("CORNERS", "CARDS_OU", False), ("CORNERS", "1X2", False),
    ("CARDS", "CARDS_OU", True), ("YELLOW", "YELLOW_OU_AWAY", True), ("GOALS_HALF", "OU_1H", True), ("GOALS_HALF", "OU_2H", True),
    ("GOALS_HALF", "HTFT", True), ("GOALS_HALF", "CORNERS_OU", False),
])
def test_each_family_owns_its_markets(family: str, key: str, owned: bool) -> None:
    f = next(x for x in FAMILIES if x.name == family)
    assert f.owns(key) is owned
    assert sum(x.owns(key) for x in FAMILIES) <= 1, "no market belongs to two families"


def test_the_core_family_owns_the_markets_of_the_shadow_rule() -> None:
    assert set(CORE.markets()) == set(CURRENT_RULE.markets)


def test_each_settlement_rule_is_a_function_that_exists_and_writes_its_layers_outcomes() -> None:
    for f in FAMILIES:
        rule = f.settlement
        assert callable(getattr(importlib.import_module(rule.module), rule.function)), rule.ref
    assert CORE.settlement.outcome_version == OUTCOME_CORE
    assert all(f.settlement.outcome_version == OUTCOME_FAMILIES for f in FORECAST_FAMILIES)


def test_the_differences_between_decision_v1_and_decision_fam_v1_are_parameters() -> None:
    c, f = CORE.params, FORECAST_FAMILIES[0].params
    assert (c.decision_version, f.decision_version) == (DECISION_CORE, DECISION_FAMILIES)
    assert c.forecast_max_age == decision.FORECAST_MAX_AGE and f.forecast_max_age is None
    assert (c.interval_required, f.interval_required) == (True, False)
    assert (c.correlate, f.correlate) == (True, False)
    assert (c.promoted, f.promoted) == (True, False)
    assert all(g.params == f for g in FORECAST_FAMILIES)
    documented = FamilyParams.__doc__ or ""
    assert "decision-fam-v1" in documented
    import inspect
    source = inspect.getsource(fam.FamilyParams)
    for name in ("decision_version", "forecast_max_age", "interval_required", "correlate", "promoted"):
        assert f'{name}:' in source and source.split(f"{name}:", 1)[1].split('"""')[1].strip(), f"{name} has a docstring"


def test_a_row_is_claimed_by_the_family_that_decided_it() -> None:
    core_row = {"decision_version": DECISION_CORE, "market_key": "OU", "filters": []}
    corners_row = {"decision_version": DECISION_FAMILIES, "market_key": "CORNERS_OU",
                   "filters": [{"key": "family", "data": {"family": "CORNERS"}}]}
    halves_row = {"decision_version": DECISION_FAMILIES, "market_key": "OU_1H", "filters": []}
    assert fam.family_of(core_row) is CORE
    assert fam.family_of(corners_row).name == "CORNERS"  # type: ignore[union-attr]
    assert fam.family_of(halves_row).name == "GOALS_HALF", "without the family's record, its market says"  # type: ignore[union-attr]
    assert fam.family_of({"decision_version": "decision-v0", "market_key": "OU"}) is None


def test_the_core_adapter_reads_decision_v1s_candidates_in_key_order() -> None:
    k1, k2 = (2, "OU", "Over", Decimal("2.50")), (1, "1X2", "Home", Decimal("0.00"))
    found = {k1: {"m": {"p_model": 0.5}}, k2: {"m": {"p_model": 0.4}, "n": {"p_model": 0.45}}}
    out = CORE.from_picks(found)
    assert [c.key for c in out] == [k2, k1] and [sorted(c.models) for c in out] == [["m", "n"], ["m"]]
    assert all(c.model_hint is None and c.ident[0] == "core" for c in out)


def test_the_forecast_adapter_reads_decision_fam_v1s_candidates_one_per_model() -> None:
    fixture = {"kickoff_at": AT + timedelta(hours=20), "status_short": "NS", "status_group": "scheduled", "home_team_id": 1, "away_team_id": 2,
               "competition_season_id": 1, "competition_id": 1, "competition_name": "L", "home_name": "A", "away_name": "B"}

    def forecast(model: str, p: float, family: str = "CORNERS", key: str = "CORNERS_OU") -> fd.Forecast:
        return fd.Forecast(1, 9, family, model, 7, key, Decimal("9.5"), "Over", p, p, None, None, "UNCALIBRATED", AT, AT, fixture)

    priced = {(9, "CORNERS_OU", Decimal("9.5"), "Over"): fd.Priced(0.5, 2.1, 4, 3, 1.05, AT),
              (9, "CARDS_OU", Decimal("9.5"), "Over"): fd.Priced(0.5, 2.1, 4, 3, 1.05, AT)}
    corners = next(f for f in FORECAST_FAMILIES if f.name == "CORNERS")
    out = corners.from_forecasts([forecast("a", 0.6), forecast("b", 0.62), forecast("a", 0.7, "CARDS", "CARDS_OU")], priced, {9: AT})
    assert [(c.model_hint, c.key[1]) for c in out] == [("a", "CORNERS_OU"), ("b", "CORNERS_OU")], "the cards are another family's"
    [(model, row)] = out[0].models.items()
    assert model == "a" and row["interval_optional"] is True and row["data_cutoff_ts"] is None and row["pick_id"] is None
    assert row == fd.candidates([forecast("a", 0.6)], priced, {9: AT}, specs={"CORNERS": corners.spec})[0].row()


# -- a toy family, plugged in with no change to the engine ---------------------------------------------------------------------------

TOY_PARAMS = FamilyParams(decision_version="toy-v1", forecast_max_age=None, interval_required=False, correlate=False, promoted=True,
                          candidate_rule="every row it is given", price_source="the row's own price")
TOY_SETTLEMENT = SettlementRule("fbi.intel.outcomes", "profit_per_unit", "toy-outcome-v1")


@dataclass(frozen=True)
class ToyFamily:
    """The toy: the total of throw-ins (``THROWINS_OU``), promoted, not correlated, with its own calibrator slot and settlement."""

    rows: Sequence[Mapping[str, Any]]
    name: str = "THROWINS"
    params: FamilyParams = TOY_PARAMS
    settlement: SettlementRule = TOY_SETTLEMENT

    def markets(self) -> tuple[str, ...]:
        return ("THROWINS_OU",)

    def owns(self, market_key: str) -> bool:
        return market_key == "THROWINS_OU"

    def candidates(self, conn: Any, *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        return [Candidate(self, (int(r["fixture_id"]), "THROWINS_OU", "Over", Decimal("20.50")), {"toy-model": r}, "toy-model")
                for r in self.rows if fixtures is None or r["fixture_id"] in fixtures]

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        cal = Calibrator(market, model, "identity", {}, id=99, role="CHAMPION")
        return GateStatus(cal, cal, {"rule_clv": 0.01}, True)

    def claims(self, row: Mapping[str, Any]) -> bool:
        return row.get("decision_version") == self.params.decision_version


def toy_row(fixture: int, *, odds: float = 2.0, p: float = 0.56, books: int = 5) -> dict[str, Any]:
    return {"fixture_id": fixture, "kickoff_at": AT + timedelta(hours=6), "status_short": "NS", "status_group": "scheduled", "p_model": p,
            "p_push": 0.0, "p_low": None, "p_high": None, "data_cutoff_ts": None, "best_odds": odds, "p_fair": 0.48, "n_bookmakers": books,
            "price_at": AT - timedelta(minutes=10), "overround": 0.05, "model_version_id": None}


def empty_world() -> decision.World:
    return decision.World(at=AT, cal=CalibrationState({}, {}, {}, {}), quality={}, reviews={}, rules={}, evidence={}, passes={}, lineups={},
                          type_clv={}, previous={}, ai_mode="shadow")


def test_a_toy_family_goes_through_the_one_engine_with_no_change_to_it() -> None:
    toy = ToyFamily([toy_row(1), toy_row(1, p=0.4), toy_row(2, books=2)])
    assert isinstance(toy, MarketFamily)
    cands = toy.candidates(None, at=AT)
    out = engine.decide_all(empty_world(), cands)
    assert [d.family for d in out] == ["THROWINS"] * 3
    assert [d.state for d in out] == ["RECOMMENDED", "REJECTED", "REJECTED"]
    assert out[0].label == "CANDIDATO_PARLAY" and out[0].verdict("correlation").ok is None, "it does not correlate: two of a match may stand"
    assert out[1].reason == "ev_cal_below" and out[2].reason == "thin_market"
    assert out[0].verdict("calibration").ok is True and out[0].prediction.calibrator_id == 99, "its own calibrator slot"
    assert out[0].verdict("model").ok is True, "it states no interval and does not require one"
    assert fam.family_of({"decision_version": "toy-v1"}, (*FAMILIES, toy)) is toy


def test_a_toy_family_that_is_not_promoted_is_held_at_abstain() -> None:
    toy = ToyFamily([toy_row(1)], params=FamilyParams(decision_version="toy-v1", forecast_max_age=None, interval_required=False,
                                                      correlate=False, promoted=False, candidate_rule="-", price_source="-"))
    [d] = engine.decide_all(empty_world(), toy.candidates(None, at=AT))
    assert d.state == "ABSTAIN" and d.reason == fam.CAP_CODE

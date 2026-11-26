"""C-17 «Unidades» and C-18 «Tendencias» (plan de correcciones UX/UI, AP-K07, AP-L02): contract and example only - no route, their
switches (FBI_STAKES, FBI_TREND_BUILDER) off. The examples are made here and held equal to these builders (``FBI_WRITE_EXAMPLES=1``
rewrites them); the generic tests (``test_intelligence_contract_*.py``) validate, project and look for leaks. Here: the units are one of
the four, a parlay at most half a unit, a slip at most three legs and under its cap, only allowed markets, and no route serves them."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.registry import CATALOGUE, by_id
from fbi.api.contracts.intelligence.stakes import (
    StakeInputs,
    StakeLine,
    StakeLinePrivate,
    StakeResults,
    Stakes,
    StakesPrivate,
    UnitResult,
)
from fbi.api.contracts.intelligence.trends import (
    DiscardedLeg,
    Frequency,
    TrendLeg,
    Trends,
    TrendSlip,
    TrendsPrivate,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence"
AT = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
KO = AT + timedelta(hours=28)


def stakes() -> StakesPrivate:
    lines = [
        StakeLinePrivate(kind="pick", id=660001, stake_units=0.75, stake_rule_version="stake-v1", stake_reason="kelly_cuarto",
                         decided_at=AT, inputs=StakeInputs(kelly_fraction=0.25, kelly_full=0.0312, cap_units=1.0, capped=False)),
        StakeLinePrivate(kind="pick", id=660002, stake_units=1.0, stake_rule_version="stake-v1", stake_reason="tope_estado",
                         decided_at=AT, inputs=StakeInputs(kelly_fraction=0.25, kelly_full=0.0577, cap_units=1.0, capped=True)),
        StakeLinePrivate(kind="parlay", id=440001, stake_units=0.25, stake_rule_version="stake-v1", stake_reason="tope_parlay",
                         decided_at=AT, inputs=Missing(missing_reason="sin_datos")),
    ]
    results = StakeResults(since=AT - timedelta(days=30), settled=24,
                           variable=UnitResult(staked_units=15.5, profit_units=-0.62, roi_pct=-4.0),
                           fixed=UnitResult(staked_units=24.0, profit_units=-1.31, roi_pct=-5.46))
    return StakesPrivate(freshness=Freshness(generated_at=AT, stale=False), stake_rule_version="stake-v1",
                         lines=ItemList[StakeLinePrivate](items=lines), results=results)


def stakes_empty() -> StakesPrivate:
    return StakesPrivate(freshness=Freshness(generated_at=AT, stale=False), stake_rule_version="stake-v1",
                         lines=ItemList[StakeLinePrivate](items=[], missing_reason="sin_publicados"),
                         results=Missing(missing_reason="sin_datos"))


def leg(fixture: int, market: str, selection: str, line: float, label_es: str, label_en: str, hits: int, sample: int,
        low: float, high: float, rule: str, odds: float, league: tuple[float, float] | None = None) -> TrendLeg:
    return TrendLeg(fixture_id=fixture, kickoff_at=KO, market=market, selection=selection, line=line, label_es=label_es,
                    label_en=label_en, trend_es=f"{hits} de los últimos {sample}", trend_en=f"{hits} of the last {sample}",
                    frequency=Frequency(hits=hits, sample=sample, pct=round(100 * hits / sample, 1), low_pct=low, high_pct=high,
                                         league_pct=league[0] if league else None, percentile=league[1] if league else None),
                    settlement_rule=rule, best_odds=odds)


def trends() -> TrendsPrivate:
    corners = leg(990001, "CORNERS_OU", "Over", 9.5, "Más de 9,5 córners", "Over 9.5 corners", 7, 10, 39.7, 89.2,
                  "corners_ft@v1", 1.85, (52.0, 81.0))
    cards = leg(990002, "CARDS_OU", "Over", 4.5, "Más de 4,5 tarjetas", "Over 4.5 cards", 8, 10, 49.0, 94.3, "cards_ft@v1", 1.95, (47.5, 90.0))
    halves = leg(990003, "HT_OU", "Under", 1.5, "Menos de 1,5 goles en la primera parte", "Under 1.5 first-half goals", 9, 12,
                 46.8, 91.1, "goals_1h@v1", 1.40)
    slip = TrendSlip(legs=[corners, cards], combined_odds=3.61, within_limits=True)
    return TrendsPrivate(freshness=Freshness(generated_at=AT, stale=False), max_combined_odds=6.0,
                         allowed_markets=["CARDS_OU", "CORNERS_OU", "HT_OU", "SHOTS_OU"],
                         candidates=ItemList[TrendLeg](items=[cards, corners, halves]), slip=slip,
                         discarded=ItemList[DiscardedLeg](items=[DiscardedLeg(fixture_id=990004, market="OFFSIDES_OU",
                                                                              reason="sin_regla_de_liquidacion"),
                                                                 DiscardedLeg(fixture_id=990001, market="SHOTS_OU",
                                                                              reason="sin_datos_en_la_liga")]),
                         min_sample=8)


def trends_empty() -> TrendsPrivate:
    return TrendsPrivate(freshness=Freshness(generated_at=AT, stale=False), max_combined_odds=6.0, allowed_markets=[],
                         candidates=ItemList[TrendLeg](items=[], missing_reason="sin_datos"), slip=Missing(missing_reason="sin_datos"),
                         discarded=ItemList[DiscardedLeg](items=[], missing_reason="sin_datos"), min_sample=8)


def files() -> dict[Path, dict[str, Any]]:
    out: dict[Path, dict[str, Any]] = {}
    for contract, cases, public in (("C-17", {"con_unidades": stakes(), "sin_publicados": stakes_empty()}, Stakes),
                                    ("C-18", {"armador": trends(), "sin_candidatas": trends_empty()}, Trends)):
        for case, m in cases.items():
            out[EXAMPLES / contract / f"{case}.private.json"] = m.model_dump(mode="json")
            out[EXAMPLES / contract / f"{case}.public.json"] = to_public(m, public).model_dump(mode="json")
    return out


def test_the_examples_are_what_the_builders_make() -> None:
    expected = files()
    if os.environ.get("FBI_WRITE_EXAMPLES") == "1":
        for path, data in expected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, data in expected.items():
        assert json.loads(path.read_text(encoding="utf-8")) == data, path.name


def test_neither_contract_has_a_route_while_its_switch_is_off() -> None:
    for cid in ("C-17", "C-18"):
        assert CATALOGUE[cid].public == () and CATALOGUE[cid].private == ()
        assert by_id()[cid].public_routes == () and by_id()[cid].private_routes == ()


@pytest.mark.parametrize("units", [0.0, 0.1, 1.25, 1.5, 2.0])
def test_units_outside_the_four_do_not_validate(units: float) -> None:
    with pytest.raises(ValidationError):
        StakeLine(kind="pick", id=1, stake_units=units, stake_rule_version="stake-v1", stake_reason="x", decided_at=AT)


def test_a_parlay_carries_at_most_half_a_unit() -> None:
    assert StakeLine(kind="parlay", id=1, stake_units=0.5, stake_rule_version="stake-v1", stake_reason="x", decided_at=AT)
    with pytest.raises(ValidationError):
        StakeLine(kind="parlay", id=1, stake_units=0.75, stake_rule_version="stake-v1", stake_reason="x", decided_at=AT)


def test_the_public_units_carry_nothing_of_what_the_rule_read() -> None:
    public = to_public(stakes(), Stakes).model_dump(mode="json")
    assert all("inputs" not in line for line in public["lines"]["items"])


def test_a_slip_has_at_most_three_legs_once_each_and_says_whether_it_is_under_the_cap() -> None:
    t = trends()
    legs = t.candidates.items
    with pytest.raises(ValidationError):
        TrendSlip(legs=[*legs, legs[0]], combined_odds=9.0, within_limits=False)
    with pytest.raises(ValidationError):
        TrendSlip(legs=[legs[0], legs[0]], combined_odds=3.4, within_limits=True)
    data = t.model_dump(mode="json")
    data["slip"]["combined_odds"] = 7.2  # above the cap of 6 while saying it is within: refused
    with pytest.raises(ValidationError):
        TrendsPrivate.model_validate(data)
    data["slip"]["within_limits"] = False
    assert TrendsPrivate.model_validate(data).slip.within_limits is False  # type: ignore[union-attr]


def test_only_an_allowed_market_is_a_candidate_and_the_label_says_it_is_not_a_pick() -> None:
    data = trends().model_dump(mode="json")
    assert data["label"] == "tendencia_no_pick" and data["label_es"] == "Análisis de tendencias · no es un pick oficial"
    data["allowed_markets"] = ["CARDS_OU"]
    with pytest.raises(ValidationError):
        TrendsPrivate.model_validate(data)


def test_a_frequency_is_its_hits_of_its_sample_inside_its_interval() -> None:
    assert Frequency(hits=7, sample=10, pct=70.0, low_pct=39.7, high_pct=89.2).pct == 70.0
    for bad in ({"hits": 11, "sample": 10, "pct": 110.0}, {"hits": 7, "sample": 10, "pct": 60.0},
                {"hits": 7, "sample": 10, "pct": 70.0, "low_pct": 75.0}):
        with pytest.raises(ValidationError):
            Frequency.model_validate({"low_pct": 39.7, "high_pct": 89.2} | bad)


def test_the_league_reference_of_a_frequency_is_optional_and_travels_only_when_there_is_one() -> None:
    plain = Frequency(hits=7, sample=10, pct=70.0, low_pct=39.7, high_pct=89.2)
    assert "league_pct" not in plain.model_dump(mode="json") and "percentile" not in plain.model_dump(mode="json")
    ref = Frequency(hits=7, sample=10, pct=70.0, low_pct=39.7, high_pct=89.2, league_pct=52.0, percentile=81.0)
    assert ref.model_dump(mode="json")["league_pct"] == 52.0 and ref.model_dump(mode="json")["percentile"] == 81.0
    for bad in ({"league_pct": 101.0}, {"percentile": -1.0}):
        with pytest.raises(ValidationError):
            Frequency.model_validate({"hits": 7, "sample": 10, "pct": 70.0, "low_pct": 39.7, "high_pct": 89.2} | bad)

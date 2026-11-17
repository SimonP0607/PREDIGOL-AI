"""AD-J05 (IA-132): contract C-04 «Parlays con estado».

The examples (``tests/fixtures/contracts/intelligence/C-04``) are made here by the service's own builders and held equal to them
(``FBI_WRITE_EXAMPLES=1`` rewrites them); the generic tests (``test_intelligence_contract_*.py``) validate, project and look for leaks.
Here: «ninguno» arrives when the rule builds nothing (parlay-v5 and parlay-v6), two and three legs, never more than three for
parlay-v6, the public field travels only with the switch on and only for what a reader is shown, parlay-v5's history stays readable, and
what the service restates of ``fbi.tracking`` (a leaf it may not import) is the code's.
"""

from __future__ import annotations

import itertools
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from fbi.api.contracts.intelligence.base import ItemList, Missing
from fbi.api.contracts.intelligence.parlays import (
    RULES,
    ParlaySetCard,
    ParlaySetLeg,
    ParlaySetPeriod,
    ParlaySetRule,
    ParlaySetState,
    ParlaySetStatePrivate,
    V6NoneDetail,
)
from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.product import CompetitionBadge, Parlay, ParlayLeg, TeamBadge
from fbi.api.envelope import ok
from fbi.api.services import parlay_states as svc
from fbi.tracking import parlay_v6 as v6
from fbi.tracking import parlay_v6_shadow as v6_shadow

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-04"
AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)
DAY = date(2026, 11, 21)
KO = datetime(2026, 11, 21, 20, 0, tzinfo=UTC)


def leg(n: int, *, odds: str = "1.80", p_win: str = "0.6100") -> ParlayLeg:
    return ParlayLeg(pick_id=660000 + n, fixture_id=990000 + n, kickoff_at=KO + timedelta(hours=n), competition=CompetitionBadge(
        id=39, name="Liga Ejemplo", country="Ejemplia", logo_url=None, flag_url=None), home=TeamBadge(id=2 * n, name=f"Local {n}",
                                                                                                         logo_url=None),
        away=TeamBadge(id=2 * n + 1, name=f"Visitante {n}", logo_url=None), market_key="1X2", selection="Home", line=Decimal("0"),
        odds=Decimal(odds), bookmaker="Casa Ejemplo", price_at=AT - timedelta(minutes=8), p_model=Decimal("0.6300"),
        p_market=Decimal("0.5400"), p_win=Decimal(p_win), edge=Decimal("0.0700"), ev=Decimal("0.0980"))


def live(kind: str, legs: int = 0, *, source: str = "qualified") -> Parlay:
    built = legs > 0
    items = [leg(n) for n in range(1, legs + 1)]
    spec = {"daily": (5, 5, 24), "multiday": (6, 7, 48)}[kind]
    return Parlay(kind=kind, status="ok" if built else "no_valid_parlay", source=source, legs=items,  # type: ignore[arg-type]
                  required_legs=spec[0], max_legs=spec[1], eligible_legs=legs + 2 if built else 1, window_from=AT,
                  window_to=AT + timedelta(hours=spec[2]), combined_odds=Decimal("34.012") if built else None,
                  probability_all_win=Decimal("0.05152") if built else None, expected_value=Decimal("0.7522") if built else None,
                  risk="very_high" if built else None, independence="distinct_fixtures_and_teams" if built else None,
                  prices_as_of=AT - timedelta(minutes=8) if built else None,
                  rejections={"not_qualified": 41, "few_bookmakers": 3} if not built else {"not_qualified": 12}, generated_at=AT)


def v6_row(pid: int, kind: str, *, built: bool, n_legs: int = 0, none_reason: str | None = None,
           refused: dict[str, int] | None = None) -> dict[str, Any]:
    frm = datetime(2026, 11, 21, 5, 0, tzinfo=UTC)
    base: dict[str, Any] = {"id": pid, "kind": kind, "day": DAY, "outcome": "built" if built else "none", "none_reason": none_reason,
                            "max_legs": 3, "n_legs": n_legs, "n_candidates": 0 if not built else n_legs + 1, "window_from": frm,
                            "window_to": frm + (timedelta(days=1) if kind == "daily" else timedelta(days=4)),
                            "inputs": {"refused": refused or {}}, "known_at": AT - timedelta(hours=2), "rule_version": "parlay-v6"}
    nulls = ("combined_odds", "p_joint", "p_joint_se", "p_joint_low", "p_product", "p_market_joint", "fair_odds",
             "accumulated_margin", "expected_value", "expected_value_low")
    base.update(dict.fromkeys(nulls))
    if built:
        joint = {2: (3.42, 0.3061, 0.0015, 0.2712, 0.3192, 0.2754, 3.2669, 0.0581, 0.0469, -0.0725),
                 3: (6.3175, 0.1683, 0.0012, 0.1397, 0.1771, 0.1490, 5.9418, 0.0587, 0.0632, -0.1175)}[n_legs]
        base.update(dict(zip(nulls, joint, strict=True)))
    return base


def v6_leg(pid: int, n: int, *, result: str | None, kickoff: datetime, odds: float) -> dict[str, Any]:
    return {"parlay_id": pid, "leg_no": n, "chain_key": f"decision-v2-shadow-v1|99{pid % 100:02d}{n:02d}|1X2|Home|0.00",
            "fixture_id": 991000 + 10 * pid % 1000 + n, "kickoff_at": kickoff, "market_key": "OU" if n == 2 else "1X2",
            "selection": "Over" if n == 2 else "Home", "line": Decimal("2.50") if n == 2 else Decimal("0.00"), "odds": odds,
            "p_model": 0.58, "p_low": 0.54, "p_market": 0.53, "result": result}


def period(kind: str | None = None) -> ParlaySetPeriod:
    return ParlaySetPeriod(date_from=DAY - timedelta(days=6), date_to=DAY, kind=kind)  # type: ignore[arg-type]


HISTORY = [{"kind": "daily", "source": "evaluation", "status": "LOST", "parlays": 14},
           {"kind": "daily", "source": "evaluation", "status": "WON", "parlays": 1},
           {"kind": "multiday", "source": "evaluation", "status": "LOST", "parlays": 10},
           {"kind": "multiday", "source": "evaluation", "status": "VOID", "parlays": 2}]


def cases() -> dict[str, ParlaySetStatePrivate]:
    # «ninguno»: neither rule found anything that meets - the product says so and parlay-v6 kept the day without one, with why
    ninguno = svc.assemble(at=AT, period=period("daily"), live=[live("daily")],
                           v6_rows=[v6_row(41, "daily", built=False, none_reason="sin_candidatos",
                                           refused={"no_confirmada": 37, "una_sola_casa": 2})], v6_legs=[], v5_counts=[])
    # two legs: parlay-v6 built one in the shadow (never published), the product's parlay of the day is «ninguno»
    two = 42
    dos = svc.assemble(at=AT, period=period(), live=[live("daily")],
                       v6_rows=[v6_row(two, "daily", built=True, n_legs=2)],
                       v6_legs=[v6_leg(two, 1, result=None, kickoff=KO, odds=1.80), v6_leg(two, 2, result=None, kickoff=KO, odds=1.90)],
                       v5_counts=HISTORY)
    # three legs: parlay-v6 lost one (a leg lost), and the product's multi-day parlay is built and published (six legs of parlay-v5)
    three = 43
    past = AT - timedelta(days=1)
    tres = svc.assemble(at=AT, period=period(), live=[live("multiday", 6)],
                        v6_rows=[v6_row(three, "multiday", built=True, n_legs=3)],
                        v6_legs=[v6_leg(three, 1, result="win", kickoff=past, odds=1.85),
                                 v6_leg(three, 2, result="loss", kickoff=past, odds=1.90),
                                 v6_leg(three, 3, result="win", kickoff=past + timedelta(hours=2), odds=1.80)],
                        v5_counts=HISTORY)
    return {"ninguno": ninguno, "dos_tramos": dos, "tres_tramos": tres}


def dumped(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def test_the_examples_are_what_the_builders_make() -> None:
    files: dict[Path, dict[str, Any]] = {}
    for case, m in cases().items():
        files[EXAMPLES / f"{case}.private.json"] = dumped(m)
        files[EXAMPLES / f"{case}.public.json"] = dumped(to_public(m, ParlaySetState))
    if os.environ.get("FBI_WRITE_EXAMPLES") == "1":
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, data in files.items():
        assert json.loads(path.read_text(encoding="utf-8")) == data, path.name


# ── «ninguno», two and three legs ────────────────────────────────────────────────────────────────────────────────────

def test_none_arrives_as_a_state_when_the_rule_builds_nothing() -> None:
    m = cases()["ninguno"]
    v5, v6_card = m.parlays.items
    for card in (v5, v6_card):
        assert card.status == "ninguno" and card.none_reason == "NINGUNO_CUMPLE"
        assert card.legs.items == [] and card.legs.missing_reason == "sin_datos" and isinstance(card.result, Missing)
    assert v5.published and v5.rule.version == "parlay-v5" and v5.source == "en_vivo"
    assert not v6_card.published and v6_card.none_detail == "sin_candidatos"
    assert [(r.code, r.count) for r in v6_card.refused] == [("no_confirmada", 37), ("una_sola_casa", 2)]
    public = to_public(m, ParlaySetState)
    assert [c.rule.version for c in public.parlays.items] == ["parlay-v5"]
    assert public.parlays.items[0].status == "ninguno"


def test_two_and_three_legs_carry_the_state_of_the_set() -> None:
    dos = cases()["dos_tramos"].parlays.items[1]
    assert (dos.status, dos.result, len(dos.legs.items)) == ("armado", "pendiente", 2)
    assert dos.rule.max_legs == 3 and dos.rule.joint == "simulacion_copula"
    assert dos.joint is not None and not isinstance(dos.joint, Missing) and dos.joint.calibration == "sin_calibrar"
    assert dos.accumulated_margin_pct == 5.81 and isinstance(dos.payout_factor, Missing)
    tres = cases()["tres_tramos"].parlays.items[1]
    assert (tres.status, tres.result, len(tres.legs.items), tres.payout_factor) == ("liquidado", "perdido", 3, 0.0)
    assert [x.result for x in tres.legs.items] == ["win", "loss", "win"]
    live_multi = cases()["tres_tramos"].parlays.items[0]
    assert (live_multi.status, len(live_multi.legs.items), live_multi.rule.max_legs) == ("armado", 6, 7)


def test_a_leg_kicked_off_puts_the_set_in_play() -> None:
    row = v6_row(50, "daily", built=True, n_legs=2)
    legs = [v6_leg(50, 1, result="win", kickoff=AT - timedelta(hours=2), odds=1.8),
            v6_leg(50, 2, result=None, kickoff=AT + timedelta(hours=1), odds=1.9)]
    card = svc.v6_card(row, legs, at=AT)
    assert (card.status, card.result) == ("en_juego", "pendiente")


def test_parlay_v6_never_holds_more_than_three_legs() -> None:
    with pytest.raises(ValidationError, match="at most 3"):
        ParlaySetRule(version="parlay-v6", min_legs=2, max_legs=4, max_per_match=2, joint="simulacion_copula")
    card = cases()["dos_tramos"].parlays.items[1]
    extra = ParlaySetLeg(fixture_id=1, kickoff_at=KO, market="1X2", selection="Home", line=0, odds=1.5, result="pending")
    with pytest.raises(ValidationError, match="outside the rule"):
        ParlaySetCard.model_validate(dumped(to_public_card(card)) | {"legs": {"items": [dumped(extra)] * 4}})


def to_public_card(card: Any) -> ParlaySetCard:
    data = {k: getattr(card, k) for k in ParlaySetCard.model_fields}
    data["legs"] = ItemList[ParlaySetLeg](items=[ParlaySetLeg(**{k: getattr(x, k) for k in ParlaySetLeg.model_fields})
                                                for x in card.legs.items])
    return ParlaySetCard(**data)


def test_a_state_that_does_not_fit_is_refused() -> None:
    card = dumped(to_public_card(cases()["dos_tramos"].parlays.items[1]))
    with pytest.raises(ValidationError, match="exactly when"):
        ParlaySetCard.model_validate(card | {"none_reason": "NINGUNO_CUMPLE"})
    with pytest.raises(ValidationError, match="does not agree"):
        ParlaySetCard.model_validate(card | {"status": "liquidado"})


# ── the public field ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_public_field_travels_only_with_the_switch_and_only_for_a_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: False)
    assert svc.public_state(live("daily", 5)) is None
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: True)
    assert svc.public_state(live("daily", 5, source="shadow_preview")) is None
    state = svc.public_state(live("daily", 5))
    assert isinstance(state, ParlaySetState) and state.projection == "public"
    assert [c.status for c in state.parlays.items] == ["armado"]
    found = leaks(dumped(state), public_schema=ParlaySetState.model_json_schema(mode="serialization"),
                  private_schema=ParlaySetStatePrivate.model_json_schema(mode="serialization"))
    assert found == []


def test_the_parlay_answer_keeps_its_shape_while_the_field_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.routers import product as route
    from fbi.api.services import product as product_service

    answer = live("daily")
    assert "state" not in dumped(answer)
    monkeypatch.setattr(product_service, "parlay_board", lambda conn, kind, include_shadow: ok(answer))
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: False)
    off = route.get_parlay(None, None, "daily")  # type: ignore[arg-type]
    assert dumped(off.data) == dumped(answer)
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: True)
    on = dumped(route.get_parlay(None, None, "daily").data)  # type: ignore[arg-type]
    assert on.pop("state")["contract"] == "C-04" and on == dumped(answer)


# ── parlay-v5's history and the restated rule ────────────────────────────────────────────────────────────────────────

def test_parlay_v5_history_stays_readable_beside_v6() -> None:
    m = cases()["dos_tramos"]
    assert [(h.kind, h.status, h.parlays) for h in m.v5_history.items] == [
        ("daily", "LOST", 14), ("daily", "WON", 1), ("multiday", "LOST", 10), ("multiday", "VOID", 2)]
    without = svc.assemble(at=AT, period=period(), live=[live("daily")], v6_rows=None, v6_legs=[], v5_counts=[])
    assert isinstance(without.calibration, Missing) and without.v5_history.missing_reason == "sin_datos"
    assert [c.source for c in without.parlays.items] == ["en_vivo"]
    cal = cases()["tres_tramos"].calibration
    assert not isinstance(cal, Missing) and (cal.settled, cal.won, cal.needed) == (1, 0, 100)


def test_what_the_service_restates_of_the_tracking_is_the_code_s() -> None:
    assert svc.CHAINS == v6_shadow.CHAINS and svc.V6 == v6.RULE_VERSION
    assert RULES["parlay-v6"] == {"min_legs": v6.MIN_LEGS, "max_legs": v6.MAX_LEGS, "max_per_match": v6.MAX_PER_MATCH,
                                  "min_books": v6.MIN_BOOKS, "joint": "simulacion_copula"}
    assert set(get_args(V6NoneDetail)) == set(get_args(v6.NoneReason))
    words = ("win", "loss", "void", None)
    for n in (2, 3):
        for results in itertools.product(words, repeat=n):
            odds = [1.8, 1.9, 2.1][:n]
            assert svc.outcome(list(results), odds) == v6.outcome(list(results), odds), results
    with pytest.raises(ValueError):
        svc.outcome(["push", "win"], [1.8, 1.9])
    sample = [{"status": "WON", "p_joint": 0.3, "p_joint_low": 0.25}, {"status": "LOST", "p_joint": 0.2, "p_joint_low": 0.18},
              {"status": "VOID", "p_joint": 0.2, "p_joint_low": 0.1}, {"status": "ACTIVE", "p_joint": 0.4, "p_joint_low": 0.3}]
    for parlays in (sample, []):
        mine, code = svc.calibration(parlays), v6_shadow.calibration(parlays)
        code.pop("note")
        assert mine == code
    assert svc.CALIBRATION_NEEDED == 100


def test_the_period_is_bounded() -> None:
    from fbi.api.problem import ApiError

    with pytest.raises(ApiError):
        svc.private(None, live=[], date_from=DAY, date_to=DAY - timedelta(days=1), at=AT)  # type: ignore[arg-type]
    with pytest.raises(ApiError):
        svc.private(None, live=[], date_from=DAY - timedelta(days=40), date_to=DAY, at=AT)  # type: ignore[arg-type]

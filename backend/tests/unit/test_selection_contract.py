"""AD-J03 (IA-114) and AD-J04 (IA-115): contracts C-02 «Selección» and C-03 «Seguimiento privado».

The examples (``tests/fixtures/contracts/intelligence/C-02``, ``C-03``) are made here and held equal to what these builders make
(``FBI_WRITE_EXAMPLES=1`` rewrites them); the generic tests (``test_intelligence_contract_*.py``) validate them, project them and look for
leaks. Here: a selection under evaluation or withdrawn has no public projection at all (the server answers nothing for it), «Explícame»
answers as before while the switch is off or the selection is not public, the price rules are the code's, the templates are code.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from fbi.api.contracts.explanation import PickExplanation
from fbi.api.contracts.intelligence.base import (
    Freshness,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    Source,
)
from fbi.api.contracts.intelligence.projection import ProjectionError, leaks, to_public
from fbi.api.contracts.intelligence.selection import (
    PRICE_RULES,
    Dependency,
    EvaluationSummary,
    ExpectedValue,
    MarketStatusRef,
    PriceView,
    Reason,
    SelectionIntelligence,
    SelectionIntelligencePrivate,
    SelectionRef,
    SettlementRuleView,
    SourceUsed,
    Version,
)
from fbi.api.contracts.intelligence.tracking import (
    BoardRef,
    FamilyCounter,
    Filters,
    Period,
    StateCounts,
    Tracking,
    TrackingFixture,
    TrackingItem,
    TrackingSelection,
)
from fbi.api.services import selection_intelligence as svc
from fbi.decision import price_age
from fbi.intel import decision as decision_v1
from fbi.lifecycle import machine

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence"
AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)
KO = datetime(2026, 11, 21, 20, 0, tzinfo=UTC)
NOT_YET = Missing(missing_reason="no_entregado", expected_piece="AD-D06")


def probability(p: float, *, calibrated: bool = True) -> Probability:
    return Probability.of(p, calibration="calibrada" if calibrated else "sin_calibrar", as_of=AT, origin="decision-v1",
                          evaluation=NOT_YET, evaluation_version=NOT_YET, interval=Missing(missing_reason="sin_datos"))


def selection(state: str, public: str | None, **kw: Any) -> SelectionIntelligencePrivate:
    base: dict[str, Any] = {
        "freshness": Freshness(generated_at=AT, stale=False),
        "selection": SelectionRef(fixture_id=990001, market="OU", selection="Over", line=2.5, family="core", label_es="Más de 2,5 goles"),
        "public_state": public, "probability": probability(0.57), "fair_odds": 1.75,
        "expected_value": ExpectedValue(pct=8.9, interval_pct=Missing(missing_reason="sin_datos")),
        "price": PriceView(best_odds=1.91, books=5, seen_at=AT - timedelta(minutes=12), age_minutes=12.0, price_state="vigente",
                        price_rule="price-age-v1", thresholds_min=[30, 180]),
        "reasons_for": ItemList[Reason](items=[Reason(code="probabilidad_sobre_mercado",
                                                   text_es="PrediGol estima un 57 % frente al 52 % del mercado sin margen."),
                                            Reason(code="valor_esperado_positivo", text_es="Valor esperado de +8,9 % a la cuota 1,91.")]),
        "reasons_against": ItemList[Reason](items=[], missing_reason="sin_datos"),
        "depends_on": ItemList[Dependency](items=[], missing_reason="sin_datos"),
        "settlement_rule": SettlementRuleView(rule="settle-v4", text_es="Se liquida con el marcador de los 90 minutos y el añadido; la "
                                                                     "prórroga y los penaltis no cuentan. Las líneas de cuarto son dos "
                                                                     "medias apuestas."),
        "versions": ItemList[Version](items=[
            Version(at=AT - timedelta(hours=12), checkpoint="T-12h", state="CAUTELA", probability_pct=55.0, best_odds=1.95,
                    change_es="Primera decisión."),
            Version(at=AT, checkpoint="T-3h", state="APROBADO", probability_pct=57.0, best_odds=1.91, change_es="Pasa de CAUTELA a APROBADO.")]),
        "sources": ItemList[SourceUsed](items=[SourceUsed(id=880001, kind="injury", source=Source(name="Diario Ejemplo",
                                                                                              url="https://diario.ejemplo.invalid/nota"),
                                                       known_at=AT - timedelta(hours=5))]),
        "market_status": MarketStatusRef(market_key="OU", state="en_calibracion", reason="sin_calibrador_validado"),
        "decision_id": 770001, "layer": "decision-v1", "decision_state": "APROBADO", "lifecycle_state": state, "lifecycle_reason": "cumple_todo",
        "raw_probability": probability(0.785, calibrated=False), "lineup_dependency": Missing(missing_reason="no_entregado", expected_piece="AD-D03"),
        "validation": MarketValidation(verdict="INSUFICIENTE", sample=0, needed=300), "validation_cell": "decision-v1|core|OU",
        "evaluation": Missing(missing_reason="sin_datos")}
    base.update(kw)
    return SelectionIntelligencePrivate(**base)


def cases_c02() -> dict[str, SelectionIntelligencePrivate]:
    return {
        "publicada": selection("confirmada_sombra", "publicada"),
        "liquidada": selection("evaluada", "liquidada", lifecycle_reason="evaluacion_posterior", evaluation=EvaluationSummary(
            version="eval-sel-v1", result="win", clv_pct=4.3, verdict="MERECIDO", evidence_held=1, evidence_contradicted=0,
            evidence_unevaluable=0, lineup_changed=False)),
    }


def private_only_c02() -> dict[str, SelectionIntelligencePrivate]:
    return {
        "en_evaluacion": selection("en_evaluacion", None, decision_state="CAUTELA", lifecycle_reason="valor_insuficiente",
                                   reasons_for=ItemList[Reason](items=[], missing_reason="sin_datos"),
                                   reasons_against=ItemList[Reason](items=[Reason(code="ev_cal_below",
                                                                                  text_es="El valor esperado no supera el mínimo.")])),
        "retirada": selection("retirada", None, decision_state="RECHAZADO", lifecycle_reason="revision_en_contra",
                              reasons_against=ItemList[Reason](items=[Reason(code="ai_reject", text_es="La revisión en contra.")]),
                              depends_on=ItemList[Dependency](items=[Dependency(code="alineacion_oficial",
                                                                                text_es="Que la alineación oficial confirme la baja que "
                                                                                        "se ha reportado.")])),
    }


def tracking(empty: bool = False) -> Tracking:
    filters = Filters(state=None, family=None, competition=None, limit=50)
    if empty:
        return Tracking(freshness=Freshness(generated_at=AT, stale=False), machine_version="lifecycle-v1", writer="lifecycle-shadow-v1",
                        filters=filters, counts_by_state=Missing(missing_reason="sin_datos"),
                        families=ItemList[FamilyCounter](items=[], missing_reason="sin_datos"), board=Missing(missing_reason="sin_datos"),
                        items=ItemList[TrackingItem](items=[], missing_reason="sin_datos"),
                        period=Period(date_from=date(2026, 11, 15), date_to=date(2026, 11, 22), total=0), next_cursor=None)
    counts = dict.fromkeys(machine.STATES, 0) | {"detectado": 4, "en_evaluacion": 9, "pendiente_alineaciones": 2, "confirmada_sombra": 6,
                                               "retirada": 1, "descartada": 31, "en_juego": 3, "liquidada": 12, "evaluada": 5}
    item = TrackingItem(fixture=TrackingFixture(id=990001, kickoff_at=KO, competition_id=39),
                        selection=TrackingSelection(market="CORNERS_OU", selection="Over", line=9.5, family="corners",
                                                    layer="decision-fam-v1"),
                        state="confirmada_sombra", reason="cumple_salvo_validacion", known_at=AT, detected_at=AT - timedelta(hours=20),
                        moves=3, public_state=None, probability=probability(0.57, calibrated=False), price_taken=1.93,
                        evaluation=Missing(missing_reason="no_entregado", expected_piece="AD-D06"), outcome="pending",
                        clv_pct=Missing(missing_reason="sin_datos"), verdict=Missing(missing_reason="sin_datos"))
    return Tracking(freshness=Freshness(generated_at=AT, stale=False), machine_version="lifecycle-v1", writer="lifecycle-shadow-v1",
                    filters=filters, counts_by_state=StateCounts(**counts),
                    families=ItemList[FamilyCounter](items=[
                        FamilyCounter(layer="decision-fam-v1", family="corners", candidates=1626, sample=212, needed=300,
                                      verdict="INSUFICIENTE", clv_pct=0.6),
                        FamilyCounter(layer="decision-v1", family="core", candidates=31593, sample=0, needed=300, verdict="INSUFICIENTE",
                                      clv_pct=Missing(missing_reason="sin_datos"))]),
                    board=BoardRef(version="board-v1", protocol="AD-K02", fingerprint="0" * 64, signed_by_owner=False, bonferroni_m=0),
                    items=ItemList[TrackingItem](items=[item]),
                    period=Period(date_from=date(2026, 11, 15), date_to=date(2026, 11, 22), total=1), next_cursor=None)


def dumped(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def expected_files() -> dict[Path, dict[str, Any]]:
    out: dict[Path, dict[str, Any]] = {}
    for case, m in cases_c02().items():
        out[EXAMPLES / "C-02" / f"{case}.private.json"] = dumped(m)
        out[EXAMPLES / "C-02" / f"{case}.public.json"] = dumped(to_public(m, SelectionIntelligence))
    for case, m in private_only_c02().items():
        out[EXAMPLES / "C-02" / "privada" / f"{case}.private.json"] = dumped(m)
    out[EXAMPLES / "C-03" / "en_sombra.private.json"] = dumped(tracking())
    out[EXAMPLES / "C-03" / "sin_tablas.private.json"] = dumped(tracking(empty=True))
    return out


def test_the_examples_are_what_the_builders_make() -> None:
    files = expected_files()
    if os.environ.get("FBI_WRITE_EXAMPLES") == "1":
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, data in files.items():
        assert json.loads(path.read_text(encoding="utf-8")) == data, path.name


def test_a_selection_under_evaluation_or_withdrawn_has_no_public_projection() -> None:
    for case, m in private_only_c02().items():
        assert m.public_state is None, case
        with pytest.raises((ValidationError, ProjectionError)):
            to_public(m, SelectionIntelligence)


def test_the_public_projection_carries_nothing_private() -> None:
    for m in cases_c02().values():
        public = dumped(to_public(m, SelectionIntelligence))
        for key in ("decision_id", "layer", "decision_state", "lifecycle_state", "raw_probability", "validation", "evaluation"):
            assert key not in public
        assert public["public_state"] in ("publicada", "en_juego", "liquidada")
        assert leaks(public, public_schema=SelectionIntelligence.model_json_schema(mode="serialization"),
                     private_schema=SelectionIntelligencePrivate.model_json_schema(mode="serialization")) == []


def test_the_explanation_does_not_carry_the_field_while_it_is_none() -> None:
    assert "intelligence" in PickExplanation.model_fields
    assert PickExplanation.model_fields["intelligence"].default is None


def test_without_the_switch_the_public_contract_is_never_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: False)
    assert svc.public_for_pick(object(), 1) is None  # type: ignore[arg-type]  # no query is even made


def test_with_the_switch_a_selection_the_owner_did_not_authorise_stays_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: True)
    monkeypatch.setattr(svc, "fetch_one", lambda conn, sql, params: {"id": 770001})
    monkeypatch.setattr(svc, "private", lambda conn, decision_id, at=None: private_only_c02()["en_evaluacion"])
    assert svc.public_for_pick(object(), 1) is None  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "private", lambda conn, decision_id, at=None: cases_c02()["publicada"])
    built = svc.public_for_pick(object(), 1)  # type: ignore[arg-type]
    assert isinstance(built, SelectionIntelligence) and not isinstance(built, SelectionIntelligencePrivate)
    assert built.public_state == "publicada"


def test_the_price_rules_in_the_contract_are_the_code_s() -> None:
    v1, v2 = price_age.V1, price_age.V2
    assert PRICE_RULES["price-age-v1"]["limits_min"] == (int(v1.bands[0].max_age.total_seconds() // 60),)
    assert v1.final_max_age is not None and PRICE_RULES["price-age-v1"]["final_min"] == int(v1.final_max_age.total_seconds() // 60)
    assert set(PRICE_RULES["price-age-v1"]["final_checkpoints"]) == set(decision_v1.FINAL_CHECKPOINTS)  # type: ignore[call-overload]
    assert PRICE_RULES["price-age-v2"]["limits_min"] == tuple(int(b.max_age.total_seconds() // 60) for b in v2.bands) == (195, 75, 45)
    assert set(price_age.PRICE_STATES) == {"vigente", "antiguo", "sin_precio"}


@pytest.mark.parametrize(("age", "checkpoint", "state"), [
    (None, "T-3h", "vigente"), (timedelta(minutes=180), "T-3h", "vigente"), (timedelta(minutes=181), "T-3h", "antiguo"),
    (timedelta(minutes=30), "T-15m", "vigente"), (timedelta(minutes=31), "lineups", "antiguo"),
])
def test_the_price_state_is_decision_v1_s_rule(age: timedelta | None, checkpoint: str, state: str) -> None:
    assert svc.price_state(age=age, checkpoint=checkpoint) == state
    check = price_age.V1.check(priced=True, age=age, minutes_to_kickoff=300, checkpoint=checkpoint)
    assert check.state == state


def test_the_labels_and_the_templates_are_code() -> None:
    assert svc.label_es("OU", "Over", Decimal("2.5")) == "Más de 2,5 goles"
    assert svc.label_es("AH", "Home", Decimal("-0.75")) == "Hándicap asiático local -0,75"
    assert svc.label_es("1X2", "Draw", Decimal(0)) == "Empate"
    assert isinstance(svc.label_es("PLAYER_SHOTS", "Over", Decimal("1.5")), Missing)
    d = {"p_cal": 0.57, "p_model": 0.6, "p_market": 0.52, "ev_cal": 0.089, "odds": 1.91, "reasons": ["ev_cal_below", "family_research",
                                                                                                    "key_absence_reported"],
         "context_status": "PENDING", "known_at": AT}
    assert [r.code for r in svc._reasons_for(d)] == ["probabilidad_sobre_mercado", "valor_esperado_positivo"]
    assert svc._reasons_for(d)[1].text_es == "Valor esperado de +8,9 % a la cuota 1,91."
    assert [r.code for r in svc._reasons_against(d)] == ["ev_cal_below", "key_absence_reported"]
    assert [x.code for x in svc._depends_on(d, None)] == ["alineacion_oficial", "contexto_del_partido"]
    assert [x.code for x in svc._depends_on(d, AT - timedelta(hours=1))] == ["contexto_del_partido"]


def test_every_reason_code_of_decision_v1_has_its_text() -> None:
    from fbi.lifecycle import derive

    assert set(derive.BLOCKER_OF) | set(derive.MARKET_LEVEL) <= set(svc.REASON_TEXT)


def test_c03_counts_carry_the_ten_states_and_a_family_s_verdict_follows_its_sample() -> None:
    t = tracking()
    assert isinstance(t.counts_by_state, StateCounts) and set(StateCounts.model_fields) == set(machine.STATES)
    with pytest.raises(ValidationError):
        FamilyCounter(layer="decision-v1", family="core", candidates=10, sample=300, needed=300, verdict="INSUFICIENTE",
                      clv_pct=Missing(missing_reason="sin_datos"))
    with pytest.raises(ValidationError):
        Tracking.model_validate(dumped(t) | {"counts_by_state": {"detectado": 1}})

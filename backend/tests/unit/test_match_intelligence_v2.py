"""C-01 2.0.0, the match complete (AD-J02 delivery 2, IA-131): composed from what the pieces already compute, nothing recomputed.

The generic tests (``test_intelligence_contract_*.py``) hold the examples, the projection and the leak check of both major versions; these
hold what is particular to 2.0.0:

* 1.x stays as it was: its classes, version, routes and examples are untouched, and the registry keeps it as ``C-01@1``;
* every block fills from its piece's rows - scenarios (``necesita``, ``depende_de``, ``decidido``, what each result does), the one chronicle
  by its eight sections and its update after the line-up, E1-E4 with their versions and decision-v2's seal, C-05, C-02's cycle, C-07, the
  market states, availability and player-engine-v2;
* the public projection never carries a shadow block the owner did not publish (``pendiente_derechos``), and the public read does not even
  read the shadow tables;
* a database without the pieces' tables answers ``no_entregado`` with each piece;
* the constants copied to keep the import cycle from growing are equal to their sources;
* the examples in ``tests/fixtures/contracts/intelligence/C-01/v2`` are exactly what the builder makes of five fictitious cases.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fbi.api.contracts.intelligence.base import Missing, Probability
from fbi.api.contracts.intelligence.match import MatchIntelligence, MatchIntelligencePrivate
from fbi.api.contracts.intelligence.match_v2 import (
    SCENARIOS_ORIGIN,
    MatchIntelligenceV2,
    MatchIntelligenceV2Private,
    MatchV2Chronicle,
    MatchV2Scenarios,
)
from fbi.api.contracts.intelligence.profiles import AvailabilityEntry, TeamAvailability
from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.intelligence.registry import by_id, by_key
from fbi.api.services import analysis_sources
from fbi.api.services import match_intelligence as mi
from fbi.api.services import match_intelligence_v2 as m2
from fbi.api.switches import MATCH_INTELLIGENCE
from tests.unit.test_match_intelligence import AT, AWAY, HOME, KO
from tests.unit.test_match_intelligence import inputs as v1_inputs

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-01" / "v2"
V1_EXAMPLES = EXAMPLES.parent
FIXTURE = 990100
RIVAL = 990003


# ── the shadow of the fictitious match ───────────────────────────────────────────────────────────────────────────────

def objective(name: str, places: list[int], state: str, p: float | None, *, points: int, max_points: int, secure: int | None,
              kind: str, rivals: list[int], proved: bool = False) -> dict[str, Any]:
    return {"objetivo": name, "zona": "champion", "sentido": "lograr", "puestos": places, "terminar_entre_los": places[-1],
            "destino": None, "condicional": False, "estado": state, "exacto": True,
            "decidido": {"valor": proved, "demostrado": proved, "motivos": []}, "probabilidad": p,
            "necesita": {"puntos_actuales": points, "puntos_maximos": max_points, "partidos_restantes": 1,
                         "puntos_que_lo_aseguran": secure},
            "depende_de": {"tipo": kind, "rivales": rivals}}


READING: dict[str, Any] = {
    "version": "scenarios-v2", "at": (AT - timedelta(hours=2)).isoformat(), "league_id": 9901, "season": 2026, "status": "ok",
    "rules": {"status": "coded", "version": 3, "sha256": "0" * 64}, "contradicciones": 0,
    "tables": [{
        "key": "fase_final", "name": "Fase final", "kind": "group",
        "teams": [
            {"team": HOME, "puesto": 1, "puntos": 13, "objetivos": [
                objective("titulo", [1, 1], "abierto", 0.62, points=13, max_points=16, secure=3, kind="de_si_mismo", rivals=[AWAY])]},
            {"team": AWAY, "puesto": 3, "puntos": 10, "objetivos": [
                objective("titulo", [1, 1], "descartado", 0.0, points=10, max_points=13, secure=None, kind="decidido", rivals=[],
                          proved=True),
                objective("plaza_continental", [2, 3], "abierto", 0.71, points=10, max_points=13, secure=None, kind="de_otros",
                          rivals=[RIVAL])]}],
        "matches": {str(FIXTURE): {
            "home": {"team": HOME, "objetivos": [{"objetivo": "titulo", "terminar_entre_los": 1, "condicional": False,
                                                 "victoria": {"estado": "conseguido", "probabilidad": 1.0},
                                                 "empate": {"estado": "abierto", "probabilidad": 0.4},
                                                 "derrota": {"estado": "abierto", "probabilidad": 0.15}}]},
            "away": {"team": AWAY, "objetivos": [{"objetivo": "plaza_continental", "terminar_entre_los": 3, "condicional": False,
                                                 "victoria": {"estado": "conseguido", "probabilidad": 1.0},
                                                 "empate": {"estado": "abierto", "probabilidad": 0.66},
                                                 "derrota": {"estado": "abierto", "probabilidad": 0.38}}]}}}}],
    "teams": {str(HOME): {"hecho": None, "demostrado": False, "motivos": ["objetivo_abierto:fase_final:titulo"]},
              str(AWAY): {"hecho": None, "demostrado": False, "motivos": ["objetivo_abierto:fase_final:plaza_continental"]}},
}

PLAN = {"sections": [
    {"code": "que_se_juega", "abstention": None}, {"code": "como_llega", "abstention": None},
    {"code": "que_puede_definir", "abstention": None}, {"code": "estadisticas", "abstention": "SIN_ESTADISTICAS"},
    {"code": "jugadores", "abstention": None}, {"code": "novedades", "abstention": None},
    {"code": "riesgos", "abstention": "SIN_RIESGOS"}, {"code": "que_falta", "abstention": None}]}


def sentence(text: str, *facts: str) -> dict[str, Any]:
    return {"text": text, "facts": list(facts)}


SECTIONS_ES = {
    "que_se_juega": [sentence("El Club Ejemplo Norte depende de sí mismo para ganar el grupo: le bastan tres puntos.", "S:home.titulo")],
    "como_llega": [sentence("El local suma cuatro victorias en sus últimos seis partidos.", "F:home.form")],
    "que_puede_definir": [sentence("Una victoria local cierra el grupo.", "S:home.titulo")],
    "jugadores": [sentence("El portero titular del local es baja confirmada por el club.", "E:1")],
    "novedades": [sentence("El delantero visitante está en duda según la prensa local.", "E:2")],
}
SECTIONS_EN = {
    "que_se_juega": [sentence("Club Ejemplo Norte's group is in their own hands: three points are enough.", "S:home.titulo")],
    "como_llega": [sentence("The hosts have won four of their last six.", "F:home.form")],
    "que_puede_definir": [sentence("A home win settles the group.", "S:home.titulo")],
    "jugadores": [sentence("The hosts' first-choice keeper is out, the club confirmed.", "E:1")],
    "novedades": [sentence("The visitors' striker is a doubt, local press says.", "E:2")],
}


def chronicle_row(*, update: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 502 if update else 501, "created_at": (KO - timedelta(minutes=17)) if update else AT - timedelta(minutes=30),
        "plan_at": AT - timedelta(minutes=40), "version": "chronicle-v4", "plan_version": "content-plan-v1",
        "verify_version": "chronicle-verify-v1", "figure_version": "forecast-v2", "status": "partial", "plan": PLAN,
        "content": {"es": SECTIONS_ES, "en": SECTIONS_EN}, "custom_id": "lineup-update:77" if update else None}
    if update:
        base["content"] = base["content"] | {
            "actualizacion": {
                "version": "lineup-update-v1", "es": ["Las alineaciones oficiales se conocieron a las 17:41 (hora de Bogotá).",
                                                      "El portero titular del local no figura en la convocatoria."],
                "en": ["The official line-ups were known at 17:41 (Bogotá time).", "The hosts' first-choice keeper is not listed."],
                "superseded": [], "unplaced": []},
            "selecciones": [{
                "version": "selection-why-v1", "verdict_id": 9002, "decision_id": 8002, "market_key": "1X2", "selection": "Home",
                "line": "0.00", "state": "confirmada_sombra", "reason": "cumple_todo", "verdict": "confirmada",
                "phrases": [
                    {"es": "Tras la alineación oficial, «victoria local» sigue en pie: cumple todo.",
                     "en": "After the official line-up, «home win» still stands: it meets everything.",
                     "origin": {"kind": "decision", "verdict_id": 9002}},
                    {"es": "Una victoria local cierra el grupo.", "en": "A home win settles the group.",
                     "origin": {"kind": "chronicle", "chronicle_id": 501, "section": "que_puede_definir", "index": 0}}]}]}
    return base


def run(i: int, step: str, known: datetime, cause: str = "ventana") -> dict[str, Any]:
    return {"id": i, "evaluation": step, "evaluation_version": 1, "cause": cause, "known_at": known, "status": "completa",
            "decided": True, "latency_ms": 17 if step == "E3" else None, "error": None}


def verdict_row(run_id: int, step: str, known: datetime, verdict: str, state: str, reason: str, p: str, *, market: str = "1X2",
                selection: str = "Home", line: str = "0", calibrated: bool = True) -> dict[str, Any]:
    return {"run_id": run_id, "market_key": market, "selection": selection, "line": Decimal(line), "verdict": verdict, "state": state,
            "reason": reason, "evaluation": step, "evaluation_version": 1, "known_at": known, "p_after": Decimal(p),
            "odds_after": Decimal("1.62"), "price_state": "vigente", "decision_id": 8000 + run_id, "calibrated": calibrated}


E1 = run(1, "E1", KO - timedelta(hours=23))
E3 = run(3, "E3", KO - timedelta(minutes=19), "alineacion_oficial")
E4 = run(4, "E4", KO - timedelta(minutes=16))
VERDICTS_E1 = [verdict_row(1, "E1", E1["known_at"], "lectura", "pendiente_alineaciones", "depende_de_alineacion", "0.5879"),
               verdict_row(1, "E1", E1["known_at"], "lectura", "pendiente_alineaciones", "depende_de_alineacion", "0.5478",
                           market="AH", line="-0.5", calibrated=False)]
VERDICTS_E3 = [verdict_row(3, "E3", E3["known_at"], "confirmada", "confirmada_sombra", "cumple_todo", "0.5901"),
               verdict_row(3, "E3", E3["known_at"], "retirada", "retirada", "alineacion_en_contra", "0.5102", market="AH", line="-0.5",
                           calibrated=False)]

ALERT = {"id": 31, "kind": "retirada", "fixture_id": FIXTURE, "market_key": "AH", "selection": "Home", "line": Decimal("-0.5"),
         "cause": "alineacion_en_contra",
         "before": {"state": "pendiente_alineaciones", "reason": "depende_de_alineacion", "p": 0.5478, "odds": 1.95,
                    "price_state": "vigente", "players_out": []},
         "after": {"state": "retirada", "reason": "alineacion_en_contra", "p": 0.5102, "odds": 1.95, "price_state": "vigente",
                   "players_out": [990777]},
         "price": {"odds": 1.95, "state": "vigente", "at": (KO - timedelta(minutes=30)).isoformat(), "age_minutes": 11.0},
         "decision_id": 8003, "evaluation": "E3", "evaluation_version": 1, "known_at": E3["known_at"], "kickoff_at": KO}


def chain(state: str, reason: str, market: str = "1X2", line: str = "0") -> dict[str, Any]:
    return {"market_key": market, "selection": "Home", "line": Decimal(line), "state": state, "reason": reason}


DECISION_IDS = [{"market_key": "1X2", "selection": "Home", "line": Decimal("0"), "id": 7101},
                {"market_key": "AH", "selection": "Home", "line": Decimal("-0.5"), "id": 7102}]


def player(pid: int, name: str, p: str, *, evaluation: str = "E1", known: datetime = KO - timedelta(hours=23),
           basis: str = "minutos_recientes", confirmed: bool = False, p_start: str = "0.8800") -> dict[str, Any]:
    return {"team_id": HOME, "team_name": "Club Ejemplo Norte", "provider_player_id": pid, "player_name": name, "family": "player_goals",
            "line": Decimal("0.5"), "p_over": Decimal(p), "seal": "sin_calibrar", "p_start": Decimal(p_start),
            "expected_minutes": Decimal("74.5"), "start_basis": basis, "lineup_confirmed": confirmed, "evaluation": evaluation,
            "known_at": known, "version": "player-engine-v2"}


PLAYERS_E1 = [player(990701, "J. Ejemplo", "0.3412"), player(990702, "P. Muestra", "0.2207", p_start="0.6100")]
PLAYERS_E4 = [player(990701, "J. Ejemplo", "0.3655", evaluation="E4", known=E4["known_at"], basis="confirmed_starter",
                     confirmed=True, p_start="1")]

AVAILABILITY: dict[str, TeamAvailability | Missing] = {
    "home": TeamAvailability(fixture_id=FIXTURE, report_checked_at=AT - timedelta(hours=5), unavailable=mi._list([AvailabilityEntry(
        player_id=990801, name="R. Ejemplo", status="baja", basis="oficial", source="club-ejemplo-norte.invalid",
        known_at=AT - timedelta(hours=3, minutes=1), fixture_id=FIXTURE)], mi.NO_DATA)),
    "away": Missing(missing_reason="sin_cobertura")}


def sources(at: datetime) -> Any:
    return analysis_sources.assemble(FIXTURE, [], None, [], published=None, at=at)


def shadow(case: str, at: datetime) -> m2.Shadow:
    before = m2.Shadow(scenario=READING, chronicle=chronicle_row(update=False), attempts=2, runs=[E1], verdicts=VERDICTS_E1, alerts=[],
                       lifecycle=[chain("pendiente_alineaciones", "depende_de_alineacion"),
                                  chain("pendiente_alineaciones", "depende_de_alineacion", "AH", "-0.5")],
                       decision_ids=DECISION_IDS, sources=sources(at), players=PLAYERS_E1)
    if case in ("antes_del_partido", "bloques_publicados"):
        return before
    after = replace(before, chronicle=chronicle_row(update=True), attempts=3, runs=[E1, E3, E4], verdicts=VERDICTS_E1 + VERDICTS_E3,
                    alerts=[ALERT], players=PLAYERS_E4,
                    lifecycle=[chain("confirmada_sombra", "cumple_todo"), chain("retirada", "alineacion_en_contra", "AH", "-0.5")])
    if case == "con_alineacion_oficial":
        return after
    if case == "terminado":
        return replace(after, lifecycle=[chain("liquidada", "resultado"), chain("descartada", "retirada_al_saque", "AH", "-0.5")])
    if case == "sin_tablas":
        return m2.Shadow(scenario_missing=Missing(missing_reason="no_entregado", expected_piece="AD-B02"),
                         chronicle_missing=Missing(missing_reason="no_entregado", expected_piece="AD-F02"), runs=None, alerts=None,
                         lifecycle=None, decision_ids=DECISION_IDS, sources=sources(at), players=None)
    raise ValueError(case)


CASES = ("antes_del_partido", "con_alineacion_oficial", "terminado", "bloques_publicados", "sin_tablas")


def inputs(case: str) -> m2.InputsV2:
    base = v1_inputs("antes_del_partido" if case in ("bloques_publicados", "sin_tablas") else case)
    published = frozenset(m2.SHADOW_BLOCKS) if case == "bloques_publicados" else frozenset()
    return m2.InputsV2(base=base, shadow=shadow(case, base.at), availability=AVAILABILITY, availability_shown=True, published=published)


def answers(case: str) -> tuple[MatchIntelligenceV2Private, MatchIntelligenceV2]:
    private = m2.assemble(inputs(case))
    return private, to_public(private, MatchIntelligenceV2)


def dumped(model: MatchIntelligenceV2) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def write_examples() -> None:
    """Rewrites the examples from the cases above (run by hand after a deliberate change; the test below holds them)."""
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        private, public = answers(case)
        for name, model in (("private", private), ("public", public)):
            (EXAMPLES / f"{case}.{name}.json").write_text(json.dumps(dumped(model), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── the examples and the leak check ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES)
def test_each_example_is_what_the_builder_makes_of_its_case(case: str) -> None:
    private, public = answers(case)
    for name, model in (("private", private), ("public", public)):
        stored = json.loads((EXAMPLES / f"{case}.{name}.json").read_text(encoding="utf-8"))
        assert dumped(model) == stored, f"{case}.{name}.json is stale: rewrite it with write_examples()"


PRIVATE_WORDS = ("raw_probability", "decision_state", "RECHAZADO", "CAUTELA", "brief", "Texto propio", "evidence", "story_key", "fair_odds",
                 "lifecycle_reason", "decision_id", "selection_whys", "verdicts", "player_forecasts", "player-engine", "alerts", "AH",
                 "cumple_todo", "alineacion_en_contra", "decision-v2", "evaluacion_e", "J. Ejemplo", "scenarios_shadow", "C-07")


@pytest.mark.parametrize("case", CASES)
def test_the_public_projection_leaks_nothing(case: str) -> None:
    _, public = answers(case)
    found = leaks(dumped(public), public_schema=MatchIntelligenceV2.model_json_schema(mode="serialization"),
                  private_schema=MatchIntelligenceV2Private.model_json_schema(mode="serialization"))
    assert found == []
    text = json.dumps(dumped(public), ensure_ascii=False)
    for word in PRIVATE_WORDS:
        assert word not in text, word


# ── 1.x does not change ──────────────────────────────────────────────────────────────────────────────────────────────

def test_1x_keeps_its_classes_its_version_its_routes_and_its_examples() -> None:
    old, new = by_key()["C-01@1"], by_id()["C-01"]
    assert (old.private, old.public, old.version, old.superseded) == (MatchIntelligencePrivate, MatchIntelligence, "1.1.0", True)
    assert old.public_routes == ("/api/v1/matches/{fixture_id}/intelligence",)
    assert old.private_routes == ("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence",)
    assert old.examples_dir == "C-01" and sorted(p.name for p in V1_EXAMPLES.glob("*.json"))[0] == "antes_del_partido.private.json"
    assert (new.private, new.public, new.version, new.key) == (MatchIntelligenceV2Private, MatchIntelligenceV2, "2.0.0", "C-01")
    assert new.public_routes == ("/api/v1/matches/{fixture_id}/intelligence/v2",)
    assert new.private_routes == ("/api/v1/admin/intelligence/matches/{fixture_id}/intelligence/v2",)
    assert new.examples_dir == "C-01/v2"
    v1_private = mi.assemble(v1_inputs("antes_del_partido"))
    assert v1_private.contract_version == "1.1.0" and v1_private.scenarios == Missing(missing_reason="no_entregado",
                                                                                     expected_piece="AD-B02")


def test_the_new_classes_rename_no_schema_of_the_api() -> None:
    from fbi.api.contracts.intelligence import match_v2

    ours = {n for n, c in vars(match_v2).items() if isinstance(c, type) and c.__module__ == match_v2.__name__}
    assert ours and all(n.startswith(("MatchV2", "MatchIntelligenceV2")) for n in ours), sorted(ours)


# ── what a reader is shown, and what only the owner sees ─────────────────────────────────────────────────────────────

def test_the_shadow_blocks_reach_the_public_only_once_published() -> None:
    private, public = answers("con_alineacion_oficial")
    kept = Missing(missing_reason="pendiente_derechos")
    assert (public.scenarios, public.chronicle, public.evaluations) == (kept, kept, kept)
    assert isinstance(private.scenarios_shadow, MatchV2Scenarios) and isinstance(private.chronicle_shadow, MatchV2Chronicle)
    assert not isinstance(private.evaluations_shadow, Missing) and len(private.evaluations_shadow.items) == 3
    # published (hypothetical: no block is published today) - the same values, without what is private
    assert frozenset() == m2.PUBLISHED_BLOCKS
    priv, pub = answers("bloques_publicados")
    assert pub.scenarios == priv.scenarios_shadow
    assert isinstance(pub.chronicle, MatchV2Chronicle) and not hasattr(pub.chronicle, "selection_whys")
    assert not isinstance(pub.evaluations, Missing) and [e.evaluation for e in pub.evaluations.items] == ["E1"]
    assert not hasattr(pub.evaluations.items[0], "verdicts")


def test_the_public_read_does_not_read_the_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("a shadow table was read for the public answer")

    monkeypatch.setattr(m2, "_rows", refuse)
    monkeypatch.setattr(m2, "fetch_one", refuse)
    monkeypatch.setattr(m2, "fetch_all", refuse)
    monkeypatch.setattr(analysis_sources, "build", refuse)
    sh = m2.read_shadow(object(), FIXTURE, AT, private=False, published=frozenset())  # type: ignore[arg-type]
    assert sh == m2.Shadow(read=False)
    private = m2.assemble(replace(inputs("con_alineacion_oficial"), shadow=sh))
    assert private.scenarios_shadow == private.sources == private.alerts == Missing(missing_reason="sin_datos")


def test_59_calibrated_for_the_reader_and_78_5_uncalibrated_only_for_the_owner() -> None:
    private, public = answers("antes_del_partido")
    pub = next(f for f in public.probabilities.items if f.market == "1X2" and f.outcome == "home")
    priv = next(f for f in private.probabilities.items if f.market == "1X2" and f.outcome == "home")
    assert (pub.probability.pct, pub.probability.calibration) == (59, "calibrada")
    assert (priv.raw_probability.pct, priv.raw_probability.calibration) == (78.5, "sin_calibrar")


# ── the blocks ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_scenarios_say_what_each_side_needs_what_it_depends_on_and_what_is_proved() -> None:
    private, _ = answers("antes_del_partido")
    scen = private.scenarios_shadow
    assert isinstance(scen, MatchV2Scenarios) and scen.version == SCENARIOS_ORIGIN and scen.rules_version == 3
    home, away = scen.sides
    [title] = home.objectives.items
    assert (title.objective, title.state, title.decided.proved) == ("titulo", "abierto", False)
    assert title.needs.points_that_secure == 3 and title.depends_on.kind == "de_si_mismo" and title.depends_on.rivals == [AWAY]
    assert isinstance(title.probability, Probability) and (title.probability.pct, title.probability.calibration) == (62, "sin_calibrar")
    assert title.probability.origin == "scenarios-v2"
    assert [(r.result, r.state) for r in title.after_result.items] == [("victoria", "conseguido"), ("empate", "abierto"),
                                                                       ("derrota", "abierto")]
    lost, europe = away.objectives.items
    assert lost.decided.proved and lost.state == "descartado" and lost.depends_on.kind == "decidido"
    assert lost.needs.points_that_secure == Missing(missing_reason="sin_datos")
    assert lost.after_result.items == [] and lost.after_result.missing_reason == "sin_datos"
    assert europe.after_result.items[2].probability.pct == 38  # type: ignore[union-attr]
    assert not home.no_objective_proved and home.no_objective_reasons == ["objetivo_abierto:fase_final:titulo"]


def test_a_reading_of_a_season_without_coded_rules_says_so() -> None:
    fx = v1_inputs("antes_del_partido").fixture
    assert m2.scenarios(None, fx, Missing(missing_reason="reglamento_no_codificado")) == Missing(missing_reason="reglamento_no_codificado")


def test_the_chronicle_goes_by_the_plans_eight_sections_and_its_update() -> None:
    private, _ = answers("antes_del_partido")
    chron = private.chronicle_shadow
    assert isinstance(chron, MatchV2Chronicle)
    assert [s.code for s in chron.sections] == list(m2.CHRONICLE_SECTIONS)
    by = {s.code: s for s in chron.sections}
    assert by["riesgos"].abstention == "SIN_RIESGOS" and by["riesgos"].es == []
    assert by["que_falta"].abstention == m2.NO_SENTENCE, "planned but nothing stood: said"
    assert by["jugadores"].es and by["jugadores"].abstention == Missing(missing_reason="sin_datos")
    assert chron.lineup_update == Missing(missing_reason="aun_no_disponible", expected_at=KO - timedelta(minutes=20))
    after, _ = answers("con_alineacion_oficial")
    upd = after.chronicle_shadow
    assert isinstance(upd, type(chron)) and not isinstance(upd.lineup_update, Missing)
    assert upd.lineup_update.version == "lineup-update-v1" and upd.chronicle_id == 502 and upd.attempts == 3
    [why] = upd.selection_whys
    assert [p.origin for p in why.phrases] == ["decision", "chronicle"]


def test_e1_to_e4_keep_every_version_with_decision_v2s_seal() -> None:
    private, _ = answers("terminado")
    evals = private.evaluations_shadow
    assert not isinstance(evals, Missing)
    assert [(e.evaluation, e.evaluation_version) for e in evals.items] == [("E1", 1), ("E3", 1), ("E4", 1)]
    e3 = evals.items[1]
    confirmed, withdrawn = e3.verdicts.items
    assert (confirmed.verdict, confirmed.state) == ("confirmada", "confirmada_sombra")
    assert isinstance(confirmed.probability, Probability)
    assert (confirmed.probability.evaluation, confirmed.probability.evaluation_version) == ("E3", 1)
    assert confirmed.probability.calibration == "calibrada" and confirmed.probability.origin == "decision-v2"
    assert withdrawn.probability.calibration == "sin_calibrar"  # type: ignore[union-attr]
    assert e3.latency_ms == 17 and evals.items[2].verdicts.missing_reason == "sin_datos"


def test_the_selections_carry_c02s_cycle_privately_and_only_the_published_reach_a_reader() -> None:
    private, public = answers("con_alineacion_oficial")
    states = {(s.market, s.line): s for s in private.selections.items}
    home, ah = states[("1X2", 0.0)], states[("AH", -0.5)]
    assert (home.lifecycle_state, home.lifecycle_reason, home.decision_id) == ("confirmada_sombra", "cumple_todo", 7101)
    assert (ah.lifecycle_state, ah.decision_id, ah.public_state) == ("retirada", 7102, None)
    assert home.market_state == "evaluable"
    [published] = public.selections.items
    assert (published.market, published.public_state) == ("1X2", "publicada")
    assert "AH" not in {m.market_key for m in public.markets.items}, "the market of an unpublished selection stays private"
    assert "AH" in {m.market_key for m in private.markets.items}


def test_c05_c07_and_the_player_engine_are_embedded_only_privately() -> None:
    private, _ = answers("con_alineacion_oficial")
    assert not isinstance(private.alerts, Missing) and [a.kind for a in private.alerts.items] == ["retirada"]
    assert not private.alerts.items[0].notifies_reader
    assert not isinstance(private.sources, Missing) and private.sources.contract == "C-07"
    assert not isinstance(private.player_forecasts, Missing)
    [line] = private.player_forecasts.items
    assert (line.evaluation, line.pct_over, line.start_basis, line.calibration) == ("E4", 36.6, "confirmed_starter", "sin_calibrar")


def test_availability_is_a_state_a_basis_a_source_and_a_date_and_follows_fbi_profiles() -> None:
    _, public = answers("antes_del_partido")
    [home] = public.availability.items
    [entry] = home.unavailable.items
    assert (entry.status, entry.basis, entry.source) == ("baja", "oficial", "club-ejemplo-norte.invalid")
    hidden = to_public(m2.assemble(replace(inputs("antes_del_partido"), availability_shown=False)), MatchIntelligenceV2)
    assert hidden.availability.items == [] and hidden.availability.missing_reason == "pendiente_derechos"
    none = m2.assemble(replace(inputs("antes_del_partido"), availability={"home": Missing(missing_reason="sin_cobertura"),
                                                                           "away": Missing(missing_reason="sin_cobertura")}))
    assert none.availability.missing_reason == "sin_cobertura"


def test_what_is_new_and_what_is_pending() -> None:
    private, public = answers("antes_del_partido")
    assert [f.n for f in public.new_since_yesterday.items] == [1, 2]
    assert [(p.what, p.expected_at) for p in public.pending_unknowns.items] == [("alineacion_oficial", KO - timedelta(minutes=20))]
    assert {p.what for p in private.pending_unknowns.items} == {"alineacion_oficial", "evaluacion_e3", "evaluacion_e4"}
    over, _ = answers("terminado")
    assert over.pending_unknowns.items == [] and over.pending_unknowns.missing_reason == "sin_datos"
    for c in public.citations.items:
        assert c.relation == Missing(missing_reason="pendiente_derechos"), "the relation lives in C-07, once published"


def test_a_database_without_the_pieces_tables_says_which_piece() -> None:
    private, public = answers("sin_tablas")
    assert private.scenarios_shadow == Missing(missing_reason="no_entregado", expected_piece="AD-B02")
    assert private.chronicle_shadow == Missing(missing_reason="no_entregado", expected_piece="AD-F02")
    assert private.evaluations_shadow == Missing(missing_reason="no_entregado", expected_piece="AD-D06")
    assert private.alerts == Missing(missing_reason="no_entregado", expected_piece="AD-D08")
    assert private.player_forecasts == Missing(missing_reason="no_entregado", expected_piece="AD-B08")
    assert {s.lifecycle_state for s in private.selections.items} == {Missing(missing_reason="no_entregado", expected_piece="AD-D02")}
    assert [p.what for p in private.pending_unknowns.items] == ["alineacion_oficial"]
    assert public.scenarios == Missing(missing_reason="pendiente_derechos")


# ── the constants copied to keep the import cycle from growing ──────────────────────────────────────────────────────

def test_the_copied_constants_equal_their_sources() -> None:
    from fbi.chronicle import inputs as chronicle_inputs
    from fbi.chronicle import plan, update_job
    from fbi.chronicle import update as chronicle_update
    from fbi.competitions import scenarios
    from fbi.evalcycle import clock

    assert SCENARIOS_ORIGIN == scenarios.VERSION and m2.SCENARIOS_MAX_AGE == chronicle_inputs.SCENARIOS_MAX_AGE
    assert m2.CHRONICLE_SECTIONS == plan.SECTIONS and m2.UPDATE_PREFIX == update_job.CUSTOM_PREFIX
    assert chronicle_update.VERSION == "lineup-update-v1"
    assert (m2.E1_FROM, m2.E1_UNTIL, m2.E4_FROM) == (clock.E1_FROM, clock.E1_UNTIL, clock.E4_FROM)
    assert tuple(scenarios._outcome_name("home", o) for o in scenarios.OUTCOMES) == m2.RESULT_WORDS


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────────────────────

def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import ROLE_PERMISSIONS, Role
    from fbi.auth.service import Principal

    principal = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role.USER, language="es",
                          timezone="America/Bogota", session_id="s", session_expires_at=KO,
                          permissions=frozenset(ROLE_PERMISSIONS[Role.USER]))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(m2, "read", lambda conn, fixture_id, at=None, private=False: inputs("con_alineacion_oficial"))
    return TestClient(app, raise_server_exceptions=False)


def test_the_public_route_is_404_while_the_switch_is_off_and_the_projection_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MATCH_INTELLIGENCE, raising=False)
    with client(monkeypatch) as c:
        assert c.get(f"/api/v1/matches/{FIXTURE}/intelligence/v2").status_code == 404
        monkeypatch.setenv(MATCH_INTELLIGENCE, "1")
        answer = c.get(f"/api/v1/matches/{FIXTURE}/intelligence/v2")
        assert answer.status_code == 200, answer.text
        data = answer.json()["data"]
        assert (data["contract"], data["contract_version"], data["projection"]) == ("C-01", "2.0.0", "public")
        assert "scenarios_shadow" not in data and data["scenarios"] == {"missing_reason": "pendiente_derechos"}
        assert c.get(f"/api/v1/admin/intelligence/matches/{FIXTURE}/intelligence/v2").status_code == 403

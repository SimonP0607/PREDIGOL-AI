"""C-02, the selection's contract, read for both projections (AD-J03, IA-114). Reading only.

One builder (``private``) makes the PRIVATE answer from what was stored: the decision of ``intel.decisions`` (decision-v1 or the
families' decision-fam-v1, read - ``fbi.intel.decision`` is not imported), every decision of the same selection and layer (its
versions), the sources it cited (``fbi.evaluation.sources.sources``: by id, with the question every reader of ``ai.evidence`` asks), its
chain in the cycle of states (``intel.selection_lifecycle``, where the table is), the state of its market (``market_states.json``,
AD-E01), the board's verdict on its market (AD-K02, over the evaluations of the last ``BOARD_DAYS`` days) and its evaluation after the
match (AD-K01). The PUBLIC answer is ``to_public`` of it, and exists only for a selection the owner authorised (``public_state``) while
``FBI_MATCH_INTELLIGENCE`` is on: ``public_for_pick`` returns None otherwise, and «Explícame» answers exactly as before.

Every line of «Por qué», «En contra» and «De qué depende» is a template of this module over the stored numbers and codes; no model
writes any of it. No number is recomputed: the percentages are rounded once (``Probability.of``), the fair odds are 1/p rounded to two
decimals, and the expected value is the decision's own.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fbi.ai.gates import typed_visible
from fbi.api.contracts.intelligence.base import (
    Freshness,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    Source,
)
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.selection import (
    PRICE_RULES,
    Band,
    Dependency,
    EvaluationSummary,
    ExpectedValue,
    MarketStatusRef,
    PriceState,
    PriceView,
    Reason,
    SelectionIntelligence,
    SelectionIntelligencePrivate,
    SelectionRef,
    SettlementRuleView,
    SourceUsed,
    Version,
)
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import market_status
from fbi.api.switches import match_intelligence_on
from fbi.core.clock import now as clock_now
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.evaluation import sources as evaluation_sources
from fbi.evaluation import views
from fbi.lifecycle import machine
from fbi.lifecycle.reader import family_of
from fbi.lifecycle.store import WRITER as LIFECYCLE_WRITER

ORIGIN: Final = "decision-v1"
LAYERS: Final = (DECISION_CORE, DECISION_FAMILIES)
BOARD_DAYS: Final = 30
CORE_MARKETS: Final = frozenset({"1X2", "DC", "OU", "BTTS", "AH"})

DECISION_SQL: Final = """
SELECT d.id, d.decision_version, d.fixture_id, d.market_key, d.selection, d.line, d.known_at, d.kickoff_at, d.checkpoint, d.state,
       d.p_model::float8 AS p_model, d.p_low::float8 AS p_low, d.p_high::float8 AS p_high, d.p_cal::float8 AS p_cal,
       d.p_market::float8 AS p_market, d.ev_cal::float8 AS ev_cal, d.odds::float8 AS odds, d.price_at, d.n_bookmakers, d.reasons,
       d.context_status, d.evidence_ids
  FROM intel.decisions d WHERE d.id = %(id)s AND d.decision_version = ANY(%(layers)s)
"""
HISTORY_SQL: Final = """
SELECT d.id, d.known_at, d.checkpoint, d.state, d.p_model::float8 AS p_model, d.p_cal::float8 AS p_cal, d.odds::float8 AS odds
  FROM intel.decisions d
 WHERE d.fixture_id = %(f)s AND d.market_key = %(m)s AND d.selection = %(s)s AND d.line = %(l)s AND d.decision_version = %(v)s
 ORDER BY d.known_at, d.id LIMIT 60
"""
PICK_DECISION_SQL: Final = """
SELECT d.id FROM intel.decisions d WHERE d.pick_id = %(pick)s AND d.decision_version = %(v)s ORDER BY d.known_at DESC, d.id DESC LIMIT 1
"""
LIFECYCLE_SQL: Final = """
SELECT state, reason, actor, owner_signature, settlement_result, evaluation, evaluation_version
  FROM intel.selection_lifecycle WHERE chain_key = %(k)s ORDER BY id
"""
EXISTS_SQL: Final = "SELECT to_regclass('intel.selection_lifecycle') IS NOT NULL AS ok"

REASON_TEXT: Final[dict[str, str]] = {
    "data": "Faltan datos del partido para decidir.",
    "model": "No hay modelo para este mercado.",
    "no_price": "No hay precio en el mercado.",
    "thin_market": "Pocas casas cotizan este mercado.",
    "price_outlier": "La mejor cuota se aleja demasiado del consenso.",
    "context_stop": "El contexto del partido lo impide.",
    "key_absence_confirmed": "Una baja clave está confirmada.",
    "ev_cal_below": "El valor esperado no supera el mínimo.",
    "not_calibrated": "La probabilidad no está calibrada.",
    "ev_unknown": "No se puede calcular el valor esperado.",
    "price_stale": "El precio es antiguo.",
    "price_not_fresh": "El precio no es reciente en el último corte.",
    "ai_reject": "La revisión en contra.",
    "ai_downgrade": "La revisión rebaja la selección.",
    "key_absence_reported": "Hay una baja clave por confirmar.",
    "correlated_same_match": "Otra selección del mismo partido ya ocupa su sitio.",
    "risk": "Riesgo señalado.",
    "edge_not_validated": "La ventaja de su mercado no está validada fuera de muestra.",
    "family_shadow_only": "Su familia de mercados solo decide en sombra.",
}
"""decision-v1's reason codes (``fbi.lifecycle.derive.BLOCKER_OF`` and ``MARKET_LEVEL``) in Spanish, a template per code."""

SIDE: Final[dict[str, str]] = {"Home": "local", "Away": "visitante", "Draw": "empate"}


def _num(x: float | Decimal) -> str:
    return f"{float(x):g}".replace(".", ",")


def label_es(market: str, selection: str, line: Decimal) -> str | Missing:
    """How the selection reads in Spanish, for the core markets (a template; the other families wait for the catalogue's labels)."""
    if market == "1X2":
        return {"Home": "Gana el local", "Draw": "Empate", "Away": "Gana el visitante"}.get(selection) or Missing(missing_reason="sin_datos")
    if market == "DC":
        return {"1X": "Local o empate", "X2": "Empate o visitante", "12": "Local o visitante"}.get(selection) or Missing(
            missing_reason="sin_datos")
    if market == "OU" and selection in ("Over", "Under"):
        return f"{'Más' if selection == 'Over' else 'Menos'} de {_num(line)} goles"
    if market == "BTTS" and selection in ("Yes", "No"):
        return f"Ambos marcan: {'sí' if selection == 'Yes' else 'no'}"
    if market == "AH" and selection in ("Home", "Away"):
        return f"Hándicap asiático {SIDE[selection]} {'+' if line > 0 else ''}{_num(line)}"
    if market.startswith("CORNERS_OU") and selection in ("Over", "Under"):
        return f"{'Más' if selection == 'Over' else 'Menos'} de {_num(line)} córners"
    if market.startswith("CARDS_OU") and selection in ("Over", "Under"):
        return f"{'Más' if selection == 'Over' else 'Menos'} de {_num(line)} tarjetas"
    return Missing(missing_reason="sin_datos")


def price_state(*, age: timedelta | None, checkpoint: str) -> PriceState:
    """The state of a decision-v1 price by its rule, ``price-age-v1`` (``PRICE_RULES``: the code's ``price_age.V1`` as data): a price
    without an age is in force (the rule does not ask for one); older than 3 h, or than 30 min at a final checkpoint, it is old."""
    r = PRICE_RULES["price-age-v1"]
    limit = int(r["limits_min"][0])  # type: ignore[index]
    if checkpoint in r["final_checkpoints"]:  # type: ignore[operator]
        limit = min(limit, int(r["final_min"]))  # type: ignore[call-overload]
    if age is None:
        return "vigente"
    return "vigente" if age <= timedelta(minutes=limit) else "antiguo"


def _probability(p: float, *, calibrated: bool, at: datetime, low: float | None = None, high: float | None = None) -> Probability:
    band: tuple[int, int] | Missing = Missing(missing_reason="sin_datos")
    if low is not None and high is not None and low <= p <= high:
        band = (round(low * 100), round(high * 100))
        if not band[0] <= round(p * 100) <= band[1]:
            band = Missing(missing_reason="sin_datos")
    return Probability.of(p, calibration="calibrada" if calibrated else "sin_calibrar", as_of=at, origin=ORIGIN,
                          evaluation=Missing(missing_reason="no_entregado", expected_piece="AD-D06"),
                          evaluation_version=Missing(missing_reason="no_entregado", expected_piece="AD-D06"), interval=band)


def _reasons_for(d: dict[str, Any]) -> list[Reason]:
    out: list[Reason] = []
    p = d["p_cal"] if d["p_cal"] is not None else d["p_model"]
    if d["p_market"] is not None and p > d["p_market"]:
        out.append(Reason(code="probabilidad_sobre_mercado",
                          text_es=f"PrediGol estima un {round(p * 100)} % frente al {round(d['p_market'] * 100)} % del mercado sin margen."))
    if d["ev_cal"] is not None and d["ev_cal"] > 0 and d["odds"] is not None:
        out.append(Reason(code="valor_esperado_positivo",
                          text_es=f"Valor esperado de {f'{d['ev_cal'] * 100:+.1f}'.replace('.', ',')} % a la cuota {_num(d['odds'])}."))
    return out


def _reasons_against(d: dict[str, Any]) -> list[Reason]:
    seen: list[Reason] = []
    for code in d["reasons"] or []:
        if code == "family_research":
            continue
        seen.append(Reason(code=code if code.replace("_", "").isalnum() and code.islower() else "otro",
                           text_es=REASON_TEXT.get(code, f"Motivo del sistema: {code}.")))
    return seen


def _depends_on(d: dict[str, Any], lineup_at: datetime | None) -> list[Dependency]:
    out: list[Dependency] = []
    codes = set(d["reasons"] or [])
    if "key_absence_reported" in codes and (lineup_at is None or lineup_at > d["known_at"]):
        out.append(Dependency(code="alineacion_oficial", text_es="Que la alineación oficial confirme la baja que se ha reportado."))
    if d["context_status"] == "PENDING":
        out.append(Dependency(code="contexto_del_partido", text_es="Que se complete la lectura del contexto del partido."))
    if codes & {"price_stale", "price_not_fresh"}:
        out.append(Dependency(code="precio_vigente", text_es="Que haya un precio vigente antes del saque."))
    if codes & {"edge_not_validated", "family_shadow_only"}:
        out.append(Dependency(code="validacion_del_mercado", text_es="Que su mercado quede validado en el tablero (AD-K02)."))
    return out


def _settlement(market: str) -> SettlementRuleView:
    if market in CORE_MARKETS:
        return SettlementRuleView(rule="settle-v4", text_es="Se liquida con el marcador de los 90 minutos y el añadido; la prórroga y "
                                                           "los penaltis no cuentan. Las líneas de cuarto son dos medias apuestas.")
    rule = market_status.load_catalogue().status(market).entry.rule_key
    if rule is None:
        return SettlementRuleView(rule="sin_regla", text_es="Ninguna regla registrada liquida este mercado.")
    return SettlementRuleView(rule=rule, text_es=f"Se liquida con el conteo del partido por la regla {rule}.")


def _versions(rows: list[dict[str, Any]]) -> list[Version]:
    out: list[Version] = []
    previous: str | None = None
    for r in rows:
        p = r["p_cal"] if r["p_cal"] is not None else r["p_model"]
        change = "Primera decisión." if previous is None else (
            "Sin cambio de estado." if previous == r["state"] else f"Pasa de {previous} a {r['state']}.")
        out.append(Version(at=r["known_at"], checkpoint=str(r["checkpoint"]), state=str(r["state"]), probability_pct=round(p * 100, 1),
                           best_odds=Missing(missing_reason="sin_datos") if r["odds"] is None else float(r["odds"]), change_es=change))
        previous = str(r["state"])
    return out


def _chain(conn: Conn, d: dict[str, Any]) -> list[machine.Step] | None:
    if not (fetch_one(conn, EXISTS_SQL, {}) or {}).get("ok"):
        return None
    key = f"{LIFECYCLE_WRITER}|{d['fixture_id']}|{d['market_key']}|{d['selection']}|{Decimal(d['line']).quantize(Decimal('0.01'))}"
    rows = fetch_all(conn, LIFECYCLE_SQL, {"k": key})
    return [machine.Step(str(r["state"]), str(r["reason"]), str(r["actor"]), r["owner_signature"], r["settlement_result"],
                         r["evaluation"], r["evaluation_version"]) for r in rows]


def _items[T](items: list[T], reason: str = "sin_datos") -> ItemList[T]:
    if items:
        return ItemList[T](items=items)
    return ItemList[T](items=[], missing_reason=reason)  # type: ignore[arg-type]


def private(conn: Conn, decision_id: int, *, at: datetime | None = None) -> SelectionIntelligencePrivate:
    """The private C-02 of one decision of ``intel.decisions``. 404 for a decision of no followed layer."""
    moment = at or clock_now()
    d = fetch_one(conn, DECISION_SQL, {"id": decision_id, "layers": list(LAYERS)})
    if d is None:
        raise ApiError(404, "not_found", "no such decision")
    line = Decimal(d["line"])
    history = fetch_all(conn, HISTORY_SQL, {"f": d["fixture_id"], "m": d["market_key"], "s": d["selection"], "l": d["line"],
                                            "v": d["decision_version"]})
    cited = sorted(int(i) for i in d["evidence_ids"] or [])
    sources = [SourceUsed(id=int(s["id"]), kind=str(s["kind"]),
                          source=Source(name=str(s["source_name"] or "sin nombre"),
                                        url=Missing(missing_reason="sin_datos") if not s["source_url"] else str(s["source_url"])),
                          known_at=s["retrieved_at"]) for s in evaluation_sources.sources(conn, cited, typed=typed_visible(conn))]
    calibrated = d["p_cal"] is not None
    p = float(d["p_cal"] if calibrated else d["p_model"])
    probability = _probability(p, calibrated=calibrated, at=d["known_at"],
                               low=d["p_low"] if not calibrated else None, high=d["p_high"] if not calibrated else None)
    raw = _probability(float(d["p_model"]), calibrated=False, at=d["known_at"], low=d["p_low"], high=d["p_high"])
    odds = d["odds"]
    price: PriceView | Missing = Missing(missing_reason="sin_datos")
    if odds is not None and odds > 1:
        age = None if d["price_at"] is None else d["known_at"] - d["price_at"]
        price = PriceView(best_odds=float(odds), books=Missing(missing_reason="sin_datos") if d["n_bookmakers"] is None
                          else int(d["n_bookmakers"]), seen_at=Missing(missing_reason="sin_datos") if d["price_at"] is None
                          else d["price_at"], age_minutes=Missing(missing_reason="sin_datos") if age is None
                          else round(age.total_seconds() / 60, 1), price_state=price_state(age=age, checkpoint=str(d["checkpoint"])),
                          price_rule="price-age-v1", thresholds_min=[30, 180])
    ev: ExpectedValue | Missing = Missing(missing_reason="sin_datos")
    if d["ev_cal"] is not None:
        band: Band | Missing = Missing(missing_reason="sin_datos")
        if odds is not None and d["p_low"] is not None and d["p_high"] is not None and not calibrated:
            band = Band(low=round((odds * d["p_low"] - 1) * 100, 1), high=round((odds * d["p_high"] - 1) * 100, 1))
        ev = ExpectedValue(pct=round(float(d["ev_cal"]) * 100, 1), interval_pct=band)
    chain = _chain(conn, d)
    public_state = None if not chain else machine.public_state(chain)
    family = family_of(str(d["market_key"]))
    status = market_status.load_catalogue().status(str(d["market_key"]))
    validation, cell = _validation(conn, str(d["decision_version"]), family, str(d["market_key"]), moment)
    lineup_at = evaluation_sources.lineup_seen(conn, int(d["fixture_id"]))
    return SelectionIntelligencePrivate(
        freshness=Freshness(generated_at=moment, stale=False),
        selection=SelectionRef(fixture_id=int(d["fixture_id"]), market=str(d["market_key"]), selection=str(d["selection"]),
                               line=float(line), family=family,  # type: ignore[arg-type]  # family_of answers one of the four
                               label_es=label_es(str(d["market_key"]), str(d["selection"]), line)),
        public_state=public_state,  # type: ignore[arg-type]  # the cycle's PUBLIC map gives one of the three words
        probability=probability,
        fair_odds=round(1 / p, 2) if p > 0 else Missing(missing_reason="sin_datos"),
        expected_value=ev, price=price,
        reasons_for=_items(_reasons_for(d)), reasons_against=_items(_reasons_against(d)),
        depends_on=_items(_depends_on(d, lineup_at)), settlement_rule=_settlement(str(d["market_key"])),
        versions=_items(_versions(history)), sources=_items(sources),
        market_status=MarketStatusRef(market_key=str(d["market_key"]), state=status.state, reason=status.reason),  # type: ignore[arg-type]
        decision_id=int(d["id"]), layer=str(d["decision_version"]), decision_state=str(d["state"]),
        lifecycle_state=Missing(missing_reason="sin_datos") if not chain else chain[-1].state,  # type: ignore[arg-type]
        lifecycle_reason=Missing(missing_reason="sin_datos") if not chain else chain[-1].reason,
        raw_probability=raw, lineup_dependency=Missing(missing_reason="no_entregado", expected_piece="AD-D03"),
        validation=validation, validation_cell=cell,
        evaluation=_evaluation(conn, int(d["id"])),
    )


def _validation(conn: Conn, layer: str, family: str, market: str, at: datetime) -> tuple[MarketValidation | Missing, str | Missing]:
    board = views.board(conn, start=at - timedelta(days=BOARD_DAYS), end=at)
    if board is None:
        return Missing(missing_reason="sin_datos"), Missing(missing_reason="sin_datos")
    cell = next((c for c in board["cells"] if (c["layer"], c["family"], c["market"]) == (layer, family, market)), None)
    if cell is None:
        return MarketValidation(verdict="INSUFICIENTE", sample=0, needed=int(board["needed"])), f"{layer}|{family}|{market}"
    return (MarketValidation(verdict=cell["verdict"], sample=int(cell["sample"]), needed=int(cell["needed"])),
            f"{layer}|{family}|{market}")


def _evaluation(conn: Conn, decision_id: int) -> EvaluationSummary | Missing:
    r = views.evaluation_of(conn, "intel.decisions", decision_id)
    if r is None:
        return Missing(missing_reason="sin_datos")
    return EvaluationSummary(version=str(r["version"]), result=r["result"], verdict=r["verdict"],
                             clv_pct=Missing(missing_reason="sin_datos") if r["clv"] is None else round(float(r["clv"]) * 100, 2),
                             evidence_held=int(r["evidence_held"]), evidence_contradicted=int(r["evidence_contradicted"]),
                             evidence_unevaluable=int(r["evidence_unevaluable"]),
                             lineup_changed=Missing(missing_reason="sin_datos") if r["lineup_changed"] is None
                             else bool(r["lineup_changed"]))


def public_for_pick(conn: Conn, pick_id: int, *, at: datetime | None = None) -> SelectionIntelligence | None:
    """The public C-02 of a pick, or None: with ``FBI_MATCH_INTELLIGENCE`` off, without a decision, or while the owner has not
    authorised the selection (a selection under evaluation never reaches a reader)."""
    if not match_intelligence_on():
        return None
    row = fetch_one(conn, PICK_DECISION_SQL, {"pick": pick_id, "v": DECISION_CORE})
    if row is None:
        return None
    built = private(conn, int(row["id"]), at=at)
    if built.public_state is None:
        return None
    projected = to_public(built, SelectionIntelligence)
    assert isinstance(projected, SelectionIntelligence)
    return projected

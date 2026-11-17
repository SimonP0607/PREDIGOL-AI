"""C-08, the evaluation after the match of one match's selections (AD-J07, IA-133). Reading only.

Every answer comes from what ``eval-sel-v1`` (AD-K01, IA-112) wrote of each settled selection of the match in
``intel.selection_evaluations``: its columns and its ``detail`` (the six questions, each answered by a rule of
``fbi.evaluation.selection``). Nothing is re-judged here: the percentages are the stored proportions x 100, rounded once. The accumulated
calibration and each market's verdict are the validation board's (AD-K02, ``board-v1``) over the evaluations of the last ``BOARD_DAYS``
days. The match is read as C-01 reads it (``match_intelligence.FIXTURE_SQL`` and ``match_info``). A table the database does not have yet
leaves its block «sin datos»; an unknown match is a 404.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.contracts.intelligence.base import (
    Freshness,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
)
from fbi.api.contracts.intelligence.post_evaluation import (
    PostMatchAnticipated,
    PostMatchBin,
    PostMatchCalibration,
    PostMatchEstimate,
    PostMatchEvaluation,
    PostMatchEvidence,
    PostMatchFact,
    PostMatchHappened,
    PostMatchLineup,
    PostMatchPrice,
    PostMatchScores,
    PostMatchSelection,
)
from fbi.api.contracts.intelligence.tracking import BoardRef
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.match_intelligence import FIXTURE_SQL, match_info
from fbi.core.clock import now as clock_now
from fbi.evaluation import views
from fbi.evaluation.board import ALL_MARKETS
from fbi.evaluation.selection import EVIDENCE_RULES, LINEUP_RULES, VERSION

BOARD_DAYS: Final = 30
NO_DATA: Final = Missing(missing_reason="sin_datos")
SCENARIO_PIECE: Final = "AD-B02"
ESTIMATE_PIECE: Final = "AD-D04"
CODE: Final = re.compile(r"^[a-z][a-z0-9_]*$")
LIFECYCLE: Final = frozenset(("detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra",
                              "retirada", "descartada", "en_juego", "liquidada", "evaluada"))

ROWS_SQL: Final = """
SELECT id, version, layer, decision_source, decision_id, family, taken, market_key, selection, line, kickoff_at, decided_at,
       settled_at, result, p_judged::float8 AS p_judged, seal, p_market::float8 AS p_market, odds::float8 AS odds,
       p_close::float8 AS p_close, clv::float8 AS clv, hit, log_loss::float8 AS log_loss, brier::float8 AS brier,
       market_log_loss::float8 AS market_log_loss, market_brier::float8 AS market_brier, price_quality, verdict, evidence_held,
       evidence_contradicted, evidence_unevaluable, lineup_changed, parity, detail, input_hash, created_at
  FROM intel.selection_evaluations
 WHERE fixture_id = %(f)s AND version = %(v)s
 ORDER BY layer, family, market_key, selection, line
 LIMIT 300
"""
"""The match's evaluations of the current version (one per selection and layer; the table refuses a second)."""


def _pct(x: Any, nd: int = 1) -> float | Missing:
    return NO_DATA if x is None else round(float(x) * 100, nd)


def _code(x: Any, fallback: str) -> str:
    return str(x) if isinstance(x, str) and CODE.match(x) else fallback


def _obj(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _when(x: Any) -> datetime | Missing:
    if isinstance(x, datetime):
        return x
    if isinstance(x, str):
        try:
            return datetime.fromisoformat(x)
        except ValueError:
            return NO_DATA
    return NO_DATA


def origin_of(layer: str) -> str:
    """A layer's name as a figure's ``origin`` (``decision-fam-v1`` -> ``decision_fam-v1``). Pure."""
    m = re.fullmatch(r"(.+)-(v\d+)", layer)
    if m and re.fullmatch(r"[a-z][a-z0-9-]*", m.group(1)):
        return f"{m.group(1).replace('-', '_')}-{m.group(2)}"
    return re.sub(r"[^a-z0-9_]", "_", layer.lower()) or "decision"


def selection_of(r: Mapping[str, Any], validation: MarketValidation | Missing) -> PostMatchSelection:
    """One stored evaluation as C-08's six answers. Pure."""
    d = _obj(r["detail"])
    ant, hap, val, ev, lu = (_obj(d.get(k)) for k in ("anticipated", "happened", "value", "evidence", "lineup"))
    cycle = _obj(ant.get("cycle"))
    p = float(r["p_judged"])
    ev_pct = ant.get("expected_value")
    hit = r["hit"]
    scores: PostMatchScores | Missing = NO_DATA
    if hit is not None and r["log_loss"] is not None and r["brier"] is not None:
        scores = PostMatchScores(log_loss=round(float(r["log_loss"]), 6), brier=round(float(r["brier"]), 6),
                                 market_log_loss=NO_DATA if r["market_log_loss"] is None else round(float(r["market_log_loss"]), 6),
                                 market_brier=NO_DATA if r["market_brier"] is None else round(float(r["market_brier"]), 6))
    facts = [PostMatchFact(id=int(f["id"]), kind=str(f.get("kind") or "otro"),
                           claim=str(f["claim"]) if f.get("claim") else NO_DATA,
                           status=f["status"] if f.get("status") in ("sostenido", "contradicho") else "no_evaluable",
                           why=_code(f.get("why"), "sin_regla"))
             for f in ev.get("items") or [] if isinstance(f, Mapping) and f.get("id") is not None]
    estimate_raw = _obj(lu.get("estimate"))
    if "hits" in estimate_raw and "of" in estimate_raw:
        share = estimate_raw.get("share")
        estimate: PostMatchEstimate | Missing = PostMatchEstimate(hits=int(estimate_raw["hits"]), of=int(estimate_raw["of"]),
                                                                  share_pct=_pct(share))
    else:
        estimate = Missing(missing_reason="no_entregado", expected_piece=ESTIMATE_PIECE)
    before = _obj(lu.get("before"))
    state = cycle.get("state")
    close_min = val.get("close_minutes_to_ko")
    changed = r["lineup_changed"]
    return PostMatchSelection(
        layer=str(r["layer"]), decision_source=r["decision_source"], decision_id=int(r["decision_id"]), family=r["family"],
        market=str(r["market_key"]), selection=str(r["selection"]), line=float(r["line"]),
        anticipated=PostMatchAnticipated(
            probability=Probability.of(p, calibration=r["seal"], as_of=r["decided_at"], origin=origin_of(str(r["layer"])),
                                       evaluation=NO_DATA, evaluation_version=NO_DATA, interval=NO_DATA, decimals=1),
            market_pct=_pct(r["p_market"]), odds=NO_DATA if r["odds"] is None else round(float(r["odds"]), 3),
            expected_value_pct=_pct(ev_pct) if isinstance(ev_pct, int | float) else NO_DATA,
            decision_state=str(ant.get("state") or "sin_estado"), checkpoint=str(ant.get("checkpoint") or "sin_corte"),
            decided_at=r["decided_at"],
            cycle_state=state if state in LIFECYCLE else NO_DATA,
            cycle_reason=str(cycle["reason"]) if cycle.get("reason") else NO_DATA, taken=bool(r["taken"])),
        happened=PostMatchHappened(result=r["result"], settled_by=str(hap.get("source") or "intel.decision_outcomes"),
                                   settled_at=r["settled_at"], hit=None if hit is None else bool(hit), scores=scores),
        price=PostMatchPrice(clv_pct=_pct(r["clv"], 2), close_pct=_pct(r["p_close"]),
                             close_minutes_to_ko=int(close_min) if isinstance(close_min, int) else NO_DATA,
                             quality=r["price_quality"], verdict=r["verdict"]),
        evidence=PostMatchEvidence(rules=str(ev.get("rules") or EVIDENCE_RULES), held=int(r["evidence_held"]),
                                   contradicted=int(r["evidence_contradicted"]), unevaluable=int(r["evidence_unevaluable"]),
                                   facts=ItemList[PostMatchFact](items=facts) if facts else ItemList[PostMatchFact](
                                       items=[], missing_reason="sin_datos")),
        lineup=PostMatchLineup(rules=str(lu.get("rules") or LINEUP_RULES), changed=NO_DATA if changed is None else bool(changed),
                               why=_code(lu.get("why"), "sin_datos"), official_at=_when(lu.get("official_at")),
                               probability_change_pp=float(lu["p_change_pp"]) if isinstance(lu.get("p_change_pp"), int | float)
                               else NO_DATA, state_before=str(before["state"]) if before.get("state") else NO_DATA,
                               estimate=estimate),
        scenario=Missing(missing_reason="no_entregado", expected_piece=SCENARIO_PIECE),
        validation=validation, validation_cell=f"{r['layer']}|{r['family']}|{r['market_key']}", parity=r["parity"],
        evaluated_at=r["created_at"], input_hash=str(r["input_hash"]))


def _cell(board: Mapping[str, Any] | None, layer: str, family: str, market: str) -> Mapping[str, Any] | None:
    if board is None:
        return None
    return next((c for c in board["cells"] if (c["layer"], c["family"], c["market"]) == (layer, family, market)), None)


def validation_of(board: Mapping[str, Any] | None, layer: str, family: str, market: str) -> MarketValidation | Missing:
    """Its market's verdict on the board: a cell the board did not count has none of the sample it needs (INSUFICIENTE). Pure."""
    if board is None:
        return NO_DATA
    c = _cell(board, layer, family, market)
    if c is None:
        return MarketValidation(verdict="INSUFICIENTE", sample=0, needed=int(board["needed"]))
    return MarketValidation(verdict=c["verdict"], sample=int(c["sample"]), needed=int(c["needed"]))


def calibration_of(board: Mapping[str, Any], cells: Sequence[tuple[str, str, str]]) -> list[PostMatchCalibration]:
    """The accumulated calibration of each cell, in the order given; a cell the board did not count is left out. Pure."""
    out: list[PostMatchCalibration] = []
    for layer, family, market in cells:
        c = _cell(board, layer, family, market)
        if c is None:
            continue
        cal, clv = _obj(c.get("calibration")), _obj(c.get("clv"))
        out.append(PostMatchCalibration(
            cell=f"{layer}|{family}|{market}", sample=int(c["sample"]), needed=int(c["needed"]),
            ece=NO_DATA if cal.get("ece") is None else round(float(cal["ece"]), 4), ece_max=float(cal.get("max") or 0.03),
            bins=[PostMatchBin(pred_pct=float(b["pred_pct"]), observed_pct=float(b["observed_pct"]), n=int(b["n"]))
                  for b in cal.get("bins") or []],
            clv_mean_pct=_pct(clv.get("mean"), 2), verdict=c["verdict"]))
    return out


def board_ref(board: Mapping[str, Any]) -> BoardRef:
    stamp = _obj(board.get("protocol"))
    return BoardRef(version=str(board["version"]), protocol=str(stamp.get("protocol") or "AD-K02"),
                    fingerprint=str(stamp.get("fingerprint") or "0" * 64), signed_by_owner=bool(board.get("signed_by_owner")),
                    bonferroni_m=int(_obj(board.get("bonferroni")).get("m") or 0))


def assemble(*, at: datetime, fixture: Mapping[str, Any], rows: Sequence[Mapping[str, Any]] | None,
             board: Mapping[str, Any] | None) -> PostMatchEvaluation:
    """C-08 from what was read (``rows`` None: the table does not exist). Pure."""
    selections = [selection_of(r, validation_of(board, str(r["layer"]), str(r["family"]), str(r["market_key"]))) for r in rows or []]
    cells: list[tuple[str, str, str]] = []
    for s in selections:
        for key in ((s.layer, s.family, s.market), (s.layer, s.family, ALL_MARKETS)):
            if key not in cells:
                cells.append(key)
    calibrated = calibration_of(board, cells) if board is not None else []
    return PostMatchEvaluation(
        freshness=Freshness(generated_at=at, stale=False), match=match_info(fixture), version=VERSION,
        selections=ItemList[PostMatchSelection](items=selections) if selections else ItemList[PostMatchSelection](
            items=[], missing_reason="sin_datos"),
        calibration=ItemList[PostMatchCalibration](items=calibrated) if calibrated else ItemList[PostMatchCalibration](
            items=[], missing_reason="sin_datos"),
        board=NO_DATA if board is None else board_ref(board))


def evaluation(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> PostMatchEvaluation:
    """C-08 of one match. 404 for an unknown match. Reading only."""
    moment = at or clock_now()
    fx = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fx is None:
        raise ApiError(404, "not_found", "no such fixture")
    rows: list[dict[str, Any]] | None = None
    board: dict[str, Any] | None = None
    if views.exists(conn):
        rows = fetch_all(conn, ROWS_SQL, {"f": fixture_id, "v": VERSION})
        if rows:
            board = views.board(conn, start=moment - timedelta(days=BOARD_DAYS), end=moment)
    return assemble(at=moment, fixture=fx, rows=rows, board=board)

"""The owner's private evaluation board (plan PM, PM-12-01; IA-153): the newest weekly board and the newest report by competition and
coverage level (PM-12-06), read from ``analytics.evaluation_reports`` and ``analytics.evaluation_segments``. Read only; 404 while
``FBI_EVALUATION_BOARD`` is off. Computing them is the weekly batch's (``fbi.coverage.weekly_board`` and ``segments``)."""

from __future__ import annotations

from typing import Any, Final

from fbi.api.cache import shared
from fbi.api.contracts.evaluation_board import EvaluationBoard, SegmentsSummary, WeeklyBoard
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.switches import evaluation_board_on

CACHE_SECONDS: Final = 60
TOP_COMPETITIONS: Final = 80
NOTICE: Final = ("Tablero privado de evaluación: no es una prueba de ventaja y no cambia picks, modelos ni probabilidades. «Insuficiente»: "
                 "la competición no tiene muestra propia.")

LATEST_SQL: Final = """
SELECT id, version, period_from, period_to, computed_at, body FROM analytics.evaluation_reports
 WHERE kind = %(kind)s ORDER BY period_to DESC, id DESC LIMIT 1
"""
COMPETITIONS_SQL: Final = """
SELECT s.segment_key::bigint AS competition_id, c.name, s.model_name AS model, s.market_key AS market, s.n, s.days, s.log_loss,
       s.log_loss_low, s.log_loss_high, s.skill, s.skill_low, s.skill_high, s.verdict
  FROM analytics.evaluation_segments s LEFT JOIN core.competitions c ON c.id::text = s.segment_key
 WHERE s.report_id = %(report)s AND s.source = 'forecast' AND s.segment_kind = 'competition'
 ORDER BY s.n DESC, s.segment_key, s.market_key LIMIT %(limit)s
"""


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def build(conn: Conn) -> EvaluationBoard:
    weekly = None
    w = fetch_one(conn, LATEST_SQL, {"kind": "weekly"})
    if w is not None:
        body = w["body"]
        weekly = WeeklyBoard.model_validate({"report_id": w["id"], "version": w["version"], "period_from": w["period_from"],
                                             "period_to": w["period_to"], "cumulative_from": body["cumulative_from"],
                                             "computed_at": w["computed_at"], "markets": body["markets"]})
    segments = None
    s = fetch_one(conn, LATEST_SQL, {"kind": "segments"})
    if s is not None:
        body = s["body"]
        rows = fetch_all(conn, COMPETITIONS_SQL, {"report": s["id"], "limit": TOP_COMPETITIONS})
        segments = SegmentsSummary.model_validate({
            "report_id": s["id"], "version": s["version"], "period_from": s["period_from"], "period_to": s["period_to"],
            "computed_at": s["computed_at"], "needed": body["needed"], "reproduced": body["reproduced"], "counts": body["counts"],
            "competitions": [{**r, "log_loss": float(r["log_loss"]), "log_loss_low": _f(r["log_loss_low"]),
                              "log_loss_high": _f(r["log_loss_high"]), "skill": float(r["skill"]), "skill_low": _f(r["skill_low"]),
                              "skill_high": _f(r["skill_high"])} for r in rows]})
    return EvaluationBoard(weekly=weekly, segments=segments, notice_es=NOTICE)


@shared(CACHE_SECONDS)
def _cached(conn: Conn) -> Envelope[EvaluationBoard]:
    return ok(build(conn))


def board(conn: Conn) -> Envelope[EvaluationBoard]:
    if not evaluation_board_on():
        raise ApiError(404, "not_found", "not found")
    return _cached(conn)

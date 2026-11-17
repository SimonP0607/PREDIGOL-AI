"""C-03, the private tracking of the selections in the shadow (AD-J04, IA-115). Reading only.

The counts by state and the selections come from the cycle's own reader (``fbi.lifecycle.reader.tracking``: ``intel.selection_lifecycle``
and ``core.fixtures``); each selection of the page is completed with its newest decision before the move the cycle stands on (the figure
and the price, ``intel.decisions`` of its layer) and with its evaluation after the match (``intel.selection_evaluations``, AD-K01). The
families' counters are the validation board's (AD-K02) over the same period. A table the database does not have yet (a schema behind the
code) leaves its block «sin datos»; nothing else fails.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg

from fbi.ai.calendar import day_bounds, local_day
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing, Probability
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
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now as clock_now
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.evaluation import views
from fbi.evaluation.board import ALL_MARKETS
from fbi.evaluation.selection import VERSION as EVAL_VERSION
from fbi.lifecycle import machine, reader
from fbi.lifecycle.store import WRITER

DEFAULT_BACK: Final = 6
DEFAULT_AHEAD: Final = 1
LAYERS: Final = (DECISION_CORE, DECISION_FAMILIES)
EXISTS_SQL: Final = "SELECT to_regclass('intel.selection_lifecycle') IS NOT NULL AS ok"
LATEST_SQL: Final = """
SELECT DISTINCT ON (k.ord) k.ord, d.p_model::float8 AS p_model, d.p_cal::float8 AS p_cal, d.odds::float8 AS odds, d.known_at
  FROM unnest(%(fixtures)s::bigint[], %(markets)s::text[], %(selections)s::text[], %(lines)s::numeric[], %(layers)s::text[],
              %(until)s::timestamptz[]) WITH ORDINALITY AS k(fixture_id, market_key, selection, line, layer, until, ord)
  JOIN intel.decisions d ON d.fixture_id = k.fixture_id AND d.market_key = k.market_key AND d.selection = k.selection
   AND d.line = k.line AND d.decision_version = k.layer AND d.decision_version = ANY(%(versions)s) AND d.known_at <= k.until
 ORDER BY k.ord, d.known_at DESC, d.id DESC
"""
"""The newest decision of each selection of the page up to the move it stands on (one statement for the whole page)."""
EVALUATIONS_SQL: Final = """
SELECT fixture_id, market_key, selection, line, layer, clv, verdict
  FROM intel.selection_evaluations
 WHERE version = %(version)s AND fixture_id = ANY(%(fixtures)s)
"""


def _missing() -> Missing:
    return Missing(missing_reason="sin_datos")


def _key(fixture: int, market: str, selection: str, line: Any, layer: str) -> tuple[int, str, str, Decimal, str]:
    return int(fixture), str(market), str(selection), Decimal(str(line)).quantize(Decimal("0.01")), str(layer)


def tracking(conn: Conn, *, date_from: date | None = None, date_to: date | None = None, state: str | None = None,
             family: str | None = None, competition_id: int | None = None, cursor: int | None = None, limit: int = 50,
             at: datetime | None = None) -> Tracking:
    """C-03 over the matches that kick off from ``date_from`` to ``date_to`` (Bogotá days, both included; by default the last six days
    and tomorrow)."""
    moment = at or clock_now()
    today = local_day(moment)
    start_day = date_from or today - timedelta(days=DEFAULT_BACK)
    end_day = date_to or today + timedelta(days=DEFAULT_AHEAD)
    limit = max(1, min(limit, reader.MAX_LIMIT))
    filters = Filters(state=state, family=family, competition=competition_id, limit=limit)  # type: ignore[arg-type]
    if not (fetch_one(conn, EXISTS_SQL, {}) or {}).get("ok"):
        cycle: dict[str, Any] | None = None
    else:
        try:
            cycle = reader.tracking(conn, date_from=start_day, date_to=end_day, state=state, family=family,
                                    competition_id=competition_id, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise ApiError(422, "invalid", str(exc)) from exc
    if cycle is None and (end_day < start_day or (end_day - start_day).days + 1 > reader.MAX_DAYS):
        raise ApiError(422, "invalid", f"a period is 1 to {reader.MAX_DAYS} days")
    start, _ = day_bounds(start_day)
    _, end = day_bounds(end_day)
    board = views.board(conn, start=start, end=end)
    items = _items(conn, cycle["items"] if cycle else [])
    families = _families(board, family)
    return Tracking(
        freshness=Freshness(generated_at=moment, stale=False),
        machine_version=machine.VERSION, writer=WRITER, filters=filters,
        counts_by_state=_missing() if cycle is None else StateCounts(**cycle["counts_by_state"]),
        families=families,
        board=_missing() if board is None else BoardRef(version=board["version"], protocol=board["protocol"]["protocol"],
                                                        fingerprint=board["protocol"]["fingerprint"],
                                                        signed_by_owner=bool(board["signed_by_owner"]),
                                                        bonferroni_m=int(board["bonferroni"]["m"])),
        items=ItemList[TrackingItem](items=items) if items else ItemList[TrackingItem](
            items=[], missing_reason="sin_datos" if cycle is None else "sin_resultados"),
        period=Period(date_from=start_day, date_to=end_day, total=0 if cycle is None else int(cycle["period"]["total"])),
        next_cursor=None if cycle is None else cycle["next_cursor"],
    )


def _families(board: dict[str, Any] | None, family: str | None) -> ItemList[FamilyCounter]:
    if board is None:
        return ItemList[FamilyCounter](items=[], missing_reason="sin_datos")
    out = [FamilyCounter(layer=c["layer"], family=c["family"], candidates=int(c["candidates"]), sample=int(c["sample"]),
                         needed=int(c["needed"]), verdict=c["verdict"],
                         clv_pct=_missing() if c["clv"]["mean"] is None else round(float(c["clv"]["mean"]) * 100, 2))
           for c in board["cells"] if c["market"] == ALL_MARKETS and (family is None or c["family"] == family)]
    return ItemList[FamilyCounter](items=out) if out else ItemList[FamilyCounter](items=[], missing_reason="sin_resultados")


def _items(conn: psycopg.Connection[Any], raw: list[dict[str, Any]]) -> list[TrackingItem]:
    if not raw:
        return []
    keys = [_key(r["fixture"]["id"], r["selection"]["market"], r["selection"]["selection"], r["selection"]["line"],
                 r["selection"]["layer"]) for r in raw]
    params = {"fixtures": [k[0] for k in keys], "markets": [k[1] for k in keys], "selections": [k[2] for k in keys],
              "lines": [k[3] for k in keys], "layers": [k[4] for k in keys], "until": [r["known_at"] for r in raw],
              "versions": list(LAYERS)}
    latest = {int(r["ord"]) - 1: r for r in fetch_all(conn, LATEST_SQL, params)}
    evaluations: dict[tuple[int, str, str, Decimal, str], dict[str, Any]] = {}
    if views.exists(conn):
        for e in fetch_all(conn, EVALUATIONS_SQL, {"version": EVAL_VERSION, "fixtures": sorted({k[0] for k in keys})}):
            evaluations[_key(e["fixture_id"], e["market_key"], e["selection"], e["line"], e["layer"])] = e
    out = []
    for i, r in enumerate(raw):
        d = latest.get(i)
        ev = evaluations.get(keys[i])
        probability: Probability | Missing = _missing()
        if d is not None:
            calibrated = d["p_cal"] is not None
            probability = Probability.of(float(d["p_cal"] if calibrated else d["p_model"]),
                                         calibration="calibrada" if calibrated else "sin_calibrar", as_of=d["known_at"],
                                         origin="decision-v1", interval=_missing(),
                                         evaluation=Missing(missing_reason="no_entregado", expected_piece="AD-D06"),
                                         evaluation_version=Missing(missing_reason="no_entregado", expected_piece="AD-D06"))
        out.append(TrackingItem(
            fixture=TrackingFixture(id=r["fixture"]["id"], kickoff_at=r["fixture"]["kickoff_at"],
                                    competition_id=r["fixture"]["competition_id"]),
            selection=TrackingSelection(market=r["selection"]["market"], selection=r["selection"]["selection"],
                                        line=r["selection"]["line"], family=r["selection"]["family"], layer=r["selection"]["layer"]),
            state=r["state"], reason=r["reason"], known_at=r["known_at"], detected_at=r["detected_at"], moves=r["moves"],
            public_state=r["public_state"], probability=probability,
            price_taken=_missing() if d is None or d["odds"] is None else float(d["odds"]),
            evaluation=_missing() if r["evaluation"] is None else r["evaluation"],
            outcome=r["outcome"] or "pending",
            clv_pct=_missing() if ev is None or ev["clv"] is None else round(float(ev["clv"]) * 100, 2),
            verdict=_missing() if ev is None else str(ev["verdict"])))
    return out

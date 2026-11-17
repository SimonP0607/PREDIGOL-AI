"""The owner's private alerts, contract C-05 (IA-107, AD-D08; ``GET /admin/intelligence/alerts``): the alerts the evaluation cycle kept in
``intel.private_alerts`` (revision 0156), newest first, «antes -> ahora».

It READS one table and decides nothing: it writes no row and notifies nobody. It does not import the cycle (``fbi.evalcycle``): it reads
the rows the cycle wrote. A database without the table (before revision 0156) answers an empty list that says ``no_entregado``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg

from fbi.api.contracts.intelligence.alerts import (
    AlertItem,
    AlertKind,
    AlertsContract,
    ConditionState,
    DecisionRef,
    KickoffState,
    LineUpState,
    PriceAtAlert,
    SelectionRef,
    SelectionState,
    Value,
)
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all
from fbi.core.clock import now

LIMIT: Final = 500
ALERTS_SQL: Final = """
SELECT id, kind, fixture_id, market_key, selection, line, cause, before, after, price, decision_id, evaluation, evaluation_version,
       known_at, kickoff_at
  FROM intel.private_alerts
 WHERE created_at >= %(since)s AND (%(fixture)s::bigint IS NULL OR fixture_id = %(fixture)s) AND (%(kind)s::text IS NULL OR kind = %(kind)s)
 ORDER BY created_at DESC, id DESC
 LIMIT %(limit)s
"""


def _time(x: Any) -> datetime | None:
    if x is None:
        return None
    return x if isinstance(x, datetime) else datetime.fromisoformat(str(x))


def _value(kind: str, d: dict[str, Any]) -> Value:
    if kind == "retirada":
        return SelectionState(state=d["state"], reason=d["reason"], probability=d.get("p"), odds=d.get("odds"),
                              price_state=d.get("price_state"), players_out=[int(p) for p in d.get("players_out") or []])
    if kind == "sin_alineacion":
        return LineUpState(state=d["state"], line_up=d["line_up"], sides_missing=list(d.get("sides_missing") or []),
                           minutes_to_kickoff=d.get("minutes_to_kickoff"))
    if kind == "cambio_horario":
        at = _time(d["kickoff_at"])
        assert at is not None
        return KickoffState(kickoff_at=at)
    venue = d.get("venue_id")
    return ConditionState(status=d.get("status"), venue_id=None if venue is None else int(venue), in_play_at=_time(d.get("in_play_at")))


def item_of(r: dict[str, Any]) -> AlertItem:
    kind: AlertKind = r["kind"]
    price = r["price"]
    return AlertItem(
        alert_id=int(r["id"]), kind=kind, fixture_id=int(r["fixture_id"]),
        selection=Missing(missing_reason="sin_datos") if r["market_key"] is None else SelectionRef(
            market_key=r["market_key"], selection=r["selection"], line=str(Decimal(str(r["line"])).quantize(Decimal("0.01")))),
        cause=r["cause"], before=_value(kind, r["before"]), now=_value(kind, r["after"]),
        price=Missing(missing_reason="sin_datos") if not price else PriceAtAlert(
            odds=price.get("odds"), state=price.get("state"), at=_time(price.get("at")), age_minutes=price.get("age_minutes")),
        decision=Missing(missing_reason="sin_datos") if r["decision_id"] is None else DecisionRef(decision_id=int(r["decision_id"])),
        evaluation=r["evaluation"], evaluation_version=int(r["evaluation_version"]), known_at=r["known_at"], kickoff_at=r["kickoff_at"])


def build(conn: Conn, *, at: datetime, hours: int = 48, fixture_id: int | None = None, kind: str | None = None) -> AlertsContract:
    fresh = Freshness(generated_at=at, stale=False)
    try:
        with conn.transaction():
            rows = fetch_all(conn, ALERTS_SQL, {"since": at - timedelta(hours=hours), "fixture": fixture_id, "kind": kind, "limit": LIMIT})
    except psycopg.errors.UndefinedTable:
        return AlertsContract(freshness=fresh, window_hours=hours,
                              alerts=ItemList[AlertItem](items=[], missing_reason="no_entregado", expected_piece="AD-D08"))
    items = [item_of(dict(r)) for r in rows]
    return AlertsContract(freshness=fresh, window_hours=hours,
                          alerts=ItemList[AlertItem](items=items, missing_reason=None if items else "sin_datos"))


def alerts(conn: Conn, *, hours: int = 48, fixture_id: int | None = None, kind: str | None = None) -> Envelope[AlertsContract]:
    return ok(build(conn, at=now(), hours=hours, fixture_id=fixture_id, kind=kind))

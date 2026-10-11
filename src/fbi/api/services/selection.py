"""The day's selection funnel for the Admin Console (``fbi.picks.funnel``), read with the daily set's own functions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fbi.api.contracts.funnel import FunnelItem, FunnelStage, SelectionFunnel
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services.product import _away, _competition, _home
from fbi.core.clock import now as clock_now
from fbi.picks import funnel
from fbi.picks.daily import (
    CONTEXT,
    HORIZON,
    RISK,
    RULE_VERSION,
    Ranked,
    Source,
    ai_view,
    load_candidates,
    passing,
    product_day,
)

TAKEN_SQL = """
SELECT s.day, array_remove(array_agg(i.fixture_id), NULL) AS fixtures
  FROM picks.daily_sets s LEFT JOIN picks.daily_set_items i ON i.set_id = s.id
 WHERE s.source = %(source)s AND s.day = ANY(%(days)s) GROUP BY s.day
"""


def _item(x: Ranked, ai: Any, *, day: date | None = None, stage: str | None = None,
          reason: str | None = None) -> FunnelItem:
    c, r = x.leg.candidate, x.row
    assert c.price is not None and c.p_market_fair is not None
    return FunnelItem(
        day=day, stage=stage, reason=reason, pick_id=c.pick_id, fixture_id=c.fixture_id, kickoff_at=c.kickoff_at,
        competition=_competition(r), home=_home(r), away=_away(r), market_key=c.market_key, selection=c.selection,
        line=c.line, odds=c.price, bookmaker=r.get("bookmaker"), p_model=c.p_model, p_low=x.p_low,
        p_market=c.p_market_fair, ev=x.leg.ev, growth=Decimal(str(round(x.elg, 8))), ai_decision=ai.decision(x),
        evidence=dict(ai.evidence.get(c.fixture_id, {})))


def selection_funnel(conn: Conn, *, source: Source, at: datetime | None = None) -> Envelope[SelectionFunnel]:
    moment = at or clock_now()
    rows = load_candidates(conn, at=moment, until=moment + HORIZON, include_shadow=source == "evaluation")
    ai = ai_view(conn, passing(rows, at=moment, source=source), at=moment)
    days = sorted({product_day(r["kickoff_at"]) for r in rows} | {product_day(moment)})
    taken = {r["day"]: set(r["fixtures"] or []) for r in fetch_all(conn, TAKEN_SQL, {"source": source, "days": days})}
    rep = funnel.report(rows, at=moment, source=source, ai=ai, taken=taken)
    body = SelectionFunnel(
        at=moment, source=source, rule_version=RULE_VERSION, risk_version=RISK.version, max_odds=RISK.max_odds,
        context_version="ai_off" if ai.mode == "off" else CONTEXT.version, ai_mode=ai.mode, ai_enforced=ai.enforced,
        candidates=rep.candidates, selections=rep.selections,
        stages=[FunnelStage(key=s.key, entered=s.entered, passed=s.passed,  # type: ignore[arg-type]
                            reasons=dict(s.reasons.most_common())) for s in rep.stages],
        chosen=[_item(x, ai, day=day) for day, x in rep.chosen],
        near=[_item(x, ai, stage=stage, reason=why) for stage, why, x in rep.near],
        in_set={str(day): len(fx) for day, fx in sorted(taken.items())})
    return ok(body, data_as_of=moment)

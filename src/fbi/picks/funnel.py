"""THE SELECTION FUNNEL (REVIEW PREDIGOL, 11 Oct 2026, B1): every candidate of the day's set, stage by stage, and where
it stopped - so "why is this a pick of the day" and "why is that one not" have an answer in data, never a guess.

    data         not_scheduled, too_close_to_kickoff, outside_window
    market       no_price, stale_price, no_consensus, few_bookmakers, price_outlier
    model        not_qualified, model_retired
    calibration  no_interval
    value        non_positive_ev, no_pessimistic_growth
    risk         odds_above_cap                              (risk-v1)
    context      day_not_ready, no_day_pass, not_reviewed,   (context-v2; a rejection only when enforced)
                 ai_rejected
    selection    match_taken (a better selection of the match, or the match already in the day's set), day_full

Counted per SELECTION (match, market, selection, line): a selection several model versions priced reaches the stage
its furthest pick reached. The stages up to value mirror the value gate check by check (``first_stop``; a test holds it
to ``fbi.picks.daily.passing``), and the ones after it are the daily set's own objects (``RISK``, ``CONTEXT``,
``AiView``), so the funnel cannot describe a rule the set does not apply. Nothing here touches the database.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fbi.parlays.engine import expected_value
from fbi.picks.daily import (
    CONTEXT,
    GATE,
    MAX_ITEMS,
    RISK,
    AiView,
    Ranked,
    Source,
    candidate_of,
    passing,
    product_day,
    single_elg,
    stage_of,
)

STAGES: tuple[str, ...] = ("data", "market", "model", "calibration", "value", "risk", "context", "selection")
Key = tuple[int, str, str, Decimal]


def first_stop(r: dict[str, Any], *, at: datetime, source: Source) -> tuple[str, str] | None:
    """The first stage a candidate row fails, up to value; None when it reaches the risk stage."""
    c = candidate_of(r)
    minutes = (c.kickoff_at - at).total_seconds() / 60
    if c.fixture_status != "scheduled":
        return "data", "not_scheduled"
    if minutes < GATE.min_minutes_to_kickoff:
        return "data", "too_close_to_kickoff"
    if stage_of(minutes) is None:
        return "data", "outside_window"
    if c.price is None or c.price_at is None:
        return "market", "no_price"
    if at - c.price_at > GATE.max_price_age:
        return "market", "stale_price"
    if c.p_market_fair is None:
        return "market", "no_consensus"
    if (c.n_bookmakers or 0) < GATE.min_bookmakers:
        return "market", "few_bookmakers"
    if c.price * c.p_market_fair - Decimal(1) > GATE.max_price_edge:
        return "market", "price_outlier"
    if not c.qualified and source != "evaluation":
        return "model", "not_qualified"
    if c.model_status == "retired":
        return "model", "model_retired"
    if r.get("p_low") is None:
        return "calibration", "no_interval"
    ev, _ = expected_value(c.p_model, c.p_push, c.price)
    if ev <= GATE.min_ev:
        return "value", "non_positive_ev"
    p_low = min(Decimal(r["p_low"]), c.p_model)
    if single_elg(c.price, p_low, c.p_push) <= 0:
        return "value", "no_pessimistic_growth"
    return None


@dataclass
class Stage:
    key: str
    entered: int = 0
    passed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass
class Report:
    candidates: int
    """Candidate rows read (a selection priced by several model versions counts once per version)."""
    selections: int
    stages: list[Stage]
    chosen: list[tuple[date, Ranked]]
    """What the next build would add to each day's set, in rank order."""
    near: list[tuple[str, str, Ranked]]
    """The best selections that passed value and stopped later (risk, context, selection): (stage, reason, it)."""


def _key(r: dict[str, Any]) -> Key:
    return (int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]))


def report(rows: list[dict[str, Any]], *, at: datetime, source: Source, ai: AiView,
           taken: dict[date, set[int]] | None = None, near: int = 8) -> Report:
    """The funnel of ``rows`` (the next 24 hours' candidates) as the daily set would see them at ``at``. ``taken``:
    per product day, the matches already in that day's set (a set holds MAX_ITEMS at most, one per match)."""
    order = {s: i for i, s in enumerate(STAGES)}
    furthest: dict[Key, tuple[str, str] | None] = {}
    for r in rows:
        k = _key(r)
        stop = first_stop(r, at=at, source=source)
        if k not in furthest:
            furthest[k] = stop
            continue
        known = furthest[k]
        if known is None:
            continue
        if stop is None or order[stop[0]] > order[known[0]]:
            furthest[k] = stop
    stages = {s: Stage(s) for s in STAGES}
    for stop in furthest.values():
        reached = len(STAGES) if stop is None else order[stop[0]]
        for s in STAGES[: min(reached + 1, order["risk"])]:
            stages[s].entered += 1
        for s in STAGES[:reached]:
            if order[s] < order["risk"]:
                stages[s].passed += 1
        if stop is not None:
            stages[stop[0]].reasons[stop[1]] += 1

    valued = [x for x in passing(rows, at=at, source=source)
              if x.elg > 0 and stage_of((x.leg.candidate.kickoff_at - at).total_seconds() / 60) is not None]
    stopped: list[tuple[str, str, Ranked]] = []
    risk_ok: list[Ranked] = []
    for x in valued:
        why = RISK.stop(x)
        if why is None:
            risk_ok.append(x)
        else:
            stopped.append(("risk", why, x))
    context_ok: list[Ranked] = []
    for x in risk_ok:
        why = CONTEXT.stop(x, ai)
        if why is None:
            context_ok.append(x)
        else:
            stopped.append(("context", why, x))
    enforced = ai.apply(context_ok)
    kept = {id(x) for x in enforced}
    stopped += [("context", "ai_rejected", x) for x in context_ok if id(x) not in kept]

    by_day: dict[date, list[Ranked]] = defaultdict(list)
    for x in enforced:
        by_day[product_day(x.leg.candidate.kickoff_at)].append(x)
    chosen: list[tuple[date, Ranked]] = []
    for day, options in sorted(by_day.items()):
        fixtures = set((taken or {}).get(day, set()))
        room = MAX_ITEMS - len(fixtures)
        picked = 0
        for x in options:
            if x.leg.candidate.fixture_id in fixtures:
                stopped.append(("selection", "match_taken", x))
            elif picked >= room:
                stopped.append(("selection", "day_full", x))
            else:
                chosen.append((day, x))
                fixtures.add(x.leg.candidate.fixture_id)
                picked += 1

    stages["risk"].entered = len(valued)
    stages["risk"].passed = len(risk_ok)
    stages["context"].entered = len(risk_ok)
    stages["context"].passed = len(enforced)
    stages["selection"].entered = len(enforced)
    stages["selection"].passed = len(chosen)
    for stage, why, _ in stopped:
        stages[stage].reasons[why] += 1
    # A selection that passed every check up to value but not the 24-hour stage window or positive growth was
    # already counted at the value stage (first_stop), so the risk stage starts from exactly ``valued``.
    best = sorted(stopped, key=lambda t: (-t[2].elg, t[2].leg.candidate.kickoff_at, t[2].leg.candidate.pick_id))
    return Report(candidates=len(rows), selections=len(furthest), stages=[stages[s] for s in STAGES],
                  chosen=chosen, near=best[:near])


__all__ = ["STAGES", "Report", "Stage", "first_stop", "report"]

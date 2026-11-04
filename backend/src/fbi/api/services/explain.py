"""«Explícame» (plan UX, B9; sections 25, 28 and 29 of the plan): the frequent questions about a match, a pick and the reader's
parlay, answered from what PrediGol already keeps. Nothing is estimated here, no model or AI is called (the static guard is
``tests/unit/test_user_layer_isolation.py``, the runtime one ``tests/integration/test_user_layer_guards.py``) and nothing is
written.

    match  no_pick     «¿Por qué no hay pick?»: it has one (open it); it was played without one (Transparencia shows how
                       PrediGol does); or, still to be played, what stands in the way - no forecast yet, no prices yet, the
                       forecast not compared with the prices yet, the rules the compared selections failed (the decision layer's
                       own record, ``picks.pick_candidates``: its latest evaluation of each selection, ``fbi.picks.rules.decide``),
                       or none meets every rule of publication yet. A selection the decision layer chose that PrediGol does not
                       publish (an evaluation pick) is never named: a reader never learns one exists
           forecast    «¿Qué significa este pronóstico?»: PrediGol's forecast (A9) - each market's probabilities, the likely
                       outcome, whether it is calibrated - and why a forecast is not a pick
           risks       «¿Qué puede salir mal?»: the risks of the match's structured reading (A9), each with its reference
    pick   risks       the same for a pick: its probability and the model's doubt, the reading's risks and, only while the AI's
                       review is applied, the review's own (the pick's explanation, B3)
           caution     «¿Por qué cautela?»: the state the one table gives (``fbi.picks.user_status``) and why - a pick in caution
                       only exists while the AI's review is applied; until then it says so
    parlay probability «¿Por qué baja la probabilidad de mi parlay?»: the parlay being built, checked as the slip checks it
                       (``fbi.userdata.records.validate_parlay``): every leg must win, each leg's probability, their product,
                       the adjustment when legs depend on each other

An answer that lacks its data is ``answered=False`` and its lines say what is missing («no tengo ese dato»). Who may see what is
the services' own rule: a pick a reader may not see is 404 here too, the forecast and the reading follow their switches.

``FBI_EXPLAIN`` (``fbi.api.switches.explain_on``) is on while absent - B9 costs nothing -: ``0`` takes the buttons away
(``/auth/me`` says ``explain: false``) and the routes answer 404.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.explain import (
    ExplainEntity,
    ExplainIntent,
    ExplainLine,
    ExplainLink,
    Explanation,
    Param,
)
from fbi.api.contracts.explanation import PickExplanation
from fbi.api.contracts.forecast import ForecastMarket
from fbi.api.contracts.reading import MatchReading, ReadingFact
from fbi.api.envelope import DataStatus, Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import explanation as explanation_service
from fbi.api.services import forecast as forecast_service
from fbi.api.services import reading as reading_service
from fbi.core.clock import now
from fbi.picks.daily import CONSENSUS_LOOKBACK
from fbi.userdata import records as userdata
from fbi.userdata.records import LegIn

VERSION: Final = "explain-v1"
INTENTS: Final[dict[ExplainEntity, tuple[ExplainIntent, ...]]] = {
    "match": ("no_pick", "forecast", "risks"),
    "pick": ("risks", "caution"),
    "parlay": ("probability",),
}
"""The questions of each place, in the order the sheet lists them."""


def _say(key: str, /, **params: Param) -> ExplainLine:
    return ExplainLine(say=key, params=params)


def _fact(f: ReadingFact) -> ExplainLine:
    return ExplainLine(fact=f)


def _answer(entity: ExplainEntity, item_id: int | None, intent: ExplainIntent, lines: list[ExplainLine], *,
            answered: bool = True, terms: tuple[str, ...] = (), links: tuple[ExplainLink, ...] = ()) -> Explanation:
    return Explanation(version=VERSION, entity=entity, item_id=item_id, intent=intent, answered=answered, lines=lines,
                       terms=list(terms), links=list(links))


# ── a match ───────────────────────────────────────────────────────────────────────────

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, th.name AS home, ta.name AS away
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""

MATCH_PICKS_SQL = """
SELECT count(*)::int AS n
  FROM picks.picks p
 WHERE p.fixture_id = %(f)s
   AND COALESCE(NULLIF(p.status, 'settled'),
                (SELECT e.from_status FROM picks.pick_events e
                  WHERE e.pick_id = p.id AND e.to_status = 'settled' AND e.event_kind = 'status'
                  ORDER BY e.at LIMIT 1)) IN ('qualified', 'published')
"""
"""The picks a reader may be shown of the match: published (qualified or published), also once settled - never a shadow pick."""

NO_PICK_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (c.market_key, c.selection, c.line) c.decision, c.rejection_reason
      FROM picks.pick_candidates c
     WHERE c.fixture_id = %(f)s AND c.evaluated_at <= %(at)s
     ORDER BY c.market_key, c.selection, c.line, c.evaluated_at DESC, c.id DESC
)
SELECT EXISTS (SELECT 1 FROM models.predictions p WHERE p.fixture_id = %(f)s AND p.data_cutoff_ts <= %(at)s) AS forecast,
       EXISTS (SELECT 1 FROM market.market_consensus m
                WHERE m.fixture_id = %(f)s AND m.as_of <= %(at)s AND m.as_of >= %(since)s) AS prices,
       (SELECT count(*) FROM latest)::int AS evaluated,
       (SELECT count(*) FROM latest WHERE decision = 'selected')::int AS selected,
       (SELECT count(*) FROM latest WHERE rejection_reason LIKE 'expected value below%%'
                                       OR rejection_reason LIKE 'probability edge below%%')::int AS no_value,
       (SELECT count(*) FROM latest WHERE rejection_reason LIKE 'odds outside%%')::int AS odds,
       (SELECT count(*) FROM latest WHERE rejection_reason LIKE 'market %% is not covered%%'
                                       OR rejection_reason LIKE 'no de-vigged market consensus%%')::int AS market
"""
"""What stands between a match still to be played and a pick: its forecast, its prices and the decision layer's latest evaluation
of each of its selections, by the first rule each failed (``fbi.picks.rules.decide``: no value at the price, a price outside the
range, a market the rule does not cover or without the market's consensus). The selected ones are only counted: one that is not
published is an evaluation pick, never named to a reader."""


def _fixture(conn: Conn, fixture_id: int) -> dict[str, Any]:
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    return fixture


def _no_pick(conn: Conn, fixture_id: int, at: datetime | None) -> Explanation:
    fixture = _fixture(conn, fixture_id)
    picks = int((fetch_one(conn, MATCH_PICKS_SQL, {"f": fixture_id}) or {}).get("n") or 0)
    if picks:
        return _answer("match", fixture_id, "no_pick", [_say("has_pick", count=picks)], terms=("pick",),
                       links=("why_pick",))
    moment = at or now()
    terms = ("pick", "value", "forecast", "odds")
    rule = _say("pick_rule")
    if fixture["status_group"] != "scheduled" or fixture["kickoff_at"] <= moment:
        lines = [_say("no_pick_published"), rule, _say("no_pick_past")]
        return _answer("match", fixture_id, "no_pick", lines, terms=terms, links=("transparency",))
    s = fetch_one(conn, NO_PICK_SQL, {"f": fixture_id, "at": moment, "since": moment - CONSENSUS_LOOKBACK}) or {}
    evaluated = int(s.get("evaluated") or 0)
    if not s.get("forecast"):
        why = _say("no_pick_no_forecast")
    elif not s.get("prices"):
        why = _say("no_pick_no_prices")
    elif not evaluated:
        why = _say("no_pick_not_compared")
    elif s.get("selected"):
        why = _say("no_pick_not_published", evaluated=evaluated)
    else:
        no_value, odds, market = int(s.get("no_value") or 0), int(s.get("odds") or 0), int(s.get("market") or 0)
        why = _say("no_pick_no_value", evaluated=evaluated, no_value=no_value, odds=odds, market=market,
                   other=evaluated - no_value - odds - market)
    return _answer("match", fixture_id, "no_pick", [why, rule, _say("no_pick_may_change")], terms=terms,
                   links=("transparency",))


def _likely(m: ForecastMarket) -> tuple[str, Decimal] | None:
    best = next((o for o in m.outcomes if o.likely), None)
    return None if best is None else (best.selection, best.probability)


def _forecast(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None) -> Explanation:
    found = forecast_service.match_forecast(conn, fixture_id, preview=preview, at=at)
    terms = ("forecast", "probability", "calibrated", "pick", "value")
    if found.status is not DataStatus.OK or found.data is None:
        return _answer("match", fixture_id, "forecast", [_say("forecast_hidden")], answered=False, terms=terms)
    section = found.data.forecast
    if not section.data:
        # the reading's own fact, worded with the reading's template: no forecast yet, too far ahead, a competition the
        # models do not cover...
        missing = ReadingFact(code="forecast_missing", params={"reason": section.code or "no_forecast_yet"}, ref="forecast")
        return _answer("match", fixture_id, "forecast", [_fact(missing)], answered=False, terms=terms, links=("glossary",))
    fixture = _fixture(conn, fixture_id)
    lines = [_say("forecast_what")]
    for m in section.data:
        likely = _likely(m)
        lines.append(_say("forecast_market", market=m.market, line=float(m.line), home=fixture["home"],
                          away=fixture["away"], likely=None if likely is None else likely[0],
                          p=None if likely is None else float(likely[1]), calibrated=m.calibration == "CALIBRATED",
                          selections=[o.selection for o in m.outcomes],
                          probabilities=[float(o.probability) for o in m.outcomes]))
    calibrated = {m.calibration == "CALIBRATED" for m in section.data}
    if True in calibrated:
        lines.append(_say("forecast_calibrated"))
    if False in calibrated:
        lines.append(_say("forecast_uncalibrated"))
    lines.append(_say("forecast_not_pick"))
    return _answer("match", fixture_id, "forecast", lines, terms=terms, links=("glossary",))


def _reading(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None) -> MatchReading | None:
    found = reading_service.match_reading(conn, fixture_id, preview=preview, at=at)
    return found.data if found.status is DataStatus.OK else None


def _match_risks(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None) -> Explanation:
    _fixture(conn, fixture_id)
    reading = _reading(conn, fixture_id, preview=preview, at=at)
    if reading is None:
        return _answer("match", fixture_id, "risks", [_say("risks_hidden")], answered=False, terms=("forecast",))
    facts = next((s.facts for s in reading.sections if s.key == "risks"), [])
    lines = [_say("risks_intro"), *(_fact(f) for f in facts)] if facts else [_say("risks_none")]
    if not reading.complete:
        lines.append(_say("risks_incomplete"))
    return _answer("match", fixture_id, "risks", lines, answered=bool(facts), terms=("forecast", "probability"))


# ── a pick ────────────────────────────────────────────────────────────────────────────

def _pick(conn: Conn, pick_id: int, *, preview: bool, at: datetime | None) -> PickExplanation:
    return explanation_service.pick_explanation(conn, pick_id, preview=preview, at=at).data


def _pick_risks(conn: Conn, pick_id: int, *, preview: bool, at: datetime | None) -> Explanation:
    e = _pick(conn, pick_id, preview=preview, at=at)
    m = e.market
    lines = [_say("pick_probability", p=float(m.p_model))]
    if m.p_low is not None and m.p_high is not None and m.p_high > m.p_low:
        lines.append(_say("pick_interval", low=float(m.p_low), high=float(m.p_high)))
    lines += [_fact(f) for f in e.risks]
    if e.review is not None and e.review.risks:
        lines.append(_say("pick_review_risks", risks=list(e.review.risks)))
    if not e.reading_shown:
        lines.append(_say("pick_reading_hidden"))
    elif not e.reading_complete:
        lines.append(_say("risks_incomplete"))
    if e.started:
        lines.append(_say("pick_started"))
    return _answer("pick", pick_id, "risks", lines, terms=("probability", "range", "pick"), links=("why_pick",))


CAUTION_LINES: Final[dict[str, str]] = {
    "downgraded": "caution_downgraded",
    "approved": "caution_none_approved",
    "value": "caution_none_pending",
    "not_reviewed": "caution_none_not_reviewed",
    "no_value_now": "caution_no_value",
    "rejected": "caution_rejected",
    "evaluation": "caution_evaluation",
}
"""The state's reason (``fbi.picks.user_status.StatusReason``) and the sentence that answers «¿Por qué cautela?» for it."""


def _caution(conn: Conn, pick_id: int, *, preview: bool, at: datetime | None) -> Explanation:
    e = _pick(conn, pick_id, preview=preview, at=at)
    lines = [_say(CAUTION_LINES[e.status_reason], status=e.user_status)]
    if e.status_reason == "downgraded" and e.review is not None and e.review.risks:
        lines.append(_say("pick_review_risks", risks=list(e.review.risks)))
    lines.append(_say("caution_what"))
    return _answer("pick", pick_id, "caution", lines, terms=("pick", "value"), links=("why_pick",))


# ── the parlay being built ────────────────────────────────────────────────────────────

NAMES_SQL = """
SELECT f.id, th.name AS home, ta.name AS away
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = ANY(%(ids)s)
"""


def explain_slip(conn: Conn, legs: list[LegIn], *, at: datetime | None = None) -> Envelope[Explanation]:
    """«¿Por qué baja la probabilidad de mi parlay?» for the legs the slip holds, checked as the slip checks them."""
    terms = ("parlay", "probability", "dependency")
    v = userdata.validate_parlay(conn, legs, at=at or now())
    broken = [e for e in v.errors if e.get("code") != "leg_count"]
    if broken:
        lines = [_say("parlay_invalid")]
        lines += [_say("parlay_issue", **{"code": str(e.get("code")), "leg": e.get("leg"), "with": e.get("with")})
                  for e in broken]
        return ok(_answer("parlay", None, "probability", lines, answered=False, terms=terms))
    names = {int(r["id"]): r for r in fetch_all(conn, NAMES_SQL, {"ids": [leg.fixture_id for leg in legs]})}
    lines = [_say("parlay_single") if len(legs) == 1 else _say("parlay_all_win", legs=len(legs))]
    missing: list[str] = []
    probabilities: list[float] = []
    for leg in v.legs:
        p = leg.get("p_used") or leg.get("p_model") or leg.get("p_fair")
        named = names.get(int(leg["fixture_id"]), {})
        lines.append(_say("parlay_leg", leg=int(leg["leg"]), home=named.get("home"), away=named.get("away"),
                          market=str(leg["market_key"]), selection=str(leg["selection"]), line=float(Decimal(leg["line"])),
                          p=None if p is None else float(Decimal(p)),
                          source=None if p is None else ("model" if leg.get("p_model") else "market")))
        if p is None:
            missing.append(str(leg["leg"]))
        else:
            probabilities.append(float(Decimal(p)))
    if missing:
        lines.append(_say("parlay_leg_missing", legs=missing))
        return ok(_answer("parlay", None, "probability", lines, answered=False, terms=terms))
    if len(legs) > 1:
        product = 1.0
        for p in probabilities:
            product *= p
        lines.append(_say("parlay_product", probabilities=probabilities, p=round(product, 6)))
        level = str((v.dependency or {}).get("level") or "low")
        if level != "low":
            reasons = [str(r) for r in (v.dependency or {}).get("reasons", [])]
            # the slip adjusts its estimate only where it measured how the legs move together (fbi.parlays.correlation)
            measured = any(w.get("code") == "same_competition_day" and w.get("rho") is not None for w in v.warnings)
            if measured and v.estimated_probability is not None:
                lines.append(_say("parlay_dependency", level=level, reasons=reasons, p=float(v.estimated_probability)))
            else:
                lines.append(_say("parlay_related", level=level, reasons=reasons))
        lines.append(_say("parlay_shrinks"))
    if v.fair_probability is not None and any(w.get("code") == "very_unlikely" for w in v.warnings):
        # the slip's own warning, on its own number: every leg wins by the market's probabilities, margin removed
        lines.append(_say("parlay_very_unlikely", p=float(v.fair_probability)))
    return ok(_answer("parlay", None, "probability", lines, terms=terms))


# ── the door ──────────────────────────────────────────────────────────────────────────

def explain(conn: Conn, entity: ExplainEntity, item_id: int, intent: ExplainIntent, *, preview: bool,
            at: datetime | None = None) -> Envelope[Explanation]:
    """The answer to one question of a match or a pick (the parlay being built: ``explain_slip``)."""
    if entity == "parlay" or intent not in INTENTS[entity]:
        raise ApiError(422, "unknown_question", f"no question {intent!r} for a {entity}")
    if entity == "match":
        if intent == "no_pick":
            return ok(_no_pick(conn, item_id, at))
        if intent == "forecast":
            return ok(_forecast(conn, item_id, preview=preview, at=at))
        return ok(_match_risks(conn, item_id, preview=preview, at=at))
    if intent == "risks":
        return ok(_pick_risks(conn, item_id, preview=preview, at=at))
    return ok(_caution(conn, item_id, preview=preview, at=at))

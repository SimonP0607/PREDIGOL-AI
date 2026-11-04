"""«¿Por qué PrediGol eligió este pick?» (plan UX, B3; section 28 of the plan): one pick in five layers, built from what is already
stored - nothing is estimated here, no model is called and nothing is written.

    1 conclusion  what PrediGol expects, in one sentence: the web's template over the pick's own numbers (layer 3)
    2 context     the facts of the match's structured reading (A9) - its context and data sections, each with its reference -
                  or, when the reader may see it, the validated narrative of that same reading (A11)
    3 market      PrediGol's probability against the market's, the price it was published at and the best price now
    4 risks       how often a selection like this fails and the model's own doubt (the web's templates over layer 3), the
                  reading's risks and, only while the AI's review is applied, the review's own
    5 how         the steps of «Cómo se decide» (the web's, the same as Transparencia) and whether this is a pick of the day

Who sees what: a reader, a published pick (qualified or published, also once settled); a shadow pick only in the owner's preview,
labelled EVALUATION - never a recommendation. Anything else is 404, so a reader never learns that a shadow pick exists.

The state (``user_status``) is the one table's (``fbi/picks/user_status.py``): before kick-off at the best price now, re-priced with
the same gate as the list of picks (``fbi.api.services.product``); once the match started, as the pick was taken. A pick of the day
also carries the state it entered the set with (``day``), the one its card shows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fbi.api.cache import shared
from fbi.api.contracts.explanation import (
    ExplanationDay,
    ExplanationMarket,
    ExplanationReview,
    PickExplanation,
)
from fbi.api.contracts.reading import ReadingNarrative
from fbi.api.contracts.records import SetSource
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, Row, fetch_one
from fbi.api.repositories import product as repo
from fbi.api.services import pick_status
from fbi.api.services import reading as reading_service
from fbi.api.services.product import CONSENSUS_LOOKBACK, candidate_of
from fbi.api.services.records import CLAIM_GROUPS, MATCH_COLS, MATCH_JOINS, item_state, match_of
from fbi.core.clock import now as clock_now
from fbi.parlays import engine
from fbi.parlays.engine import GateConfig, Leg
from fbi.picks import user_status

VERSION: Final = "pick-explanation-v1"
CONTEXT_SECTIONS: Final = ("context", "data")
NARRATIVE_SECTIONS: Final = frozenset({"context", "data", "risks"})

PICK_SQL = """
SELECT p.id AS pick_id, p.fixture_id, p.market_key, p.selection, p.line,
       COALESCE(NULLIF(p.status, 'settled'),
                (SELECT e.from_status FROM picks.pick_events e
                  WHERE e.pick_id = p.id AND e.to_status = 'settled' AND e.event_kind = 'status'
                  ORDER BY e.at LIMIT 1)) AS pick_status,
       p.p_calibrated AS p_model, p.p_calibrated_lo AS p_low, p.p_calibrated_hi AS p_high,
       p.p_market_fair AS p_market_taken, p.market_odds AS odds_taken, p.odds_captured_at AS taken_at,
       b.name AS bookmaker_taken, """ + MATCH_COLS + """
  FROM picks.picks p
  LEFT JOIN market.bookmakers b ON b.id = p.bookmaker_id
""" + MATCH_JOINS.format(alias="p") + """
 WHERE p.id = %(pick)s
"""
"""The pick, what it was before it was settled, and its match as every record shows it."""

DAY_SQL = """
SELECT s.day, i.rank, i.stage, i.selected_at, i.odds, b.name AS bookmaker, i.inputs
  FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id
  LEFT JOIN market.bookmakers b ON b.id = i.bookmaker_id
 WHERE i.pick_id = %(pick)s AND s.source = %(source)s
 ORDER BY s.day DESC, i.rank LIMIT 1
"""
"""The pick in a set of the day: the published set for a published pick, the evaluation set for a shadow pick (the preview)."""

REVIEW_SQL = """
SELECT r.decision, r.output
  FROM ai.pick_reviews r
 WHERE r.engine = 'combined' AND r.fixture_id = %(fixture)s AND r.market_key = %(market)s AND r.selection = %(selection)s
   AND r.line = %(line)s AND r.reviewed_at <= %(at)s AND r.reviewed_at >= %(at)s - make_interval(hours => %(hours)s)
 ORDER BY r.reviewed_at DESC, r.id DESC LIMIT 1
"""
"""The review the state reads (``fbi.api.services.pick_status.REVIEWS_SQL``, one selection), with its claims."""


def _visible(status: str | None, *, preview: bool) -> bool:
    return user_status.is_published(status) or (preview and status == "shadow")


def _day(conn: Conn, r: Row, *, shadow: bool) -> ExplanationDay | None:
    source: SetSource = "evaluation" if shadow else "qualified"
    d = fetch_one(conn, DAY_SQL, {"pick": int(r["pick_id"]), "source": source})
    if d is None:
        return None
    state = item_state(d, source)
    return ExplanationDay(day=d["day"], rank=int(d["rank"]), stage=d["stage"], selected_at=d["selected_at"],
                          odds=Decimal(d["odds"]), bookmaker=d["bookmaker"], user_status=state.status,
                          status_reason=state.reason, context_pending=state.context_pending)


def _review(conn: Conn, r: Row, *, at: datetime) -> ExplanationReview | None:
    row = fetch_one(conn, REVIEW_SQL, {"fixture": int(r["fixture_id"]), "market": r["market_key"],
                                       "selection": r["selection"], "line": Decimal(r["line"]), "at": at,
                                       "hours": pick_status.REVIEW_WINDOW_HOURS})
    if row is None or row["decision"] not in user_status.DECISIONS:
        return None
    output: dict[str, Any] = dict(row["output"] or {})
    texts = {k: [str(c.get("text")) for g in groups for c in output.get(g, []) or [] if isinstance(c, dict) and c.get("text")][:4]
             for k, groups in CLAIM_GROUPS.items()}
    return ExplanationReview(decision=row["decision"], positives=texts["positives"], risks=texts["risks"])


def _narrative(n: ReadingNarrative | None) -> ReadingNarrative | None:
    if n is None:
        return None
    return n.model_copy(update={"es": [s for s in n.es if s.key in NARRATIVE_SECTIONS],
                                "en": [s for s in n.en if s.key in NARRATIVE_SECTIONS]})


@shared(30)
def pick_explanation(conn: Conn, pick_id: int, *, preview: bool, at: datetime | None = None) -> Envelope[PickExplanation]:
    moment = at or clock_now()
    r = fetch_one(conn, PICK_SQL, {"pick": pick_id})
    if r is None or not _visible(r["pick_status"], preview=preview):
        raise ApiError(404, "not_found", "no such pick")
    shadow = r["pick_status"] == "shadow"
    fixture = int(r["fixture_id"])
    kickoff: datetime = r["m_kickoff_at"]
    started = kickoff <= moment  # as the list of picks: a pick is re-priced until its match's kick-off, never after
    line = Decimal(r["line"])

    odds_now = bookmaker_now = price_at = p_market_now = None
    value_now: bool | None = None
    if started:
        review_at = kickoff
        applied = pick_status.applied_now(conn, [fixture], at=review_at)
        state = applied.shown(pick_status=r["pick_status"], value=True, fixture_id=fixture, market_key=r["market_key"],
                              selection=r["selection"], line=line)
    else:
        review_at = moment
        rows = repo.pick_candidates(conn, now=moment, until=kickoff + timedelta(seconds=1), since=moment - CONSENSUS_LOOKBACK,
                                    include_shadow=preview, fixture_id=fixture)
        row = next((x for x in rows if int(x["pick_id"]) == pick_id), None)
        if row is not None:
            verdict = engine.assess(candidate_of(row), moment, GateConfig(allow_unqualified=preview))
            value_now = isinstance(verdict, Leg)
            odds_now = row.get("best_odds")
            bookmaker_now = row.get("bookmaker")
            price_at = row.get("price_at")
            p_market_now = row.get("p_fair")
        else:
            value_now = False
        applied = pick_status.applied_now(conn, [fixture], at=moment)
        state = applied.shown(pick_status=r["pick_status"], value=value_now, fixture_id=fixture,
                              market_key=r["market_key"], selection=r["selection"], line=line)

    day = _day(conn, r, shadow=shadow)
    market = ExplanationMarket(
        p_model=Decimal(r["p_model"]), p_low=r["p_low"], p_high=r["p_high"],
        p_market=r["p_market_taken"] if started else p_market_now,
        published_odds=day.odds if day else Decimal(r["odds_taken"]),
        published_bookmaker=day.bookmaker if day else r["bookmaker_taken"],
        published_at=day.selected_at if day else r["taken_at"],
        odds_now=odds_now, bookmaker_now=bookmaker_now, price_at=price_at, value_now=value_now)

    shown = preview or reading_service.users_may_see()
    context: list[Any] = []
    risks: list[Any] = []
    narrative = None
    complete = False
    reading_at = None
    if shown:
        basis = reading_service.reading_basis(conn, fixture, at=moment)
        sections = {s.key: s.facts for s in basis.sections}
        context = [f for key in CONTEXT_SECTIONS for f in sections.get(key, [])]
        risks = list(sections.get("risks", []))
        narrative = _narrative(reading_service.narrative_for(conn, basis, preview=preview))
        complete = basis.packet_id is not None
        reading_at = basis.data_at

    body = PickExplanation(
        pick_id=int(r["pick_id"]), version=VERSION, match=match_of(r, moment), market_key=r["market_key"],
        selection=r["selection"], line=line, started=started, user_status=state.status, status_reason=state.reason,
        context_pending=state.context_pending, day=day, reading_shown=shown, reading_complete=complete,
        reading_at=reading_at, context=context, narrative=narrative, market=market, risks=risks,
        review=_review(conn, r, at=review_at) if applied.enforced else None)
    newest = max((t for t in (reading_at, price_at) if t is not None), default=None)
    return ok(body, data_as_of=newest)

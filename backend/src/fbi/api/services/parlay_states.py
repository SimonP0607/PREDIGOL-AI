"""C-04, the parlays with their state, read for both projections (AD-J05, IA-132). Reading only.

* PUBLIC - ``public_state`` turns the product's parlay of a kind (``GET /parlays/{kind}``: ``parlay-v5`` built now from the qualified
  picks, ``fbi.api.services.product.parlay_board``) into the public projection of C-04, only while ``FBI_MATCH_INTELLIGENCE`` is on and
  only for what a reader is shown: the owner's preview (``source = shadow_preview``) never gets it. The route adds it to its answer;
  with the switch off nothing changes.
* PRIVATE - ``private`` reads ``parlay-v6`` in the shadow (``intel.parlays_v6`` and ``intel.parlay_v6_legs``, IA-110) of a period with
  each leg's newest settlement (``intel.selection_settlements``, IA-109), beside the product's parlays of now (given by the route) and
  ``parlay-v5``'s kept history by state (``picks.parlays``). A table the database does not have yet leaves its block «sin datos».

``fbi.tracking`` is not imported: it is a leaf that only the shadow's doors import (``tests/unit/test_tracking_ia109.py``). What this
module needs of it - the writer of the chains, the rule's thresholds, how a result is read from the legs and how the joint is measured
against the results - is restated here and held equal to the code by ``tests/unit/test_parlay_states_contract.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing, Probability
from fbi.api.contracts.intelligence.parlays import (
    RULES,
    ParlaySetCalibration,
    ParlaySetCardPrivate,
    ParlaySetLegPrivate,
    ParlaySetPeriod,
    ParlaySetRefusal,
    ParlaySetResult,
    ParlaySetRule,
    ParlaySetState,
    ParlaySetStatePrivate,
    ParlaySetStatus,
    ParlaySetV5Count,
)
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.product import Parlay
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.switches import match_intelligence_on
from fbi.core.calendar import local_day
from fbi.core.clock import now as clock_now

V5: Final = "parlay-v5"
V6: Final = "parlay-v6"
CHAINS: Final = "decision-v2-shadow-v1"
"""The writer of the chains whose confirmations are parlay-v6's legs (``fbi.tracking.parlay_v6_shadow.CHAINS``)."""
CALIBRATION_NEEDED: Final = 100
"""parlay-v6's calibration is not judged with fewer settled parlays (``parlay_v6_shadow.calibration``)."""
DEFAULT_BACK: Final = 6
MAX_DAYS: Final = 31
TIMEOUT_MS: Final = 30_000
NO_DATA: Final = Missing(missing_reason="sin_datos")
RESULT_WORD: Final[dict[str, ParlaySetResult]] = {"ACTIVE": "pendiente", "WON": "ganado", "LOST": "perdido", "VOID": "nulo",
                                                  "PARTIAL_VOID": "parcial_nulo"}

EXISTS_SQL: Final = """
SELECT to_regclass('intel.parlays_v6') IS NOT NULL AND to_regclass('intel.parlay_v6_legs') IS NOT NULL
       AND to_regclass('intel.selection_settlements') IS NOT NULL AS ok
"""
V6_SQL: Final = """
SELECT p.id, p.kind, p.day, p.outcome, p.none_reason, p.max_legs, p.n_legs, p.n_candidates, p.window_from, p.window_to,
       p.combined_odds::float8 AS combined_odds, p.p_joint::float8 AS p_joint, p.p_joint_se::float8 AS p_joint_se,
       p.p_joint_low::float8 AS p_joint_low, p.p_product::float8 AS p_product, p.p_market_joint::float8 AS p_market_joint,
       p.fair_odds::float8 AS fair_odds, p.accumulated_margin::float8 AS accumulated_margin,
       p.expected_value::float8 AS expected_value, p.expected_value_low::float8 AS expected_value_low, p.inputs, p.known_at,
       p.rule_version
  FROM intel.parlays_v6 p
 WHERE p.writer = %(writer)s AND p.day >= %(start)s AND p.day <= %(end)s AND (%(kind)s::text IS NULL OR p.kind = %(kind)s)
 ORDER BY p.day DESC, p.kind
 LIMIT 200
"""
"""The kept parlays of the period, newest product day first (two a day at most: one per kind)."""
V6_LEGS_SQL: Final = """
SELECT l.parlay_id, l.leg_no, l.chain_key, l.fixture_id, l.kickoff_at, l.market_key, l.selection, l.line, l.odds::float8 AS odds,
       l.p_model::float8 AS p_model, l.p_low::float8 AS p_low, l.p_market::float8 AS p_market,
       (SELECT s.result FROM intel.selection_settlements s WHERE s.chain_key = l.chain_key AND s.kind IN ('primera', 'correccion')
         ORDER BY s.known_at DESC, s.id DESC LIMIT 1) AS result
  FROM intel.parlay_v6_legs l WHERE l.parlay_id = ANY(%(ids)s) ORDER BY l.parlay_id, l.leg_no
"""
"""Each leg and its newest settlement (``parlay_v6_shadow.LEGS_SQL``'s reading)."""
V5_HISTORY_SQL: Final = """
SELECT kind, source, status, count(*)::int AS parlays FROM picks.parlays
 WHERE day >= %(start)s AND day <= %(end)s AND (%(kind)s::text IS NULL OR kind = %(kind)s)
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""


# ── what is restated of parlay-v6 (held equal to fbi.tracking by a test) ────────────────────────────────────────────

def outcome(results: Sequence[str | None], odds: Sequence[float]) -> tuple[str, float | None]:
    """A parlay-v6 parlay's result from its legs' settlements and the payout of a 1-unit stake (``parlay_v6.outcome``). Pure."""
    if any(r == "loss" for r in results):
        return "LOST", 0.0
    if any(r is None for r in results):
        return "ACTIVE", None
    if any(r not in ("win", "void") for r in results):
        raise ValueError(f"a leg of {V6} cannot settle {sorted(str(r) for r in set(results) - {'win', 'void'})}")
    if all(r == "void" for r in results):
        return "VOID", 1.0
    factor = math.prod(o for r, o in zip(results, odds, strict=True) if r == "win")
    return ("PARTIAL_VOID" if "void" in results else "WON"), factor


def calibration(parlays: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The joint against the results of the settled parlays (``parlay_v6_shadow.calibration``). Pure."""
    done = [p for p in parlays if p.get("status") in ("WON", "LOST")]
    n = len(done)
    won = sum(1 for p in done if p["status"] == "WON")
    if not n:
        return {"settled": 0, "won": 0, "expected": None, "expected_low": None, "brier": None}
    exp = sum(float(p["p_joint"]) for p in done)
    low = sum(float(p["p_joint_low"]) for p in done)
    brier = sum((float(p["p_joint"]) - (p["status"] == "WON")) ** 2 for p in done) / n
    return {"settled": n, "won": won, "expected": round(exp, 4), "expected_low": round(low, 4), "brier": round(brier, 6)}


def v6_rule(max_legs: int | None = None) -> ParlaySetRule:
    r = RULES[V6]
    return ParlaySetRule(version=V6, min_legs=int(r["min_legs"]), max_legs=int(max_legs or r["max_legs"]),  # type: ignore[call-overload]
                         max_per_match=int(r["max_per_match"]), joint="simulacion_copula")  # type: ignore[call-overload]


# ── small conversions ────────────────────────────────────────────────────────────────────────────────────────────────

def _pct(x: float | Decimal | None, nd: int = 1) -> float | Missing:
    return NO_DATA if x is None else round(float(x) * 100, nd)


def _num(x: float | Decimal | None, nd: int = 4) -> float | Missing:
    return NO_DATA if x is None else round(float(x), nd)


def _joint(p: float | Decimal | None, *, at: datetime, origin: str) -> Probability | Missing:
    if p is None or not 0 <= float(p) <= 1:
        return NO_DATA
    return Probability.of(float(p), calibration="sin_calibrar", as_of=at, origin=origin, evaluation=NO_DATA,
                          evaluation_version=NO_DATA, interval=NO_DATA, decimals=1)


def _fair(p: float | Decimal | None) -> float | Missing:
    return NO_DATA if p is None or float(p) <= 0 else round(1 / float(p), 2)


def status_of(word: str, kickoffs: Sequence[datetime], *, at: datetime) -> ParlaySetStatus:
    """The state of a built set: settled once its result is known, in play once a leg kicked off, otherwise built. Pure."""
    if word != "ACTIVE":
        return "liquidado"
    return "en_juego" if any(k <= at for k in kickoffs) else "armado"


def _legs[T](items: list[T]) -> ItemList[T]:
    return ItemList[T](items=items) if items else ItemList[T](items=[], missing_reason="sin_datos")


# ── the product's parlay (parlay-v5, built now) ─────────────────────────────────────────────────────────────────────

def v5_card(parlay: Parlay) -> ParlaySetCardPrivate:
    """The product's parlay of a kind as a card of C-04. A reader's (``qualified``) is published; the preview's never is. Pure."""
    at = parlay.generated_at
    built = parlay.status == "ok"
    legs = [ParlaySetLegPrivate(fixture_id=x.fixture_id, kickoff_at=x.kickoff_at, market=x.market_key, selection=x.selection,
                                line=float(x.line), odds=float(x.odds), result="pending", ref=f"pick:{x.pick_id}",
                                probability_pct=_pct(x.p_win), probability_low_pct=NO_DATA, market_pct=_pct(x.p_market))
            for x in parlay.legs] if built else []
    p = parlay.probability_all_win if built else None
    return ParlaySetCardPrivate(
        kind=parlay.kind, status="armado" if built else "ninguno", result="pendiente" if built else NO_DATA,
        none_reason=None if built else "NINGUNO_CUMPLE",
        rule=ParlaySetRule(version=V5, min_legs=parlay.required_legs, max_legs=parlay.max_legs, max_per_match=1, joint="producto"),
        window_from=parlay.window_from, window_to=parlay.window_to, built_at=at, legs=_legs(legs),
        combined_odds=_num(parlay.combined_odds) if built else NO_DATA, joint=_joint(p, at=at, origin=V5),
        fair_odds=_fair(p), accumulated_margin_pct=NO_DATA,
        expected_value_pct=_pct(parlay.expected_value) if built else NO_DATA,
        published=parlay.source == "qualified", source="en_vivo", stored_id=NO_DATA, day=local_day(at),
        candidates=parlay.eligible_legs, none_detail=NO_DATA,
        refused=[ParlaySetRefusal(code=k, count=v) for k, v in sorted(parlay.rejections.items()) if v > 0
                 and k.replace("_", "").isalnum() and k.islower()],
        joint_low=NO_DATA, joint_se=NO_DATA, product_of_legs=_num(p, 8), market_joint_pct=NO_DATA, expected_value_low_pct=NO_DATA,
        payout_factor=NO_DATA)


def public_state(parlay: Parlay, *, at: datetime | None = None) -> ParlaySetState | None:
    """The public C-04 of the product's parlay, or None: with ``FBI_MATCH_INTELLIGENCE`` off, or for the owner's preview (only what a
    reader is shown has a public projection)."""
    if not match_intelligence_on() or parlay.source != "qualified":
        return None
    moment = at or parlay.generated_at
    card = v5_card(parlay)
    day = card.day
    answer = ParlaySetStatePrivate(
        freshness=Freshness(generated_at=moment, stale=False), parlays=ItemList[ParlaySetCardPrivate](items=[card]),
        period=ParlaySetPeriod(date_from=day, date_to=day, kind=parlay.kind), calibration=NO_DATA,
        v5_history=ItemList[ParlaySetV5Count](items=[], missing_reason="sin_datos"))
    projected = to_public(answer, ParlaySetState)
    assert isinstance(projected, ParlaySetState)
    return projected


# ── parlay-v6 in the shadow ──────────────────────────────────────────────────────────────────────────────────────────

def v6_card(row: Mapping[str, Any], legs: Sequence[Mapping[str, Any]], *, at: datetime) -> ParlaySetCardPrivate:
    """One kept row of ``intel.parlays_v6`` and its legs as a card of C-04 (never published). Pure."""
    known: datetime = row["known_at"]
    refused_raw = (row.get("inputs") or {}).get("refused") or {}
    refused = [ParlaySetRefusal(code=str(k), count=int(v)) for k, v in sorted(refused_raw.items()) if int(v) > 0]
    common: dict[str, Any] = {
        "kind": row["kind"], "rule": v6_rule(int(row["max_legs"])), "window_from": row["window_from"], "window_to": row["window_to"],
        "built_at": known, "published": False, "source": "intel.parlays_v6", "stored_id": int(row["id"]), "day": row["day"],
        "candidates": int(row["n_candidates"]), "refused": refused}
    if row["outcome"] != "built":
        return ParlaySetCardPrivate(
            **common, status="ninguno", result=NO_DATA, none_reason="NINGUNO_CUMPLE", legs=_legs([]), combined_odds=NO_DATA,
            joint=NO_DATA, fair_odds=NO_DATA, accumulated_margin_pct=NO_DATA, expected_value_pct=NO_DATA,
            none_detail=row["none_reason"] or "ninguna_combinacion_cumple", joint_low=NO_DATA, joint_se=NO_DATA,
            product_of_legs=NO_DATA, market_joint_pct=NO_DATA, expected_value_low_pct=NO_DATA, payout_factor=NO_DATA)
    results = [None if x["result"] is None else str(x["result"]) for x in legs]
    word, factor = outcome(results, [float(x["odds"]) for x in legs])
    cards = [ParlaySetLegPrivate(fixture_id=int(x["fixture_id"]), kickoff_at=x["kickoff_at"], market=str(x["market_key"]),
                                 selection=str(x["selection"]), line=float(x["line"]), odds=float(x["odds"]),
                                 result="pending" if r is None else r,  # type: ignore[arg-type]  # settle-v4's words
                                 ref=str(x["chain_key"]), probability_pct=_pct(x["p_model"]), probability_low_pct=_pct(x["p_low"]),
                                 market_pct=_pct(x["p_market"])) for x, r in zip(legs, results, strict=True)]
    return ParlaySetCardPrivate(
        **common, status=status_of(word, [x["kickoff_at"] for x in legs], at=at), result=RESULT_WORD[word], none_reason=None,
        legs=_legs(cards), combined_odds=_num(row["combined_odds"]), joint=_joint(row["p_joint"], at=known, origin=V6),
        fair_odds=_num(row["fair_odds"], 2), accumulated_margin_pct=_pct(row["accumulated_margin"], 2),
        expected_value_pct=_pct(row["expected_value"]), none_detail=NO_DATA,
        joint_low=_joint(row["p_joint_low"], at=known, origin=V6), joint_se=_num(row["p_joint_se"], 6),
        product_of_legs=_num(row["p_product"], 8), market_joint_pct=_pct(row["p_market_joint"]),
        expected_value_low_pct=_pct(row["expected_value_low"]), payout_factor=NO_DATA if factor is None else round(factor, 4))


def assemble(*, at: datetime, period: ParlaySetPeriod, live: Sequence[Parlay], v6_rows: Sequence[Mapping[str, Any]] | None,
             v6_legs: Sequence[Mapping[str, Any]], v5_counts: Sequence[Mapping[str, Any]] | None) -> ParlaySetStatePrivate:
    """The private C-04 from what was read (``v6_rows`` None: the tables do not exist). Pure."""
    by_parlay: dict[int, list[Mapping[str, Any]]] = {}
    for leg in v6_legs:
        by_parlay.setdefault(int(leg["parlay_id"]), []).append(leg)
    cards = [v5_card(p) for p in live if period.kind in (None, p.kind)]
    stored = [v6_card(r, by_parlay.get(int(r["id"]), []), at=at) for r in v6_rows or []]
    cards += stored
    if v6_rows is None:
        cal: ParlaySetCalibration | Missing = NO_DATA
    else:
        c = calibration([{"status": {v: k for k, v in RESULT_WORD.items()}[x.result] if isinstance(x.result, str) else None,
                          "p_joint": x.joint.value if isinstance(x.joint, Probability) else None,
                          "p_joint_low": x.joint_low.value if isinstance(x.joint_low, Probability) else None} for x in stored])
        cal = ParlaySetCalibration(settled=c["settled"], won=c["won"],
                                   expected_wins=NO_DATA if c["expected"] is None else c["expected"],
                                   expected_wins_low=NO_DATA if c["expected_low"] is None else c["expected_low"],
                                   brier=NO_DATA if c["brier"] is None else c["brier"], needed=CALIBRATION_NEEDED)
    history = [ParlaySetV5Count(kind=r["kind"], source=r["source"], status=r["status"], parlays=int(r["parlays"]))
               for r in v5_counts or []]
    return ParlaySetStatePrivate(
        freshness=Freshness(generated_at=at, stale=False),
        parlays=ItemList[ParlaySetCardPrivate](items=cards) if cards else ItemList[ParlaySetCardPrivate](
            items=[], missing_reason="sin_datos"),
        period=period, calibration=cal,
        v5_history=ItemList[ParlaySetV5Count](items=history) if history else ItemList[ParlaySetV5Count](
            items=[], missing_reason="sin_datos"))


def private(conn: Conn, *, live: Sequence[Parlay], kind: str | None = None, date_from: date | None = None,
            date_to: date | None = None, at: datetime | None = None) -> ParlaySetStatePrivate:
    """The private C-04 of the product days ``date_from`` to ``date_to`` (the last seven by default, 31 at most). Reading only."""
    moment = at or clock_now()
    end = date_to or local_day(moment)
    start = date_from or end - timedelta(days=DEFAULT_BACK)
    if start > end or (end - start).days >= MAX_DAYS:
        raise ApiError(422, "invalid_period", f"from must not be after to, and at most {MAX_DAYS} days")
    period = ParlaySetPeriod(date_from=start, date_to=end, kind=kind)  # type: ignore[arg-type]  # the route's Literal
    params = {"writer": CHAINS, "start": start, "end": end, "kind": kind}
    conn.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
    rows: list[dict[str, Any]] | None = None
    legs: list[dict[str, Any]] = []
    if (fetch_one(conn, EXISTS_SQL, {}) or {}).get("ok"):
        rows = fetch_all(conn, V6_SQL, params)
        ids = [int(r["id"]) for r in rows if r["outcome"] == "built"]
        legs = fetch_all(conn, V6_LEGS_SQL, {"ids": ids}) if ids else []
    counts = fetch_all(conn, V5_HISTORY_SQL, params)
    return assemble(at=moment, period=period, live=live, v6_rows=rows, v6_legs=legs, v5_counts=counts)

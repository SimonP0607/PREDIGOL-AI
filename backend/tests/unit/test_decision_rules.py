"""The decision layer's documented rules, on the real ``evaluate`` (no database): what each filter does when it fails.

Plan F0, defect 12 (documentation and code diverged): the document said a forecast could be 48 h old (the code allows 72),
that a price not fresh at the end was a RECHAZADO (it is a CAUTELA), that a PICK PREMIUM needed a score and the CLV of its
type (it needs the walk-forward CLV of the market's rule as well) and that a parlay used the measured dependence (it
multiplies two probabilities from different competitions). ``test_docs_match_code`` holds the document to these numbers
and to the effects this file produces."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.intel import decision
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.intel.decision import Evaluated, World, evaluate

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)
MARKET, MODEL, SELECTION = "OU", "dixon_coles", "Over"
LINE = Decimal("2.5")
STALE = decision.FINAL_FRESH + timedelta(minutes=15)
"""A price older than a final checkpoint tolerates, and younger than any price is allowed to be."""


def key_of(fixture: int = 1, line: Decimal = LINE) -> decision.Key:
    return (fixture, MARKET, SELECTION, line)


def world(*, fixture: int = 1, rule_clv: float | None = 0.03, edge: bool = True,
          type_clv: tuple[float, int] | None = (0.03, 80), odds: float = 2.10, data_class: str = "MODEL_READY",
          quarantined: bool = False, lineups: bool = False, calibrated: bool = True,
          rules: dict[str, str] | None = None, review: str | None = None, approved_before: bool = False) -> World:
    """A market whose calibrator is the champion (identity), whose edge is validated, whose walk-forward rule has a CLV
    of ``rule_clv`` and whose kind of pick (market x selection x odds band) has ``type_clv`` = (mean, n) over the last
    30 days. ``rules`` are the signals of the rules review (code -> severity), ``review`` the combined review's
    decision, ``lineups`` whether the line-ups are in, ``approved_before`` whether the last decision was an approval."""
    champion = Calibrator(MARKET, MODEL, "identity", {}, None, "CHAMPION")
    wf = {"ece_cal": 0.01, "rule_clv": rule_clv, "logloss_cal": 0.60}
    cal = CalibrationState({(MARKET, MODEL): champion} if calibrated else {}, {}, {(MARKET, MODEL): wf},
                           {(MARKET, MODEL): edge})
    key = key_of(fixture)
    signals = [{"code": c, "severity": s} for c, s in (rules or {}).items()]
    reviews = {} if review is None else {key: {"id": 5, "decision": review, "confidence": 0.7, "reviewed_at": AT,
                                              "engine_version": "rules-review-v1+none", "output": {"reason": "test"}}}
    kinds = {} if type_clv is None else {(MARKET, SELECTION, decision.odds_band(odds)): type_clv}
    return World(AT, cal, {fixture: {"data_class": data_class, "quarantined": quarantined}}, reviews,
                 {key: {"output": {"negative_evidence": signals}}} if signals else {}, {}, {},
                 {fixture: AT - timedelta(minutes=5)} if lineups else {}, kinds,
                 {key: {"state": "APROBADO"}} if approved_before else {}, "shadow")


def row(*, fixture: int = 1, odds: float | None = 2.10, p_model: float = 0.62, p_fair: float | None = 0.50,
        minutes: float = 360, forecast_age: timedelta = timedelta(hours=2), price_age: timedelta = timedelta(minutes=5),
        books: int = 9, overround: float = 0.04, width: float = 0.04, status: str = "NS",
        group: str = "scheduled", line: Decimal = LINE) -> dict[str, Any]:
    return {"pick_id": 1, "fixture_id": fixture, "market_key": MARKET, "selection": SELECTION, "line": line,
            "model_name": MODEL, "model_version_id": 1, "p_model": p_model, "p_push": 0.0,
            "p_low": p_model - width / 2, "p_high": p_model + width / 2, "data_cutoff_ts": AT - forecast_age,
            "kickoff_at": AT + timedelta(minutes=minutes), "status_short": status, "status_group": group,
            "p_fair": p_fair, "best_odds": odds, "best_bookmaker_id": 1, "n_bookmakers": books, "overround": overround,
            "price_at": AT - price_age, "competition_id": 10, "home_team_id": 100 + 2 * fixture,
            "away_team_id": 101 + 2 * fixture}


def run(w: World | None = None, **kw: Any) -> Evaluated:
    """One selection through the ten filters: ``w`` is the world, the keywords describe the candidate's row."""
    r = row(**kw)
    return evaluate(w or world(odds=float(r["best_odds"] or 2.10)), key_of(int(r["fixture_id"]), r["line"]), {MODEL: r})


def effect(e: Evaluated, n: int) -> str | None:
    """The state the filter number ``n`` imposed when it failed (None if it did not fail)."""
    return next((f.get("effect") for f in e.filters if f["n"] == n), None)


# ── the base case ─────────────────────────────────────────────────────────────

def test_the_base_case_is_a_premium_pick_and_its_score_is_above_the_premium_threshold() -> None:
    e = run()
    assert e.score is not None and e.score.total >= decision.PREMIUM_SCORE, e.score
    assert e.state == "PICK_PREMIUM" and e.premium and e.reasons == []


# ── filter 1: data ────────────────────────────────────────────────────────────

def test_a_forecast_is_too_old_after_the_documented_age() -> None:
    limit = decision.FORECAST_MAX_AGE
    fresh = run(forecast_age=limit - timedelta(hours=1))
    assert "data" not in fresh.reasons and fresh.state != "RECHAZADO"
    old = run(forecast_age=limit + timedelta(hours=1))
    assert old.state == "RECHAZADO" and "data" in old.reasons and effect(old, 1) == "RECHAZADO"


def test_a_match_that_cannot_be_played_or_is_too_close_is_rejected_for_its_data() -> None:
    assert "data" not in run(minutes=decision.MIN_MINUTES + 1).reasons
    for kw in ({"minutes": decision.MIN_MINUTES - 1}, {"status": "PST", "group": "postponed"}):
        e = run(**kw)
        assert e.state == "RECHAZADO" and "data" in e.reasons, kw
    for unfit in sorted(decision.NOT_FIT):
        e = run(world(data_class=unfit))
        assert e.state == "RECHAZADO" and "data" in e.reasons, unfit
    assert run(world(quarantined=True)).state == "RECHAZADO"


# ── filter 3: market ──────────────────────────────────────────────────────────

def test_the_market_filter_rejects_no_price_a_thin_market_and_an_outlier_but_only_investigates_a_stale_price() -> None:
    none = run(odds=None, p_fair=None)
    assert none.state == "RECHAZADO" and "no_price" in none.reasons and effect(none, 3) == "RECHAZADO"
    thin = run(books=decision.MIN_BOOKS - 1)
    assert thin.state == "RECHAZADO" and "thin_market" in thin.reasons
    dear = (1 + decision.MAX_PRICE_EDGE) / 2.10 + 0.02  # odds x p_fair - 1 above the cap
    outlier = run(p_fair=dear)
    assert outlier.state == "RECHAZADO" and "price_outlier" in outlier.reasons
    stale = run(price_age=decision.MAX_PRICE_AGE + timedelta(minutes=30))
    assert stale.state == "INVESTIGACION" and "price_stale" in stale.reasons and effect(stale, 3) == "INVESTIGACION"
    within = run(price_age=decision.MAX_PRICE_AGE - timedelta(minutes=30))
    assert "price_stale" not in within.reasons


# ── filters 4, 5, 7 ───────────────────────────────────────────────────────────

def test_without_a_champion_calibrator_the_selection_is_only_investigated() -> None:
    e = run(world(calibrated=False))
    assert e.state == "INVESTIGACION" and "not_calibrated" in e.reasons and effect(e, 4) == "INVESTIGACION"


def test_a_calibrated_ev_below_the_minimum_is_rejected() -> None:
    e = run(odds=2.10, p_model=0.47, p_fair=0.46)  # 0.47 x 2.10 - 1 < 0
    assert e.state == "RECHAZADO" and "ev_cal_below" in e.reasons and effect(e, 5) == "RECHAZADO"
    just_enough = run(odds=2.10, p_model=(1 + decision.EV_MIN) / 2.10 + 0.002, p_fair=0.46)
    assert "ev_cal_below" not in just_enough.reasons


def test_a_risky_selection_is_a_caution_not_a_rejection() -> None:
    cases: list[dict[str, Any]] = [{"odds": decision.RISK_MAX_ODDS + 0.4, "p_model": 0.55, "p_fair": 0.30},
                                   {"width": decision.RISK_MAX_WIDTH + 0.05}]
    for kw in cases:
        e = run(**kw)
        assert e.state == "CAUTELA" and "risk" in e.reasons and effect(e, 7) == "CAUTELA", (kw, e.reasons)


# ── filter 6: context ─────────────────────────────────────────────────────────

def test_context_that_prevents_the_match_rejects_and_the_ais_doubt_is_a_caution() -> None:
    stop = run(world(rules={"fixture_not_playable": "hard"}))
    assert stop.state == "RECHAZADO" and "context_stop" in stop.reasons and effect(stop, 6) == "RECHAZADO"
    for verdict in ("REJECT", "DOWNGRADE"):
        e = run(world(review=verdict))
        assert e.state == "CAUTELA" and f"ai_{verdict.lower()}" in e.reasons and effect(e, 6) == "CAUTELA"


def test_a_key_absence_is_a_caution_while_reported_and_a_rejection_once_the_lineups_confirm_it() -> None:
    reported = run(world(rules={"key_absences_pick_side": "hard"}))
    assert reported.state == "CAUTELA" and "key_absence_reported" in reported.reasons
    confirmed = run(world(rules={"key_absences_pick_side": "hard"}, lineups=True))
    assert confirmed.state == "RECHAZADO" and "key_absence_confirmed" in confirmed.reasons
    assert effect(confirmed, 6) == "RECHAZADO"


def test_a_match_without_context_is_penalised_in_the_score_not_rejected() -> None:
    e = run()
    assert e.context.status == "PENDING" and effect(e, 6) is None and e.state != "RECHAZADO"


# ── filter 8: one selection per match ────────────────────────────────────────

def correlated() -> Evaluated:
    """Two approved selections of ONE match (the second with a thinner market, so a lower score): the one correlate()
    demotes."""
    w = world(rule_clv=-0.01)
    best = evaluate(w, key_of(1), {MODEL: row()})
    other = evaluate(w, key_of(1, Decimal("1.5")), {MODEL: row(books=4, line=Decimal("1.5"))})
    assert best.score is not None and other.score is not None and best.score.total > other.score.total
    assert best.state in decision.APPROVED and other.state in decision.APPROVED
    decision.correlate([best, other])
    assert best.state in decision.APPROVED, "the best scored one stays"
    return other


def test_only_the_best_scored_selection_of_a_match_stays_approved() -> None:
    other = correlated()
    assert other.state == "CAUTELA" and "correlated_same_match" in other.reasons and effect(other, 8) == "CAUTELA"
    assert other.stake.units <= 0.25 and not other.premium and not other.parlay_eligible


# ── filter 9: the price at the end ───────────────────────────────────────────

def test_a_price_not_fresh_at_the_final_checkpoints_is_a_caution_not_a_rejection() -> None:
    for minutes, checkpoint, w in ((80, "T-90m", world()), (55, "T-60m", world()), (95, "lineups", world(lineups=True)),
                                   (12, "T-15m", world(approved_before=True))):
        e = run(w, minutes=minutes, price_age=STALE)
        assert e.checkpoint == checkpoint and checkpoint in decision.FINAL_CHECKPOINTS, (minutes, e.checkpoint)
        assert e.state == "CAUTELA" and "price_not_fresh" in e.reasons and effect(e, 9) == "CAUTELA", checkpoint
    early = run(minutes=360, price_age=STALE)
    assert early.checkpoint == "T-6h" and "price_not_fresh" not in early.reasons, "T-6h: a 45-minute price is fine"
    fresh = run(minutes=80, price_age=decision.FINAL_FRESH - timedelta(minutes=5))
    assert "price_not_fresh" not in fresh.reasons and fresh.state != "CAUTELA"


# ── filter 10: PREMIUM and the parlay candidate ──────────────────────────────

def test_a_premium_pick_needs_the_score_the_walk_forward_clv_and_the_clv_of_its_type() -> None:
    assert run().state == "PICK_PREMIUM"
    for name, w in (("walk-forward CLV of the rule not positive", world(rule_clv=-0.01)),
                    ("no walk-forward CLV", world(rule_clv=None)),
                    ("CLV of the type not positive", world(type_clv=(-0.01, 80))),
                    ("no CLV of the type", world(type_clv=None))):
        e = run(w)
        assert not e.premium and e.state in decision.APPROVED and e.state != "PICK_PREMIUM", name
    weak = run(books=3, overround=0.09, price_age=timedelta(minutes=25), width=0.20)  # the other two conditions hold
    assert weak.score is not None and weak.score.total < decision.PREMIUM_SCORE, weak.score
    assert weak.state in decision.APPROVED and not weak.premium and weak.state != "PICK_PREMIUM"


def candidate(odds: float, p: float) -> Evaluated:
    """An approved selection that is not PREMIUM, at ``odds`` with calibrated probability ``p`` and a market price that
    is neither dear nor an outlier."""
    return run(world(rule_clv=-0.01, odds=odds), odds=odds, p_model=p, p_fair=min(p - 0.05, 1.2 / odds))


def test_a_parlay_candidate_is_an_approved_selection_inside_the_documented_odds_and_probability() -> None:
    lo, hi = decision.PARLAY_ODDS
    inside = candidate(2.10, 0.62)
    assert inside.state == "CANDIDATO_PARLAY" and inside.parlay_eligible and not inside.premium
    assert candidate(hi, 0.62).state == "CANDIDATO_PARLAY", "the upper bound is inclusive"
    assert candidate(round(hi + 0.10, 2), 0.62).state == "APROBADO", "above the range"
    assert candidate(lo, 0.85).state == "CANDIDATO_PARLAY", "the lower bound is inclusive"
    assert candidate(round(lo - 0.01, 2), 0.90).state == "APROBADO", "below the range"
    assert candidate(2.10, decision.PARLAY_MIN_P).state == "CANDIDATO_PARLAY", "the probability bound is inclusive"
    below_p = candidate(2.20, decision.PARLAY_MIN_P - 0.02)
    assert below_p.state == "APROBADO" and not below_p.parlay_eligible


def test_nothing_is_approved_while_the_markets_edge_is_not_validated() -> None:
    e = run(world(edge=False))
    assert e.state == "INVESTIGACION" and "edge_not_validated" in e.reasons and not e.premium


# ── every failing filter, by the state it imposes ────────────────────────────

SCENARIOS: dict[int, list[Callable[[], Evaluated]]] = {
    1: [lambda: run(forecast_age=decision.FORECAST_MAX_AGE + timedelta(hours=1))],
    2: [lambda: run(p_model=1.2)],
    3: [lambda: run(odds=None, p_fair=None), lambda: run(books=decision.MIN_BOOKS - 1),
        lambda: run(price_age=decision.MAX_PRICE_AGE + timedelta(minutes=30))],
    4: [lambda: run(world(calibrated=False))],
    5: [lambda: run(odds=2.10, p_model=0.47, p_fair=0.46)],
    6: [lambda: run(world(rules={"fixture_not_playable": "hard"})), lambda: run(world(review="REJECT")),
        lambda: run(world(rules={"key_absences_pick_side": "hard"}, lineups=True))],
    7: [lambda: run(width=decision.RISK_MAX_WIDTH + 0.05)],
    8: [correlated],
    9: [lambda: run(minutes=80, price_age=STALE)],
}


def effects_of_failing(n: int) -> set[str]:
    """The states filter ``n`` imposes across the scenarios in which it fails: the code's side of the document's
    "Falla ->" column."""
    return {str(f["effect"]) for build in SCENARIOS[n] for f in build().filters if f["n"] == n and f.get("effect")}


def test_every_scenario_fails_the_filter_it_is_filed_under() -> None:
    for n, builds in SCENARIOS.items():
        for build in builds:
            e = build()
            assert any(f["n"] == n and f.get("ok") is False for f in e.filters), (n, e.reasons)

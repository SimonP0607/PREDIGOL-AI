"""decision-v2 (``fbi.decision.engine``): the shared stages, one by one, and against decision-v1 and decision-fam-v1 themselves.

The worlds are built in memory (as in tests/unit/test_intel_state_v2.py) and the reference is ``fbi.intel.decision.evaluate`` /
``correlate`` and ``fbi.familydecisions.decide.finalise`` run on the same world: decision-v2 is held to what the layers it replaces really
do, read through state-v2, not to a copy of them."""

from __future__ import annotations

import ast
import itertools
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.decision import engine
from fbi.decision.engine import RANK, MarketRisk
from fbi.decision.families import CAP_CODE, CORE, FORECAST_FAMILIES, Candidate, ForecastFamily
from fbi.familydecisions import decide as fd
from fbi.intel import context_adjustment as ctx
from fbi.intel import decision, state_v2
from fbi.intel.calibration import CalibrationState, Calibrator

AT = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
KEY: decision.Key = (77, "1X2", "Home", Decimal("0.00"))
MODEL = "dixon_coles"


def world(*, champion: bool = True, best: bool = False, edge: bool = True, market: str = "1X2", model: str = MODEL,
          quality: dict[str, Any] | None = None, rules: list[dict[str, str]] | None = None, review: str | None = None,
          lineups: bool = False, previous: str | None = None, type_clv: float | None = None, rule_clv: float = 0.01) -> decision.World:
    cal = Calibrator(market, model, "identity", {}, id=5, role="CHAMPION" if champion else "CHALLENGER")
    slot = (market, model)
    reviews = {} if review is None else {(77, market, KEY[2], KEY[3]): {"id": 9, "decision": review, "confidence": 0.7, "engine_version": "x",
                                                                        "reviewed_at": AT, "output": {"reason": "porque"}}}
    rule_rows = {} if rules is None else {(77, market, KEY[2], KEY[3]): {"output": {"negative_evidence": rules}}}
    return decision.World(
        at=AT, cal=CalibrationState(champions={slot: cal} if champion else {}, best={slot: cal} if (best or champion) else {},
                                    wf={slot: {"ece_cal": 0.02, "rule_clv": rule_clv, "logloss_cal": 0.6}}, edge={slot: edge}),
        quality={77: quality or {"data_class": "MODEL_READY", "quarantined": False}}, reviews=reviews, rules=rule_rows, evidence={},
        passes={}, lineups={77: AT - timedelta(minutes=5)} if lineups else {},
        type_clv={} if type_clv is None else {(market, KEY[2], b): (type_clv, 80) for b in "abcd"},
        previous={} if previous is None else {KEY: {"state": previous}}, ai_mode="shadow")


def pick(*, odds: float = 2.0, p: float = 0.56, p_fair: float = 0.48, price_age: timedelta = timedelta(minutes=20), books: int = 6,
         kickoff: timedelta = timedelta(hours=5), width: float | None = 0.10, status: str = "NS", forecast_age: timedelta = timedelta(hours=2),
         market: str = "1X2", selection: str = "Home") -> dict[str, Any]:
    return {"pick_id": 1, "fixture_id": 77, "market_key": market, "selection": selection, "line": Decimal("0"), "model_name": MODEL,
            "model_version_id": 3, "p_model": p, "p_push": 0.0, "p_low": None if width is None else p - width / 2,
            "p_high": None if width is None else p + width / 2, "kickoff_at": AT + kickoff, "status_short": status,
            "status_group": "scheduled" if status == "NS" else "finished", "data_cutoff_ts": AT - forecast_age, "best_odds": odds,
            "p_fair": p_fair, "best_bookmaker_id": 8, "n_bookmakers": books, "overround": 0.05, "dispersion": 0.01, "price_at": AT - price_age}


def core(models: dict[str, dict[str, Any]], key: decision.Key = KEY) -> Candidate:
    return Candidate(CORE, key, models)


def v1(w: decision.World, models: dict[str, dict[str, Any]], key: decision.Key = KEY) -> tuple[decision.Evaluated, dict[str, Any]]:
    e = decision.evaluate(w, key, models)
    decision.correlate([e])
    return e, as_row(e)


def as_row(e: decision.Evaluated) -> dict[str, Any]:
    """A row of ``intel.decisions`` with the fields state-v2 reads, as ``decision.store`` writes them."""
    return {"id": 1, "state": e.state, "reasons": list(e.reasons), "filters": e.filters, "checkpoint": e.checkpoint, "fixture_id": e.key[0],
            "market_key": e.key[1], "selection": e.key[2], "line": e.key[3]}


def v2_view(d: engine.Decision2) -> tuple[str, set[str], str, str | None]:
    return d.state, set(d.codes), d.checkpoint, d.label


CONTEXT_CODES = frozenset({"key_absence_reported", "ai_reject", "ai_downgrade"})
"""decision-v1's context codes whose effect is CAUTELA."""


def v1_view(e: decision.Evaluated, row: dict[str, Any], w: decision.World) -> tuple[str, set[str], str, str | None]:
    """What decision-v2 must say, read off decision-v1: its state through state-v2, its reasons, its checkpoint, its label - and the one
    place decision-v2 is stricter by design: a CAUTELA that only the context gave, on a market whose edge is not validated, is the
    context lifting an INVESTIGACION (decision-v1 gates only an APROBADO); decision-v2 keeps it ABSTAIN with the edge gate's code."""
    state, _ = state_v2.classify(row)
    codes = {r for r in e.reasons if r not in {fd.REASON_RESEARCH}}
    edge = bool(w.cal.edge.get((e.key[1], e.row["model_used"])))
    if state == "CAUTION" and codes and codes <= CONTEXT_CODES and not edge:
        return "ABSTAIN", codes | {"edge_not_validated"}, e.checkpoint, None
    return state, codes, e.checkpoint, state_v2.label_of(row)


# -- the whole engine against decision-v1 -------------------------------------------------------------------------------------------------

FACTORS: dict[str, tuple[Any, ...]] = {
    "champion": (True, False), "best": (False, True), "edge": (True, False), "odds": (2.0, 1.5, 2.6, 3.4), "p": (0.56, 0.25, 0.45, 0.7),
    "p_fair": (0.48, 0.3, 0.6), "price_age": (timedelta(minutes=10), timedelta(minutes=45), timedelta(hours=4)), "books": (6, 2, 3),
    "kickoff": (timedelta(hours=5), timedelta(minutes=5), timedelta(minutes=50), timedelta(minutes=80), timedelta(hours=30)),
    "width": (0.1, None, 0.3), "status": ("NS", "PST"), "forecast_age": (timedelta(hours=2), timedelta(hours=80)),
    "data_class": ("MODEL_READY", "PRODUCT_ONLY", None), "quarantined": (False, True),
    "rules": (None, [{"code": "key_absences_pick_side", "severity": "hard"}], [{"code": "fixture_not_playable", "severity": "hard"}],
              [{"code": "something", "severity": "soft"}]),
    "review": (None, "APPROVE", "REJECT", "DOWNGRADE"), "lineups": (False, True), "previous": (None, "APROBADO", "RECHAZADO"),
    "type_clv": (None, 0.02, -0.01), "rule_clv": (0.01, -0.01)}
"""Each factor's first value is the one a good selection has."""


def cases(n: int, seed: int = 20261106, keep: float = 0.85) -> list[dict[str, Any]]:
    """``n`` selections: each factor keeps its good value with probability ``keep``, otherwise any of its values."""
    rng = random.Random(seed)
    return [{k: v[0] if rng.random() < keep else rng.choice(v) for k, v in FACTORS.items()} for _ in range(n)]


def build(c: dict[str, Any]) -> tuple[decision.World, dict[str, Any]]:
    w = world(champion=c["champion"], best=c["best"], edge=c["edge"], quality={"data_class": c["data_class"], "quarantined": c["quarantined"]},
              rules=c["rules"], review=c["review"], lineups=c["lineups"], previous=c["previous"], type_clv=c["type_clv"], rule_clv=c["rule_clv"])
    return w, pick(odds=c["odds"], p=c["p"], p_fair=c["p_fair"], price_age=c["price_age"], books=c["books"], kickoff=c["kickoff"],
                   width=c["width"], status=c["status"], forecast_age=c["forecast_age"])


def test_decision_v2_agrees_with_decision_v1_on_two_thousand_selections_state_reasons_checkpoint_and_label() -> None:
    seen: set[str] = set()
    for c in cases(2000):
        w, p = build(c)
        e, row = v1(w, {MODEL: p})
        d = engine.decide(w, core({MODEL: p}))
        got, want = v2_view(d), v1_view(e, row, w)
        # decision-v2 also records the edge gate behind a context that rejected or held the selection (decision-v1 stops before it)
        assert (got[0], got[1] - {"edge_not_validated"}, *got[2:]) == (want[0], want[1] - {"edge_not_validated"}, *want[2:]), c
        assert ("edge_not_validated" in want[1]) <= ("edge_not_validated" in got[1]), c
        assert got[1] - want[1] <= {"edge_not_validated"} and (got[1] == want[1] or set(e.reasons) & (CONTEXT_CODES | {"context_stop",
                                                                                                                   "key_absence_confirmed"})), c
        seen.add(d.state)
    assert seen == set(state_v2.STATES), "the grid reaches every state"


def test_a_good_selection_is_recommended_with_its_label_and_every_stage_recorded() -> None:
    w, p = world(), pick()
    d = engine.decide(w, core({MODEL: p}))
    assert (d.state, d.reason, d.codes, d.label) == ("RECOMMENDED", "approved", (), "CANDIDATO_PARLAY")
    assert [v.stage for v in d.verdicts] == list(engine.STAGES) and [v.n for v in d.verdicts] == list(range(1, 11))
    assert all(v.ok in (True, None) for v in d.verdicts)
    assert d.prediction.p_cal == pytest.approx(0.56) and d.value.ev_cal == pytest.approx(0.12) and d.price.odds == 2.0
    assert d.as_json()["stages"][0] == {"n": 1, "stage": "data", "ok": True, "why": "datos MODEL_READY", "data": {"forecast_age_checked": True}}


# -- stage by stage -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("stage", "w", "p", "code", "state"), [
    ("data", world(), pick(status="PST"), "data", "REJECTED"),
    ("data", world(), pick(kickoff=timedelta(minutes=5)), "data", "REJECTED"),
    ("data", world(quality={"data_class": "INSUFFICIENT"}), pick(), "data", "REJECTED"),
    ("data", world(quality={"quarantined": True}), pick(), "data", "REJECTED"),
    ("data", world(), pick(forecast_age=timedelta(hours=73)), "data", "REJECTED"),
    ("model", world(), pick(width=None), "model", "REJECTED"),
    ("model", world(), pick(p=1.0), "model", "REJECTED"),
    ("market", world(), pick(books=2), "thin_market", "REJECTED"),
    ("market", world(), pick(odds=2.8, p_fair=0.48), "price_outlier", "REJECTED"),
    ("market", world(), pick(price_age=timedelta(hours=4)), "price_stale", "WATCH"),
    ("calibration", world(champion=False, best=True), pick(), "not_calibrated", "ABSTAIN"),
    ("value", world(champion=False), pick(), "ev_unknown", "ABSTAIN"),
    ("value", world(), pick(p=0.49), "ev_cal_below", "REJECTED"),
    ("context", world(rules=[{"code": "fixture_quarantined", "severity": "hard"}]), pick(), "context_stop", "REJECTED"),
    ("context", world(rules=[{"code": "key_absences_pick_side", "severity": "hard"}], lineups=True), pick(), "key_absence_confirmed", "REJECTED"),
    ("context", world(rules=[{"code": "key_absences_pick_side", "severity": "hard"}]), pick(), "key_absence_reported", "CAUTION"),
    ("context", world(review="DOWNGRADE"), pick(), "ai_downgrade", "CAUTION"),
    ("risk", world(), pick(odds=3.2, p=0.4, p_fair=0.3), "risk", "CAUTION"),
    ("risk", world(), pick(width=0.3), "risk", "CAUTION"),
    ("price", world(), pick(kickoff=timedelta(minutes=80), price_age=timedelta(minutes=45)), "price_not_fresh", "CAUTION"),
    ("final", world(edge=False), pick(), "edge_not_validated", "ABSTAIN"),
])
def test_each_stage_records_its_verdict_its_code_and_its_effect(stage: str, w: decision.World, p: dict[str, Any], code: str, state: str) -> None:
    d = engine.decide(w, core({MODEL: p}))
    v = d.verdict(stage)
    assert v.ok is False and (code, state) in v.effects, v
    assert d.state == state or RANK[d.state] < RANK[state]  # type: ignore[index]
    assert engine.CODE_STAGE[code] == stage and engine.CODE_STATE[code] == state


def test_a_negative_context_does_not_lift_a_selection_past_the_edge_gate() -> None:
    """decision-v1: no validated edge -> INVESTIGACION, but the same with a review DOWNGRADE -> CAUTELA (the context raised it). decision-v2:
    ABSTAIN both times."""
    w0, w1, p = world(edge=False), world(edge=False, review="DOWNGRADE"), pick()
    assert [state_v2.classify(v1(w, {MODEL: p})[1])[0] for w in (w0, w1)] == ["ABSTAIN", "CAUTION"]
    d0, d1 = (engine.decide(w, core({MODEL: p})) for w in (w0, w1))
    assert (d0.state, d1.state) == ("ABSTAIN", "ABSTAIN") and {"ai_downgrade", "edge_not_validated"} <= set(d1.codes)
    assert d1.reason == "edge_not_validated" and d1.verdict("final").ok is False


def test_a_caution_stays_a_caution_without_a_validated_edge_as_in_decision_v1() -> None:
    w, p = world(edge=False), pick(width=0.3)
    d = engine.decide(w, core({MODEL: p}))
    _, row = v1(w, {MODEL: p})
    assert d.state == "CAUTION" == state_v2.classify(row)[0] and "edge_not_validated" not in d.codes
    assert d.verdict("final").ok is True, "the edge gate only stands between a selection and RECOMMENDED"


def test_a_structural_lack_wins_over_a_wait() -> None:
    d = engine.decide(world(champion=False, best=True), core({MODEL: pick(price_age=timedelta(hours=4))}))
    assert d.state == "ABSTAIN" and d.reason == "not_calibrated" and {"price_stale", "not_calibrated"} <= set(d.codes)


def test_the_specialised_model_decides_and_the_others_only_vote() -> None:
    w = world()
    other = pick(p=0.4) | {"model_name": "elo"}
    d = engine.decide(w, core({MODEL: pick(), "elo": other}))
    e, _ = v1(w, {MODEL: pick(), "elo": other})
    assert d.prediction.model == MODEL == e.row["model_used"]
    assert d.score == pytest.approx(e.score.total if e.score else None)


# -- correlation (8) ---------------------------------------------------------------------------------------------------------------------

def two_markets() -> decision.World:
    """A world with a champion and a validated edge for 1X2 and for OU."""
    w = world()
    return replace(w, cal=CalibrationState(
        champions={**w.cal.champions, ("OU", MODEL): Calibrator("OU", MODEL, "identity", {}, id=6, role="CHAMPION")},
        best=w.cal.best, wf={**w.cal.wf, ("OU", MODEL): {"ece_cal": 0.02, "rule_clv": 0.01}}, edge={**w.cal.edge, ("OU", MODEL): True}))


def test_one_recommended_per_match_the_best_score_stays_like_decision_v1() -> None:
    k2: decision.Key = (77, "OU", "Over", Decimal("2.50"))
    w = two_markets()
    a, b = pick(), pick(odds=2.1, p=0.6, p_fair=0.47, market="OU", selection="Over") | {"line": Decimal("2.5")}
    e1, e2 = decision.evaluate(w, KEY, {MODEL: a}), decision.evaluate(w, k2, {MODEL: b})
    decision.correlate([e1, e2])
    out = engine.decide_all(w, [core({MODEL: a}), core({MODEL: b}, k2)])
    assert [d.state for d in out] == [state_v2.classify(as_row(e))[0] for e in (e1, e2)]
    loser = next(d for d in out if d.state == "CAUTION")
    assert loser.reason == "correlated_same_match" and loser.label is None and loser.verdict("correlation").ok is False
    winner = next(d for d in out if d.state == "RECOMMENDED")
    assert winner.verdict("correlation").ok is True and (winner.score or 0) >= (loser.score or 0)
    assert [d.key for d in engine.decide_all(w, [core({MODEL: b}, k2), core({MODEL: a})])] == [k2, KEY], "in the order given"
    assert {d.key: d.state for d in engine.decide_all(w, [core({MODEL: b}, k2), core({MODEL: a})])} == {d.key: d.state for d in out}


def test_alone_a_candidate_passes_correlation_and_a_family_that_does_not_correlate_records_none() -> None:
    assert engine.decide(world(), core({MODEL: pick()})).verdict("correlation").ok is True
    fam = forecast_candidate()
    assert engine.decide(fam_world(), fam).verdict("correlation").ok is None


# -- context: the Council only as a typed adjustment, and it never raises ----------------------------------------------------------------

def adjustment(verdict: ctx.AdjVerdict) -> ctx.ContextAdjustment:
    severity: ctx.Severity = "bloqueante" if verdict == "BLOQUEA" else "media" if verdict in ("RESERVA", "FALTA_INFO") else "baja"
    return ctx.ContextAdjustment(verdict, severity, ctx.Source(engine="ma-v1"), AT)


def test_the_councils_verdict_maps_to_state_v2_as_the_contract_says() -> None:
    assert engine.ADJ_EFFECT == {"BLOQUEA": "REJECTED", "RESERVA": "CAUTION", "FALTA_INFO": "WATCH", "CONFIRMA": None, "SIN_COUNCIL": None}
    assert set(engine.ADJ_EFFECT) == set(ctx.VERDICTS)


@pytest.mark.parametrize("verdict", ctx.VERDICTS)
def test_context_never_raises_a_state_whatever_the_other_stages_said(verdict: ctx.AdjVerdict) -> None:
    """The property, over a grid of worlds and candidates: with the Council's adjustment the state is never above the state without it, the
    prediction, the price and the value are the same objects, and only the context stage differs."""
    for c in cases(400, seed=ctx.VERDICTS.index(verdict)):
        w, p = build(c)
        base = engine.decide(w, core({MODEL: p}))
        with_adj = engine.decide(w, core({MODEL: p}), adjustment=adjustment(verdict))
        assert RANK[with_adj.state] <= RANK[base.state], (verdict, c)
        target = engine.ADJ_EFFECT[verdict]
        if target is not None:
            assert RANK[with_adj.state] <= RANK[target]
        assert (with_adj.prediction, with_adj.price, with_adj.value) == (base.prediction, base.price, base.value)
        assert [v for v in with_adj.verdicts if v.stage != "context"] == [v for v in base.verdicts if v.stage != "context"] or \
            with_adj.state != base.state, "only the context stage (and what follows from it) moves"
        assert with_adj.adjustment == verdict


@pytest.mark.parametrize("extra", [{"review": "REJECT"}, {"review": "DOWNGRADE"},
                                   {"rules": [{"code": "key_absences_pick_side", "severity": "hard"}]},
                                   {"rules": [{"code": "key_absences_pick_side", "severity": "hard"}], "lineups": True},
                                   {"rules": [{"code": "fixture_not_playable", "severity": "hard"}]}])
def test_the_context_decision_v1_reads_never_raises_a_state_either(extra: dict[str, Any]) -> None:
    for c in cases(400, seed=7):
        quiet = c | {"review": None, "rules": None, "lineups": extra.get("lineups", c["lineups"])}
        w0, p = build(quiet)
        w1, _ = build(quiet | extra)
        assert RANK[engine.decide(w1, core({MODEL: p})).state] <= RANK[engine.decide(w0, core({MODEL: p})).state], (extra, c)


def test_a_council_that_holds_one_selection_back_never_lifts_another_of_its_match() -> None:
    k2: decision.Key = (77, "OU", "Over", Decimal("2.50"))
    w = two_markets()
    a, b = pick(), pick(odds=2.1, p=0.6, p_fair=0.47, market="OU", selection="Over") | {"line": Decimal("2.5")}
    cands = [core({MODEL: a}), core({MODEL: b}, k2)]
    base = {d.key: d.state for d in engine.decide_all(w, cands)}
    assert sorted(base.values()) == ["CAUTION", "RECOMMENDED"]
    for verdict in ctx.VERDICTS:
        for key in (KEY, k2):
            held = {d.key: d.state for d in engine.decide_all(w, cands, adjustments={key: adjustment(verdict)})}
            assert all(RANK[held[k]] <= RANK[base[k]] for k in base), (verdict, key, held)


def test_a_confirmation_does_not_promote() -> None:
    w, p = world(edge=False), pick()
    assert engine.decide(w, core({MODEL: p}), adjustment=adjustment("CONFIRMA")).state == "ABSTAIN"


def test_a_blocking_council_rejects_and_says_so_in_the_context_stage() -> None:
    d = engine.decide(world(), core({MODEL: pick()}), adjustment=adjustment("BLOQUEA"))
    assert d.state == "REJECTED" and d.reason == "council_bloquea" and d.verdict("context").effects == (("council_bloquea", "REJECTED"),)


# -- risk: the market's signals are risk inputs, never a probability --------------------------------------------------------------------

def test_steam_against_the_model_is_a_caution_and_touches_no_number() -> None:
    w, p = world(), pick()
    base = engine.decide(w, core({MODEL: p}))
    against = engine.decide(w, core({MODEL: p}), market=MarketRisk("ok", "against", True, -4.0, False))
    assert against.state == "CAUTION" and against.reason == engine.MARKET_STEAM_AGAINST
    assert (against.prediction, against.price, against.value) == (base.prediction, base.price, base.value)
    for quiet in (MarketRisk("ok", "against", False, -1.0, False), MarketRisk("ok", "toward", True, 4.0, False),
                  MarketRisk("no_prices", None, False, None, None)):
        assert engine.decide(w, core({MODEL: p}), market=quiet).state == "RECOMMENDED"


# -- the families of F10, against decision-fam-v1 ----------------------------------------------------------------------------------------

FIXTURE = {"kickoff_at": AT + timedelta(hours=20), "status_short": "NS", "status_group": "scheduled", "home_team_id": 1, "away_team_id": 2,
           "competition_season_id": 1, "competition_id": 1, "competition_name": "League", "home_name": "A", "away_name": "B"}


def forecast_candidate(*, family: ForecastFamily = FORECAST_FAMILIES[1], p: float = 0.56, odds: float = 2.0, p_fair: float = 0.48,
                       books: int = 3, price_age: timedelta = timedelta(minutes=30), lo: float | None = None, hi: float | None = None,
                       status: str = "NS", kickoff: timedelta = timedelta(hours=20)) -> Candidate:
    key = {"CORNERS": "CORNERS_OU", "CARDS": "CARDS_OU", "YELLOW": "YELLOW_OU", "GOALS_HALF": "OU_1H"}[family.name]
    f = fd.Forecast(100, 77, family.name, f"family-{family.name.lower()}", 7, key, Decimal("9.5"), "Over", p, p, lo, hi, "UNCALIBRATED",
                    AT - timedelta(hours=5), AT - timedelta(hours=100),
                    {**FIXTURE, "kickoff_at": AT + kickoff, "status_short": status, "status_group": "scheduled" if status == "NS" else "x"})
    priced = fd.Priced(p_fair, odds, 8, books, 1.05, AT - timedelta(hours=1))
    return family.from_found(fd.Candidate(f, priced, AT - price_age, odds * p - 1))


def fam_world(**kw: Any) -> decision.World:
    return world(champion=False, **kw)


def test_a_family_agrees_with_decision_fam_v1_over_a_grid() -> None:
    rng = random.Random(11)
    grid = list(itertools.product(FORECAST_FAMILIES, (0.3, 0.56, 0.7), (1.6, 2.0, 3.4), (0.3, 0.48), (2, 3, 6),
                                  (timedelta(minutes=30), timedelta(hours=4)), ((None, None), (0.4, 0.8)), ("NS", "PST"),
                                  (timedelta(minutes=5), timedelta(hours=20)), (False, True)))
    for fam, p, odds, p_fair, books, age, (lo, hi), status, kickoff, champion in rng.sample(grid, 600):
        c = forecast_candidate(family=fam, p=p, odds=odds, p_fair=p_fair, books=books, price_age=age, lo=lo, hi=hi, status=status, kickoff=kickoff)
        [(model, r)] = c.models.items()
        w = world(champion=champion, market=c.key[1], model=model)
        e = decision.evaluate(w, c.key, {model: dict(r)})
        found = fd.Candidate(fd.Forecast(100, 77, fam.name, model, 7, c.key[1], c.key[3], c.key[2], p, p, lo, hi, "UNCALIBRATED", AT, AT,
                                         FIXTURE), fd.Priced(p_fair, odds, 8, books, 1.05, AT), AT - age, odds * p - 1)
        e = fd.finalise(e, found, fam.spec)
        d = engine.decide(w, c)
        row = as_row(e)
        expected = state_v2.classify(row)[0]
        if expected == "WATCH":  # decision-fam-v1 leaves a stale price parked; a family in shadow is not something to wait for
            expected = "ABSTAIN"
            assert CAP_CODE in d.codes and CAP_CODE not in e.reasons
        assert d.state == expected, (fam.name, p, odds, p_fair, books, age, lo, hi, status, kickoff, champion, d.codes, e.reasons)
        assert d.state in ("REJECTED", "ABSTAIN"), "a family in shadow is never more than ABSTAIN"
        assert set(d.codes) - {CAP_CODE} == {x for x in e.reasons if x not in (fd.REASON_RESEARCH, fd.REASON_CAPPED)}


def test_a_family_without_an_interval_passes_the_model_stage_and_its_old_forecast_is_not_an_old_pick() -> None:
    d = engine.decide(fam_world(market="CORNERS_OU", model="family-corners"), forecast_candidate())
    assert d.verdict("model").ok is True and "no se juzga su ancho" in d.verdict("model").why
    assert d.verdict("data").ok is True and d.verdict("data").data == {"forecast_age_checked": False}
    assert d.state == "ABSTAIN" and d.reason == "not_calibrated"


def test_a_family_that_would_be_recommended_is_held_at_abstain_by_the_cap() -> None:
    w = world(market="CORNERS_OU", model="family-corners")
    d = engine.decide(w, forecast_candidate())
    assert d.state == "ABSTAIN" and d.reason == CAP_CODE and d.label is None
    assert d.verdict("final").effects == ((CAP_CODE, "ABSTAIN"),)


# -- the tables ---------------------------------------------------------------------------------------------------------------------------

def test_the_effects_are_state_v2s_reading_of_decision_v1s_codes() -> None:
    assert set(state_v2.REASON_EFFECT) <= set(engine.CODE_STATE) and set(engine.CODE_STATE) == set(engine.CODE_STAGE)
    for code, v1_state in state_v2.REASON_EFFECT.items():
        v2 = engine.CODE_STATE[code]
        if v1_state == "INVESTIGACION":
            assert v2 in ("WATCH", "ABSTAIN") and (code, v2) in {(c, k) for c, _, _, k in state_v2.INVESTIGATION_RULES}
        else:
            assert v2 == state_v2.DIRECT[v1_state]
    for code, _, key, _ in state_v2.INVESTIGATION_RULES:
        assert engine.CODE_STAGE[code] == engine.V1_STAGE.get(key, key)


def test_the_order_of_the_states_is_decision_v1s_precedence() -> None:
    assert set(RANK) == set(state_v2.STATES)
    v1_rank = {"REJECTED": decision.RANK["RECHAZADO"], "ABSTAIN": decision.RANK["INVESTIGACION"], "WATCH": decision.RANK["INVESTIGACION"],
               "CAUTION": decision.RANK["CAUTELA"], "RECOMMENDED": decision.RANK["APROBADO"]}
    for a, b in itertools.product(RANK, RANK):
        if v1_rank[a] < v1_rank[b]:
            assert RANK[a] < RANK[b], (a, b)


def test_the_thresholds_are_decision_v1s_imported_not_copied() -> None:
    module = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    tree = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "assess")
    numbers = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, int | float) and not isinstance(n.value, bool)}
    for name in ("EV_MIN", "EDGE_MIN", "RISK_MAX_ODDS", "RISK_MIN_P", "RISK_MAX_WIDTH", "MAX_PRICE_EDGE", "PREMIUM_SCORE", "PARLAY_MIN_P",
                 "MIN_BOOKS", "MIN_MINUTES"):
        assert getattr(decision, name) not in numbers, f"{name} is written as a number in the engine"
    assert decision.PARLAY_ODDS[0] not in numbers and decision.PARLAY_ODDS[1] not in numbers


def test_the_engine_stakes_nothing() -> None:
    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert "stake" not in {a.name.split(".")[-1] for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not any(f.name.startswith("stake") for f in engine.Decision2.__dataclass_fields__.values())

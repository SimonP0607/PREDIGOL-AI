"""PrediGol Intelligence's pure pieces: the logistic fit, the gates, the stake, the score, the checkpoints and the
context, the post-mortem verdicts and causes, the memory's arithmetic and the market discovery's classification."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from fbi.intel import calibration, decision, discovery, memory, postmortem, score, stake, stats


def test_the_logistic_fit_recovers_known_parameters() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(20000, 2))
    w = np.array([-0.4, 0.8, -1.2])
    y = (rng.random(20000) < stats.sigmoid(w[0] + x @ w[1:])).astype(float)
    fit = stats.fit_logistic(x, y, l2=1.0)
    assert fit.converged
    assert np.allclose(fit.w, w, atol=0.06)


def test_scoring_rules() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    p = np.array([0.9, 0.1, 0.8, 0.3])
    assert stats.logloss(y, p) < stats.logloss(y, np.full(4, 0.5))
    assert stats.brier(y, np.array([1.0, 0.0, 1.0, 0.0])) == 0
    assert stats.ece(np.array([1.0, 0.0]), np.array([0.5, 0.5])) == pytest.approx(0.0)


def test_apply_params_and_the_identity() -> None:
    assert calibration.apply_params("identity", {}, 0.6, None) == 0.6
    assert calibration.apply_params("logit2", {"a": 0, "b": 0, "c": 1}, 0.7, 0.4) == pytest.approx(0.4, abs=1e-6)
    assert calibration.apply_params("logit2", {"a": 0, "b": 1, "c": 0}, 0.7, None) is None, "no market, no logit2"
    assert calibration.apply_params("platt", {"a": 0, "b": 1}, 0.25, None) == pytest.approx(0.25, abs=1e-6)


def _wf(**kw: object) -> calibration.WalkForward:
    base: dict[str, object] = {"method": "logit2", "n": 3000, "days": 8, "logloss_cal": 0.640, "logloss_raw": 0.680,
                               "logloss_market": 0.639, "ece_cal": 0.02, "rule_n": 500, "rule_clv": 0.004,
                               "rule_clv_n": 480}
    base.update(kw)
    return calibration.WalkForward(**base)  # type: ignore[arg-type]


def test_the_calibration_gate_and_the_edge_gate() -> None:
    ok = calibration.gate(_wf())
    assert ok.calibrated and ok.edge
    assert not calibration.gate(_wf(n=1000)).calibrated, "too few out-of-sample selections"
    assert not calibration.gate(_wf(days=3)).calibrated
    assert not calibration.gate(_wf(logloss_cal=0.677)).calibrated, "must beat the raw model by 0.005"
    assert not calibration.gate(_wf(ece_cal=0.05)).calibrated
    worse = calibration.gate(_wf(logloss_cal=0.645, logloss_market=0.640))
    assert not worse.calibrated, "worse than the market alone: the model adds nothing"
    no_edge = calibration.gate(_wf(rule_clv=-0.01))
    assert no_edge.calibrated and not no_edge.edge, "calibrated, but the closing line says no edge"
    assert not calibration.gate(_wf(rule_n=100)).edge


def test_kelly_and_the_quarter_stake() -> None:
    assert stake.kelly(0.55, 2.0) == pytest.approx(0.10)
    assert stake.kelly(0.40, 2.0) < 0
    s = stake.stake_for("APROBADO", 0.55, 2.0)
    assert s.units == 1.0 and s.capped, "quarter Kelly 2.5 u, capped at 1 u"
    assert stake.stake_for("PICK_PREMIUM", 0.55, 2.0).units == 1.5
    assert stake.stake_for("CAUTELA", 0.55, 2.0).units == 0.25
    assert stake.stake_for("INVESTIGACION", 0.55, 2.0).units == 0
    assert stake.stake_for("RECHAZADO", 0.9, 3.0).units == 0
    small = stake.stake_for("APROBADO", 0.52, 2.0)  # f* 0.04 -> quarter 1 % -> 1.0 u
    assert small.units == 1.0
    tiny = stake.stake_for("APROBADO", 0.505, 2.0)  # f* 0.01 -> quarter 0.25 %: rounds down to 0.25 u
    assert tiny.units == 0.25
    assert stake.stake_for("APROBADO", 0.45, 2.0).units == 0, "no stake on a negative Kelly"
    push = stake.kelly(0.6, 2.0, p_push=0.2)
    assert push == pytest.approx((0.48 - 0.32) / 1.0)


def test_the_score_is_explained_and_unknowns_score_zero() -> None:
    assert sum(score.WEIGHTS.values()) == 100
    full = score.score(score.ScoreInputs(ev_cal=0.10, edge_cal=0.06, ece=0.005, rule_clv=0.03, data_class="MODEL_READY",
                                         price_age_min=5, n_bookmakers=10, overround=0.03, context_status="FULL",
                                         consensus=1.0, width=0.03, review_decision="APPROVE", type_clv=0.03))
    assert full.total == pytest.approx(100.0)
    empty = score.score(score.ScoreInputs())
    assert empty.total < 15
    assert all("sin dato" in c["detail"] for c in empty.components if c["value"] is None)
    risky = score.score(score.ScoreInputs(ev_cal=0.10, review_decision="REJECT"))
    assert next(c for c in risky.components if c["key"] == "context_risk")["points"] == 0


def test_checkpoints() -> None:
    cp = decision.checkpoint_of
    assert cp(2000, important=False, lineups=False) == "T-36h"
    assert cp(1400, important=False, lineups=False) == "T-24h"
    assert cp(700, important=False, lineups=False) == "T-12h"
    assert cp(300, important=False, lineups=False) == "T-6h"
    assert cp(170, important=False, lineups=False) == "T-3h"
    assert cp(85, important=False, lineups=False) == "T-90m"
    assert cp(85, important=False, lineups=True) == "lineups"
    assert cp(50, important=False, lineups=False) == "T-60m"
    assert cp(12, important=False, lineups=False) == "T-60m"
    assert cp(12, important=True, lineups=True) == "T-15m"


def test_context_status() -> None:
    cs = decision.context_status
    assert cs(ai_mode="off", first_pass=True, reviewed=True, searched=True, web_good=3, provider_items=1,
              lineups=True) == "AI_OFF"
    assert cs(ai_mode="shadow", first_pass=False, reviewed=False, searched=False, web_good=0, provider_items=0,
              lineups=False) == "PENDING"
    assert cs(ai_mode="shadow", first_pass=True, reviewed=True, searched=True, web_good=0, provider_items=0,
              lineups=False) == "LIMITED", "searched, nothing found: CONTEXTO EXTERNO LIMITADO"
    assert cs(ai_mode="shadow", first_pass=True, reviewed=True, searched=False, web_good=0, provider_items=2,
              lineups=False) == "PARTIAL"
    assert cs(ai_mode="shadow", first_pass=True, reviewed=True, searched=True, web_good=1, provider_items=0,
              lineups=False) == "FULL"


def test_ev_with_a_push() -> None:
    assert decision.ev_of(0.5, 2.1) == pytest.approx(0.05)
    assert decision.ev_of(0.5, 2.1, p_push=0.2) == pytest.approx(0.04)


def test_postmortem_separates_the_decision_from_the_result() -> None:
    assert postmortem.quality_of(0.03) == "GOOD" and postmortem.quality_of(-0.03) == "BAD"
    assert postmortem.quality_of(0.0) == "NEUTRAL" and postmortem.quality_of(None) == "UNKNOWN"
    assert postmortem.verdict_of("win", "GOOD") == "MERECIDO"
    assert postmortem.verdict_of("win", "BAD") == "SUERTE"
    assert postmortem.verdict_of("loss", "GOOD") == "VARIANZA"
    assert postmortem.verdict_of("loss", "BAD") == "ERROR"
    assert postmortem.verdict_of("void", "GOOD") == "NULO"
    assert postmortem.verdict_of("loss", "UNKNOWN") == "SIN_DATOS"


def test_postmortem_causes() -> None:
    d = {"market_key": "1X2", "selection": "Home", "line": Decimal(0)}
    events = [
        {"minute": 8, "event_type": "Goal", "detail": "Normal Goal", "team_side": "away", "comments": None},
        {"minute": 34, "event_type": "Card", "detail": "Red Card", "team_side": "home", "comments": None},
        {"minute": 70, "event_type": "Goal", "detail": "Missed Penalty", "team_side": "home", "comments": None},
        {"minute": 20, "event_type": "subst", "detail": "Substitution 1", "team_side": "home", "comments": None},
    ]
    stats_ = {"home": {"yellow_cards": 5, "red_cards": 1, "xg": 1.9}, "away": {"yellow_cards": 4, "red_cards": 0,
                                                                                "xg": 0.6}}
    causes = postmortem.causes_of(d, events, stats_, {"gh": 0, "ga": 1}, referee_avg=4.0)
    codes = {c["code"]: c for c in causes}
    assert codes["red_card"]["effect"] == "against", "a red card for the backed side counts against the selection"
    assert codes["early_goal"]["effect"] == "against"
    assert "penalty_missed" in codes and "early_substitution" in codes
    assert codes["cards_above_referee"]["cards"] == 10
    assert codes["xg_supported"]["effect"] == "for", "1.9 - 0.6 xG: the game backed the home side"


def test_memory_merge_accumulates() -> None:
    first = memory.merge(None, {"decisions": 2, "wins": 1, "losses": 1, "settled": 2, "profit_flat": 0.1,
                                "clv_sum": 0.02, "clv_n": 2, "by_state": {"INVESTIGACION": 2}, "results": ["W", "L"]})
    second = memory.merge(first, {"decisions": 1, "wins": 1, "losses": 0, "settled": 1, "profit_flat": 0.9,
                                  "clv_sum": 0.01, "clv_n": 1, "by_state": {"CAUTELA": 1}, "results": ["W"]})
    assert second["decisions"] == 3 and second["wins"] == 2 and second["last10"] == ["W", "L", "W"]
    assert second["by_state"] == {"INVESTIGACION": 2, "CAUTELA": 1}
    assert second["clv_mean"] == pytest.approx(0.01)
    assert second["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)
    ref = memory.merge(None, {"matches": 2, "cards": 9, "fouls": 50, "fouls_matches": 2, "penalties": 1})
    assert ref["cards_per_match"] == 4.5 and ref["fouls_per_match"] == 25.0


def test_discovery_classifies_and_never_activates() -> None:
    assert discovery.classify("Total - Home") == ("goals", "goal_matrix")
    assert discovery.classify("Corners Over Under")[0] == "corners"
    assert discovery.classify("Cards Over/Under")[0] == "cards"
    assert discovery.classify("Anytime Goal Scorer")[0] == "players"
    assert discovery.classify("Own Goal") == (None, "not_modelable")
    at = datetime(2032, 9, 20, tzinfo=UTC)
    b = discovery.BetStats(name="Corners Over Under", fixtures=set(range(150)), books_per_fixture=[5] * 150,
                           lines={"Over 9.5"}, competitions={1})
    status, crit, metrics, proposal = discovery.criteria_for(
        45, b, catalogue={"first_seen_at": at - timedelta(days=40)}, active={}, n_fixtures=200,
        coverage={"corners": 0.87}, at=at, fixtures_by_competition={1: 160})
    assert status == "RESEARCH" and "corners" in proposal
    assert crit["calibration"]["ok"] is False and crit["shadow"]["ok"] is False
    assert len([k for k in crit if k != "settle_data"]) == 10
    active, *_ = discovery.criteria_for(5, discovery.BetStats(name="Goals Over/Under", fixtures={1}),
                                        catalogue=None, active={5: "OU"}, n_fixtures=1, coverage={}, at=at)
    assert active == "ACTIVE"
    assert not math.isnan(metrics["share"])

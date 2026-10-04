"""Research V2 (GATE F-G): every model family against the market, on the validated history.

One run, fixed protocol, nothing tuned on the test season:

1. E1 - the market champion: every de-vigged market baseline scored on the fixtures all of
   them priced; the lowest log loss is the CHAMPION.
2. The walk-forward session (``fbi.backtesting.session``): base rates, Poisson,
   Dixon-Coles, the Elo ordered logit, the multinomial logit - plus the E5 challengers,
   gradient-boosted trees without and with the pre-closing market as an input, and the
   ensemble rung: an equal-weight log pool of the models that read no market
   (``fbi.research.v2_models``).
3. E2 - for every model, its walk-forward predictions on the VALIDATION season too, to fit
   the weight a logarithmic opinion pool gives it next to the market
   (``fbi.research.blend``), applied unchanged to the test season; and the weight
   re-estimated on the test season with its interval.
4. Roles (``fbi.research.roles``): CHAMPION, CHALLENGER, RESEARCH or REJECTED.
5. E0 - the shadow picks' returns decomposed into price, edge and luck
   (``fbi.research.pick_audit``).
6. Prospective - the forecasts stored before kick-off since 25 Sep 2026, judged against the
   closing consensus per segment (``fbi.research.prospective``).

Qualified picks need a model whose gate passed and an explicit promotion; nothing here
promotes anything.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import psycopg
from numpy.typing import NDArray

from fbi.backtesting.evaluate import BASELINES_1X2, Comparison, SessionEvaluation, evaluate_session
from fbi.backtesting.session import SessionResult, run_session
from fbi.backtesting.walkforward import (
    ModelRun,
    WalkForwardConfig,
    outcome_index,
    run_base_rates,
    run_elo_ologit,
    run_goal_model,
    run_mnlogit,
)
from fbi.models.metrics import log_loss
from fbi.research.blend import BlendResult, blend_analysis
from fbi.research.pick_audit import AuditResult, audit_picks
from fbi.research.prospective import MIN_SEGMENT, ProspectiveResult, evaluate_prospective
from fbi.research.roles import Role, model_role
from fbi.research.v2_models import MARKET_INPUT, ensemble_run, run_hgb, validation_targets

Progress = Callable[[str], None]
HGB_REFIT_DAYS = 30
BLEND_BASES = ("champion", MARKET_INPUT)
"""The blend is fitted against the champion (does the model know something the closing
line did not?) and against the pre-closing average (something the price at pick time did
not?)."""


@dataclass
class ChampionChoice:
    key: str
    n_common: int
    logloss: dict[str, float]
    """baseline key -> log loss on the fixtures every 1X2 baseline priced."""


@dataclass
class V2Result:
    session: SessionResult
    champion: ChampionChoice
    validation_runs: dict[str, ModelRun]
    blends: dict[str, dict[str, BlendResult]]
    roles: dict[str, Role]
    data_as_of: datetime | None
    audit: AuditResult | None = None
    prospective: ProspectiveResult | None = None
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def evaluation(self) -> SessionEvaluation:
        return self.session.evaluation

    def vs_champion(self, model: str) -> Comparison | None:
        ev = next((e for e in self.evaluation.models if e.run.model == model), None)
        if ev is None:
            return None
        return next((c for c in ev.comparisons if c.baseline_key == self.champion.key), None)

    def model_metrics(self) -> dict[str, dict[str, Any]]:
        """What each model's experiment row carries beyond the standard session metrics."""
        out: dict[str, dict[str, Any]] = {}
        for ev in self.evaluation.models:
            m = ev.run.model
            c = self.vs_champion(m)
            out[m] = {"research_v2": {
                "champion": self.champion.key,
                "vs_champion": None if c is None else {"n": c.n_common, "diff": [c.logloss_diff.mean,
                                                                                  c.logloss_diff.lo,
                                                                                  c.logloss_diff.hi],
                                                       "verdict": c.verdict, "evidence": c.evidence},
                "blends": {k: b.as_json() for k, b in self.blends.get(m, {}).items()},
                "role": self.roles[m].role if m in self.roles else None,
                "role_reason": self.roles[m].reason if m in self.roles else None,
                "validation_predictions": len(self.validation_runs[m].predictions)
                if m in self.validation_runs else 0,
                "data_as_of": None if self.data_as_of is None else self.data_as_of.isoformat(),
            }}
        return out


def choose_champion(evaluation: SessionEvaluation, data_market: dict[str, dict[int, Any]]) -> ChampionChoice:
    y = {m.fixture_id: outcome_index(m) for m in evaluation.targets}
    keys = [k for k in BASELINES_1X2 if data_market.get(k)]
    common = set(y)
    for k in keys:
        common &= set(data_market[k])
    ids = sorted(common)
    yy = np.array([y[i] for i in ids])
    scores: dict[str, float] = {}
    for k in keys:
        t = data_market[k]
        p = np.array([[t[i].p_home, t[i].p_draw, t[i].p_away] for i in ids])
        scores[k] = log_loss(p, yy) if ids else float("inf")
    best = min(scores, key=lambda k: scores[k]) if scores else "pinnacle/closing/shin"
    return ChampionChoice(best, len(ids), scores)


def _probs(run: ModelRun) -> dict[int, NDArray[np.float64]]:
    return {fid: np.array(p.p) for fid, p in run.predictions.items()}


def _market(data_market: dict[str, dict[int, Any]], key: str) -> dict[int, NDArray[np.float64]]:
    return {fid: np.array([t.p_home, t.p_draw, t.p_away]) for fid, t in data_market.get(key, {}).items()}


def run_v2(conn: psycopg.Connection[Any], cfg: WalkForwardConfig, competitions: list[tuple[int, str]], *,
           at: datetime, progress: Progress | None = None, with_audit: bool = True,
           with_prospective: bool = True) -> V2Result:
    say = progress or (lambda _m: None)
    started = time.monotonic()
    session = run_session(conn, cfg, competitions, progress=say)
    data = session.data
    targets = session.targets

    for with_market in (False, True):
        t0 = time.monotonic()
        run = run_hgb(data, targets, cfg=cfg, refit_days=HGB_REFIT_DAYS, with_market=with_market)
        session.runs.append(run)
        say(f"{run.model}: {len(run.predictions)} predictions in {time.monotonic() - t0:.0f}s")
    ensemble = ensemble_run(session.runs)
    session.runs.append(ensemble)
    say(f"ensemble: {len(ensemble.predictions)} predictions ({ensemble.spec})")
    session.evaluation = evaluate_session(data, targets, session.runs)

    champion = choose_champion(session.evaluation, data.market)
    say(f"champion: {champion.key} on {champion.n_common} fixtures " +
        ", ".join(f"{k} {v:.5f}" for k, v in sorted(champion.logloss.items(), key=lambda kv: kv[1])))

    val = validation_targets(data, cfg)
    val_runs: dict[str, ModelRun] = {}
    for kind, spec in session.specs.items():
        val_runs[kind] = run_goal_model(data, val, spec=spec, cfg=cfg, refit_days=cfg.validation_refit_days,
                                        intervals=False)
    for label, runner in (("elo_ologit", run_elo_ologit), ("base_rates", run_base_rates), ("mnlogit", run_mnlogit)):
        val_runs[label] = runner(data, val, cfg=cfg, refit_days=cfg.validation_refit_days)
    for with_market in (False, True):
        r = run_hgb(data, val, cfg=cfg, refit_days=HGB_REFIT_DAYS, with_market=with_market)
        val_runs[r.model] = r
    val_runs["ensemble"] = ensemble_run(list(val_runs.values()))
    say("validation predictions: " + ", ".join(f"{k} {len(v.predictions)}" for k, v in sorted(val_runs.items())))

    y_test = {m.fixture_id: outcome_index(m) for m in targets if m.has_result}
    y_val = {m.fixture_id: outcome_index(m) for m in val}
    days = {m.fixture_id: m.kickoff_at.date().isoformat() for m in targets}
    blends: dict[str, dict[str, BlendResult]] = {}
    roles: dict[str, Role] = {}
    for run in session.runs:
        blends[run.model] = {}
        for base in BLEND_BASES:
            key = champion.key if base == "champion" else base
            q = _market(data.market, key)
            vr = val_runs.get(run.model)
            b = blend_analysis(base_key=key, val_q=q, val_m=_probs(vr) if vr else {}, val_y=y_val,
                               test_q=q, test_m=_probs(run), test_y=y_test, test_blocks=days)
            if b is not None:
                blends[run.model][key] = b
        roles[run.model] = model_role(_vs(session.evaluation, run.model, champion.key),
                                      blends[run.model].get(champion.key), champion=champion.key)
        say(f"{run.model}: {roles[run.model].role} - {roles[run.model].reason}")

    as_of = max((m.kickoff_at for m in data.matches if m.has_result), default=None)
    result = V2Result(session, champion, val_runs, blends, roles, as_of)
    if with_audit:
        result.audit = audit_picks(conn, at=at)
        say(f"pick audit: {result.audit.overall}")
    if with_prospective:
        result.prospective = evaluate_prospective(conn, until=at)
        judged = sum(1 for r in result.prospective.rows if r.n_common >= MIN_SEGMENT)
        say(f"prospective: {result.prospective.played} played, {result.prospective.priced} priced, "
            f"{judged} model-segment pairs with {MIN_SEGMENT}+ fixtures")
    result.seconds = time.monotonic() - started
    return result


def _vs(evaluation: SessionEvaluation, model: str, key: str) -> Comparison | None:
    ev = next((e for e in evaluation.models if e.run.model == model), None)
    return None if ev is None else next((c for c in ev.comparisons if c.baseline_key == key), None)


__all__ = ["V2Result", "choose_champion", "run_v2"]

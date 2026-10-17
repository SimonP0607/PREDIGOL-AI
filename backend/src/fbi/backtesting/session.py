"""One walk-forward backtest session, end to end, as a function.

``scripts.run_backtest`` prints and stores it; ``scripts.experiment reproduce``
runs it again from a registry row and compares. Both call this, so a
reproduction exercises exactly the code that produced the original.

Zero provider requests: reads core fixtures and results, the current feature
version, market.historical_odds and analytics.market_baseline.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.backtesting.data import BacktestData, load_backtest_data
from fbi.backtesting.evaluate import SessionEvaluation, evaluate_session
from fbi.backtesting.persist import base_rates_hyper, goal_hyper, mnlogit_hyper, ologit_hyper
from fbi.backtesting.walkforward import (
    GoalSpec,
    ModelRun,
    WalkForwardConfig,
    run_base_rates,
    run_elo_ologit,
    run_goal_model,
    run_mnlogit,
    select_goal_spec,
)
from fbi.features.data import MatchRecord
from fbi.features.engine import FEATURE_VERSION

MIN_SEASON_FIXTURES = 100
GOAL_MODELS = ("poisson", "dixon_coles")
SEEDS = {"comparison_bootstrap": 11, "roi_bootstrap": 17, "parameter_intervals": 7}
"""Every random draw in a session is seeded with a constant; the registry records
them. Changing one is a code change, visible in the code version."""
BOOTSTRAP_SEED = SEEDS["comparison_bootstrap"]

Progress = Callable[[str], None]


@dataclass
class SessionResult:
    cfg: WalkForwardConfig
    competitions: list[tuple[int, str]]
    data: BacktestData
    targets: list[MatchRecord]
    specs: dict[str, GoalSpec]
    selection: dict[str, Any]
    runs: list[ModelRun]
    evaluation: SessionEvaluation
    feature_version: str = FEATURE_VERSION
    seconds: float = 0.0


def eligible_competitions(conn: psycopg.Connection, provider_ids: list[int], validation: int, test: int
                          ) -> list[tuple[int, str]]:
    """Domestic leagues with at least MIN_SEASON_FIXTURES finished fixtures in both seasons."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT c.id, c.name
            FROM core.competitions c
            JOIN core.competition_seasons cs ON cs.competition_id = c.id
            JOIN core.fixtures f ON f.competition_season_id = cs.id AND f.status_group = 'finished'
            WHERE c.competition_type = 'domestic_league'
              AND (%s::bigint[] IS NULL OR c.provider_league_id = ANY(%s::bigint[]))
            GROUP BY c.id, c.name
            HAVING count(*) FILTER (WHERE cs.season = %s) >= %s AND count(*) FILTER (WHERE cs.season = %s) >= %s
            ORDER BY c.id
            """,
            (provider_ids or None, provider_ids or None, validation, MIN_SEASON_FIXTURES, test, MIN_SEASON_FIXTURES),
        )
        return [(int(a), str(b)) for a, b in cur.fetchall()]


def run_session(conn: psycopg.Connection, cfg: WalkForwardConfig, competitions: list[tuple[int, str]], *,
                progress: Progress | None = None) -> SessionResult:
    say = progress or (lambda _m: None)
    started = time.monotonic()
    data = load_backtest_data(conn, feature_version=FEATURE_VERSION, feature_competitions=cfg.competition_ids)
    targets = [m for m in data.matches if m.competition_id in cfg.competition_ids
               and m.season == cfg.test_season and m.has_result]
    say(f"{len(data.matches)} fixtures loaded; {len(targets)} test fixtures with results")

    selection: dict[str, Any] = {}
    specs: dict[str, GoalSpec] = {}
    for kind in GOAL_MODELS:
        say(f"selecting {kind} hyper-parameters on {cfg.validation_season} ...")
        spec, scores, grid = select_goal_spec(data, cfg, kind, progress=say)
        specs[kind] = spec
        selection[kind] = {"chosen": {"xi": spec.xi, "penalty": spec.penalty}, "validation_logloss": scores,
                           "initial_grid": {"xi": list(cfg.xi_grid), "penalty": list(cfg.penalty_grid)},
                           "final_grid": grid, "validation_season": cfg.validation_season}
        say(f"  -> {kind}: {spec.tag}")

    runs: list[ModelRun] = []
    for kind in GOAL_MODELS:
        t0 = time.monotonic()
        runs.append(run_goal_model(data, targets, spec=specs[kind], cfg=cfg, refit_days=cfg.refit_days,
                                   intervals=True))
        say(f"{kind}: {len(runs[-1].predictions)} predictions in {time.monotonic() - t0:.0f}s")
    for label, runner in (("elo_ologit", run_elo_ologit), ("base_rates", run_base_rates), ("mnlogit", run_mnlogit)):
        t0 = time.monotonic()
        runs.append(runner(data, targets, cfg=cfg, refit_days=cfg.refit_days))
        say(f"{label}: {len(runs[-1].predictions)} predictions in {time.monotonic() - t0:.0f}s")

    evaluation = evaluate_session(data, targets, runs)
    return SessionResult(cfg, competitions, data, targets, specs, selection, runs, evaluation,
                         seconds=time.monotonic() - started)


def hypers_for(result: SessionResult, code_version: str) -> dict[str, dict[str, Any]]:
    """The recorded hyper-parameters of every model in the session (model version identity)."""
    cfg = result.cfg
    hypers = {kind: goal_hyper(result.specs[kind].xi, result.specs[kind].penalty, cfg, code_version)
              for kind in GOAL_MODELS}
    hypers["elo_ologit"] = ologit_hyper(code_version)
    hypers["base_rates"] = base_rates_hyper(cfg, code_version)
    hypers["mnlogit"] = mnlogit_hyper(code_version)
    return hypers

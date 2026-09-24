"""Walk-forward predictive backtest of the V2 models against the de-vigged market.

    python -m scripts.run_backtest                  # dry run: full report printed and saved as JSON, nothing stored
    python -m scripts.run_backtest --apply          # store the session (refuses on uncommitted code)

Protocol (fixed before any test result is seen):
  * competitions: every domestic league with at least 100 finished fixtures in both the
    validation and the test season (or --competitions, provider league ids);
  * validation season: time decay and shrinkage for the goal models are chosen
    here, by log loss, on the fixtures every candidate predicted;
  * test season: refit every --refit-days on results public before the
    block's cut-off (kick-off of its first fixture minus 60 minutes);
  * every model is scored on its own sample AND on the fixtures it shares with
    each market baseline; the verdict against the market needs the whole
    paired-bootstrap interval on one side of zero.

Zero provider requests. Reads core fixtures/results, features fv1.0.0,
market.historical_odds and analytics.market_baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from fbi.backtesting.data import load_backtest_data
from fbi.backtesting.evaluate import PRIMARY_BASELINE, SessionEvaluation, evaluate_session
from fbi.backtesting.persist import (
    MODEL_SEMVER,
    comparison_json,
    config_hash,
    config_json,
    find_completed_session,
    scores_json,
    store_session,
)
from fbi.backtesting.walkforward import (
    MIN_GOAL_TRAIN,
    MIN_OLOGIT_TRAIN,
    WalkForwardConfig,
    run_elo_ologit,
    run_goal_model,
    select_goal_spec,
)
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.features.engine import FEATURE_VERSION
from fbi.ingestion.ledger import RunCounters, RunLedger

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "data" / "reports"
MIN_SEASON_FIXTURES = 100


def _say(msg: str) -> None:
    print(msg, flush=True)


def _dirty() -> list[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "migrations"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.splitlines() if line.strip()]


def _competitions(conn: psycopg.Connection, provider_ids: list[int], validation: int, test: int) -> list[tuple[int, str]]:
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


def report_json(name: str, cfg: WalkForwardConfig, evaluation: SessionEvaluation, selection: dict[str, object],
                competitions: list[tuple[int, str]], version: str) -> dict[str, object]:
    return {
        "name": name,
        "generated_at": now().isoformat(),
        "code_version": version,
        "model_semver": MODEL_SEMVER,
        "feature_version": FEATURE_VERSION,
        "protocol": "walk_forward",
        "config": config_json(cfg),
        "competitions": [{"id": i, "name": n} for i, n in competitions],
        "dataset_hash": evaluation.dataset_hash,
        "targets": len(evaluation.targets),
        "primary_baseline": PRIMARY_BASELINE,
        "selection": selection,
        "baselines": [{"key": b.key, "market": b.market_key, "line": b.line, "scores": scores_json(b.scores),
                       "mean_overround": b.mean_overround} for b in evaluation.baselines],
        "common_sample": {"n": len(evaluation.common_ids),
                          "scores": {k: scores_json(v) for k, v in evaluation.common_scores.items()}},
        "models": [
            {
                "model": ev.run.model, "spec": ev.run.spec, "coverage": ev.coverage, "scores": scores_json(ev.own),
                "comparisons": [comparison_json(c) for c in ev.comparisons],
                "ou": scores_json(ev.ou), "ou_comparisons": [comparison_json(c) for c in ev.ou_comparisons],
                "btts": scores_json(ev.btts), "by_competition": ev.by_competition, "by_month": ev.by_month,
                "betting": None if ev.betting is None else {
                    "hypothetical": True, "rule": ev.betting.rule, "odds_source": ev.betting.odds_source,
                    "fixtures_priced": ev.betting.fixtures_priced, "bets": len(ev.betting.bets),
                    "staked": ev.betting.staked, "profit": ev.betting.profit, "roi_pct": ev.betting.roi_pct,
                    "roi_ci": ev.betting.roi_ci, "max_drawdown": ev.betting.max_drawdown,
                    "mean_probability_edge": ev.betting.mean_probability_edge,
                },
            }
            for ev in evaluation.models
        ],
    }


def _print_summary(evaluation: SessionEvaluation, competitions: dict[int, str]) -> None:
    _say("")
    _say(f"common sample (every model AND {PRIMARY_BASELINE}): {len(evaluation.common_ids)} fixtures")
    _say(f"{'':28s} {'n':>5s} {'log loss':>9s} {'Brier':>8s} {'ECE':>7s}")
    for key, s in sorted(evaluation.common_scores.items(), key=lambda kv: kv[1].log_loss):
        _say(f"  {key:26s} {s.n:5d} {s.log_loss:9.5f} {s.brier:8.5f} {s.ece:7.4f}")
    _say("")
    _say("market baselines (own sample):")
    for b in evaluation.baselines:
        _say(f"  {b.key:30s} {b.market_key:4s} n={b.scores.n:5d} logloss={b.scores.log_loss:.5f} "
             f"brier={b.scores.brier:.5f} ece={b.scores.ece:.4f}")
    for ev in evaluation.models:
        _say("")
        _say(f"{ev.run.model} [{ev.run.spec}] coverage {len(ev.run.predictions)}/{ev.n_targets} "
             f"fits={ev.run.fits} failed={ev.run.failed_fits} no_interval={ev.run.no_interval}")
        if ev.run.uncovered:
            for why, n in Counter(w for _, w in ev.run.uncovered).most_common():
                _say(f"    uncovered {n:4d}: {why}")
        if ev.own is not None:
            _say(f"  own sample: n={ev.own.n} logloss={ev.own.log_loss:.5f} brier={ev.own.brier:.5f} "
                 f"ece={ev.own.ece:.4f} (accuracy {ev.own.accuracy:.1%}, not a ranking metric)")
        for c in (*ev.comparisons, *ev.ou_comparisons):
            _say(f"  vs {c.baseline_key:30s} {c.market_key:4s} n={c.n_common:5d} "
                 f"dLL={c.logloss_diff.mean:+.5f} [{c.logloss_diff.lo:+.5f},{c.logloss_diff.hi:+.5f}] "
                 f"dBrier={c.brier_diff.mean:+.5f} -> {c.verdict}")
        if ev.btts is not None:
            _say(f"  BTTS (no market baseline available): n={ev.btts.n} logloss={ev.btts.log_loss:.5f} "
                 f"brier={ev.btts.brier:.5f} ece={ev.btts.ece:.4f}")
        for cid, row in ev.by_competition.items():
            _say(f"    {competitions.get(int(cid), cid)!s:22s} n={int(row['n']):4d} "
                 f"model={row['model_logloss']:.4f} market={row['baseline_logloss']:.4f} "
                 f"diff={row['logloss_diff']:+.4f}")
        bet = ev.betting
        if bet is not None:
            roi = "-" if bet.roi_pct is None else f"{bet.roi_pct:+.2f}%"
            ci = "" if bet.roi_ci is None else f" [{bet.roi_ci[0]:+.1f}%, {bet.roi_ci[1]:+.1f}%]"
            _say(f"  hypothetical bets ({bet.rule}): {len(bet.bets)} bets, profit {bet.profit:+.2f}u, "
                 f"ROI {roi}{ci}, max drawdown {bet.max_drawdown:.1f}u")


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="run_backtest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="store the session in the database")
    parser.add_argument("--allow-dirty", action="store_true", help="store even with uncommitted code (not reproducible)")
    parser.add_argument("--name", default="", help="session name (default: leagues-<test season>-wf)")
    parser.add_argument("--competitions", default="", help="provider league ids, comma-separated (default: data-driven)")
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--validation-season", type=int, default=2023)
    parser.add_argument("--refit-days", type=int, default=1)
    args = parser.parse_args()

    version = code_version()
    dirty = _dirty()
    if args.apply and dirty and not args.allow_dirty:
        _say("refusing to store: uncommitted changes under src/, scripts/ or migrations/ - the stored result could not "
             "be reproduced from its code_version. Commit first (or pass --allow-dirty).")
        for line in dirty[:10]:
            _say(f"  {line}")
        return 2
    started = time.monotonic()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        provider_ids = [int(x) for x in args.competitions.split(",") if x.strip()]
        comps = _competitions(conn, provider_ids, args.validation_season, args.test_season)
        if not comps:
            _say("no competition has enough finished fixtures in both seasons")
            return 1
        cfg = WalkForwardConfig(competition_ids=tuple(i for i, _ in comps), test_season=args.test_season,
                                validation_season=args.validation_season, refit_days=args.refit_days)
        name = args.name or f"leagues-{args.test_season}-wf"
        _say(f"backtest '{name}' at {version}: {', '.join(n for _, n in comps)}")
        _say(f"validation season {cfg.validation_season} (hyper-parameters) -> test season {cfg.test_season} "
             f"(refit every {cfg.refit_days} day(s), cut-off {int(cfg.cutoff_offset.total_seconds() // 60)} min "
             f"before a block's first kick-off, min training {MIN_GOAL_TRAIN} goal / {MIN_OLOGIT_TRAIN} Elo)")
        data = load_backtest_data(conn, feature_version=FEATURE_VERSION)
        targets = [m for m in data.matches if m.competition_id in cfg.competition_ids
                   and m.season == cfg.test_season and m.has_result]
        _say(f"{len(data.matches)} fixtures loaded; {len(targets)} test fixtures with results")

        selection: dict[str, object] = {}
        specs = {}
        for kind in ("poisson", "dixon_coles"):
            _say(f"selecting {kind} hyper-parameters on {cfg.validation_season} ...")
            spec, scores, grid = select_goal_spec(data, cfg, kind, progress=_say)
            specs[kind] = spec
            selection[kind] = {"chosen": {"xi": spec.xi, "penalty": spec.penalty}, "validation_logloss": scores,
                               "initial_grid": {"xi": list(cfg.xi_grid), "penalty": list(cfg.penalty_grid)},
                               "final_grid": grid, "validation_season": cfg.validation_season}
            _say(f"  -> {kind}: {spec.tag}")

        runs = []
        for kind in ("poisson", "dixon_coles"):
            t0 = time.monotonic()
            runs.append(run_goal_model(data, targets, spec=specs[kind], cfg=cfg, refit_days=cfg.refit_days,
                                       intervals=True))
            _say(f"{kind}: {len(runs[-1].predictions)} predictions in {time.monotonic() - t0:.0f}s")
        t0 = time.monotonic()
        runs.append(run_elo_ologit(data, targets, cfg=cfg, refit_days=cfg.refit_days))
        _say(f"elo_ologit: {len(runs[-1].predictions)} predictions in {time.monotonic() - t0:.0f}s")

        evaluation = evaluate_session(data, targets, runs)
        _print_summary(evaluation, dict(comps))

        report = report_json(name, cfg, evaluation, selection, comps, version)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"backtest-{name}-{now().strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        _say("")
        _say(f"report: {path.relative_to(REPO)}  ({time.monotonic() - started:.0f}s)")
        if not args.apply:
            _say("dry run - nothing stored (use --apply)")
            return 0

        hypers = {
            kind: {"xi": specs[kind].xi, "penalty": specs[kind].penalty, "history_days": cfg.history_days,
                   "min_train": MIN_GOAL_TRAIN, "interval": "laplace 90%", "code_version": version}
            for kind in ("poisson", "dixon_coles")
        }
        hypers["elo_ologit"] = {"elo": "elo-v2.0 K=20 home=65 initial=1500", "feature_version": FEATURE_VERSION,
                                "min_train": MIN_OLOGIT_TRAIN, "interval": "laplace 90%", "code_version": version}
        cfg_hash = config_hash({"cfg": config_json(cfg), "hypers": hypers, "semver": MODEL_SEMVER})
        existing = find_completed_session(conn, name=name, dataset_hash=evaluation.dataset_hash,
                                          code_version=version, cfg_hash=cfg_hash)
        if existing is not None:
            _say(f"session {existing} already holds this exact backtest (same data, code and config) - nothing stored")
            return 0
        ledger = RunLedger(conn)
        run_id = ledger.open("backtest", params={"name": name, "test_season": cfg.test_season,
                                                 "competitions": list(cfg.competition_ids)})
        counters = RunCounters()
        try:
            session_id = store_session(conn, name=name, cfg=replace(cfg), data=data, evaluation=evaluation,
                                       selection=selection, hypers=hypers, code_version=version, cfg_hash=cfg_hash)
            conn.commit()
            counters.rows_inserted = sum(len(r.predictions) for r in runs)
            _say(f"stored session {session_id} (ledger run {run_id})")
        except Exception as exc:
            conn.rollback()
            counters.errors.append(f"{type(exc).__name__}: {exc}"[:500])
            ledger.close(run_id, counters, notes="failed, nothing stored")
            raise
        ledger.close(run_id, counters, notes=f"session {session_id}, 0 requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

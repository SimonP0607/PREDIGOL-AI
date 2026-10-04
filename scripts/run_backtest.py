"""Walk-forward predictive backtest of the V2 models against the de-vigged market.

    python -m scripts.run_backtest                  # dry run: full report printed and saved as JSON, nothing stored
    python -m scripts.run_backtest --apply          # store the session and one registry experiment per model
                                                    # (refuses on uncommitted code)

Protocol (fixed before any test result is seen):
  * competitions: every domestic league with at least 100 finished fixtures in both the
    validation and the test season (or --competitions, provider league ids);
  * validation season: time decay and shrinkage for the goal models are chosen
    here, by log loss, on the fixtures every candidate predicted;
  * test season: refit every --refit-days on results public before the
    block's cut-off (kick-off of its first fixture minus 60 minutes);
  * families: the no-skill base rates, Poisson, Dixon-Coles, the Elo ordered logit
    and the multinomial logistic on feature version 2 (fbi.models.families);
  * every model is scored on its own sample AND on the fixtures it shares with
    each market baseline; the verdict against the market needs the whole
    interval (match days resampled as blocks) on one side of zero, and a
    comparison whose interval straddles zero is labelled with its evidence
    ('equivalent' inside +/- 0.005 nats, else 'insufficient');
  * every stored model gets a research-registry experiment with its model gate
    (fbi.research.gate): RESEARCH unless all six checks pass.

Zero provider requests. Reads core fixtures/results, the current feature
version, market.historical_odds and analytics.market_baseline.
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

from fbi.backtesting.evaluate import PRIMARY_BASELINE, SessionEvaluation
from fbi.backtesting.persist import (
    MODEL_SEMVER,
    comparison_json,
    config_hash,
    config_json,
    find_completed_session,
    scores_json,
    store_session,
)
from fbi.backtesting.session import SessionResult, eligible_competitions, hypers_for, run_session
from fbi.backtesting.walkforward import (
    MIN_GOAL_TRAIN,
    MIN_MNLOGIT_TRAIN,
    MIN_OLOGIT_TRAIN,
    WalkForwardConfig,
)
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.features.engine import FEATURE_VERSION
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.research.experiments import record_session
from fbi.research.gate import evaluate_gate

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "data" / "reports"
QUESTION = ("Out of sample and walk-forward, does any model family forecast 1X2 better than the de-vigged "
            "Pinnacle closing line - or at least better than the league base rates?")


def _say(msg: str) -> None:
    print(msg, flush=True)


def dirty_tree() -> list[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "migrations"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.splitlines() if line.strip()]


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
                "gate": evaluate_gate(ev, evaluation, refit_days=cfg.refit_days),
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


def print_summary(evaluation: SessionEvaluation, competitions: dict[int, str], refit_days: int) -> None:
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
            dm = "" if c.dm_p is None else f" DM p={c.dm_p:.3f}"
            _say(f"  vs {c.baseline_key:30s} {c.market_key:4s} n={c.n_common:5d} "
                 f"dLL={c.logloss_diff.mean:+.5f} [{c.logloss_diff.lo:+.5f},{c.logloss_diff.hi:+.5f}] "
                 f"dBrier={c.brier_diff.mean:+.5f}{dm} -> {c.verdict} ({c.evidence})")
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
        gate = evaluate_gate(ev, evaluation, refit_days=refit_days)
        failed = [k for k, v in gate["checks"].items() if not v["passed"]]
        _say(f"  model gate: {'PASSED' if gate['passed'] else 'not passed'}"
             + ("" if gate["passed"] else f" ({', '.join(failed)})"))


def save_report(name: str, result: SessionResult, version: str) -> Path:
    report = report_json(name, result.cfg, result.evaluation, result.selection, result.competitions, version)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"backtest-{name}-{now().strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="run_backtest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="store the session and its experiments")
    parser.add_argument("--allow-dirty", action="store_true", help="store even with uncommitted code (not reproducible)")
    parser.add_argument("--name", default="", help="session name (default: leagues-<test season>-wf)")
    parser.add_argument("--competitions", default="", help="provider league ids, comma-separated (default: data-driven)")
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--validation-season", type=int, default=2023)
    parser.add_argument("--refit-days", type=int, default=1)
    args = parser.parse_args()

    version = code_version()
    dirty = dirty_tree()
    if args.apply and dirty and not args.allow_dirty:
        _say("refusing to store: uncommitted changes under src/, scripts/ or migrations/ - the stored result could not "
             "be reproduced from its code_version. Commit first (or pass --allow-dirty).")
        for line in dirty[:10]:
            _say(f"  {line}")
        return 2
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.apply:
            from fbi.datasets.versions import DatasetNotModelReadyError, require_model_ready

            try:
                _say(f"dataset: {require_model_ready(conn)}")
            except DatasetNotModelReadyError as exc:
                _say(f"refusing to store: {exc}")
                return 4
        provider_ids = [int(x) for x in args.competitions.split(",") if x.strip()]
        comps = eligible_competitions(conn, provider_ids, args.validation_season, args.test_season)
        if not comps:
            _say("no competition has enough finished fixtures in both seasons")
            return 1
        cfg = WalkForwardConfig(competition_ids=tuple(i for i, _ in comps), test_season=args.test_season,
                                validation_season=args.validation_season, refit_days=args.refit_days)
        name = args.name or f"leagues-{args.test_season}-wf"
        _say(f"backtest '{name}' at {version}: {', '.join(n for _, n in comps)}")
        _say(f"validation season {cfg.validation_season} (hyper-parameters) -> test season {cfg.test_season} "
             f"(refit every {cfg.refit_days} day(s), cut-off {int(cfg.cutoff_offset.total_seconds() // 60)} min "
             f"before a block's first kick-off, min training {MIN_GOAL_TRAIN} goal / {MIN_OLOGIT_TRAIN} Elo / "
             f"{MIN_MNLOGIT_TRAIN} mnlogit)")
        result = run_session(conn, cfg, comps, progress=_say)
        print_summary(result.evaluation, dict(comps), cfg.refit_days)
        path = save_report(name, result, version)
        _say("")
        _say(f"report: {path.relative_to(REPO)}  ({result.seconds:.0f}s)")
        if not args.apply:
            _say("dry run - nothing stored (use --apply)")
            return 0
        started = time.monotonic()
        hypers = hypers_for(result, version)
        cfg_hash = config_hash({"cfg": config_json(cfg), "hypers": hypers, "semver": MODEL_SEMVER})
        existing = find_completed_session(conn, name=name, dataset_hash=result.evaluation.dataset_hash,
                                          code_version=version, cfg_hash=cfg_hash)
        if existing is not None:
            _say(f"session {existing} already holds this exact backtest (same data, code and config) - nothing stored")
            return 0
        ledger = RunLedger(conn)
        run_id = ledger.open("backtest", params={"name": name, "test_season": cfg.test_season,
                                                 "competitions": list(cfg.competition_ids)})
        counters = RunCounters()
        try:
            session_id = store_session(conn, name=name, cfg=replace(cfg), data=result.data,
                                       evaluation=result.evaluation, selection=result.selection, hypers=hypers,
                                       code_version=version, cfg_hash=cfg_hash)
            recorded = record_session(conn, result=result, session_id=session_id, name=name, question=QUESTION,
                                      code_version=version, hypers=hypers, report_path=path)
            conn.commit()
            counters.rows_inserted = sum(len(r.predictions) for r in result.runs)
            _say(f"stored session {session_id} (ledger run {run_id}) in {time.monotonic() - started:.0f}s")
            for r in recorded:
                _say(f"  experiment {r.id} {r.model:12s} {r.research_status}  data/experiments/{r.uuid}/")
        except Exception as exc:
            conn.rollback()
            counters.errors.append(f"{type(exc).__name__}: {exc}"[:500])
            ledger.close(run_id, counters, notes="failed, nothing stored")
            raise
        ledger.close(run_id, counters, notes=f"session {session_id}, {len(recorded)} experiments, 0 requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

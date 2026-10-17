"""REVIEW PREDIGOL (11 Oct 2026), P0 - a pick is qualified only on evidence about ITS market at ITS line.

The walk-forward backtest compares 1X2 and Over/Under 2.5 with the market. The qualification lookup ignored the line,
so an Over/Under 3.5 pick was "qualified" on the 2.5 comparison - a claim nobody tested."""

from __future__ import annotations

from decimal import Decimal

import psycopg

from fbi.picks.engine import OU_BASELINE, _evidence
from fbi.picks.rules import qualify
from tests.integration.conftest import Seed


def _ou_backtest(db: psycopg.Connection, seed: Seed) -> None:
    session = db.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, test_season, test_from, test_to, "
        "primary_baseline, n_targets, dataset_hash, code_version) VALUES ('s','walk_forward','{1}',2025,'2025-08-01',"
        "'2026-05-31','pinnacle/closing/shin',2000,'h','c') RETURNING id").fetchone()[0]  # type: ignore[index]
    run = db.execute(
        "INSERT INTO analytics.backtest_runs (name, model_version_id, competition_ids, test_from, test_to, protocol, "
        "train_window, code_version, dataset_hash, n_samples, accuracy_pct, brier_score, logloss, ece, session_id, "
        "status, finished_at) VALUES ('r',%s,'{1}','2025-08-01','2026-05-31','walk_forward','w','c','h',2000,50,0.6,"
        "1.0,0.01,%s,'completed',now() + interval '100 years') RETURNING id",
        (seed.model_version_id, session)).fetchone()[0]  # type: ignore[index]
    db.execute(
        "INSERT INTO analytics.backtest_comparisons (backtest_run_id, baseline_key, market_key, line, n_common, "
        "model_logloss, baseline_logloss, logloss_diff, logloss_diff_ci_low, logloss_diff_ci_high, model_brier, "
        "baseline_brier, brier_diff, brier_diff_ci_low, brier_diff_ci_high, verdict) VALUES "
        "(%s, %s, 'OU', 2.5, 1500, 0.66, 0.68, -0.02, -0.03, -0.01, 0.23, 0.24, -0.01, -0.02, -0.001, 'better')",
        (run, OU_BASELINE))


def test_an_over_under_pick_is_qualified_only_at_the_line_the_backtest_tested(db: psycopg.Connection,
                                                                               seed: Seed) -> None:
    _ou_backtest(db, seed)
    at_25 = _evidence(db, seed.model_version_id, "OU", Decimal("2.5"))
    assert at_25.verdict == "better" and qualify(at_25).qualified
    at_35 = _evidence(db, seed.model_version_id, "OU", Decimal("3.5"))
    assert at_35.verdict is None
    q = qualify(at_35)
    assert not q.qualified and "at this line" in q.reasons[0]

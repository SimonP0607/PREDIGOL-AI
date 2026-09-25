"""The research registry against the real schema: rows, files, manifests,
the PRODUCTION guard and the reproduction mark."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from fbi.backtesting.data import BacktestData, MarketTriplet
from fbi.backtesting.evaluate import PRIMARY_BASELINE, evaluate_session
from fbi.backtesting.session import SessionResult
from fbi.backtesting.walkforward import WalkForwardConfig, run_base_rates
from fbi.research.experiments import (
    load_experiment,
    mark_reproduced,
    promote,
    record_session,
    verify_manifest,
)
from tests.unit.test_backtest_protocol import COMP, _league, _targets


def _result() -> SessionResult:
    matches = _league()
    targets = _targets(matches)
    market = {m.fixture_id: MarketTriplet(0.45, 0.27, 0.28, 1.03) for m in targets}
    data = BacktestData(matches, {}, {}, {}, {PRIMARY_BASELINE: market}, {})
    cfg = WalkForwardConfig(competition_ids=(COMP,), refit_days=7)
    runs = [run_base_rates(data, targets, cfg=cfg, refit_days=7)]
    return SessionResult(cfg, [(COMP, "Synthetic League")], data, targets, {}, {}, runs,
                         evaluate_session(data, targets, runs))


def test_a_session_is_recorded_with_files_that_match_their_manifest(db: psycopg.Connection, tmp_path: Path) -> None:
    recorded = record_session(db, result=_result(), session_id=None, name="synthetic", question="plumbing?",
                              code_version="0" * 40, hypers={"base_rates": {"laplace": 1}}, root=tmp_path)
    assert len(recorded) == 1 and recorded[0].model == "base_rates"
    row = load_experiment(db, str(recorded[0].id))
    assert row is not None and load_experiment(db, row.uuid) is not None
    assert row.research_status == "RESEARCH" and row.gate["passed"] is False
    assert set(row.artifact_manifest) == {"predictions.csv", "metrics.json", "config.json"}
    folder = Path(str(row.artifact_path))
    assert verify_manifest(folder, row.artifact_manifest) == []
    assert row.metrics["own_sample"]["n"] > 0 and row.metrics["predictions_digest"]
    assert row.config["seeds"]["comparison_bootstrap"] == 11
    (folder / "metrics.json").write_text("{}")
    assert verify_manifest(folder, row.artifact_manifest) == ["metrics.json: sha256 differs from the recorded one"]


def test_production_needs_a_passed_gate(db: psycopg.Connection, tmp_path: Path) -> None:
    (rec,) = record_session(db, result=_result(), session_id=None, name="synthetic", question="guard?",
                            code_version="0" * 40, hypers={}, root=tmp_path)
    with pytest.raises(PermissionError):
        promote(db, rec.id)
    with db.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute("UPDATE analytics.experiments SET research_status = 'PRODUCTION' WHERE id = %s", (rec.id,))


def test_a_reproduction_marks_the_original(db: psycopg.Connection, tmp_path: Path) -> None:
    result = _result()
    (orig,) = record_session(db, result=result, session_id=None, name="synthetic", question="q",
                             code_version="0" * 40, hypers={}, root=tmp_path)
    (copy,) = record_session(db, result=result, session_id=None, name="reproduce-synthetic", question="q",
                             code_version="0" * 40, hypers={}, root=tmp_path,
                             reproduction={"base_rates": {"of": orig.id, "identical": True, "differences": []}})
    row = load_experiment(db, str(copy.id))
    assert row is not None and row.reproduced_from == orig.id and row.metrics["reproduction"]["identical"]
    original = load_experiment(db, str(orig.id))
    assert original is not None
    gate = mark_reproduced(db, original, copy.id)
    assert gate["checks"]["reproducible"]["passed"]
    assert gate["passed"] is False, "reproducible is one check of six; the market is not beaten"
    after = load_experiment(db, str(orig.id))
    assert after is not None and after.research_status == "RESEARCH"
    assert after.gate["checks"]["reproducible"]["passed"]

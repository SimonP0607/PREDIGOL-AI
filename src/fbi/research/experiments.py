"""analytics.experiments: one row per experiment, files under data/experiments/<uuid>/.

What makes an experiment reproducible is recorded with it: the configuration
(walk-forward config, competitions, hyper-parameters), the dataset hash, the
code version, the seeds and the library versions. What it produced is on
disk, each file with a sha256 in ``artifact_manifest``, so a later reader can
tell whether a file is still the one the metrics came from.

No MLflow: a table and a directory are enough for a single-user research
loop, and both are covered by the backup.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import scipy
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.backtesting.evaluate import PRIMARY_BASELINE, ModelEvaluation, SessionEvaluation
from fbi.backtesting.persist import FEATURE_LINEAGE, comparison_json, config_json, scores_json
from fbi.backtesting.session import SEEDS, SessionResult
from fbi.backtesting.walkforward import outcome_index
from fbi.research.gate import evaluate_gate, status_for

REPO = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = REPO / "data" / "experiments"
MANIFEST_ALGORITHM = "sha256"


def environment() -> dict[str, str]:
    return {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__,
            "psycopg": psycopg.__version__, "platform": platform.platform()}


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def manifest(folder: Path) -> dict[str, dict[str, Any]]:
    return {p.name: {MANIFEST_ALGORITHM: sha256_file(p), "bytes": p.stat().st_size}
            for p in sorted(folder.iterdir()) if p.is_file()}


def verify_manifest(folder: Path, recorded: dict[str, dict[str, Any]]) -> list[str]:
    """Problems found; empty when every recorded file is present and unchanged."""
    problems = []
    for name, meta in sorted(recorded.items()):
        p = folder / name
        if not p.is_file():
            problems.append(f"{name}: missing")
        elif sha256_file(p) != meta.get(MANIFEST_ALGORITHM):
            problems.append(f"{name}: sha256 differs from the recorded one")
    return problems


def predictions_digest(ev: ModelEvaluation) -> str:
    """Hash of every prediction a run made, rounded to 12 decimals: what a reproduction must match."""
    d = hashlib.sha256()
    for fid, p in sorted(ev.run.predictions.items()):
        d.update(f"{fid}:{p.data_cutoff.isoformat()}:{','.join(f'{x:.12f}' for x in p.p)};".encode())
    return d.hexdigest()


def metrics_for(ev: ModelEvaluation, evaluation: SessionEvaluation) -> dict[str, Any]:
    primary = ev.primary()
    bet = ev.betting
    return {
        "own_sample": scores_json(ev.own),
        "coverage": ev.coverage,
        "common_sample": {"n": len(evaluation.common_ids),
                          "model": scores_json(evaluation.common_scores.get(ev.run.model)),
                          "market": scores_json(evaluation.common_scores.get(PRIMARY_BASELINE))},
        "primary_baseline": PRIMARY_BASELINE,
        "vs_primary": None if primary is None else comparison_json(primary),
        "vs_market": [comparison_json(c) for c in ev.comparisons],
        "by_competition": ev.by_competition,
        "by_month": ev.by_month,
        "betting_hypothetical": None if bet is None else {
            "rule": bet.rule, "bets": len(bet.bets), "staked": bet.staked, "profit": bet.profit,
            "roi_pct": bet.roi_pct, "roi_ci": bet.roi_ci, "max_drawdown": bet.max_drawdown},
        "predictions_digest": predictions_digest(ev),
    }


def _write_artifacts(folder: Path, ev: ModelEvaluation, result: SessionResult, metrics: dict[str, Any],
                     config: dict[str, Any], report_path: Path | None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    by_id = {m.fixture_id: m for m in result.targets}
    fair = result.data.market.get(PRIMARY_BASELINE, {})
    with (folder / "predictions.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fixture_id", "competition_id", "kickoff_at", "data_cutoff", "p_home", "p_draw", "p_away",
                    "outcome", "market_p_home", "market_p_draw", "market_p_away", "input_hash", "n_train"])
        for fid, p in sorted(ev.run.predictions.items()):
            m = by_id.get(fid)
            if m is None:
                continue
            f = fair.get(fid)
            w.writerow([fid, m.competition_id, m.kickoff_at.isoformat(), p.data_cutoff.isoformat(),
                        f"{p.p[0]:.12f}", f"{p.p[1]:.12f}", f"{p.p[2]:.12f}", outcome_index(m),
                        "" if f is None else f"{f.p_home:.6f}", "" if f is None else f"{f.p_draw:.6f}",
                        "" if f is None else f"{f.p_away:.6f}", p.input_hash, p.n_train])
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str))
    (folder / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True, default=str))
    if report_path is not None and report_path.is_file():
        (folder / "session_report.json").write_bytes(report_path.read_bytes())


@dataclass(frozen=True, slots=True)
class Recorded:
    id: int
    uuid: str
    model: str
    research_status: str
    gate_passed: bool


def record_session(conn: psycopg.Connection, *, result: SessionResult, session_id: int | None, name: str,
                   question: str, code_version: str, hypers: dict[str, dict[str, Any]],
                   report_path: Path | None = None, reproduction: dict[str, dict[str, Any]] | None = None,
                   root: Path | None = None) -> list[Recorded]:
    """One completed experiment per model run of the session. The caller commits.

    ``reproduction``: model -> {"of": original experiment id, "identical": bool,
    "differences": [...]} when this session re-ran a recorded one."""
    cfg = result.cfg
    val = [m for m in result.data.matches if m.competition_id in cfg.competition_ids
           and m.season == cfg.validation_season and m.has_result]
    test_from: date = min(m.kickoff_at for m in result.targets).date()
    test_to: date = max(m.kickoff_at for m in result.targets).date()
    out: list[Recorded] = []
    for ev in result.evaluation.models:
        run = ev.run
        if ev.own is None or not run.predictions or run.train_from is None or run.train_to is None:
            continue
        version_id = None
        if session_id is not None:
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("SELECT model_version_id FROM analytics.backtest_runs WHERE session_id = %s AND name = %s",
                            (session_id, f"{name}:{run.model}"))
                row = cur.fetchone()
                version_id = None if row is None else int(row[0])
        goal = run.model in result.specs
        config = {"walk_forward": config_json(cfg), "competitions": [{"id": i, "name": n} for i, n in
                                                                    result.competitions],
                  "session_name": name, "model": run.model, "spec": run.spec, "hyper": hypers.get(run.model, {}),
                  "selection": result.selection.get(run.model), "seeds": SEEDS}
        metrics = metrics_for(ev, result.evaluation)
        rep = (reproduction or {}).get(run.model)
        origin = None if rep is None else int(rep["of"])
        ok = bool(rep and rep.get("identical"))
        if rep is not None:
            metrics["reproduction"] = rep
        gate = evaluate_gate(ev, result.evaluation, refit_days=cfg.refit_days)
        exp_uuid = str(uuid.uuid4())
        folder = (root or EXPERIMENT_DIR) / exp_uuid
        _write_artifacts(folder, ev, result, metrics, config, report_path)
        files = manifest(folder)
        notes = None
        if origin is not None:
            notes = (f"reproduction of experiment {origin}: " +
                     ("identical predictions" if ok else "DIFFERENT predictions - see metrics.reproduction"))
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "INSERT INTO analytics.experiments (experiment_uuid, name, kind, question, model_family, "
                "model_version_id, backtest_session_id, feature_version, feature_names, train_from, train_to, "
                "validation_from, validation_to, test_from, test_to, config, dataset_hash, code_version, seed, "
                "environment, metrics, artifact_path, artifact_manifest, status, research_status, gate, "
                "reproduced_from, finished_at, notes) VALUES (%s,%s,'backtest',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s,%s,%s,'completed',%s,%s,%s,now(),%s) RETURNING id",
                (exp_uuid, f"{name}:{run.model}", question, run.model, version_id, session_id, result.feature_version,
                 FEATURE_LINEAGE.get(run.model, []), run.train_from.date(), run.train_to.date(),
                 min(m.kickoff_at for m in val).date() if goal and val else None,
                 max(m.kickoff_at for m in val).date() if goal and val else None,
                 test_from, test_to, Json(config), result.evaluation.dataset_hash, code_version,
                 SEEDS["comparison_bootstrap"], Json(environment()), Json(metrics), str(folder), Json(files),
                 status_for(gate), Json(gate), origin, notes),
            )
            row = cur.fetchone()
            assert row is not None
            out.append(Recorded(int(row[0]), exp_uuid, run.model, status_for(gate), bool(gate["passed"])))
    return out


@dataclass(frozen=True, slots=True)
class ExperimentRow:
    id: int
    uuid: str
    name: str
    model_family: str
    backtest_session_id: int | None
    config: dict[str, Any]
    dataset_hash: str | None
    code_version: str
    metrics: dict[str, Any]
    gate: dict[str, Any]
    research_status: str
    artifact_path: str | None
    artifact_manifest: dict[str, Any]
    reproduced_from: int | None


def load_experiment(conn: psycopg.Connection, ref: str) -> ExperimentRow | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        where = "id = %s" if ref.isdigit() else "experiment_uuid::text = %s"
        cur.execute(
            "SELECT id, experiment_uuid::text, name, model_family, backtest_session_id, config, dataset_hash, "
            "code_version, metrics, gate, research_status, artifact_path, artifact_manifest, reproduced_from "
            f"FROM analytics.experiments WHERE {where}", (int(ref) if ref.isdigit() else ref,))
        r = cur.fetchone()
    if r is None:
        return None
    return ExperimentRow(int(r[0]), str(r[1]), str(r[2]), str(r[3]), None if r[4] is None else int(r[4]),
                         dict(r[5]), None if r[6] is None else str(r[6]), str(r[7]), dict(r[8]), dict(r[9]),
                         str(r[10]), None if r[11] is None else str(r[11]), dict(r[12]),
                         None if r[13] is None else int(r[13]))


def session_experiments(conn: psycopg.Connection, session_id: int) -> list[ExperimentRow]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id FROM analytics.experiments WHERE backtest_session_id = %s AND reproduced_from IS NULL "
                    "ORDER BY id", (session_id,))
        ids = [int(r[0]) for r in cur.fetchall()]
    rows = [load_experiment(conn, str(i)) for i in ids]
    return [r for r in rows if r is not None]


def mark_reproduced(conn: psycopg.Connection, original: ExperimentRow, reproduction_id: int) -> dict[str, Any]:
    """Record on the original that it reproduced; re-derive gate.passed and the research status."""
    gate: dict[str, Any] = json.loads(json.dumps(original.gate))
    checks: dict[str, Any] = gate.setdefault("checks", {})
    checks["reproducible"] = {"passed": True, "evidence": f"experiment {reproduction_id} re-ran the recorded code on "
                                                          "the recorded data: identical predictions"}
    gate["passed"] = all(bool(c.get("passed")) for c in checks.values()) and len(checks) == 6
    status = original.research_status
    if status in ("RESEARCH", "CANDIDATE"):
        status = status_for(gate)
    with conn.cursor() as cur:
        cur.execute("UPDATE analytics.experiments SET gate = %s, research_status = %s WHERE id = %s",
                    (Json(gate), status, original.id))
    return gate


def promote(conn: psycopg.Connection, experiment_id: int) -> str:
    """CANDIDATE -> PRODUCTION, only with a passed gate (the schema enforces it too)."""
    row = load_experiment(conn, str(experiment_id))
    if row is None:
        raise LookupError(f"no experiment {experiment_id}")
    if not row.gate.get("passed"):
        failed = [k for k, v in row.gate.get("checks", {}).items() if not v.get("passed")]
        raise PermissionError(f"the model gate has not passed: {', '.join(failed) or 'not evaluated'}")
    with conn.cursor() as cur:
        cur.execute("UPDATE analytics.experiments SET research_status = 'PRODUCTION' WHERE id = %s", (experiment_id,))
    return "PRODUCTION"

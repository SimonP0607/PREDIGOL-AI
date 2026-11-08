"""Calibration drift and the CLV trend (``fbi.observability.drift``, drift-v1) without a database: each rule on crafted data, the minimum
samples, no alert on healthy data, and that the module only reads."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from fbi.ai.calendar import day_start
from fbi.intel import calibration
from fbi.intel.calibration import Obs
from fbi.observability import drift as dr

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 11, 6)
PROMOTED = datetime(2026, 10, 1, 12, tzinfo=UTC)


def ref(**kw: object) -> dr.Reference:
    base = dr.Reference(7, "OU", "poisson", "identity", calibration.VERSION, {}, PROMOTED - timedelta(hours=1), PROMOTED,
                        0.02, 0.68, 0.68, 2000)
    return replace(base, **kw)  # type: ignore[arg-type]


def world(n: int, *, seed: int = 1, shift: float = 0.0, market_noise: float = 0.0, fixture_of: int = 0,
          day: date = DAY) -> list[Obs]:
    """``n`` settled selections on ``day``: the model (and the market) say p, the outcome is drawn from p - shift."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.25, 0.75, n)
    y = (rng.random(n) < np.clip(p - shift, 0.01, 0.99)).astype(float)
    pm = np.clip(p + rng.normal(0, market_noise, n), 0.02, 0.98) if market_noise else p
    ko = day_start(day) + timedelta(hours=15)
    return [Obs(i + 1, (fixture_of or i + 1), ko, ko + timedelta(hours=2), "OU", "poisson", float(p[i]), float(pm[i]), 1.9,
                float(y[i]), None) for i in range(n)]


# ── the calibration cell ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_healthy_calibrator_raises_nothing() -> None:
    cell = dr.assess(ref(), dr.ALL, world(2000))
    assert cell.status == dr.OK, cell.reasons
    assert cell.metrics["ece_status"] == dr.OK and cell.metrics["gap_status"] == dr.OK and cell.n == 2000
    assert cell.metrics["ece"] < cell.metrics["ece_null_q95"] or cell.metrics["ece_excess"] < 0.02


def test_below_the_minimum_a_cell_is_insufficient_and_says_how_many_never_an_alert() -> None:
    cell = dr.assess(ref(), dr.ALL, world(dr.MIN_N - 1, shift=0.3))
    assert cell.status == dr.INSUFFICIENT and cell.n == dr.MIN_N - 1
    assert f"{dr.MIN_N - 1} settled selections" in cell.reasons[0]
    assert dr.DriftReport(DAY, day_start(DAY), (cell,), ()).alerts() == []
    assert dr.assess(ref(), dr.ALL, world(dr.MIN_N)).status != dr.INSUFFICIENT


def test_the_ece_rule_reads_the_excess_over_perfect_calibration_against_the_reference() -> None:
    obs = world(3000, shift=0.08)
    no_gap = ref(logloss=None)
    excess = dr.assess(no_gap, dr.ALL, obs).metrics["ece_excess"]
    assert excess > 0.05
    watch = dr.assess(replace(no_gap, ece=excess - 0.015), dr.ALL, obs)
    alarm = dr.assess(replace(no_gap, ece=excess - 0.03), dr.ALL, obs)
    calm = dr.assess(replace(no_gap, ece=excess), dr.ALL, obs)
    assert (watch.status, alarm.status, calm.status) == (dr.WATCH, dr.DRIFT, dr.OK)
    assert "ECE" in alarm.reasons[0] and "at promotion" in alarm.reasons[0]
    assert any("log-loss rule not applied" in r for r in alarm.reasons)


def test_a_small_sample_ece_floor_alone_is_not_drift() -> None:
    """At n = 300 a perfectly calibrated probability shows an ECE of several points: the null removes it."""
    cell = dr.assess(ref(ece=0.0), dr.ALL, world(dr.MIN_N, seed=4))
    assert cell.metrics["ece"] > 0.02 and cell.metrics["ece_null_mean"] > 0.02
    assert cell.metrics["ece_status"] == dr.OK


def test_the_log_loss_rule_is_the_gap_to_the_market_against_the_gap_at_promotion() -> None:
    obs = world(1000)  # the calibrated probability IS the market's here: the gap is exactly 0, its sd 0
    base = ref(ece=None)
    assert dr.assess(replace(base, logloss=0.680, logloss_market=0.680), "top_league", obs).status == dr.OK
    w = dr.assess(replace(base, logloss=0.665, logloss_market=0.680), "top_league", obs)
    d = dr.assess(replace(base, logloss=0.650, logloss_market=0.680), "top_league", obs)
    assert (w.status, d.status) == (dr.WATCH, dr.DRIFT)
    assert w.metrics["gap_drift"] == 0.015 and d.metrics["gap_reference"] == -0.03


def test_the_log_loss_rule_needs_significance_not_only_size() -> None:
    """A noisy market: the same drift is not enough when z is small."""
    obs = world(dr.MIN_N, seed=9, market_noise=0.15)
    base = ref(ece=None)
    gap = dr.assess(replace(base, logloss=0.7, logloss_market=0.7), dr.ALL, obs).metrics["gap_vs_market"]
    cell = dr.assess(replace(base, logloss=0.7 + gap - 0.025, logloss_market=0.7), dr.ALL, obs)
    assert cell.metrics["gap_drift"] >= dr.GAP_DRIFT_MARGIN and cell.metrics["gap_z"] < dr.Z_DRIFT
    assert cell.status != dr.DRIFT


def test_an_overconfident_model_drifts_on_both_rules() -> None:
    obs = world(3000, shift=0.10)
    cell = dr.assess(ref(), dr.ALL, obs)
    assert cell.status == dr.DRIFT
    assert cell.metrics["ece_status"] == dr.DRIFT
    assert cell.metrics["retire_test_holds"] is True


def test_without_any_reference_figure_the_cell_cannot_be_judged() -> None:
    cell = dr.assess(ref(ece=None, logloss=None), dr.ALL, world(500))
    assert cell.status == dr.INSUFFICIENT and len(cell.reasons) == 2


def test_the_calibrator_s_own_probability_is_the_one_judged() -> None:
    """A platt calibrator that pulls an overconfident model down is healthy where the raw model is not."""
    obs = world(3000, shift=0.10)
    fitted = calibration.fit_params("platt", obs)
    cell = dr.assess(ref(method="platt", params=fitted, logloss=None), dr.ALL, obs)
    assert cell.metrics["ece_status"] == dr.OK
    assert cell.metrics["logloss_cal"] < cell.metrics["logloss_raw"]


def test_cells_split_by_segment_and_keep_all() -> None:
    obs = world(400, seed=2) + [replace(o, pick_id=o.pick_id + 10_000, fixture_id=99_999) for o in world(50, seed=3)]
    segs = {o.fixture_id: "top_league" for o in obs[:400]} | {99_999: "women"}
    cells = dr.cells_of(ref(), obs, segs)
    assert [c.segment for c in cells] == [dr.ALL, "top_league", "women"]
    assert [c.n for c in cells] == [450, 400, 50]
    assert cells[2].status == dr.INSUFFICIENT
    assert dr.cells_of(ref(), obs[:1], {})[1].segment == "unknown"


def test_the_window_is_out_of_sample_and_rolling() -> None:
    r = ref()
    inside = world(3, day=DAY)
    old = world(3, day=DAY - timedelta(days=dr.WINDOW_DAYS))
    first_day = world(3, day=DAY - timedelta(days=dr.WINDOW_DAYS - 1))
    before_promotion = [replace(o, kickoff_at=PROMOTED - timedelta(hours=2)) for o in world(3)]
    other_model = [replace(o, model_name="elo") for o in world(3)]
    got = dr.in_window(inside + old + first_day + other_model, r, day=DAY)
    assert len(got) == 6
    assert dr.in_window(before_promotion, replace(r, promoted_at=PROMOTED), day=date(2026, 10, 1)) == []


def test_a_reference_is_read_from_the_roles_row() -> None:
    row = {"entity_id": 11, "market_key": "BTTS", "model_name": "dc", "method": "logit2", "version": "cal-logit2-v1",
           "params": {"a": 0.1, "b": 0.9, "c": 0.2}, "known_at": PROMOTED, "at": PROMOTED + timedelta(hours=1),
           "wf": {"n": 1800, "ece_cal": 0.021, "logloss_cal": 0.66, "logloss_market": 0.665}}
    r = dr.reference_of(row)
    assert (r.calibrator_id, r.n, r.ece, r.since) == (11, 1800, 0.021, PROMOTED + timedelta(hours=1))
    assert r.gap is not None and abs(r.gap + 0.005) < 1e-12
    assert dr.reference_of(row | {"wf": {}}).gap is None


def test_null_ece_is_reproducible() -> None:
    p = np.linspace(0.2, 0.8, 500)
    assert dr.null_ece(p) == dr.null_ece(p)
    mean, q95, q99 = dr.null_ece(p)
    assert 0 < mean < q95 <= q99


# ── the CLV trend ───────────────────────────────────────────────────────────────────────────────────────────────────


def alternating(n: int, mean: float, spread: float = 0.05) -> list[float]:
    return [mean + (spread if i % 2 else -spread) for i in range(n)]


def test_a_steady_clv_is_ok() -> None:
    t = dr.clv_trend("decision-v1", "OU", alternating(150, -0.02), alternating(400, -0.02))
    assert t.status == dr.OK and t.delta == 0


def test_a_clv_that_falls_is_watched_then_drifts() -> None:
    w = dr.clv_trend("decision-v1", "OU", alternating(150, -0.035), alternating(400, -0.02))
    d = dr.clv_trend("decision-v1", "OU", alternating(150, -0.05), alternating(400, -0.02))
    assert (w.status, d.status) == (dr.WATCH, dr.DRIFT)
    assert "z" in d.reasons[0] and d.as_json()["recent_quality"] == "BAD"


def test_a_clv_that_rises_is_never_an_alert() -> None:
    assert dr.clv_trend("decision-v1", "OU", alternating(150, 0.03), alternating(400, -0.02)).status == dr.OK


def test_a_noisy_fall_is_not_significant() -> None:
    t = dr.clv_trend("decision-v1", "OU", alternating(150, -0.045, spread=0.6), alternating(400, -0.02, spread=0.6))
    assert t.delta is not None and t.delta <= -dr.CLV_DRIFT_DROP and t.status == dr.OK


def test_the_clv_trend_needs_its_minimum_samples() -> None:
    t = dr.clv_trend("decision-v1", "OU", alternating(dr.CLV_MIN_RECENT - 1, -0.2), alternating(400, 0.05))
    assert t.status == dr.INSUFFICIENT and "needs" in t.reasons[0]
    t = dr.clv_trend("decision-v1", "OU", alternating(150, -0.2), alternating(dr.CLV_MIN_BASELINE - 1, 0.05))
    assert t.status == dr.INSUFFICIENT


def test_the_trend_groups_by_layer_and_family_and_splits_the_windows() -> None:
    rows = [("decision-v1", "CORNERS_OU", DAY, -0.05)] * 150 + [("decision-v1", "CORNERS_OU_HOME", DAY - timedelta(days=10), -0.02)] * 400
    rows += [("decision-v1", "CORNERS_OU", DAY - timedelta(days=dr.CLV_RECENT_DAYS + dr.CLV_BASELINE_DAYS), 0.5)] * 10  # outside
    rows += [("decision-fam-v1", "GOALS_HALF", DAY, 0.0)] * 5
    trends = {t.subject: t for t in dr.clv_trends(rows, day=DAY)}
    assert set(trends) == {"decision-v1/CORNERS", "decision-fam-v1/GOALS_HALF"}
    c = trends["decision-v1/CORNERS"]
    assert (c.recent_n, c.baseline_n) == (150, 400) and c.baseline_mean == pytest.approx(-0.02)
    assert trends["decision-fam-v1/GOALS_HALF"].status == dr.INSUFFICIENT


def test_only_the_selections_the_layer_saw_value_in_count() -> None:
    assert dr._value_seen(0.03, -0.5) and not dr._value_seen(0.01, 0.5)
    assert dr._value_seen(None, calibration.EV_RULE) and not dr._value_seen(None, None)


def test_the_report_lists_alerts_worst_first_with_evidence() -> None:
    watch = dr.clv_trend("decision-v1", "OU", alternating(150, -0.035), alternating(400, -0.02))
    cell = dr.assess(ref(), dr.ALL, world(3000, shift=0.10))
    rep = dr.DriftReport(DAY, day_start(DAY + timedelta(days=1)), (cell,), (watch,))
    alerts = rep.alerts()
    assert [a["severity"] for a in alerts] == [dr.DRIFT, dr.WATCH]
    assert alerts[0]["rule"] == "calibration_drift" and alerts[0]["evidence"]["calibrator"]["calibrator_id"] == 7
    assert alerts[0]["subject"] == "OU/poisson/calibrator 7 (identity, cal-logit2-v1)/all"
    assert rep.as_json()["version"] == "drift-v1"


# ── read-only, and nothing that decides depends on it ──────────────────────────────────────────────────────────────

WRITES = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE|ALTER|DROP|CREATE|GRANT|COPY)\b", re.IGNORECASE)


def test_every_statement_is_a_select_and_nothing_commits() -> None:
    from fbi.observability import cost_alerts

    for mod in (dr, cost_alerts):
        for name, sql in vars(mod).items():
            if name.endswith("_SQL") and isinstance(sql, str):
                assert sql.lstrip().upper().startswith("SELECT"), name
                assert not WRITES.search(sql), name
    for path in ("src/fbi/observability/drift.py", "src/fbi/observability/cost_alerts.py", "scripts/ia_alerts.py"):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert ".commit(" not in source and "Jsonb" not in source and "check_alerts(" not in source, path


def test_nothing_that_decides_imports_the_alerts() -> None:
    importers = []
    for path in (ROOT / "src/fbi").rglob("*.py"):
        if "observability" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(n.startswith(("fbi.observability.drift", "fbi.observability.cost_alerts")) for n in names):
                importers.append(str(path))
            if isinstance(node, ast.ImportFrom) and node.module == "fbi.observability" and any(
                    a.name in ("drift", "cost_alerts") for a in node.names):
                importers.append(str(path))
    assert importers == []

"""G-COH in a real database (plan 2026, AD-B05/AD-B09, IA-083/IA-084): the single figure (``forecast-v2``) as the reader makes it from the
stored rows (``market_reader.figures_at``), as the contract of the match serves it to the owner (C-01, private projection), and as decision-v2
reads it at the same moment (``fbi.decision.view``, ``--view-version forecast-v2``) are the same - to the six places, with the same seal,
model and version. Its three page markets are the page's: with the 6-hour window they are ``forecast-v1`` as the writer stored it and the
page serves it; with its own window they are ``forecast-v1-seal``. Nothing is written by the readers, and the replay judged with it is
deterministic."""

# ruff: noqa: F811  (pytest fixtures imported from test_match_forecast are used by name as parameters)
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai.calendar import local_day
from fbi.api.services import forecast as page
from fbi.api.services import match_intelligence as mi
from fbi.decision import engine, replay
from fbi.decision import view as common
from fbi.forecasting import seal
from fbi.forecasting import single_figure as sf
from fbi.forecasting.market_reader import figures_at
from fbi.forecasting.market_view import MAX_MARKET_AGE
from fbi.intel import decision
from fbi.intel.calibration import calibration_state
from fbi.models.quoted import price_quoted_lines
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from tests.integration.conftest import Seed
from tests.integration.test_match_forecast import AT, CUT, World, world  # noqa: F401

from .test_decision_v2_replay import core_scene, writes
from .test_intel import AT as INTEL_AT

pytestmark = pytest.mark.integration

LH, LA, RHO = 1.55, 1.05, -0.06
QUOTED = [("OU", s, Decimal(x)) for x in ("1.5", "3.5") for s in ("Over", "Under")] + [
    ("AH", "Home", Decimal("-1")), ("AH", "Away", Decimal("1")), ("AH", "Home", Decimal("-0.5")), ("AH", "Away", Decimal("0.5"))]


def q(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))


def predict_from_matrix(w: World, fid: int, model: str = "dixon_coles") -> None:
    """What the model's writer stores for the match: the seven fixed rows and the quoted lines, off one matrix (``fbi.predictions``)."""
    m = dc_tau(poisson_matrix(LH, LA), LH, LA, RHO)
    rows = [(mk, s, Decimal(str(line)), p, 0.0, True) for (mk, s, line), p in zip(MARKET_ROWS, from_matrix(m, LH, LA).as_rows(), strict=True)]
    rows += [(lp.market_key, lp.selection, lp.line, lp.p_win, lp.p_push, False) for lp in price_quoted_lines(m, QUOTED)]
    for mk, s, line, p, push, bounded in rows:
        w.db.execute(
            "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, p_lo, p_hi, "
            "p_push, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'fh', %s)",
            (fid, w.version[model], mk, s, line, q(p), q(p), q(max(p - 0.05, 0)) if bounded else None,
             q(min(p + 0.05, 1)) if bounded else None, q(push), CUT))


def scene(w: World, monkeypatch: pytest.MonkeyPatch) -> int:
    """A match with a calibrated result (fresh price), a total whose price is a day old (calibrated by the stable seal only) and the
    rest with no champion."""
    monkeypatch.setenv(seal.SWITCH, "shadow")
    fid = w.fixture()
    predict_from_matrix(w, fid)
    w.champion("1X2", "dixon_coles", "logit2", {"a": 0.0, "b": 0.6, "c": 0.4})
    w.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    w.consensus(fid, "1X2", "0", {"Home": 0.47, "Draw": 0.27, "Away": 0.26}, as_of=AT - timedelta(minutes=40))
    for line, over in (("2.5", 0.52), ("3.5", 0.31), ("1.5", 0.74)):
        w.consensus(fid, "OU", line, {"Over": over, "Under": 1 - over}, as_of=AT - timedelta(hours=26))
    w.write(fid)
    return fid


def stored(db: psycopg.Connection[Any], fid: int, version: str) -> dict[tuple[str, str, Decimal], dict[str, Any]]:
    out = {}
    for r in db.execute("SELECT market_key, selection, line, p, calibration, basis, model_name, calibrator_id FROM models.match_forecasts "
                        "WHERE fixture_id = %s AND version = %s", (fid, version)).fetchall():
        out[sf.key_of(r[0], r[1], r[2])] = {"p": r[3], "calibration": r[4], "basis": r[5], "model": r[6], "calibrator_id": r[7]}
    return out


def test_the_reader_the_contract_and_decision_v2_say_one_single_figure(db: psycopg.Connection[Any], world: World,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    fid = scene(world, monkeypatch)
    cal = calibration_state(db, at=AT)
    before = writes(db)
    fs = figures_at(db, [fid], at=AT, cal=cal)[fid]
    answer = mi.private(db, fid, at=AT).data
    views = common.read(db, [fid], at=AT, cal=cal, version=sf.VERSION)
    assert writes(db) == before, "the readers wrote nothing"

    assert answer is not None and len(fs.figures) >= 30
    served = {sf.key_of(i.market, i.selection, i.line): i for i in answer.single_figure.items}
    assert set(served) == set(fs.figures)
    for k, f in fs.figures.items():
        item, v = served[k], views[(fid, k[0], k[1], k[2])]
        assert item.probability.value == round(f.p, 6) == round(v.p, 6), k
        assert item.reading_id == f.reading_id and item.probability.origin == sf.VERSION == v.version, k
        assert (item.probability.calibration, item.model, item.basis) == (f.label, f.model, f.basis), k
        assert (v.calibration, v.model, v.basis, v.calibrator_id) == (f.calibration, f.model, f.basis, f.calibrator_id), k
    assert {(f.calibration, f.basis) for f in fs.figures.values() if f.market_key == "1X2"} == {("CALIBRATED", "champion")}
    over = fs.get("OU", "Over", "3.5")
    assert over is not None and over.calibration == "CALIBRATED" and over.price_as_of == AT - timedelta(hours=26)
    dc = fs.get("DC", "1X", 0)
    home, draw = fs.get("1X2", "Home", 0), fs.get("1X2", "Draw", 0)
    assert dc and home and draw and dc.p == pytest.approx(home.p + draw.p, abs=1e-12) and dc.source == sf.SOURCE_RESULT
    assert answer.probabilities.items and {p.probability.origin for p in answer.probabilities.items} == {"forecast-v1"}


def test_its_three_page_markets_are_forecast_v1_with_its_window_and_the_stable_seal_with_its_own(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = scene(world, monkeypatch)
    cal = calibration_state(db, at=AT)
    v1 = stored(db, fid, "forecast-v1")
    v1_seal = stored(db, fid, seal.SHADOW_VERSION)
    assert len(v1) == len(v1_seal) == 7
    body = page.match_forecast(db, fid, preview=True, at=AT).data
    assert body is not None
    served = {sf.key_of(m.market, o.selection, m.line): o.probability for m in body.forecast.data for o in m.outcomes}
    for window, rows in ((MAX_MARKET_AGE, v1), (sf.MARKET_AGE, v1_seal)):
        fs = figures_at(db, [fid], at=AT, cal=cal, max_age=window)[fid]
        for k, r in rows.items():
            f = fs.figures[k]
            assert q(f.p) == r["p"], (window, k)
            assert (f.calibration, f.basis, f.model, f.calibrator_id) == (r["calibration"], r["basis"], r["model"], r["calibrator_id"]), k
            if rows is v1:
                assert q(f.p) == served[k], "the page serves what the writer stored"
    assert {r["basis"] for k, r in v1.items() if k[0] == "OU"} == {"needs_price"}, "a day-old price: forecast-v1 says Sin calibrar"
    assert {r["basis"] for k, r in v1_seal.items() if k[0] == "OU"} == {"champion"}, "the stable seal calibrates with it"


def test_decision_v2_judges_the_single_figure_writes_nothing_and_is_deterministic(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, a, b = core_scene(db, seed)
    for fid in (a, b):  # the other side of total goals at 2.5 and at 3.5, so that the view has the whole set
        for line, p in (("2.5", 0.40), ("3.5", 0.42)):
            db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, calibrator_id, market_key, selection, line, p_raw, "
                       "p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, %s, 'OU', 'Under', %s, %s, %s, %s, %s, "
                       "'fh', %s) ON CONFLICT DO NOTHING",
                       (fid, seed.model_version_id, w.model_calibrator, Decimal(line), p, p, p - 0.05, p + 0.05, INTEL_AT - timedelta(hours=3)))
    decision.decide(db, at=INTEL_AT)
    day = local_day(INTEL_AT)
    before = writes(db)
    out = replay.replay_day(db, day=day, probability=engine.COMMON, view_version=sf.VERSION)
    again = replay.replay_day(db, day=day, probability=engine.COMMON, view_version=sf.VERSION)
    v1 = replay.replay_day(db, day=day, probability=engine.COMMON)
    assert writes(db) == before, "the replay wrote nothing"
    assert json.dumps(out, default=str, sort_keys=True) == json.dumps(again, default=str, sort_keys=True), "and it is deterministic"
    assert out["inputs"]["view_version"] == sf.VERSION and v1["inputs"]["view_version"] == "forecast-v1"
    p = out["probability"]
    assert set(p["versions"]) == {sf.VERSION}
    assert p["judged_with_common"] >= v1["probability"]["judged_with_common"], "the single figure covers at least what forecast-v1 covers"
    with pytest.raises(ValueError, match="view_version"):
        replay.replay_day(db, day=day, probability=engine.COMMON, view_version="forecast-v9")


def test_the_production_report_finds_no_difference_where_the_single_figure_must_reproduce_the_page(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import ia_single_figure as report

    scene(world, monkeypatch)
    before = writes(db)
    out = report.check(db, at=AT, hours=72, limit=50)
    assert writes(db) == before
    assert out["fixtures"] == 1 and out["figures"]["figures"] >= 30
    for name in ("forecast-v1 (6 h)", "forecast-v1-seal (4 d)"):
        r = out["replay"][name]
        assert r["all"]["n"] == 7 and r["all"]["over_tolerance"] == 0 and r["all"]["max_pp"] == 0, (name, r)
    page_now = out["page"]
    assert page_now["all"]["n"] == 7
    assert page_now["causes_over_tolerance"] == {"different_seal": 2}, "the page's total is Sin calibrar (a day-old price), the figure is not"
    assert out["coherence"]["sets"] == 1 and out["texts"]["measured"] is False
    assert json.dumps(out, default=str)

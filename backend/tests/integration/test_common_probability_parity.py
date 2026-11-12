"""ONE number per selection, in a real database (plan Intelligence 2026, INT-A03, IA-053): what the Match Center's writer stores
(``match_forecast``, ``forecast-v1``), what the page of the match serves from it (``fbi.api.services.forecast``), what decision-v2 reads at the
same moment (``fbi.decision.view``) and the number its stages judge with ``--probability common`` (``view.judged``) are the same - not close,
the same to the six places the table keeps - with the same model, seal and version, and every market adds up to one. With a fresh price the
number is calibrated; with a stale one it is the model's own, «Sin calibrar», and decision-v2 then has no calibrated number to judge the value
with. Nothing is written by the readers."""

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
from fbi.decision import engine, replay
from fbi.decision import view as common
from fbi.decision.families import CORE, Candidate
from fbi.intel import decision
from fbi.intel.calibration import calibration_state
from tests.integration.conftest import Seed
from tests.integration.test_match_forecast import AT, KO, SHEET, World, world  # noqa: F401

from .test_decision_v2_replay import core_scene, writes
from .test_intel import AT as INTEL_AT

pytestmark = pytest.mark.integration

SIX = Decimal("0.000001")


def q(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, 6)))


def candidate(fid: int, market: str, selection: str, line: str) -> Candidate:
    """A core candidate of the selection, priced and fresh: what the replay would put before the engine (only its probability is judged)."""
    key: decision.Key = (fid, market, selection, Decimal(line).quantize(decision.LINE_Q))
    row = {"pick_id": 1, "fixture_id": fid, "market_key": market, "selection": selection, "line": Decimal(line), "model_name": "dixon_coles",
           "model_version_id": None, "p_model": 0.5, "p_push": 0.0, "p_low": 0.45, "p_high": 0.55, "kickoff_at": KO, "status_short": "NS",
           "status_group": "scheduled", "data_cutoff_ts": AT - timedelta(hours=1), "best_odds": 2.0, "p_fair": 0.48, "best_bookmaker_id": 1,
           "n_bookmakers": 6, "overround": 0.05, "dispersion": 0.01, "price_at": AT - timedelta(minutes=20)}
    return Candidate(CORE, key, {"dixon_coles": row})


def readers(db: psycopg.Connection[Any], world: World, fid: int) -> tuple[dict[tuple[str, str], dict[str, Any]], ...]:
    """The four readings of the match at ``AT``, as (market, selection) -> what each says."""
    stored = {(r["market_key"], r["selection"]): {"p": r["p"], "p_model": r["p_model"], "model": r["model_name"], "calibration": r["calibration"],
                                                  "basis": r["basis"], "calibrator_id": r["calibrator_id"]}
              for r in world.stored(fid)}
    body = page.match_forecast(db, fid, preview=True, at=AT).data
    assert body is not None and body.forecast.data
    served = {(m.market, o.selection): {"p": o.probability, "p_model": o.model_probability, "model": m.model, "calibration": m.calibration,
                                        "basis": m.basis} for m in body.forecast.data for o in m.outcomes}
    cal = calibration_state(db, at=AT)
    views = common.read(db, [fid], at=AT, cal=cal)
    read = {(k[1], k[2]): {"p": q(v.p), "p_model": q(v.p_model), "model": v.model, "calibration": v.calibration, "basis": v.basis,
                           "calibrator_id": v.calibrator_id} for k, v in views.items()}
    w = decision.read_world(db, [fid], at=AT)
    cands = [candidate(fid, m, s, line) for (m, line), sheet in SHEET.items() for s in sheet]
    decided = engine.decide_all(w, common.judged(cands, views, family=CORE.name))
    judged = {(d.key[1], d.key[2]): {"p": q(d.prediction.p_cal), "p_model": q(d.prediction.p_model), "model": d.prediction.model,
                                     "calibration": d.prediction.calibration, "basis": d.prediction.basis,
                                     "calibrator_id": d.prediction.calibrator_id, "source": d.prediction.source,
                                     "version": d.prediction.version} for d in decided}
    return stored, served, read, judged


def adds_up(readings: dict[tuple[str, str], dict[str, Any]], *, tolerance: Decimal) -> None:
    for market in {m for m, _ in readings}:
        total = sum((r["p"] for (m, _), r in readings.items() if m == market), Decimal(0))
        assert abs(total - 1) <= tolerance, (market, total)


def test_with_a_fresh_price_the_writer_the_page_and_decision_v2_say_one_calibrated_number(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    calibrator = world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(minutes=40))
    world.write(fid)

    before = writes(db)
    stored, served, read, judged = readers(db, world, fid)
    assert writes(db) == before, "the readers wrote nothing"
    assert len(stored) == 7 and set(stored) == set(served) == set(read) == set(judged), "every outcome of 1X2, total goals at 2.5 and BTTS"
    for k, s in stored.items():
        assert served[k]["p"] == s["p"] == read[k]["p"], k
        assert served[k]["p_model"] == s["p_model"] == read[k]["p_model"], k
        assert (served[k]["model"], served[k]["calibration"], served[k]["basis"]) == (s["model"], s["calibration"], s["basis"]), k
        assert (read[k]["model"], read[k]["calibration"], read[k]["basis"], read[k]["calibrator_id"]) == (
            s["model"], s["calibration"], s["basis"], s["calibrator_id"]), k
        j = judged[k]
        assert (j["source"], j["version"], j["model"], j["calibration"], j["basis"]) == (
            engine.COMMON, "forecast-v1", s["model"], s["calibration"], s["basis"]), k
        if s["calibration"] == "CALIBRATED":
            assert (j["p"], j["calibrator_id"]) == (s["p"], calibrator), "the number judged is the number stored"
        else:
            assert j["p"] is None and j["p_model"] == s["p_model"], "«Sin calibrar»: the model's own number, no calibrated one to judge"
    assert {s["calibration"] for (m, _), s in stored.items() if m == "OU"} == {"CALIBRATED"}
    assert {s["calibration"] for (m, _), s in stored.items() if m != "OU"} == {"UNCALIBRATED"}, "no champion for 1X2 nor BTTS"
    adds_up(stored, tolerance=2 * SIX)
    adds_up(read, tolerance=2 * SIX)
    adds_up({k: v for k, v in judged.items() if k[0] == "OU"}, tolerance=2 * SIX)


def test_with_a_stale_price_every_reader_says_sin_calibrar_with_the_same_reason(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(hours=7))
    world.write(fid)
    stored, served, read, judged = readers(db, world, fid)
    ou = {k: v for k, v in judged.items() if k[0] == "OU"}
    assert set(stored) == set(served) == set(read) == set(ou) == {("OU", "Over"), ("OU", "Under")}
    for k, s in stored.items():
        assert (s["calibration"], s["basis"]) == (served[k]["calibration"], served[k]["basis"]) == (read[k]["calibration"], read[k]["basis"]) == (
            "UNCALIBRATED", "needs_price")
        assert s["p"] == s["p_model"] == served[k]["p"] == read[k]["p"] == ou[k]["p_model"]
        assert (ou[k]["source"], ou[k]["calibration"], ou[k]["basis"], ou[k]["p"]) == (engine.COMMON, "UNCALIBRATED", "needs_price", None)
    others = {k: v for k, v in judged.items() if k[0] != "OU"}
    assert others and all(v["source"] == engine.OWN for v in others.values()), "no reading of 1X2 nor BTTS: they keep their own number"
    adds_up(stored, tolerance=2 * SIX)


def test_the_replay_judged_with_the_view_reads_it_writes_nothing_and_leaves_the_default_as_it_was(db: psycopg.Connection[Any],
                                                                                                   seed: Seed) -> None:
    w, a, b = core_scene(db, seed)
    for fid in (a, b):  # the other side of total goals at 2.5, so that the view has the whole market (an identity champion: the same number)
        db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, calibrator_id, market_key, selection, line, p_raw, p_calibrated, "
                   "p_lo, p_hi, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, %s, 'OU', 'Under', 2.5, 0.40, 0.40, 0.35, 0.45, 'fh', %s)",
                   (fid, seed.model_version_id, w.model_calibrator, INTEL_AT - timedelta(hours=3)))
    decision.decide(db, at=INTEL_AT)
    day = local_day(INTEL_AT)
    plain = replay.replay_day(db, day=day)

    before = writes(db)
    out = replay.replay_day(db, day=day, probability=engine.COMMON)
    again = replay.replay_day(db, day=day, probability=engine.COMMON)
    assert writes(db) == before, "the replay wrote nothing"
    assert json.dumps(out, default=str, sort_keys=True) == json.dumps(again, default=str, sort_keys=True), "and it is deterministic"

    assert plain["inputs"]["probability"] == engine.OWN and "probability" not in plain and plain["agreement"]["rate"] == 1.0
    assert out["inputs"]["probability"] == engine.COMMON and out["agreement"] == plain["agreement"]
    p = out["probability"]
    assert (p["decisions"], p["judged_with_common"]) == (6, 2), "Over 2.5 of each match: the only selections whose whole market the view read"
    assert p["seal"] == {"CALIBRATED (champion)": 2} and p["versions"] == {"forecast-v1": 2}
    assert p["kept_own"] == {"no_reading": 2, "not_in_view": 2}, "BTTS and 1X2 without a whole market; the lines at 3.5 are not in the view"
    assert (p["against_own"]["rows"], p["against_own"]["changed"]) == (6, 0), "an identity champion on a market that adds up to one: one number"

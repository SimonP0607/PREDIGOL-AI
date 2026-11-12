"""decision-v2 judged with the common probability view (plan Intelligence 2026, INT-A03, IA-053), without a database: by default nothing
changes; with the view the stages judge the view's number - its model, its interval, its seal and its version - and a view «Sin calibrar»
gives no calibrated probability to judge the value with; a selection the view does not cover keeps its own probability and says why; the
replay says what the view changed against the pick's own probability; and the number the Match Center stores, the one decision-v2 reads and
the one its stages judge are the same for the same input, each market adding up to one. The same parity against a real database, through the
writer and the page's reader, is in tests/integration/test_common_probability_parity.py."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import psycopg
import pytest
from scripts import ia_decision_v2 as cli

from fbi.decision import engine, replay
from fbi.decision import view as common
from fbi.decision.families import CORE, FORECAST_FAMILIES, Candidate
from fbi.forecasting import match_forecast as mf
from fbi.forecasting.market_view import (
    BASIS_CHAMPION,
    BASIS_NEEDS_PRICE,
    BASIS_NO_CHAMPION,
    BASIS_NOT_APPLICABLE,
    MARKETS,
    Row,
    Source,
    forecast_market,
)
from fbi.intel import decision
from fbi.intel.calibration import CalibrationState, Calibrator

from .test_decision_v2_engine import AT, KEY, MODEL, core, pick, world

SELECTIONS = MARKETS[("1X2", Decimal(0))]
CUT = AT - timedelta(hours=2)


def view_of(p: float = 0.58, *, model: str = MODEL, calibrated: bool = True, basis: str | None = None, low: float | None = 0.53,
            high: float | None = 0.63, cutoff: Any = CUT, calibrator: int | None = 5) -> engine.CommonView:
    return engine.CommonView(p, 0.55, model, "CALIBRATED" if calibrated else "UNCALIBRATED", basis or ("champion" if calibrated else "needs_price"),
                             calibrator if calibrated else None, low, high, cutoff, AT - timedelta(minutes=20) if calibrated else None,
                             "forecast-v1", 3)


def judged(p: dict[str, Any], v: engine.CommonView | None, key: decision.Key = KEY) -> Candidate:
    [c] = common.judged([core({MODEL: p}, key)], {} if v is None else {key: v}, family=CORE.name)
    return c


# -- by default nothing changes ----------------------------------------------------------------------------------------------------------

def test_by_default_the_stages_judge_the_picks_own_probability_and_say_so() -> None:
    d = engine.decide(world(), core({MODEL: pick()}))
    p = d.prediction
    assert (p.source, p.calibration, p.basis, p.version, p.missing) == (engine.OWN, None, None, None, None)
    assert p.p_cal == pytest.approx(0.56) and d.state == "RECOMMENDED"
    assert d.as_json()["prediction"]["source"] == "own" and "probability" not in d.verdict("model").data


# -- the view's number, judged -------------------------------------------------------------------------------------------------------------

def test_a_calibrated_view_is_the_number_every_stage_judges() -> None:
    w = world()
    d = engine.decide(w, judged(pick(p=0.56), view_of(0.58)))
    p = d.prediction
    assert (p.source, p.calibration, p.basis, p.version, p.model_version_id) == (engine.COMMON, "CALIBRATED", "champion", "forecast-v1", 3)
    assert (p.p_model, p.p_cal, p.interval, p.calibrator_id, p.calibrator_role) == (0.55, 0.58, (0.53, 0.63), 5, "CHAMPION")
    assert d.value.ev_cal == pytest.approx(decision.ev_of(0.58, 2.0)) and d.value.edge_cal == pytest.approx(0.58 - 0.48)
    assert d.verdict("calibration").ok is True and d.verdict("calibration").why == "cifra única calibrada: calibrador #5 (champion), forecast-v1"
    assert d.verdict("model").why.startswith(f"{MODEL}: p 0.550 (cifra única forecast-v1)") and d.verdict("model").data["probability"] == "common"
    js = d.as_json()["prediction"]
    assert (js["source"], js["calibration"], js["version"]) == ("common", "CALIBRATED", "forecast-v1")


def test_a_view_without_a_fresh_price_is_sin_calibrar_and_gives_no_calibrated_value() -> None:
    d = engine.decide(world(), judged(pick(), view_of(0.58, calibrated=False, basis=BASIS_NEEDS_PRICE)))
    assert (d.prediction.calibration, d.prediction.basis, d.prediction.p_cal, d.prediction.calibrator_id) == ("UNCALIBRATED", "needs_price", None, None)
    assert d.verdict("calibration").why == "cifra única «Sin calibrar» (sin precio fresco): no aprueba"
    assert {"not_calibrated", "ev_unknown"} <= set(d.codes) and d.value.ev_cal is None and d.state == "ABSTAIN"
    assert d.value.ev_raw == pytest.approx(decision.ev_of(0.55, 2.0)), "the raw value is the model's own number, said as raw"


def test_the_view_can_judge_another_model_than_the_picks_and_its_slot_is_the_one_read() -> None:
    w = world(model="elo_ologit", edge=False)  # the slot (1X2, elo_ologit) has a champion and no validated edge
    d = engine.decide(w, judged(pick(), view_of(0.58, model="elo_ologit")))
    assert d.prediction.model == "elo_ologit" and d.verdict("model").why.startswith("elo_ologit: p 0.550")
    assert "edge_not_validated" in d.codes, "the edge gate of the view's model, not the pick's"


def test_the_views_interval_and_cutoff_are_the_ones_judged() -> None:
    wide = engine.decide(world(), judged(pick(width=0.10), view_of(0.58, low=0.40, high=0.70)))
    assert "risk" in wide.codes and wide.prediction.interval == (0.40, 0.70)
    old = engine.decide(world(), judged(pick(forecast_age=timedelta(hours=2)), view_of(0.58, cutoff=AT - timedelta(hours=80))))
    assert old.state == "REJECTED" and old.reason == "data", "the forecast's age is the view's"
    none = engine.decide(world(), judged(pick(width=0.10), view_of(0.58, low=None, high=None)))
    assert none.reason == "model" and none.state == "REJECTED", "the core asks for an interval, the view's too"


def test_a_selection_the_view_does_not_cover_keeps_its_own_probability_and_says_why() -> None:
    plain = engine.decide(world(), core({MODEL: pick()}))
    kept = engine.decide(world(), judged(pick(), None))
    assert kept.prediction.source == engine.OWN and kept.prediction.missing == common.NO_READING
    assert replace(kept, prediction=replace(kept.prediction, missing=None)) == plain, "judged exactly as the default"
    ah = (77, "AH", "Home", Decimal("-0.50"))
    assert engine.decide(world(market="AH"), judged(pick(market="AH"), None, ah)).prediction.missing == common.NOT_IN_VIEW
    assert common.covered((77, "OU", "Over", Decimal("2.50"))) and not common.covered((77, "OU", "Over", Decimal("1.50")))


def test_only_the_cores_candidates_are_judged_and_nothing_given_is_changed() -> None:
    row = pick()
    c = core({MODEL: row, "elo": dict(row)})
    fam = Candidate(FORECAST_FAMILIES[0], (77, "corners_ft_ou", "Over", Decimal("9.50")), {MODEL: dict(row)}, model_hint=MODEL)
    out = common.judged([c, fam], {KEY: view_of()}, family=CORE.name)
    assert out[1] is fam and all(r["probability_source"] == engine.COMMON and r["common_p"] == 0.58 for r in out[0].models.values())
    assert "probability_source" not in row and c.models[MODEL] is row


def test_the_reasons_of_sin_calibrar_are_the_views_own() -> None:
    assert set(engine.VIEW_BASIS) == {BASIS_NO_CHAMPION, BASIS_NEEDS_PRICE, BASIS_NOT_APPLICABLE} and BASIS_CHAMPION not in engine.VIEW_BASIS


# -- one number: stored, read, judged ------------------------------------------------------------------------------------------------------

class Captured:
    """A connection whose cursor keeps what the writer would insert (``match_forecast.store``)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.rowcount = 1

    def cursor(self) -> Captured:
        return self

    def __enter__(self) -> Captured:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        assert sql == mf.INSERT_SQL
        self.rows.append(params)


def sources(ps: tuple[float, ...] = (0.50, 0.30, 0.20)) -> dict[str, list[Row]]:
    return {MODEL: [Row(s, Source(MODEL, 3, CUT, "h", p, p - 0.05, p + 0.05, 0.0)) for s, p in zip(SELECTIONS, ps, strict=True)]}


def champion() -> CalibrationState:
    cal = Calibrator("1X2", MODEL, "logit2", {"a": 0.1, "b": 0.8, "c": 0.3}, id=5, role="CHAMPION")
    return CalibrationState(champions={("1X2", MODEL): cal}, best={("1X2", MODEL): cal}, wf={("1X2", MODEL): {"logloss_cal": 0.6}},
                            edge={("1X2", MODEL): True})


@pytest.mark.parametrize("fresh", [True, False])
def test_the_stored_forecast_the_view_decision_v2_reads_and_the_number_it_judges_are_one(fresh: bool) -> None:
    market = {s: (p, AT - timedelta(minutes=30)) for s, p in zip(SELECTIONS, (0.45, 0.30, 0.25), strict=True)} if fresh else {}
    f = forecast_market(77, "1X2", Decimal(0), sources(), champion(), market)
    assert f is not None and f.calibration == ("CALIBRATED" if fresh else "UNCALIBRATED")
    conn = Captured()
    mf.store(cast(psycopg.Connection[Any], conn), f, at=AT, code_version="test")
    stored = {r["selection"]: r for r in conn.rows}
    views = common.readings({(77, "1X2", Decimal(0)): f})
    w = replace(world(), cal=champion())
    decided = {d.key[2]: d for d in engine.decide_all(w, common.judged(
        [core({MODEL: pick(selection=s)}, (77, "1X2", s, Decimal("0.00"))) for s in SELECTIONS], views, family=CORE.name))}
    for s in SELECTIONS:
        v, row, d = views[(77, "1X2", s, Decimal("0.00"))], stored[s], decided[s]
        assert row["p"] == Decimal(str(round(v.p, 6))) and row["p_model"] == Decimal(str(round(v.p_model, 6)))
        assert (row["p_lo"], row["p_hi"]) == (Decimal(str(round(v.low or 0, 6))), Decimal(str(round(v.high or 0, 6))))
        assert (row["model_name"], row["model_version_id"], row["calibration"], row["calibrator_id"], row["basis"]) == (
            v.model, v.model_version_id, v.calibration, v.calibrator_id, v.basis)
        assert (d.prediction.source, d.prediction.calibration, d.prediction.version) == (engine.COMMON, v.calibration, mf.VERSION)
        assert d.prediction.p_cal == (v.p if fresh else None) and d.prediction.p_model == v.p_model
    assert abs(sum(v.p for k, v in views.items()) - 1) < 1e-9, "the market adds up to one"
    assert abs(sum(r["p"] for r in conn.rows) - 1) <= Decimal("0.000002"), "and so does what is stored, to its six places"
    if fresh:
        assert abs(sum(d.prediction.p_cal or 0 for d in decided.values()) - 1) < 1e-9, "the numbers judged add up to one"


# -- the replay's report and the command ---------------------------------------------------------------------------------------------------

def against(i: int, d: engine.Decision2 | None, o: engine.Decision2 | None, family: str = "core") -> replay.Against:
    return {"id": i, "known_at": AT, "fixture_id": 77, "market_key": "1X2", "selection": "Home", "line": Decimal("0")}, family, d, o


def test_the_report_says_what_the_view_changed_and_at_which_stage() -> None:
    w = world()
    own = engine.decide(w, core({MODEL: pick()}))
    same = engine.decide(w, judged(pick(), view_of(0.5605)))
    lower = engine.decide(w, judged(pick(), view_of(0.49)))  # the view's number is below the value threshold
    sealed = engine.decide(w, judged(pick(), view_of(0.58, calibrated=False)))
    kept = engine.decide(w, judged(pick(), None))
    out = replay.probability_summary([against(1, same, own), against(2, lower, own), against(3, sealed, own), against(4, kept, own),
                                      against(5, own, None, family="CORNERS"), against(6, None, own)])
    assert (out["decisions"], out["judged_with_common"]) == (5, 3)
    assert out["seal"] == {"CALIBRATED (champion)": 2, "UNCALIBRATED (needs_price)": 1} and out["versions"] == {"forecast-v1": 3}
    assert out["kept_own"] == {"family": 1, "no_reading": 1}
    a = out["against_own"]
    assert (a["rows"], a["same_state"], a["changed"], a["calibrated_lost"]) == (4, 2, 2, 1)
    assert a["transitions"] == {"RECOMMENDED -> ABSTAIN": 1, "RECOMMENDED -> REJECTED": 1}
    assert a["by_stage"] == {"calibration": 1, "value": 1} and a["p_cal_gap_pp"]["max"] == pytest.approx(7.0)
    assert [e["decision_id"] for e in a["examples"]] == [2, 3] and a["examples"][0]["stage"] == "value"


def test_the_replay_refuses_an_unknown_probability() -> None:
    with pytest.raises(ValueError, match="probability must be one of"):
        replay.replay_day(cast(psycopg.Connection[Any], None), day=AT.date(), probability="modelo")


def test_the_command_takes_the_probability_and_prints_what_it_changed() -> None:
    assert cli.build_parser().parse_args(["replay", "--day", "2026-11-10"]).probability == engine.OWN, "the default is the pick's own"
    assert cli.build_parser().parse_args(["replay", "--day", "2026-11-10", "--probability", "common"]).probability == engine.COMMON
    w = world()
    own = engine.decide(w, core({MODEL: pick()}))
    out = replay.probability_summary([against(1, engine.decide(w, judged(pick(), view_of(0.49))), own)])
    text = "\n".join(cli.render_probability(out))
    assert "probability: common view on 1/1 decisions" in text and "1 changed state {'RECOMMENDED -> REJECTED': 1}" in text
    assert "own RECOMMENDED (approved) -> common REJECTED (ev_cal_below) - stage value" in text

"""IA-095 (AD-B07): count-cal-v1, the calibrator of the ladder of lines of corners and cards, and the walk-forward of its protocol.

* the calibrated distribution is a distribution and its ladder is coherent; the identity is the model; a known miscalibration is found;
* with few matches the calibrator stays the identity, and the referee's multiplier stays near one;
* the walk never uses a match whose result was not known: what happens later does not move an earlier block;
* the verdict follows the protocol's three rules, and INSUFICIENTE below its sample;
* the probabilities agree with the settlement of the counts (``fbi.picks.count_settlement``), and a missing count settles as None.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from fbi.countcal import calibrator as cc
from fbi.countcal import lab
from fbi.countcal import walkforward as wf
from fbi.families import referee as fref
from fbi.families.counts import nb_pmf, normalised
from fbi.families.fit import Match, fit_family
from fbi.market.rules import RULES_BY_MEASURE
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status
from fbi.research import protocol


def _pmf(mean: float = 9.8, phi: float = 0.05) -> Any:
    return normalised(nb_pmf(mean, phi, 60))


# ── the calibrator ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_calibrated_count_is_a_distribution_with_a_coherent_ladder() -> None:
    pmf = _pmf()
    for params in (cc.Params(1.3, 0.25, 900), cc.Params(0.6, -0.4, 900), cc.IDENTITY):
        out = cc.calibrated_pmf(pmf, params)
        assert out.sum() == pytest.approx(1.0, abs=1e-12) and (out >= 0).all()
        ladder = cc.ladder(out, cc.LADDERS["corners_total"])
        assert (np.diff(ladder) < 0).all(), "over 8.5 is always above over 9.5"
        raw = cc.ladder(pmf, cc.LADDERS["corners_total"])
        assert np.allclose(ladder, cc.transform(raw, params), atol=1e-12), "every line reads the same calibrated distribution"


def test_the_identity_is_the_model() -> None:
    pmf = _pmf()
    assert np.allclose(cc.calibrated_pmf(pmf, cc.IDENTITY), pmf, atol=1e-12)
    assert cc.over(pmf, 9.5) == pytest.approx(float(pmf[10:].sum()))


def test_a_known_miscalibration_is_found_and_a_calibrated_model_is_left_alone() -> None:
    rng = np.random.default_rng(7)
    p = rng.uniform(0.15, 0.85, 20_000)
    y_bad = (rng.uniform(size=p.size) < cc.sigmoid(1.3 * cc.logit(p) + 0.2)).astype(float)
    fitted = cc.fit(p, y_bad, n_matches=4000)
    assert fitted.a == pytest.approx(1.3, abs=0.06) and fitted.b == pytest.approx(0.2, abs=0.05)
    y_good = (rng.uniform(size=p.size) < p).astype(float)
    calm = cc.fit(p, y_good, n_matches=4000)
    assert calm.a == pytest.approx(1.0, abs=0.06) and calm.b == pytest.approx(0.0, abs=0.04)


def test_with_few_matches_the_calibrator_is_the_identity_and_the_ridge_pulls_towards_it() -> None:
    p, y = np.full(400, 0.5), np.ones(400)
    small = cc.fit(p, y, n_matches=cc.MIN_FIT - 1)
    assert small.identity and small.n_matches == cc.MIN_FIT - 1
    rng = np.random.default_rng(3)
    p = rng.uniform(0.3, 0.7, 3000)
    y = (rng.uniform(size=p.size) < cc.sigmoid(cc.logit(p) + 0.5)).astype(float)
    loose = cc.fit(p, y, n_matches=600, ridge=0.0)
    tight = cc.fit(p, y, n_matches=600, ridge=5000.0)
    assert abs(tight.b) < abs(loose.b) and abs(tight.a - 1.0) <= abs(loose.a - 1.0) + 1e-9
    assert cc.A_BOUNDS[0] <= loose.a <= cc.A_BOUNDS[1]


def test_a_ladder_is_made_of_half_lines() -> None:
    with pytest.raises(ValueError):
        cc.ladder(_pmf(), (9.0,))


def test_rps_and_ece_are_the_textbook_ones() -> None:
    pmf = np.array([0.0, 1.0, 0.0])
    assert cc.rps(pmf, 1) == pytest.approx(0.0)
    assert cc.rps(pmf, 0) == pytest.approx(1.0)
    p, y = np.array([0.7, 0.7, 0.7, 0.7]), np.array([1.0, 1.0, 0.0, 1.0])
    assert cc.ece(p, y) == pytest.approx(abs(0.7 - 0.75))


# ── the referee ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _league(n_teams: int = 12, rounds: int = 30, start: datetime = datetime(2024, 1, 6, 15, tzinfo=UTC), seed: int = 1,
            referee_of: Any = None, mean: float = 2.2) -> list[Match]:
    rng = np.random.default_rng(seed)
    out, fid = [], 0
    for r in range(rounds):
        perm = rng.permutation(n_teams)
        for i in range(0, n_teams, 2):
            fid += 1
            ref = None if referee_of is None else referee_of(fid)
            out.append(Match(fid, start + timedelta(days=7 * r), 100 + int(perm[i]), 100 + int(perm[i + 1]),
                             int(rng.poisson(mean)), int(rng.poisson(mean * 0.9)), False, ref))
    return out


def test_a_referee_with_few_matches_stays_near_one() -> None:
    """The protocol's test: with 10 known matches or fewer, the multiplier is within 0.25 of 1, even for a referee whose matches had
    no card at all or twice the cards they had (KAPPA = 150 cards of «no effect»: (150 + 2E) / (150 + E) <= 1.22 for E <= 42)."""
    train = _league(referee_of=lambda fid: 1 if fid <= 10 else (2 if fid <= 15 else None))
    train = [dataclasses.replace(m, home=0, away=0) if m.referee_id == 1 else
             (dataclasses.replace(m, home=2 * m.home, away=2 * m.away) if m.referee_id == 2 else m) for m in train]
    fitted = fit_family(train, measure="cards_lines_ft", at=datetime(2025, 1, 1, tzinfo=UTC), xi=0.0019, penalty=32.0,
                        dispersion=None)
    factors = fref.factors(train, fitted)
    assert set(factors) == {1, 2}
    assert all(abs(f - 1.0) <= wf.REFEREE_BAND for f in factors.values()), factors
    check = wf.referee_check([(10, factors[1]), (5, factors[2]), (200, 1.6)])
    assert check["few_matches"] == 2 and check["few_within_band"] == 1.0 and check["all_max_deviation"] == pytest.approx(0.6)


# ── the walk ─────────────────────────────────────────────────────────────────────────────────────────────────────────

WARMUP = datetime(2024, 6, 3, tzinfo=UTC)
START = WARMUP + timedelta(days=5 * wf.STEP_DAYS)
END = START + timedelta(days=3 * wf.STEP_DAYS)


def _corners(seed: int = 5) -> dict[int, list[Match]]:
    leagues = {}
    for c in range(1, 9):
        leagues[c] = [dataclasses.replace(m, fixture_id=c * 100_000 + m.fixture_id, home_id=c * 1000 + m.home_id,
                                          away_id=c * 1000 + m.away_id)
                      for m in _league(n_teams=20, rounds=125, start=datetime(2023, 1, 7, 15, tzinfo=UTC), seed=seed + c, mean=5.0)]
    return leagues


@pytest.fixture(scope="module")
def walked() -> tuple[wf.Walk, dict[int, list[Match]]]:
    data = _corners()
    walk = wf.predict(data, measure="corners_ft", warmup=WARMUP, end=END)
    wf.calibrate(walk, start=START)
    return walk, data


def test_the_walk_states_out_of_sample_and_scores_only_calibrated_blocks(walked: tuple[wf.Walk, dict[int, list[Match]]]) -> None:
    walk, _ = walked
    assert walk.starts[0] == WARMUP and len(walk.blocks) == len(walk.starts)
    for p in walk.preds:
        assert walk.starts[p.block] <= p.kickoff_at < walk.starts[p.block] + timedelta(days=wf.STEP_DAYS)
    assert not walk.blocks[0].dispersed, "the first block has nothing before it"
    scored = [i for i, b in enumerate(walk.blocks) if b.scored]
    assert scored and all(walk.starts[i] > WARMUP for i in scored)
    for i in scored:
        assert all(c.n_matches >= cc.MIN_FIT for c in walk.blocks[i].calibrators.values())


def test_what_happens_later_never_moves_an_earlier_block(walked: tuple[wf.Walk, dict[int, list[Match]]]) -> None:
    walk, data = walked
    last = walk.starts[-1]
    changed = {c: [dataclasses.replace(m, home=m.home + 9) if m.kickoff_at >= last else m for m in ms] for c, ms in data.items()}
    other = wf.predict(changed, measure="corners_ft", warmup=WARMUP, end=END)
    wf.calibrate(other, start=START)
    for b in range(len(walk.starts)):
        assert other.blocks[b].calibrators == walk.blocks[b].calibrators, b
        assert other.blocks[b].model == walk.blocks[b].model, b
    early = [(p.fixture_id, p.mu_home) for p in walk.preds if p.kickoff_at < last]
    assert early == [(p.fixture_id, p.mu_home) for p in other.preds if p.kickoff_at < last]


def test_a_current_fit_ends_with_a_block_at_the_moment() -> None:
    at = START + timedelta(days=60)
    params, n = wf.fit_current(_corners(), measure="corners_ft", at=at)
    assert set(params) == {"corners_total", "corners_side"} and n >= cc.MIN_FIT
    assert all(p.n_matches >= cc.MIN_FIT for p in params.values())


def test_the_score_of_a_family_carries_its_sample_and_verdict(walked: tuple[wf.Walk, dict[int, list[Match]]]) -> None:
    walk, _ = walked
    market = [wf.MarketPrice(p.fixture_id, "CORNERS_OU", 9.5, 0.5, 4) for p in walk.preds[-300:]]
    s = wf.score(walk, "corners_total", start=START, seed=1, market=market)
    assert s["matches"] > 0 and s["verdict"] in wf.VERDICTS
    assert s["verdict"] == wf.INSUFFICIENT, "three blocks of small leagues are below 1.500 matches in 60 days"
    assert s["market"]["rows"] > 0 and s["cal_minus_raw"]["n"] == s["units"]
    side = wf.score(walk, "corners_side", start=START, seed=1)
    assert side["units"] == 2 * side["matches"]


# ── the verdict ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _summary(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"matches": 4000, "days": 200, "cal_minus_raw": {"high": 0.0004}, "cal_minus_base": {"high": -0.002},
                            "ece": {"cal": {"9.5": {"n": 900, "ece": 0.012}, "13.5": {"n": 150, "ece": 0.08}}}}
    base.update(over)
    return base


def test_the_verdict_follows_the_three_rules_of_the_protocol() -> None:
    assert wf.verdict(_summary())[0] == wf.VALIDATED, "a line with fewer than 200 matches is not judged by its ECE"
    assert wf.verdict(_summary(matches=1499))[0] == wf.INSUFFICIENT
    assert wf.verdict(_summary(days=59))[0] == wf.INSUFFICIENT
    assert wf.verdict(_summary(cal_minus_raw={"high": 0.0011}))[0] == wf.NOT_VALIDATED
    assert wf.verdict(_summary(cal_minus_base={"high": 0.0}))[0] == wf.NOT_VALIDATED
    bad_ece = _summary(ece={"cal": {"9.5": {"n": 200, "ece": 0.031}}})
    verdict, reasons = wf.verdict(bad_ece)
    assert verdict == wf.NOT_VALIDATED and "9.5" in reasons[0]


def test_the_daily_interval_is_reproducible_and_brackets_the_mean() -> None:
    days = [datetime(2026, 1, 1, tzinfo=UTC).date() + timedelta(days=i % 30) for i in range(600)]
    rng = np.random.default_rng(0)
    diffs = list(rng.normal(-0.002, 0.01, 600))
    a, b = wf.daily_ci(diffs, days, seed=9), wf.daily_ci(diffs, days, seed=9)
    assert a == b and a["low"] <= a["mean"] <= a["high"] and a["days"] == 30
    assert a["mde"] == pytest.approx(2.8016 * a["sd_daily"] / math.sqrt(30))


def test_bogota_days() -> None:
    assert wf.bogota_day(datetime(2026, 1, 2, 3, tzinfo=UTC)).isoformat() == "2026-01-01"


# ── the settlement ───────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("measure", ["corners_ft", "cards_lines_ft"])
def test_the_probability_of_over_is_the_mass_the_settlement_pays(measure: str) -> None:
    rule = RULES_BY_MEASURE[measure]
    home, away = rule.columns
    pmf = cc.calibrated_pmf(_pmf(9.8 if measure == "corners_ft" else 4.4), cc.Params(1.2, 0.1, 900))
    for line in (3.5, 4.5, 9.5, 10.5):
        paid = sum(float(pmf[k]) for k in range(pmf.size)
                   if settle_numbers(rule, "over_under", "match", "Over", Decimal(str(line)), {home: k, away: 0}) == Status.WIN)
        assert paid == pytest.approx(cc.over(pmf, line), abs=1e-12)


def test_a_missing_count_settles_as_none_never_as_a_loss() -> None:
    rule = RULES_BY_MEASURE["corners_ft"]
    home, away = rule.columns
    assert settle_numbers(rule, "over_under", "match", "Over", Decimal("9.5"), {home: None, away: 4}) is None


# ── the LAB ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_lab_windows_and_statements_are_the_protocols() -> None:
    p = protocol.require("AD-B07")
    assert lab.START.date().isoformat() == "2025-11-10" and lab.END.date().isoformat() == "2026-11-10"
    assert "10-nov-2025" in p.data and "18-ago-2025" in p.split and lab.WARMUP.date().isoformat() == "2025-08-18"
    assert lab.HISTORY_FROM.date().isoformat() == "2023-11-01" and "1-nov-2023" in p.data
    for name, sql in lab.statements().items():
        assert sql.startswith("COPY (") and sql.endswith("TO STDOUT WITH (FORMAT csv, HEADER true)"), name
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "ALTER ", "DROP "):
            assert verb not in sql.upper(), (name, verb)
    assert set(lab.statements()) == set(lab.FILES)
    for family, lines in cc.LADDERS.items():
        assert all(float(ln - 0.5).is_integer() for ln in lines), family
    assert "7,5 a 13,5" in p.primary_metric and "0,5 a 3,5" in p.primary_metric


def test_the_recorded_result_carries_the_protocol_and_one_verdict_per_family() -> None:
    """The LAB run of 17-nov-2026 (docs/owner/IA_095_CORNERS_Y_TARJETAS_resultado.json) is the one the owner's ``fit`` reads: it is
    refused unless it carries the stamp of AD-B07 as registered."""
    from pathlib import Path

    from scripts import count_calibration

    path = Path(__file__).resolve().parents[2] / "docs" / "owner" / "IA_095_CORNERS_Y_TARJETAS_resultado.json"
    verdicts, report = count_calibration._verdicts(path)
    assert report["stamp"] == protocol.stamp("AD-B07")
    assert set(verdicts) == set(cc.FAMILIES) and set(verdicts.values()) <= set(wf.VERDICTS)
    assert verdicts["corners_total"] == wf.NOT_VALIDATED and verdicts["cards_total"] == wf.VALIDATED
    for measure in ("corners_ft", "cards_lines_ft"):
        for family in (f for f in cc.FAMILIES if cc.MEASURE_OF[f] == measure):
            s = report[measure][family]
            assert s["matches"] >= wf.MIN_MATCHES and s["days"] >= wf.MIN_DAYS
            rules = (s["cal_minus_raw"]["high"] <= wf.NON_INFERIORITY, s["ece_cal_max"]["ece"] <= wf.MAX_ECE,
                     s["cal_minus_base"]["high"] < 0)
            assert (verdicts[family] == wf.VALIDATED) == all(rules), family

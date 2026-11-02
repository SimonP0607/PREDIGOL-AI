"""The experiment of plan F4.4 (protocol ``rest-ab-v1``): does the model that reads the real rest score better? Pure: worlds made up here,
where the truth about rest is known, no database.

A world is a list of finished matches; each has a stored feature set (the Elo difference and the rest production counted) and, for each side, the
days since its last match outside the followed competitions. In a world where the real rest matters the arm that reads it must be
``promising``; where it does not, no arm may be called so; and where production's rest was the truth and the calendar only adds noise, the
real-rest arm must be ``harmful``. The verdict is arithmetic - these tests hold the arithmetic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.research import rest_ab
from fbi.research.rest_ab import ARMS, Observation, Pair, Protocol, SideRest

T0 = datetime(2026, 8, 1, 12, tzinfo=UTC)


def side(rest_outside: float | None, *, played_14d: int = 2) -> SideRest:
    return SideRest(rest_days=None, rest_days_tracked=None, rest_days_outside=rest_outside, played_7d=1, played_14d=played_14d,
                    played_30d=4, outside_14d=0 if rest_outside is None else 1, next_gap_days=None, next_competition_type=None,
                    whole=True, reason=None)


def world(n: int, *, truth: str, effect: float, seed: int) -> list[Observation]:
    """``n`` matches over twenty-four weeks. ``truth`` says which rest the result depends on: 'real' (the shorter of production's and the
    outside match's), 'production' (production's own, the outside matches being noise) or 'none'."""
    rng = np.random.default_rng(seed)
    out: list[Observation] = []
    span = 24 * 7 * 24 * 60
    for i in range(n):
        kickoff = T0 + timedelta(minutes=int(i * span / n))
        elo = float(rng.normal(0, 120))
        prod_h, prod_a = float(rng.integers(3, 11)), float(rng.integers(3, 11))
        outside_h = float(rng.integers(1, 4)) if rng.random() < 0.5 else None
        outside_a = float(rng.integers(1, 4)) if rng.random() < 0.5 else None
        real_h = prod_h if outside_h is None else min(prod_h, outside_h)
        real_a = prod_a if outside_a is None else min(prod_a, outside_a)
        used = {"real": real_h - real_a, "production": prod_h - prod_a, "none": 0.0}[truth]
        s = 0.004 * elo + effect * max(-7.0, min(7.0, used))
        logits = np.array([s, 0.3, -s])
        p = np.exp(logits - logits.max())
        p /= p.sum()
        outcome = int(rng.choice(3, p=p))
        values = {"elo_diff": elo, "pi_expected_gd": elo / 400, "league_home_gd_avg": 0.3, "is_neutral": 0.0,
                  "home_rest_days": prod_h, "away_rest_days": prod_a}
        out.append(Observation(i + 1, kickoff, outcome, values, side(outside_h, played_14d=int(rng.integers(1, 5))),
                               side(outside_a, played_14d=int(rng.integers(1, 5)))))
    return out


def pair(diff: float, lo: float, hi: float, n: int = 3000) -> Pair:
    return Pair(arm="true_rest", reference="production", n=n, days=100, loss_arm=1.0 + diff, loss_reference=1.0, diff=diff, lo=lo, hi=hi,
                brier_arm=0.6, brier_reference=0.6, rps_arm=0.2, rps_reference=0.2, minimum_detectable=0.001)


# ── the inputs of each arm ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_real_rest_is_the_shorter_of_what_production_counted_and_the_last_outside_match() -> None:
    assert rest_ab.true_rest(8.0, 2.0) == 2.0
    assert rest_ab.true_rest(3.0, 6.0) == 3.0, "the calendar can only shorten a rest"
    assert rest_ab.true_rest(None, 4.0) == 4.0 and rest_ab.true_rest(5.0, None) == 5.0 and rest_ab.true_rest(None, None) is None


def test_each_arm_changes_only_the_rest_and_the_difference_is_clipped_to_a_week_like_production() -> None:
    o = Observation(1, T0, 0, {"elo_diff": 40.0, "pi_expected_gd": 0.2, "home_rest_days": 9.0, "away_rest_days": 4.0}, side(2.0), side(None))
    production = rest_ab.arm_row("production", o)
    assert production[rest_ab.REST_AT] == 5.0
    real = rest_ab.arm_row("true_rest", o)
    assert real[rest_ab.REST_AT] == -2.0, "2 days (the outside match) against 4 (production's): -2"
    assert [x for i, x in enumerate(real) if i != rest_ab.REST_AT] == [x for i, x in enumerate(production) if i != rest_ab.REST_AT]
    assert rest_ab.arm_row("no_rest", o)[rest_ab.REST_AT] is None
    load = rest_ab.arm_row("true_rest_load", o)
    assert len(load) == len(production) + 1 == len(rest_ab.arm_features("true_rest_load")) and load[-1] == 0.0
    far = Observation(2, T0, 0, {"home_rest_days": 30.0, "away_rest_days": 1.0}, side(None), side(None))
    assert rest_ab.arm_row("production", far)[rest_ab.REST_AT] == 7.0 == rest_ab.true_rest_diff(far)
    with pytest.raises(ValueError):
        rest_ab.arm_row("tomorrow", o)


def test_what_the_calendar_changes_in_the_rest_is_counted_before_any_model() -> None:
    sample = [Observation(1, T0, 0, {"home_rest_days": 8.0, "away_rest_days": 7.0}, side(2.0), side(None)),
              Observation(2, T0, 1, {"home_rest_days": 6.0, "away_rest_days": 5.0}, side(5.5), side(4.0))]
    d = rest_ab.describe(sample)
    assert d["sides"] == 4 and d["with_rest"] == 4 and d["sides_with_an_outside_match_in_14d"] == 3
    assert d["share_rest_shorter_by_1d_or_more"] == 0.5, "8->2 and 5->4 are 1 day or more; 7, 6 untouched; 6->5.5 is half a day"
    assert d["share_rest_shorter_by_2d_or_more"] == 0.25 and d["max_days_shorter"] == 6.0
    assert rest_ab.describe([]) == {"sides": 0, "with_rest": 0}


# ── the arithmetic of the verdict ────────────────────────────────────────────────────────────────────────────────────────


def test_the_verdict_is_arithmetic_and_every_way_to_be_inconclusive_says_why() -> None:
    p = Protocol()
    assert rest_ab.verdict_of(pair(-0.002, -0.003, -0.001), p)[0] == "promising"
    assert rest_ab.verdict_of(pair(0.002, 0.001, 0.003), p)[0] == "harmful"
    verdict, why = rest_ab.verdict_of(pair(-0.0002, -0.0004, -0.0001), p)
    assert verdict == "inconclusive" and "less than" in why, "wholly better, but by less than the protocol asks"
    verdict, why = rest_ab.verdict_of(pair(-0.001, -0.002, 0.0005), p)
    assert verdict == "inconclusive" and "includes zero" in why
    verdict, why = rest_ab.verdict_of(pair(-0.01, -0.02, -0.005, n=400), p)
    assert verdict == "inconclusive" and "not enough evidence" in why, "too few matches decides nothing, however good they look"
    assert rest_ab.verdict_of(None, p)[0] == "inconclusive"


def test_the_test_blocks_are_fitted_only_on_results_that_were_known_before_them() -> None:
    sample = [Observation(i, T0 + timedelta(days=i * 3), 0, {}, side(None), side(None)) for i in range(1, 15)]
    blocks = rest_ab.blocks_of(sample, timedelta(days=14))
    assert blocks, "there are blocks after the first"
    for start, train, test in blocks:
        assert all(o.kickoff_at + timedelta(hours=3) <= start for o in train)
        assert all(start <= o.kickoff_at < start + timedelta(days=14) for o in test)
        assert not {o.fixture_id for o in train} & {o.fixture_id for o in test}
    edge = [Observation(1, T0, 0, {}, side(None), side(None)), Observation(2, T0 + timedelta(days=14) - timedelta(hours=1), 0, {}, side(None), side(None)),
            Observation(3, T0 + timedelta(days=14) + timedelta(hours=1), 0, {}, side(None), side(None))]
    (start, train, test), = rest_ab.blocks_of(edge, timedelta(days=14))
    assert [o.fixture_id for o in train] == [1], "a match three hours from finishing has no result to fit on yet"
    assert [o.fixture_id for o in test] == [3]


# ── the experiment on worlds where the truth is known ───────────────────────────────────────────────────────────────────


def test_where_the_real_rest_decides_the_result_the_model_that_reads_it_is_promising() -> None:
    result = rest_ab.run(world(6000, truth="real", effect=0.15, seed=3))
    assert result.verdict == "promising", result.why
    assert result.primary is not None and result.primary.diff < -0.002 and result.primary.hi < 0
    assert result.n_tested >= 4000 and result.blocks >= 8
    by = {(p.arm, p.reference): p for p in result.secondary}
    assert by[("no_rest", "production")].diff > 0, "taking the rest away makes it worse: production's rest is worth something"
    assert result.description["share_rest_shorter_by_1d_or_more"] > 0.2, "the calendar changes the rest of a good share of sides"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_where_rest_decides_nothing_nothing_is_promising(seed: int) -> None:
    result = rest_ab.run(world(5000, truth="none", effect=0.0, seed=seed))
    assert result.verdict != "promising", result.why


def test_where_production_rest_was_the_truth_and_the_calendar_only_adds_noise_the_real_rest_is_harmful() -> None:
    result = rest_ab.run(world(8000, truth="production", effect=0.25, seed=4))
    assert result.verdict == "harmful", result.why
    assert result.primary is not None and result.primary.lo > 0


def test_a_sample_too_small_to_fit_and_test_is_inconclusive_and_says_so() -> None:
    result = rest_ab.run(world(300, truth="real", effect=0.2, seed=5))
    assert result.verdict == "inconclusive" and result.n_tested == 0 and result.primary is None
    assert "too small" in result.why
    empty = rest_ab.run([])
    assert empty.verdict == "inconclusive" and empty.n_sample == 0


def test_a_match_whose_calendar_is_not_whole_is_not_in_the_sample() -> None:
    sample = world(100, truth="none", effect=0.0, seed=6)
    broken = [Observation(o.fixture_id, o.kickoff_at, o.outcome, o.values, o.home,
                          SideRest(None, None, None, 0, 0, 0, 0, None, None, False, "unconfirmed_match")) if i % 2 else o
              for i, o in enumerate(sample)]
    assert rest_ab.run(broken).n_sample == 50


def test_the_result_is_a_record_a_person_can_look_back_on() -> None:
    result = rest_ab.run(world(4000, truth="real", effect=0.15, seed=7))
    record = result.as_dict()
    assert record["protocol"]["protocol"] == "rest-ab-v1" and record["protocol"]["arms"] == list(ARMS)
    assert record["verdict"] == result.verdict and record["primary"]["arm"] == "true_rest"
    assert len(record["secondary"]) == 3 and record["sample"]["with_rest"] > 0
    assert set(record) >= {"why", "n_sample", "n_tested", "blocks", "first_kickoff", "last_kickoff"}

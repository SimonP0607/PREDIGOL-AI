"""RP-9.1 (EXP-E1): the segments, the pool of the models and the verdict on simulated matches. Pure: nothing reads a database."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from fbi.research import exp_e1 as e1
from fbi.research import exp_protocol

THRESHOLDS = exp_protocol.THRESHOLDS["EXP-E1"]
D0 = date(2026, 12, 1)


def test_the_segments_of_a_competition_are_those_of_the_protocol_and_a_match_can_be_in_two() -> None:
    assert e1.segments_of(tier=1, competition_type="domestic_league", entity_scope="club") == ("nivel 1", "ligas nacionales")
    assert e1.segments_of(tier=3, competition_type="domestic_cup", entity_scope="club") == ("nivel 3", "copas nacionales")
    assert e1.segments_of(tier=None, competition_type="international", entity_scope="national_team") == ("competiciones de selecciones",)
    assert e1.segments_of(tier=9, competition_type="continental", entity_scope="club") == (), "outside the protocol: not in any segment"
    assert set(e1.SEGMENTS) == {"nivel 1", "nivel 2", "nivel 3", "nivel 4", "nivel 5", "ligas nacionales", "copas nacionales", "competiciones de selecciones"}


def test_the_pool_of_one_forecast_is_that_forecast_and_the_pool_of_two_is_between_them() -> None:
    a, b = (0.6, 0.25, 0.15), (0.4, 0.3, 0.3)
    assert e1.pool([a]) == pytest.approx(a)
    mixed = e1.pool([a, b])
    assert sum(mixed) == pytest.approx(1.0) and all(min(x, y) < z < max(x, y) for x, y, z in zip(a, b, mixed, strict=True))


def test_the_sample_starts_the_day_after_the_signature() -> None:
    assert e1.after_signature(date(2026, 11, 26)).isoformat() == "2026-11-27T00:00:00+00:00"


def world(n: int, *, edge: float, seed: int = 1, segment_tier: int = 3) -> list[e1.Match]:
    """``n`` matches (a day each, a few per day), all in one competition of ``segment_tier``. The close is the true probability; the pool is the true
    probability moved ``edge`` (in log odds, toward the draw) so its loss is a little above the close's, by an amount that grows with ``edge``."""
    rng = np.random.default_rng(seed)
    out: list[e1.Match] = []
    for i in range(n):
        base = rng.dirichlet([6.0, 3.0, 4.0])
        truth = (float(base[0]), float(base[1]), float(base[2]))
        outcome = int(rng.choice(3, p=base))
        shifted = np.array(truth) * np.array([1.0, np.exp(edge), 1.0])
        shifted /= shifted.sum()
        model = (float(shifted[0]), float(shifted[1]), float(shifted[2]))
        out.append(e1.Match(i, D0 + timedelta(days=i // 10), e1.segments_of(tier=segment_tier, competition_type="domestic_league", entity_scope="club"),
                            outcome, truth, {"poisson": model, "dixon_coles": model}))
    return out


def test_with_less_than_the_fixed_sample_nothing_is_declared() -> None:
    j, pop = e1.judge(world(400, edge=0.0), required=1000, thresholds=THRESHOLDS, seed=7)
    assert j.verdict == "insuficiente" and "400 de 1000" in j.reason
    assert pop["segments"]["nivel 3"]["verdict"] is None and pop["segments"]["nivel 3"]["matches"] == 400


def test_a_model_far_from_the_close_in_the_only_segment_is_not_an_abandonment_while_the_other_segments_have_no_sample() -> None:
    j, pop = e1.judge(world(1200, edge=1.0), required=1000, thresholds=THRESHOLDS, seed=7)
    assert pop["segments"]["nivel 3"]["verdict"] == "abandono"
    assert j.verdict == "insuficiente", "only every one of the eight segments with its sample and none below the threshold abandons the experiment"


def test_a_model_that_is_the_close_is_a_success_in_its_segment() -> None:
    j, pop = e1.judge(world(1200, edge=0.0), required=1000, thresholds=THRESHOLDS, seed=7)
    assert j.verdict == "exito" and j.mean < 0.005 and "nivel 3" in j.reason
    assert pop["segments"]["nivel 3"]["adjusted_p"] is not None and pop["holm_over"] == ["ligas nacionales", "nivel 3"]
    assert pop["models"]["poisson"]["matches"] == 1200


def test_every_segment_with_its_sample_and_none_below_the_threshold_is_an_abandonment() -> None:
    matches: list[e1.Match] = []
    for k, tier in enumerate(range(1, 6)):
        matches += [e1.Match(m.fixture + 10_000 * k, m.day, ("nivel " + str(tier),), m.outcome, m.close, m.forecasts) for m in world(1100, edge=1.0, seed=k)]
    for k, kind in enumerate(("ligas nacionales", "copas nacionales", "competiciones de selecciones")):
        matches += [e1.Match(m.fixture + 100_000 * (k + 1), m.day, (kind,), m.outcome, m.close, m.forecasts) for m in world(1100, edge=1.0, seed=9 + k)]
    j, _ = e1.judge(matches, required=1000, thresholds=THRESHOLDS, seed=7)
    assert j.verdict == "abandono" and j.low >= 0.005

"""RP-9.0: the common protocol of the plan's eight experiments (exp-protocol-v1) - registered before any result, frozen, and the statistics
that judge them. A verdict without a prior protocol is refused."""

from __future__ import annotations

import dataclasses
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from fbi.research import exp_protocol as ep
from fbi.research import protocol as proto

PINNED = {
    "EXP-E1": "2a291735aefd2a7ccd3f64861c7678d316a627e17dbc04e9d0d68bfa5ba222ee",
    "EXP-E2": "652a5f8067397082b29fb8966118d2673602c01ef9658a5597863417fe5b596a",
    "EXP-E3": "53726ea318f0464337f9c618846306155338a74d04df488e1b03b40fb3d65287",
    "EXP-E4": "ad471f26f738e467c25dbd45936e2051e465daa4e0967268ce0f839c7c56d2c3",
    "EXP-E5": "26cac84b26d8863452fdb4de7686b54f852d064b8aa3cd2d586f43798ed91753",
    "EXP-E6": "8662b15c2797d0bf52e612147d961acd321e1b3eedfe7c10de5318fbe5f38eb4",
    "EXP-E7": "50641854352c0d59003fedd195724d838a7518b1dccaa0dc322acf5ee5035529",
    "EXP-E8": "f4943f75138ed58868c44db9bd990e7ffe61a12f36003a3a378ff33c89af8fac",
}
"""Frozen: changing a registered protocol is a new version with its own PR, never an edit of these lines to make a test pass."""


def _series(n_days: int, per_day: int, mean: float, spread: float, seed: int) -> tuple[list[float], list[date]]:
    rng = random.Random(seed)
    values: list[float] = []
    days: list[date] = []
    for i in range(n_days):
        for _ in range(per_day):
            values.append(rng.gauss(mean, spread))
            days.append(date(2026, 12, 1) + timedelta(days=i))
    return values, days


def test_the_eight_are_registered_with_their_pinned_fingerprints() -> None:
    assert set(ep.EXPERIMENTS) == set(PINNED)
    for key, expected in PINNED.items():
        assert proto.fingerprint(ep.EXPERIMENTS[key]) == expected, f"{key} changed: it is a new version, not an edit"


def test_every_protocol_is_complete_dated_and_findable() -> None:
    for key, p in ep.EXPERIMENTS.items():
        assert p.key == key and p.registered_on == ep.SIGNATURE and p.version.endswith("-v1")
        for f in dataclasses.fields(p):
            value = getattr(p, f.name)
            if f.name == "secondary":  # a protocol may fix no secondary reading
                continue
            assert value not in ("", (), None), f"{key}.{f.name} is empty"
        assert proto.require(key) is p and proto.stamp(key)["fingerprint"] == PINNED[key]
    assert not set(ep.EXPERIMENTS) & set(proto.PROTOCOLS), "the signable catalogue (C-11) stays INT-/AD- only"


def test_an_experiment_without_protocol_is_refused() -> None:
    with pytest.raises(LookupError):
        proto.require("EXP-E9")
    with pytest.raises(ep.ProtocolRefusedError):
        ep.admit("EXP-E9", claimed_fingerprint="x", computed_at=datetime(2026, 12, 1, tzinfo=UTC))


def test_a_verdict_must_carry_the_fingerprint_and_come_after_the_signature() -> None:
    ok = datetime(2026, 12, 1, tzinfo=UTC)
    assert ep.admit("EXP-E1", claimed_fingerprint=PINNED["EXP-E1"], computed_at=ok).key == "EXP-E1"
    with pytest.raises(ep.ProtocolRefusedError, match="huella"):
        ep.admit("EXP-E1", claimed_fingerprint="0" * 64, computed_at=ok)
    with pytest.raises(ep.ProtocolRefusedError, match="anterior a la firma"):
        ep.admit("EXP-E1", claimed_fingerprint=PINNED["EXP-E1"], computed_at=datetime(2026, 11, 25, tzinfo=UTC))


def test_the_thresholds_are_the_audits_and_match_their_protocols() -> None:
    assert ep.THRESHOLDS["EXP-E1"] == {"success_below": 0.005, "n_required": 1000}
    assert ep.THRESHOLDS["EXP-E3"] == {"success_below": 0.005, "n_required": 1500}
    assert ep.THRESHOLDS["EXP-E5"] == {"success_below": 0.010, "abandon_at_or_above": 0.020, "n_required": 900}
    assert "1.000" in ep.E1.min_sample and "1.500" in ep.E3.min_sample and "900" in ep.E5.min_sample
    assert len(ep.E1.segments) <= ep.MAX_SEGMENTS


def test_bootstrap_by_days_covers_the_mean_and_is_reproducible() -> None:
    v, d = _series(60, 10, 0.02, 0.1, 1)
    m1, lo1, hi1 = ep.day_bootstrap_ci(v, d, seed=7)
    assert (m1, lo1, hi1) == ep.day_bootstrap_ci(v, d, seed=7)
    assert lo1 < m1 < hi1 and lo1 < 0.02 < hi1
    with pytest.raises(ValueError):
        ep.day_bootstrap_ci([], [], seed=1)
    with pytest.raises(ValueError):
        ep.day_bootstrap_ci([1.0], [], seed=1)


def test_resampling_days_is_wider_than_resampling_matches_when_a_day_moves_together() -> None:
    """Matches of one day share their conditions: the interval by days must be wider than the naive one."""
    rng = random.Random(3)
    values: list[float] = []
    days: list[date] = []
    for i in range(40):
        shock = rng.gauss(0, 0.05)
        for _ in range(20):
            values.append(shock + rng.gauss(0, 0.02))
            days.append(date(2026, 12, 1) + timedelta(days=i))
    _, lo, hi = ep.day_bootstrap_ci(values, days, seed=1)
    naive = [date(2026, 12, 1) + timedelta(days=i) for i in range(len(values))]
    _, nlo, nhi = ep.day_bootstrap_ci(values, naive, seed=1)
    assert (hi - lo) > 2 * (nhi - nlo)


def test_holm_is_monotone_capped_and_keeps_the_order_given() -> None:
    p = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5}
    adj = ep.holm(p)
    assert list(adj) == ["a", "b", "c", "d"]
    assert adj["a"] == pytest.approx(0.04) and adj["c"] == pytest.approx(0.09) and adj["b"] == pytest.approx(0.09)
    assert adj["d"] == pytest.approx(0.5) and all(adj[k] >= p[k] for k in p) and max(adj.values()) <= 1.0
    assert ep.holm({}) == {}


def test_same_sign_in_halves() -> None:
    days = [date(2026, 12, 1) + timedelta(days=i) for i in range(10) for _ in range(2)]
    assert ep.same_sign_in_halves([0.01] * 20, days, centre=0.02)
    assert not ep.same_sign_in_halves([-1.0] * 10 + [1.0] * 10, days)
    assert not ep.same_sign_in_halves([1.0], [date(2026, 12, 1)])


def test_equal_population_keeps_only_what_every_scorer_predicted() -> None:
    assert ep.equal_population([1, 2, 3, 4], [4, 2, 9], iter([2, 4, 7])) == [2, 4]
    assert ep.equal_population() == []


def test_only_matches_after_the_signature_count() -> None:
    sig = datetime(2026, 11, 26, 12, tzinfo=UTC)
    items = [(sig - timedelta(hours=1), "old"), (sig, "same_instant"), (sig + timedelta(hours=1), "new")]
    assert ep.only_after(items, sig) == ["new"]


def test_verdict_is_insufficient_below_the_sample_and_never_stretches_it() -> None:
    v, d = _series(10, 10, -0.05, 0.05, 2)
    j = ep.difference_verdict(v, d, success_below=0.005, n_required=1000, seed=1)
    assert j.verdict == "insuficiente" and j.n == 100 and "100 de 1000" in j.reason


def test_verdict_success_when_the_whole_interval_is_below_the_threshold_in_both_halves() -> None:
    v, d = _series(120, 10, -0.02, 0.05, 4)
    j = ep.difference_verdict(v, d, success_below=0.005, n_required=1000, seed=1, adjusted_p=0.01)
    assert j.verdict == "exito" and j.high < 0.005


def test_a_success_without_the_holm_p_value_under_alpha_is_not_a_success() -> None:
    v, d = _series(120, 10, -0.02, 0.05, 4)
    assert ep.difference_verdict(v, d, success_below=0.005, n_required=1000, seed=1, adjusted_p=0.2).verdict == "insuficiente"


def test_verdict_abandon_when_the_interval_stays_above() -> None:
    v, d = _series(120, 10, 0.03, 0.05, 5)
    assert ep.difference_verdict(v, d, success_below=0.005, n_required=1000, seed=1).verdict == "abandono"


def test_verdict_inconclusive_when_the_interval_holds_both_answers() -> None:
    v, d = _series(120, 10, 0.005, 0.2, 6)
    assert ep.difference_verdict(v, d, success_below=0.005, n_required=1000, seed=1).verdict == "insuficiente"


def test_exp_e5_two_thresholds_leave_a_middle_zone_undeclared() -> None:
    kw = {**ep.THRESHOLDS["EXP-E5"]}
    mid, d = _series(120, 10, 0.015, 0.02, 7)
    assert ep.difference_verdict(mid, d, seed=1, **kw).verdict == "insuficiente"
    high, d2 = _series(120, 10, 0.05, 0.02, 8)
    assert ep.difference_verdict(high, d2, seed=1, **kw).verdict == "abandono"
    low, d3 = _series(120, 10, 0.0, 0.02, 9)
    assert ep.difference_verdict(low, d3, seed=1, **kw).verdict == "exito"


def test_the_module_touches_no_database_clock_or_model() -> None:
    import inspect

    src = inspect.getsource(ep)
    for forbidden in ("psycopg", "sqlalchemy", "datetime.now", "utcnow", "import numpy"):
        assert forbidden not in src

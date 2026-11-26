"""RP-4.5: the residual of a context factor against the market, clustered by day (``fbi.intel.factor_residual``), and the rule that says what each state of the
registry allows (``fbi.intel.factors.usable_as_signal``)."""

from __future__ import annotations

import math
import random
import re
from datetime import date, timedelta

import pytest

from fbi.ai import stats_factors, views
from fbi.intel import factor_block, factors
from fbi.intel import factor_residual as fr

D0 = date(2026, 1, 1)


def make(n_days: int, per_day: int, *, shift: float, group: str = "g", market: float = 0.45, seed: int = 1, flip_second_half: bool = False) -> list[fr.Obs]:
    """Matches whose true probability is ``market + shift`` (the factor's effect): the outcome is drawn from it."""
    rng = random.Random(seed)
    out = []
    for d in range(n_days):
        s = -shift if flip_second_half and d >= n_days // 2 else shift
        for _ in range(per_day):
            out.append(fr.Obs(D0 + timedelta(days=d), group, 1.0 if rng.random() < market + s else 0.0, market))
    return out


def test_the_audits_own_group_is_inside_its_error_and_gives_no_state() -> None:
    # the audit of 24-nov: 204 matches, +3.1 points, standard error 3.2 points -> 0.97 standard errors, inside
    z = 0.031 / 0.032
    assert abs(z) <= fr.NOTABLE_Z
    assert fr.MAX_DETECTABLE < 1.96 * 0.032, "a test with that error could not have seen less than 6.3 points: «no effect» is not said"


def test_a_clear_effect_is_found_and_stable() -> None:
    found = fr.lines(make(80, 8, shift=0.10))
    assert len(found) == 1 and found[0].n == 640 and found[0].days == 80
    assert found[0].mean > 0.05 and found[0].inside_error is False and found[0].halves_agree
    verdict = fr.judge(found)
    assert verdict.state == factors.TESTED_EFFECT


def test_no_effect_needs_a_sample_that_could_have_seen_one() -> None:
    big = fr.judge(fr.lines(make(150, 20, shift=0.0, seed=3)))
    assert big.state == factors.TESTED_NO_EFFECT, big.reason
    small = fr.judge(fr.lines(make(20, 10, shift=0.0, seed=3)))
    assert small.state is None, "200 matches over 20 days cannot show «no effect»"
    assert "no se dice" in small.reason or "evidencia" in small.reason


def test_an_effect_that_changes_sign_between_halves_is_not_declared() -> None:
    verdict = fr.judge(fr.lines(make(120, 12, shift=0.12, flip_second_half=True)))
    assert verdict.state != factors.TESTED_EFFECT


def test_the_error_is_clustered_by_day_and_is_wider_than_the_naive_one() -> None:
    # every match of a day shares one shock: the naive error ignores it, the clustered one must not
    rng = random.Random(7)
    res, days = [], []
    for d in range(60):
        shock = rng.choice([-0.3, 0.3])
        for _ in range(10):
            res.append(shock)
            days.append(D0 + timedelta(days=d))
    se = fr.cluster_se(res, days)
    assert se is not None
    mean = sum(res) / len(res)
    naive = math.sqrt(sum((r - mean) ** 2 for r in res) / (len(res) - 1) / len(res))
    assert naive < 0.02 and se > 0.03, "ten matches a day move together, so the evidence is 60 days, not 600 matches"


def test_one_day_has_no_error_and_a_group_with_too_few_matches_says_nothing() -> None:
    assert fr.cluster_se([0.1, -0.2], [D0, D0]) is None
    found = fr.lines(make(5, 5, shift=0.0))
    assert not found[0].enough
    assert fr.judge(found).state is None


def test_holm_is_over_the_groups_with_enough_matches() -> None:
    obs = make(100, 10, shift=0.12, group="a", seed=2) + make(100, 10, shift=0.0, group="b", seed=4) + make(5, 5, shift=0.0, group="c")
    found = fr.lines(obs)
    verdict = fr.judge(found)
    assert set(verdict.adjusted) == {"a", "b"}, "the group with 25 matches is reported but not tested"
    assert verdict.state == factors.TESTED_EFFECT


@pytest.mark.parametrize("bad", [fr.Obs(D0, "g", 0.5, 0.4), fr.Obs(D0, "g", 1.0, 1.0), fr.Obs(D0, "g", 0.0, 0.0)])
def test_an_impossible_observation_is_refused(bad: fr.Obs) -> None:
    with pytest.raises(ValueError):
        fr.lines([bad])


def test_the_report_is_plain_json_the_registry_can_keep() -> None:
    import json

    doc = fr.report(make(40, 10, shift=0.0))
    json.dumps(doc, allow_nan=False)
    assert doc["version"] == fr.VERSION and doc["verdict"]["version"] == fr.VERSION and doc["matches"] == 400
    factors.check_evidence("F-residual-01", doc)


# ── what each state allows ──────────────────────────────────────────────────────────────────────────────────────────────


def test_only_a_validation_lets_anything_use_a_factor() -> None:
    assert [s for s in factors.STATUSES if factors.usable_as_signal(s)] == [factors.VALIDATED]
    assert not factors.usable_as_signal(None) and not factors.usable_as_signal("")
    assert not factors.usable_as_signal("tested_effect")


@pytest.mark.parametrize("status", [s for s in factors.STATUSES if s != factors.VALIDATED])
def test_every_reader_keeps_a_measured_factor_out(status: str) -> None:
    """The packet states a status; the brief's view and the Statistics Agent read it. A measured state must be as closed as DESCRIPTIVE."""
    content = {"factors": {f.key: {"version": f.version, "block": f.where, "status": status} for f in factors.CATALOGUE}}
    assert views.validated_factors(content) == frozenset()
    paths, _ = stats_factors.descriptive_blocks({"shared": {"factors": content["factors"]}})
    assert paths == {stats_factors.package_path(f) for f in factors.CATALOGUE}


def test_the_block_factors_carry_the_versions_of_the_code_that_computes_them() -> None:
    from fbi.ai import calendar_facts, stakes_facts

    assert factor_block.BY_KEY[factor_block.STAKES].version == stakes_facts.VERSION
    assert factor_block.BY_KEY[factor_block.CALENDAR_FACTS].version == calendar_facts.VERSION
    assert not set(factor_block.BY_KEY) & set(factors.BY_KEY), "a factor is in the packet's catalogue or in the block, not both"
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{1,62}", k) for k in factor_block.BY_KEY), "the table's own check on a factor's name"

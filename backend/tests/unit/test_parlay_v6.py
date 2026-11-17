"""IA-110 (AD-E06): ``parlay-v6``'s builder is pure - its properties, over many random pools and the cases the owner's decision 6 names.

* never more than 3 legs (and a cap above 3 is refused), never fewer than 2, never a leg that is not confirmed in the shadow by itself;
* 0 parlays from a single valid candidate; ``none`` with why when nothing meets;
* the joint by simulation is never above the smallest margin, nor below the Fréchet floor; with a positive dependence it is not below the
  product (beyond its Monte Carlo error) and with a negative one not above it; the same legs give the same joint (the seed is theirs);
* the same match from the score matrix: «más de 2,5» and «ambos marcan» together, as the matrix says (1.5 times the product);
* an unmeasured or positive measured dependence between two matches never raises the joint; one team in two matches is never combined;
* the accumulated margin grows with every leg; a leg is never added that does not grow the parlay.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from scipy.special import ndtri

from fbi.ai.calendar import local_day
from fbi.forecasting import score_matrix as sm
from fbi.picks import daily
from fbi.tracking import parlay_v6 as v6
from fbi.valuation import dependence as dep

AT = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)  # 09:00 in Bogotá
KO = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)


def cand(n: int, *, fixture: int | None = None, teams: tuple[int, int] | None = None, market: str = "1X2", selection: str = "Home",
         line: str = "0", odds: float = 2.4, p: float = 0.48, p_low: float | None = None, books: int | None = 5, state: str = v6.CONFIRMED,
         kickoff: datetime = KO, competition: int | None = None, p_market: float | None = 0.40) -> v6.Candidate:
    f = fixture if fixture is not None else 100 + n
    t = teams if teams is not None else (2 * f, 2 * f + 1)
    return v6.Candidate(f"decision-v2-shadow-v1|{f}|{market}|{selection}|{line}", state, 1000 + n, AT - timedelta(hours=2), f,
                        competition if competition is not None else 500 + n, kickoff, frozenset(t), market, selection,
                        Decimal(line).quantize(Decimal("0.01")), odds, p, p - 0.03 if p_low is None else p_low, p_market, books,
                        "intel.decisions_v2", 9000 + n)


def test_the_stake_that_chooses_is_the_daily_sets() -> None:
    assert v6.STAKE_FRACTION == daily.STAKE_FRACTION and v6.MAX_LEGS == 3 and v6.MIN_LEGS == 2


def test_a_cap_above_three_is_refused() -> None:
    with pytest.raises(ValueError):
        v6.choose([cand(1), cand(2)], kind="daily", at=AT, max_legs=4)


@pytest.mark.parametrize("seed", range(40))
def test_random_pools_never_break_the_rules(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pool = []
    for n in range(int(rng.integers(0, 9))):
        p = float(rng.uniform(0.25, 0.75))
        pool.append(cand(n, odds=round(float(rng.uniform(1.3, 4.0)), 2), p=p, p_low=max(0.01, p - float(rng.uniform(0, 0.1))),
                         state=v6.CONFIRMED if rng.random() < 0.7 else str(rng.choice(["en_evaluacion", "retirada", "pendiente_alineaciones"])),
                         books=int(rng.integers(1, 8)), fixture=100 + int(rng.integers(0, 5)) if rng.random() < 0.3 else None,
                         kickoff=KO + timedelta(minutes=int(rng.integers(-600, 600)))))
    res = v6.choose(pool, kind="daily", at=AT, simulations=20_000)
    valid = [c for c in pool if v6.refusal(c, at=AT) is None and v6.window("daily", AT)[0] <= c.kickoff_at < v6.window("daily", AT)[1]]
    if isinstance(res, v6.Built):
        assert v6.MIN_LEGS <= len(res.legs) <= v6.MAX_LEGS
        assert all(c.state == v6.CONFIRMED and v6.refusal(c, at=AT) is None for c in res.legs)
        assert len({c.chain_key for c in res.legs}) == len(res.legs)
        j = res.joint
        assert j.p_low <= j.p <= min(float(c.p or 0) for c in res.legs) + 1e-12
        assert j.p >= max(0.0, sum(float(c.p or 0) for c in res.legs) - (len(res.legs) - 1)) - 1e-12
        assert res.expected_log_growth > 0
        assert math.isclose(res.combined_odds, math.prod(float(c.odds or 0) for c in res.legs))
    else:
        assert res.n_candidates == len(valid) or res.reason == "ninguna_combinacion_cumple"
        if len(valid) <= 1:
            assert res.reason == ("sin_candidatos" if not valid else "un_solo_candidato")


def test_one_valid_candidate_is_no_parlay_and_an_unconfirmed_one_never_joins() -> None:
    lone = v6.choose([cand(1), cand(2, state="en_evaluacion"), cand(3, state="retirada")], kind="daily", at=AT)
    assert isinstance(lone, v6.NoParlay) and lone.reason == "un_solo_candidato"
    assert lone.refused == {"no_confirmada": 2}
    assert isinstance(v6.choose([], kind="daily", at=AT), v6.NoParlay)


def test_four_good_legs_make_three_at_most() -> None:
    res = v6.choose([cand(n, odds=2.6, p=0.5) for n in range(4)], kind="daily", at=AT, simulations=20_000)
    assert isinstance(res, v6.Built) and len(res.legs) == 3
    two = v6.choose([cand(n, odds=2.6, p=0.5) for n in range(4)], kind="daily", at=AT, max_legs=2, simulations=20_000)
    assert isinstance(two, v6.Built) and len(two.legs) == 2


def test_a_leg_is_never_added_to_raise_the_odds() -> None:
    good = [cand(1, odds=2.2, p=0.55), cand(2, odds=2.2, p=0.55)]
    long_shot = cand(3, odds=9.0, p=0.115, p_low=0.08)  # odds x p > 1 at its point, but its pessimistic end does not grow the parlay
    res = v6.choose([*good, long_shot], kind="daily", at=AT, simulations=20_000)
    assert isinstance(res, v6.Built) and {c.chain_key for c in res.legs} == {c.chain_key for c in good}


@pytest.mark.parametrize(("c", "why"), [
    (cand(1, books=2), "una_sola_casa"), (cand(1, books=None), "una_sola_casa"), (cand(1, line="2.5", market="OU", selection="Over"), None),
    (cand(1, line="2", market="OU", selection="Over"), "linea_con_devolucion"), (cand(1, line="-0.25", market="AH"), "linea_con_devolucion"),
    (cand(1, market="CORNERS_OU", selection="Over", line="9.5"), "linea_con_devolucion"), (cand(1, odds=1.0), "sin_precio"),
    (cand(1, p=0.3, odds=3.0), "sin_valor"), (cand(1, kickoff=AT + timedelta(minutes=9)), "empieza_ya"),
    (cand(1, p=0.5, p_low=0.6), "sin_probabilidad"), (cand(1, state="detectado"), "no_confirmada")])
def test_what_a_leg_must_be(c: v6.Candidate, why: str | None) -> None:
    assert v6.refusal(c, at=AT) == why


def test_the_joint_is_bounded_and_follows_the_sign_of_the_dependence() -> None:
    p = [0.55, 0.5]
    indep = v6.joint(p, [0.5, 0.45], [0.5, 0.48], {}, seed=7)
    pos = v6.joint(p, [0.5, 0.45], [0.5, 0.48], {(0, 1): 0.3}, seed=7)
    neg = v6.joint(p, [0.5, 0.45], [0.5, 0.48], {(0, 1): -0.3}, seed=7)
    assert indep is not None and pos is not None and neg is not None
    assert abs(indep.p - indep.product) < 4 * indep.se
    assert pos.p <= min(p) and pos.p >= pos.product - 4 * pos.se and pos.p > indep.p
    assert neg.p <= neg.product + 4 * neg.se and neg.p < indep.p
    assert abs(pos.p - v6.pair_target(0.55, 0.5, 0.3)) < 4 * pos.se, "the simulated pair has the phi it was given"
    assert v6.joint(p, [0.5, 0.45], [0.5, 0.48], {(0, 1): 0.3}, seed=7) == pos, "the same seed gives the same draws"
    assert pos.p_low <= pos.p and pos.p_market is not None


def test_an_incoherent_set_of_dependences_is_no_joint() -> None:
    assert v6.joint([0.5, 0.5, 0.5], [0.4] * 3, [None] * 3, {(0, 1): 0.95, (0, 2): 0.95, (1, 2): -0.95}, seed=1) is None


def test_the_bivariate_normal_and_the_latent_correlation() -> None:
    assert abs(v6.bvn(0.0, 0.0, 0.5) - (0.25 + math.asin(0.5) / (2 * math.pi))) < 1e-9
    r = v6.latent(0.6, 0.45, 0.25)
    assert abs(v6.bvn(float(ndtri(0.6)), float(ndtri(0.45)), r) - v6.pair_target(0.6, 0.45, 0.25)) < 1e-9


def _matrix() -> np.ndarray:
    return sm.build(sm.Params(1.65, 1.35, None, "poisson")).p


def test_same_match_over_and_both_score_as_the_matrix_says() -> None:
    m = _matrix()
    over, btts = ("OU", "Over", Decimal("2.5")), ("BTTS", "Yes", Decimal("0"))
    pa = float(sum(m[i, j] for i in range(m.shape[0]) for j in range(m.shape[1]) if i + j > 2))
    pb = float(sum(m[i, j] for i in range(1, m.shape[0]) for j in range(1, m.shape[1])))
    pab = float(sum(m[i, j] for i in range(1, m.shape[0]) for j in range(1, m.shape[1]) if i + j > 2))
    assert 1.3 < pab / (pa * pb) < 1.8, "the plan's 1.55 times the product (16-nov-2026) is the order of it"
    a = cand(1, fixture=77, market="OU", selection="Over", line="2.5", p=pa, p_low=pa - 0.02, odds=1.0 / pa + 0.3)
    b = cand(2, fixture=77, market="BTTS", selection="Yes", line="0", p=pb, p_low=pb - 0.02, odds=1.0 / pb + 0.3)
    got = v6.evaluate([a, b], matrices={77: m}, simulations=200_000)
    assert got is not None
    j, used = got
    assert abs(j.p - pab) < 4 * j.se, "the joint of two legs of one match is the matrix's"
    assert used[0]["source"] == dep.SCORE_MATRIX and used[0]["relation"] == "same_match"
    assert dep.matrix_rho(m, over, btts) is not None
    assert v6.evaluate([a, b], matrices={}) is None, "one match without its matrix cannot be combined"


def test_two_matches_are_never_raised_by_an_unmeasured_or_positive_dependence() -> None:
    a = cand(1, competition=9, market="OU", selection="Over", line="2.5", p=0.55, odds=2.0)
    b = cand(2, competition=9, market="OU", selection="Over", line="2.5", p=0.55, odds=2.0)
    positive = {"over_2_5": dep.Measured("over_2_5", 0.03, 0.003, 12663, 57073)}
    for measured in (None, positive):
        got = v6.evaluate([a, b], measured=measured, simulations=200_000)
        assert got is not None
        assert got[0].p <= got[0].product + 4 * got[0].se and got[0].latent == ()
    negative = {"over_2_5": dep.Measured("over_2_5", -0.05, 0.003, 12663, 57073)}
    got = v6.evaluate([a, b], measured=negative, simulations=200_000)
    assert got is not None and got[0].p < got[0].product and got[0].latent


def test_one_team_in_two_matches_is_never_combined() -> None:
    a, b = cand(1, teams=(10, 11)), cand(2, teams=(11, 12))
    assert v6.evaluate([a, b]) is None
    res = v6.choose([a, b], kind="daily", at=AT)
    assert isinstance(res, v6.NoParlay) and res.reason == "ninguna_combinacion_cumple"


def test_the_margin_accumulates_and_the_record_says_what_it_shows() -> None:
    legs = [cand(n, odds=2.5, p=0.5, p_market=0.38) for n in range(3)]
    res = v6.choose(legs, kind="daily", at=AT, simulations=50_000)
    assert isinstance(res, v6.Built) and len(res.legs) == 3
    assert res.accumulated_margin is not None
    assert all(m is not None and abs(m - (1 - 2.5 * 0.38)) < 1e-12 for m in res.leg_margins)
    assert res.accumulated_margin == pytest.approx(1 - res.combined_odds * (res.joint.p_market or 0))
    assert res.fair_odds == pytest.approx(1 / res.joint.p)
    assert res.expected_value == pytest.approx(res.combined_odds * res.joint.p - 1)


def test_a_multiday_parlay_spans_two_product_days() -> None:
    same_day = [cand(n, odds=2.6, p=0.5) for n in range(3)]
    assert isinstance(v6.choose(same_day, kind="multiday", at=AT, simulations=20_000), v6.NoParlay)
    two_days = [*same_day, cand(9, odds=2.6, p=0.5, kickoff=KO + timedelta(days=1))]
    res = v6.choose(two_days, kind="multiday", at=AT, simulations=20_000)
    assert isinstance(res, v6.Built) and len({local_day(c.kickoff_at) for c in res.legs}) == 2


@pytest.mark.parametrize(("results", "status", "factor"), [
    (["win", "win"], "WON", 5.0), (["win", "loss"], "LOST", 0.0), (["loss", None], "LOST", 0.0), (["win", None], "ACTIVE", None),
    (["void", "win"], "PARTIAL_VOID", 2.5), (["void", "void"], "VOID", 1.0)])
def test_the_result_of_a_parlay(results: list[str | None], status: str, factor: float | None) -> None:
    assert v6.outcome(results, [2.0, 2.5]) == (status, factor)


def test_a_leg_that_cannot_push_never_settles_a_push() -> None:
    with pytest.raises(ValueError):
        v6.outcome(["push", "win"], [2.0, 2.0])

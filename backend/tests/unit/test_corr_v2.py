"""corr-v2 (``fbi.valuation.dependence``, AD-E07, IA-098): one calculation of dependence. Symmetric and within [-1, 1]; the same match from
its score matrix; parity with ``icc-v1`` as the parlays use it (``parlay-v5``) on the pairs it measures, and with portfolio-corr-v1's
budgets; an unmeasured positive dependence never raises a joint probability; and decision-v1's filter 8 untouched."""

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from fbi.forecasting import score_matrix as sm
from fbi.parlays import correlation as icc
from fbi.parlays import persist
from fbi.portfolio import correlation as pcorr
from fbi.portfolio.selection import Selection
from fbi.valuation import dependence as dep

AT = datetime(2033, 3, 15, 15, tzinfo=UTC)  # 10:00 Bogotá
MEASURED = {m: dep.Measured(m, rho, se, 12663, 57073) for m, rho, se in (
    ("home_win", 0.01334, 0.00308), ("draw", 0.01530, 0.00338), ("away_win", 0.00868, 0.00306), ("over_2_5", 0.03020, 0.00356),
    ("btts", 0.01038, 0.00293))}
"""The newest ``icc-v1`` estimates in production (``ai.correlation_estimates``, 16 Nov 2026, 12,663 matchdays): all positive and significant."""
NEGATIVE = {m: dep.Measured(m, -0.05, 0.01, 400, 2000) for m in MEASURED}
"""A significantly negative measurement of every market (none exists in production today): what lowers a joint probability."""
SELECTIONS = (("1X2", "Home", "0"), ("1X2", "Draw", "0"), ("1X2", "Away", "0"), ("OU", "Over", "2.5"), ("OU", "Under", "2.5"),
              ("OU", "Over", "1.5"), ("BTTS", "Yes", "0"), ("BTTS", "No", "0"), ("AH", "Home", "-0.5"), ("AH", "Away", "0.5"),
              ("DC", "1X", "0"), ("AH", "Home", "0"), ("OU", "Under", "2.25"))
_ids = itertools.count(1)


def leg(**kw: Any) -> dep.Leg:
    n = next(_ids)
    base: dict[str, Any] = {"ident": n, "fixture_id": 1000 + n, "competition_id": 500 + n, "kickoff_at": AT + timedelta(hours=4),
                            "teams": frozenset({2 * n + 10_000, 2 * n + 10_001}), "market_key": "1X2", "selection": "Home",
                            "line": Decimal(0)}
    base.update(kw)
    return dep.Leg(**base)


def matrix(lh: float = 1.5, la: float = 1.1, rho: float | None = -0.05) -> np.ndarray[Any, np.dtype[np.float64]]:
    return sm.build(sm.Params(lh, la, rho, "dixon_coles" if rho is not None else "poisson")).p


def random_legs(rng: random.Random, n: int) -> list[dep.Leg]:
    """Legs that share matches, teams, competitions, days and windows at random."""
    out: list[dep.Leg] = []
    for _ in range(n):
        m, s, line = rng.choice(SELECTIONS)
        fixture = rng.randrange(6)
        out.append(leg(fixture_id=fixture, competition_id=rng.choice([1, 1, 2, None]),
                       kickoff_at=AT + timedelta(minutes=rng.choice([0, 30, 90, 200, 900, 1500])),
                       teams=frozenset({fixture * 2, fixture * 2 + 1}) if rng.random() < 0.9 else frozenset({rng.randrange(12), 99}),
                       market_key=m, selection=s, line=Decimal(line)))
    return out


# -- the properties -------------------------------------------------------------------------------------------------------------------

def test_property_symmetric_and_every_rho_within_minus_one_and_one() -> None:
    rng = random.Random(20261117)
    mats = {f: matrix(rng.uniform(0.6, 2.6), rng.uniform(0.5, 2.2), rng.choice([None, -0.08, 0.0])) for f in range(6)}
    for _ in range(300):
        a, b = random_legs(rng, 2)
        for measured in (MEASURED, NEGATIVE, None):
            x = dep.estimate(a, b, matrices=mats, measured=measured)
            y = dep.estimate(b, a, matrices=mats, measured=measured)
            assert x == y
            for r in (x.rho, x.low, x.high, x.joint_rho, x.budget_rho):
                assert r is None or -1.0 <= r <= 1.0
            if x.low is not None and x.high is not None and x.rho is not None:
                assert x.low <= x.rho <= x.high


def test_the_same_match_from_its_score_matrix() -> None:
    m = matrix()
    a = leg()
    same = {"fixture_id": a.fixture_id, "teams": a.teams, "competition_id": a.competition_id}
    home_away = dep.estimate(a, leg(selection="Away", **same), matrices={a.fixture_id: m})
    assert home_away.source == dep.SCORE_MATRIX and home_away.rho is not None and home_away.rho < -0.5  # they exclude each other
    over = leg(market_key="OU", selection="Over", line=Decimal("2.5"), **same)
    btts = leg(market_key="BTTS", selection="Yes", **same)
    d = dep.estimate(over, btts, matrices={a.fixture_id: m}, matrix_basis={a.fixture_id: "dixon_coles mv 7"})
    assert d.source == dep.SCORE_MATRIX and d.rho is not None and d.rho > 0.3 and d.joint_rho == d.rho and d.basis.startswith("matrix-v1")
    # a line that can return the stake has no win indicator: the pair is unmeasured and cannot be combined
    ah0 = leg(market_key="AH", selection="Home", line=Decimal(0), **same)
    u = dep.estimate(a, ah0, matrices={a.fixture_id: m})
    assert u.source == dep.UNMEASURED and not u.combinable and u.joint_rho is None and u.budget_rho == dep.PRIORS["same_match"]
    no_matrix = dep.estimate(over, btts)
    assert no_matrix.source == dep.UNMEASURED and not no_matrix.combinable and no_matrix.budget_rho == 0.60


def test_the_matrix_rho_is_portfolio_corr_v1s_joint_distribution_on_what_both_settle() -> None:
    m = matrix(1.7, 0.9)
    provider = pcorr.ScoreMatrixJoint({5: m.tolist()})
    base = Selection(1, 5, AT, AT, 1, None, 10, 11, "1X2", "Home", Decimal(0), 2.0, 0.5, 0.0, None, None, None, 5, AT, None, False,
                     False, "APROBADO", "RECOMMENDED", "approved", None)
    pairs = [(("1X2", "Home"), ("OU", "Over")), (("1X2", "Draw"), ("BTTS", "No")), (("BTTS", "Yes"), ("OU", "Under")),
             (("1X2", "Away"), ("1X2", "Home"))]
    for (ma, sa), (mb, sb) in pairs:
        la = Decimal("2.5") if ma == "OU" else Decimal(0)
        lb = Decimal("2.5") if mb == "OU" else Decimal(0)
        old = provider.correlation(_replace(base, market_key=ma, selection=sa, line=la), _replace(base, decision_id=2, market_key=mb,
                                                                                                   selection=sb, line=lb))
        new = dep.matrix_rho(m, (ma, sa, la), (mb, sb, lb))
        assert old is not None and new == pytest.approx(old, abs=1e-12)


def _replace(s: Selection, **kw: Any) -> Selection:
    return replace(s, **kw)


def test_two_legs_of_one_match_joint_is_the_matrix_itself() -> None:
    """With the legs' own probabilities from the matrix, the joint of two legs of one match is the sum of the cells where both win."""
    m = matrix(1.4, 1.2)
    a = leg()
    b = leg(fixture_id=a.fixture_id, teams=a.teams, competition_id=a.competition_id, market_key="OU", selection="Over", line=Decimal("2.5"))
    pa = sum(float(m[h, x]) for h in range(m.shape[0]) for x in range(m.shape[1]) if h > x)
    pb = sum(float(m[h, x]) for h in range(m.shape[0]) for x in range(m.shape[1]) if h + x > 2)
    both = sum(float(m[h, x]) for h in range(m.shape[0]) for x in range(m.shape[1]) if h > x and h + x > 2)
    assert dep.joint_probability([a, b], [pa, pb], matrices={a.fixture_id: m}) == pytest.approx(both, abs=1e-9)
    assert dep.joint_probability([a, b], [pa, pb]) is None  # no matrix: one match cannot be combined


def test_property_an_unmeasured_or_positive_dependence_never_raises_the_joint_probability() -> None:
    rng = random.Random(8)
    for _ in range(400):
        legs = [leg(fixture_id=n, teams=frozenset({2 * n, 2 * n + 1}), competition_id=rng.choice([1, 2]),
                    kickoff_at=AT + timedelta(minutes=rng.choice([0, 60, 600])), market_key=rng.choice(["1X2", "BTTS"]),
                    selection="Home") for n in range(rng.randint(2, 4))]
        legs = [dep.Leg(x.ident, x.fixture_id, x.competition_id, x.kickoff_at, x.teams, x.market_key,
                        "Home" if x.market_key == "1X2" else "Yes", x.line) for x in legs]
        probs = [rng.uniform(0.2, 0.8) for _ in legs]
        product = float(np.prod(probs))
        for measured in (MEASURED, None, {k: dep.Measured(k, 0.4, 0.3, 50, 200) for k in MEASURED}):  # positive, none, uncertain
            got = dep.joint_probability(legs, probs, measured=measured)
            assert got is not None and got == pytest.approx(product)
        lowered = dep.joint_probability(legs, probs, measured=NEGATIVE)
        assert lowered is not None and lowered <= product + 1e-12


# -- parity with the calculations it unifies -------------------------------------------------------------------------------------------

def _ranked(x: dep.Leg) -> Any:
    return SimpleNamespace(leg=SimpleNamespace(candidate=SimpleNamespace(market_key=x.market_key, selection=x.selection,
                                                                         kickoff_at=x.kickoff_at)),
                           row={"competition_id": x.competition_id})


@pytest.mark.parametrize("measured", [MEASURED, NEGATIVE, {"home_win": dep.Measured("home_win", -0.04, 0.03, 400, 900)}])
def test_parity_with_icc_v1_as_parlay_v5_uses_it_on_the_pairs_it_measures(measured: dict[str, dep.Measured]) -> None:
    """On legs of distinct matches and teams (the parlays' guard) and the selections icc-v1 measures, the pairs a joint probability uses
    and their rho are ``parlay-v5``'s own (``persist.correlated_pairs``), and so is the joint."""
    rng = random.Random(31)
    measured_selections = [s for s in SELECTIONS if dep.measured_market(s[0], s[1], Decimal(s[2])) is not None]
    old_estimates = {m: icc.Estimate(m, e.rho, e.se, e.n_groups, e.n_matches) for m, e in measured.items()}
    for _ in range(300):
        legs = []
        for n in range(rng.randint(2, 5)):
            m, s, line = rng.choice(measured_selections)
            legs.append(leg(fixture_id=n, teams=frozenset({2 * n, 2 * n + 1}), competition_id=rng.choice([1, 1, 2, None]),
                            kickoff_at=AT + timedelta(minutes=rng.choice([0, 60, 900, 1500])), market_key=m, selection=s,
                            line=Decimal(line)))
        old = persist.correlated_pairs(cast(Any, [_ranked(x) for x in legs]), old_estimates)
        index = {x.ident: n for n, x in enumerate(legs)}
        new = sorted((index[d.a], index[d.b], d.joint_rho) for d in dep.pairs(legs, measured=measured) if d.joint_rho)
        assert new == sorted(old)
        probs = [rng.uniform(0.3, 0.7) for _ in legs]
        assert dep.joint_probability(legs, probs, measured=measured) == pytest.approx(icc.joint_probability(probs, old))


def _selection(x: dep.Leg) -> Selection:
    home, away = sorted(x.teams)[0], sorted(x.teams)[-1]
    return Selection(x.ident, x.fixture_id, x.kickoff_at, AT, x.competition_id or 0, None, home, away, x.market_key, x.selection,
                     x.line, 2.0, 0.5, 0.0, None, None, None, 5, AT, None, False, False, "APROBADO", "RECOMMENDED", "approved", None)


def test_parity_with_portfolio_corr_v1_budgets_without_a_matrix() -> None:
    """Without a matrix, corr-v2's budget is portfolio-corr-v1's on every pair, except a total-goals line icc-v1 does not measure, which
    corr-v2 judges by the prior (more cautious: never a smaller budget correlation)."""
    rng = random.Random(77)
    for _ in range(300):
        legs = [x for x in random_legs(rng, 4) if x.competition_id is not None]
        for a, b in itertools.combinations(legs, 2):
            for measured in (MEASURED, NEGATIVE, None):
                old = pcorr.estimate(_selection(a), _selection(b), measured={m: icc.Estimate(m, e.rho, e.se, e.n_groups, e.n_matches)
                                                                             for m, e in (measured or {}).items()})
                new = dep.estimate(a, b, measured=measured)
                other_line = any(x.market_key == "OU" and x.line != dep.OU_MEASURED_LINE for x in (a, b))
                if other_line and old.source == "measured_icc":
                    assert new.budget_rho >= old.budget_rho
                    continue
                assert new.budget_rho == pytest.approx(old.budget_rho), (a, b, old, new)
                assert (new.relation == "none") == (old.source == "none")


def test_the_constants_are_the_ones_of_the_calculations_it_unifies() -> None:
    assert dep.PRIORS["same_match"] == pcorr.SAME_MATCH and dep.PRIORS["same_team"] == pcorr.SAME_TEAM
    assert dep.PRIORS["same_competition_day_window"] == pcorr.SAME_LEAGUE_WINDOW and dep.PRIORS["same_competition"] == pcorr.SAME_LEAGUE
    assert dep.PRIORS["same_window"] == pcorr.SAME_WINDOW and dep.WINDOW == pcorr.WINDOW and dep.GROUP_MIN == pcorr.GROUP_MIN
    assert dep.MIN_GROUPS == icc.MIN_GROUPS and dep.Z == pcorr.Z
    for m, s, _ in SELECTIONS:
        assert dep.polarity(m, s) == persist._polarity(m, s)


def test_a_measured_correlation_carries_its_interval_and_sample_and_only_what_icc_v1_measures() -> None:
    a = leg(competition_id=1, market_key="OU", selection="Over", line=Decimal("2.5"))
    b = leg(competition_id=1, market_key="OU", selection="Under", line=Decimal("2.5"), kickoff_at=a.kickoff_at + timedelta(hours=3))
    d = dep.estimate(a, b, measured=MEASURED)
    assert d.source == dep.MEASURED and d.rho == pytest.approx(-0.0302) and d.sample == 12663 and d.significant
    assert d.low == pytest.approx(-0.0302 - 1.96 * 0.00356) and d.high == pytest.approx(-0.0302 + 1.96 * 0.00356)
    assert d.joint_rho == pytest.approx(-0.0302) and d.budget_rho == 0.0  # it lowers a joint; too small to share a budget
    c = leg(competition_id=1, market_key="OU", selection="Over", line=Decimal("1.5"))
    u = dep.estimate(a, c, measured=MEASURED)
    assert u.source == dep.UNMEASURED and u.rho is None and u.joint_rho == 0.0 and u.budget_rho == dep.PRIORS["same_competition_day_window"]


# -- decision-v1 untouched ------------------------------------------------------------------------------------------------------------

def test_decision_v1_and_every_serving_layer_import_nothing_of_corr_v2_or_value_v2() -> None:
    from .test_valuation_isolation import importers

    serving = ("intel/", "picks/", "familydecisions/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/",
               "knowledge/", "apps/")
    assert not [f for f in importers() if f.startswith(serving)]

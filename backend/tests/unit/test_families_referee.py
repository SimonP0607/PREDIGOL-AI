"""The referee's effect on a count of cards, shrunk towards no effect (plan F10): the multiplier, and whether it earns anything out of sample."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.families import evaluate, referee
from fbi.families.fit import Fitted, Match, fit_family

AT = datetime(2026, 10, 20, 12, tzinfo=UTC)


def season(n: int, *, strict: dict[int, float], seed: int = 5, teams: int = 8, days: int = 700, kappa_noise: float = 0.0) -> list[Match]:
    """``n`` matches whose cards depend on the teams and on a referee (the factor of ``strict[referee]``, 1 for the rest)."""
    rng = np.random.default_rng(seed)
    attack, defence = rng.normal(0.0, 0.15, teams), rng.normal(0.0, 0.15, teams)
    referees = list(range(1, 13))
    out: list[Match] = []
    for i in range(n):
        home, away = int(rng.integers(teams)), int(rng.integers(teams))
        if home == away:
            away = (away + 1) % teams
        ref = int(rng.choice(referees))
        factor = strict.get(ref, 1.0)
        counts = [int(rng.poisson(2.1 * np.exp(attack[a] - defence[d]) * factor)) for a, d in ((home, away), (away, home))]
        out.append(Match(i, AT - timedelta(days=days) + timedelta(days=days) / n * i, home, away, counts[0], counts[1], False, ref))
    return out


def fitted_for(matches: list[Match]) -> Fitted:
    return fit_family(matches, measure="cards_lines_ft", at=AT, xi=0.0019, penalty=8.0)


def test_a_referee_without_known_matches_has_no_multiplier_and_a_balanced_one_stays_near_one() -> None:
    matches = season(900, strict={})
    f = referee.factors(matches, fitted_for(matches))
    assert f and all(0.85 < v < 1.15 for v in f.values()), "no referee is different: none is believed to be"
    few = [Match(9000 + i, AT - timedelta(days=i + 1), 0, 1, 9, 9, False, 99) for i in range(referee.MIN_MATCHES - 1)]
    assert 99 not in referee.factors([*matches, *few], fitted_for(matches)), "four matches are not a referee"


def test_a_strict_referee_gets_a_multiplier_above_one_and_a_lenient_one_below_but_not_all_the_way() -> None:
    matches = season(1500, strict={3: 1.6, 7: 0.6})
    f = referee.factors(matches, fitted_for(matches))
    assert f[3] > 1.2 and f[7] < 0.85, "the direction is found"
    assert f[3] < 1.6 and f[7] > 0.6, "and shrunk towards one: the prior says 'no effect' until the cards say otherwise"
    wide = referee.factors(matches, fitted_for(matches), kappa=5000.0)
    assert abs(wide[3] - 1.0) < abs(f[3] - 1.0), "a heavier prior shrinks more"


def test_a_referee_is_believed_in_proportion_to_what_he_has_given() -> None:
    matches = season(1500, strict={3: 1.6})
    count = {r: sum(1 for m in matches if m.referee_id == r) for r in range(1, 13)}
    few = [m for m in matches if m.referee_id != 3] + [m for m in matches if m.referee_id == 3][:8]
    f_few = referee.factors(few, fitted_for(few))
    f_all = referee.factors(matches, fitted_for(matches))
    assert count[3] > 8 and f_few[3] < f_all[3], "eight matches move the multiplier less than a hundred"


def evaluation_start(matches: list[Match]) -> datetime:
    return matches[len(matches) // 2].kickoff_at


def test_the_referee_earns_log_score_when_there_is_one_and_costs_almost_nothing_when_there_is_not() -> None:
    matches = season(2400, strict={2: 1.5, 5: 1.5, 8: 0.65, 11: 0.65})
    end = AT - timedelta(days=1)
    start = evaluation_start(matches)
    plain = evaluate.walk_forward({1: matches}, measure="cards_lines_ft", start=start, end=end, step_days=28, xi=0.0019, penalty=8.0)
    with_ref = evaluate.walk_forward({1: matches}, measure="cards_lines_ft", start=start, end=end, step_days=28, xi=0.0019, penalty=8.0,
                                     referee_kappa=referee.KAPPA)
    got = evaluate.compare_referee(plain, with_ref)
    assert got["n"] > 500 and got["coverage"] > 0.9
    assert got["total"]["mean"] > 3 * got["total"]["se"] > 0, "a referee that matters adds log score, well beyond its error"
    assert got["home"]["mean"] > 0 and got["away"]["mean"] > 0

    none = season(2400, strict={}, seed=9)
    p0 = evaluate.walk_forward({1: none}, measure="cards_lines_ft", start=evaluation_start(none), end=end, step_days=28, xi=0.0019, penalty=8.0)
    w0 = evaluate.walk_forward({1: none}, measure="cards_lines_ft", start=evaluation_start(none), end=end, step_days=28, xi=0.0019, penalty=8.0,
                               referee_kappa=referee.KAPPA)
    nothing = evaluate.compare_referee(p0, w0)
    assert nothing["total"]["mean"] > -0.01, "with no real effect the shrinkage keeps what it costs small"


def test_two_evaluations_of_different_matches_cannot_be_compared() -> None:
    a, b = season(600, strict={}), season(600, strict={}, seed=6)
    start = evaluation_start(a)
    end = AT - timedelta(days=1)
    ea = evaluate.walk_forward({1: a}, measure="cards_lines_ft", start=start, end=end, xi=0.0019, penalty=8.0)
    eb = evaluate.walk_forward({1: b[:-50]}, measure="cards_lines_ft", start=start, end=end, xi=0.0019, penalty=8.0)
    if [r.fixture_id for r in ea.rows] != [r.fixture_id for r in eb.rows]:
        with pytest.raises(ValueError):
            evaluate.compare_referee(ea, eb)


def test_the_means_are_scaled_for_both_sides() -> None:
    matches = season(600, strict={})
    fit = fitted_for(matches)
    plain, strict = fit.predict(0, 1), fit.predict(0, 1, factor=1.5)
    assert plain is not None and strict is not None
    assert strict.mean_home == pytest.approx(1.5 * plain.mean_home) and strict.mean_away == pytest.approx(1.5 * plain.mean_away)

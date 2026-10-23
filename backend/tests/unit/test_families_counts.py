"""Plan F10 - the counts of a match (the goals of a half, the corners, the cards) as distributions, and the fit of one family on one competition.

Nothing here touches the database. The maths is checked against numbers worked out independently (the variance of a negative binomial, a sum
by hand) and against simulated leagues whose strengths are known.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.stats import nbinom, poisson

from fbi.families import counts
from fbi.families.fit import (
    MIN_TRAIN,
    OUTCOME_KNOWN_AFTER,
    Dispersion,
    Match,
    NotEnoughHistoryError,
    estimate_dispersion,
    fit_family,
)

T0 = datetime(2024, 8, 1, 15, tzinfo=UTC)


# ── the distributions ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_negative_binomial_has_the_mean_and_the_variance_it_is_given() -> None:
    mean, phi = 5.2, 0.18
    pmf = counts.nb_pmf(mean, phi)
    k = np.arange(pmf.size)
    assert counts.tail_mass(pmf) < 1e-6
    assert float((k * pmf).sum()) == pytest.approx(mean, rel=1e-4)
    assert float(((k - mean) ** 2 * pmf).sum()) == pytest.approx(mean + phi * mean**2, rel=1e-3)


def test_with_no_dispersion_it_is_the_poisson_and_it_agrees_with_scipy() -> None:
    pmf = counts.nb_pmf(1.3, 0.0)
    assert np.allclose(pmf, poisson.pmf(np.arange(pmf.size), 1.3), atol=1e-12)
    nb = counts.nb_pmf(4.0, 0.25)
    r = 1.0 / 0.25
    assert np.allclose(nb, nbinom.pmf(np.arange(nb.size), r, r / (r + 4.0)), atol=1e-12)


def test_a_count_with_no_mean_or_a_negative_dispersion_is_refused() -> None:
    with pytest.raises(ValueError):
        counts.nb_pmf(0.0, 0.1)
    with pytest.raises(ValueError):
        counts.nb_pmf(2.0, -0.1)


def test_over_and_under_of_half_and_whole_lines() -> None:
    pmf = np.array([0.1, 0.2, 0.3, 0.25, 0.15])
    half = counts.over_under(pmf, 2.5)
    assert (half.over, half.push, half.under) == pytest.approx((0.4, 0.0, 0.6))
    whole = counts.over_under(pmf, 2.0)
    assert (whole.over, whole.push, whole.under) == pytest.approx((0.4, 0.3, 0.3))
    assert counts.over_under(pmf, -0.5).over == pytest.approx(1.0)


def test_the_total_of_two_independent_counts_is_their_convolution() -> None:
    a, b = counts.nb_pmf(3.0, 0.1, 30), counts.nb_pmf(2.0, 0.1, 30)
    total = counts.convolve(a, b)
    k = np.arange(total.size)
    assert float((k * total).sum()) == pytest.approx(5.0, rel=1e-3)
    assert total[0] == pytest.approx(a[0] * b[0])
    assert total[1] == pytest.approx(a[0] * b[1] + a[1] * b[0])


def test_who_has_more_and_the_handicap_agree() -> None:
    home, away = counts.nb_pmf(6.0, 0.15, 30), counts.nb_pmf(4.0, 0.15, 30)
    win, draw, lose = counts.difference_probs(home, away)
    assert win + draw + lose == pytest.approx(1.0)
    assert win > lose
    level = counts.handicap_probs(home, away, 0.0)
    assert (level.over, level.push, level.under) == pytest.approx((win, draw, lose))
    plus_half = counts.handicap_probs(home, away, 0.5)
    assert plus_half.push == 0.0 and plus_half.over == pytest.approx(win + draw)
    swapped = counts.difference_probs(away, home)
    assert swapped == pytest.approx((lose, draw, win))


def test_the_dispersion_is_recovered_from_simulated_counts_and_is_zero_for_poisson_data() -> None:
    rng = np.random.default_rng(11)
    mu = rng.uniform(2.0, 9.0, 20000)
    phi = 0.2
    r = 1.0 / phi
    y = rng.negative_binomial(r, r / (r + mu))
    assert counts.fit_dispersion(y, mu) == pytest.approx(phi, rel=0.12)
    assert counts.fit_dispersion(rng.poisson(mu), mu) == 0.0


def test_a_distribution_is_scored_by_the_probability_it_gave_to_what_happened() -> None:
    sharp, vague = counts.nb_pmf(5.0, 0.0), counts.nb_pmf(5.0, 1.0)
    assert counts.mean_log_score([sharp], [5]) > counts.mean_log_score([vague], [5]), "the sharper distribution wins when it was right"
    assert counts.mean_log_score([sharp], [200]) == pytest.approx(np.log(1e-12)), "a count beyond the support scores the floor, it is not an error"


# ── the fit of a family ──────────────────────────────────────────────────────────────────────────────────────────────────

N_TEAMS = 12


def league(seasons: int = 3, phi: float = 0.15, seed: int = 5) -> tuple[list[Match], dict[tuple[int, int], tuple[float, float]]]:
    """A double round robin per season with known strengths; the counts are negative binomial."""
    rng = np.random.default_rng(seed)
    attack = rng.normal(0.0, 0.18, N_TEAMS)
    defence = rng.normal(0.0, 0.18, N_TEAMS)
    attack -= attack.mean()
    defence -= defence.mean()
    mu, home_adv = np.log(5.0), 0.12
    r = 1.0 / phi
    matches: list[Match] = []
    truth: dict[tuple[int, int], tuple[float, float]] = {}
    fid, day = 0, 0
    for _ in range(seasons):
        for h in range(N_TEAMS):
            for a in range(N_TEAMS):
                if h == a:
                    continue
                mh = float(np.exp(mu + home_adv + attack[h] - defence[a]))
                ma = float(np.exp(mu + attack[a] - defence[h]))
                fid += 1
                day += 1
                matches.append(Match(fid, T0 + timedelta(days=day), h + 1, a + 1, int(rng.negative_binomial(r, r / (r + mh))),
                                     int(rng.negative_binomial(r, r / (r + ma)))))
                truth[(h + 1, a + 1)] = (mh, ma)
    return matches, truth


def test_a_family_fitted_on_a_simulated_league_finds_the_strengths_that_made_it() -> None:
    matches, truth = league()
    at = matches[-1].kickoff_at + timedelta(days=2)
    fitted = fit_family(matches, measure="corners_ft", at=at, xi=0.0, penalty=0.5)
    assert fitted.n_train == len(matches) and fitted.model.converged
    got = np.array([fitted.means(h, a) for (h, a) in truth])
    want = np.array(list(truth.values()))
    assert np.corrcoef(got[:, 0], want[:, 0])[0, 1] > 0.85 and np.corrcoef(got[:, 1], want[:, 1])[0, 1] > 0.85
    assert float(got.mean()) == pytest.approx(float(want.mean()), rel=0.05)
    assert 0.08 < fitted.dispersion.home < 0.3, "the dispersion the data were made with is 0.15"


def test_a_prediction_is_a_distribution_and_an_unknown_team_gets_none() -> None:
    matches, _ = league(seasons=2)
    at = matches[-1].kickoff_at + timedelta(days=2)
    fitted = fit_family(matches, measure="corners_ft", at=at, xi=0.0, penalty=0.5)
    p = fitted.predict(1, 2)
    assert p is not None
    for pmf in (p.pmf_home, p.pmf_away, p.pmf_total):
        assert float(pmf.sum()) == pytest.approx(1.0)
    assert float((np.arange(p.pmf_total.size) * p.pmf_total).sum()) == pytest.approx(p.mean_home + p.mean_away, rel=0.02)
    assert fitted.predict(1, 999) is None, "a team the model has never seen is not predicted"


def test_a_match_that_is_not_known_yet_is_never_training_material() -> None:
    """The leak test of the family: the result of a match that kicked off less than OUTCOME_KNOWN_AFTER ago must not move the fit by a hair."""
    matches, _ = league(seasons=2)
    at = matches[-1].kickoff_at + OUTCOME_KNOWN_AFTER - timedelta(minutes=1)
    recent = matches[-1]
    assert recent.kickoff_at + OUTCOME_KNOWN_AFTER > at
    tampered = [*matches[:-1], Match(recent.fixture_id, recent.kickoff_at, recent.home_id, recent.away_id, 40, 0)]
    a = fit_family(matches, measure="corners_ft", at=at, xi=0.0, penalty=0.5, dispersion=Dispersion(0.1, 0.1, 0.1))
    b = fit_family(tampered, measure="corners_ft", at=at, xi=0.0, penalty=0.5, dispersion=Dispersion(0.1, 0.1, 0.1))
    assert a.n_train == b.n_train == len(matches) - 1
    assert np.array_equal(a.model.attack, b.model.attack) and a.model.mu == b.model.mu
    later = fit_family(tampered, measure="corners_ft", at=at + timedelta(minutes=2), xi=0.0, penalty=0.5, dispersion=Dispersion(0.1, 0.1, 0.1))
    assert later.n_train == len(matches) and not np.array_equal(later.model.attack, a.model.attack), "two minutes later it is known, and it counts"


def test_too_little_history_is_refused_not_guessed() -> None:
    matches, _ = league(seasons=1)
    assert len(matches) >= MIN_TRAIN
    with pytest.raises(NotEnoughHistoryError):
        fit_family(matches[: MIN_TRAIN - 1], measure="corners_ft", at=matches[-1].kickoff_at + timedelta(days=9), xi=0.0, penalty=0.5)


def test_the_time_decay_gives_the_recent_matches_more_weight() -> None:
    matches, _ = league(seasons=2)
    at = matches[-1].kickoff_at + timedelta(days=1)
    flat = fit_family(matches, measure="corners_ft", at=at, xi=0.0, penalty=0.5, dispersion=Dispersion(0.1, 0.1, 0.1))
    decayed = fit_family(matches, measure="corners_ft", at=at, xi=0.01, penalty=0.5, dispersion=Dispersion(0.1, 0.1, 0.1))
    assert flat.n_train == decayed.n_train and not np.allclose(flat.model.attack, decayed.model.attack)


def test_the_dispersion_of_out_of_sample_predictions_is_found() -> None:
    rng = np.random.default_rng(3)
    mh, ma = rng.uniform(3, 8, 8000), rng.uniform(2, 6, 8000)
    r = 1.0 / 0.12
    yh, ya = rng.negative_binomial(r, r / (r + mh)), rng.negative_binomial(r, r / (r + ma))
    d = estimate_dispersion(yh, mh, ya, ma)
    assert d.home == pytest.approx(0.12, rel=0.2) and d.away == pytest.approx(0.12, rel=0.2)
    assert d.total >= 0.0


# ── the walk-forward evaluation ──────────────────────────────────────────────────────────────────────────────────────────

def _flat_league(seasons: int = 6, phi: float = 0.15, seed: int = 8) -> list[Match]:
    """Twelve identical teams: nothing to learn about them."""
    rng = np.random.default_rng(seed)
    r = 1.0 / phi
    matches: list[Match] = []
    fid = day = 0
    for _ in range(seasons):
        for h in range(N_TEAMS):
            for a in range(N_TEAMS):
                if h == a:
                    continue
                fid += 1
                day += 1
                matches.append(Match(fid, T0 + timedelta(days=day), h + 1, a + 1, int(rng.negative_binomial(r, r / (r + 5.5))),
                                     int(rng.negative_binomial(r, r / (r + 4.5)))))
    return matches


def test_the_family_beats_the_baseline_where_the_teams_differ_and_does_not_where_they_do_not() -> None:
    from fbi.families.evaluate import summarise, walk_forward

    real, _ = league(seasons=6, seed=21)
    start = real[len(real) // 2].kickoff_at
    end = real[-1].kickoff_at + timedelta(days=1)
    ev = walk_forward({1: real}, measure="corners_ft", start=start, end=end, xi=0.0, penalty=1.0)
    s = summarise(ev, lines=(9.5,))
    gain = s["log_score_gain_per_match"]["total"]
    assert s["n"] > 300
    assert gain["mean"] > 2.0 * gain["se"] and gain["mean"] > 0.0, f"teams that differ should be found: {gain}"
    flat = _flat_league()
    ev0 = walk_forward({1: flat}, measure="corners_ft", start=flat[len(flat) // 2].kickoff_at, end=flat[-1].kickoff_at + timedelta(days=1),
                       xi=0.0, penalty=1.0)
    gain0 = summarise(ev0)["log_score_gain_per_match"]["total"]
    assert gain0["mean"] < 2.0 * gain0["se"], f"identical teams: whatever the model finds is noise, it must not look like skill: {gain0}"


def test_a_prediction_never_depends_on_the_outcomes_of_its_own_block() -> None:
    """Change what happened in the block being predicted: every prediction of the block stays exactly as it was."""
    from fbi.families.evaluate import walk_forward

    matches, _ = league(seasons=3, seed=4)
    start = matches[len(matches) // 2].kickoff_at
    end = start + timedelta(days=28)
    inside = {m.fixture_id for m in matches if start <= m.kickoff_at < end}
    assert len(inside) > 20
    tampered = [Match(m.fixture_id, m.kickoff_at, m.home_id, m.away_id, 40, 0) if m.fixture_id in inside else m for m in matches]
    a = walk_forward({1: matches}, measure="corners_ft", start=start, end=end, xi=0.0, penalty=1.0)
    b = walk_forward({1: tampered}, measure="corners_ft", start=start, end=end, xi=0.0, penalty=1.0)
    assert [(r.fixture_id, r.mu_home, r.mu_away, r.base_home) for r in a.rows] == [(r.fixture_id, r.mu_home, r.mu_away, r.base_home) for r in b.rows]
    assert len(a.rows) == len(inside)


def test_the_summary_adds_up() -> None:
    from fbi.families.evaluate import summarise, walk_forward

    matches, _ = league(seasons=4, seed=2)
    ev = walk_forward({1: matches}, measure="corners_ft", start=matches[len(matches) // 2].kickoff_at, end=matches[-1].kickoff_at + timedelta(days=1),
                      xi=0.0, penalty=1.0)
    s = summarise(ev, lines=(8.5, 10.5))
    assert s["n"] == len(ev.rows) > 0
    for line in ("8.5", "10.5"):
        assert sum(b["n"] for b in s["lines"][line]["reliability"]) == s["n"]
        assert 0.0 < s["lines"][line]["over_rate"] < 1.0
    assert summarise(walk_forward({}, measure="corners_ft", start=T0, end=T0 + timedelta(days=30)))["n"] == 0


def test_each_side_and_who_has_more_are_graded_too() -> None:
    from fbi.families.evaluate import summarise, walk_forward

    real, _ = league(seasons=6, seed=21)
    ev = walk_forward({1: real}, measure="corners_ft", start=real[len(real) // 2].kickoff_at, end=real[-1].kickoff_at + timedelta(days=1),
                      xi=0.0, penalty=1.0)
    s = summarise(ev, lines=(9.5,), side_lines=(4.5, 5.5))
    assert set(s["side_lines"]) == {"home 4.5", "home 5.5", "away 4.5", "away 5.5"}
    for d in s["side_lines"].values():
        assert sum(b["n"] for b in d["reliability"]) == s["n"] and 0.0 < d["over_rate"] < 1.0
        assert d["log_loss_gain"] > 0.0, "teams that differ are found on each side too"
    assert s["result"]["log_score_gain"] > 0.0 and s["result"]["se"] > 0.0
    assert summarise(ev)["side_lines"] == {}, "no side lines asked, none graded"

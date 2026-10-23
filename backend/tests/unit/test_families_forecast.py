"""The writer of the family forecasts, the parts that need no database (plan F10): the dispersion measured out of sample, the digest of what a
number was computed from, the shape of what is stored, and the families as configured."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from fbi.families import forecast, history, rows
from fbi.families.fit import (
    NO_DISPERSION,
    OUTCOME_KNOWN_AFTER,
    Dispersion,
    Match,
    fit_family,
    known_at,
    prediction,
)
from fbi.forecasting.match_forecast import BASIS_NO_CHAMPION, UNCALIBRATED
from fbi.forecasting.match_forecast import VERSION as PAGE_VERSION
from fbi.market import catalogue
from fbi.odds.quote_taxonomy import extracted_specs

AT = datetime(2026, 10, 20, 12, tzinfo=UTC)
KEYS = catalogue.key_defs(list(extracted_specs()))
ALL_KEYS = frozenset(KEYS)


def league(n: int, *, over: float = 0.0, seed: int = 7, teams: int = 10, days: int = 300, base: int = 0) -> list[Match]:
    """``n`` finished matches of one competition, evenly spaced over the ``days`` before ``AT`` (the last one a day before it). The count of a
    side is Poisson around its mean, or negative binomial with variance mu + ``over`` mu^2."""
    rng = np.random.default_rng(seed)
    attack, defence = rng.normal(0.0, 0.2, teams), rng.normal(0.0, 0.2, teams)
    out: list[Match] = []
    step = timedelta(days=days) / n
    for i in range(n):
        home, away = int(rng.integers(teams)), int(rng.integers(teams))
        if home == away:
            away = (away + 1) % teams
        counts = []
        for scale in (np.exp(attack[home] - defence[away]), np.exp(attack[away] - defence[home])):
            mean = 5.0 * scale
            if over > 0.0:
                mean *= rng.gamma(1.0 / over, over)
            counts.append(int(rng.poisson(mean)))
        out.append(Match(fixture_id=base + i, kickoff_at=AT - timedelta(days=days) + step * i, home_id=base + home, away_id=base + away,
                         home=counts[0], away=counts[1]))
    return out


def known_in_window(matches: list[Match], days: int = forecast.DISPERSION_DAYS) -> int:
    start = AT - timedelta(days=days)
    return sum(1 for m in matches if start < known_at(m) <= AT)


def test_the_dispersion_is_measured_on_matches_played_after_the_fit_and_known_by_then() -> None:
    matches = league(500, over=0.15)
    got, n = forecast.out_of_sample({1: matches}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    assert n == known_in_window(matches) and n > 100, "every match of the window, no more and no fewer"
    assert 0.03 < got.home < 0.5 and 0.03 < got.away < 0.5, "the extra variance that was put in is seen"
    flat, _ = forecast.out_of_sample({1: league(500, over=0.0)}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    assert flat.home < got.home and flat.total < got.total, "and a count with none is seen as having little"


def test_a_match_is_in_the_window_from_six_hours_after_its_kick_off_and_not_before() -> None:
    matches = league(400, over=0.1)
    _, n = forecast.out_of_sample({1: matches}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    on_time = Match(900, AT - OUTCOME_KNOWN_AFTER, 0, 1, 5, 4)
    late = Match(901, AT - OUTCOME_KNOWN_AFTER + timedelta(minutes=1), 0, 1, 40, 40)
    _, with_both = forecast.out_of_sample({1: [*matches, on_time, late]}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    assert with_both == n + 1, "known exactly at the moment counts; a minute later does not, whatever it says"


def test_a_competition_with_too_many_sides_or_too_little_history_is_left_out() -> None:
    crowd = [Match(i, AT - timedelta(days=200) + timedelta(hours=i), 2 * i, 2 * i + 1, 5, 4) for i in range(forecast.MAX_TEAMS)]
    short = league(60, over=0.1)
    assert forecast._teams(crowd) > forecast.MAX_TEAMS
    assert forecast.out_of_sample({1: crowd, 2: short}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0) == (NO_DISPERSION, 0)
    ok = league(500, over=0.1, seed=3)
    alone = forecast.out_of_sample({3: ok}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    assert forecast.out_of_sample({1: crowd, 2: short, 3: ok}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0) == alone, (
        "the ones left out change nothing of the one that is used")


def test_competitions_are_pooled() -> None:
    a, b = league(500, over=0.1, seed=1), league(500, over=0.1, seed=2, base=1000)
    _, n_a = forecast.out_of_sample({1: a}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    _, n_b = forecast.out_of_sample({2: b}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    _, n_ab = forecast.out_of_sample({1: a, 2: b}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0)
    assert n_ab == n_a + n_b


def test_nothing_to_measure_is_no_dispersion() -> None:
    assert forecast.out_of_sample({}, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0) == (NO_DISPERSION, 0)


# ── what a number was computed from ─────────────────────────────────────────────────────────────────────────────────

SPEC = next(s for s in forecast.SPECS if s.key == "corners_ft")
DISP = Dispersion(0.11, 0.12, 0.08)


def test_the_digest_says_what_the_numbers_came_from() -> None:
    matches = league(300, over=0.1)
    fit = fit_family(matches, measure="corners_ft", at=AT, xi=0.0019, penalty=2.0, dispersion=DISP)
    digest = forecast.input_hash(SPEC, [fit], DISP, 1, 2)
    assert digest == forecast.input_hash(SPEC, [fit], DISP, 1, 2) and len(digest) == 32, "the same inputs, the same digest"
    assert forecast.input_hash(SPEC, [fit], DISP, 2, 1) != digest, "the other match"
    assert forecast.input_hash(SPEC, [fit], Dispersion(0.11, 0.12, 0.09), 1, 2) != digest, "another dispersion"
    later = fit_family(matches[:-20], measure="corners_ft", at=AT, xi=0.0019, penalty=2.0, dispersion=DISP)
    assert forecast.input_hash(SPEC, [later], DISP, 1, 2) != digest, "another training"
    other = next(s for s in forecast.SPECS if s.key == "yellow_ft")
    assert forecast.input_hash(other, [fit], DISP, 1, 2) != digest, "another family"


def test_a_market_is_stored_uncalibrated_with_no_interval_and_the_probabilities_it_was_given() -> None:
    probs = rows.MarketProbs("CORNERS_OU", 9.5, (("Over", 0.55), ("Under", 0.45)))
    f = forecast.market_forecast(77, probs, model="family-corners_ft", model_version_id=5, at=AT, digest="d" * 32)
    assert (f.fixture_id, f.market_key, f.line, f.model, f.model_version_id) == (77, "CORNERS_OU", Decimal("9.5"), "family-corners_ft", 5)
    assert f.calibration == UNCALIBRATED and f.basis == BASIS_NO_CHAMPION and f.calibrator_id is None
    assert [(o.selection, o.p, o.p_model, o.lo, o.hi, o.push) for o in f.outcomes] == [
        ("Over", 0.55, 0.55, None, None, 0.0), ("Under", 0.45, 0.45, None, None, 0.0)]


# ── the families as configured ──────────────────────────────────────────────────────────────────────────────────────

def test_the_families_are_distinct_and_read_measures_that_exist() -> None:
    assert len({s.key for s in forecast.SPECS}) == len({s.model for s in forecast.SPECS}) == len(forecast.SPECS)
    assert {s.family for s in forecast.SPECS} == {"GOALS_HALF", "CORNERS", "CARDS", "YELLOW"}
    for s in forecast.SPECS:
        assert s.model.startswith("family-") and s.model != forecast.VERSION
        for measure in s.measures:
            history.columns_of(measure)
        assert s.spec == f"{s.key}:xi={s.xi},penalty={s.penalty}"
    assert forecast.VERSION == "family-v1" and str(PAGE_VERSION) != forecast.VERSION, "the page of the forecast of a match reads another version"


def test_what_every_family_states_is_in_the_catalogue_and_adds_up() -> None:
    for s in forecast.SPECS:
        n = len(s.measures)
        d = Dispersion(0.12, 0.12, 0.09) if s.over_dispersed else NO_DISPERSION
        preds = [prediction(0.55 + 0.1 * i, 0.4 + 0.1 * i, d) if not s.over_dispersed else prediction(5.2 - 3 * i, 4.4 - 3 * i, d)
                 for i in range(n)]
        markets = s.build(preds, ALL_KEYS)
        assert markets, s.key
        seen: set[tuple[str, float]] = set()
        for m in markets:
            assert m.market_key in KEYS, f"{s.key} states {m.market_key}, which the catalogue does not have"
            assert (m.market_key, m.line) not in seen
            seen.add((m.market_key, m.line))
            assert len(m.outcomes) == KEYS[m.market_key].n_outcomes
            assert m.total == pytest.approx(1.0, abs=1e-12)


def test_a_key_the_catalogue_lacks_is_never_invented() -> None:
    for s in forecast.SPECS:
        n = len(s.measures)
        preds = [prediction(0.6, 0.5, NO_DISPERSION)] * n if not s.over_dispersed else [prediction(5.0, 4.0, Dispersion(0.1, 0.1, 0.08))]
        assert s.build(preds, frozenset()) == [], s.key
        only = frozenset(k for k in ALL_KEYS if k.endswith("_OU") or k in {"OU_1H", "OU_2H", "HTFT"})
        assert {m.market_key for m in s.build(preds, only)} <= only


def test_the_summary_tells_each_family_what_it_did() -> None:
    report = forecast.FamilyReport(at=AT, targets=10, not_fit=2)
    report.specs["corners_ft"] = forecast.SpecReport(competitions_fitted=3, fixtures=6, markets_written=40, rows_written=96, unchanged=2)
    report.specs["corners_ft"].competitions_skipped["short history"] = 4
    text = report.summary()
    assert "10 targets, 2 not fit" in text and "corners_ft: 40 markets written (96 rows)" in text and "short history 4" in text

"""The pure pieces of scripts/research_team_totals.py (REVIEW P5, B3): a team total read off a score matrix, the
provider's value text, the per-book de-vig, the growth and the bootstrap - so the backtest's numbers mean what the
owner's note says they mean."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest
from scipy.stats import poisson
from scripts.research_team_totals import (
    growth,
    p_team_over,
    p_team_over_draws,
    parse_value,
    roi_ci,
    shin_pair,
    team_totals,
)

from fbi.models.scoring import poisson_matrix


def test_the_provider_value_text_and_half_lines_only() -> None:
    assert parse_value("Over 1.5") == ("Over", 1.5)
    assert parse_value("under 0.5") == ("Under", 0.5)
    assert parse_value("Over 1") is None, "a whole line can push: left out"
    assert parse_value("Over 1.25") is None and parse_value("Home") is None and parse_value("") is None


@pytest.mark.parametrize(("side", "lam"), [("home", 1.7), ("away", 0.9)])
@pytest.mark.parametrize("line", [0.5, 1.5, 2.5])
def test_a_team_total_off_the_score_matrix_is_that_teams_poisson_tail(side: str, lam: float, line: float) -> None:
    m = poisson_matrix(1.7, 0.9)
    expected = 1 - poisson.cdf(math.floor(line), lam)
    assert p_team_over(m, side, line) == pytest.approx(expected, abs=1e-5)  # the matrix stops at 10 goals
    draws = p_team_over_draws(np.array([1.7, 1.7]), np.array([0.9, 0.9]), None, side, line)
    assert draws == pytest.approx([expected, expected], abs=1e-5)


def test_the_dixon_coles_correction_leaves_a_teams_own_goals_alone() -> None:
    """tau moves mass between 0-0/1-1 and 1-0/0-1 inside each row and column, so both marginals - a team's own
    goals - are the Poisson ones: Dixon-Coles and Poisson differ on team totals only through the fitted lambdas."""
    lh, la, rho = np.array([1.4]), np.array([1.1]), np.array([-0.1])
    for side in ("home", "away"):
        for line in (0.5, 1.5, 2.5):
            assert p_team_over_draws(lh, la, rho, side, line)[0] == pytest.approx(
                p_team_over_draws(lh, la, None, side, line)[0], abs=1e-9)


def test_a_book_pair_is_de_vigged_and_a_pair_without_margin_is_refused() -> None:
    p = shin_pair(1.80, 2.00)
    assert p is not None and 0.5 < p < 1 / 1.80, "the favourite keeps most of its raw probability"
    assert shin_pair(2.10, 2.10) is None, "1/2.10 + 1/2.10 < 1: no margin, not a real two-way price"


def test_growth_and_the_bootstrap() -> None:
    assert growth(0.5, 2.0) == pytest.approx(0.5 * math.log(1.01) + 0.5 * math.log(0.99))
    assert growth(0.6, 2.0) > 0 > growth(0.45, 2.0)
    point, lo, hi = roi_ci({1: [1.0, -1.0], 2: [-1.0], 3: [0.5]}, random.Random(7))
    assert point == pytest.approx(-0.125) and lo <= point <= hi


def test_one_fixtures_team_totals_out_of_an_odds_answer() -> None:
    item = {"bookmakers": [
        {"id": 8, "bets": [
            {"id": 16, "name": "Total - Home", "values": [{"value": "Over 1.5", "odd": "2.10"},
                                                         {"value": "Under 1.5", "odd": "1.70"},
                                                         {"value": "Over 1", "odd": "1.50"}]},
            {"id": 17, "name": "Total - Away", "values": [{"value": "Over 0.5", "odd": "1.40"}]},
            {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "1.90"},
                                                             {"value": "Under 2.5", "odd": "1.90"}]}]},
        {"id": 3, "bets": [{"id": 17, "values": [{"value": "Over 0.5", "odd": "1.36"},
                                                 {"value": "Under 0.5", "odd": "2.95"}]}]}]}
    assert team_totals(item) == {("home", 1.5, 8): (2.10, 1.70), ("away", 0.5, 3): (1.36, 2.95)}, \
        "half lines with both sides only; other bet types ignored"


def test_a_competition_production_does_not_forecast_is_left_out_not_fitted() -> None:
    """The first run on the server was killed for memory (11 Oct): it fitted club friendlies, thousands of sides,
    which production never forecasts (MAX_GOAL_TEAMS). The backtest leaves them out the same way."""
    from datetime import UTC, datetime, timedelta

    from scripts.research_team_totals import walk_forward

    from fbi.features.data import MatchRecord
    from fbi.predictions.forecast import MAX_GOAL_TEAMS

    start = datetime(2026, 1, 1, tzinfo=UTC)
    teams = MAX_GOAL_TEAMS + 10
    matches = [MatchRecord(n + 1, start + timedelta(hours=n), 99, "friendly", 2026, 2 * n % teams + 1,
                           (2 * n + 1) % teams + 1, 1, 0, False, "finished", 1, 0) for n in range(400)]
    target = matches[-1].fixture_id
    preds, note = walk_forward(matches, [target], family="poisson", hyper={"xi": 0.0, "penalty": 3.0},
                               refit_days=7, lines={target: {("home", 0.5)}})
    assert preds == {} and note["too_many_teams"] == 1 and note.get("fits", 0) == 0

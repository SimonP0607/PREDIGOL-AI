"""Feature version 2: pi-ratings, shot shares, Elo-residual form, league context.

Same discipline as version 1: only what was public before the cut-off, None
where the data says nothing, and the published parameters rather than ones
fitted on the matches later used for evaluation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from fbi.features.data import MatchRecord, TeamStatsPair
from fbi.features.engine import FEATURE_NAMES, FEATURE_VERSION, walk_forward
from fbi.features.pi import PiBook, PiParams, expected_gd

T0 = datetime(2024, 8, 10, 14, 0, tzinfo=UTC)
A, B, C, D = 1, 2, 3, 4


def match(fid: int, days: float, home: int, away: int, gh: int | None, ga: int | None, comp: int = 39) -> MatchRecord:
    return MatchRecord(fid, T0 + timedelta(days=days), comp, "domestic_league", 2024, home, away, gh, ga, False,
                       "finished" if gh is not None else "scheduled")


def test_version_two_extends_version_one() -> None:
    assert FEATURE_VERSION == "fv2.0.0"
    for name in ("elo_diff", "home_ppg5", "pi_home", "pi_expected_gd", "home_sot_share10", "league_elo_mean"):
        assert name in FEATURE_NAMES
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))


def test_pi_ratings_follow_the_published_rule() -> None:
    p = PiParams()
    assert (p.learning_rate, p.cross_venue_rate, p.b, p.c) == (0.035, 0.7, 10.0, 3.0)
    assert expected_gd(0.0, p) == 0.0 and expected_gd(3.0, p) == pytest.approx(9.0)
    assert expected_gd(-1.0, p) == pytest.approx(-(10 ** (1 / 3) - 1))
    book = PiBook(p)
    book.update(A, B, 3, 0)
    psi = 3.0 * math.log10(1 + 3)
    assert book.home[A] == pytest.approx(0.035 * psi), "the home side did better than predicted"
    assert book.away[B] == pytest.approx(-0.035 * psi)
    assert book.away[A] == pytest.approx(0.7 * book.home[A]), "the cross-venue rating learns at gamma"
    assert book.home[B] == pytest.approx(0.7 * book.away[B])
    before = dict(book.home)
    book.update(A, B, 1, 1)
    assert book.home[A] < before[A], "a draw is worse than the expected home win: the rating falls"


def test_a_goal_difference_matching_the_prediction_changes_nothing() -> None:
    book = PiBook()
    book.update(A, B, 0, 0)
    assert book.home.get(A, 0.0) == 0.0 and book.away.get(B, 0.0) == 0.0


def test_shot_shares_come_only_from_matches_with_statistics_before_the_cutoff() -> None:
    history = [match(1, 0, A, B, 1, 0), match(2, 7, B, A, 0, 2), match(3, 14, A, C, 1, 1)]
    target = match(9, 21, A, D, None, None)
    cutoff = target.kickoff_at - timedelta(hours=1)
    stats = {1: TeamStatsPair(10, 5, 4, 1, "football-data.co.uk"), 2: TeamStatsPair(6, 12, 2, 6, "x")}
    (v,), _ = walk_forward(history, [(target, cutoff)], None, stats)
    # A: match 1 home 10 v 5 shots, match 2 away 12 v 6 -> 22 / 33; on target 4+6 v 1+2 -> 10/13
    assert v.values["home_shot_share10"] == pytest.approx(22 / 33)
    assert v.values["home_sot_share10"] == pytest.approx(10 / 13)
    assert v.values["home_stats_n10"] == 2.0, "match 3 has no statistics: not counted, not zero-filled"
    assert v.values["away_shot_share10"] is None and v.values["away_stats_n10"] == 0.0


def test_statistics_of_a_later_match_never_reach_an_earlier_cutoff() -> None:
    history = [match(1, 0, A, B, 1, 0), match(2, 30, A, B, 2, 0)]
    target = match(9, 21, A, B, None, None)
    stats = {2: TeamStatsPair(30, 1, 15, 0, "x")}
    (v,), _ = walk_forward(history, [(target, target.kickoff_at - timedelta(hours=1))], None, stats)
    assert v.values["home_shot_share10"] is None


def test_stats_are_part_of_the_information_set_hash() -> None:
    history = [match(1, 0, A, B, 1, 0)]
    target = match(9, 7, A, B, None, None)
    cutoff = target.kickoff_at - timedelta(hours=1)
    (without,), _ = walk_forward(history, [(target, cutoff)])
    (with_stats,), _ = walk_forward(history, [(target, cutoff)], None, {1: TeamStatsPair(9, 3, 4, 1, "x")})
    assert without.input_hash != with_stats.input_hash


def test_elo_residual_form_and_league_context() -> None:
    history = [match(1, 0, A, B, 1, 0), match(2, 7, C, A, 1, 0), match(3, 14, B, C, 2, 2)]
    target = match(9, 21, A, B, None, None)
    (v,), elo = walk_forward(history, [(target, target.kickoff_at - timedelta(hours=1))])
    exp_first = next(r.expected_score for r in elo if r.team_id == A and r.fixture_id == 1)
    exp_second = next(r.expected_score for r in elo if r.team_id == A and r.fixture_id == 2)
    assert v.values["home_elo_resid10"] == pytest.approx(((1.0 - exp_first) + (0.0 - exp_second)) / 2)
    assert v.values["league_home_gd_avg"] == pytest.approx((1 + 1 + 0) / 3)
    assert v.values["league_elo_mean"] is not None
    assert v.values["pi_home"] is not None and v.values["pi_expected_gd"] is not None


def test_a_team_never_seen_has_neutral_ratings_and_no_form() -> None:
    target = match(9, 1, A, B, None, None)
    (v,), _ = walk_forward([], [(target, target.kickoff_at - timedelta(hours=1))])
    assert v.values["pi_home"] == 0.0 and v.values["pi_expected_gd"] == 0.0
    assert v.values["home_elo_resid10"] is None and v.values["league_home_gd_avg"] is None

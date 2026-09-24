"""The feature engine cannot see the future.

Leakage is the failure that makes a worthless model look brilliant: a
backtest that accidentally lets a match's own result, or anything after its
kick-off, into its features reports a skill that disappears the day the model
meets real fixtures. These tests pin the engine's time discipline from every
side a bug could come in.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from fbi.features.data import MatchRecord
from fbi.features.elo import EloBook, EloParams, expected_score, margin_multiplier
from fbi.features.engine import (
    FEATURE_NAMES,
    RESULT_AVAILABLE_AFTER,
    LeakageError,
    walk_forward,
)

T0 = datetime(2024, 8, 10, 14, 0, tzinfo=UTC)
A, B, C, D = 1, 2, 3, 4


def match(fid: int, days: float, home: int, away: int, gh: int | None, ga: int | None, *,
          comp: int = 39, season: int = 2024, status: str | None = None, neutral: bool = False) -> MatchRecord:
    return MatchRecord(
        fixture_id=fid, kickoff_at=T0 + timedelta(days=days), competition_id=comp,
        competition_type="domestic_league", season=season, home_team_id=home, away_team_id=away,
        goals_home=gh, goals_away=ga, is_neutral=neutral,
        status_group=status or ("finished" if gh is not None else "scheduled"),
    )


HISTORY = [
    match(1, 0, A, B, 2, 0),
    match(2, 0, C, D, 1, 1),
    match(3, 7, B, C, 0, 3),
    match(4, 7, D, A, 1, 2),
    match(5, 14, A, C, 1, 1),
    match(6, 14, B, D, 2, 2),
]
TARGET = match(7, 21, A, D, 3, 0)  # its own result is in the history too
CUTOFF = TARGET.kickoff_at - timedelta(hours=1)


def features_for(history: list[MatchRecord], target: MatchRecord = TARGET, cutoff: datetime = CUTOFF):
    vectors, _ = walk_forward(history, [(target, cutoff)])
    assert len(vectors) == 1
    return vectors[0]


# ---------------------------------------------------------------------------
# Time discipline
# ---------------------------------------------------------------------------

def test_the_target_own_result_never_enters_its_features() -> None:
    with_own = features_for([*HISTORY, TARGET])
    without_own = features_for(HISTORY)
    assert with_own.values == without_own.values
    assert with_own.input_hash == without_own.input_hash
    assert with_own.n_inputs == 6


def test_results_after_the_cutoff_change_nothing() -> None:
    before = features_for(HISTORY)
    later = [match(8, 30, A, B, 9, 0), match(9, 25, D, C, 0, 7)]
    after = features_for([*HISTORY, *later])
    assert after.values == before.values and after.input_hash == before.input_hash


def test_a_result_is_unknown_until_three_hours_after_its_kickoff() -> None:
    """A match that kicked off two hours before the cut-off has not finished
    (or has not been published): it is not an input."""
    recent = match(10, 0, B, C, 5, 0)
    recent = replace(recent, kickoff_at=CUTOFF - timedelta(hours=2))
    assert features_for([*HISTORY, recent]).n_inputs == 6
    known = replace(recent, kickoff_at=CUTOFF - RESULT_AVAILABLE_AFTER - timedelta(seconds=1))
    assert features_for([*HISTORY, known]).n_inputs == 7


def test_a_result_that_becomes_available_exactly_at_the_cutoff_is_excluded() -> None:
    edge = replace(match(11, 0, B, C, 1, 0), kickoff_at=CUTOFF - RESULT_AVAILABLE_AFTER)
    assert features_for([*HISTORY, edge]).n_inputs == 6, "ties go against the input"


def test_the_newest_input_is_always_strictly_before_the_cutoff() -> None:
    v = features_for(HISTORY)
    assert v.newest_input_at is not None and v.newest_input_at < v.data_cutoff


def test_a_cutoff_after_kickoff_is_refused() -> None:
    with pytest.raises(LeakageError):
        walk_forward(HISTORY, [(TARGET, TARGET.kickoff_at + timedelta(minutes=1))])


def test_editing_a_past_result_changes_the_hash_and_editing_a_future_one_does_not() -> None:
    base = features_for(HISTORY)
    past_edit = [replace(HISTORY[0], goals_home=0), *HISTORY[1:]]
    assert features_for(past_edit).input_hash != base.input_hash
    future = match(12, 40, A, B, 1, 0)
    assert features_for([*HISTORY, future]).input_hash == base.input_hash
    assert features_for([*HISTORY, replace(future, goals_home=4)]).input_hash == base.input_hash


def test_a_postponed_fixtures_zero_zero_is_not_a_result() -> None:
    ghost = match(13, 16, A, B, 0, 0, status="postponed")
    assert features_for([*HISTORY, ghost]).n_inputs == 6


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def test_every_declared_feature_is_produced() -> None:
    assert set(features_for(HISTORY).values) == set(FEATURE_NAMES)


def test_no_history_is_null_not_zero() -> None:
    first = match(20, 0, A, B, None, None)
    v = features_for([], target=first, cutoff=first.kickoff_at - timedelta(hours=1))
    for name in ("home_gf_avg5", "home_ppg5", "home_rest_days", "home_attack", "home_sos5", "league_goals_avg"):
        assert v.values[name] is None, f"{name} with no history must be None, not a number"
    assert v.values["home_history_n"] == 0.0
    assert v.values["elo_home"] == EloParams().initial, "an unseen team starts at the prior"


def test_form_rest_and_venue_splits_are_exact() -> None:
    v = features_for(HISTORY)
    # A: 2-0 (h) v B, 2-1 (a) at D, 1-1 (h) v C -> gf 5/3, ga 2/3, points 7/3
    assert v.values["home_gf_avg5"] == pytest.approx(5 / 3)
    assert v.values["home_ga_avg5"] == pytest.approx(2 / 3)
    assert v.values["home_ppg5"] == pytest.approx(7 / 3)
    assert v.values["home_gf_home5"] == pytest.approx(1.5), "home matches only: 2 and 1"
    assert v.values["home_rest_days"] == pytest.approx(7.0), "last played day 14, target day 21"
    # D away: 1-1 at C, 2-2 at B -> away_gf_away5 = 1.5
    assert v.values["away_gf_away5"] == pytest.approx(1.5)
    assert v.values["home_season_matches"] == 3.0


def test_strength_is_relative_to_the_competition_average() -> None:
    v = features_for(HISTORY)
    goals = 2 + 0 + 1 + 1 + 0 + 3 + 1 + 2 + 1 + 1 + 2 + 2
    per_team = goals / (2 * 6)
    assert v.values["league_goals_avg"] == pytest.approx(goals / 6)
    assert v.values["home_attack"] == pytest.approx((5 / 3) / per_team)


# ---------------------------------------------------------------------------
# Elo
# ---------------------------------------------------------------------------

def test_elo_is_zero_sum_and_moves_the_right_way() -> None:
    book = EloBook(EloParams())
    up = book.update(A, B, 3, 0, neutral=False)
    assert up.home_after > up.home_before and up.away_after < up.away_before
    assert up.home_after - up.home_before == pytest.approx(-(up.away_after - up.away_before))
    assert up.multiplier == pytest.approx((11 + 3) / 8)


def test_home_advantage_is_off_at_a_neutral_venue() -> None:
    assert expected_score(1500, 1500, advantage=0) == pytest.approx(0.5)
    assert expected_score(1500, 1500, advantage=65) > 0.5


def test_margin_multiplier_follows_eloratings() -> None:
    assert [margin_multiplier(g) for g in (0, 1, -1, 2, 3, 5)] == [1.0, 1.0, 1.0, 1.5, 14 / 8, 16 / 8]


def test_elo_history_is_walk_forward_and_chained() -> None:
    _, history = walk_forward(HISTORY, [])
    by_team: dict[int, list] = {}
    for h in history:
        by_team.setdefault(h.team_id, []).append(h)
    for rows in by_team.values():
        for prev, nxt in pairwise(rows):
            assert nxt.rating_before == pytest.approx(prev.rating_after), "each match starts where the last ended"
            assert nxt.kickoff_at > prev.kickoff_at


def test_elo_is_deterministic() -> None:
    a = features_for(HISTORY)
    b = features_for(list(reversed(HISTORY)))
    assert a.values == b.values and a.input_hash == b.input_hash, "input order must not matter"


def test_ratings_going_into_a_match_ignore_that_match() -> None:
    v_win = features_for([*HISTORY, TARGET])
    v_loss = features_for([*HISTORY, replace(TARGET, goals_home=0, goals_away=5)])
    assert v_win.values["elo_home"] == v_loss.values["elo_home"]

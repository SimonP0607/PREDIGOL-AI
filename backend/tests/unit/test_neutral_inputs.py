"""What a neutral-venue flag does to the inputs the models are keyed by (plan F0, defect 1).

The flag reaches a model through ``MatchRecord.is_neutral``. The models, the stored feature sets and the stored
forecasts are keyed by hashes of their inputs ("no new information, no new row"), so the flag has to be part of those
hashes when it is set - and ONLY then: a history with no neutral match must hash exactly as it always did, or deploying
the code (rule OFF) would rewrite every feature set and every forecast."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fbi.backtesting.walkforward import prediction_hash, train_hash
from fbi.features.data import MatchRecord
from fbi.features.engine import walk_forward

T0 = datetime(2024, 8, 10, 14, 0, tzinfo=UTC)
A, B, C, D = 1, 2, 3, 4


def match(fid: int, days: float, home: int, away: int, gh: int | None, ga: int | None, *,
          neutral: bool = False) -> MatchRecord:
    return MatchRecord(
        fixture_id=fid, kickoff_at=T0 + timedelta(days=days), competition_id=39, competition_type="domestic_league",
        season=2024, home_team_id=home, away_team_id=away, goals_home=gh, goals_away=ga, is_neutral=neutral,
        status_group="finished" if gh is not None else "scheduled")


def history(neutral_ids: frozenset[int] = frozenset()) -> list[MatchRecord]:
    return [match(1, 0, A, B, 2, 0, neutral=1 in neutral_ids), match(2, 0, C, D, 1, 1, neutral=2 in neutral_ids),
            match(3, 7, B, C, 0, 3, neutral=3 in neutral_ids), match(4, 7, D, A, 1, 2, neutral=4 in neutral_ids)]


def target(neutral: bool = False) -> MatchRecord:
    return match(7, 21, A, D, None, None, neutral=neutral)


def vector(hist: list[MatchRecord], tgt: MatchRecord):
    vectors, _ = walk_forward(hist, [(tgt, tgt.kickoff_at - timedelta(hours=1))])
    return vectors[0]


LEGACY = hashlib.sha256(b"1:2-0;2:1-1;3:0-3;4:1-2;").hexdigest()
"""The digest of the four results above as it was computed before the flag existed: ``id:score;`` in order."""


def test_a_history_with_no_neutral_match_hashes_as_it_always_did() -> None:
    assert vector(history(), target()).input_hash == LEGACY


def test_a_neutral_match_in_the_history_is_a_different_input() -> None:
    v = vector(history(frozenset({3})), target())
    assert v.input_hash == hashlib.sha256(b"1:2-0;2:1-1;3:0-3|n;4:1-2;").hexdigest()
    assert v.input_hash != LEGACY


def test_the_flag_of_the_fixture_itself_is_an_input_too() -> None:
    v = vector(history(), target(neutral=True))
    assert v.input_hash == hashlib.sha256(b"1:2-0;2:1-1;3:0-3;4:1-2;|target-neutral").hexdigest()
    assert v.input_hash != LEGACY


def test_a_neutral_match_changes_the_ratings_it_feeds() -> None:
    # at a neutral venue the home side gets no advantage, so the same win moves the ratings further
    plain = vector(history(), target()).values
    neutral = vector(history(frozenset({1})), target()).values
    assert plain["elo_diff"] != neutral["elo_diff"]
    assert vector(history(), target(neutral=True)).values["is_neutral"] == 1.0


def test_the_training_hash_marks_neutral_matches_and_only_them() -> None:
    plain = [match(1, 0, A, B, 2, 0), match(2, 1, C, D, 1, 1)]
    assert train_hash(plain) == hashlib.sha256(b"1:2-0;2:1-1;").hexdigest()
    marked = [match(1, 0, A, B, 2, 0, neutral=True), match(2, 1, C, D, 1, 1)]
    assert train_hash(marked) == hashlib.sha256(b"1:2-0|n;2:1-1;").hexdigest()


def test_a_forecast_is_keyed_by_the_training_set_and_by_the_venue_of_the_fixture() -> None:
    th = train_hash([match(1, 0, A, B, 2, 0)])
    assert prediction_hash(th, target()) == th, "a home fixture is keyed as it always was"
    assert prediction_hash(th, target(neutral=True)) == th + "|n"
    assert prediction_hash(th, target(neutral=True)) != prediction_hash(th, target())

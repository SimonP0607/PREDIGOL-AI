"""RP-1.5: the table of the twelve stages and the pure judgements of the stall check."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.ops import freshness

AT = datetime(2026, 12, 7, 12, 0, tzinfo=UTC)


def test_the_table_has_the_twelve_stages_of_the_plan_in_order() -> None:
    assert [s.number for s in freshness.STAGES] == list(range(1, 13))
    assert len({s.key for s in freshness.STAGES}) == 12
    assert all(s.alarm_es.strip() for s in freshness.STAGES)


def test_a_stage_without_a_reader_names_the_piece_that_delivers_it() -> None:
    without = [s for s in freshness.STAGES if s.number not in freshness.READERS]
    assert [s.number for s in without] == [6, 7, 8, 9, 10, 12]
    assert all(s.delivered_by and s.delivered_by.startswith("RP-") for s in without)


def test_a_sign_of_life_older_than_the_limit_is_a_stop() -> None:
    limit = timedelta(hours=36)
    assert freshness.judge_age(AT - timedelta(hours=35, minutes=59), AT, limit) == "al_dia"
    assert freshness.judge_age(AT - timedelta(hours=36), AT, limit) == "al_dia"
    assert freshness.judge_age(AT - timedelta(hours=36, minutes=1), AT, limit) == "parada"


def test_no_sign_at_all_is_a_stop_only_after_the_limit_has_been_watched() -> None:
    limit = timedelta(days=8)
    assert freshness.judge_age(None, AT, limit) == "sin_registro"
    assert freshness.judge_age(None, AT, limit, since=AT - timedelta(days=3)) == "sin_registro"
    assert freshness.judge_age(None, AT, limit, since=AT - timedelta(days=9)) == "parada"


def test_more_than_the_limit_is_a_stop_the_limit_itself_is_not() -> None:
    assert freshness.judge_count(20, 20) == "al_dia"
    assert freshness.judge_count(21, 20) == "parada"


def test_an_alarm_is_only_a_stop() -> None:
    stage = freshness.STAGES[0]
    readings = [freshness.Reading(stage, s, "x") for s in freshness.STATUSES]
    assert [r.status for r in freshness.alarms(readings)] == ["parada"]

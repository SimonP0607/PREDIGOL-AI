"""Plan F0, defect 3: the arithmetic of late news in the longitudinal memory (memory-v2), without a database.

A day's row is never rewritten, so what that day learns late is its fresh delta less what is already recorded for it; the
rest of memory-v2 (the queries) is tested on a real database in tests/integration/test_intel_memory_late.py."""

from __future__ import annotations

import pytest

from fbi.intel import memory

SETTLED_LATE = {
    "decisions": 2, "settled": 2, "wins": 1, "losses": 1, "voids": 0, "profit_flat": 0.8, "clv_sum": 0.03, "clv_n": 2,
    "by_state": {"INVESTIGACION": 2}, "by_selection": {"Home": 1, "Draw": 1}, "verdicts": {"MERECIDO": 1, "ERROR": 1},
    "results": ["W", "L"],
}
AT_WRITING = {
    "decisions": 1, "settled": 1, "wins": 0, "losses": 1, "voids": 0, "profit_flat": -1.0, "clv_sum": 0.01, "clv_n": 1,
    "by_state": {"INVESTIGACION": 1}, "by_selection": {"Draw": 1}, "verdicts": {"ERROR": 1}, "results": ["L"],
}


def test_late_news_is_what_the_data_say_now_less_what_was_recorded() -> None:
    news = memory.late_news(SETTLED_LATE, AT_WRITING)
    assert news == {
        "decisions": 1, "settled": 1, "wins": 1, "profit_flat": 1.8, "clv_sum": 0.02, "clv_n": 1,
        "by_state": {"INVESTIGACION": 1}, "by_selection": {"Home": 1}, "verdicts": {"MERECIDO": 1}, "results": ["W"],
    }, "only what changed: no zero entry, no entry the row already has"


def test_nothing_new_is_nothing_booked() -> None:
    assert memory.late_news(AT_WRITING, AT_WRITING) == {}
    assert memory._empty(memory.late_news(AT_WRITING, AT_WRITING))
    assert memory.late_news(None, None) == {}


def test_a_day_that_was_never_recorded_books_all_of_it() -> None:
    """A night the worker missed: nothing recorded, so everything the day has is news."""
    assert memory.late_news(AT_WRITING, None) == {
        "decisions": 1, "settled": 1, "losses": 1, "profit_flat": -1.0, "clv_sum": 0.01, "clv_n": 1,
        "by_state": {"INVESTIGACION": 1}, "by_selection": {"Draw": 1}, "verdicts": {"ERROR": 1}, "results": ["L"],
    }


def test_news_that_went_away_is_booked_as_negative() -> None:
    """The data say less than the row recorded (a decision withdrawn): the correction is booked, not hidden."""
    news = memory.late_news({}, AT_WRITING)
    assert news["decisions"] == -1 and news["settled"] == -1 and news["losses"] == -1 and news["profit_flat"] == 1.0
    assert news["by_selection"] == {"Draw": -1}


def test_a_changed_verdict_is_a_pair_of_counters() -> None:
    news = memory.late_news({"verdicts": {"MERECIDO": 1}}, {"verdicts": {"ERROR": 1}})
    assert news == {"verdicts": {"MERECIDO": 1, "ERROR": -1}}


def test_plus_undoes_minus() -> None:
    news = memory._minus(SETTLED_LATE, AT_WRITING)
    back = memory._plus(news, AT_WRITING)
    assert back["decisions"] == 2 and back["wins"] == 1 and back["losses"] == 1
    assert back["profit_flat"] == pytest.approx(0.8)
    assert back["by_selection"] == {"Home": 1, "Draw": 1} and back["verdicts"] == {"MERECIDO": 1, "ERROR": 1}
    assert sorted(back["results"]) == ["L", "W"]


def test_results_subtract_as_a_multiset() -> None:
    assert memory._minus({"results": ["W", "L", "W", "L"]}, {"results": ["L", "W"]})["results"] == ["W", "L"]
    assert memory._minus({"results": ["W"]}, {"results": ["W", "W"]})["results"] == []


def test_merge_without_late_news_is_what_it_always_was() -> None:
    state = memory.merge(None, AT_WRITING)
    assert state["decisions"] == 1 and state["losses"] == 1 and state["last10"] == ["L"]
    assert state["roi_flat"] == -1.0 and state["hit_rate"] == 0.0


def test_merge_books_the_late_news_after_the_days_own_delta_and_oldest_day_first() -> None:
    yesterday = {"decisions": 1, "settled": 1, "wins": 1, "losses": 0, "profit_flat": 0.5, "results": ["W"]}
    delta = {
        "decisions": 1, "settled": 1, "wins": 0, "losses": 1, "profit_flat": -1.0, "results": ["L"],
        "late": {
            "2032-10-04": {"decisions": 1, "settled": 1, "wins": 1, "profit_flat": 1.0, "results": ["W"]},
            "2032-10-03": {"decisions": 1, "settled": 1, "losses": 1, "profit_flat": -1.0, "results": ["L"]},
        },
    }
    state = memory.merge(memory.merge(None, yesterday), delta)
    assert state["decisions"] == 4 and state["settled"] == 4 and state["wins"] == 2 and state["losses"] == 2
    assert state["profit_flat"] == pytest.approx(-0.5)
    assert state["last10"] == ["W", "L", "L", "W"], "the day's own result, then the oldest late one, then the newer"
    assert "late" not in state, "late news is booked in the numbers, not kept as a key of the state"


def test_merge_of_late_news_alone_changes_the_numbers_and_the_rates() -> None:
    prev = memory.merge(None, AT_WRITING)
    state = memory.merge(prev, {"late": {"2032-10-04": memory.late_news(SETTLED_LATE, AT_WRITING)}})
    assert state["decisions"] == 2 and state["settled"] == 2 and state["wins"] == 1
    assert state["hit_rate"] == 0.5 and state["roi_flat"] == pytest.approx(0.4)
    assert state["clv_mean"] == pytest.approx(0.015)
    assert state["verdicts"] == {"ERROR": 1, "MERECIDO": 1}
    assert state["by_selection"] == {"Draw": 1, "Home": 1}


def test_a_counter_that_returns_to_zero_leaves_no_entry() -> None:
    prev = memory.merge(None, {"verdicts": {"ERROR": 1}})
    state = memory.merge(prev, {"late": {"2032-10-04": {"verdicts": {"MERECIDO": 1, "ERROR": -1}}}})
    assert state["verdicts"] == {"MERECIDO": 1}

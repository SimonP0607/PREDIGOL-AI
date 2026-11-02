"""Research v2 against the database: one search per entity and topic, shared by every match that asks while the answer is fresh.

The plan's test for this phase: a team with two matches in three days is searched once. Here the "search" is a function that counts its
calls; the cache is the real table, the real scope (``entity``, migration 0114) and the real expiry. One transaction, rolled back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import cache

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


class Search:
    """A search that remembers how many times it was asked and answers with what it was asked about."""

    def __init__(self, what: str = "availability of team 10") -> None:
        self.calls = 0
        self.what = what

    def __call__(self) -> dict[str, Any]:
        self.calls += 1
        return {"found": self.what, "n": self.calls}


def test_a_team_with_two_matches_in_three_days_is_searched_once(db: psycopg.Connection) -> None:
    search = Search()
    match_a, match_b = T0 + timedelta(days=1), T0 + timedelta(days=3)
    first, searched_first = cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=match_a)
    second, searched_second = cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=1), nearest_kickoff=match_a)
    third, searched_third = cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=2), nearest_kickoff=match_b)
    assert (searched_first, searched_second, searched_third) == (True, False, False) and search.calls == 1
    assert first == second == third == {"found": "availability of team 10", "n": 1}, "the second match, and the agent that asks later, read the same answer"


def test_another_team_another_topic_another_kind_are_other_questions(db: psycopg.Connection) -> None:
    search = Search()
    asks = [("TEAM", 10, "availability"), ("TEAM", 11, "availability"), ("TEAM", 10, "preview"), ("PLAYER", 10, "availability"), ("COACH", 10, "confirmation")]
    for kind, entity, topic in asks:
        assert cache.through(db, kind, entity, topic, search, at=T0, nearest_kickoff=T0 + timedelta(days=2))[1] is True
    assert search.calls == len(asks)
    for kind, entity, topic in asks:
        assert cache.through(db, kind, entity, topic, search, at=T0 + timedelta(minutes=5), nearest_kickoff=T0 + timedelta(days=2))[1] is False
    assert search.calls == len(asks), "and each is read from its own row"


def test_an_answer_expires_when_its_topic_says_and_is_then_searched_again(db: psycopg.Connection) -> None:
    search = Search()
    kickoff = T0 + timedelta(days=2)
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=kickoff)
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=23, minutes=59), nearest_kickoff=kickoff)[1] is False
    again, searched = cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=24), nearest_kickoff=kickoff)
    assert searched is True and again["n"] == 2 and search.calls == 2, "a day later it is searched again, and the new answer replaces the old"
    assert db.execute("SELECT count(*) FROM ai.research_cache WHERE scope = 'entity'").fetchone() == (1,)


def test_the_nearest_kickoff_shortens_the_life_of_the_answer_for_everybody(db: psycopg.Connection) -> None:
    search = Search()
    tonight = T0 + timedelta(hours=6)  # the team plays tonight and again in three days
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=tonight)
    row = db.execute("SELECT expires_at - fetched_at FROM ai.research_cache WHERE key = 'rk-v2:team:10:availability'").fetchone()
    assert row == (timedelta(hours=4),)
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=3), nearest_kickoff=tonight)[1] is False
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=4), nearest_kickoff=tonight)[1] is True


def test_a_search_that_fails_leaves_nothing_in_the_cache_and_is_asked_again(db: psycopg.Connection) -> None:
    def broken() -> dict[str, Any]:
        raise TimeoutError("the search provider did not answer")

    with pytest.raises(TimeoutError):
        cache.through(db, "TEAM", 10, "availability", broken, at=T0, nearest_kickoff=None)
    assert db.execute("SELECT count(*) FROM ai.research_cache").fetchone() == (0,)
    assert cache.through(db, "TEAM", 10, "availability", Search(), at=T0, nearest_kickoff=None)[1] is True


def test_the_keys_of_v2_and_of_v1_live_in_the_same_table_without_reading_each_other(db: psycopg.Connection) -> None:
    """A search of v1 (the hash of a query) and a page of v1 (``<fixture>:<url>``) are untouched by the rows of v2, and the other way round."""
    cache.put(db, "search", "0123456789abcdef0123456789abcdef01234567", {"v": 1}, at=T0, ttl=timedelta(hours=24))
    cache.put(db, "url", "555:https://example.com/p", {"seen": True}, at=T0, ttl=timedelta(days=7))
    search = Search()
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=None)
    page = cache.url_key("https://example.com/p")
    assert cache.get(db, "url", page, at=T0) is None, "the page of v1 was read for a match; v2 has not read it yet"
    cache.put(db, "url", page, {"seen": True}, at=T0, ttl=timedelta(days=7))
    assert cache.get(db, "url", "555:https://example.com/p", at=T0) == {"seen": True}
    assert cache.get(db, "url", page, at=T0 + timedelta(hours=1)) == {"seen": True}, "and now every match that finds that page finds it read"
    assert db.execute("SELECT count(*) FROM ai.research_cache").fetchone() == (4,)


def test_asking_for_what_the_server_does_not_know_searches_nothing(db: psycopg.Connection) -> None:
    search = Search()
    for kind, entity, topic in [("CLUB", 1, "availability"), ("TEAM", 0, "availability"), ("TEAM", 1, "news")]:
        with pytest.raises(ValueError):
            cache.through(db, kind, entity, topic, search, at=T0, nearest_kickoff=None)
    assert search.calls == 0 and db.execute("SELECT count(*) FROM ai.research_cache").fetchone() == (0,)


# ── fresh is judged when the question is asked ─────────────────────────────────────────────────────────────────────

def test_what_was_found_a_day_before_the_match_is_not_fresh_for_the_pass_of_the_last_hours(db: psycopg.Connection) -> None:
    """The plan's trigger: a ``pre`` pass whose last search is more than four hours old searches again. The answer was found 14 h before the
    kick-off, so it lives a day; at 3 h before the kick-off the asker is inside the last twelve hours and four hours is what it accepts."""
    search = Search()
    kickoff = T0 + timedelta(hours=14)
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=kickoff)
    assert db.execute("SELECT expires_at - fetched_at FROM ai.research_cache WHERE key = 'rk-v2:team:10:availability'").fetchone() == (timedelta(hours=24),)
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=1), nearest_kickoff=kickoff)[1] is False, "still the early bucket"
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=1, minutes=59), nearest_kickoff=kickoff)[1] is False
    answer, searched = cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=11), nearest_kickoff=kickoff)
    assert searched is True and answer["n"] == 2 and search.calls == 2, "3 h before the match the 11-hour-old answer is not accepted"


def test_inside_the_last_hours_an_answer_is_accepted_for_four_hours_and_not_a_minute_more(db: psycopg.Connection) -> None:
    search = Search()
    kickoff = T0 + timedelta(hours=5)
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=kickoff)
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=3, minutes=59), nearest_kickoff=kickoff)[1] is False
    assert cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=4), nearest_kickoff=kickoff)[1] is True
    assert search.calls == 2


def test_a_reuse_is_counted_only_when_it_is_a_reuse(db: psycopg.Connection) -> None:
    """``hits`` is what the admin view and the metrics call reuse: an answer refused for being too old for this asker is not a reuse."""
    search = Search()
    kickoff = T0 + timedelta(hours=14)
    cache.through(db, "TEAM", 10, "availability", search, at=T0, nearest_kickoff=kickoff)
    cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(minutes=30), nearest_kickoff=kickoff)
    assert db.execute("SELECT hits FROM ai.research_cache WHERE key = 'rk-v2:team:10:availability'").fetchone() == (1,)
    cache.through(db, "TEAM", 10, "availability", search, at=T0 + timedelta(hours=11), nearest_kickoff=kickoff)  # refused, searched again
    assert db.execute("SELECT hits FROM ai.research_cache WHERE key = 'rk-v2:team:10:availability'").fetchone() == (1,), "the refusal counted nothing"
    assert search.calls == 2


def test_get_with_a_maximum_age_leaves_alone_what_it_refuses(db: psycopg.Connection) -> None:
    cache.put(db, "entity", "rk-v2:team:1:preview", {"a": 1}, at=T0, ttl=timedelta(hours=24))
    assert cache.get(db, "entity", "rk-v2:team:1:preview", at=T0 + timedelta(hours=5), max_age=timedelta(hours=4)) is None
    assert cache.get(db, "entity", "rk-v2:team:1:preview", at=T0 + timedelta(hours=5), max_age=timedelta(hours=6)) == {"a": 1}
    assert cache.get(db, "entity", "rk-v2:team:1:preview", at=T0 + timedelta(hours=5)) == {"a": 1}, "without a maximum age it is what it always was"
    assert db.execute("SELECT hits FROM ai.research_cache WHERE key = 'rk-v2:team:1:preview'").fetchone() == (2,)

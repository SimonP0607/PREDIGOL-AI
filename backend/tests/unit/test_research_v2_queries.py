"""Research v2, the questions: the key of a search, the query of one side of a match and the topic each level of the tiered search answers.

Pure: no database and no network. The research itself (``fbi.ai.entity_research``) is held on a built world in ``tests/integration``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from fbi.ai import collectors as c
from fbi.ai import research

KICKOFF = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
COUNTRIES = {"es": "Colombia", "pt": "Brazil", "it": "Italy", "fr": "France", "de": "Germany", "nl": "Netherlands", "tr": "Turkey",
             "en": "England"}


def old_key(query: str, bucket: str, level: int) -> str:
    """The key the collector computed inline before research v2: the answers cached under it must stay valid."""
    return hashlib.sha256((f"{query}|{bucket}" if level == 1 else f"{query}|{bucket}|L{level}").lower().encode()).hexdigest()[:40]


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("bucket", ["early", "late"])
def test_the_key_of_a_search_is_the_one_it_always_had(level: int, bucket: str) -> None:
    query = c.queries_for("Millonarios", "Santa Fe", KICKOFF, "Colombia", "Liga BetPlay", levels=3)[level - 1]
    assert c.search_key(query, bucket, level) == old_key(query, bucket, level) and len(c.search_key(query, bucket, level)) == 40


def test_a_golden_key_guards_the_answers_already_cached() -> None:
    """Literal values computed with the formula the collector had inline: a change of the key would make every cached search be paid again."""
    assert c.search_key("Millonarios vs Santa Fe", "early", 1) == "5516e95bb26d8cfb631183f86ce9db02d13d64e1"
    assert c.search_key("Millonarios vs Santa Fe", "late", 2) == "1c15a90e152201c7b27af6e8e255b9f740b434e6"
    assert c.search_key("A", "early", 1) != c.search_key("A", "early", 2) != c.search_key("A", "late", 2), "level and bucket are in the key"
    assert c.search_key("A", "early", 1) == c.search_key("a", "EARLY", 1), "the key ignores case"


@pytest.mark.parametrize("level", [1, 2, 3])
def test_both_sides_ask_the_query_of_the_match_so_an_answer_cached_for_it_is_the_answer(level: int) -> None:
    for country in (*COUNTRIES.values(), None):
        match_query = c.queries_for("Home FC", "Away FC", KICKOFF, country, "Cup", levels=(level,))[0]
        assert c.query_for_sides(level, ("home", "away"), home="Home FC", away="Away FC", kickoff=KICKOFF, country=country,
                                 competition="Cup") == match_query
        assert c.query_for_sides(level, ("away", "home"), home="Home FC", away="Away FC", kickoff=KICKOFF, country=country,
                                 competition="Cup") == match_query


@pytest.mark.parametrize("lang", sorted(COUNTRIES))
@pytest.mark.parametrize("level", [1, 2])
def test_one_side_asks_about_that_team_alone_in_the_language_of_the_competition(lang: str, level: int) -> None:
    for side, team, other in (("home", "Home FC", "Away FC"), ("away", "Away FC", "Home FC")):
        q = c.query_for_sides(level, (side,), home="Home FC", away="Away FC", kickoff=KICKOFF, country=COUNTRIES[lang], competition="Cup")
        assert q.startswith(team) and other not in q and "2026-10-27" in q and "{" not in q and "  " not in q
        assert ("Cup" in q) is (level == 2), "the official statements are asked in the competition's name; the team news are not"
        assert q == (c.TEAM_NEWS_ONE if level == 1 else c.OFFICIAL_ONE)[lang].format(team=team, competition="Cup", when="2026-10-27").strip()


def test_the_preview_is_about_the_match_even_when_one_side_asks() -> None:
    both = c.queries_for("Home FC", "Away FC", KICKOFF, "England", "Cup", levels=(3,))[0]
    assert c.query_for_sides(3, ("home",), home="Home FC", away="Away FC", kickoff=KICKOFF, country="England", competition="Cup") == both


def test_a_search_with_no_side_or_no_level_is_not_a_search() -> None:
    with pytest.raises(ValueError, match="at least one side"):
        c.query_for_sides(1, (), home="A", away="B", kickoff=KICKOFF, country=None, competition=None)
    with pytest.raises(ValueError, match="at least one side"):
        c.query_for_sides(1, ("both",), home="A", away="B", kickoff=KICKOFF, country=None, competition=None)
    with pytest.raises(ValueError, match="unknown level"):
        c.query_for_sides(4, ("home",), home="A", away="B", kickoff=KICKOFF, country=None, competition=None)


def test_every_language_of_the_match_queries_has_its_query_for_one_team() -> None:
    assert set(c.TEAM_NEWS_ONE) == set(c.TEAM_NEWS) == set(c.OFFICIAL_ONE) == set(c.OFFICIAL)
    for lang in c.TEAM_NEWS:
        assert "{team}" in c.TEAM_NEWS_ONE[lang] and "{when}" in c.TEAM_NEWS_ONE[lang]
        assert "{team}" in c.OFFICIAL_ONE[lang] and "{competition}" in c.OFFICIAL_ONE[lang] and "{when}" in c.OFFICIAL_ONE[lang]


def test_each_level_of_the_tiered_search_answers_one_topic_of_the_closed_list() -> None:
    assert set(research.LEVEL_TOPIC) == set(c.LEVELS) and set(research.LEVEL_TOPIC.values()) == set(research.BY_KEY)
    for level, topic in research.LEVEL_TOPIC.items():
        assert level in research.BY_KEY[topic].levels, "the level is one of the levels the topic is served by"
    assert set(research.TOPIC_ENTITY) == set(research.BY_KEY) and set(research.TOPIC_ENTITY.values()) == {"TEAM", "MATCH"}
    assert research.TOPIC_ENTITY["preview"] == "MATCH", "a preview is about a match; the teams' news are about teams"

"""Research v2 (plan, phase 2): the keys of the cache and the freshness of each topic, as pure functions.

What is held here: a key of v2 names an entity and a topic and never a match, it cannot be mistaken for a key of v1 (so the two generations
share the table for the week they run side by side), the address of a page is reduced to what makes it that page, and the freshness of v2 is
the freshness of v1 until a week of comparison says otherwise. The database side (the new scope, the read-through that searches once) is
in ``tests/integration/test_cache_v2.py``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest

from fbi.ai import cache, collectors, research
from fbi.ai.contracts.claim import SubjectKind

AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


# ── the key of an entity and a topic ────────────────────────────────────────────────────────────────────────────────

def test_the_kinds_of_entity_are_the_subjects_a_claim_can_be_about() -> None:
    assert set(cache.ENTITY_KINDS) == set(get_args(SubjectKind)), "a claim of claim-v1 can always be filed under its subject"


def test_the_key_is_the_version_the_kind_the_id_and_the_topic_and_nothing_about_a_match() -> None:
    assert cache.entity_key("TEAM", 42, "availability") == "rk-v2:team:42:availability"
    assert cache.entity_key("PLAYER", 7, "confirmation") == "rk-v2:player:7:confirmation"
    keys = {cache.entity_key(kind, 42, topic) for kind in cache.ENTITY_KINDS for topic in research.BY_KEY}
    assert len(keys) == len(cache.ENTITY_KINDS) * len(research.BY_KEY), "kind and topic both tell two keys apart"
    assert cache.entity_key("TEAM", 42, "availability") != cache.entity_key("TEAM", 43, "availability")
    assert all(len(k) < 500 for k in keys), "the cache keeps the first 500 characters of a key: a longer one would collide"


def test_a_key_of_v2_cannot_be_mistaken_for_a_key_of_v1() -> None:
    """v1 keys: forty hexadecimal characters (a search) or ``<fixture>:<url>``. Neither starts with the version of v2."""
    v1 = ["0123456789abcdef0123456789abcdef01234567", "123456:https://example.com/page"]
    v2 = [cache.entity_key("TEAM", 1, "availability"), cache.url_key("https://example.com/page")]
    for key in v2:
        assert key.startswith(f"{cache.KEY_VERSION}:") and not re.fullmatch(r"[0-9a-f]{40}", key) and not re.match(r"\d+:", key)
    assert not any(k.startswith(cache.KEY_VERSION) for k in v1)


@pytest.mark.parametrize("kind, entity_id, topic", [
    ("team", 1, "availability"), ("CLUB", 1, "availability"), ("", 1, "availability"),
    ("TEAM", 0, "availability"), ("TEAM", -3, "availability"), ("TEAM", True, "availability"), ("TEAM", "7", "availability"),
    ("TEAM", 1.0, "availability"), ("TEAM", 1, "news"), ("TEAM", 1, ""), ("TEAM", 1, "AVAILABILITY"),
])
def test_a_key_is_never_made_of_something_the_server_does_not_know(kind: str, entity_id: int, topic: str) -> None:
    with pytest.raises(ValueError):
        cache.entity_key(kind, entity_id, topic)


# ── the address of a page ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given, canonical", [
    ("HTTPS://Example.COM/a/b", "https://example.com/a/b"),
    ("https://example.com:443/a", "https://example.com/a"),
    ("http://example.com:80/a", "http://example.com/a"),
    ("https://example.com:8443/a", "https://example.com:8443/a"),
    ("https://example.com/a/", "https://example.com/a"),
    ("https://example.com/", "https://example.com"),
    ("https://example.com/a#section-2", "https://example.com/a"),
    ("https://example.com/a?utm_source=x&utm_medium=y&id=5", "https://example.com/a?id=5"),
    ("https://example.com/a?fbclid=abc&gclid=def&id=5", "https://example.com/a?id=5"),
    ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
    ("https://example.com/a?UTM_Campaign=z&id=5", "https://example.com/a?id=5"),
    ("https://example.com/a?FBCLID=abc&Gclid=def&id=5", "https://example.com/a?id=5"),
    ("https://example.com/a?q=&id=5", "https://example.com/a?id=5&q="),  # a blank value is a value
    ("  https://example.com/a  ", "https://example.com/a"),
    ("https://example.com/A/B", "https://example.com/A/B"),  # the path is case-sensitive: two pages
])
def test_the_address_of_a_page_keeps_what_makes_it_that_page(given: str, canonical: str) -> None:
    assert cache.canonical_url(given) == canonical


def test_the_same_page_reached_two_ways_is_one_key_and_two_pages_are_two() -> None:
    a = cache.url_key("https://www.example.com/news/injury-report?utm_source=newsletter#top")
    b = cache.url_key("HTTPS://www.example.com/news/injury-report/?utm_medium=social")
    assert a == b and a.startswith("rk-v2:url:") and len(a) == len("rk-v2:url:") + 40
    assert cache.url_key("https://www.example.com/news/injury-report?id=1") != cache.url_key("https://www.example.com/news/injury-report?id=2")
    assert cache.url_key("https://www.example.com/news/a") != cache.url_key("https://www.example.com/news/b")
    assert cache.url_key("https://a.example.com/x") != cache.url_key("https://b.example.com/x")


def test_the_key_of_a_page_does_not_carry_the_match() -> None:
    """In v1 the same page read for two matches was read twice (``<fixture>:<url>``): in v2 there is no fixture in the key to differ."""
    assert cache.url_key("https://example.com/p") == cache.url_key("https://example.com/p")
    assert "123456" not in cache.url_key("https://example.com/p")


@pytest.mark.parametrize("bad", ["", "   ", "example.com/a", "ftp://example.com/a", "javascript:alert(1)", "file:///etc/passwd",
                                 "https:///no-host", "data:text/html;base64,AAAA", "//example.com/a"])
def test_only_a_web_address_has_a_key(bad: str) -> None:
    with pytest.raises(ValueError):
        cache.url_key(bad)


# ── freshness ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_v2_starts_with_the_freshness_of_v1_for_every_topic() -> None:
    """Declared: the week of comparison must measure the change of key, not a change of how long an answer is reused."""
    assert (cache.EARLY_TTL, cache.LATE_TTL, cache.LATE_WINDOW) == (collectors.EARLY_TTL, collectors.LATE_TTL, collectors.LATE_WINDOW)
    assert set(cache.FRESHNESS) == set(research.BY_KEY), "every topic the AI may ask for has a freshness, and no other"
    assert all(v == (collectors.EARLY_TTL, collectors.LATE_TTL) for v in cache.FRESHNESS.values())


@pytest.mark.parametrize("hours_to_kickoff, ttl", [(72, 24), (13, 24), (12.01, 24), (12, 4), (11.99, 4), (3, 4), (0, 4), (-2, 4)])
def test_the_nearest_kickoff_decides_how_long_an_answer_lives(hours_to_kickoff: float, ttl: int) -> None:
    kickoff = AT + timedelta(hours=hours_to_kickoff)
    for topic in research.BY_KEY:
        assert cache.ttl_for(topic, nearest_kickoff=kickoff, at=AT) == timedelta(hours=ttl), (topic, hours_to_kickoff)


def test_with_no_kickoff_known_an_answer_lives_the_long_time() -> None:
    assert cache.ttl_for("availability", nearest_kickoff=None, at=AT) == timedelta(hours=24)


def test_fresh_until_is_the_moment_found_plus_the_time_it_lives() -> None:
    assert cache.fresh_until("availability", retrieved_at=AT, nearest_kickoff=AT + timedelta(days=2)) == AT + timedelta(hours=24)
    assert cache.fresh_until("preview", retrieved_at=AT, nearest_kickoff=AT + timedelta(hours=5)) == AT + timedelta(hours=4)
    assert cache.fresh_until("confirmation", retrieved_at=AT, nearest_kickoff=None) == AT + timedelta(hours=24)
    # found 20 h before kick-off: the answer lives a day (the bucket is judged at the moment it was found, not a day later)
    assert cache.fresh_until("availability", retrieved_at=AT, nearest_kickoff=AT + timedelta(hours=20)) == AT + timedelta(hours=24)


def test_a_topic_the_server_does_not_know_has_no_freshness() -> None:
    with pytest.raises(KeyError):
        cache.ttl_for("news", nearest_kickoff=None, at=AT)

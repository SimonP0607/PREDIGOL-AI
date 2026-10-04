"""Provenance on plain values: a claim cites pages this run retrieved, and its grade is what
those pages support - the model can lower it, never raise it."""

from __future__ import annotations

from typing import Any

from fbi.analyst.budget import UNKNOWN_PRICE, cost, price_of
from fbi.analyst.provenance import Grade, SourceRegistry, accept_claims, allowed_grade, kind_of
from fbi.analyst.search import SearchResult

AT = "2026-10-04T11:00:00+00:00"


def page(url: str, published: str | None = "2026-10-03T09:00:00+00:00") -> SearchResult:
    return SearchResult(url, "t", url.split("/")[2], published, AT, "snippet")


def test_domains_are_matched_on_the_host_not_the_text() -> None:
    assert kind_of("https://www.premierleague.com/news/1") == "official"
    assert kind_of("https://es.uefa.com/x") == "official", "a subdomain of an official site"
    assert kind_of("https://www.bbc.co.uk/sport/football/1") == "reputable"
    assert kind_of("https://premierleague.com.fake-news.example/x") == "other", "a look-alike host is not official"
    assert kind_of("https://blog.example/premierleague.com") == "other"


def test_grades_follow_the_sources() -> None:
    assert allowed_grade([page("https://www.premierleague.com/a")]) is Grade.CONFIRMED
    assert allowed_grade([page("https://www.premierleague.com/a", None)]) is Grade.REPORTED, \
        "an undated official page is not a confirmation"
    assert allowed_grade([page("https://www.bbc.co.uk/a"), page("https://www.marca.com/b")]) is Grade.CONFIRMED, \
        "two independent reputable outlets"
    assert allowed_grade([page("https://www.bbc.co.uk/a"), page("https://www.bbc.co.uk/b")]) is Grade.REPORTED, \
        "two pages of one outlet are one source"
    assert allowed_grade([page("https://rumours.example/a")]) is Grade.RUMOR


def test_claims_are_resolved_graded_and_refused_with_a_reason() -> None:
    reg = SourceRegistry()
    s1 = reg.add(page("https://www.premierleague.com/news/1"))
    s2 = reg.add(page("https://rumours.example/x"))
    assert reg.add(page("https://www.premierleague.com/news/1")) == s1, "one page, one id"
    raw: list[dict[str, Any]] = [
        {"ref": "C1", "claim": "Player X is ruled out for the weekend.", "source_ids": [s1], "confidence": "CONFIRMED",
         "fixture_id": 10},
        {"ref": "C2", "claim": "Player Y might be dropped.", "source_ids": [s2], "confidence": "CONFIRMED",
         "team_id": 5},
        {"ref": "C3", "claim": "Player Z is injured.", "source_ids": ["S9"], "confidence": "REPORTED"},
        {"ref": "C4", "claim": "Something about another match.", "source_ids": [s1], "confidence": "RUMOR",
         "fixture_id": 999},
        {"ref": "C5", "claim": "No source at all here.", "source_ids": [], "confidence": "RUMOR"},
        {"ref": "C1", "claim": "A second C1.", "source_ids": [s1], "confidence": "RUMOR"},
        {"ref": "C6", "claim": "The official page says so too.", "source_ids": [s1], "confidence": "RUMOR"},
    ]
    accepted, rejected = accept_claims(raw, reg, fixture_ids={10}, team_ids={5})
    grades = {c.ref: c.grade for c in accepted}
    assert grades == {"C1": Grade.CONFIRMED, "C2": Grade.RUMOR, "C6": Grade.RUMOR}, \
        "a grade is lowered to what the source supports, and a modest grade is kept"
    assert accepted[0].source.url == "https://www.premierleague.com/news/1" and accepted[0].fixture_id == 10
    reasons = {r.ref: r.reason for r in rejected}
    assert "not retrieved in this run" in reasons["C3"] and "not in this report" in reasons["C4"]
    assert reasons["C5"] == "no source cited" and reasons["C1"] == "duplicate claim id"


def test_an_unknown_model_is_priced_at_the_most_expensive_rate() -> None:
    assert price_of("claude-haiku-4-5-20251001") != UNKNOWN_PRICE
    assert price_of("some-new-model") == UNKNOWN_PRICE and price_of(None) == UNKNOWN_PRICE
    assert float(cost("claude-haiku-4-5", 1_000_000, 100_000)) == 1.5

"""Home's summary of the news (plan de Inicio, 3.3), pure: «confirmed» only with an official source or two distinct outlets (two
pages or two subdomains of one site are one outlet; an aggregator never corroborates), the best few first, at most two from one
match, and at most one rumour - only with room left and never of low relevance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from fbi.api.contracts.news import (
    NewsClaim,
    NewsItem,
    NewsSource,
    TodayNewsItem,
    TodayNewsMatch,
)
from fbi.api.services import news

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)
_ids = count(1)


def source(name: str = "www.sport.es", tier: str = "media", url: str | None = "https://www.sport.es/a") -> NewsSource:
    return NewsSource(name=name, tier=tier, url=url, published_at=NOW, published_day_only=False)  # type: ignore[arg-type]


def item(status: str = "PROBABLE", *, sources: list[NewsSource] | None = None, relevance: str = "high",
         age_h: float = 1, claims: int = 1) -> NewsItem:
    found = sources if sources is not None else [source()]
    return NewsItem(
        id=f"n{next(_ids)}", kind="injury", status=status, relevance=relevance, team=None, player="Alguien",  # type: ignore[arg-type]
        claims=[NewsClaim(text="Es baja.", lang="es", assertion="out", sources=found) for _ in range(claims)],
        published_at=NOW - timedelta(hours=age_h), published_day_only=False, seen_at=NOW)


def entry(it: NewsItem, fixture: int = 1) -> TodayNewsItem:
    match = TodayNewsMatch(fixture_id=fixture, kickoff_at=NOW + timedelta(hours=3), status_group="scheduled", home="A",
                           away="B", competition="Liga")
    return TodayNewsItem(match=match, item=it)


@pytest.mark.parametrize(("name", "url", "expected"), [
    ("www.marca.com", "https://www.marca.com/futbol/a.html", "marca.com"),
    ("es.marca.com", "https://es.marca.com/b", "marca.com"),
    ("eltiempo.com.co", "https://www.eltiempo.com.co/deportes/x", "eltiempo.com.co"),
    ("bbc.co.uk", "https://www.bbc.co.uk/sport/1", "bbc.co.uk"),
    ("Sport.es", None, "sport.es"),
    ("a site", None, "a site"),
])
def test_the_outlet_behind_a_source(name: str, url: str | None, expected: str) -> None:
    assert news.outlet_key(source(name, url=url)) == expected


def test_one_official_source_confirms() -> None:
    assert news.corroborated(item("CONFIRMED", sources=[source("laliga.com", "official", "https://laliga.com/x")]))


def test_two_distinct_outlets_confirm() -> None:
    both = [source("www.marca.com", url="https://www.marca.com/1"), source("www.as.com", "journalist", "https://as.com/2")]
    assert news.corroborated(item("CONFIRMED", sources=both))


def test_one_outlet_twice_does_not_confirm() -> None:
    same = [source("www.marca.com", url="https://www.marca.com/1"), source("es.marca.com", url="https://es.marca.com/2")]
    assert not news.corroborated(item("CONFIRMED", sources=same))
    assert news.for_home(item("CONFIRMED", sources=same)).status == "PROBABLE"


def test_aggregators_and_social_posts_never_corroborate() -> None:
    mixed = [source("besoccer.com", "aggregator", "https://besoccer.com/1"), source("x.com", "social", "https://x.com/2"),
             source("www.marca.com", url="https://www.marca.com/3")]
    assert not news.corroborated(item("CONFIRMED", sources=mixed))


def test_a_contradiction_is_never_confirmed() -> None:
    official = [source("laliga.com", "official", "https://laliga.com/x")]
    assert not news.corroborated(item("CONFIRMED", sources=official, claims=2))


def test_confirmed_corroborated_stays_and_probable_is_untouched() -> None:
    official = item("CONFIRMED", sources=[source("laliga.com", "official", "https://laliga.com/x")])
    assert news.for_home(official).status == "CONFIRMED"
    assert news.for_home(item("PROBABLE")).status == "PROBABLE"


def test_the_summary_is_confirmed_first_then_the_most_relevant_then_the_newest() -> None:
    official = [source("laliga.com", "official", "https://laliga.com/x")]
    old_high = entry(item("PROBABLE", relevance="high", age_h=9), 1)
    new_high = entry(item("PROBABLE", relevance="high", age_h=1), 2)
    medium = entry(item("PROBABLE", relevance="medium", age_h=0.5), 3)
    firm = entry(item("CONFIRMED", sources=official, relevance="medium", age_h=20), 4)
    got = news.digest([old_high, medium, new_high, firm], 3)
    assert [g.match.fixture_id for g in got] == [4, 2, 1]


def test_a_confirmed_nobody_corroborated_competes_as_probable() -> None:
    lone = entry(item("CONFIRMED", relevance="medium", age_h=1), 1)
    high = entry(item("PROBABLE", relevance="high", age_h=5), 2)
    got = news.digest([lone, high], 2)
    assert [g.match.fixture_id for g in got] == [2, 1]
    assert [g.item.status for g in got] == ["PROBABLE", "PROBABLE"]


def test_at_most_the_limit_and_two_from_one_match() -> None:
    same = [entry(item("PROBABLE", age_h=h), 1) for h in (1, 2, 3, 4)]
    other = entry(item("PROBABLE", age_h=8), 2)
    got = news.digest([*same, other], 3)
    assert [g.match.fixture_id for g in got] == [1, 1, 2]
    assert len(news.digest(same, 2)) == 2
    assert len(news.digest(same, 3)) == 2, "a third of one match is not taken to fill the space"


def test_one_rumour_at_most_only_with_room_and_never_of_low_relevance() -> None:
    firm = [entry(item("PROBABLE"), 1), entry(item("PROBABLE"), 2)]
    rumors = [entry(item("RUMOR", sources=[source("x.com", "social", "https://x.com/1")], age_h=h), 3 + h) for h in (1, 2)]
    got = news.digest([*firm, *rumors], 3)
    assert [g.item.status for g in got] == ["PROBABLE", "PROBABLE", "RUMOR"]
    assert news.digest([*firm, *rumors], 2) == news.digest(firm, 2), "no room: no rumour"
    low = entry(item("RUMOR", relevance="low"), 9)
    assert news.digest([*firm[:1], low], 3) == news.digest(firm[:1], 3)


def test_the_outdated_and_contradictory_stay_out() -> None:
    assert news.digest([entry(item("OUTDATED")), entry(item("CONTRADICTORY"))], 3) == []


def test_a_rumour_alone_is_a_summary_of_one() -> None:
    got = news.digest([entry(item("RUMOR"))], 3)
    assert [g.item.status for g in got] == ["RUMOR"]

"""BE-012 - the switched-off connector of The Odds API: no key, no request; the budget refuses before the provider does; the key never
reaches a log line or an exception; a price is only ever put on the one fixture that agrees."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import structlog
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs

from fbi.core.clock import now
from fbi.core.errors import (
    ConfigError,
    ProviderError,
    ProviderPayloadError,
    QuotaExhaustedError,
    RateLimitError,
)
from fbi.domain.market_probability import DevigMethod
from fbi.providers.the_odds_api import client as client_module
from fbi.providers.the_odds_api.client import MemoryCreditStore, TheOddsApiClient
from fbi.providers.the_odds_api.identity import KnownFixture, match_fixture
from fbi.providers.the_odds_api.parse import parse_events, reference_fair
from fbi.providers.the_odds_api.settings import FREE_PLAN_CREDITS, TheOddsApiSettings

KEY = "k3y-that-must-never-be-printed"
KICKOFF = "2026-11-21T15:00:00Z"


def book(key: str, home: float, draw: float, away: float, *, teams: tuple[str, str] = ("Arsenal", "Chelsea")) -> dict[str, object]:
    return {"key": key, "title": key.title(), "markets": [{"key": "h2h", "last_update": "2026-11-20T10:00:00Z", "outcomes": [
        {"name": teams[0], "price": home}, {"name": "Draw", "price": draw}, {"name": teams[1], "price": away}]}]}


def event(*books: dict[str, object], event_id: str = "ev1", home: str = "Arsenal", away: str = "Chelsea", at: str = KICKOFF) -> dict[str, object]:
    return {"id": event_id, "sport_key": "soccer_epl", "commence_time": at, "home_team": home, "away_team": away, "bookmakers": list(books)}


def settings(**kw: Any) -> TheOddsApiSettings:
    return TheOddsApiSettings(_env_file=None, key=SecretStr(KEY), **kw)  # type: ignore[call-arg]


def http_with(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.the-odds-api.com", transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def answer(events: list[dict[str, object]], *, last: int = 1, remaining: int = 499, used: int = 1) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(events), headers={"x-requests-last": str(last), "x-requests-remaining": str(remaining), "x-requests-used": str(used)})


# --- settings ----------------------------------------------------------------------------------------------------------------------

def test_without_a_key_the_connector_is_off_and_cannot_even_be_built() -> None:
    off = TheOddsApiSettings(_env_file=None)  # type: ignore[call-arg]
    assert off.enabled is False
    with pytest.raises(ConfigError, match="FBI_THEODDSAPI_KEY"):
        TheOddsApiClient(off)


def test_the_key_is_never_in_the_text_of_the_settings() -> None:
    s = settings()
    assert s.enabled and KEY not in repr(s) and KEY not in str(s) and KEY not in s.model_dump_json()


def test_only_the_free_plan_exists_and_the_budget_cannot_pass_it() -> None:
    assert settings().monthly_credit_budget == int(FREE_PLAN_CREDITS * 0.9)
    with pytest.raises(ValidationError):
        settings(plan="paid")
    with pytest.raises(ValidationError):
        settings(monthly_credit_budget=FREE_PLAN_CREDITS + 1)
    with pytest.raises(ValidationError):
        settings(regions="moon")


# --- parse -------------------------------------------------------------------------------------------------------------------------

def test_the_reference_book_loses_its_margin_and_the_three_add_up_to_one() -> None:
    [ev] = parse_events([event(book("pinnacle", 2.10, 3.50, 3.60), book("bet365", 2.0, 3.4, 3.5))])
    fair = reference_fair(ev, "pinnacle")
    assert fair is not None and set(fair) == {"home", "draw", "away"}
    assert sum(float(p) for p in fair.values()) == pytest.approx(1.0)
    assert fair["home"].method is DevigMethod.SHIN and fair["home"].overround > 1.0
    assert float(fair["home"]) > float(fair["away"]) > 0.0
    assert reference_fair(ev, "a-book-that-is-not-there") is None


def test_a_book_with_a_malformed_h2h_is_dropped_and_the_loss_is_written_down() -> None:
    two_outcomes: dict[str, object] = {"key": "odd", "markets": [{"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 2.0}, {"name": "Chelsea", "price": 2.0}]}]}
    wrong_names = book("elsewhere", 2.0, 3.0, 4.0, teams=("Arsenal FC", "Chelsea FC"))
    no_price = book("noprice", 2.0, 3.0, 4.0)
    no_price["markets"][0]["outcomes"][0]["price"] = "n/a"  # type: ignore[index]
    one_or_less = book("flat", 1.0, 3.0, 4.0)
    [ev] = parse_events([event(book("pinnacle", 2.1, 3.5, 3.6), two_outcomes, wrong_names, no_price, one_or_less)])
    assert [p.bookmaker for p in ev.prices] == ["pinnacle"]
    assert len(ev.dropped) == 4 and all(":" in line for line in ev.dropped)


def test_an_answer_that_is_not_a_list_is_an_error_and_a_broken_event_is_skipped() -> None:
    with pytest.raises(ProviderPayloadError):
        parse_events({"message": "quota"})
    assert parse_events([{"id": "x"}, "nonsense", event(book("pinnacle", 2.1, 3.5, 3.6))]).__len__() == 1


def test_prices_are_exact_decimals_not_floats() -> None:
    [ev] = parse_events([event(book("pinnacle", 2.1, 3.5, 3.6))])
    assert ev.prices[0].home.value == Decimal("2.100")
    assert ev.commence_at == datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


# --- client ------------------------------------------------------------------------------------------------------------------------

async def test_a_call_asks_for_h2h_in_the_region_and_counts_what_the_provider_charged() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer([event(book("pinnacle", 2.1, 3.5, 3.6))], last=1, remaining=499, used=1)

    store = MemoryCreditStore()
    client = TheOddsApiClient(settings(), store=store, http=http_with(handler))
    result = await client.fetch_h2h("soccer_epl")
    assert len(result.events) == 1 and result.credits_charged == 1 and result.remaining == 499 and result.used == 1
    assert store.spent(now().strftime("%Y-%m")) == 1
    params = dict(seen[0].url.params)
    assert seen[0].url.path == "/v4/sports/soccer_epl/odds/"
    assert params["regions"] == "eu" and params["markets"] == "h2h" and params["oddsFormat"] == "decimal" and params["apiKey"] == KEY


async def test_an_answer_with_no_events_costs_nothing() -> None:
    store = MemoryCreditStore()
    client = TheOddsApiClient(settings(), store=store, http=http_with(lambda r: answer([], last=0, remaining=500, used=0)))
    result = await client.fetch_h2h("soccer_epl")
    assert result.events == [] and result.credits_charged == 0 and store.spent(now().strftime("%Y-%m")) == 0


async def test_the_budget_refuses_before_any_request_is_made() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request was made with the month's budget spent")

    store = MemoryCreditStore()
    store.add(now().strftime("%Y-%m"), settings().monthly_credit_budget)
    client = TheOddsApiClient(settings(), store=store, http=http_with(handler))
    assert client.credits_left_in_budget() == 0
    with pytest.raises(QuotaExhaustedError):
        await client.fetch_h2h("soccer_epl")


async def test_the_budget_of_the_next_month_is_a_new_one() -> None:
    store = MemoryCreditStore()
    store.add("2026-10", 450)
    client = TheOddsApiClient(settings(), store=store, http=http_with(lambda r: answer([])))
    assert client.credits_left_in_budget() == 450 - store.spent(now().strftime("%Y-%m"))


async def test_when_the_provider_says_no_credits_are_left_the_next_call_is_not_made() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return answer([event(book("pinnacle", 2.1, 3.5, 3.6))], remaining=0)

    client = TheOddsApiClient(settings(), http=http_with(handler))
    await client.fetch_h2h("soccer_epl")
    with pytest.raises(QuotaExhaustedError, match="provider reports"):
        await client.fetch_h2h("soccer_epl")
    assert calls == 1


async def test_two_regions_cost_two_credits_a_call() -> None:
    client = TheOddsApiClient(settings(regions="eu,uk"), http=http_with(lambda r: answer([])))
    assert client.cost_of_a_call == 2


@pytest.mark.parametrize("bad", ["../../etc/passwd", "basketball_nba", "soccer_epl?x=1", "SOCCER_EPL", ""])
async def test_only_football_sport_keys_reach_the_url(bad: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request was made for a bad sport key")

    client = TheOddsApiClient(settings(), http=http_with(handler))
    with pytest.raises(ProviderError):
        await client.fetch_h2h(bad)


@pytest.mark.parametrize(("status", "error"), [(401, ProviderError), (403, ProviderError), (429, RateLimitError), (500, ProviderError)])
async def test_errors_of_the_provider_are_ours_and_say_no_key(status: int, error: type[Exception]) -> None:
    client = TheOddsApiClient(settings(), http=http_with(lambda r: httpx.Response(status, text=f"nope {KEY}")))
    with pytest.raises(error) as caught:
        await client.fetch_h2h("soccer_epl")
    assert KEY not in str(caught.value) and "apiKey" not in str(caught.value)


async def test_a_transport_error_leaves_no_url_behind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client = TheOddsApiClient(settings(), http=http_with(handler))
    with pytest.raises(ProviderError) as caught:
        await client.fetch_h2h("soccer_epl")
    assert KEY not in str(caught.value) and caught.value.__cause__ is None and caught.value.__suppress_context__


async def test_no_log_line_carries_the_key_or_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # The module logger caches its processors at first use; another test in the same pytest-xdist worker may have used it already, so give the
    # client a fresh logger for this test (capture_logs only reaches loggers that have not cached their chain yet).
    monkeypatch.setattr(client_module, "log", structlog.get_logger("the_odds_api_test"))
    client = TheOddsApiClient(settings(), http=http_with(lambda r: answer([event(book("pinnacle", 2.1, 3.5, 3.6))])))
    with capture_logs() as logs:
        await client.fetch_h2h("soccer_epl")
    assert logs and KEY not in json.dumps(logs, default=str) and "apiKey" not in json.dumps(logs, default=str)


async def test_an_answer_that_is_not_json_is_a_provider_error() -> None:
    client = TheOddsApiClient(settings(), http=http_with(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(ProviderError):
        await client.fetch_h2h("soccer_epl")


# --- identity ----------------------------------------------------------------------------------------------------------------------

def ours(fid: int, home: str, away: str, hours: float = 0.0) -> KnownFixture:
    return KnownFixture(fid, home, away, datetime(2026, 11, 21, 15, 0, tzinfo=UTC) + timedelta(hours=hours))


def an_event(home: str = "Manchester United", away: str = "Liverpool") -> object:
    return parse_events([event(book("pinnacle", 2.1, 3.5, 3.6, teams=(home, away)), home=home, away=away)])[0]


def test_a_fixture_that_agrees_in_teams_and_hour_is_the_match_even_with_another_spelling() -> None:
    result = match_fixture(an_event("Manchester United", "Liverpool"), [ours(1, "Man United", "Liverpool", 0.5), ours(2, "Arsenal", "Chelsea")])  # type: ignore[arg-type]
    assert result.fixture is not None and result.fixture.provider_fixture_id == 1 and result.reason == "matched"


def test_teams_are_never_flipped() -> None:
    result = match_fixture(an_event("Manchester United", "Liverpool"), [ours(1, "Liverpool", "Manchester United")])  # type: ignore[arg-type]
    assert result.fixture is None and result.reason == "no fixture agrees"


def test_three_hours_apart_is_another_match() -> None:
    result = match_fixture(an_event(), [ours(1, "Manchester United", "Liverpool", 3)])  # type: ignore[arg-type]
    assert result.fixture is None


def test_two_fixtures_that_agree_are_no_match() -> None:
    result = match_fixture(an_event(), [ours(1, "Manchester United", "Liverpool", 0), ours(2, "Manchester United", "Liverpool", 1)])  # type: ignore[arg-type]
    assert result.fixture is None and result.reason == "several fixtures agree"


def test_a_lookalike_is_not_the_team() -> None:
    result = match_fixture(an_event("Real Madrid", "Barcelona"), [ours(1, "Real Mallorca", "Barcelona")])  # type: ignore[arg-type]
    assert result.fixture is None

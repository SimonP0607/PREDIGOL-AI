"""The catalogue of a match's structured markets (plan Partidos y Match Center, F4a): the price IN FORCE after A -> B -> A,
307 and 339 read as one market, and the grouping by category. Pure: no database."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from fbi.api.services import market_catalog as service
from fbi.odds.quote_current import (
    CATALOG_FAMILIES,
    MARKET_CODES,
    PAGE_SPREAD,
    Ask,
    CurrentBook,
    CurrentQuote,
    InForce,
    Reading,
    choose_in_force,
    market_key,
)
from fbi.odds.quote_taxonomy import extracted_specs

KO = datetime(2026, 11, 8, 19, 0, tzinfo=UTC)
FIXTURE = 77


def at(hours_before: float) -> datetime:
    return KO - timedelta(hours=hours_before)


def reading(xid: int, payload: str, captured: datetime, *, page: int = 1, status: str = "ok",
            fixture_id: int | None = FIXTURE, stamped_by: str = "fetch") -> Reading:
    return Reading(extraction_id=xid, payload_hash=payload, status=status, fixture_id=fixture_id, captured_at=captured,
                   stamped_by=stamped_by, page=page, fetched_at=captured)


def choose(asks: list[Ask], readings: list[Reading], later: list[Reading] | None = None) -> InForce:
    return choose_in_force(asks, {r.payload_hash: r for r in readings}, fixture_id=FIXTURE, kickoff_at=KO,
                           later_pages=later or [])


# ── which body is in force ────────────────────────────────────────────────────────────────────────────────────────


def test_after_a_b_a_the_body_in_force_is_a_and_it_is_in_force_since_it_came_back() -> None:
    a, b = reading(1, "hA", at(30)), reading(2, "hB", at(20))
    asks = [Ask(at(30), 1, "hA"), Ask(at(20), 1, "hB"), Ask(at(10), 1, "hA")]
    got = choose(asks, [a, b])
    assert got.state == "priced"
    assert [x.extraction_id for x in got.bodies] == [1], "A's quotes, not B's newer rows"
    assert got.checked_at == at(10)
    assert got.bodies[0].captured_at == at(30), "the rows are A's first sighting"
    assert got.bodies[0].since == at(10), "A was not in force while B was: since the ask that brought it back"
    assert not got.newer_pending and not got.partial


def test_the_newest_row_reading_would_have_said_b() -> None:
    """The bug M4 describes, stated: the newest stored body is B, the one in force is A."""
    a, b = reading(1, "hA", at(30)), reading(2, "hB", at(20))
    newest_row = max([a, b], key=lambda r: r.captured_at or KO)
    got = choose([Ask(at(30), 1, "hA"), Ask(at(20), 1, "hB"), Ask(at(10), 1, "hA")], [a, b])
    assert newest_row.extraction_id == 2 and got.bodies[0].extraction_id == 1


def test_an_unbroken_run_goes_back_to_the_first_sighting() -> None:
    a = reading(1, "hA", at(30))
    got = choose([Ask(at(30), 1, "hA"), Ask(at(20), 1, "hA"), Ask(at(10), 1, "hA")], [a])
    assert got.bodies[0].since == at(30) and got.checked_at == at(10)


def test_a_run_broken_by_an_empty_answer_starts_after_it() -> None:
    a = reading(1, "hA", at(30))
    got = choose([Ask(at(30), 1, "hA"), Ask(at(20), 0, "hEmpty"), Ask(at(10), 1, "hA"), Ask(at(5), 1, "hA")], [a])
    assert got.bodies[0].since == at(10)


def test_an_empty_newest_answer_withdraws_every_price() -> None:
    a = reading(1, "hA", at(30))
    got = choose([Ask(at(30), 1, "hA"), Ask(at(10), 0, "hEmpty")], [a])
    assert got.state == "withdrawn" and got.bodies == () and got.checked_at == at(10)


def test_a_body_not_structured_yet_is_skipped_and_said() -> None:
    a = reading(1, "hA", at(30))
    got = choose([Ask(at(30), 1, "hA"), Ask(at(10), 1, "hNew")], [a])
    assert got.state == "priced" and got.newer_pending
    assert got.bodies[0].extraction_id == 1 and got.checked_at == at(30)


def test_nothing_structured_yet_is_unread() -> None:
    got = choose([Ask(at(10), 1, "hNew")], [])
    assert got.state == "unread" and got.newer_pending and got.bodies == ()


def test_no_ask_before_kick_off_is_never_asked() -> None:
    assert choose([], []).state == "never_asked"
    assert choose([Ask(KO + timedelta(minutes=5), 1, "hA")], [reading(1, "hA", at(1))]).state == "never_asked"


@pytest.mark.parametrize("bad", [
    reading(1, "hA", at(30), status="error"),
    reading(1, "hA", at(30), fixture_id=999),
    reading(1, "hA", at(30), stamped_by="provider_update"),
    reading(1, "hA", KO + timedelta(minutes=1)),
])
def test_a_reading_that_is_not_a_pre_match_capture_of_this_match_is_never_in_force(bad: Reading) -> None:
    got = choose([Ask(at(10), 1, "hA")], [bad])
    assert got.state == "unread" and got.bodies == ()


def test_a_later_page_fetched_by_the_ask_is_in_force() -> None:
    a = reading(1, "hA", at(10))
    page2 = reading(5, "hA2", at(10) + timedelta(seconds=3), page=2)
    got = choose([Ask(at(10), 1, "hA")], [a], [page2])
    assert [x.extraction_id for x in got.bodies] == [1, 5] and not got.partial


def test_a_later_page_that_cannot_be_tied_to_the_ask_is_left_out_and_said() -> None:
    a, b = reading(1, "hA", at(30)), reading(2, "hB", at(20))
    old_page2 = reading(5, "hA2", at(30) + timedelta(seconds=3), page=2)
    got = choose([Ask(at(30), 1, "hA"), Ask(at(20), 1, "hB"), Ask(at(10), 1, "hA")], [a, b], [old_page2])
    assert [x.extraction_id for x in got.bodies] == [1], "A's page 2 at the third ask could be stale: never shown"
    assert got.partial


def test_a_later_page_fetched_after_the_spread_is_not_the_asks() -> None:
    a = reading(1, "hA", at(10))
    late = reading(5, "hA2", at(10) + PAGE_SPREAD, page=2)
    got = choose([Ask(at(10), 1, "hA")], [a], [late])
    assert [x.extraction_id for x in got.bodies] == [1] and got.partial


# ── the market codes ──────────────────────────────────────────────────────────────────────────────────────────────


def test_every_structured_bet_has_a_code_and_only_307_and_339_share_a_market() -> None:
    specs = extracted_specs()
    assert {s.family for s in specs} == set(CATALOG_FAMILIES)
    assert {s.bet_id for s in specs} == set(MARKET_CODES), "a bet extracted with no code, or a code with no bet"
    keys = Counter(market_key(s.bet_id, s.period, s.subject) for s in specs)
    shared = {k: n for k, n in keys.items() if n > 1}
    assert shared == {"corners_double_chance.FT.match": 2}
    assert len(keys) == len(specs) - 1 == 54


def test_codes_carry_no_spanish_words() -> None:
    assert all(code.isascii() and code == code.lower() and " " not in code for code in MARKET_CODES.values())


# ── unification and grouping ──────────────────────────────────────────────────────────────────────────────────────

SINCE = at(6)


def q(bet_id: int, selection: str, odds: str, *, book: int = 1, name: str = "Bet365", line: str = "0",
      family: str = "corners", period: str = "FT", subject: str = "match", kind: str = "double_chance",
      has_line: bool = False, market: str | None = None, since: datetime = SINCE) -> CurrentQuote:
    return CurrentQuote(bookmaker_id=book, bookmaker=name, bet_id=bet_id, family=family, period=period, subject=subject,
                        kind=kind, has_line=has_line, market_key=market, provider_name=f"bet {bet_id}",
                        selection=selection, line=Decimal(line), odds=Decimal(odds), captured_at=since, since=since)


def test_307_and_339_read_as_one_market_with_one_price_per_bookmaker() -> None:
    quotes = [q(307, "1X", "1.40", book=1), q(339, "1X", "1.55", book=1),   # one bookmaker, both ids: 307 wins
              q(339, "1X", "1.45", book=2, name="Pinnacle"), q(339, "X2", "2.10", book=2, name="Pinnacle")]
    unified = service.unify(quotes)
    assert len(unified) == 3
    [market] = service.markets(unified, "corners")
    assert market.key == "corners_double_chance.FT.match" and market.bet_ids == [307, 339]
    assert market.bookmakers == 2 and market.provider_name == "bet 307"
    one_x = next(s for s in market.selections if s.selection == "1X")
    assert one_x.bookmakers == 2 and one_x.best_odds == Decimal("1.45") and one_x.bookmaker == "Pinnacle"
    assert [(b.bookmaker, b.odds, b.bet_id) for b in one_x.books] == [("Pinnacle", Decimal("1.45"), 339),
                                                                     ("Bet365", Decimal("1.40"), 307)]


def test_categories_only_where_there_are_prices_in_the_products_order() -> None:
    quotes = service.unify([
        q(45, "Over", "1.9", line="9.5", kind="over_under", has_line=True),
        q(45, "Under", "1.9", line="9.5", kind="over_under", has_line=True, book=2, name="Pinnacle"),
        q(1, "Home", "2.0", family="result", kind="one_x_two", market="1X2"),
        q(80, "Over", "1.8", family="cards", line="4.5", kind="over_under", has_line=True),
        q(153, "Over", "1.8", family="cards", line="3.5", kind="over_under", has_line=True),
    ])
    cats = service.categories(quotes)
    assert [c.key for c in cats] == ["result", "corners", "cards"]
    corners = next(c for c in cats if c.key == "corners")
    assert (corners.markets, corners.selections, corners.bookmakers) == (1, 2, 2)
    cards = next(c for c in cats if c.key == "cards")
    assert cards.markets == 2, "cards and yellow cards over/under are two markets, not one"


def test_markets_and_selections_are_ordered_and_handicap_pairs_sit_together() -> None:
    rows = service.unify([
        q(4, "Away", "1.9", family="result", kind="asian_handicap", line="0.5", has_line=True, market="AH"),
        q(4, "Home", "1.9", family="result", kind="asian_handicap", line="-0.5", has_line=True, market="AH"),
        q(4, "Home", "2.6", family="result", kind="asian_handicap", line="-1.5", has_line=True, market="AH"),
        q(4, "Away", "1.5", family="result", kind="asian_handicap", line="1.5", has_line=True, market="AH"),
        q(2, "Away", "2.2", family="result", kind="draw_no_bet"),
        q(1, "Away", "3.0", family="result", kind="one_x_two", market="1X2"),
        q(1, "Home", "2.0", family="result", kind="one_x_two", market="1X2"),
        q(1, "Draw", "3.4", family="result", kind="one_x_two", market="1X2"),
    ])
    got = service.markets(rows, "result")
    assert [m.key for m in got] == ["result_1x2.FT.match", "result_asian_handicap.FT.match",
                                    "result_draw_no_bet.FT.match"]
    assert [s.selection for s in got[0].selections] == ["Home", "Draw", "Away"]
    assert got[0].market_key == "1X2" and got[2].market_key is None
    assert [(s.selection, s.line) for s in got[1].selections] == [
        ("Home", Decimal("-1.5")), ("Away", Decimal("1.5")), ("Home", Decimal("-0.5")), ("Away", Decimal("0.5"))]


def test_a_tie_for_the_best_price_goes_to_the_name_and_the_since_is_the_bookmakers() -> None:
    rows = service.unify([q(55, "Home", "2.0", book=2, name="Pinnacle", kind="one_x_two", since=at(3)),
                          q(55, "Home", "2.0", book=1, name="Bet365", kind="one_x_two", since=at(8))])
    [market] = service.markets(rows, "corners")
    [home] = market.selections
    assert home.bookmaker == "Bet365" and home.captured_at == at(8) and home.bookmakers == 2


def _book(state: str = "priced", quotes: tuple[CurrentQuote, ...] = ()) -> CurrentBook:
    return CurrentBook(fixture_id=FIXTURE, kickoff_at=KO, in_force=InForce(state, checked_at=at(2)),  # type: ignore[arg-type]
                       quotes=quotes)


def test_without_a_category_only_the_categories_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = (q(45, "Over", "1.9", line="9.5", kind="over_under", has_line=True),)
    monkeypatch.setattr(service, "read_in_force", lambda conn, fid: _book(quotes=quotes))
    env = service.match_market_catalog(object(), FIXTURE)  # type: ignore[arg-type]
    assert env.status == "ok" and env.data.category is None and env.data.markets == []
    assert [c.key for c in env.data.categories] == ["corners"] and env.data.checked_at == at(2)
    env = service.match_market_catalog(object(), FIXTURE, "corners")  # type: ignore[arg-type]
    assert [m.key for m in env.data.markets] == ["corners_over_under.FT.match"]
    env = service.match_market_catalog(object(), FIXTURE, "cards")  # type: ignore[arg-type]
    assert env.status == "ok" and env.data.markets == [], "a category with no prices has no markets"


@pytest.mark.parametrize("state", ["withdrawn", "unread", "never_asked"])
def test_no_price_in_force_is_empty_with_its_reason(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    monkeypatch.setattr(service, "read_in_force", lambda conn, fid: _book(state))
    env = service.match_market_catalog(object(), FIXTURE)  # type: ignore[arg-type]
    assert env.status == "empty" and env.data.state == state and env.data.categories == []
    assert env.reason and env.reason.isascii()


def test_an_unknown_match_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def none(conn: Any, fid: int) -> None:
        return None

    monkeypatch.setattr(service, "read_in_force", none)
    with pytest.raises(HTTPException) as caught:
        service.match_market_catalog(object(), 404)  # type: ignore[arg-type]
    assert caught.value.status_code == 404


def test_the_route_takes_an_optional_closed_list_of_categories() -> None:
    """The route lives on the Match Center's router (the product tier of ``create_app``, beside ``/markets``); the USER's
    200 is checked over the real application in ``tests/integration/test_market_catalog_api.py``."""
    from fastapi import FastAPI

    from fbi.api.routers.center import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    op = app.openapi()["paths"]["/api/v1/matches/{fixture_id}/markets/catalog"]["get"]
    [category] = [p for p in op["parameters"] if p["name"] == "category"]
    assert not category.get("required", False)
    schema = category["schema"]
    enum = next(o["enum"] for o in schema.get("anyOf", [schema]) if "enum" in o)
    assert enum == list(CATALOG_FAMILIES)

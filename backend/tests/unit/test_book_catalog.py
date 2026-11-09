"""«Mercados» read through the book (plan Cuotas, phase 6: BE-020): the same answer of the provider read by the two readers - the
``tax-v2`` extractor behind the catalogue and ``tax-v3`` behind the book - gives the same catalogue."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.api.contracts.market_catalog import MarketCatalog
from fbi.api.services.market_catalog import build
from fbi.odds.book import read_answer, summarize
from fbi.odds.book_catalog import Bookmaker, build_book, quotes_of_rows, structured_specs
from fbi.odds.quote_current import CATALOG_FAMILIES, CurrentQuote, InForce
from fbi.odds.quote_extract import parse_body
from fbi.odds.quote_taxonomy import extracted_specs, known_bet_ids

ANSWERS = Path(__file__).parents[1] / "fixtures" / "odds_book" / "real_answers.json"
AT = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
SINCE = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
KO = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)


def entry(name: str) -> dict[str, Any]:
    data: dict[str, dict[str, Any]] = json.loads(ANSWERS.read_text(encoding="utf-8"))["answers"]
    return copy.deepcopy(data[name])


def legacy_quotes(answer: dict[str, Any], ids: dict[int, int]) -> list[CurrentQuote]:
    """What ``quote_current.read_in_force`` would hold for this answer: the ``tax-v2`` reading, one quote per value."""
    specs = {s.bet_id: s for s in extracted_specs()}
    parsed = parse_body({"response": [answer]}, specs, known_bet_ids())
    quotes: list[CurrentQuote] = []
    for item in parsed:
        for q in item.quotes:
            spec = specs[q.provider_bet_id]
            if spec.family not in CATALOG_FAMILIES:
                continue
            quotes.append(CurrentQuote(
                bookmaker_id=ids[q.provider_bookmaker_id], bookmaker=q.bookmaker_name, bet_id=spec.bet_id,
                family=spec.family, period=spec.period, subject=spec.subject, kind=spec.kind, has_line=spec.has_line,
                market_key=spec.market_key, provider_name=spec.name, selection=q.selection, line=q.line, odds=q.odds,
                captured_at=AT, since=SINCE))
    return quotes


def book_quotes(answer: dict[str, Any], ids: dict[int, int]) -> list[CurrentQuote]:
    """What the book would hold for the same answer, folded back by ``book_catalog``."""
    names = {int(b["id"]): str(b["name"]) for b in answer["bookmakers"]}
    bookmakers = {p: Bookmaker(ids[p], names[p]) for p in ids}
    rows = [(bet_id, summarize(t.spec, t.prices), AT, SINCE) for bet_id, t in read_answer(answer).shown().items()]
    return quotes_of_rows(rows, bookmakers)


def catalog(quotes: list[CurrentQuote], category: Any = None) -> MarketCatalog:
    return build(1, KO, InForce(state="priced", checked_at=AT), quotes, category)


def shape(view: MarketCatalog) -> list[Any]:
    """Everything a reader sees of the markets: key, period, subject, each selection's line, best price, bookmaker and the
    price of every bookmaker. Decimals compared as numbers."""
    return [
        (m.key, m.period, m.subject, m.has_line, m.bookmakers,
         [(s.selection, Decimal(s.line), Decimal(s.best_odds), s.bookmaker_id, s.bookmakers,
           sorted((b.bookmaker_id, b.bookmaker, Decimal(b.odds)) for b in s.books)) for s in m.selections])
        for m in view.markets]


@pytest.mark.parametrize("name", ["premier_league", "serie_a", "primera_a", "copa_del_rey"])
def test_the_same_answer_gives_the_same_categories_and_markets_through_the_book(name: str) -> None:
    answer = entry(name)
    ids = {int(b["id"]): 1000 + int(b["id"]) for b in answer["bookmakers"]}
    old, new = legacy_quotes(answer, ids), book_quotes(answer, ids)
    assert old and new
    assert [c.model_dump() for c in catalog(old).categories] == [c.model_dump() for c in catalog(new).categories]
    for family in CATALOG_FAMILIES:
        old_markets = {m[0]: m for m in shape(catalog(old, family))}
        new_markets = {m[0]: m for m in shape(catalog(new, family))}
        assert set(new_markets) == set(old_markets), family
        for key, market in new_markets.items():
            assert market == old_markets[key], key
    assert sum(len(catalog(new, f).markets) for f in CATALOG_FAMILIES) >= 24  # not an empty comparison


def test_the_catalogue_structures_the_five_classic_markets_and_their_halves() -> None:
    assert {1, 4, 5, 8, 12} <= set(structured_specs())


def test_a_bookmaker_we_cannot_name_is_left_out_and_the_rest_stays() -> None:
    answer = entry("premier_league")
    ids = {int(b["id"]): 1000 + int(b["id"]) for b in answer["bookmakers"]}
    full = book_quotes(answer, ids)
    dropped = next(iter(ids))
    partial = book_quotes(answer, {p: i for p, i in ids.items() if p != dropped})
    assert partial and len(partial) < len(full)
    assert dropped not in {q.bookmaker_id - 1000 for q in partial}


def test_the_book_of_a_match_is_priced_since_the_answer_in_force() -> None:
    answer = entry("serie_a")
    ids = {int(b["id"]): 1000 + int(b["id"]) for b in answer["bookmakers"]}
    names = {int(b["id"]): str(b["name"]) for b in answer["bookmakers"]}
    rows = [{"bet_id": bet_id, "summary": summarize(t.spec, t.prices), "captured_at": AT, "in_force_since": None,
             "checked_at": AT, "newer_pending": bet_id == 1}
            for bet_id, t in read_answer(answer).shown().items()]
    book = build_book(7, KO, rows, {p: Bookmaker(ids[p], names[p]) for p in ids})
    assert book.in_force.state == "priced" and book.in_force.newer_pending
    assert {q.since for q in book.quotes} == {AT}  # no in_force_since: the capture instant stands in

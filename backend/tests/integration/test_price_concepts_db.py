"""RP-10.1 on a real database: C-14's private answer for a match with prices in force carries the concepts of price (the reference of the consensus, its
equivalent fair odds and age, the implied probability of the best price and its age, the settlement rule), they agree with each other, and the public projection
carries the same optional fields. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import psycopg
import pytest
from scripts import ia_price_concepts as cli

import fbi.api.services.market_probs as market_probs
from fbi.api.contracts.intelligence.market_probs import MarketProbs
from fbi.api.contracts.intelligence.projection import to_public
from fbi.market import price_glossary as pg
from fbi.odds.quote_current import CurrentBook, CurrentQuote

from .conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
_ids = count(980_000)


def houses(db: psycopg.Connection[Any], n: int) -> list[int]:
    out = []
    for i in range(n):
        row = db.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id", (next(_ids), f"Casa {i}")).fetchone()
        assert row is not None
        out.append(int(row[0]))
    return out


def quotes_of(books: list[int], captured: datetime) -> tuple[CurrentQuote, ...]:
    return tuple(CurrentQuote(bookmaker_id=bk, bookmaker=f"Casa {bk}", bet_id=45, family="corners", period="FT", subject="match", kind="over_under",
                              has_line=True, market_key=None, provider_name="Corners Over Under", selection=sel, line=Decimal("9.5"),
                              odds=Decimal(odds), captured_at=captured - timedelta(minutes=5 * k), since=captured)
                 for k, bk in enumerate(books) for sel, odds in (("Over", "1.90"), ("Under", "1.95")))


@pytest.fixture()
def priced(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> int:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (AT + timedelta(hours=8), seed.fixture_id))
    book = CurrentBook(fixture_id=seed.fixture_id, kickoff_at=AT + timedelta(hours=8), in_force=None,  # type: ignore[arg-type]
                       quotes=quotes_of(houses(db, 4), AT))
    monkeypatch.setattr(market_probs, "book_in_force", lambda conn, fixture_id: book)
    return seed.fixture_id


def test_the_private_answer_carries_the_concepts_and_they_agree(db: psycopg.Connection[Any], priced: int) -> None:
    answer = market_probs.build(db, priced, at=AT + timedelta(minutes=30))
    dumped = answer.model_dump(mode="json")
    (market,) = dumped["markets"]["items"]
    assert market["settlement"]["rule"] == market["rule_key"] and market["settlement"]["text_es"] and market["settlement"]["text_en"]
    for sel in market["selections"]:
        implied = sel["implied"]
        assert implied["reference"] == "consenso_vigente" and implied["books"] == 4
        assert implied["fair_odds"] is not None and abs(implied["fair_odds"] * implied["value"] - 1) < pg.TOLERANCE
        assert sel["best_implied"] == pytest.approx(1 / sel["best_odds"], abs=1e-4)
        assert sel["price_age_minutes"] >= 30 and implied["age_minutes"] >= 30
        assert pg.problems(sel) == []
        assert {"fair_probability", "houses", "fair_odds", "implied_probability", "best_price", "current_odds", "price_age"} <= pg.present(sel, market)


def test_the_public_projection_carries_the_same_optional_fields(db: psycopg.Connection[Any], priced: int) -> None:
    public = to_public(market_probs.build(db, priced, at=AT), MarketProbs).model_dump(mode="json")
    (market,) = public["markets"]["items"]
    sel = market["selections"][0]
    assert sel["implied"]["fair_odds"] and sel["best_implied"] and "settlement" in market


def test_the_report_over_a_real_answer_is_coherent(db: psycopg.Connection[Any], priced: int) -> None:
    doc = cli.report([market_probs.build(db, priced, at=AT).model_dump(mode="json")])
    assert doc["coherent"] is True and doc["matches"] == 1 and doc["matches_with_all_producible"] == 1

"""«Mercados» through the book (plan Cuotas, phase 6: BE-020) over a migrated database.

The seeded match is the one of the catalogue's own test (A -> B -> A, two bookmakers, corners under 307 and 339). With the book
refreshes OFF the route reads as it always did; with them ON and the book built it reads the book: the same match, the same
prices. A match the book holds nothing of keeps the reading it always had.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api import cache
from fbi.core.config import settings
from fbi.odds.book import build as build_book
from tests.integration.conftest import Seed
from tests.integration.test_market_catalog_api import KO, client, seeded, url  # noqa: F401  (the fixture `client`)


def read(api: TestClient, fixture_id: int, *categories: str) -> list[Any]:
    cache.clear()  # the route keeps its answer for 60 s per process
    return [api.get(url(fixture_id, c or None)).json() for c in ("", *categories)]


def refreshes(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    monkeypatch.setattr(settings.odds, "odds_book", "1" if on else "0")
    monkeypatch.setattr(settings.odds, "odds_book_refresh", "1" if on else "0")


def comparable(env: dict[str, Any]) -> Any:
    """What a reader sees of an envelope: the data, without the instants that belong to the answer in force."""
    data = env["data"]
    return {
        "categories": data["categories"],
        "markets": [
            {**m, "selections": [
                {k: v for k, v in s.items() if k not in {"captured_at"}} | {
                    "books": [{k: v for k, v in b.items() if k != "captured_at"} for b in s["books"]]}
                for s in m["selections"]]}
            for m in data["markets"]]}


def test_with_the_refreshes_on_the_book_gives_the_same_markets(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                               client: TestClient,  # noqa: F811
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_id, _a, _b = seeded(db, seed, tmp_path)
    refreshes(monkeypatch, False)
    before = read(client, fixture_id, "result", "corners", "cards")
    build_book(db, tmp_path, [fixture_id], commit=False, apply=True, now=KO)
    refreshes(monkeypatch, True)
    after = read(client, fixture_id, "result", "corners", "cards")
    assert [comparable(e) for e in after] == [comparable(e) for e in before]
    assert after[2]["data"]["markets"], "the corners are there"


def test_with_the_refreshes_on_and_no_book_the_route_reads_as_always(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                                     client: TestClient,  # noqa: F811
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_id, _a, _b = seeded(db, seed, tmp_path)
    refreshes(monkeypatch, False)
    before = read(client, fixture_id, "corners")
    refreshes(monkeypatch, True)  # the book was never built for this match
    after = read(client, fixture_id, "corners")
    assert [e["data"] for e in after] == [e["data"] for e in before]

"""AD-E01 (IA-070): the six read-only queries of the catalogue with a state, run on a database built by the migrations, against
counts worked out by hand."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import market_status as ms
from fbi.market import catalogue
from fbi.odds.quote_taxonomy import sync_definitions

from .conftest import Seed
from .knowledge_world import KICKOFF, World

pytestmark = pytest.mark.integration

AT = KICKOFF + timedelta(days=3)


def one(db: psycopg.Connection[Any], sql: str, *args: object) -> Any:
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _quote(db: psycopg.Connection[Any], w: World, extraction: int, fid: int, bet_id: int, books: int) -> None:
    definition = one(db, "SELECT id FROM market.market_definitions WHERE provider_bet_id = %s", bet_id)
    for book in w.books(books):
        db.execute("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, "
                   "minutes_to_ko, extraction_id) VALUES (%s, %s, %s, 'Over', 9.5, 1.90, %s, 60, %s)",
                   (fid, book, definition, KICKOFF - timedelta(hours=1), extraction))


def test_the_catalogue_is_measured_from_the_database_as_counted_by_hand(db: psycopg.Connection[Any], seed: Seed) -> None:
    sync_definitions(db)
    catalogue.sync(db)
    w = World(db, seed)
    with_corners, without_corners, upcoming = w.match(), w.match(), w.match(kickoff=AT + timedelta(days=1), goals=None,
                                                                             status="NS", group="scheduled")
    for side in ("home", "away"):
        w.team_stats(with_corners, side, corners=5)
    extraction = one(db, "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, "
                         "stamped_by, status) VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", w.hash, KICKOFF)
    for fid in (with_corners, without_corners, upcoming):
        _quote(db, w, extraction, fid, 45, 3)  # corners over/under, three houses
    _quote(db, w, extraction, with_corners, 80, 1)  # cards over/under, one house

    facts = ms.collect(db, at=AT)
    assert facts.base_fixtures == 3
    corners = facts.prices["CORNERS_OU"]
    assert (corners["priced"], corners["books_median"], corners["priced_3"], corners["finished"], corners["settleable"]) == (
        3, 3.0, 3, 2, 1), "three priced, two finished, one with the corners of both teams"
    assert facts.prices["CARDS_OU"]["books_median"] == 1.0
    assert facts.rules["corners_ft@v1"] is True and facts.rules["corners_1h@v1"] is False, "the rules sync wrote, as stored"
    assert facts.models == {} and facts.champions == {}

    statuses = {m.key: m for m in ms.build(facts)}
    assert len(facts.definitions) == len(statuses) + sum(len(m.entry.bet_ids) - 1 for m in statuses.values())
    assert (statuses["CORNERS_OU"].state, statuses["CORNERS_OU"].reason) == ("necesita_datos", "liquidacion_sin_muestra")
    assert (statuses["CARDS_OU"].state, statuses["CARDS_OU"].reason) == ("necesita_datos", "menos_de_3_casas")
    assert (statuses["OU"].state, statuses["OU"].reason) == ("no_ofrecer", "sin_cuotas")
    assert not any(m.state == "evaluable" for m in statuses.values())
    assert one(db, "SELECT count(*) FROM market.odds_quotes") == 3 * 3 + 1, "collect reads; it writes nothing"

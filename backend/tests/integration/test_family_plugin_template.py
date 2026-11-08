"""The example plug-in family (``fbi.plugins._template``, TEAM_TOTALS, shadow) against the real schema, on a world of its own: the
Dixon-Coles in force at the moment is read as sim-v1 reads it (not an older forecast, not one made after the moment, not another
model), the books' quotes of bets 16 and 17 in force at the moment are priced (not one captured after it), and the adapter puts the
selection the model sees value in before decision-v2. Read-only; the transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.odds.quote_taxonomy import sync_definitions
from fbi.plugins._template import family as example
from tests.integration.conftest import Seed

from .test_families_forecast import catalogue
from .test_simulator_check import CUTOFF, KO, World, rows_of

pytestmark = pytest.mark.integration

AT = KO - timedelta(hours=3)


def books(db: psycopg.Connection[Any], seed: Seed, n: int) -> list[int]:
    out = [seed.bookmaker_id]
    for i in range(1, n):
        out.append(int(db.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                                  (989900 + i, f"Plugin book {i}")).fetchall()[0][0]))
    return out


def test_the_example_reads_the_model_in_force_and_the_prices_as_of_the_moment(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db)
    a, b, _c = w.fixtures
    w.forecast(a, w.version("dixon_coles", "old"), rows_of(2.4, 0.6, -0.05), cutoff=CUTOFF - timedelta(days=1))
    now = w.version("dixon_coles", "now")
    w.forecast(a, now, rows_of(1.55, 1.1, -0.09))
    w.forecast(a, w.version("dixon_coles", "later"), rows_of(0.7, 2.2, -0.05), cutoff=AT + timedelta(minutes=30))  # after the moment
    w.forecast(b, w.version("poisson", "b"), rows_of(1.3, 1.2, None))  # not the family's source model

    matches = example.read_matches(db, at=AT, horizon=timedelta(days=2))
    assert set(matches) == {a}, "b has no Dixon-Coles, c no forecast"
    m = matches[a]
    assert m.model_version_id == now and m.data_cutoff_ts == CUTOFF
    assert m.joint.intensities.home == pytest.approx(1.55, rel=1e-3) and m.joint.rho == pytest.approx(-0.09, abs=1e-3)
    assert m.fixture["kickoff_at"] == KO and m.fixture["competition_name"] == "Simulator League"
    assert example.read_matches(db, at=AT, fixtures=[]) == {}
    assert example.read_matches(db, at=KO + timedelta(minutes=1), fixtures=[a]) == {}, "a match that has started is not read"

    catalogue(db, (("OU_HOME", 2, True), ("OU_AWAY", 2, True)))
    sync_definitions(db, names={})
    for bet, key in ((16, "OU_HOME"), (17, "OU_AWAY")):
        db.execute("UPDATE market.market_definitions SET market_key = %s WHERE provider_bet_id = %s AND scope = 'prematch'", (key, bet))
    definition = int(db.execute("SELECT id FROM market.market_definitions WHERE provider_bet_id = 16 AND scope = 'prematch'").fetchall()[0][0])
    extraction = int(db.execute(
        "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
        "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (seed.payload_hash, AT - timedelta(hours=2))).fetchall()[0][0])
    p = example.TeamTotalsModel(matches).price(a, "OU_HOME", "Over", Decimal("1.5"))
    assert p is not None
    over = round(1.10 / p[0], 2)
    under = round(1.0 / (1.06 - 1.0 / over), 2)
    ids = books(db, seed, 3)

    def quote(book: int, o: float, u: float, minutes: int) -> None:
        for selection, odds in (("Over", o), ("Under", u)):
            db.execute("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, "
                       "minutes_to_ko, extraction_id) VALUES (%s, %s, %s, %s, 1.5, %s, %s, 60, %s)",
                       (a, book, definition, selection, str(odds), AT + timedelta(minutes=minutes), extraction))

    for book in ids:
        quote(book, over, under, -60)
    quote(ids[0], 9.0, 1.01, 30)  # captured after the moment: never read
    db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, "
               "overround, best_odds, best_bookmaker_id) VALUES (%s, 'OU', 'Over', 2.5, %s, 'shin', 0.5, 3, 0.05, 2.0, %s)",
               (a, AT - timedelta(minutes=20), ids[0]))

    found = example.read_inputs(db, at=AT, horizon=timedelta(days=2))
    priced = found.priced[(a, "OU_HOME", Decimal("1.5"), "Over")]
    assert priced.books == 3 and priced.best_odds == pytest.approx(over), "the quote captured after the moment is not read"
    assert found.observed == {a: AT - timedelta(minutes=20)}

    [cand] = example.TeamTotalsFamily().candidates(db, at=AT, horizon=timedelta(days=2))
    assert cand.key == (a, "OU_HOME", "Over", Decimal("1.50")) and cand.model_hint == example.MODEL
    row = cand.models[example.MODEL]
    assert row["p_model"] == pytest.approx(p[0]) and row["n_bookmakers"] == 3 and row["model_version_id"] == now

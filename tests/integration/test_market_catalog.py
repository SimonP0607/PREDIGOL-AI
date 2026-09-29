"""The provider's catalogue, our markets, and the line invariants between them.

The bug this file exists for was measured, not imagined: API-Football returned
Asian Handicap prices, ``BET_ID_TO_MARKET`` mapped bet 4 to ``AH``, and
``OddsRepository.write_snapshots`` dropped every one of them because no row with
key ``AH`` existed in ``market.markets``. The provider answered and we discarded
the answer, counting it as "unknown market".
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from fbi.catalog.provider_markets import load_bet_catalogue, load_bookmakers, record_observed_bets
from fbi.domain.market import MarketType
from fbi.odds.repository import OddsRepository
from fbi.picks.rules import RULE_V1
from fbi.picks.settlement import market_outcome
from fbi.providers.base import OddsQuote
from tests.integration.conftest import Seed

CAPTURED = datetime(2026, 9, 15, 18, 48, tzinfo=UTC)
CATALOGUE_DIR = pathlib.Path(__file__).parents[2] / "docs" / "api-football" / "catalogues"


def _quote(seed: Seed, market: str, selection: str, line: str, odds: str = "1.90") -> OddsQuote:
    return OddsQuote(
        provider_fixture_id=9001,
        provider_bookmaker_id=8,
        bookmaker_name="Bet365",
        market_key=market,
        selection=selection,
        line=Decimal(line),
        odds_decimal=Decimal(odds),
        captured_at=CAPTURED,
        minutes_to_ko=12,
        source="prematch",
        payload_hash=seed.payload_hash,
    )


@pytest.fixture()
def fixture_9001(db: psycopg.Connection, seed: Seed) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (9001,%s,%s,%s,%s,'NS','scheduled') RETURNING id",
            (seed.season_id, seed.home_team_id, seed.away_team_id, datetime(2026, 9, 15, 19, 0, tzinfo=UTC)),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


# ── the two catalogues are separate ─────────────────────────────────────────


def test_tracking_a_market_is_not_the_same_as_modelling_it(db: psycopg.Connection, seed: Seed) -> None:
    with db.cursor() as cur:
        cur.execute("SELECT key, is_tracked, is_model_enabled FROM market.markets ORDER BY key")
        rows = {k: (t, m) for k, t, m in cur.fetchall()}
    assert set(rows) == {m.value for m in MarketType}
    assert all(tracked for tracked, _ in rows.values()), "we store prices for everything we can read"
    assert {k for k, (_, modelled) in rows.items() if modelled} == {"1X2", "OU", "BTTS"}
    assert rows["AH"] == (True, False), "Asian Handicap is captured from tonight and modelled by nobody"


def test_no_market_is_model_enabled_without_a_rule_and_a_settlement(db: psycopg.Connection, seed: Seed) -> None:
    """The invariant that keeps the flag honest in both directions.

    A market our models may use must be one the decision rule covers and one we
    can actually settle - otherwise a pick on it could never be paid out. And a
    market the rule covers must be enabled, or the rule is dead text.
    """
    with db.cursor() as cur:
        cur.execute("SELECT key FROM market.markets WHERE is_model_enabled ORDER BY key")
        enabled = {r[0] for r in cur.fetchall()}
    assert enabled == set(RULE_V1.markets)
    for key in enabled:
        selection = {"1X2": "Home", "OU": "Over", "BTTS": "Yes"}[key]
        line = Decimal("2.5") if key == "OU" else Decimal(0)
        market_outcome(key, selection, line, 2, 1)  # raises if there is no rule


def test_a_market_cannot_be_modelled_without_being_tracked(db: psycopg.Connection, seed: Seed) -> None:
    with pytest.raises(psycopg.errors.CheckViolation, match="markets_model_requires_tracking"):
        db.execute("UPDATE market.markets SET is_tracked = false WHERE key = '1X2'")


def test_the_provider_catalogue_can_hold_bets_we_do_not_model(db: psycopg.Connection, seed: Seed) -> None:
    """Corners Asian Handicap (56) is not our AH. Knowing it exists is the point
    of the table: an unmapped bet stops being invisible."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO market.provider_markets (provider,scope,provider_bet_id,name,market_key,source) "
            "VALUES ('api-football','prematch',56,'Corners Asian Handicap',NULL,'catalogue')"
        )
        cur.execute("SELECT name, market_key FROM market.provider_markets "
                    "WHERE provider_bet_id = 4 AND scope = 'prematch'")
        assert cur.fetchone() == ("Asian Handicap", "AH")
        cur.execute("SELECT count(*) FROM market.provider_markets WHERE market_key IS NULL")
        assert cur.fetchone() == (1,)


def test_prematch_and_inplay_bet_ids_are_different_namespaces(db: psycopg.Connection, seed: Seed) -> None:
    """Bet 4 in-play is not bet 4 pre-match, so both rows must be able to exist."""
    db.execute("INSERT INTO market.provider_markets (provider,scope,provider_bet_id,name,market_key,source) "
               "VALUES ('api-football','inplay',4,'Asian Handicap (in-play)',NULL,'catalogue')")
    with db.cursor() as cur:
        cur.execute("SELECT scope, name FROM market.provider_markets WHERE provider_bet_id = 4 ORDER BY scope")
        assert [r[0] for r in cur.fetchall()] == ["inplay", "prematch"]


def test_two_provider_bets_cannot_claim_the_same_market(db: psycopg.Connection, seed: Seed) -> None:
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("INSERT INTO market.provider_markets (provider,scope,provider_bet_id,name,market_key,source) "
                   "VALUES ('api-football','prematch',19,'Asian Handicap First Half','AH','catalogue')")


# ── asian handicap prices now survive the write ──────────────────────────────


def test_asian_handicap_prices_reach_the_database(db: psycopg.Connection, seed: Seed,
                                                  fixture_9001: int) -> None:
    """The regression. Before market.markets knew AH, every one of these was
    counted as skipped_unknown_market and thrown away."""
    quotes = [
        _quote(seed, "AH", "Home", "-0.25", "1.92"),
        _quote(seed, "AH", "Away", "0.25", "1.88"),
        _quote(seed, "AH", "Home", "0", "1.59"),
        _quote(seed, "AH", "Away", "0.75", "3.52"),
        _quote(seed, "AH", "Home", "-2.5", "8.20"),
    ]
    result = OddsRepository(db).write_snapshots(quotes)
    assert result.skipped_unknown_market == 0, "the market is known now"
    assert result.written == 5
    with db.cursor() as cur:
        cur.execute("SELECT selection, line FROM market.odds_snapshots WHERE fixture_id = %s "
                    "AND market_key = 'AH' ORDER BY selection, line", (fixture_9001,))
        assert cur.fetchall() == [("Away", Decimal("0.25")), ("Away", Decimal("0.75")),
                                  ("Home", Decimal("-2.50")), ("Home", Decimal("-0.25")),
                                  ("Home", Decimal("0.00"))]


def test_the_same_handicap_on_both_sides_is_two_distinct_rows(db: psycopg.Connection, seed: Seed,
                                                              fixture_9001: int) -> None:
    """Home -0.25 and Away -0.25 are different bets at different prices. The
    primary key has to keep them apart, and the signs make that automatic."""
    written = OddsRepository(db).write_snapshots([
        _quote(seed, "AH", "Home", "-0.25", "1.92"),
        _quote(seed, "AH", "Away", "-0.25", "2.60"),
    ]).written
    assert written == 2


def test_a_price_is_never_overwritten_by_a_recapture(db: psycopg.Connection, seed: Seed,
                                                     fixture_9001: int) -> None:
    repo = OddsRepository(db)
    first = repo.write_snapshots([_quote(seed, "AH", "Home", "-0.25", "1.92")])
    again = repo.write_snapshots([_quote(seed, "AH", "Home", "-0.25", "1.75")])
    assert (first.written, again.written, again.skipped_existing) == (1, 0, 1)
    with db.cursor() as cur:
        cur.execute("SELECT odds_decimal FROM market.odds_snapshots WHERE fixture_id = %s AND market_key = 'AH'",
                    (fixture_9001,))
        assert cur.fetchall() == [(Decimal("1.920"),)]


# ── the schema refuses a line it cannot mean ────────────────────────────────


@pytest.mark.parametrize(
    ("market", "selection", "line", "complaint"),
    [
        ("OU", "Over", "-2.5", "does not take a negative line"),
        ("1X2", "Home", "1.5", "has no line"),
        ("1X2", "Home", "-1", "has no line"),
        ("AH", "Home", "-0.3", r"not a multiple of 0\.25"),
        ("OU", "Over", "2.4", r"not a multiple of 0\.25"),
    ],
)
def test_the_database_refuses_an_impossible_line(db: psycopg.Connection, seed: Seed, fixture_9001: int,
                                                 market: str, selection: str, line: str,
                                                 complaint: str) -> None:
    """Enforced in the schema, not only in Python: a backfill script, a manual
    fix or a new service cannot store a handicap whose sign has been lost."""
    with pytest.raises(psycopg.errors.CheckViolation, match=complaint):
        db.execute(
            "INSERT INTO market.odds_snapshots (fixture_id,bookmaker_id,market_key,selection,line,"
            "odds_decimal,captured_at,minutes_to_ko,source,payload_hash) "
            "VALUES (%s,%s,%s,%s,%s,1.90,%s,12,'prematch',%s)",
            (fixture_9001, seed.bookmaker_id, market, selection, Decimal(line), CAPTURED, seed.payload_hash),
        )


def test_the_same_rule_guards_near_close_and_consensus(db: psycopg.Connection, seed: Seed,
                                                       fixture_9001: int) -> None:
    with pytest.raises(psycopg.errors.CheckViolation, match=r"not a multiple of 0\.25"):
        db.execute(
            "INSERT INTO market.near_close_snapshots (fixture_id,bookmaker_id,market_key,selection,line,"
            "odds_decimal,captured_at,minutes_to_ko,source) VALUES (%s,%s,'AH','Home',0.3,1.90,%s,12,'prematch')",
            (fixture_9001, seed.bookmaker_id, CAPTURED),
        )
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation, match="does not take a negative line"):
        db.execute(
            "INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,"
            "p_fair,n_bookmakers,overround,best_odds,best_bookmaker_id) "
            "VALUES (%s,'OU','Over',-2.5,%s,'shin',0.5,3,1.05,1.90,%s)",
            (fixture_9001, CAPTURED, seed.bookmaker_id),
        )


def test_a_level_handicap_of_zero_is_a_real_line(db: psycopg.Connection, seed: Seed,
                                                 fixture_9001: int) -> None:
    """For AH, 0 means level ball and a draw returns the stake; for 1X2 the same
    stored 0 means "no line at all". market_key is what tells them apart, which
    is why the rule is expressed against market.markets.has_line."""
    written = OddsRepository(db).write_snapshots([
        _quote(seed, "AH", "Home", "0", "1.59"),
        _quote(seed, "1X2", "Home", "0", "2.10"),
    ]).written
    assert written == 2


# ── loading the provider's catalogue ────────────────────────────────────────


def test_the_whole_provider_catalogue_loads_and_maps_only_what_we_model(
    db: psycopg.Connection, seed: Seed
) -> None:
    reports = {r.scope: r for r in load_bet_catalogue(db, directory=CATALOGUE_DIR)}
    assert reports["prematch"].rows_in_file == 338
    assert reports["inplay"].rows_in_file == 266
    assert reports["prematch"].mapped == len(MarketType) == reports["inplay"].mapped
    assert not reports["prematch"].renamed and not reports["inplay"].renamed
    with db.cursor() as cur:
        cur.execute("SELECT count(*), count(market_key) FROM market.provider_markets")
        total, mapped = cur.fetchone() or (0, 0)
    assert (total, mapped) == (604, 10), "604 bets known, 10 mapped (five markets, two scopes)"


def test_the_two_scopes_map_the_same_markets_to_different_bets(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The measurement behind the scope-aware id map: pre-match 4 is Asian
    Handicap, in-play 4 is an extra-time corners market."""
    load_bet_catalogue(db, directory=CATALOGUE_DIR)
    with db.cursor() as cur:
        cur.execute("SELECT scope, provider_bet_id, name FROM market.provider_markets "
                    "WHERE market_key = 'AH' ORDER BY scope")
        assert cur.fetchall() == [("inplay", 33, "Asian Handicap"), ("prematch", 4, "Asian Handicap")]
        cur.execute("SELECT name, market_key FROM market.provider_markets "
                    "WHERE scope = 'inplay' AND provider_bet_id = 4")
        assert cur.fetchone() == ("Extra Time Total Corners (3 Ways) (1st Half)", None)


def test_loading_the_catalogue_twice_changes_nothing(db: psycopg.Connection, seed: Seed) -> None:
    load_bet_catalogue(db, directory=CATALOGUE_DIR)
    again = {r.scope: r for r in load_bet_catalogue(db, directory=CATALOGUE_DIR)}
    assert again["prematch"].inserted == 0 and again["prematch"].refreshed == 338
    assert again["inplay"].inserted == 0 and again["inplay"].refreshed == 266


def test_a_renamed_bet_is_reported_not_swallowed(db: psycopg.Connection, seed: Seed) -> None:
    load_bet_catalogue(db, directory=CATALOGUE_DIR)
    db.execute("UPDATE market.provider_markets SET name = 'Goals Over/Under (old name)' "
               "WHERE scope = 'prematch' AND provider_bet_id = 5")
    report = next(r for r in load_bet_catalogue(db, directory=CATALOGUE_DIR, scopes=["prematch"]))
    assert report.renamed == [(5, "Goals Over/Under (old name)", "Goals Over/Under")]


def test_a_bet_the_provider_stops_listing_is_kept(db: psycopg.Connection, seed: Seed) -> None:
    """Prices captured under it are real, so the row stays and the disappearance
    is reported instead."""
    db.execute("INSERT INTO market.provider_markets (provider,scope,provider_bet_id,name,source) "
               "VALUES ('api-football','prematch',9999,'A Bet That Was Withdrawn','catalogue')")
    report = next(r for r in load_bet_catalogue(db, directory=CATALOGUE_DIR, scopes=["prematch"]))
    assert report.vanished == [(9999, "A Bet That Was Withdrawn")]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM market.provider_markets WHERE provider_bet_id = 9999")
        assert cur.fetchone() == (1,)


def test_a_bet_observed_in_a_payload_but_absent_from_the_catalogue_is_registered(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Straight from OddsParseLog.unmapped_bets. This is what makes a provider
    change visible instead of a skipped row."""
    load_bet_catalogue(db, directory=CATALOGUE_DIR, scopes=["prematch"])
    new = record_observed_bets(db, {(4, "Asian Handicap"): 22, (9998, "Brand New Bet"): 3},
                               scope="prematch")
    assert new == [(9998, "Brand New Bet")], "only the one the catalogue had never mentioned"
    with db.cursor() as cur:
        cur.execute("SELECT source, market_key FROM market.provider_markets "
                    "WHERE scope = 'prematch' AND provider_bet_id = 4")
        assert cur.fetchone() == ("catalogue", "AH"), "an observation confirms a bet, it never unmaps one"
        cur.execute("SELECT source, market_key FROM market.provider_markets WHERE provider_bet_id = 9998")
        assert cur.fetchone() == ("observed", None)


def test_the_bookmaker_list_loads_without_touching_our_own_judgements(
    db: psycopg.Connection, seed: Seed
) -> None:
    db.execute("UPDATE market.bookmakers SET is_sharp = true, consensus_weight = 2.50 "
               "WHERE provider_bookmaker_id = 8")
    assert load_bookmakers(db, directory=CATALOGUE_DIR) == 33
    with db.cursor() as cur:
        cur.execute("SELECT name, is_sharp, consensus_weight FROM market.bookmakers "
                    "WHERE provider_bookmaker_id = 8")
        assert cur.fetchone() == ("Bet365", True, Decimal("2.50"))
        cur.execute("SELECT name FROM market.bookmakers WHERE provider_bookmaker_id = 4")
        assert cur.fetchone() == ("Pinnacle",)

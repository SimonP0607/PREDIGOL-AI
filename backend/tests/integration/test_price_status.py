"""PRICE_UNAVAILABLE and MODEL_INTERESTING_NO_PRICE: each core market's price status before kick-off,
and the model's own number where nothing is priced - never a bookmaker's price, never a pick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.market.price_status import PriceStatus, market_prices
from fbi.picks.no_price import WatchStatus, watch

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 6, 1, 12, tzinfo=UTC)


def _world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, int]:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                "competition_type, is_tracked) VALUES (97201, 'Price League', 'Colombia', 'league', 'club', "
                "'domestic_league', true) RETURNING id")
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                "competition_type, is_tracked) VALUES (97202, 'Dark League', 'Colombia', 'league', 'club', "
                "'domestic_league', true) RETURNING id")
    dark = scalar(cur)
    seasons = {}
    for cid, league, flag in ((comp, 97201, True), (dark, 97202, False)):
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2032, true) "
                    "RETURNING id", (cid,))
        seasons[cid] = scalar(cur)
        cur.execute("INSERT INTO raw.league_coverage (provider_league_id, season, odds, payload_hash, observed_at) "
                    "VALUES (%s, 2032, %s, %s, %s)", (league, flag, seed.payload_hash, AT - timedelta(days=1)))
    cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (9942, 'Second Book') "
                "RETURNING id")
    book2 = scalar(cur)
    ids, pids = {}, {}
    plan = (("priced", comp, AT + timedelta(hours=10)), ("asked", comp, AT + timedelta(hours=10)),
            ("pending", comp, AT + timedelta(days=5)), ("dark", dark, AT + timedelta(hours=10)))
    for n, (name, cid, ko) in enumerate(plan):
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (7320001 + n, seasons[cid], seed.home_team_id, seed.away_team_id, ko))
        ids[name], pids[name] = scalar(cur), 7320001 + n
    for name in ("priced", "asked"):
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                    "file_path, bytes) VALUES (%s, %s, '/odds', %s, %s, 200, 'x', 1)",
                    (f"ps-{name}", seed.run_id, Jsonb({"fixture": pids[name]}), AT - timedelta(hours=2)))
    captured = AT - timedelta(hours=2)
    for book in (seed.bookmaker_id, book2):
        for sel in ("Home", "Draw", "Away"):
            cur.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                        "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) VALUES "
                        "(%s, %s, '1X2', %s, 0, 2.40, %s, 720, 'prematch', %s)",
                        (ids["priced"], book, sel, captured, seed.payload_hash))
    for sel in ("Over", "Under"):
        cur.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                    "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) VALUES "
                    "(%s, %s, 'OU', %s, 2.5, 1.90, %s, 720, 'prematch', %s)",
                    (ids["priced"], seed.bookmaker_id, sel, captured, seed.payload_hash))
    preds = (("1X2", "Home", 0, "0.50", "0.44", "0.56"), ("1X2", "Draw", 0, "0.27", "0.22", "0.32"),
             ("1X2", "Away", 0, "0.23", "0.18", "0.28"), ("OU", "Over", 2.5, "0.55", "0.50", "0.60"),
             ("OU", "Under", 2.5, "0.45", "0.40", "0.50"), ("BTTS", "Yes", 0, "0.52", "0.40", "0.60"),
             ("BTTS", "No", 0, "0.48", "0.40", "0.60"))
    for cutoff, scale in ((AT - timedelta(hours=3), Decimal(1)), (AT + timedelta(hours=1), Decimal("0.5"))):
        for market, sel, line, p, lo, hi in preds:  # the second forecast is made after AT: never read
            cur.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, "
                        "p_raw, p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'fh', %s)",
                        (ids["asked"], seed.model_version_id, market, sel, line, Decimal(p) * scale,
                         Decimal(p) * scale, Decimal(lo) * scale, Decimal(hi) * scale, cutoff))
    return ids


def test_each_core_market_says_why_it_has_no_price(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = _world(db, seed)
    got = {(p.fixture_id, p.market_key): p for p in market_prices(db, list(ids.values()), at=AT)}
    assert got[(ids["priced"], "1X2")].status is PriceStatus.PRICED
    assert got[(ids["priced"], "1X2")].bookmakers == 2
    assert got[(ids["priced"], "OU")].status is PriceStatus.THIN_PRICE
    assert got[(ids["priced"], "BTTS")].status is PriceStatus.PRICE_UNAVAILABLE, "asked; other markets only"
    assert {got[(ids["asked"], m)].status for m in ("1X2", "OU", "BTTS")} == {PriceStatus.PRICE_UNAVAILABLE}
    assert {got[(ids["pending"], m)].status for m in ("1X2", "OU", "BTTS")} == {PriceStatus.PRICE_PENDING}
    assert {got[(ids["dark"], m)].status for m in ("1X2", "OU", "BTTS")} == {PriceStatus.NOT_COVERED}


def test_the_model_view_is_its_own_number_and_never_a_price(db: psycopg.Connection[Any], seed: Seed) -> None:
    ids = _world(db, seed)
    views = {(v.fixture_id, v.market_key): v for v in watch(db, list(ids.values()), at=AT)}
    assert set(views) == {(ids["asked"], m) for m in ("1X2", "OU", "BTTS")}, \
        "only markets with no price at all, and only where the watch model forecast before now"
    home = views[(ids["asked"], "1X2")]
    assert home.selection == "Home" and home.status is WatchStatus.MODEL_INTERESTING_NO_PRICE
    assert home.fair_odds == Decimal("2.00") and home.min_odds == Decimal("2.39"), "1.05 / 0.44"
    assert home.evaluation_mode and home.rule_version == "no-price-watch-v1"
    assert views[(ids["asked"], "OU")].min_odds == Decimal("2.10")
    assert views[(ids["asked"], "BTTS")].selection == "Yes", "the model's most likely outcome"
    assert all(v.data_cutoff_ts < AT for v in views.values()), "a forecast made after now is never read"

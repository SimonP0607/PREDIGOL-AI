"""/odds/mapping read by the capture and by the price status (5 Oct 2026).

The mapping lists the fixtures the provider prices. It overrules a season's coverage flag that says "no odds" (the
flag is per season and can be stale; the mapping names the fixture), and it is never used to leave a fixture out:
measured that day, four fixtures were priced 25-86 minutes before the daily listing named them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from scripts.capture_odds import _upcoming

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.market.price_status import PriceStatus, market_prices

from .conftest import Seed
from .helpers import scalar

AT = datetime(2033, 3, 1, 12, tzinfo=UTC)


def _world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, tuple[int, int]]:
    """Three fixtures in 10 h: two in a season flagged 'no odds' (one listed by the mapping), one in a season with
    no coverage row at all."""
    cur = db.cursor()
    out: dict[str, tuple[int, int]] = {}
    seasons = {}
    for league, flag in ((97301, False), (97302, None)):
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', 'domestic_league', "
                    "true) RETURNING id", (league, f"League {league}"))
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2033, true) "
                    "RETURNING id", (comp,))
        seasons[league] = scalar(cur)
        if flag is not None:
            cur.execute("INSERT INTO raw.league_coverage (provider_league_id, season, odds, payload_hash, observed_at) "
                        "VALUES (%s, 2033, %s, %s, %s)", (league, flag, seed.payload_hash, AT - timedelta(days=1)))
    for n, (name, league) in enumerate((("listed", 97301), ("unlisted", 97301), ("no_flag", 97302))):
        pid = 7330001 + n
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at, status_group, status_short) VALUES (%s, %s, %s, %s, %s, 'scheduled', 'NS') "
                    "RETURNING id", (pid, seasons[league], seed.home_team_id, seed.away_team_id,
                                      AT + timedelta(hours=10)))
        out[name] = (scalar(cur), pid)
    cur.execute("INSERT INTO market.odds_mapping_seen (provider_fixture_id, provider_league_id, season, fixture_date, "
                "first_seen_at, payload_hash, normalizer_version) VALUES (%s, 97301, 2033, %s, %s, %s, 'reference-1')",
                (out["listed"][1], AT + timedelta(hours=10), AT - timedelta(hours=6), seed.payload_hash))
    return out


def test_a_listed_fixture_is_asked_where_the_coverage_flag_says_no_odds(db: psycopg.Connection[Any],
                                                                       seed: Seed) -> None:
    world = _world(db, seed)
    set_clock(FrozenClock(AT))
    try:
        got = {f.provider_fixture_id for f in _upcoming(db, 96)}
    finally:
        set_clock(SystemClock())
    assert world["listed"][1] in got, "the mapping overrules the season's 'no odds' flag"
    assert world["unlisted"][1] not in got, "the flag still holds where the mapping says nothing"
    assert world["no_flag"][1] in got, "no coverage row: asked, as before"


def test_price_status_reads_the_mapping_and_every_ask(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = _world(db, seed)
    ids = [world[k][0] for k in ("listed", "unlisted", "no_flag")]
    got = {(p.fixture_id, p.market_key): p for p in market_prices(db, ids, at=AT)}
    assert got[(world["listed"][0], "1X2")].status is PriceStatus.PRICE_PENDING, "listed: not 'not covered'"
    assert got[(world["unlisted"][0], "1X2")].status is PriceStatus.NOT_COVERED
    # Asked twice with an empty answer: RAW keeps the first (identical bytes are stored once), market.odds_asks both.
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES ('om-empty', %s, '/odds', %s, %s, 200, 'x', 1)",
               (seed.run_id, Jsonb({"fixture": world["no_flag"][1]}), AT - timedelta(hours=30)))
    for hours in (30, 2):
        db.execute("INSERT INTO market.odds_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, "
                   "results, quotes, payload_hash) VALUES (%s, %s, %s, 720, 0, 0, 'om-empty')",
                   (world["no_flag"][1], AT - timedelta(hours=hours), (hours + 10) * 60))
    again = {(p.fixture_id, p.market_key): p for p in market_prices(db, ids, at=AT)}
    assert again[(world["no_flag"][0], "1X2")].last_asked == AT - timedelta(hours=2), "the newest ask, not RAW's"
    assert again[(world["no_flag"][0], "1X2")].status is PriceStatus.PRICE_UNAVAILABLE

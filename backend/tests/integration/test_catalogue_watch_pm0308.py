"""PM-03-08 (DOC-010): the watch reads raw.league_coverage as the daily /leagues stored it - one row per league with its newest
season's name and country - and reports a league added in a priority country and a waiting competition's new edition."""

from __future__ import annotations

from datetime import UTC, date, datetime

import psycopg

from fbi.catalog import watch
from tests.integration.conftest import Seed

NEW = 9961
"""A league id the provider "adds" in Panama."""
BACK = 9962
"""A discontinued competition, listed with an old season and then a new one."""


def _cov(conn: psycopg.Connection, seed: Seed, league: int, season: int, name: str, country: str) -> None:
    conn.execute(
        "INSERT INTO raw.league_coverage (provider_league_id, season, league_name, country, league_type, is_current, "
        "start_date, end_date, events, lineups, statistics_fixtures, statistics_players, standings, odds, "
        "payload_hash, observed_at) VALUES (%s, %s, %s, %s, 'Cup', true, %s, %s, true, true, false, false, false, false, %s, %s)",
        (league, season, name, country, date(season, 2, 1), date(season, 11, 1), seed.payload_hash,
         datetime(2026, 11, 20, tzinfo=UTC)))


def test_the_watch_reads_what_the_catalogue_stored(migrated_database: str, seed: Seed) -> None:
    config = watch.WatchConfig(
        known={"Panama": frozenset({304}), "Mexico": frozenset({BACK})},
        waiting=(watch.Waiting(BACK, "Copa", "Mexico", "descontinuada", 2019),),
        missing=(), baseline_at="2026-11-20T14:27:03Z")
    with psycopg.connect(migrated_database) as conn:
        try:
            _cov(conn, seed, BACK, 2019, "Copa", "Mexico")
            assert [f for f in watch.check(conn, config) if f.league_id in (NEW, BACK)] == []
            _cov(conn, seed, BACK, 2027, "Copa (nueva)", "Mexico")
            _cov(conn, seed, NEW, 2026, "Liga Prom", "Panama")
            _cov(conn, seed, NEW, 2027, "Liga Prom", "Panama")
            found = [f for f in watch.check(conn, config) if f.league_id in (NEW, BACK)]
            assert [(f.kind, f.league_id, f.name, f.season) for f in found] == [
                ("nueva", NEW, "Liga Prom", 2027), ("edicion", BACK, "Copa (nueva)", 2027)]
        finally:
            conn.rollback()
            conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id IN (%s, %s)", (NEW, BACK))
            conn.commit()

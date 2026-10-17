"""P3: an expansion batch is tracked from the /leagues answer on disk, and migrated as its own tier."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest

from fbi.migration.config import MIGRATION_FILE, ConfigError, load_migration_config
from tests.integration.conftest import Seed

LEAGUE = 9955


def coverage(conn: psycopg.Connection, seed: Seed, season: int, current: bool) -> None:
    conn.execute(
        "INSERT INTO raw.league_coverage (provider_league_id, season, league_name, country, league_type, is_current, "
        "start_date, end_date, events, lineups, statistics_fixtures, statistics_players, standings, odds, "
        "payload_hash, observed_at) VALUES (%s, %s, 'Expansion League', 'Finland', 'League', %s, %s, %s, true, true, "
        "false, false, true, %s, %s, %s)",
        (LEAGUE, season, current, date(season, 4, 1), date(season, 11, 1), current, seed.payload_hash,
         datetime(2026, 10, 5, tzinfo=UTC)))


def test_a_batch_is_tracked_from_coverage_on_disk_and_nothing_else_changes(migrated_database: str, seed: Seed) -> None:
    from scripts.expand_leagues import expand

    batch = {"batch": 9, "tier": 5, "leagues": [LEAGUE], "names": {LEAGUE: "Expansion League"}}
    with psycopg.connect(migrated_database) as conn:
        try:
            refused = expand(conn, batch, apply=True)
            assert refused["missing"] == [LEAGUE] and "refused" in refused, "no coverage on disk, no tracking"
            coverage(conn, seed, 2025, False)
            coverage(conn, seed, 2026, True)
            tracked_before = conn.execute("SELECT count(*) FROM core.competitions WHERE is_tracked").fetchone()
            dry = expand(conn, batch, apply=False)
            assert [(r["seasons_listed"], r["current_season"], r["known"]) for r in dry["leagues"]] == [(2, 2026, False)]
            assert conn.execute("SELECT count(*) FROM core.competitions WHERE provider_league_id = %s",
                                (LEAGUE,)).fetchone() == (0,), "a dry run writes nothing"
            done = expand(conn, batch, apply=True)
            row = conn.execute("SELECT is_tracked, tier, competition_type, elo_weight::text FROM core.competitions "
                               "WHERE provider_league_id = %s", (LEAGUE,)).fetchone()
            assert row == (True, 5, "domestic_league", "1.00")
            seasons = conn.execute("SELECT cs.season, cs.is_current FROM core.competition_seasons cs JOIN "
                                   "core.competitions c ON c.id = cs.competition_id WHERE c.provider_league_id = %s "
                                   "ORDER BY 1", (LEAGUE,)).fetchall()
            assert seasons == [(2025, False), (2026, True)]
            after = conn.execute("SELECT count(*) FROM core.competitions WHERE is_tracked").fetchone()
            assert tracked_before is not None and after == (tracked_before[0] + 1,), "only the batch is tracked"
            run = conn.execute("SELECT job_type, status, api_calls, rows_written FROM raw.ingestion_runs WHERE id = %s",
                               (done["run_id"],)).fetchone()
            assert run is not None and run[:3] == ("league_expansion", "completed", 0)
        finally:
            conn.rollback()
            conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN "
                         "(SELECT id FROM core.competitions WHERE provider_league_id = %s)", (LEAGUE,))
            conn.execute("DELETE FROM core.competitions WHERE provider_league_id = %s", (LEAGUE,))
            conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = %s", (LEAGUE,))
            conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'league_expansion'")
            conn.commit()


def test_a_batch_is_merged_as_the_tier_after_the_selection(tmp_path: Path) -> None:
    expansion = tmp_path / "expansion.yaml"
    expansion.write_text("candidates:\n  - {rank: 1, league_id: 9955, name: Expansion League}\n"
                         "batches:\n  - {batch: 1, tier: 5, leagues: [9955, 39]}\n", encoding="utf-8")
    cfg = load_migration_config(MIGRATION_FILE, expansion=expansion)
    mine = [(c.tier, c.league_id, c.name) for c in cfg.competitions if c.tier == 5]
    assert mine == [(5, 9955, "Expansion League")], "a league the selection migrates stays in its own tier"
    assert cfg.tiers[5] == "P3 expansion - batch 1"
    expansion.write_text("batches:\n  - {batch: 1, tier: 2, leagues: [9955]}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="already a tier"):
        load_migration_config(MIGRATION_FILE, expansion=expansion)

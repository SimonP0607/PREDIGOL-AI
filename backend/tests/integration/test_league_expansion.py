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


BATCH2 = {29: ("World Cup - Qualification Africa", "League"), 33: ("World Cup - Qualification Oceania", "League"),
          7: ("Asian Cup", "Cup")}
OTHERS = (9956, 9957)  # one tracked, one known but not tracked: neither may change


def provider_coverage(conn: psycopg.Connection, seed: Seed, league: int, name: str, kind: str, season: int,
                      current: bool, country: str = "World") -> None:
    conn.execute(
        "INSERT INTO raw.league_coverage (provider_league_id, season, league_name, country, league_type, is_current, "
        "start_date, end_date, events, lineups, statistics_fixtures, statistics_players, standings, odds, "
        "payload_hash, observed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, true, true, true, true, %s, %s, %s)",
        (league, season, name, country, kind, current, date(season, 1, 1), date(season + 1, 6, 1), current,
         seed.payload_hash, datetime(2026, 11, 5, tzinfo=UTC)))


def _clean(conn: psycopg.Connection, leagues: list[int]) -> None:
    conn.rollback()
    conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN "
                 "(SELECT id FROM core.competitions WHERE provider_league_id = ANY(%s))", (leagues,))
    conn.execute("DELETE FROM core.competitions WHERE provider_league_id = ANY(%s)", (leagues,))
    conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = ANY(%s)", (leagues,))
    conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'league_expansion'")
    conn.commit()


def test_batch_2_tracks_the_three_national_team_competitions_and_nothing_else(
        migrated_database: str, seed: Seed) -> None:
    """BE-002: the real batch 2 of config/expansion.yaml, dry run then --apply, on the test database."""
    from scripts.expand_leagues import batch_of, expand

    batch = batch_of(2)
    leagues = sorted(BATCH2)
    with psycopg.connect(migrated_database) as conn:
        try:
            for lid, (name, kind) in BATCH2.items():
                provider_coverage(conn, seed, lid, name, kind, 2025, False)
                provider_coverage(conn, seed, lid, name, kind, 2026, True)
            for lid, tracked in zip(OTHERS, (True, False), strict=True):
                conn.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type, is_tracked, tier) VALUES (%s, 'Other', 'league', 'club', "
                             "'domestic_league', %s, 2)", (lid, tracked))
            conn.commit()
            before = conn.execute("SELECT provider_league_id, is_tracked, tier FROM core.competitions "
                                  "ORDER BY 1").fetchall()

            dry = expand(conn, batch, apply=False)
            assert "refused" not in dry and "catalogue" not in dry
            assert [(r["provider_league_id"], r["seasons_listed"], r["current_season"], r["known"])
                    for r in dry["leagues"]] == [(7, 2, 2026, False), (29, 2, 2026, False), (33, 2, 2026, False)]
            after_dry = conn.execute("SELECT provider_league_id, is_tracked, tier FROM core.competitions "
                                     "ORDER BY 1").fetchall()
            assert after_dry == before, "a dry run writes nothing"

            done = expand(conn, batch, apply=True)
            assert done["catalogue"]["competitions_inserted"] == 3 and done["catalogue"]["seasons_inserted"] == 6
            rows = conn.execute("SELECT provider_league_id, name, is_tracked, tier, entity_scope, competition_type "
                                "FROM core.competitions WHERE provider_league_id = ANY(%s) ORDER BY 1",
                                (leagues,)).fetchall()
            assert rows == [
                # A Cup of country World is catalogued continental until sync_teams --scopes-only reads its teams,
                # as the World Cup, Euro and Africa Cup of Nations were.
                (7, "Asian Cup", True, 6, "club", "continental"),
                (29, "World Cup - Qualification Africa", True, 6, "national_team", "international"),
                (33, "World Cup - Qualification Oceania", True, 6, "national_team", "international"),
            ]
            after = conn.execute("SELECT provider_league_id, is_tracked, tier FROM core.competitions "
                                 "WHERE NOT (provider_league_id = ANY(%s)) ORDER BY 1", (leagues,)).fetchall()
            assert after == before, "no other competition's tracking or tier changed"
            run = conn.execute("SELECT job_type, status, api_calls FROM raw.ingestion_runs WHERE id = %s",
                               (done["run_id"],)).fetchone()
            assert run == ("league_expansion", "completed", 0)
        finally:
            _clean(conn, [*leagues, *OTHERS])


def test_a_league_the_provider_names_differently_is_refused_and_nothing_is_written(
        migrated_database: str, seed: Seed) -> None:
    """A wrong id in config/expansion.yaml must stop the batch, not track some other competition."""
    from scripts.expand_leagues import batch_of, expand

    batch = batch_of(2)
    leagues = sorted(BATCH2)
    with psycopg.connect(migrated_database) as conn:
        try:
            provider_coverage(conn, seed, 29, "World Cup - Qualification Africa", "League", 2026, True)
            provider_coverage(conn, seed, 33, "World Cup - Qualification Oceania", "League", 2026, True)
            provider_coverage(conn, seed, 7, "Some Other Cup", "Cup", 2026, True, country="Japan")
            conn.commit()
            out = expand(conn, batch, apply=True)
            assert "refused" in out and "catalogue" not in out
            assert out["mismatched"] == ["7: provider calls it 'Some Other Cup', config says 'Asian Cup'",
                                         "7: provider country 'Japan', config says 'World'"]
            assert conn.execute("SELECT count(*) FROM core.competitions WHERE provider_league_id = ANY(%s)",
                                (leagues,)).fetchone() == (0,)
            assert conn.execute("SELECT count(*) FROM raw.ingestion_runs WHERE job_type = 'league_expansion'"
                                ).fetchone() == (0,)
        finally:
            _clean(conn, leagues)


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


# IA-077: as production had them on 17 Nov 2026 - known to the catalogue, not tracked, older tiers and one older name.
IA077 = {299: ("Primera División", "League", "Venezuela", "Primera División", 8, "domestic_league", 1.00),
         240: ("Primera B", "League", "Colombia", "Primera B", 5, "domestic_league", 1.00),
         268: ("Primera División", "League", "Uruguay", "Primera División - Apertura", 7, "domestic_league", 1.00),
         241: ("Copa Colombia", "Cup", "Colombia", "Copa Colombia", 5, "domestic_cup", 0.40)}


def test_batches_3_and_4_track_and_untrack_the_four_competitions_and_nothing_else(
        migrated_database: str, seed: Seed) -> None:
    """IA-077: the real batches 3 and 4, dry run, --apply, then --untrack --apply - only their own rows move."""
    from scripts.expand_leagues import batch_of, expand

    leagues = sorted(IA077)
    with psycopg.connect(migrated_database) as conn:
        try:
            for lid, (name, kind, country, ours, tier, comp_type, elo) in IA077.items():
                provider_coverage(conn, seed, lid, name, kind, 2025, False, country=country)
                provider_coverage(conn, seed, lid, name, kind, 2026, True, country=country)
                conn.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                             "competition_type, elo_weight, is_tracked, tier) VALUES (%s, %s, %s, %s, 'club', %s, %s, "
                             "false, %s)", (lid, ours, country, kind.lower(), comp_type, elo, tier))
            for lid, tracked in zip(OTHERS, (True, False), strict=True):
                conn.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type, is_tracked, tier) VALUES (%s, 'Other', 'league', 'club', "
                             "'domestic_league', %s, 2)", (lid, tracked))
            conn.commit()
            others = "SELECT provider_league_id, is_tracked, tier FROM core.competitions " \
                     "WHERE NOT (provider_league_id = ANY(%s)) ORDER BY 1"
            before = conn.execute(others, (leagues,)).fetchall()
            mine = ("SELECT provider_league_id, name, is_tracked, tier, competition_type, elo_weight::text "
                    "FROM core.competitions WHERE provider_league_id = ANY(%s) ORDER BY 1")
            untouched = conn.execute(mine, (leagues,)).fetchall()

            for number in (3, 4):
                dry = expand(conn, batch_of(number), apply=False)
                assert "refused" not in dry and "catalogue" not in dry, dry
                assert all(r["known"] and not r["tracked"] for r in dry["leagues"])
            assert conn.execute(mine, (leagues,)).fetchall() == untouched, "a dry run writes nothing"

            done3 = expand(conn, batch_of(3), apply=True)
            assert done3["catalogue"]["competitions_updated"] == 2 and done3["catalogue"]["competitions_inserted"] == 0
            after3 = conn.execute(mine, (leagues,)).fetchall()
            assert [(r[0], r[2], r[3]) for r in after3] == [(240, True, 7), (241, False, 5), (268, False, 7),
                                                            (299, True, 7)], "batch 3 alone: batch 4 waits"
            expand(conn, batch_of(4), apply=True)
            assert conn.execute(mine, (leagues,)).fetchall() == [
                (240, "Primera B", True, 7, "domestic_league", "1.00"),
                (241, "Copa Colombia", True, 8, "domestic_cup", "0.40"),
                # The provider's name replaces the older one; the Elo weight is not rewritten.
                (268, "Primera División", True, 8, "domestic_league", "1.00"),
                (299, "Primera División", True, 7, "domestic_league", "1.00"),
            ]
            assert conn.execute(others, (leagues,)).fetchall() == before, "no other competition changed"

            seasons = ("SELECT count(*) FROM core.competition_seasons cs JOIN core.competitions c "
                       "ON c.id = cs.competition_id WHERE c.provider_league_id = ANY(%s)")
            assert conn.execute(seasons, (leagues,)).fetchone() == (8,)
            back = expand(conn, batch_of(4), apply=True, untrack=True)
            assert back["untrack"] is True and "catalogue" in back
            assert [(r[0], r[2], r[3]) for r in conn.execute(mine, (leagues,)).fetchall()] == [
                (240, True, 7), (241, False, 8), (268, False, 8), (299, True, 7)], "only batch 4 stops"
            assert conn.execute(seasons, (leagues,)).fetchone() == (8,), "untracking deletes nothing"
            assert conn.execute(others, (leagues,)).fetchall() == before
            runs = conn.execute("SELECT params->>'batch', params->>'untrack', status, api_calls, notes "
                                "FROM raw.ingestion_runs WHERE job_type = 'league_expansion' ORDER BY id").fetchall()
            assert runs == [("3", "false", "completed", 0, "expansion batch 3: 2 league(s) tracked"),
                            ("4", "false", "completed", 0, "expansion batch 4: 2 league(s) tracked"),
                            ("4", "true", "completed", 0, "expansion batch 4: 2 league(s) untracked")]
        finally:
            _clean(conn, [*leagues, *OTHERS])

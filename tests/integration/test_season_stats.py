"""The provider's season aggregates, kept as the provider's (fbi.ingestion.season_stats): a player's per team
and competition (/players), a team's per competition season (/teams/statistics); averages and totals apart,
the rating as sent, a row per change; the weekly sweep of current seasons is one set of units per ISO week."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ingestion.people import seed_player_seasons
from fbi.ingestion.season_stats import apply_player_season_stats, apply_team_statistics
from tests.integration.conftest import Seed

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime = T0) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/players', '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING",
               (h, seed.run_id, at, h))
    return h


def player(goals: int, rating: str = "7.55") -> dict[str, Any]:
    return {"response": [{"player": {"id": 13491, "name": "Y. Guzmán"}, "statistics": [
        {"team": {"id": 1138}, "league": {"id": 239, "season": 2026},
         "games": {"appearences": 29, "lineups": 27, "minutes": 2397, "position": "Attacker", "rating": rating,
                   "captain": False},
         "goals": {"total": goals, "assists": 4}, "penalty": {"won": 2, "commited": None, "scored": 3},
         "cards": {"yellow": 4, "yellowred": 0, "red": 0}},
        {"team": {"id": 0}, "league": {"id": 239, "season": 2026}, "games": {"minutes": 10}}]}]}


def test_a_players_season_aggregate_is_the_providers_and_kept_change_only(db: psycopg.Connection,
                                                                         seed: Seed) -> None:
    for i in range(3):
        payload(db, seed, f"ps{i}", T0 + timedelta(days=i))
    assert apply_player_season_stats(db, player(18), payload_hash="ps0", observed_at=T0) == 1
    assert apply_player_season_stats(db, player(18), payload_hash="ps1", observed_at=T0 + timedelta(days=1)) == 0
    assert apply_player_season_stats(db, player(19), payload_hash="ps2", observed_at=T0 + timedelta(days=2)) == 1
    row = db.execute("SELECT goals, assists, appearances, rating, penalties_scored, penalties_committed, captain, "
                     "payload_hash FROM core.player_season_stats_latest WHERE provider_player_id = 13491").fetchone()
    assert row == (19, 4, 29, Decimal("7.550000"), 3, None, False, "ps2")


TEAM = {"response": {
    "league": {"id": 39, "season": 2025}, "team": {"id": 33}, "form": "WWDL",
    "fixtures": {"played": {"home": 4, "away": 2, "total": 6}, "wins": {"home": 4, "away": 2, "total": 6},
                 "draws": {"home": 0, "away": 0, "total": 0}, "loses": {"home": 0, "away": 0, "total": 0}},
    "goals": {"for": {"total": {"home": 18, "away": 4, "total": 22}, "average": {"home": "4.5", "away": "2.0"}},
              "against": {"total": {"home": 2, "away": 1, "total": 3}, "average": {"home": "0.5", "away": "0.5"}}},
    "clean_sheet": {"home": 2, "away": 1, "total": 3}, "failed_to_score": {"home": 0, "away": 0, "total": 0},
    "penalty": {"scored": {"total": 1}, "missed": {"total": 0}}, "lineups": [{"formation": "4-2-3-1", "played": 3}]}}


def test_a_teams_statistics_keep_averages_and_totals_apart(db: psycopg.Connection, seed: Seed) -> None:
    payload(db, seed, "ts0")
    assert apply_team_statistics(db, seed.season_id, seed.home_team_id, TEAM, payload_hash="ts0", observed_at=T0) == 1
    assert apply_team_statistics(db, seed.season_id, seed.home_team_id, TEAM, payload_hash="ts0", observed_at=T0) == 0
    row = db.execute("SELECT goals_for_home, goals_for_total_home, clean_sheets_home, form, raw->'lineups', "
                     "raw ? 'league', payload_hash FROM core.team_season_stats_latest WHERE team_id = %s",
                     (seed.home_team_id,)).fetchone()
    assert row == (Decimal("4.500"), 18, 2, "WWDL", [{"formation": "4-2-3-1", "played": 3}], False, "ts0")


def test_the_weekly_player_sweep_is_one_set_of_units_per_week_and_six_days_apart(db: psycopg.Connection, seed: Seed) -> None:
    """The seed commits (it is a worker step), so the test puts back what it changed."""
    try:
        db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        assert seed_player_seasons(db, at=T0) == 1
        assert seed_player_seasons(db, at=T0 - timedelta(hours=6)) == 0, "same ISO week"
        assert seed_player_seasons(db, at=T0 + timedelta(days=1)) == 0, \
            "Monday is a new ISO week, but the season was swept a day ago (4-5 Oct 2026: 3,200 requests for nothing)"
        assert seed_player_seasons(db, at=T0 + timedelta(days=6, hours=1)) == 1, "six days on: the next sweep"
        keys = db.execute("SELECT batch_key, params->>'page' FROM raw.backfill_tasks WHERE kind = 'players_season' "
                          "ORDER BY batch_key").fetchall()
        assert keys == [("w202640", "1"), ("w202641", "1")]
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind = 'players_season'")
        db.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
        db.execute("UPDATE core.competition_seasons SET is_current = false WHERE id = %s", (seed.season_id,))
        db.commit()

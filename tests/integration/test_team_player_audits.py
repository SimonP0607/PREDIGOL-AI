"""The teams and players audits (database only): a national side not flagged national is reported; the product's
club is never a national side; coverage is counted over the players and teams of current tracked seasons."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
from scripts import audit_players, audit_teams

from tests.integration.conftest import Seed


def current(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))


def test_a_national_side_playing_as_a_club_is_reported(db: psycopg.Connection, seed: Seed) -> None:
    current(db, seed)
    db.execute("UPDATE core.competitions SET entity_scope = 'national_team' WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.fixtures SET kickoff_at = now() - interval '10 days' WHERE id = %s", (seed.fixture_id,))
    result, items = audit_teams.audit(db)
    assert result["summary"]["coverage"]["teams"] == 2
    flagged = {e.key for e in items if e.issue_type == "IDENTITY_MAPPING_ERROR"}
    assert flagged == {"teams:national_flag:33", "teams:national_flag:40"}


def test_the_products_club_is_never_a_national_side(db: psycopg.Connection, seed: Seed) -> None:
    current(db, seed)
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_group = 'finished' WHERE id = %s",
               (datetime.now(UTC) - timedelta(days=5), seed.fixture_id))
    db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (909, 'A. Striker')")
    db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
               "payload_hash, fetched_at) VALUES (%s, 'api-football', 909, 'home', 90, %s, now())",
               (seed.fixture_id, seed.payload_hash))
    result, items = audit_players.audit(db)
    s = result["summary"]
    assert s["coverage"]["players"] == 1 and s["players_checked"] == 1
    assert s["club_is_national"] == 0 and items == []
    assert s["club_source"]["appearances"] == 1

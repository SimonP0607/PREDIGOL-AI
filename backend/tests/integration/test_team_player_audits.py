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
    db.execute("UPDATE core.fixture_player_stats SET rating = 0 WHERE provider_player_id = 909")
    _, items = audit_players.audit(db)
    assert [(e.key, e.at_fault, e.status) for e in items] == [("players:rating_zero", "provider", "MONITOR")]


def test_a_youth_national_side_the_provider_flags_as_a_club_is_never_a_players_club(db: psycopg.Connection,
                                                                                   seed: Seed) -> None:
    """Bolivia U20 is national=false at the provider. It plays only national-team competitions, so PrediGol
    classifies it national (core.team_kind) and the player's club stays the club he plays for."""
    from fbi.api.services import center
    from fbi.catalog.team_kind import refresh_team_kind

    now_ = datetime.now(UTC)
    friendly = db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                          "competition_type) VALUES (10, 'Friendlies', 'cup', 'national_team', 'international') "
                          "RETURNING id").fetchone()
    assert friendly is not None
    fs = db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                    (friendly[0],)).fetchone()
    assert fs is not None
    teams = {}
    for pid, name in ((16199, "Bolivia U20"), (16200, "Chile U20"), (3700, "Bolivar")):
        row = db.execute("INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (%s, %s, false) "
                         "RETURNING id", (pid, name)).fetchone()
        assert row is not None
        teams[name] = int(row[0])
    league_fx = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                           "away_team_id, kickoff_at, status_group) VALUES (7001, %s, %s, %s, %s, 'finished') "
                           "RETURNING id", (seed.season_id, teams["Bolivar"], seed.away_team_id,
                                            now_ - timedelta(days=20))).fetchone()
    youth_fx = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                          "away_team_id, kickoff_at, status_group) VALUES (7002, %s, %s, %s, %s, 'finished') "
                          "RETURNING id", (fs[0], teams["Bolivia U20"], teams["Chile U20"],
                                           now_ - timedelta(days=3))).fetchone()
    assert league_fx is not None and youth_fx is not None
    player = db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (5555, 'J. Joven') RETURNING id"
                        ).fetchone()
    assert player is not None
    for fx in (league_fx[0], youth_fx[0]):
        db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                   "payload_hash, fetched_at) VALUES (%s, 'api-football', 5555, 'home', 90, %s, now())",
                   (fx, seed.payload_hash))
    refresh_team_kind(db, at=now_)
    kinds: dict[str, bool] = dict(db.execute("SELECT t.name, k.is_national FROM core.team_kind k "
                                             "JOIN core.teams t ON t.id = k.team_id "
                                             "WHERE t.provider_team_id IN (16199, 3700)").fetchall())
    assert kinds == {"Bolivia U20": True, "Bolivar": False}
    detail = center.player(db, int(player[0])).data
    assert detail is not None
    assert (detail.player.team, detail.player.national_team, detail.player.last_team) == (
        "Bolivar", "Bolivia U20", "Bolivia U20")

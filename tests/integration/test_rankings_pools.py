"""Elo rankings one rating pool at a time: senior men, women, youth never play each other.

On 5 Oct 2026 the Rankings page put Barcelona W (2126) second, above Manchester City (2111): two numbers from walks
that never meet, ranked as if they could."""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg

from fbi.api.services.rankings import rankings
from tests.integration.helpers import scalar

KO = datetime(2030, 2, 1, 15, 0, tzinfo=UTC)


def _team_with_rating(cur: psycopg.Cursor, run: int, comp_name: str, team: str, rating: float, n: int) -> None:
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (970000 + n, comp_name))
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2030) RETURNING id", (comp,))
    season = scalar(cur)
    cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (980000 + n, team))
    home = scalar(cur)
    cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                (990000 + n, f"{team} rival"))
    away = scalar(cur)
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id", (960000 + n, season, home, away, KO))
    fixture = scalar(cur)
    cur.execute("INSERT INTO features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, rating_before, "
                "rating_after, expected_score, actual_score, k_factor, margin_multiplier, computed_at) "
                "VALUES ('elo-pool-test', %s, %s, %s, %s, %s, %s, 0.5, 1, 20, 1, '2030-02-02')",
                (run, home, fixture, KO, rating - 10, rating))


def test_each_pool_ranks_only_its_own_teams(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                            "VALUES ('t', 'elo_refresh', 'completed', now()) RETURNING id")
                run = scalar(cur)
                _team_with_rating(cur, run, "Pool Test League", "Pool City", 2111, 1)
                _team_with_rating(cur, run, "Pool Test League Women", "Pool Barcelona W", 2126, 2)
                _team_with_rating(cur, run, "Friendlies Pool", "Pool Hungary U18", 1900, 3)
                _team_with_rating(cur, run, "Pool Test Cup", "Pool United W", 1700, 4)

            def names(pool: str) -> list[str]:
                body = rankings(conn, competition_id=None, limit=50, pool=pool).data
                assert body is not None and body.elo_version == "elo-pool-test"
                return [r.team for r in body.rows]

            assert names("men") == ["Pool City"], "a women's or a youth side is not ranked among senior men"
            assert names("women") == ["Pool Barcelona W", "Pool United W"], "by its league, or by its ' W' name"
            assert names("youth") == ["Pool Hungary U18"], "a U18 side in a friendly is still youth"
            assert names("all") == ["Pool Barcelona W", "Pool City", "Pool Hungary U18", "Pool United W"]
            assert names("bogus") == ["Pool City"], "an unknown pool falls back to senior men"
        finally:
            conn.rollback()

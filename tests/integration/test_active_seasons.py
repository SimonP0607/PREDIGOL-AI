"""The fixtures sync spends one request per active season, so "active" matters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from fbi.ingestion.fixtures import FINISHED_GRACE_DAYS, active_seasons
from tests.integration.helpers import scalar


def make_season(
    cur: psycopg.Cursor, league_id: int, *, is_current: bool, last_kickoff: object
) -> int:
    cur.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, "
        " entity_scope, competition_type, is_tracked) "
        "VALUES (%s, %s, 'cup', 'national_team', 'domestic_cup', true) RETURNING id",
        (league_id, f"Test {league_id}"),
    )
    comp = scalar(cur)
    cur.execute(
        "INSERT INTO core.competition_seasons (competition_id, season, is_current) "
        "VALUES (%s, 2026, %s) RETURNING id",
        (comp, is_current),
    )
    season = scalar(cur)
    if last_kickoff is not None:
        cur.execute(
            "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A'), (%s, 'B') "
            "RETURNING id",
            (900000 + league_id, 910000 + league_id),
        )
        cur.execute(
            "SELECT id FROM core.teams WHERE provider_team_id IN (%s, %s) ORDER BY id",
            (900000 + league_id, 910000 + league_id),
        )
        home, away = (r[0] for r in cur.fetchall())
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, "
            " home_team_id, away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s)",
            (950000 + league_id, season, home, away, last_kickoff),
        )
    return season


def test_a_season_whose_last_fixture_is_long_past_is_not_refreshed(
    db: psycopg.Connection,
) -> None:
    """is_current is the provider's answer and it is reliable - one current
    season per tracked competition. What it does not say is whether that season
    is OVER: World Cup qualifying stays current for years, and 23 of the 124
    current seasons had already played their last fixture more than a month
    before. A quarter of this job's requests, twice a day, asking a finished
    competition whether anything had changed.
    """
    stale_at = datetime.now(UTC) - timedelta(days=FINISHED_GRACE_DAYS + 10)
    with db.cursor() as cur:
        make_season(cur, 97001, is_current=True, last_kickoff=stale_at)
    leagues = {s.provider_league_id for s in active_seasons(db)}
    assert 97001 not in leagues


def test_a_season_still_playing_is_refreshed(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        make_season(cur, 97002, is_current=True,
                    last_kickoff=datetime.now(UTC) + timedelta(days=7))
    assert 97002 in {s.provider_league_id for s in active_seasons(db)}


def test_a_season_inside_the_grace_window_is_still_refreshed(
    db: psycopg.Connection,
) -> None:
    """Not zero days: a postponed match can be rescheduled weeks later, and
    seeing that is the point of refreshing."""
    recent = datetime.now(UTC) - timedelta(days=FINISHED_GRACE_DAYS - 5)
    with db.cursor() as cur:
        make_season(cur, 97003, is_current=True, last_kickoff=recent)
    assert 97003 in {s.provider_league_id for s in active_seasons(db)}


def test_a_season_with_no_fixtures_at_all_is_refreshed(
    db: psycopg.Connection,
) -> None:
    """"We have never fetched this one" is the opposite of "this one is over",
    and skipping it would mean never fetching it."""
    with db.cursor() as cur:
        make_season(cur, 97004, is_current=True, last_kickoff=None)
    assert 97004 in {s.provider_league_id for s in active_seasons(db)}


def test_a_season_the_provider_does_not_call_current_is_never_refreshed(
    db: psycopg.Connection,
) -> None:
    with db.cursor() as cur:
        make_season(cur, 97005, is_current=False,
                    last_kickoff=datetime.now(UTC) + timedelta(days=7))
    assert 97005 not in {s.provider_league_id for s in active_seasons(db)}

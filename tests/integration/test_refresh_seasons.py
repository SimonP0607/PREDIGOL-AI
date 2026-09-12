"""refresh_seasons is the only writer of competition_seasons.is_current."""

from __future__ import annotations

import psycopg
import pytest

from fbi.catalog.activation import refresh_seasons
from fbi.providers.base import SeasonRef
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar


def ref(league: int, season: int, current: bool, odds: bool = True) -> SeasonRef:
    return SeasonRef(
        provider_league_id=league,
        season=season,
        is_current=current,
        start_date=f"{season}-08-15",
        end_date=f"{season + 1}-05-24",
        has_odds=odds,
        has_fixtures=True,
    )


def test_a_stale_current_season_is_corrected(db: psycopg.Connection, seed: Seed) -> None:
    """The seeded catalogue says 2025. The provider says 2026 is current. After
    the refresh exactly one season is current, and it is the provider's."""
    updates = refresh_seasons(db, [ref(39, 2025, False), ref(39, 2026, True)], dry_run=False)
    assert len(updates) == 1
    u = updates[0]
    assert u.was_current == 2025 and u.now_current == 2026 and u.has_odds

    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.is_current"
        )
        assert [r[0] for r in cur.fetchall()] == [2026]
        cur.execute(
            "SELECT s.start_date, s.end_date, s.has_odds FROM core.competition_seasons s "
            "JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.season = 2026"
        )
        start, end, has_odds = cur.fetchone()  # type: ignore[misc]
        assert str(start) == "2026-08-15" and str(end) == "2027-05-24" and has_odds is True


def test_exactly_one_season_can_be_current(db: psycopg.Connection, seed: Seed) -> None:
    refresh_seasons(db, [ref(39, 2026, True)], dry_run=False)
    refresh_seasons(db, [ref(39, 2027, True)], dry_run=False)
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.is_current"
        )
        assert scalar(cur) == 1


def test_dry_run_reports_the_change_without_making_it(db: psycopg.Connection, seed: Seed) -> None:
    updates = refresh_seasons(db, [ref(39, 2026, True)], dry_run=True)
    assert updates[0].was_current == 2025 and updates[0].now_current == 2026
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.is_current"
        )
        assert [r[0] for r in cur.fetchall()] == [2025], "dry run must not touch the database"


def test_a_league_with_no_current_season_is_reported_and_nothing_is_written(
    db: psycopg.Connection, seed: Seed
) -> None:
    """What a restricted plan looks like: seasons exist, none is current."""
    updates = refresh_seasons(db, [ref(39, 2021, False), ref(39, 2022, False)], dry_run=False)
    assert updates[0].now_current is None and updates[0].seasons_seen == 2
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.is_current"
        )
        assert [r[0] for r in cur.fetchall()] == [2025], "no current season means no change"


def test_a_league_absent_from_the_catalogue_is_skipped_not_created(
    db: psycopg.Connection, seed: Seed
) -> None:
    assert refresh_seasons(db, [ref(9999, 2026, True)], dry_run=False) == []
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.competitions WHERE provider_league_id = 9999")
        assert scalar(cur) == 0


@pytest.mark.parametrize("dry", [True, False])
def test_no_odds_coverage_is_carried_through_to_the_report(
    db: psycopg.Connection, seed: Seed, dry: bool
) -> None:
    updates = refresh_seasons(db, [ref(39, 2026, True, odds=False)], dry_run=dry)
    assert updates[0].has_odds is False

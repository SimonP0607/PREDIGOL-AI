"""refresh_seasons keeps every season the provider lists, and owns is_current.

It used to keep exactly one row per competition - the current season - and drop
every other season /leagues had named, along with has_fixtures, which was parsed
and never stored. A season we have no row for cannot be planned against, cannot
carry fixtures, and cannot be reported as known-and-not-fetched: it is invisible.
"""

from __future__ import annotations

import psycopg
import pytest

from fbi.catalog.activation import refresh_seasons
from fbi.providers.base import SeasonRef
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar


@pytest.fixture(autouse=True)
def seeded_current_season(db: psycopg.Connection, seed: Seed) -> None:
    """The catalogue-from-a-backup state these tests are about: season 2025 marked
    current, one season behind the provider.

    Stated here rather than assumed. It used to be supplied by accident - another
    module commits is_current = true as a side effect, and this file only passed
    when it happened to run afterwards.
    """
    db.execute("UPDATE core.competition_seasons SET is_current = (season = 2025) "
               "WHERE competition_id = %s", (seed.competition_id,))


def ref(league: int, season: int, current: bool, odds: bool = True,
        fixtures: bool = True) -> SeasonRef:
    return SeasonRef(
        provider_league_id=league,
        season=season,
        is_current=current,
        start_date=f"{season}-08-15",
        end_date=f"{season + 1}-05-24",
        has_odds=odds,
        has_fixtures=fixtures,
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


def test_a_league_with_no_current_season_keeps_its_seasons_and_its_old_current(
    db: psycopg.Connection, seed: Seed
) -> None:
    """What a restricted plan looks like: seasons exist, none is current.

    The seasons are still recorded - they exist at the provider - but nothing is
    promoted to current, because the provider did not say which one is.
    """
    updates = refresh_seasons(db, [ref(39, 2021, False), ref(39, 2022, False)], dry_run=False)
    assert updates[0].now_current is None and updates[0].seasons_seen == 2
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.is_current"
        )
        assert [r[0] for r in cur.fetchall()] == [2025], \
            "no current season at the provider means we do not move ours"
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 ORDER BY s.season"
        )
        assert [r[0] for r in cur.fetchall()] == [2021, 2022, 2025], "and the seasons are kept"


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


# ── every season, not only the current one ──────────────────────────────────


def test_every_season_the_provider_lists_is_recorded(db: psycopg.Connection, seed: Seed) -> None:
    """Eight seasons in, eight rows out. The old behaviour wrote one."""
    refs = [ref(39, y, y == 2026) for y in range(2019, 2027)]
    updates = refresh_seasons(db, refs, dry_run=False)
    assert updates[0].seasons_seen == 8 and updates[0].seasons_written == 8
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season, s.is_current, s.start_date, s.listed_at IS NOT NULL "
            "FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 ORDER BY s.season"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    assert [r[1] for r in rows].count(True) == 1 and rows[-1][1] is True
    assert str(rows[0][2]) == "2019-08-15", "each season keeps its own start, not the current one's"
    assert all(r[3] for r in rows), "and when the provider last named it"


def test_a_season_the_provider_says_has_no_fixtures_is_not_a_gap(
    db: psycopg.Connection, seed: Seed
) -> None:
    """has_fixtures was parsed and discarded. A season that exists with no fixture
    list is nothing to fetch - which is not the same as a season we have missed."""
    updates = refresh_seasons(db, [ref(39, 2019, False, fixtures=False),
                                   ref(39, 2026, True, fixtures=True)], dry_run=False)
    assert updates[0].without_fixtures == 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season, s.has_fixtures FROM core.competition_seasons s "
            "JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.has_fixtures IS NOT NULL ORDER BY s.season"
        )
        assert cur.fetchall() == [(2019, False), (2026, True)]
        cur.execute(
            "SELECT s.has_fixtures FROM core.competition_seasons s "
            "JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 AND s.season = 2025"
        )
        assert cur.fetchone() == (None,), \
            "a row written before this rule does not get a claim it never made"


def test_refreshing_twice_changes_nothing_but_the_timestamp(
    db: psycopg.Connection, seed: Seed
) -> None:
    refs = [ref(39, y, y == 2026) for y in (2024, 2025, 2026)]
    refresh_seasons(db, refs, dry_run=False)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.competition_seasons s "
                    "JOIN core.competitions c ON c.id = s.competition_id WHERE c.provider_league_id = 39")
        before = scalar(cur)
    refresh_seasons(db, refs, dry_run=False)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.competition_seasons s "
                    "JOIN core.competitions c ON c.id = s.competition_id WHERE c.provider_league_id = 39")
        assert scalar(cur) == before


def test_a_season_that_stops_being_listed_is_kept(db: psycopg.Connection, seed: Seed) -> None:
    """The fixtures we hold for it happened. It simply stops being refreshed."""
    refresh_seasons(db, [ref(39, 2019, False), ref(39, 2026, True)], dry_run=False)
    refresh_seasons(db, [ref(39, 2026, True)], dry_run=False)
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.season FROM core.competition_seasons s JOIN core.competitions c ON c.id = s.competition_id "
            "WHERE c.provider_league_id = 39 ORDER BY s.season"
        )
        assert 2019 in [r[0] for r in cur.fetchall()]


def test_the_coverage_column_stays_empty_on_purpose(db: psycopg.Connection, seed: Seed) -> None:
    """The flags live in raw.league_coverage with the payload they came from. A
    second copy here would be two truths that can drift."""
    refresh_seasons(db, [ref(39, 2026, True)], dry_run=False)
    with db.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT s.coverage::text FROM core.competition_seasons s "
            "JOIN core.competitions c ON c.id = s.competition_id WHERE c.provider_league_id = 39"
        )
        assert [r[0] for r in cur.fetchall()] == ["{}"]

"""The catalogue is built from coverage already on disk, for no provider request.

raw.league_coverage holds what one /leagues call returned. Spending a request per
league to re-read it would break the rule against repeating what RAW can answer -
and with 124 selected competitions that is a thousand requests for nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from fbi.catalog.from_raw import build_catalogue, classify
from tests.integration.conftest import Seed

OBSERVED = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)


SEEDED = 39
"""The Premier League the integration seed creates. One test deliberately catalogues
it, to prove an existing competition is updated rather than duplicated - so the
teardown has to put it back exactly as the seed left it."""

SEED_SEASONS = (2021, 2022, 2025)


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    """build_catalogue commits, so nothing here rolls back on its own."""
    with db.cursor() as cur:
        cur.execute("SELECT name, country, type, entity_scope, competition_type, elo_weight, tier, "
                    "is_tracked FROM core.competitions WHERE provider_league_id = %s", (SEEDED,))
        before = cur.fetchone()
    db.commit()
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM raw.league_coverage WHERE provider_league_id BETWEEN 90000 AND 90999")
        cur.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = %s", (SEEDED,))
        cur.execute("DELETE FROM core.competition_seasons s USING core.competitions c "
                    "WHERE s.competition_id = c.id AND c.provider_league_id BETWEEN 90000 AND 90999")
        cur.execute("DELETE FROM core.competitions WHERE provider_league_id BETWEEN 90000 AND 90999")
        if before is not None:
            cur.execute(
                "DELETE FROM core.competition_seasons s USING core.competitions c "
                "WHERE s.competition_id = c.id AND c.provider_league_id = %s "
                "AND NOT (s.season = ANY(%s))", (SEEDED, list(SEED_SEASONS)))
            cur.execute(
                "UPDATE core.competitions SET name=%s, country=%s, type=%s, entity_scope=%s, "
                "competition_type=%s, elo_weight=%s, tier=%s, is_tracked=%s "
                "WHERE provider_league_id = %s", (*before, SEEDED))
    db.commit()


def coverage(db: psycopg.Connection, seed: Seed, league: int, season: int, *, name: str,
             country: str | None, league_type: str, current: bool = False, odds: bool = True,
             detail: bool = True) -> None:
    db.execute(
        "INSERT INTO raw.league_coverage (provider, provider_league_id, season, league_name, country, "
        " league_type, is_current, start_date, end_date, events, lineups, statistics_fixtures, "
        " statistics_players, standings, injuries, odds, payload_hash, observed_at) "
        "VALUES ('api_football',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,true,%s,%s,%s) "
        "ON CONFLICT (provider, provider_league_id, season) DO NOTHING",
        (league, season, name, country, league_type, current, f"{season}-08-01",
         f"{season + 1}-05-31", detail, detail, detail, detail, odds, seed.payload_hash, OBSERVED),
    )


# ── classifying without reading names ───────────────────────────────────────


@pytest.mark.parametrize(
    ("league_type", "country", "expected"),
    [
        ("League", "Spain", ("league", "club", "domestic_league")),
        ("Cup", "Spain", ("cup", "club", "domestic_cup")),
        ("Cup", "World", ("cup", "club", "continental")),
        ("League", "World", ("league", "national_team", "international")),
        (None, "Spain", ("league", "club", "domestic_league")),
    ],
)
def test_a_competition_is_classified_from_the_providers_fields(
    league_type: str | None, country: str, expected: tuple[str, str, str]
) -> None:
    """Never from the name: a competition called "Cup" in one language is a league in
    another, and guessing from strings is how a catalogue drifts."""
    assert classify(league_type, country) == expected


# ── building ────────────────────────────────────────────────────────────────


def test_a_competition_and_all_its_seasons_arrive_from_the_stored_coverage(
    db: psycopg.Connection, seed: Seed
) -> None:
    for season in (2022, 2023, 2024, 2025, 2026):
        coverage(db, seed, 90001, season, name="Test Liga", country="Spain",
                 league_type="League", current=(season == 2026))
    report = build_catalogue(db, tiers={90001: 2})
    assert report.competitions_inserted == 1 and report.seasons_inserted == 5
    with db.cursor() as cur:
        cur.execute("SELECT name, country, type, entity_scope, competition_type, tier, is_tracked, "
                    "       elo_weight FROM core.competitions WHERE provider_league_id = 90001")
        assert cur.fetchone() == ("Test Liga", "Spain", "league", "club", "domestic_league", 2,
                                 True, 1)
        cur.execute("SELECT s.season, s.is_current, s.has_odds, s.listed_at IS NOT NULL, "
                    "       s.start_date IS NOT NULL FROM core.competition_seasons s "
                    "JOIN core.competitions c ON c.id = s.competition_id "
                    "WHERE c.provider_league_id = 90001 ORDER BY s.season")
        rows = cur.fetchall()
    assert [r[0] for r in rows] == [2022, 2023, 2024, 2025, 2026]
    assert [r[1] for r in rows].count(True) == 1 and rows[-1][1] is True
    assert all(r[3] and r[4] for r in rows), "the listing instant and the dates come across"


def test_a_cup_of_the_world_is_continental_and_weighted_lower(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A cup draws sides from different leagues, so its result says less about either."""
    coverage(db, seed, 90002, 2026, name="Test Continental Cup", country="World",
             league_type="Cup", current=True)
    build_catalogue(db, tiers={90002: 2})
    with db.cursor() as cur:
        cur.execute("SELECT competition_type, elo_weight FROM core.competitions "
                    "WHERE provider_league_id = 90002")
        assert cur.fetchone() == ("continental", Decimal("0.90"))


def test_building_twice_changes_nothing(db: psycopg.Connection, seed: Seed) -> None:
    coverage(db, seed, 90003, 2026, name="Idem", country="Italy", league_type="League", current=True)
    first = build_catalogue(db, tiers={90003: 3})
    second = build_catalogue(db, tiers={90003: 3})
    assert (first.competitions_inserted, first.seasons_inserted) == (1, 1)
    assert (second.competitions_inserted, second.seasons_inserted) == (0, 0)
    assert second.competitions_updated == 1 and second.seasons_updated == 1


def test_a_league_the_coverage_does_not_mention_is_reported_not_invented(
    db: psycopg.Connection, seed: Seed
) -> None:
    report = build_catalogue(db, tiers={90999: 2})
    assert report.competitions_inserted == 0
    assert any("absent from raw.league_coverage" in s for s in report.skipped)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.competitions WHERE provider_league_id = 90999")
        assert cur.fetchone() == (0,)


def test_selected_competitions_are_followed_live(db: psycopg.Connection, seed: Seed) -> None:
    """Pre-match odds cannot be backfilled, so a competition worth migrating is worth
    capturing prices for."""
    coverage(db, seed, 90004, 2026, name="Tracked", country="France", league_type="League",
             current=True)
    build_catalogue(db, tiers={90004: 2})
    with db.cursor() as cur:
        cur.execute("SELECT is_tracked FROM core.competitions WHERE provider_league_id = 90004")
        assert cur.fetchone() == (True,)


def test_building_without_tracking_is_possible_and_explicit(
    db: psycopg.Connection, seed: Seed
) -> None:
    coverage(db, seed, 90005, 2026, name="Catalogued only", country="Peru", league_type="League",
             current=True)
    build_catalogue(db, tiers={90005: 4}, tracked=set())
    with db.cursor() as cur:
        cur.execute("SELECT is_tracked FROM core.competitions WHERE provider_league_id = 90005")
        assert cur.fetchone() == (False,)


def test_an_existing_competition_keeps_its_identity_and_gains_the_tier(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The seeded Premier League already exists; cataloguing must fill it in, not
    duplicate it."""
    coverage(db, seed, 39, 2026, name="Premier League", country="England", league_type="League",
             current=True)
    before = build_catalogue(db, tiers={39: 1})
    assert before.competitions_inserted == 0 and before.competitions_updated == 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*), max(tier) FROM core.competitions WHERE provider_league_id = 39")
        assert cur.fetchone() == (1, 1)


# ── tracking is never withdrawn as a side effect ─────────────────────────────


def test_a_tracked_competition_outside_the_selection_keeps_its_tracking(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Running the catalogue for one tier must not stop the odds capture of the others.

    A capture window that closes unobserved is gone for good, so withdrawing tracking
    is an operator's decision, not a consequence of passing a narrower --tiers.
    """
    coverage(db, seed, 90006, 2026, name="Already followed", country="Chile",
             league_type="League", current=True)
    coverage(db, seed, 90007, 2026, name="This run", country="Chile",
             league_type="League", current=True)
    build_catalogue(db, tiers={90006: 2})

    report = build_catalogue(db, tiers={90007: 2})

    with db.cursor() as cur:
        cur.execute("SELECT provider_league_id, is_tracked FROM core.competitions "
                    "WHERE provider_league_id IN (90006, 90007) ORDER BY provider_league_id")
        assert cur.fetchall() == [(90006, True), (90007, True)], \
            "the competition this run did not mention still has its tracking"
    assert any(r.startswith("90006 ") for r in report.tracked_outside_selection), \
        "and it is reported, so an operator can decide about it with the list in hand"


def test_untracking_inside_the_selection_stays_possible(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The explicit case still works: a league named in this run, with tracked= given,
    is set to exactly what was asked for."""
    coverage(db, seed, 90008, 2026, name="Dropped", country="Chile", league_type="League",
             current=True)
    build_catalogue(db, tiers={90008: 2})
    build_catalogue(db, tiers={90008: 2}, tracked=set())
    with db.cursor() as cur:
        cur.execute("SELECT is_tracked FROM core.competitions WHERE provider_league_id = 90008")
        assert cur.fetchone() == (False,)


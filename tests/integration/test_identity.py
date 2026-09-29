"""Identity: our id, and the provider's reference, unique.

/teams?league&season had been fetched 54 times, returning 1,604 teams, and
normalised into nothing - the unit stored raw bytes and wrote zero rows. So
core.venues stayed almost empty, core.players had no writer at all, and a coach
was only a name repeated inside every line-up row.

Matching on names is what these tests forbid: two clubs really are called
"Arsenal", and one club really does change its name.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.ingestion.identity import apply_people, apply_teams, link_lineup_coaches
from fbi.providers.api_football.details import (
    LineupPlayerRef,
    LineupRef,
    PersonRef,
    TeamRef,
    iter_lineup_people,
    iter_teams,
)
from tests.integration.conftest import Seed

FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
LATER = FETCHED + timedelta(days=1)


def teams_body() -> dict:
    """A /teams?league&season response, shaped like the provider's."""
    return {
        "response": [
            {"team": {"id": 33, "name": "Manchester United", "code": "MUN", "country": "England",
                      "founded": 1878, "national": False, "logo": "https://example.invalid/33.png"},
             "venue": {"id": 556, "name": "Old Trafford", "address": "Sir Matt Busby Way",
                       "city": "Manchester", "capacity": 76212, "surface": "grass"}},
            {"team": {"id": 42, "name": "Arsenal", "code": "ARS", "country": "England",
                      "founded": 1886, "national": False, "logo": None},
             "venue": {"id": 494, "name": "Emirates Stadium", "city": "London", "capacity": 60383,
                       "surface": "grass"}},
            {"team": {"id": 99001, "name": "A Team With No Venue", "code": None, "country": "England",
                      "founded": None, "national": False, "logo": None},
             "venue": {"id": None, "name": None, "city": None, "capacity": None}},
            {"team": {"id": None, "name": "No Id, No Identity"}, "venue": {}},
        ],
        "errors": [],
    }


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.team_season_memberships")
        # 33 is the seeded Manchester United, which fixtures reference: this
        # module must not delete it, and updating it is the realistic case anyway.
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (42, 99001, 99002)")
        cur.execute("UPDATE core.teams SET short_name = NULL, country = NULL, founded = NULL, "
                    "venue_id = NULL, logo_url = NULL, source_payload_hash = NULL, "
                    "source_fetched_at = NULL, name = 'Manchester United' WHERE provider_team_id = 33")
        cur.execute("DELETE FROM core.venues WHERE provider_venue_id IN (556, 494)")
        cur.execute("DELETE FROM core.players WHERE provider_player_id BETWEEN 9000 AND 9099")
        cur.execute("DELETE FROM core.coaches WHERE provider_coach_id BETWEEN 700 AND 799")
    db.commit()


# ── /teams stops being raw-only ─────────────────────────────────────────────


def test_a_teams_payload_becomes_teams_and_venues(db: psycopg.Connection, seed: Seed) -> None:
    """Team 33 already exists as a stub the fixtures importer created - a row with
    a name and nothing else. Filling it in is the normal case, not an exception."""
    teams = list(iter_teams(teams_body()))
    assert [t.provider_team_id for t in teams] == [33, 42, 99001], \
        "an entry without an id is not an identity and is skipped"

    report = apply_teams(db, teams, payload_hash=seed.payload_hash, fetched_at=FETCHED,
                         competition_season_id=seed.season_id)
    assert (report.teams_written, report.venues_written, report.memberships_written) == (3, 2, 3)
    with db.cursor() as cur:
        cur.execute("SELECT t.name, t.short_name, t.founded, v.name, v.city, v.capacity, v.surface "
                    "FROM core.teams t LEFT JOIN core.venues v ON v.id = t.venue_id "
                    "WHERE t.provider_team_id = 33")
        assert cur.fetchone() == ("Manchester United", "MUN", 1878, "Old Trafford", "Manchester",
                                  76212, "grass")
        cur.execute("SELECT venue_id FROM core.teams WHERE provider_team_id = 99001")
        assert cur.fetchone() == (None,), "a venue the provider does not identify is not invented"


def test_the_payload_that_wrote_a_team_is_recorded(db: psycopg.Connection, seed: Seed) -> None:
    apply_teams(db, list(iter_teams(teams_body())), payload_hash=seed.payload_hash,
                fetched_at=FETCHED, competition_season_id=seed.season_id)
    with db.cursor() as cur:
        cur.execute("SELECT source_payload_hash, source_fetched_at FROM core.teams "
                    "WHERE provider_team_id = 42")
        assert cur.fetchone() == (seed.payload_hash, FETCHED)
        cur.execute("SELECT source_payload_hash FROM core.venues WHERE provider_venue_id = 494")
        assert cur.fetchone() == (seed.payload_hash,)


def test_identity_is_the_provider_id_never_the_name(db: psycopg.Connection, seed: Seed) -> None:
    """Two rows with the same name and different ids are two teams; the same id
    under a new name is one team that was renamed."""
    first = [TeamRef(provider_team_id=99001, name="Same Name FC", code=None, country="England",
                     founded=None, is_national=False, logo_url=None, venue=None),
             TeamRef(provider_team_id=99002, name="Same Name FC", code=None, country="Wales",
                     founded=None, is_national=False, logo_url=None, venue=None)]
    apply_teams(db, first, payload_hash=seed.payload_hash, fetched_at=FETCHED)
    renamed = [TeamRef(provider_team_id=99001, name="Renamed FC", code=None, country="England",
                       founded=None, is_national=False, logo_url=None, venue=None)]
    apply_teams(db, renamed, payload_hash=seed.payload_hash, fetched_at=LATER)
    with db.cursor() as cur:
        cur.execute("SELECT provider_team_id, name FROM core.teams "
                    "WHERE provider_team_id IN (99001, 99002) ORDER BY provider_team_id")
        assert cur.fetchall() == [(99001, "Renamed FC"), (99002, "Same Name FC")]


def test_an_older_payload_never_overwrites_a_newer_one(db: psycopg.Connection, seed: Seed) -> None:
    new = [TeamRef(provider_team_id=99001, name="Current Name", code=None, country=None,
                   founded=None, is_national=False, logo_url=None, venue=None)]
    old = [TeamRef(provider_team_id=99001, name="Stale Name", code=None, country=None,
                   founded=None, is_national=False, logo_url=None, venue=None)]
    apply_teams(db, new, payload_hash=seed.payload_hash, fetched_at=LATER)
    report = apply_teams(db, old, payload_hash=seed.payload_hash, fetched_at=FETCHED)
    assert report.teams_written == 0
    with db.cursor() as cur:
        cur.execute("SELECT name FROM core.teams WHERE provider_team_id = 99001")
        assert cur.fetchone() == ("Current Name",)


def test_membership_is_only_recorded_for_a_season_we_know(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A membership attached to no season we hold is a row with no meaning."""
    report = apply_teams(db, list(iter_teams(teams_body())), payload_hash=seed.payload_hash,
                         fetched_at=FETCHED, competition_season_id=None)
    assert report.memberships_written == 0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.team_season_memberships")
        assert cur.fetchone() == (0,)


def test_applying_the_same_payload_twice_writes_the_same_rows(
    db: psycopg.Connection, seed: Seed
) -> None:
    teams = list(iter_teams(teams_body()))
    first = apply_teams(db, teams, payload_hash=seed.payload_hash, fetched_at=FETCHED,
                        competition_season_id=seed.season_id)
    second = apply_teams(db, teams, payload_hash=seed.payload_hash, fetched_at=FETCHED,
                         competition_season_id=seed.season_id)
    assert first.rows == second.rows, "an equal instant still applies: the same values, rewritten"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.teams WHERE provider_team_id IN (33, 42, 99001)")
        assert cur.fetchone() == (3,)


# ── players and coaches come free with the detail ───────────────────────────


def _lineup(coach_id: int | None = 700, coach: str | None = "A Coach") -> LineupRef:
    return LineupRef(
        provider_fixture_id=1, provider_team_id=33, formation="4-3-3",
        provider_coach_id=coach_id, coach_name=coach,
        players=tuple(LineupPlayerRef(provider_player_id=9000 + n, name=f"Player {n}", number=n + 1,
                                      position="M", grid=None, is_starter=n < 11)
                      for n in range(14)),
    )


def test_a_lineup_names_its_players_and_its_coach(db: psycopg.Connection, seed: Seed) -> None:
    from fbi.providers.api_football.details import FixtureDetail
    detail = FixtureDetail(provider_fixture_id=1, stats=(), events=(), lineups=(_lineup(),),
                           players=(), blocks_present=frozenset({"lineups"}))
    players, coaches = iter_lineup_people(detail)
    assert len(players) == 14 and len(coaches) == 1

    report = apply_people(db, players, coaches, payload_hash=seed.payload_hash, fetched_at=FETCHED)
    assert (report.players_written, report.coaches_written) == (14, 1)
    with db.cursor() as cur:
        cur.execute("SELECT name, position, source_payload_hash FROM core.players "
                    "WHERE provider_player_id = 9000")
        assert cur.fetchone() == ("Player 0", "M", seed.payload_hash)
        cur.execute("SELECT name FROM core.coaches WHERE provider_coach_id = 700")
        assert cur.fetchone() == ("A Coach",)


def test_a_player_named_twice_in_one_payload_is_one_identity(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The line-up and the statistics block both name the same people."""
    from fbi.providers.api_football.details import FixtureDetail, PlayerStatsRef
    detail = FixtureDetail(
        provider_fixture_id=1, stats=(), events=(), lineups=(_lineup(),),
        players=(PlayerStatsRef(provider_fixture_id=1, provider_team_id=33, provider_player_id=9000,
                                name="Player 0", values={}),),
        blocks_present=frozenset({"lineups", "players"}),
    )
    players, _coaches = iter_lineup_people(detail)
    assert len([p for p in players if p.provider_id == 9000]) == 1


def test_a_richer_field_is_not_wiped_by_a_payload_that_lacks_it(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A line-up gives an id and a name. It must not blank the position or the
    birth date that /players filled in."""
    apply_people(db, [PersonRef(9000, "Player 0", "Goalkeeper")], [], payload_hash=seed.payload_hash,
                 fetched_at=FETCHED)
    db.execute("UPDATE core.players SET birth_date = '1998-04-02', nationality = 'England' "
               "WHERE provider_player_id = 9000")
    apply_people(db, [PersonRef(9000, "Player 0", None)], [], payload_hash=seed.payload_hash,
                 fetched_at=LATER)
    with db.cursor() as cur:
        cur.execute("SELECT position, birth_date, nationality FROM core.players "
                    "WHERE provider_player_id = 9000")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "Goalkeeper", "the position survives a payload that does not carry one"
    assert (str(row[1]), row[2]) == ("1998-04-02", "England")


def test_a_person_without_a_name_is_not_stored(db: psycopg.Connection, seed: Seed) -> None:
    report = apply_people(db, [PersonRef(9050, "")], [PersonRef(750, "")],
                          payload_hash=seed.payload_hash, fetched_at=FETCHED)
    assert (report.players_written, report.coaches_written, report.skipped_no_name) == (0, 0, 2)


def test_a_lineup_points_at_the_coach_identity_and_keeps_the_name(
    db: psycopg.Connection, seed: Seed
) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, "
            "provider_coach_id, coach_name, payload_hash, fetched_at) "
            "VALUES (%s,'home','api-football','4-3-3',700,'A Coach',%s,%s)",
            (seed.fixture_id, seed.payload_hash, FETCHED),
        )
    apply_people(db, [], [PersonRef(700, "A Coach")], payload_hash=seed.payload_hash,
                 fetched_at=FETCHED)
    assert link_lineup_coaches(db, seed.fixture_id) == 1
    with db.cursor() as cur:
        cur.execute("SELECT l.coach_name, c.name, c.provider_coach_id FROM core.fixture_lineups l "
                    "JOIN core.coaches c ON c.id = l.coach_id WHERE l.fixture_id = %s",
                    (seed.fixture_id,))
        assert cur.fetchone() == ("A Coach", "A Coach", 700)
    assert link_lineup_coaches(db, seed.fixture_id) == 0, "already linked: nothing to do"

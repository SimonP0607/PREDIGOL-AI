"""A competition is club or national-team football by evidence, not by two fields.

classify() reads league_type and country. Both the UEFA Champions League and the World
Cup are Cup/World, so a rule on those two fields called the World Cup club football - and
did, for about twenty national-team competitions, with a Champions-League rating weight.
The provider publishes the missing fact on the team (/teams returns national: true), so
this resolves from the teams that actually played and records an issue where none are
known instead of picking the plausible value.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from fbi.catalog.scopes import FRIENDLY_LEAGUES, resolve_scopes
from tests.integration.conftest import Seed

KICKOFF = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
LEAGUES = (91001, 91002, 91003, 91004, 91005, 91006)


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues WHERE provider_entity_id = ANY(%s)",
                    (list(LEAGUES) + sorted(FRIENDLY_LEAGUES),))
        cur.execute("DELETE FROM core.fixtures f USING core.competition_seasons s, core.competitions c "
                    "WHERE f.competition_season_id = s.id AND s.competition_id = c.id "
                    "AND c.provider_league_id = ANY(%s)", (list(LEAGUES) + sorted(FRIENDLY_LEAGUES),))
        cur.execute("DELETE FROM core.team_season_memberships m USING core.competition_seasons s, "
                    "core.competitions c WHERE m.competition_season_id = s.id "
                    "AND s.competition_id = c.id AND c.provider_league_id = ANY(%s)",
                    (list(LEAGUES) + sorted(FRIENDLY_LEAGUES),))
        cur.execute("DELETE FROM core.competition_seasons s USING core.competitions c "
                    "WHERE s.competition_id = c.id AND c.provider_league_id = ANY(%s)",
                    (list(LEAGUES) + sorted(FRIENDLY_LEAGUES),))
        cur.execute("DELETE FROM core.competitions WHERE provider_league_id = ANY(%s)",
                    (list(LEAGUES) + sorted(FRIENDLY_LEAGUES),))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id BETWEEN 910000 AND 919999")
    db.commit()


def team(db: psycopg.Connection, provider_id: int, *, national: bool) -> int:
    row = db.execute(
        "INSERT INTO core.teams (provider_team_id, name, country, is_national) "
        "VALUES (%s, %s, 'Nowhere', %s) ON CONFLICT (provider_team_id) DO UPDATE "
        "SET is_national = EXCLUDED.is_national RETURNING id",
        (provider_id, f"Team {provider_id}", national),
    ).fetchone()
    assert row is not None
    return int(row[0])


def competition(db: psycopg.Connection, league: int, *, country: str, kind: str = "cup",
                comp_type: str = "continental", elo: str = "0.90") -> int:
    row = db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
        " competition_type, elo_weight, tier, is_tracked) "
        "VALUES (%s,%s,%s,%s,'club',%s,%s,2,true) RETURNING id",
        (league, f"Competition {league}", country, kind, comp_type, elo),
    ).fetchone()
    assert row is not None
    return int(row[0])


def season_with(db: psycopg.Connection, competition_id: int, pairs: list[tuple[int, int]]) -> None:
    row = db.execute(
        "INSERT INTO core.competition_seasons (competition_id, season, is_current) "
        "VALUES (%s, 2026, true) RETURNING id", (competition_id,)).fetchone()
    assert row is not None
    season_id = int(row[0])
    for n, (home, away) in enumerate(pairs):
        db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
            " away_team_id, kickoff_at, status_short, status_group) "
            "VALUES (%s,%s,%s,%s,%s,'NS','scheduled')",
            (9_100_000 + competition_id * 100 + n, season_id, home, away,
             KICKOFF + timedelta(days=n)),
        )


def scope_of(db: psycopg.Connection, league: int) -> tuple[str, str, Decimal]:
    row = db.execute("SELECT entity_scope, competition_type, elo_weight FROM core.competitions "
                     "WHERE provider_league_id = %s", (league,)).fetchone()
    assert row is not None
    return (row[0], row[1], row[2])


def test_a_world_competition_of_national_teams_stops_being_club_football(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The World Cup: Cup + country World, exactly like the Champions League, and only the
    teams tell them apart."""
    spain, italy, brazil, japan = (team(db, 910001 + i, national=True) for i in range(4))
    comp = competition(db, 91001, country="World")
    season_with(db, comp, [(spain, italy), (brazil, japan)])

    report = resolve_scopes(db)

    assert scope_of(db, 91001) == ("national_team", "international", Decimal("0.70"))
    assert any("91001" in entry for entry in report.resolved_national)


def test_a_world_competition_of_clubs_stays_continental(
    db: psycopg.Connection, seed: Seed
) -> None:
    clubs = [team(db, 910101 + i, national=False) for i in range(4)]
    comp = competition(db, 91006, country="World")
    season_with(db, comp, [(clubs[0], clubs[1]), (clubs[2], clubs[3])])

    resolve_scopes(db)

    assert scope_of(db, 91006) == ("club", "continental", Decimal("0.90"))


def test_season_membership_counts_as_evidence_without_any_fixture(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A competition out of season has no fixture in the sync horizon, and 34 of the
    tracked 124 were in exactly that state. /teams still said who is in it, so the
    membership rows are the evidence of record and fixtures are the fallback."""
    nationals = [team(db, 910601 + i, national=True) for i in range(4)]
    comp = competition(db, 91002, country="World")
    row = db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                     "VALUES (%s, 2026, true) RETURNING id", (comp,)).fetchone()
    assert row is not None
    for t in nationals:
        db.execute("INSERT INTO core.team_season_memberships (team_id, competition_season_id) "
                   "VALUES (%s, %s)", (t, int(row[0])))

    resolve_scopes(db)

    assert scope_of(db, 91002) == ("national_team", "international", Decimal("0.70"))


def test_a_competition_with_no_team_on_record_is_reported_not_guessed(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Nothing to appeal to, so nothing is changed - and it is visible in the registry."""
    comp = competition(db, 91003, country="World")
    db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
               "VALUES (%s, 2026, true)", (comp,))

    report = resolve_scopes(db)

    assert scope_of(db, 91003) == ("club", "continental", Decimal("0.90")), "left exactly as it was"
    assert any("91003" in entry for entry in report.no_evidence)
    row = db.execute(
        "SELECT code, severity FROM audit.data_quality_issues WHERE provider_entity_id = 91003"
    ).fetchone()
    assert row is not None and row[0] == "UNKNOWN_PROVIDER_ENTITY"


def test_a_mixed_field_is_recorded_as_a_contradiction_and_left_alone(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Half national, half clubs is not something this rule can classify, and picking one
    would be the guess the module exists to remove."""
    a, b = team(db, 910201, national=True), team(db, 910202, national=True)
    c, d = team(db, 910203, national=False), team(db, 910204, national=False)
    comp = competition(db, 91004, country="World")
    season_with(db, comp, [(a, c), (b, d)])

    report = resolve_scopes(db)

    assert scope_of(db, 91004) == ("club", "continental", Decimal("0.90"))
    assert any("91004" in entry for entry in report.contradictory)
    row = db.execute("SELECT code FROM audit.data_quality_issues "
                     "WHERE provider_entity_id = 91004").fetchone()
    assert row is not None and row[0] == "PROVIDER_INCONSISTENCY"


def test_one_unflagged_team_does_not_reclassify_a_national_competition(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A qualifying group can hold a provider record that is not flagged. Nine of ten is
    still national-team football."""
    nationals = [team(db, 910301 + i, national=True) for i in range(9)]
    odd = team(db, 910399, national=False)
    comp = competition(db, 91005, country="World")
    season_with(db, comp, [(nationals[i], nationals[i + 1]) for i in range(0, 8, 2)]
                + [(nationals[8], odd)])

    resolve_scopes(db)

    assert scope_of(db, 91005)[0] == "national_team"


def test_a_friendly_is_weighted_zero_whoever_plays_it(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A friendly result must not move a rating, and the provider flags friendlies only by
    name - so the ids are pinned and the weight is not up for inference."""
    league = min(FRIENDLY_LEAGUES)
    a, b = team(db, 910401, national=True), team(db, 910402, national=True)
    comp = competition(db, league, country="World")
    season_with(db, comp, [(a, b)])

    report = resolve_scopes(db)

    scope, comp_type, elo = scope_of(db, league)
    assert elo == Decimal("0.00"), "a friendly moves no rating"
    assert scope == "national_team", "the scope still comes from the teams that played"
    assert comp_type == "international"
    assert any(str(league) in entry for entry in report.friendlies_weighted_zero)


def test_reporting_without_applying_changes_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    nationals = [team(db, 910501 + i, national=True) for i in range(2)]
    comp = competition(db, 91001, country="World")
    season_with(db, comp, [(nationals[0], nationals[1])])

    report = resolve_scopes(db, apply=False)

    assert any("91001" in entry for entry in report.resolved_national)
    assert scope_of(db, 91001) == ("club", "continental", Decimal("0.90"))

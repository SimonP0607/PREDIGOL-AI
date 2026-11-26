"""RP-4.3 on a real database: the schedule facts of the matches about to kick off come from the team's calendar as known at the moment (a match played
before it, never a fixture recorded after it), are stored as complete context facts only when the caller says so, say that the calendar was never read when no
fetch is logged, and a team with no previous match has none. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import calendar_facts as cf

from .conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 26, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(days=2)


def third_team(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (9999, 'Tercero') ON CONFLICT (provider_team_id) DO UPDATE SET name = 'Tercero' "
                     "RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def played(db: psycopg.Connection[Any], seed: Seed, *, pfid: int, days_before: float, status: str = "finished", created: datetime | None = None) -> None:
    """A match of the HOME team against a third team (so the away side has none), ``days_before`` the match under study."""
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_short, status_group, "
               "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
               (pfid, seed.season_id, seed.home_team_id, third_team(db), KICKOFF - timedelta(days=days_before), "FT" if status == "finished" else "NS", status,
                created or KICKOFF - timedelta(days=days_before + 7)))


def start(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (KICKOFF, seed.fixture_id))


def facts(db: psycopg.Connection[Any], seed: Seed) -> list[tuple[Any, ...]]:
    return db.execute("SELECT kind, claim_type, origin, side, fact_schema, subject_id, fresh_until, claim FROM ai.evidence WHERE fixture_id = %s "
                      "AND kind = 'schedule' ORDER BY side", (seed.fixture_id,)).fetchall()


def test_only_the_side_with_a_previous_match_has_a_fact_and_it_says_the_calendar_was_never_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    start(db, seed)
    played(db, seed, pfid=9001, days_before=3.0)
    played(db, seed, pfid=9002, days_before=8.0)
    counts = cf.run(db, at=AT, write=True)
    assert (counts.facts, counts.created, counts.no_previous, counts.not_whole, counts.whole) == (1, 1, 1, 1, 0) and counts.errors == []
    (row,) = facts(db, seed)
    assert row[:7] == ("schedule", "SCHEDULE", "own_calc", "home", "context-fact-v1", seed.home_team_id, KICKOFF)
    assert "a lo sumo 3,0 días desde su último partido" in row[7] and "al menos 2 partidos en los 14 días anteriores" in row[7]
    assert "Calendario incompleto: el calendario del equipo nunca se leyó." in row[7]


def test_switched_off_it_reads_and_counts_but_writes_nothing_and_a_second_run_does_not_duplicate(db: psycopg.Connection[Any], seed: Seed) -> None:
    start(db, seed)
    played(db, seed, pfid=9001, days_before=3.0)
    assert cf.run(db, at=AT, write=False).facts == 1 and facts(db, seed) == []
    assert cf.run(db, at=AT, write=True).created == 1
    assert cf.run(db, at=AT, write=True).created == 0 and len(facts(db, seed)) == 1


def test_a_fixture_recorded_after_the_moment_is_not_known_yet(db: psycopg.Connection[Any], seed: Seed) -> None:
    start(db, seed)
    played(db, seed, pfid=9001, days_before=3.0)
    played(db, seed, pfid=9003, days_before=-2.0, status="scheduled", created=AT + timedelta(hours=1))  # an announcement made after the moment
    cf.run(db, at=AT, write=True)
    (row,) = facts(db, seed)
    assert "siguiente partido" not in row[7]
    later = cf.collect(db, at=AT + timedelta(hours=2))
    assert "siguiente partido" in later[0].facts[0].claim


def test_a_match_beyond_the_horizon_gets_none(db: psycopg.Connection[Any], seed: Seed) -> None:
    played(db, seed, pfid=9001, days_before=3.0)
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (AT + cf.AHEAD + timedelta(days=1), seed.fixture_id))
    assert cf.run(db, at=AT, write=True).facts == 0


def test_the_report_counts_sides_with_and_without_a_fact(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_calendar_facts as cli

    start(db, seed)
    played(db, seed, pfid=9001, days_before=3.0)
    doc = cli.report(cf.collect(db, at=AT), sheet=3)
    assert (doc["matches"], doc["sides"], doc["with_fact"], doc["without_fact"], doc["whole_calendar"], doc["not_whole"], doc["coverage"]) == (1, 2, 1, 1, 0, 1, 0.5)
    text = "\n".join(cli.lines(doc))
    assert "1 de 2 lados con hecho (50.0 %)" in text and "a lo sumo 3,0 días" in text

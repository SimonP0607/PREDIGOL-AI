"""RP-4.3, second tranche, on a real database: the minutes of the usual starters and the probable rotation come from the line-ups and statistics of the
matches the team FINISHED before the moment asked (a match not finished, or one that kicks off after the moment, is not read), are written as complete context facts of
their own story only when the caller says so (the rotation carrying ``certainty = probable``), a side without three full line-ups has none, and the category
the schema derives for the stored rotation is ``informacion_probable``. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import calendar_facts as cf
from fbi.ai import factor_counts, factor_schema, value_sheet_readers

from .conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 26, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(days=2)
XI = list(range(1, 12))


def third_team(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (9999, 'Tercero') ON CONFLICT (provider_team_id) DO UPDATE SET name = 'Tercero' "
                     "RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def played(db: psycopg.Connection[Any], seed: Seed, *, pfid: int, days_before: float, starters: list[int], minutes: int | None = 90,
           status: str = "finished") -> int:
    """A match of the HOME team against a third team with a line-up of ``starters`` (plus two substitutes) and, when ``minutes`` is given, statistics."""
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_short, status_group) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                     (pfid, seed.season_id, seed.home_team_id, third_team(db), KICKOFF - timedelta(days=days_before), "FT" if status == "finished" else "NS",
                      status)).fetchone()
    assert row is not None
    fid = int(row[0])
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) VALUES (%s, 'home', 'api-football', %s, %s)",
               (fid, seed.payload_hash, KICKOFF - timedelta(days=days_before)))
    for p in [*starters, 900, 901]:
        db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) VALUES (%s, 'home', 'api-football', %s, %s)",
                   (fid, p, p in starters))
        if minutes is not None:
            db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, is_substitute, payload_hash, fetched_at) "
                       "VALUES (%s, 'api-football', %s, 'home', %s, %s, %s, %s)",
                       (fid, p, minutes if p in starters else 0, p not in starters, seed.payload_hash, KICKOFF - timedelta(days=days_before)))
    return fid


def start(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (KICKOFF, seed.fixture_id))


def stored(db: psycopg.Connection[Any], seed: Seed, kind: str) -> list[tuple[Any, ...]]:
    return db.execute("SELECT kind, claim_type, origin, side, fact_schema, subject_id, fresh_until, attributes ->> 'certainty', claim FROM ai.evidence "
                      "WHERE fixture_id = %s AND kind = %s AND story_key LIKE %s ORDER BY side",
                      (seed.fixture_id, kind, ("minutes" if kind == "schedule" else "rotation") + ":%")).fetchall()


def season(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Three full line-ups in the fortnight (two of them 3 days apart), and old pairs that show the team repeats 10 starters with more rest and 6 with less."""
    start(db, seed)
    rows = [(9001, 3.0, XI), (9002, 6.0, [*XI[:6], *range(20, 25)]), (9003, 10.0, XI)]
    for pfid, days, starters in rows:
        played(db, seed, pfid=pfid, days_before=days, starters=starters)


def test_the_minutes_of_the_usual_starters_are_written_complete_and_only_when_asked(db: psycopg.Connection[Any], seed: Seed) -> None:
    season(db, seed)
    assert cf.run(db, at=AT, write=False).minutes == 1 and stored(db, seed, "schedule") == []
    counts = cf.run(db, at=AT, write=True)
    assert counts.minutes == 1 and counts.rotation == 0 and counts.errors == []
    (row,) = stored(db, seed, "schedule")
    assert row[:8] == ("schedule", "SCHEDULE", "own_calc", "home", "context-fact-v1", seed.home_team_id, KICKOFF, None)
    assert "sus 6 titulares habituales" in row[8] or "sus 11 titulares habituales" in row[8]
    assert "3 partidos con estadísticas" in row[8]
    assert cf.run(db, at=AT, write=True).created == 0, "the same fact is stored once"


def test_a_match_not_finished_or_after_the_moment_is_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    season(db, seed)
    played(db, seed, pfid=9004, days_before=1.0, starters=XI, status="scheduled")
    later = played(db, seed, pfid=9005, days_before=-1.0, starters=XI)
    assert later > 0, "a match that kicks off after the one under study, already in the table, is never part of its history"
    read = next(r for r in cf.collect(db, at=AT) if r.match.fixture_id == seed.fixture_id)
    minutes = [f for f in read.facts if f.story == "minutes"]
    assert len(minutes) == 1 and minutes[0].calculation["matches_in_14d"] == 3


def test_fewer_than_three_full_lineups_leave_the_side_without_minutes_and_a_match_without_statistics_does_not_count(db: psycopg.Connection[Any], seed: Seed) -> None:
    start(db, seed)
    played(db, seed, pfid=9001, days_before=3.0, starters=XI)
    played(db, seed, pfid=9002, days_before=6.0, starters=XI)
    assert cf.run(db, at=AT, write=False).minutes == 0
    played(db, seed, pfid=9003, days_before=9.0, starters=XI, minutes=None)
    (read,) = cf.collect(db, at=AT)
    (fact,) = [f for f in read.facts if f.story == "minutes"]
    assert fact.calculation["matches_in_14d"] == 2, "the third match has a line-up but no statistics"


def test_the_probable_rotation_is_stored_as_informacion_probable_with_its_calculation(db: psycopg.Connection[Any], seed: Seed) -> None:
    start(db, seed)
    # alternating pattern: after 3 days the XI changes by five players, after 7 days by one
    state = list(XI)
    day, pfid, fresh = 150.0, 9100, 100
    played(db, seed, pfid=pfid, days_before=day, starters=state)
    for gap, changes in [(3, 5), (3, 5), (3, 5), (7, 1), (7, 1), (7, 1)]:
        pfid += 1
        day -= gap
        state = [*state[: 11 - changes], *range(fresh, fresh + changes)]
        fresh += 20
        played(db, seed, pfid=pfid, days_before=day, starters=state)
    # the last match was played 3 days before the one under study
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE provider_fixture_id = %s", (KICKOFF - timedelta(days=3), pfid))
    counts = cf.run(db, at=AT, write=True)
    assert counts.rotation == 1 and counts.errors == []
    (row,) = stored(db, seed, "rotation")
    assert row[:8] == ("rotation", "OTHER", "own_calc", "home", "context-fact-v1", seed.home_team_id, KICKOFF, "probable")
    assert "rotación probable" in row[8] and "no una alineación anunciada" in row[8]
    doc = factor_counts.report(value_sheet_readers.fact_rows(db, since=AT - timedelta(days=1), until=AT + timedelta(days=1), typed=True))
    assert doc["new"]["by_category"].get("informacion_probable") == 1 and doc["new"]["by_kind"].get("rotation") == 1
    assert factor_schema.category_of("PROBABLE", "own_calc") == "hecho_confirmado"

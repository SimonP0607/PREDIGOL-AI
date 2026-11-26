"""RP-4.4 (first tranche) on a real database: the coach, the usual formation and the referee of the matches about to kick off are read from the sheets and the
provider's facts as of a moment and stored as complete context facts only when the switch is on (or the caller says so). A team with no sheets, a match with
nobody named and a switch off write nothing. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import factor_schema
from fbi.ai import people_facts as pf

from .conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 26, 12, tzinfo=UTC)
KICKOFF = AT + timedelta(days=1)
COACH_ID = 99701


def kick_off_soon(db: psycopg.Connection[Any], seed: Seed, *, at: datetime = KICKOFF) -> None:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (at, seed.fixture_id))


def played(db: psycopg.Connection[Any], seed: Seed, *, home: bool, weeks_ago: int, n: int, formation: str | None, coach: int | None = COACH_ID) -> None:
    """One finished match of the seed's home team (or its away team) with its sheet."""
    team, rival = (seed.home_team_id, seed.away_team_id) if home else (seed.away_team_id, seed.home_team_id)
    host, guest = (team, rival) if home else (rival, team)
    kickoff = AT - timedelta(weeks=weeks_ago)
    fid = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_short, status_group) "
                     "VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                     (9970000 + n + (0 if home else 500), seed.season_id, host, guest, kickoff)).fetchone()
    assert fid is not None
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, provider_coach_id, coach_name, payload_hash, fetched_at) "
               "VALUES (%s, %s, 'api-football', %s, %s, 'M. Entrenador', %s, %s)",
               (fid[0], "home" if home else "away", formation, coach, seed.payload_hash, kickoff + timedelta(hours=3)))


def history(db: psycopg.Connection[Any], seed: Seed, *, formations: tuple[str | None, ...] = ("4-3-3", "4-3-3", "4-2-3-1", "4-3-3", "4-3-3")) -> None:
    for i, f in enumerate(formations):
        played(db, seed, home=True, weeks_ago=i + 1, n=i, formation=f)


def named_referee(db: psycopg.Connection[Any], seed: Seed, *, at: datetime = AT - timedelta(hours=2)) -> None:
    db.execute("INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, payload_hash, normalizer_version) VALUES (%s, %s, 'R. Tester', %s, 'v1')",
               (seed.fixture_id, at, seed.payload_hash))


def facts(db: psycopg.Connection[Any], seed: Seed) -> list[tuple[Any, ...]]:
    return db.execute("SELECT kind, side, subject_type, subject_id, fact_schema, fresh_until, claim FROM ai.evidence WHERE fixture_id = %s "
                      "AND kind IN ('coach', 'formation', 'referee') AND origin = 'own_calc' ORDER BY kind, side", (seed.fixture_id,)).fetchall()


def test_the_switch_off_reads_and_counts_but_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    history(db, seed)
    named_referee(db, seed)
    counts = pf.run(db, at=AT, write=False)
    assert counts.facts == 3 and counts.created == 0 and counts.no_coach == 1 and counts.no_formation == 1 and counts.no_referee == 0
    assert facts(db, seed) == []


def test_the_facts_are_stored_complete_and_valid_until_kickoff_and_say_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    history(db, seed)
    named_referee(db, seed)
    counts = pf.run(db, at=AT, write=True)
    assert counts.created == 3 and counts.errors == []
    rows = facts(db, seed)
    assert [(r[0], r[1], r[2]) for r in rows] == [("coach", "home", "TEAM"), ("formation", "home", "TEAM"), ("referee", "match", "MATCH")]
    assert rows[0][3] == seed.home_team_id and rows[2][3] == seed.fixture_id
    assert all(r[4] == factor_schema.VERSION and r[5] == KICKOFF for r in rows)
    assert "en el banquillo M. Entrenador desde el partido del" in rows[0][6] and "5 planillas seguidas" in rows[0][6]
    assert "formación más usada 4-3-3, en 4 de sus últimas 5 planillas con formación" in rows[1][6]
    assert "Árbitro de" in rows[2][6] and "R. Tester" in rows[2][6]
    assert pf.run(db, at=AT, write=True).created == 0, "the same sheets say the same thing once"
    assert len(facts(db, seed)) == 3


def test_a_team_with_no_sheets_and_a_match_with_nobody_named_have_no_facts_and_are_counted(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    counts = pf.run(db, at=AT, write=True)
    assert (counts.facts, counts.created, counts.no_coach, counts.no_formation, counts.no_referee) == (0, 0, 2, 2, 1)
    assert facts(db, seed) == []


def test_a_referee_named_after_the_moment_asked_does_not_exist_yet(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    named_referee(db, seed, at=AT + timedelta(hours=1))
    assert pf.run(db, at=AT, write=False).no_referee == 1
    assert pf.run(db, at=AT + timedelta(hours=2), write=False, ahead=timedelta(days=2)).no_referee == 0


def test_the_sheets_of_the_away_side_count_for_the_away_team(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    for i, f in enumerate(("4-4-2", "4-4-2", "4-4-2", "3-5-2", "4-4-2")):
        played(db, seed, home=False, weeks_ago=i + 1, n=i, formation=f)
    reads = pf.collect(db, at=AT)
    mine = next(r for r in reads if r.match.fixture_id == seed.fixture_id)
    away = [f for f in mine.facts if f.kind == "formation"]
    assert [f.side for f in away] == ["away"] and away[0].calculation["usual"] == "4-4-2" and away[0].team == seed.away_team_id


def test_a_match_that_kicks_off_later_than_the_horizon_or_already_played_gets_none(db: psycopg.Connection[Any], seed: Seed) -> None:
    history(db, seed)
    named_referee(db, seed)
    kick_off_soon(db, seed, at=AT + pf.AHEAD + timedelta(hours=1))
    assert pf.run(db, at=AT, write=True).matches == 0
    kick_off_soon(db, seed, at=AT - timedelta(hours=3))
    assert pf.run(db, at=AT, write=True).matches == 0


def test_only_the_sheets_before_the_match_and_before_the_moment_count(db: psycopg.Connection[Any], seed: Seed) -> None:
    history(db, seed, formations=("4-3-3", "4-3-3", "4-3-3", "4-3-3"))
    earlier = AT - timedelta(days=15)
    kick_off_soon(db, seed, at=earlier + timedelta(days=1))
    then = next(r for r in pf.collect(db, at=earlier) if r.match.fixture_id == seed.fixture_id)
    assert "formation:home" in then.missing, "asked 15 days earlier only two of the four sheets existed: too few for a habit"
    kick_off_soon(db, seed)
    now = next(r for r in pf.collect(db, at=AT) if r.match.fixture_id == seed.fixture_id)
    assert "formation:home" not in now.missing and any(f.kind == "formation" for f in now.facts)


def test_the_report_gives_the_coverage_of_each_slot_and_lists_the_sheet(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_people_facts as cli

    kick_off_soon(db, seed)
    history(db, seed)
    named_referee(db, seed)
    doc = cli.report(pf.collect(db, at=AT), sheet=5)
    assert doc["with_facts"] == 1 and doc["facts"] == 3
    assert doc["coverage"]["coach:home"] == {"with": 1, "of": 1, "share": 1.0} and doc["coverage"]["coach:away"]["with"] == 0
    assert doc["coverage"]["referee"]["with"] == 1 and doc["sheet"][0]["missing"] == ["coach:away", "formation:away"]
    text = "\n".join(cli.lines(doc))
    assert "árbitro nombrado: 1 de 1 (100 %)" in text and "entrenador visitante: 0 de 1 (0 %)" in text

"""RP-4.2 on a real database: the facts of the matches about to kick off are read from the newest scenarios reading of their season, as of a moment, and are
stored as complete context facts only when the switch is on (or the caller says so); a stale reading, a regulation not coded and a switch off write nothing. The
transaction is rolled back afterwards."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import factor_schema
from fbi.competitions import stakes_facts as sf

from .conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 26, 12, tzinfo=UTC)


def put(db: psycopg.Connection[Any], seed: Seed, *, computed: datetime, status: str = "ok", home: str = "conseguido", away: str = "descartado") -> None:
    def row(team: int, state: str) -> dict[str, Any]:
        return {"team": team, "puesto": 1 if state == "conseguido" else 2, "puntos": 60, "partidos_restantes": 2, "puntos_minimos": 60, "puntos_maximos": 66,
                "objetivos": [{"objetivo": "titulo", "zona": "champion", "sentido": "lograr", "puestos": [1, 1], "terminar_entre_los": 1, "condicional": False,
                               "estado": state, "decidido": {"valor": True, "demostrado": True, "motivos": []}}]}
    reading = {"version": "scenarios-v2", "at": computed.isoformat(), "league_id": 39, "season": 2025, "status": status, "input_hash": "a" * 64,
               "rules": {"sha256": "b" * 64},
               "tables": [{"key": "season.league", "teams": [row(seed.home_team_id, home), row(seed.away_team_id, away)], "matches": {}}],
               "teams": {}}
    digest = hashlib.sha256(f"{computed.isoformat()}{status}{home}{away}".encode()).hexdigest()
    ok = status == "ok"
    db.execute("INSERT INTO intel.scenario_readings (computed_at, league_id, season, competition_season_id, status, engine_version, rules_version, "
               "rules_sha256, sims, seed, input_hash, contradictions, reading) VALUES (%s, 39, 2025, %s, %s, 'scenarios-v2', %s, %s, 0, 1, %s, 0, %s)",
               (computed, seed.season_id, status, 1 if ok else None, "b" * 64 if ok else None, digest, Jsonb(reading)))


def kick_off_soon(db: psycopg.Connection[Any], seed: Seed, *, at: datetime = AT + timedelta(days=1)) -> None:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (at, seed.fixture_id))


def facts(db: psycopg.Connection[Any], seed: Seed) -> list[tuple[Any, ...]]:
    return db.execute("SELECT kind, origin, side, fact_schema, subject_type, subject_id, fresh_until, claim FROM ai.evidence WHERE fixture_id = %s "
                      "AND kind = 'stakes' ORDER BY side", (seed.fixture_id,)).fetchall()


def test_the_switch_off_reads_and_counts_but_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    put(db, seed, computed=AT - timedelta(hours=1))
    counts = sf.run(db, at=AT, write=False)
    assert counts.facts == 2 and counts.created == 0 and counts.matches >= 1
    assert facts(db, seed) == []


def test_the_facts_of_both_sides_are_stored_complete_and_valid_until_kickoff(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    put(db, seed, computed=AT - timedelta(hours=1))
    counts = sf.run(db, at=AT, write=True)
    assert counts.created == 2 and counts.errors == []
    rows = facts(db, seed)
    assert [r[:6] for r in rows] == [("stakes", "own_calc", "away", factor_schema.VERSION, "TEAM", seed.away_team_id),
                                     ("stakes", "own_calc", "home", factor_schema.VERSION, "TEAM", seed.home_team_id)]
    assert rows[1][6] == AT + timedelta(days=1)
    assert "ya tiene asegurado ganar el título" in rows[1][7] and "ya no puede ganar el título" in rows[0][7]
    again = sf.run(db, at=AT, write=True)
    assert again.created == 0, "the same reading says the same thing once"
    assert len(facts(db, seed)) == 2


def test_a_newer_reading_adds_a_new_fact_for_the_same_story(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    put(db, seed, computed=AT - timedelta(hours=5))
    sf.run(db, at=AT - timedelta(hours=4), write=True)
    put(db, seed, computed=AT - timedelta(hours=1), home="abierto", away="abierto")
    sf.run(db, at=AT, write=True)
    assert len(facts(db, seed)) == 4


def test_a_stale_reading_and_a_regulation_not_coded_say_why_and_write_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    kick_off_soon(db, seed)
    put(db, seed, computed=AT - sf.MAX_AGE - timedelta(hours=1))
    stale = sf.run(db, at=AT, write=True)
    assert (stale.no_reading, stale.facts, stale.created) == (1, 0, 0)
    put(db, seed, computed=AT - timedelta(hours=1), status=sf.NOT_CODED)
    not_coded = sf.run(db, at=AT, write=True)
    assert (not_coded.not_coded, not_coded.facts) == (1, 0)
    assert facts(db, seed) == []


def test_a_match_that_kicks_off_later_than_the_horizon_or_already_played_gets_none(db: psycopg.Connection[Any], seed: Seed) -> None:
    put(db, seed, computed=AT - timedelta(hours=1))
    kick_off_soon(db, seed, at=AT + sf.AHEAD + timedelta(hours=1))
    assert sf.run(db, at=AT, write=True).facts == 0
    kick_off_soon(db, seed, at=AT - timedelta(hours=3))
    assert sf.run(db, at=AT, write=True).facts == 0


def test_the_report_counts_matches_with_and_without_facts_and_lists_the_sheet(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_stakes_facts as cli

    kick_off_soon(db, seed)
    put(db, seed, computed=AT - timedelta(hours=1))
    doc = cli.report(sf.collect(db, at=AT), sheet=5)
    assert doc["with_facts"] == 1 and doc["facts"] == 2 and doc["without"] == {}
    assert doc["sheet"][0]["fixture_id"] == seed.fixture_id and len(doc["sheet"][0]["facts"]) == 2
    text = "\n".join(cli.lines(doc))
    assert "ya tiene asegurado ganar el título" in text and "1 de 1 partidos con hecho" in text

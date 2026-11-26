"""RP-4.4 (second tranche) on a real database: the state of each player named by a report, as known 90 minutes before kick-off, set against the official sheet
of a played match. A report that arrives after that moment does not count; a match without both sheets is not read; nothing is written. The transaction is
rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import availability_contrast as ac

from .conftest import Seed

pytestmark = pytest.mark.integration

KICKOFF = datetime(2026, 11, 14, 15, tzinfo=UTC)
SINCE, UNTIL = KICKOFF - timedelta(days=1), KICKOFF + timedelta(days=1)


def played(db: psycopg.Connection[Any], seed: Seed, *, sides: tuple[str, ...] = ("home", "away")) -> None:
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'FT', status_group = 'finished' WHERE id = %s", (KICKOFF, seed.fixture_id))
    for side in sides:
        db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, %s)",
                   (seed.fixture_id, side, seed.payload_hash, KICKOFF - timedelta(minutes=20)))


def on_sheet(db: psycopg.Connection[Any], seed: Seed, pid: int, *, starter: bool, side: str = "home") -> None:
    db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) VALUES (%s, %s, 'api-football', %s, %s)",
               (seed.fixture_id, side, pid, starter))


def listed(db: psycopg.Connection[Any], seed: Seed, pid: int, kind: str, *, reason: str = "Knee Injury", before: timedelta = timedelta(hours=5)) -> None:
    db.execute("INSERT INTO core.player_availability_obs (fixture_id, source, provider_player_id, observed_at, status, provider_fixture_id, provider_team_id, "
               "player_name, absence_type, reason, payload_hash, origin, normalizer_version) VALUES (%s, 'api-football', %s, %s, 'LISTED', 50011, 33, %s, %s, %s, "
               "%s, 'answer', 'v1')", (seed.fixture_id, pid, KICKOFF - before, f"Jugador {pid}", kind, reason, seed.payload_hash))


def test_each_report_is_set_against_the_sheet_and_the_level_that_decided_it_is_the_providers(db: psycopg.Connection[Any], seed: Seed) -> None:
    played(db, seed)
    on_sheet(db, seed, 101, starter=True)
    on_sheet(db, seed, 103, starter=False)
    listed(db, seed, 101, "Missing Fixture")  # reported out, started: contradicted
    listed(db, seed, 102, "Missing Fixture", reason="Red Card")  # reported out (suspended), not on the sheet
    listed(db, seed, 103, "Questionable")  # doubtful, on the bench
    got = {o.provider_player_id: o for o in ac.collect(db, since=SINCE, until=UNTIL)}
    assert {p: (o.status, o.basis, o.on_sheet, o.started) for p, o in got.items()} == {
        101: ("baja", "proveedor", True, True), 102: ("sancionado", "proveedor", False, False), 103: ("duda", "proveedor", True, False)}
    doc = ac.summarize(got.values())
    assert (doc["contradicted_out"]["proveedor"]["n"], doc["contradicted_out"]["proveedor"]["hits"]) == (2, 1)
    assert doc["doubt"]["proveedor"] == {"eleven": 0, "bench": 1, "off_sheet": 0}


def test_a_report_made_after_the_moment_asked_does_not_exist_yet(db: psycopg.Connection[Any], seed: Seed) -> None:
    played(db, seed)
    on_sheet(db, seed, 101, starter=True)
    listed(db, seed, 101, "Missing Fixture", before=timedelta(minutes=30))  # after kick-off minus 90 minutes
    assert ac.collect(db, since=SINCE, until=UNTIL) == []
    assert [o.provider_player_id for o in ac.collect(db, since=SINCE, until=UNTIL, lead=timedelta(minutes=10))] == [101]


def test_a_match_without_both_official_sheets_or_outside_the_window_is_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    played(db, seed, sides=("home",))
    on_sheet(db, seed, 101, starter=True)
    listed(db, seed, 101, "Missing Fixture")
    assert ac.collect(db, since=SINCE, until=UNTIL) == [] and ac.matches_read(db, since=SINCE, until=UNTIL) == 0
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) VALUES (%s, 'away', 'api-football', %s, %s)",
               (seed.fixture_id, seed.payload_hash, KICKOFF - timedelta(minutes=20)))
    assert len(ac.collect(db, since=SINCE, until=UNTIL)) == 1 and ac.matches_read(db, since=SINCE, until=UNTIL) == 1
    assert ac.collect(db, since=KICKOFF + timedelta(days=2), until=KICKOFF + timedelta(days=5)) == []


def test_the_command_prints_the_table_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    played(db, seed)
    on_sheet(db, seed, 101, starter=True)
    listed(db, seed, 101, "Missing Fixture")
    doc = ac.summarize(ac.collect(db, since=SINCE, until=UNTIL))
    text = "\n".join(ac.lines(doc))
    assert "baja/sancionado · proveedor: 1 de 1 desmentidos (100.0 %" in text and "menos de 30 reportes: sin veredicto" in text
    before = db.execute("SELECT count(*) FROM core.player_availability_obs").fetchone()
    ac.collect(db, since=SINCE, until=UNTIL)
    assert db.execute("SELECT count(*) FROM core.player_availability_obs").fetchone() == before

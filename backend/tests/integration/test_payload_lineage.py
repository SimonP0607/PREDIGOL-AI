"""A derived row must never be dated after the payload it names.

The raw store keeps identical bodies once and the index holds the FIRST fetch, so a
payload fetched twice left the caller holding the second time. Writing that onto the
derived rows made them newer than their own payload: replaying the indexed payload then
reads as stale, the monotonic writers refuse it - correctly - and that is how 1,809
fixtures' detail came to look absent.

The write path now asks the ledger for the index's time. These tests cover the two things
that were still wrong: the check looked at three relations while six qualified, missing
its two biggest offenders, and nothing repaired the rows already written.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.ops.reprocess import repair_payload_lineage
from fbi.quality.detect import payload_dated_relations, row_newer_than_payload_sql
from tests.integration.conftest import Seed

PAYLOAD_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LATER = PAYLOAD_AT + timedelta(hours=6)
HASH = "aa" * 32


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixture_events WHERE payload_hash = %s", (HASH,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (HASH,))
    db.commit()


def test_every_relation_that_names_a_payload_is_discovered(db: psycopg.Connection) -> None:
    """Asked of the schema, not kept in a list. The list held fixture_team_stats,
    fixture_events and fixture_lineups; it omitted fixture_player_stats (76,305 offending
    rows), player_absences (79,593) and fixture_detail_coverage (7,236)."""
    relations = set(payload_dated_relations(db))

    for required in ("fixture_events", "fixture_lineups", "fixture_team_stats",
                     "fixture_player_stats", "player_absences", "fixture_detail_coverage"):
        assert required in relations, f"core.{required} names a payload and must be checked"


def test_the_generated_sql_covers_each_discovered_relation(db: psycopg.Connection) -> None:
    relations = payload_dated_relations(db)
    sql = row_newer_than_payload_sql(relations)

    assert sql.count("UNION ALL") == len(relations) - 1
    for rel in relations:
        assert f"core.{rel}" in sql


def _an_event_dated_after_its_payload(db: psycopg.Connection, seed: Seed) -> int:
    db.execute(
        "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, "
        " http_status, results_count, file_path, bytes) "
        "VALUES (%s,%s,'/fixtures','{}'::jsonb,%s,200,1,'x.json.gz',1)",
        (HASH, seed.run_id, PAYLOAD_AT))
    db.execute(
        "INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, "
        " event_type, payload_hash, fetched_at) "
        "VALUES (%s,'api-football',1,23,'home','Goal',%s,%s)",
        (seed.fixture_id, HASH, LATER))
    db.commit()
    row = db.execute("SELECT count(*) FROM core.fixture_events e "
                     " JOIN raw.ingestion_payloads p ON p.hash = e.payload_hash "
                     " WHERE e.fetched_at > p.fetched_at AND e.payload_hash = %s",
                     (HASH,)).fetchone()
    assert row is not None and row[0] == 1
    return int(seed.fixture_id)


def test_the_repair_moves_the_row_back_to_its_payloads_time(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The only change is a timestamp moving BACK to the value it should have had."""
    _an_event_dated_after_its_payload(db, seed)

    counts = repair_payload_lineage(db, apply=True)

    assert counts.get("fixture_events", 0) >= 1
    row = db.execute("SELECT fetched_at FROM core.fixture_events WHERE payload_hash = %s",
                     (HASH,)).fetchone()
    assert row is not None and row[0] == PAYLOAD_AT


def test_reporting_without_applying_changes_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    _an_event_dated_after_its_payload(db, seed)

    counts = repair_payload_lineage(db, apply=False)

    assert counts.get("fixture_events", 0) >= 1, "it says what it would do"
    row = db.execute("SELECT fetched_at FROM core.fixture_events WHERE payload_hash = %s",
                     (HASH,)).fetchone()
    assert row is not None and row[0] == LATER, "and does none of it"


def test_the_repair_is_idempotent(db: psycopg.Connection, seed: Seed) -> None:
    """The invariant it restores is the condition it selects on, so a second run has
    nothing to find."""
    _an_event_dated_after_its_payload(db, seed)

    repair_payload_lineage(db, apply=True)
    again = repair_payload_lineage(db, apply=True)

    assert again.get("fixture_events", 0) == 0


def test_a_row_dated_before_its_payload_is_left_alone(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Only rows NEWER than their payload are wrong. An older one is ordinary history and
    moving it forward would invent provenance."""
    db.execute(
        "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, "
        " http_status, results_count, file_path, bytes) "
        "VALUES (%s,%s,'/fixtures','{}'::jsonb,%s,200,1,'x.json.gz',1)",
        (HASH, seed.run_id, LATER))
    db.execute(
        "INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, "
        " event_type, payload_hash, fetched_at) "
        "VALUES (%s,'api-football',2,41,'away','Goal',%s,%s)",
        (seed.fixture_id, HASH, PAYLOAD_AT))
    db.commit()

    repair_payload_lineage(db, apply=True)

    row = db.execute("SELECT fetched_at FROM core.fixture_events WHERE payload_hash = %s",
                     (HASH,)).fetchone()
    assert row is not None and row[0] == PAYLOAD_AT, "untouched"

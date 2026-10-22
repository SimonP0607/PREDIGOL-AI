"""Revision 0069 and scripts/inplay_cleanup.py: the in-play history leaves operational storage only with its evidence.

* 0069 refuses to drop a history table that holds rows no verified archive accounts for - exactly, row for row -
  and drops it, recording rows and bytes, once one does; its downgrade rebuilds the schema of 0032/0037/0038, empty;
* purge-raw removes only archived /odds/live payloads whose bytes match the archive, keeps every payload a quality
  issue still names, refuses while the history tables exist, and records what it freed;
* nothing pre-match is touched along the way.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from scripts import inplay_cleanup as ic

from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import REPO_ROOT, Seed

AT = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)


def _alembic() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _exists(conn: psycopg.Connection, relation: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (relation,))
        row = cur.fetchone()
        return bool(row and row[0])


@pytest.fixture()
def at_0068(migrated_database: str, seed: Seed) -> Iterator[str]:
    """The schema one revision back - the history tables exist again, empty - and head restored afterwards."""
    command.downgrade(_alembic(), "0068")
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        if _exists(conn, "market.live_odds_snapshots"):
            cur.execute("DELETE FROM market.live_odds_snapshots")
            cur.execute("DELETE FROM market.live_fixture_states")
        cur.execute("DELETE FROM audit.storage_cleanups")
    command.upgrade(_alembic(), "head")


def test_0069_refuses_unarchived_rows_then_drops_and_records_once_they_are_archived(at_0068: str, seed: Seed) -> None:
    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        assert _exists(conn, "market.live_odds_snapshots") and _exists(conn, "market.live_market_movement")
        cur.execute("INSERT INTO market.live_odds_snapshots (fixture_id, provider_bet_id, market_key, selection, line, "
                    "odds_decimal, captured_at, payload_hash) VALUES (%s, 59, '1X2', 'Home', 0, 2.5, %s, 'h1')",
                    (seed.fixture_id, AT))
        cur.execute("INSERT INTO market.live_fixture_states (fixture_id, captured_at, elapsed_minute, payload_hash) "
                    "VALUES (%s, %s, 12, 'h1')", (seed.fixture_id, AT))
        cur.execute("SELECT count(*) FROM market.odds_snapshots")
        prematch_before = cur.fetchone()
    with psycopg.connect(at_0068) as conn:
        # A partitioned table is the sum of its partitions; one that is not partitioned is its own size - not 0
        # (the archive of 6 Oct 2026 recorded 0 bytes for live_fixture_states before this was handled).
        assert ic._relation_bytes(conn, "market.live_odds_snapshots") > 0
        assert ic._relation_bytes(conn, "market.live_fixture_states") > 0

    with pytest.raises(Exception, match="no verified archive"):
        command.upgrade(_alembic(), "0069")
    with psycopg.connect(at_0068) as conn:
        assert _exists(conn, "market.live_odds_snapshots"), "nothing was dropped"

    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        # An archive of a different row count does not count.
        cur.execute("INSERT INTO audit.storage_cleanups (kind, subject, rows, verified, code_version) VALUES "
                    "('inplay_archive', 'market.live_odds_snapshots', 2, true, 't')")
    with pytest.raises(Exception, match="no verified archive"):
        command.upgrade(_alembic(), "0069")

    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit.storage_cleanups (kind, subject, rows, verified, code_version) VALUES "
                    "('inplay_archive', 'market.live_odds_snapshots', 1, true, 't')")
    with pytest.raises(Exception, match="no verified archive"):
        command.upgrade(_alembic(), "0069")  # the states table is not archived yet: neither table is dropped
    with psycopg.connect(at_0068) as conn:
        assert _exists(conn, "market.live_odds_snapshots") and _exists(conn, "market.live_fixture_states")

    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit.storage_cleanups (kind, subject, rows, verified, code_version) VALUES "
                    "('inplay_archive', 'market.live_fixture_states', 1, true, 't')")
    command.upgrade(_alembic(), "0069")
    with psycopg.connect(at_0068) as conn, conn.cursor() as cur:
        assert not _exists(conn, "market.live_odds_snapshots") and not _exists(conn, "market.live_fixture_states")
        assert not _exists(conn, "market.live_market_movement") and not _exists(conn, "market.live_odds_at_instant")
        cur.execute("SELECT subject, rows, bytes > 0 FROM audit.storage_cleanups WHERE kind = 'inplay_drop' "
                    "ORDER BY subject")
        assert cur.fetchall() == [("market.live_fixture_states", 1, True), ("market.live_odds_snapshots", 1, True)], \
            "what held rows is recorded, with the bytes each table held"
        cur.execute("SELECT count(*) FROM market.odds_snapshots")
        assert cur.fetchone() == prematch_before, "pre-match prices untouched"
        assert _exists(conn, "market.live_odds_current"), "the current book stays"


# -- purge-raw ---------------------------------------------------------------------------------------------------


def _body(n: int) -> dict[str, Any]:
    return {"response": [{"fixture": {"id": 1001}, "odds": [], "n": n}], "errors": [], "results": 1}


@pytest.fixture()
def raw_world(migrated_database: str, seed: Seed, tmp_path: Path,
              monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Three archived /odds/live payloads in a RAW store: one named by a quality issue, two not."""
    root = tmp_path / "raw"
    store = PayloadStore(root)
    monkeypatch.setattr(ic, "_raw_root", lambda: root)
    monkeypatch.setattr(ic, "_connect", lambda: psycopg.connect(migrated_database))
    stored = [store.store(endpoint="/odds/live", params={}, fetched_at=AT, http_status=200, body=_body(n))
              for n in range(3)]
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        for s in stored:
            cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                        "bytes) VALUES (%s, %s, '/odds/live', %s, 200, %s, %s)",
                        (s.hash, seed.run_id, AT, s.file_path, s.bytes_written))
        cur.execute("INSERT INTO audit.data_quality_issues (code, severity, entity_type, payload_hash, field, observed, "
                    "expected, fingerprint) VALUES ('NORMALIZATION_REJECTED', 'warning', 'odds_snapshot', %s, '1X2', "
                    "'Draw @ 1.00', 'odds out of range', 'purge-test')", (stored[0].hash,))
    out = tmp_path / "archive"
    (out / "db").mkdir(parents=True)
    with psycopg.connect(migrated_database) as conn:
        raw = ic._archive_raw(conn, out)
    manifest = {"created_at": AT.isoformat(), "backup_label": "TEST", "tables": {}, "raw": raw}
    (out / "manifest.json").write_text(json.dumps(manifest))
    yield {"dsn": migrated_database, "root": root, "out": out, "stored": stored, "raw": raw}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues WHERE fingerprint = 'purge-test'")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        cur.execute("DELETE FROM audit.storage_cleanups")


def _record_archive(dsn: str, out: Path) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit.storage_cleanups (kind, subject, rows, archive_path, archive_sha256, verified, "
                    "code_version) VALUES ('inplay_archive', %s, 3, %s, %s, true, 't')",
                    (ic.RAW_SUBJECT, str(out), ic._sha256_file(out / "manifest.json")))


def test_the_raw_archive_reads_back_every_payload_as_its_own_body(raw_world: dict[str, Any]) -> None:
    assert ic._verify_raw(raw_world["out"], raw_world["raw"]) == []
    assert len(raw_world["raw"]["files"]) == 3 and not raw_world["raw"]["missing"]


def test_purge_raw_refuses_without_a_recorded_verified_archive(raw_world: dict[str, Any]) -> None:
    assert ic.purge_raw(raw_world["out"], confirm=True) == 2
    assert all((raw_world["root"] / s.file_path).is_file() for s in raw_world["stored"])


def test_purge_raw_keeps_the_evidence_of_a_quality_issue_and_records_what_it_freed(
    raw_world: dict[str, Any]
) -> None:
    _record_archive(raw_world["dsn"], raw_world["out"])
    assert ic.purge_raw(raw_world["out"], confirm=False) == 0, "a dry run first"
    assert all((raw_world["root"] / s.file_path).is_file() for s in raw_world["stored"])

    assert ic.purge_raw(raw_world["out"], confirm=True) == 0
    kept, gone = raw_world["stored"][0], raw_world["stored"][1:]
    assert (raw_world["root"] / kept.file_path).is_file(), "named by a quality issue: kept"
    assert not any((raw_world["root"] / s.file_path).exists() for s in gone)
    with psycopg.connect(raw_world["dsn"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT hash FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        assert [r[0] for r in cur.fetchall()] == [kept.hash]
        cur.execute("SELECT rows, bytes, details->'kept_as_evidence' FROM audit.storage_cleanups "
                    "WHERE kind = 'inplay_raw_purge'")
        rows, freed, evidence = cur.fetchone() or (0, 0, [])
    assert rows == 2 and freed == sum(s.bytes_written for s in gone) and evidence == [kept.hash]
    # Still recoverable: the archive holds every byte that was removed.
    assert ic._verify_raw(raw_world["out"], raw_world["raw"]) == []


def test_purge_raw_refuses_when_a_file_on_disk_is_not_the_archived_one(raw_world: dict[str, Any]) -> None:
    _record_archive(raw_world["dsn"], raw_world["out"])
    victim = raw_world["root"] / raw_world["stored"][1].file_path
    victim.write_bytes(gzip.compress(b'{"body": "changed"}'))
    assert ic.purge_raw(raw_world["out"], confirm=True) == 2
    assert all((raw_world["root"] / s.file_path).is_file() for s in raw_world["stored"])


def test_the_whole_flow_archive_verify_drop_purge(at_0068: str, seed: Seed, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """measure -> archive (read back, verified, recorded) -> verify -> 0069 drops -> purge-raw: the order of 6 Oct."""
    root = tmp_path / "raw"
    monkeypatch.setattr(ic, "_raw_root", lambda: root)
    monkeypatch.setattr(ic, "_connect", lambda: psycopg.connect(at_0068))
    store = PayloadStore(root)
    payload = store.store(endpoint="/odds/live", params={}, fetched_at=AT, http_status=200, body=_body(7))
    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                    "bytes) VALUES (%s, %s, '/odds/live', %s, 200, %s, %s)",
                    (payload.hash, seed.run_id, AT, payload.file_path, payload.bytes_written))
        for n, (sel, odds) in enumerate((("Home", "2.50"), ("Draw", "3.30"), ("Away", "2.90"))):
            cur.execute("INSERT INTO market.live_odds_snapshots (fixture_id, provider_bet_id, market_key, selection, "
                        "line, odds_decimal, captured_at, payload_hash) VALUES (%s, 59, '1X2', %s, 0, %s, %s, %s)",
                        (seed.fixture_id, sel, odds, AT.replace(second=n), payload.hash))
        cur.execute("INSERT INTO market.live_fixture_states (fixture_id, captured_at, elapsed_minute, score_home, "
                    "score_away, payload_hash) VALUES (%s, %s, 77, 0, 1, %s)", (seed.fixture_id, AT, payload.hash))
    with psycopg.connect(at_0068) as conn:
        measured = ic.measure(conn)
    assert measured["tables"]["market.live_odds_snapshots"]["rows"] == 3
    assert measured["foreign_keys_into_history"] == [] and measured["functions_naming_history"] == []
    assert {v["view"] for v in measured["dependent_views"]} == {"market.live_market_movement",
                                                                 "market.live_odds_at_instant"}

    out = tmp_path / "archive"
    assert ic.archive(out, "TEST_LABEL") == 0
    assert ic.verify(out) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["tables"]["market.live_odds_snapshots"]["rows"] == 3
    assert manifest["tables"]["market.live_fixture_states"]["rows"] == 1
    with gzip.open(out / "db" / "market.live_odds_snapshots.csv.gz", "rt") as fh:
        assert fh.readline().startswith("fixture_id,provider_bet_id,market_key,selection,line,odds_decimal")

    command.upgrade(_alembic(), "0069")  # the recorded archive satisfies the guard
    with psycopg.connect(at_0068) as conn, conn.cursor() as cur:
        assert not _exists(conn, "market.live_odds_snapshots")
        cur.execute("SELECT kind, subject, rows FROM audit.storage_cleanups ORDER BY id")
        assert cur.fetchall() == [("inplay_archive", "market.live_odds_snapshots", 3),
                                  ("inplay_archive", "market.live_fixture_states", 1),
                                  ("inplay_archive", ic.RAW_SUBJECT, 1),
                                  ("inplay_drop", "market.live_odds_snapshots", 3),
                                  ("inplay_drop", "market.live_fixture_states", 1)]
    assert ic.purge_raw(out, confirm=True) == 0
    assert not (root / payload.file_path).exists()
    with psycopg.connect(at_0068, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        assert cur.fetchone() == (0,)


def test_a_payload_damaged_in_the_store_is_archived_as_it_is_and_marked(raw_world: dict[str, Any]) -> None:
    """The archive reproduces the store byte for byte; it does not repair it, and it says which files were damaged."""
    victim = raw_world["root"] / raw_world["stored"][2].file_path
    victim.write_bytes(b"")  # as the 4 Oct 2026 02:57 UTC stop left a few
    out = raw_world["out"].parent / "archive-damaged"
    (out / "db").mkdir(parents=True)
    with psycopg.connect(raw_world["dsn"]) as conn:
        raw = ic._archive_raw(conn, out)
    assert raw["damaged_at_source"] == [raw_world["stored"][2].file_path]
    assert ic._verify_raw(out, raw) == []


def test_an_indexed_payload_already_absent_from_the_store_is_named_and_its_row_purged(
    raw_world: dict[str, Any]
) -> None:
    gone = raw_world["root"] / raw_world["stored"][1].file_path
    gone.unlink()  # as the 4 Oct 2026 02:57 UTC stop left one
    out = raw_world["out"].parent / "archive-missing"
    (out / "db").mkdir(parents=True)
    with psycopg.connect(raw_world["dsn"]) as conn:
        raw = ic._archive_raw(conn, out)
    assert raw["missing"] == [{"file_path": raw_world["stored"][1].file_path,
                               "payload_hash": raw_world["stored"][1].hash}]
    assert ic._verify_raw(out, raw) == []
    (out / "manifest.json").write_text(json.dumps({"backup_label": "TEST", "tables": {}, "raw": raw}))
    _record_archive(raw_world["dsn"], out)
    gone.write_bytes(b"back after the archive")
    assert ic.purge_raw(out, confirm=True) == 2, "a file that was not archived is never removed blind"
    assert gone.read_bytes() == b"back after the archive"
    gone.unlink()
    assert ic.purge_raw(out, confirm=True) == 0
    with psycopg.connect(raw_world["dsn"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT hash FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        assert [r[0] for r in cur.fetchall()] == [raw_world["stored"][0].hash], "only the issue's evidence remains"


def test_purge_raw_deletes_nothing_when_a_payload_becomes_referenced_during_the_purge(
    raw_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-row foreign-key checks are skipped for the delete and replaced by one check per table AFTER it, in the
    same transaction: a reference the first look missed (here: the quality issue's, hidden from it) is found there,
    and the whole purge is rolled back - index rows, files and the record."""
    _record_archive(raw_world["dsn"], raw_world["out"])
    real, looks = ic._named, []

    def first_look_misses(cur: Any, referencing: Any, hashes: list[str]) -> set[str]:
        looks.append(len(hashes))
        return set() if len(looks) == 1 else real(cur, referencing, hashes)

    monkeypatch.setattr(ic, "_named", first_look_misses)
    assert ic.purge_raw(raw_world["out"], confirm=True) == 2
    assert len(looks) == 2, "checked before and after the delete"
    assert all((raw_world["root"] / s.file_path).is_file() for s in raw_world["stored"])
    with psycopg.connect(raw_world["dsn"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        assert cur.fetchone() == (3,)
        cur.execute("SELECT count(*) FROM audit.storage_cleanups WHERE kind = 'inplay_raw_purge'")
        assert cur.fetchone() == (0,)


def test_purge_raw_removes_the_files_an_interrupted_purge_left(raw_world: dict[str, Any]) -> None:
    """Killed after its commit and before its last unlink: the index rows are gone, some files are not. Run again,
    the archived bytes still on disk are removed - and only those."""
    _record_archive(raw_world["dsn"], raw_world["out"])
    left = raw_world["stored"][1]
    with psycopg.connect(raw_world["dsn"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (left.hash,))
    stranger = raw_world["root"] / "api-football" / "odds-live__not-archived.json.gz"
    stranger.parent.mkdir(parents=True, exist_ok=True)
    stranger.write_bytes(b"not in the archive")
    assert ic.purge_raw(raw_world["out"], confirm=True) == 0
    assert not (raw_world["root"] / left.file_path).exists()
    assert not (raw_world["root"] / raw_world["stored"][2].file_path).exists()
    assert (raw_world["root"] / raw_world["stored"][0].file_path).is_file(), "the issue's evidence stays"
    assert stranger.read_bytes() == b"not in the archive", "a file the archive does not hold is never touched"
    with psycopg.connect(raw_world["dsn"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT rows, details->'unindexed_files_removed' FROM audit.storage_cleanups "
                    "WHERE kind = 'inplay_raw_purge'")
        assert cur.fetchone() == (1, 1)
    assert ic.purge_raw(raw_world["out"], confirm=True) == 0, "a third run finds nothing to do"

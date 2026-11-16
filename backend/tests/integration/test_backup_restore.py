"""A backup is only as good as its restore: dump, archive, restore into a new
database, and compare every table and every raw file - including the case
where the index names a payload the archive does not hold."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from fbi.ops.backup import (
    MANIFEST,
    RAW,
    create_backup,
    fingerprints,
    live_worker,
    restore_test,
    verify_files,
)
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import ADMIN_URL, Seed


def test_backup_restores_to_an_identical_database(migrated_database: str, seed: Seed, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    stored = PayloadStore(raw).store(endpoint="/status", params={"apikey": "never-stored"},
                                     fetched_at=datetime(2026, 9, 25, 3, 0, tzinfo=UTC), http_status=200,
                                     body={"response": {"requests": {"current": 1}}})
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                     "bytes) VALUES (%s, %s, '/status', now(), 200, %s, %s)",
                     (stored.hash, seed.run_id, stored.file_path, stored.bytes_written))
    try:
        rep = create_backup(migrated_database, raw, tmp_path / "backups", label="test")
        manifest = json.loads((rep.folder / MANIFEST).read_text())
        assert manifest["alembic_revision"] and manifest["raw_store"]["files"] == 1
        assert "raw.ingestion_payloads" in manifest["tables"] and manifest["changed_during_dump"] == []
        assert "never-stored" not in (rep.folder / MANIFEST).read_text()
        assert verify_files(rep.folder) == []

        report = restore_test(rep.folder, ADMIN_URL)
        by = {c.name.split(":")[0]: c for c in report.checks}
        assert "intel.capability_transitions:capability_transitions_append_only" in manifest["append_only"]  # AD-A07
        assert {"ai", "intel", "raw"} <= set(manifest["schemas"])
        for name in ("FILES", "RESTORE", "TABLES", "SCHEMA", "RAW", "SCHEMAS", "APPEND-ONLY"):
            assert by[name].passed, f"{name}: {by[name].detail}"
        lineage = by["LINEAGE"]
        assert not lineage.passed and "not in this raw store" in lineage.detail, \
            "the seed's index row names a file that was never written: the check must say so"
        assert "MISMATCHED" not in lineage.detail
        with psycopg.connect(ADMIN_URL) as admin:
            left = admin.execute("SELECT count(*) FROM pg_database WHERE datname = %s", (report.scratch_db,)).fetchone()
        assert left is not None and left[0] == 0, "the scratch database is dropped"

        tampered = rep.folder / RAW
        data = bytearray(tampered.read_bytes())
        data[len(data) // 2] ^= 0xFF
        tampered.write_bytes(bytes(data))
        assert verify_files(rep.folder) == [f"{RAW}: sha256 differs from the manifest"]
        assert not restore_test(rep.folder, ADMIN_URL).passed
    finally:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (stored.hash,))


def test_fingerprints_see_a_changed_value(db: psycopg.Connection, seed: Seed) -> None:
    before = fingerprints(db)
    db.execute("UPDATE core.teams SET name = name || ' ' WHERE id = %s", (seed.home_team_id,))
    after = fingerprints(db)
    assert before["core.teams"]["rows"] == after["core.teams"]["rows"]
    assert before["core.teams"]["md5"] != after["core.teams"]["md5"]
    assert before["core.fixtures"] == after["core.fixtures"]


# --- the restore test must not be the reason the capture stopped ------------


def test_a_restore_test_refuses_while_the_worker_is_beating(
    db: psycopg.Connection, migrated_database: str, tmp_path: Path
) -> None:
    """The guard, and the outage behind it.

    Run on the live machine, a restore test held the database server for 19,123
    seconds - five hours and twenty-one minutes - and the capture stopped for
    all of it. An in-play price missed cannot be re-fetched: /odds/live keeps no
    history, and a pre-match window that closes is gone. The misfire grace is
    derived from the capture tolerance now, so a short busy period is survived
    by running ticks late; five hours is not a short busy period and no grace
    should be asked to cover it.

    The guard costs nothing and fires before any work is done - note that it
    does not even need the backup folder to be valid.
    """
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.worker_heartbeats "
            "(worker_id, hostname, pid, code_version, started_at, last_beat_at, "
            " tick_interval_s) "
            "VALUES ('test:worker', 'test', 1, 'test', now(), now(), 300) "
            "ON CONFLICT (worker_id) DO UPDATE SET last_beat_at = now(), "
            "  stopped_at = NULL"
        )
    db.commit()
    try:
        assert live_worker(migrated_database) == "test:worker"
        report = restore_test(tmp_path, "postgresql://nowhere/postgres",
                              app_url=migrated_database)
        assert not report.passed
        assert any("WORKER" in c.name for c in report.checks)
        assert report.scratch_db == "", "no scratch database was created"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'test:worker'")
        db.commit()


def test_a_stopped_worker_does_not_block_a_restore_test(
    db: psycopg.Connection, migrated_database: str
) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.worker_heartbeats "
            "(worker_id, hostname, pid, code_version, started_at, last_beat_at, "
            " tick_interval_s, stopped_at) "
            "VALUES ('test:stopped', 'test', 1, 'test', now(), now(), 300, now()) "
            "ON CONFLICT (worker_id) DO UPDATE SET last_beat_at = now(), stopped_at = now()"
        )
    db.commit()
    try:
        assert live_worker(migrated_database) is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'test:stopped'")
        db.commit()


def test_a_stale_heartbeat_does_not_block_a_restore_test(
    db: psycopg.Connection, migrated_database: str
) -> None:
    """A worker that died without saying so must not lock maintenance out for
    ever, so the guard asks whether it beat RECENTLY, not whether it ever did."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.worker_heartbeats "
            "(worker_id, hostname, pid, code_version, started_at, last_beat_at, "
            " tick_interval_s) "
            "VALUES ('test:stale', 'test', 1, 'test', now() - interval '2 hours', "
            "        now() - interval '2 hours', 300) "
            "ON CONFLICT (worker_id) DO UPDATE SET "
            "  last_beat_at = now() - interval '2 hours', stopped_at = NULL"
        )
    db.commit()
    try:
        assert live_worker(migrated_database) is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'test:stale'")
        db.commit()


def test_a_database_the_guard_cannot_read_does_not_block_it_either(
    tmp_path: Path,
) -> None:
    """The guard refusing to speak must not become the guard refusing the work:
    without a readable heartbeat it returns None and the test proceeds."""
    assert live_worker("postgresql://127.0.0.1:1/nowhere") is None


def test_a_new_schema_with_an_append_only_table_comes_back_append_only(migrated_database: str, tmp_path: Path) -> None:
    """AD-A07: a schema the plan adds (here a stand-in for ``news``) is in the backup with no list to update, and its restore test proves
    the schema and its append-only trigger came back - and that the restored table still refuses an UPDATE."""
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA ad_a07_probe; CREATE TABLE ad_a07_probe.items (id int PRIMARY KEY); "
                     "INSERT INTO ad_a07_probe.items VALUES (1); "
                     "CREATE TRIGGER items_append_only BEFORE UPDATE OR DELETE ON ad_a07_probe.items "
                     "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")
    scratch = None
    try:
        rep = create_backup(migrated_database, tmp_path / "raw", tmp_path / "backups", label="a07")
        assert "ad_a07_probe" in rep.manifest["schemas"]
        assert "ad_a07_probe.items:items_append_only" in rep.manifest["append_only"]
        report = restore_test(rep.folder, ADMIN_URL, keep=True)
        scratch = report.scratch_db
        by = {c.name.split(":")[0]: c for c in report.checks}
        assert by["SCHEMAS"].passed and by["APPEND-ONLY"].passed, (by["SCHEMAS"].detail, by["APPEND-ONLY"].detail)
        head, _, _ = ADMIN_URL.rpartition("/")
        with psycopg.connect(f"{head}/{report.scratch_db}") as restored:
            try:
                restored.execute("UPDATE ad_a07_probe.items SET id = 2")
                raise AssertionError("the restored table took an UPDATE")
            except psycopg.errors.CheckViolation:
                restored.rollback()
    finally:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS ad_a07_probe CASCADE")
        if scratch:
            with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{scratch}"')

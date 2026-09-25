"""A backup is only as good as its restore: dump, archive, restore into a new
database, and compare every table and every raw file - including the case
where the index names a payload the archive does not hold."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from fbi.ingestion.payload_store import PayloadStore
from fbi.ops.backup import MANIFEST, RAW, create_backup, fingerprints, restore_test, verify_files
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
        for name in ("FILES", "RESTORE", "TABLES", "SCHEMA", "RAW"):
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

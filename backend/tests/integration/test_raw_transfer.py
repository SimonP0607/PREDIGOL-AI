"""Raw payloads move between installations verified, idempotently, and with the
fetch time they really had - the transfer is its own dated ledger run."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Json

from fbi.ops.raw_transfer import MANIFEST, TransferError, export_payloads, import_payloads
from fbi.storage.payload_store import PayloadStore, body_hash
from tests.integration.conftest import Seed

FETCHED = [datetime(2026, 9, 24, 20, 1, tzinfo=UTC), datetime(2026, 9, 24, 20, 2, tzinfo=UTC)]


def _stored(db: psycopg.Connection, root: Path, provider: str) -> list[str]:
    store = PayloadStore(root, provider="football-data")
    tag = uuid.uuid4().hex
    with db.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t', 'test', 'completed') "
                    "RETURNING id")
        row = cur.fetchone()
        assert row is not None
        hashes = []
        for i, at in enumerate(FETCHED):
            body = {"format": "csv", "text": f"Div,Date,HomeTeam\nE0,{i},{tag}\n"}
            sp = store.store(endpoint=f"/mmz4281/2425/E{i}.csv", params={"division": f"E{i}"}, fetched_at=at,
                             http_status=200, body=body)
            cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, "
                        "http_status, results_count, file_path, bytes) VALUES (%s,%s,%s,%s,%s,%s,200,1,%s,%s)",
                        (sp.hash, row[0], provider, f"/mmz4281/2425/E{i}.csv", Json({"division": f"E{i}"}), at,
                         sp.file_path, sp.bytes_written))
            hashes.append(sp.hash)
    db.commit()
    return hashes


def _drop_rows(db: psycopg.Connection, provider: str) -> None:
    db.execute("DELETE FROM raw.ingestion_payloads WHERE provider = %s", (provider,))
    db.commit()


def test_export_then_import_keeps_lineage_and_is_idempotent(db: psycopg.Connection, seed: Seed,
                                                            tmp_path: Path) -> None:
    provider = f"transfer_test_{uuid.uuid4().hex[:8]}"
    hashes = _stored(db, tmp_path / "origin", provider)
    rep = export_payloads(db, tmp_path / "origin", tmp_path / "t.tar", provider=provider, origin="cloud replica")
    assert rep.rows == 2
    _drop_rows(db, provider)  # the receiving installation has never seen them

    dest = tmp_path / "dest"
    dry = import_payloads(db, dest, tmp_path / "t.tar", reason="blocked here", apply=False)
    assert dry.files_written == 2 and dry.run_id is None and not dest.exists(), "verify-only writes nothing"

    imp = import_payloads(db, dest, tmp_path / "t.tar", reason="blocked here", apply=True)
    assert (imp.files_written, imp.rows_inserted, imp.rows_already_indexed) == (2, 2, 0)
    with db.cursor() as cur:
        cur.execute("SELECT hash, run_id, fetched_at, file_path FROM raw.ingestion_payloads WHERE provider = %s "
                    "ORDER BY fetched_at", (provider,))
        rows = cur.fetchall()
        cur.execute("SELECT job_type, status, params->>'origin', params->>'reason' FROM raw.ingestion_runs "
                    "WHERE id = %s", (imp.run_id,))
        run = cur.fetchone()
    assert [r[0] for r in rows] == hashes and all(r[1] == imp.run_id for r in rows)
    assert [r[2] for r in rows] == FETCHED, "the provider's answer keeps its own time"
    assert run == ("raw_transfer", "completed", "cloud replica", "blocked here")
    store = PayloadStore(dest)
    assert all(body_hash(store.load(r[3])["body"]) == r[0] for r in rows), "the files re-hash where they landed"

    again = import_payloads(db, dest, tmp_path / "t.tar", reason="blocked here", apply=True)
    assert (again.files_written, again.files_already_present, again.rows_inserted, again.rows_already_indexed) \
        == (0, 2, 0, 2)


def test_a_corrupted_archive_writes_nothing(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    provider = f"transfer_test_{uuid.uuid4().hex[:8]}"
    _stored(db, tmp_path / "origin", provider)
    export_payloads(db, tmp_path / "origin", tmp_path / "t.tar", provider=provider, origin="cloud replica")
    _drop_rows(db, provider)

    bad = tmp_path / "bad.tar"
    with tarfile.open(tmp_path / "t.tar") as src, tarfile.open(bad, "w") as dst:
        for m in src.getmembers():
            fh = src.extractfile(m)
            assert fh is not None
            data = fh.read()
            if m.name != MANIFEST:
                data = data[:-1] + bytes([data[-1] ^ 1])  # one bit
            info = tarfile.TarInfo(m.name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    with pytest.raises(TransferError, match="sha256 differs"):
        import_payloads(db, tmp_path / "dest", bad, reason="blocked here", apply=True)
    assert not (tmp_path / "dest").exists()
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE provider = %s", (provider,))
        assert cur.fetchone() == (0,)


def test_export_refuses_a_file_that_does_not_rehash(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> None:
    provider = f"transfer_test_{uuid.uuid4().hex[:8]}"
    _stored(db, tmp_path / "origin", provider)
    with db.cursor() as cur:
        cur.execute("SELECT file_path FROM raw.ingestion_payloads WHERE provider = %s LIMIT 1", (provider,))
        row = cur.fetchone()
    assert row is not None
    path = tmp_path / "origin" / row[0]
    env = json.loads(gzip.decompress(path.read_bytes()))
    env["body"]["text"] += "tampered"
    path.write_bytes(gzip.compress(json.dumps(env).encode()))
    with pytest.raises(TransferError, match="does not re-hash"):
        export_payloads(db, tmp_path / "origin", tmp_path / "t.tar", provider=provider, origin="cloud replica")
    _drop_rows(db, provider)

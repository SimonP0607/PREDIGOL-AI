"""The raw store must be traceable, idempotent, and free of credentials."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fbi.ingestion.payload_store import PayloadStore, body_hash, sanitize

FETCHED = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)
SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.fixture()
def store(tmp_path: Path) -> PayloadStore:
    return PayloadStore(tmp_path)


def test_an_api_key_can_never_reach_the_disk(store: PayloadStore, tmp_path: Path) -> None:
    """The single most important test in this module. If it ever fails, stop and
    rotate the key before doing anything else."""
    store.store(
        endpoint="/odds",
        params={"fixture": 1001, "apikey": SECRET, "x-apisports-key": SECRET, "token": SECRET},
        fetched_at=FETCHED,
        http_status=200,
        body={"response": []},
    )
    for path in tmp_path.rglob("*.json.gz"):
        with gzip.open(path, "rb") as fh:
            text = fh.read().decode()
        assert SECRET not in text, f"the API key was written to {path}"
        assert "[REDACTED]" in text


def test_sanitize_redacts_every_credential_shaped_key() -> None:
    cleaned = sanitize(
        {
            "fixture": 1001,
            "apikey": SECRET,
            "API_KEY": SECRET,
            "Authorization": f"Bearer {SECRET}",
            "x-apisports-key": SECRET,
            "password": "hunter2",
            "season": 2025,
        }
    )
    assert cleaned["fixture"] == "1001"
    assert cleaned["season"] == "2025"
    assert SECRET not in json.dumps(cleaned)
    assert "hunter2" not in json.dumps(cleaned)


def test_layout_is_date_partitioned(store: PayloadStore, tmp_path: Path) -> None:
    stored = store.store(
        endpoint="/odds/live",
        params={"fixture": 1001},
        fetched_at=FETCHED,
        http_status=200,
        body={"response": [{"a": 1}]},
    )
    assert stored.file_path.replace("\\", "/").startswith("api-football/2026/09/15/")
    assert stored.file_path.endswith(".json.gz")
    assert (tmp_path / stored.file_path).exists()


def test_identical_bodies_are_stored_once(store: PayloadStore) -> None:
    """Idempotency: re-ingesting the same response must not duplicate bytes."""
    body = {"response": [{"fixture": {"id": 1}}]}
    first = store.store(
        endpoint="/odds", params={"fixture": 1}, fetched_at=FETCHED, http_status=200, body=body
    )
    second = store.store(
        endpoint="/odds", params={"fixture": 1}, fetched_at=FETCHED, http_status=200, body=body
    )
    assert first.hash == second.hash
    assert first.already_present is False
    assert second.already_present is True


def test_hash_is_insensitive_to_key_order_but_not_to_content() -> None:
    assert body_hash({"a": 1, "b": 2}) == body_hash({"b": 2, "a": 1})
    assert body_hash({"a": 1}) != body_hash({"a": 2})


def test_a_stored_payload_round_trips(store: PayloadStore) -> None:
    body = {"response": [{"fixture": {"id": 7}}], "paging": {"current": 1, "total": 1}}
    stored = store.store(
        endpoint="/odds", params={"fixture": 7}, fetched_at=FETCHED, http_status=200, body=body
    )
    envelope = store.load(stored.file_path)
    assert envelope["body"] == body
    assert envelope["endpoint"] == "/odds"
    assert envelope["http_status"] == 200
    assert envelope["payload_hash"] == stored.hash
    assert envelope["captured_at"] == FETCHED.isoformat()


def test_credentials_inside_strings_are_redacted_and_httpx_is_quiet() -> None:
    import logging

    from fbi.core.logging import configure, redact_text

    assert redact_text("POST https://api.telegram.org/bot123456:AAE-x_y/sendMessage") == \
        "POST https://api.telegram.org/bot[REDACTED]/sendMessage"
    assert "sk-ant-" not in redact_text("key sk-ant-api03-abcdefghijkl failed")
    assert redact_text("postgresql+psycopg://fbi:hunter2@localhost:5433/fbi") == \
        "postgresql+psycopg://fbi:[REDACTED]@localhost:5433/fbi"
    configure("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING


def test_an_empty_file_left_by_a_crash_is_not_taken_as_the_payload(store: PayloadStore, tmp_path: Path) -> None:
    """4 Oct 2026: a payload renamed into place before its bytes reached the disk was found empty after
    the machine stopped. The same body arriving again rewrites it; a whole file is never rewritten."""
    body = {"response": [{"fixture": {"id": 7}}]}
    first = store.store(endpoint="/fixtures", params={"ids": "7"}, fetched_at=FETCHED, http_status=200, body=body)
    path = tmp_path / first.file_path
    path.write_bytes(b"")
    again = store.store(endpoint="/fixtures", params={"ids": "7"}, fetched_at=FETCHED, http_status=200, body=body)
    assert again.hash == first.hash and not again.already_present
    assert store.load(again.file_path)["body"] == body
    whole = path.stat().st_mtime_ns
    third = store.store(endpoint="/fixtures", params={"ids": "7"}, fetched_at=FETCHED, http_status=200, body=body)
    assert third.already_present and path.stat().st_mtime_ns == whole

"""Immutable on-disk store of every provider response.

Layout:  data/raw/api-football/YYYY/MM/DD/<endpoint>__<hash12>.json.gz

The body is gzipped JSON with a small envelope: endpoint, params, captured_at,
http_status, payload_hash. The database keeps only the index (raw.ingestion_payloads);
the bytes stay on disk, where they cost nothing and can be replayed.

CREDENTIALS ARE NEVER WRITTEN HERE. ``SENSITIVE_KEYS`` is applied to the params
before anything touches the filesystem, and there is a test that asserts the API
key cannot appear in a stored file. This is the one rule in this module that is
not a preference.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

SENSITIVE_KEYS = re.compile(
    r"(key|token|secret|password|apikey|api_key|authorization|auth|bearer)", re.IGNORECASE
)
REDACTED = "[REDACTED]"


def sanitize(params: dict[str, Any]) -> dict[str, str]:
    """Strip anything that looks like a credential. Applied before storage AND
    before logging, so a secret has no path to either."""
    return {
        k: (REDACTED if SENSITIVE_KEYS.search(k) else str(v))
        for k, v in sorted(params.items())
    }


def body_hash(body: Any) -> str:
    """sha256 of the canonical JSON body. Identical responses hash identically,
    which is what makes re-ingestion idempotent."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _usable(path: Path) -> bool:
    """An existing file counts as the payload only when it has content and is gzip. On 4 Oct 2026 a
    payload written at 02:57 UTC was found empty (0 bytes on disk, 6,124 recorded): renamed into place
    before its bytes reached the disk, then the machine stopped. Writes are now synced before the rename;
    and a damaged file is rewritten from the same body (same hash, so the same evidence) instead of being
    taken as already captured."""
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def _fsync_dir(directory: Path) -> None:
    """Make the rename itself durable (POSIX); a no-op where directories cannot be opened (Windows)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class StoredPayload:
    hash: str
    file_path: str
    bytes_written: int
    already_present: bool


class PayloadStore:
    def __init__(self, root: Path | str, provider: str = "api-football") -> None:
        self._root = Path(root)
        self._provider = provider

    def path_for(self, endpoint: str, fetched_at: datetime, digest: str) -> Path:
        slug = endpoint.strip("/").replace("/", "-") or "root"
        return (
            self._root
            / self._provider
            / f"{fetched_at:%Y}"
            / f"{fetched_at:%m}"
            / f"{fetched_at:%d}"
            / f"{slug}__{digest[:12]}.json.gz"
        )

    def store(
        self,
        *,
        endpoint: str,
        params: dict[str, Any],
        fetched_at: datetime,
        http_status: int,
        body: Any,
    ) -> StoredPayload:
        safe_params = sanitize(params)
        digest = body_hash(body)
        path = self.path_for(endpoint, fetched_at, digest)

        if _usable(path):
            # Same bytes already captured. Re-ingestion must not duplicate work.
            return StoredPayload(
                hash=digest,
                file_path=str(path.relative_to(self._root)),
                bytes_written=path.stat().st_size,
                already_present=True,
            )

        envelope = {
            "provider": self._provider,
            "endpoint": endpoint,
            "params": safe_params,
            "captured_at": fetched_at.isoformat(),
            "http_status": http_status,
            "payload_hash": digest,
            "body": body,
        }
        raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as out:
            with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6) as fh:
                fh.write(raw)
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(path)  # atomic: a reader never sees a half-written payload
        _fsync_dir(path.parent)

        written = path.stat().st_size
        log.debug(
            "payload.stored",
            endpoint=endpoint,
            params=safe_params,
            payload_hash=digest[:12],
            bytes=written,
        )
        return StoredPayload(
            hash=digest,
            file_path=str(path.relative_to(self._root)),
            bytes_written=written,
            already_present=False,
        )

    def load(self, file_path: str) -> dict[str, Any]:
        with gzip.open(self._root / file_path, "rb") as fh:
            envelope: dict[str, Any] = json.loads(fh.read().decode("utf-8"))
        return envelope

"""One V2 audit command run: its provider requests and its ``audit.truth_v2_runs`` row.

Every request goes through the normal client (daily guard + per-run cap) and its answer is
stored as a NEW raw payload, indexed under an ingestion run of job type ``truth_v2_<kind>``.
Existing payloads are never touched. A request that fails is counted and remembered; a quota
stop ends the run's requests (``stopped``) without raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.core.version import code_version
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.base import RawResponse

log = structlog.get_logger(__name__)


@dataclass
class Answer:
    """One provider answer: its body and where its bytes are kept."""

    endpoint: str
    params: dict[str, Any]
    body: dict[str, Any]
    fetched_at: datetime
    payload_hash: str | None

    @property
    def items(self) -> list[dict[str, Any]]:
        response = self.body.get("response")
        if isinstance(response, list):
            return [x for x in response if isinstance(x, dict)]
        if isinstance(response, dict):
            return [response]
        return []

    @property
    def errors(self) -> Any:
        return self.body.get("errors")

    def ref(self) -> dict[str, Any]:
        """The evidence pointer: endpoint, parameters, when, which RAW payload."""
        return {"endpoint": self.endpoint, "params": self.params, "fetched_at": self.fetched_at.isoformat(),
                "payload_hash": self.payload_hash}


@dataclass
class V2Run:
    conn: psycopg.Connection[Any]
    client: Any
    kind: str
    at: datetime
    params: dict[str, Any] = field(default_factory=dict)
    run_id: int = 0
    ingestion_run_id: int = 0
    requests: int = 0
    failures: list[str] = field(default_factory=list)
    stopped: str | None = None
    counters: RunCounters = field(default_factory=RunCounters)

    def __post_init__(self) -> None:
        self._ledger = RunLedger(self.conn)
        self.ingestion_run_id = self._ledger.open(f"truth_v2_{self.kind}", params=self.params, scheduled_for=self.at)
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO audit.truth_v2_runs (kind, started_at, ingestion_run_id, code_version, params) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (self.kind, self.at, self.ingestion_run_id, code_version(), Json(self.params)))
            row = cur.fetchone()
        assert row is not None
        self.run_id = int(row[0])
        self.conn.commit()

    async def get(self, endpoint: str, params: dict[str, Any]) -> Answer | None:
        """One request; None when it failed or the run has stopped."""
        if self.stopped or self.client is None:
            return None
        try:
            response = await self.client.get(endpoint, params)
        except QuotaExhaustedError as exc:
            self.stopped = f"quota: {exc}"
            self.counters.stopped_early = "quota"
            return None
        except ProviderError as exc:
            self.requests += 1
            self.counters.api_calls += 1
            message = f"{endpoint} {params}: {exc}"[:300]
            self.failures.append(message)
            self.counters.errors.append(message)
            return None
        self.requests += 1
        self.counters.api_calls += 1
        stored = getattr(response, "stored", None)
        payload_hash = None
        if stored is not None:
            raw = RawResponse(endpoint=endpoint, params=response.params, fetched_at=response.fetched_at,
                              http_status=response.http_status, results_count=response.results_count,
                              payload_hash=stored.hash, file_path=stored.file_path,
                              bytes_written=stored.bytes_written, body=response.body)
            self.counters.payloads_stored += self._ledger.record_payloads(self.ingestion_run_id, [raw])
            payload_hash = stored.hash
            self.conn.commit()
        body = response.body if isinstance(response.body, dict) else {}
        return Answer(endpoint, {k: str(v) for k, v in params.items()}, body, response.fetched_at, payload_hash)

    async def get_all_pages(self, endpoint: str, params: dict[str, Any], *, max_pages: int = 50) -> list[Answer]:
        """Every page of a paginated endpoint (``paging.total``)."""
        first = await self.get(endpoint, params)
        if first is None:
            return []
        out = [first]
        paging = first.body.get("paging") if isinstance(first.body.get("paging"), dict) else {}
        total = int(paging.get("total") or 1) if isinstance(paging, dict) else 1
        for page in range(2, min(total, max_pages) + 1):
            nxt = await self.get(endpoint, {**params, "page": page})
            if nxt is None:
                break
            out.append(nxt)
        return out

    def finish(self, summary: dict[str, Any], *, report_dir: Path | None = None, failed: bool = False) -> str:
        status = "failed" if failed else ("partial" if (self.stopped or self.failures) else "completed")
        with self.conn.cursor() as cur:
            cur.execute("UPDATE audit.truth_v2_runs SET finished_at = now(), status = %s, requests = %s, summary = %s, "
                        "report_dir = %s WHERE id = %s",
                        (status, self.requests, Json(json.loads(json.dumps(summary, default=str))),
                         str(report_dir) if report_dir else None, self.run_id))
        self._ledger.close(self.ingestion_run_id, self.counters,
                           notes=f"truth v2 {self.kind} run {self.run_id}: {self.requests} requests")
        self.conn.commit()
        return status


def write_report(root: Path, kind: str, at: datetime, body: dict[str, Any], md: str) -> Path:
    """``<root>/<stamp>-<kind>/``; two runs of one kind started in the same second get "-2", "-3"
    (each report is evidence: one never overwrites another)."""
    folder = root / f"{at:%Y%m%dT%H%M%SZ}-{kind}"
    n = 1
    while folder.exists():
        n += 1
        folder = root / f"{at:%Y%m%dT%H%M%SZ}-{kind}-{n}"
    folder.mkdir(parents=True)
    (folder / f"{kind}.json").write_text(json.dumps(body, indent=1, default=str))
    (folder / f"{kind}.md").write_text(md)
    return folder

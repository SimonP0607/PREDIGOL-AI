"""Where the AI layer writes - its own tables and nothing else (``migrations/versions/0055``).

Every run is a row in ``analytics.ai_runs`` from its first moment (status ``running``), its
tokens and cost updated after each model call so the monthly cap sees a run in flight, and
closed with how it ended: ok, failed, not_configured or over_budget. Claims, reports and pick
flags hang off their run.

The connection is injected: the API and the worker use ``fbi.analyst.db.write_connection``
(its own transaction per write, bounded statements); tests pass their own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.analyst import budget
from fbi.analyst.db import write_connection
from fbi.analyst.provenance import Claim

Connect = Callable[[], AbstractContextManager[psycopg.Connection[Any]]]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, body: dict[str, Any]) -> None:
        u = body.get("usage") or {}
        self.input_tokens += int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) \
            + int(u.get("cache_read_input_tokens") or 0)
        self.output_tokens += int(u.get("output_tokens") or 0)
        self.calls += 1


@dataclass(frozen=True, slots=True)
class FlagRow:
    set_id: int | None
    rank: int | None
    fixture_id: int
    code: str
    severity: str
    note: str
    claim_ids: tuple[int, ...] = ()


def shared(conn: psycopg.Connection[Any]) -> Connect:
    """A connector that hands out one existing connection (tests, or a caller's transaction)."""

    @contextmanager
    def _cm() -> Iterator[psycopg.Connection[Any]]:
        yield conn

    return _cm


class AiStore:
    def __init__(self, connect: Connect = write_connection) -> None:
        self._connect = connect

    # ── runs ────────────────────────────────────────────────────────────────
    def start(self, kind: str, *, model: str | None, at: datetime, detail: dict[str, Any] | None = None) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO analytics.ai_runs (kind, model, started_at, detail) VALUES (%s,%s,%s,%s) "
                        "RETURNING id", (kind, model, at, Json(detail or {})))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def progress(self, run_id: int, *, model: str | None, usage: Usage, tool_calls: int) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE analytics.ai_runs SET input_tokens = %s, output_tokens = %s, cost_usd = %s, "
                        "tool_calls = %s WHERE id = %s",
                        (usage.input_tokens, usage.output_tokens,
                         budget.cost(model, usage.input_tokens, usage.output_tokens), tool_calls, run_id))

    def finish(self, run_id: int, *, status: str, at: datetime, model: str | None, usage: Usage | None = None,
               tool_calls: int = 0, detail: dict[str, Any] | None = None, error: str | None = None) -> None:
        u = usage or Usage()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE analytics.ai_runs SET status = %s, finished_at = %s, input_tokens = %s, output_tokens = %s, "
                "cost_usd = %s, tool_calls = %s, detail = detail || %s::jsonb, error = %s WHERE id = %s",
                (status, at, u.input_tokens, u.output_tokens, budget.cost(model, u.input_tokens, u.output_tokens),
                 tool_calls, Json(detail or {}), None if error is None else error[:500], run_id))

    def spent(self, at: datetime) -> Decimal:
        with self._connect() as conn:
            return budget.spent_this_month(conn, at=at)

    def runs_since(self, kind: str, since: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM analytics.ai_runs WHERE kind = %s AND started_at >= %s "
                        "AND status <> 'not_configured'", (kind, since))
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def latest_run(self, kind: str, *, where: str = "", params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT * FROM analytics.ai_runs WHERE kind = %s {where} ORDER BY id DESC LIMIT 1",
                        (kind, *params))
            row = cur.fetchone()
        return None if row is None else dict(row)

    # ── what runs produce ───────────────────────────────────────────────────
    def claims(self, run_id: int, claims: list[Claim]) -> dict[str, int]:
        """Store accepted claims; returns claim ref -> id."""
        out: dict[str, int] = {}
        with self._connect() as conn, conn.cursor() as cur:
            for c in claims:
                published = _ts(c.source.published_at)
                retrieved = _ts(c.source.retrieved_at)
                assert retrieved is not None
                if published is not None and published > retrieved:
                    published = None  # a date in the future is not a publication date
                cur.execute(
                    "INSERT INTO analytics.ai_claims (run_id, fixture_id, team_id, claim, source_url, also_urls, "
                    "publisher, published_at, retrieved_at, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING id",
                    (run_id, c.fixture_id, c.team_id, c.claim, c.source.url, [s.url for s in c.also],
                     c.source.publisher, published, retrieved, c.grade.name))
                row = cur.fetchone()
                assert row is not None
                out[c.ref] = int(row[0])
        return out

    def report(self, run_id: int, *, day: date, source: str, markdown: str, claims: int, at: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO analytics.ai_reports (run_id, day, source, markdown, claims, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (run_id, day, source, markdown, claims, at))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def hypotheses(self, items: list[dict[str, Any]], *, run_id: int, at: datetime) -> list[int]:
        """Research proposals from a run, for the owner to accept or reject (``fbi.research.evolution``)."""
        from fbi.research.evolution import propose

        out: list[int] = []
        with self._connect() as conn:
            for h in items:
                hid = propose(conn, title=h["title"], hypothesis=h["hypothesis"], rationale=h["rationale"],
                              evidence={"ai_run": run_id}, proposed_by="ai", at=at)
                if hid is not None:
                    out.append(hid)
        return out

    def flags(self, run_id: int, flags: list[FlagRow], *, at: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            for f in flags:
                cur.execute(
                    "INSERT INTO analytics.ai_pick_flags (run_id, set_id, rank, fixture_id, code, severity, note, "
                    "claim_ids, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (run_id, f.set_id, f.rank, f.fixture_id, f.code, f.severity, f.note[:500], list(f.claim_ids), at))
        return len(flags)


def _ts(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None

"""What the tests of migration 0111 (the tables of the agents) share: the rows they put in, and the way they show that a rule holds.

``refuses`` is the one that matters: a statement the database must refuse is run inside a savepoint and the refusal has to be the one that was
expected - the constraint named, or the words of the trigger - so that a typo, a missing column or any other error fails the test instead of
passing it for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
HASH = "a" * 64
OTHER = "b" * 64
# ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def key(n: int) -> str:
    return f"{n:064x}"


def insert(db: psycopg.Connection[Any], table: str, values: dict[str, Any]) -> int:
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return int(scalar(db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks}) RETURNING id", list(values.values()))))


def update(db: psycopg.Connection[Any], table: str, row_id: int, **values: Any) -> None:
    sets = ", ".join(f"{column} = %s" for column in values)
    db.execute(f"UPDATE {table} SET {sets} WHERE id = %s", [*values.values(), row_id])


def columns_of(db: psycopg.Connection[Any], table: str) -> list[str]:
    schema, name = table.split(".")
    rows = db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                      "ORDER BY ordinal_position", (schema, name)).fetchall()
    return [r[0] for r in rows]


@contextmanager
def refuses(db: psycopg.Connection[Any], error: type[psycopg.Error], *, constraint: str | None = None,
            saying: str | None = None) -> Iterator[None]:
    """The statements inside must be refused with ``error`` - by the constraint named, or with the words given - and leave the
    transaction usable (a savepoint). A refusal for any other reason fails the test with its real cause."""
    refusal: psycopg.Error | None = None
    try:
        with db.transaction(force_rollback=True):
            yield
    except psycopg.Error as exc:
        refusal = exc
    assert refusal is not None, "the database ACCEPTED it: the rule is gone"
    assert isinstance(refusal, error), f"refused, but by {type(refusal).__name__}: {refusal}"
    if constraint is not None:
        assert refusal.diag.constraint_name == constraint, f"refused by {refusal.diag.constraint_name!r}, not by {constraint!r}: {refusal}"
    if saying is not None:
        assert saying in str(refusal), f"refused, but not for {saying!r}: {refusal}"


def task_values(seed: Seed, n: int = 1, **over: Any) -> dict[str, Any]:
    k = key(n)
    values: dict[str, Any] = {
        "idem_key": k, "custom_id": k[:48], "workspace": "production", "agent": "council", "agent_version": "council-v1",
        "prompt_version": "council-prompt-v1", "schema_version": "cd-v1", "model": "claude-sonnet-5-5", "effort": "low",
        "input_version": "package-v1", "input_hash": HASH, "pass_kind": "first", "fixture_id": seed.fixture_id,
        "candidates": ["c1", "c2"], "run_kind": "live", "task_kind": "council", "reason": "first pass of the match",
        "router_version": "router-v1", "route": Jsonb({"level": "sonnet"}), "package_hash": HASH, "priority": 100,
        "est_cost_usd": Decimal("0.031"), "created_at": NOW, "not_before": NOW, "deadline_at": NOW + timedelta(hours=6),
    }
    return values | over


def run_values(seed: Seed, n: int = 1, **over: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "run_kind": "live", "reason": "first pass of the match", "task_kind": "council", "pass_kind": "first",
        "fixture_id": seed.fixture_id, "candidates": ["c1", "c2"], "started_at": NOW, "finished_at": NOW + timedelta(seconds=3),
        "known_at": NOW - timedelta(hours=1), "model": "claude-sonnet-5-5", "effort": "low", "agent": "council",
        "agent_version": "council-v1", "prompt_version": "council-prompt-v1", "schema_version": "cd-v1", "router_version": "router-v1",
        "package_hash": HASH, "slice_hash": HASH, "idem_key": key(n), "attempt": 1, "output": Jsonb({"verdict": "NO_PICK"}),
        "verdict": "NO_PICK", "input_tokens": 1200, "output_tokens": 300, "cached_tokens": 800, "cache_write_tokens": 0,
        "cost_usd": Decimal("0.0123"), "status": "ok",
    }
    return values | over


UNPAID: dict[str, Any] = {
    "status": "timeout", "model": None, "output": None, "verdict": None, "input_tokens": None, "output_tokens": None,
    "cached_tokens": None, "cache_write_tokens": None, "cost_usd": Decimal(0), "error": "no answer within the time given",
}
INVALID: dict[str, Any] = {"status": "invalid", "output": None, "verdict": None, "error": "the answer did not fit the schema"}
ABSTAIN: dict[str, Any] = {"status": "abstain", "output": Jsonb({"abstain": True}), "verdict": "ABSTAIN"}


def match_values(seed: Seed, **over: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "fixture_id": seed.fixture_id, "run_kind": "live", "pass_kind": "first", "known_at": NOW - timedelta(hours=1), "created_at": NOW,
        "state_version": "ms-v1", "package_version": "mcp-v1", "package_hash": HASH, "packet_id": 17, "elapsed_ms": 420,
        "slices": Jsonb([{"name": "match", "hash": HASH, "tokens": 9000, "cap": 18000, "fits": True, "trimmed": False, "blocks": 12}]),
        "blocking": [], "flags": ["thin_market"],
    }
    return values | over


def shaped(state: str, run_id: int) -> dict[str, Any]:
    """The fields a task in ``state`` must have for the table's own rules: its times, its attempts and, when it has ended, its run."""
    fields: dict[str, Any] = {"state": state}
    if state in ("queued", "running", "done", "failed"):
        fields["queued_at"] = NOW
    if state in ("running", "done", "failed"):
        fields |= {"started_at": NOW + timedelta(seconds=1), "attempts": 1}
    if state in ("done", "failed", "skipped", "expired"):
        fields |= {"finished_at": NOW + timedelta(seconds=5), "last_run_id": run_id}
    return fields

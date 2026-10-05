"""The evolution loop, read for the Admin Console; the owner's proposals and decisions written
through the AI layer's own connection (``fbi.analyst.db``) - nothing else."""

from __future__ import annotations

from datetime import datetime

from fbi.analyst.db import write_connection
from fbi.api.contracts.evolution import (
    EvolutionOverview,
    Hypothesis,
    HypothesisIn,
    LastRun,
    MemoryEntry,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.research import evolution
from fbi.research.loop import frozen, latest_v2, v2_due_reason

LOOP = [
    "A result (research V2, the daily audit, the prospective evaluation) is written to memory with its evidence.",
    "Where the evidence points somewhere, the system - or the AI, or the owner - proposes a hypothesis.",
    "Only the owner accepts or rejects it. Accepting queues an experiment in research; it changes no rule.",
    "The experiment runs in research and is judged by the same gate as every model (roles vs the market).",
    "Nothing reaches users without a passed gate AND an explicit promotion. A bad result never edits a rule.",
]

HYPOTHESES_SQL = """
SELECT h.id, h.proposed_by, h.title, h.hypothesis, h.rationale, h.evidence, h.status, h.experiment_ids, h.created_at,
       h.decided_at, u.email AS decided_by, h.decision_note
  FROM analytics.research_hypotheses h LEFT JOIN auth.users u ON u.id = h.decided_by
 ORDER BY (h.status = 'PROPOSED') DESC, h.created_at DESC, h.id DESC
 LIMIT 200
"""

MEMORY_SQL = """
SELECT m.id, m.topic, m.finding, m.evidence, m.source, m.created_at,
       (SELECT count(*) FROM analytics.research_memory x WHERE x.topic = m.topic) AS versions
  FROM analytics.research_memory m
 WHERE m.superseded_by IS NULL
 ORDER BY m.created_at DESC, m.id DESC
 LIMIT 200
"""


def overview(conn: Conn, *, at: datetime | None = None) -> Envelope[EvolutionOverview]:
    at = at or now()
    last = latest_v2(conn)
    due = v2_due_reason(conn, at=at)
    monitor = fetch_one(conn, "SELECT max(finished_at) AS at FROM raw.ingestion_runs WHERE job_type = "
                              "'research_monitor' AND status = 'completed'")
    return ok(EvolutionOverview(
        loop=LOOP, hypotheses=[Hypothesis.model_validate(r) for r in fetch_all(conn, HYPOTHESES_SQL)],
        memory=[MemoryEntry.model_validate(r) for r in fetch_all(conn, MEMORY_SQL)],
        last_monitor=monitor["at"] if monitor else None,
        last_v2=None if last is None else LastRun.model_validate(last), v2_due=None if due is None else due.text,
        research_frozen=frozen(), v2_due_code=None if due is None else due.code,
        v2_due_vars={} if due is None else due.vars))


def propose(body: HypothesisIn, *, at: datetime | None = None) -> int:
    with write_connection() as conn:
        hid = evolution.propose(conn, title=body.title, hypothesis=body.hypothesis, rationale=body.rationale,
                                evidence={}, proposed_by="owner", at=at or now())
    assert hid is not None
    return hid


def decide(hypothesis_id: int, *, accept: bool, user_id: int, note: str | None, at: datetime | None = None) -> str:
    try:
        with write_connection() as conn:
            return evolution.decide(conn, hypothesis_id, accept=accept, user_id=user_id, note=note,
                                    at=at or now())
    except evolution.DecisionError as exc:
        status = 404 if "no such" in str(exc) else 409
        raise ApiError(status, "not_found" if status == 404 else "conflict", str(exc)) from exc

"""The evolution loop, read for the Admin Console; the owner's proposals and decisions written
through the AI layer's own connection (``fbi.analyst.db``) - nothing else."""

from __future__ import annotations

from datetime import datetime

from fbi.analyst.db import write_connection
from fbi.api.cache import shared
from fbi.api.contracts.evolution import (
    CodeCounts,
    CodeFingerprint,
    CodeLedgerEntry,
    CodePromotionRow,
    CodePromotions,
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
from fbi.core.version import model_code_version
from fbi.research import evolution, promotions, trace
from fbi.research.loop import frozen, latest_v2, v2_due_reason

LOOP = [
    "OBSERVE: a result (research V2, the daily audit, the prospective evaluation, a match post-mortem) is observed.",
    "MEMORY: it is written to memory with its evidence, its sources and the version that produced it.",
    "HYPOTHESIS: where the evidence points somewhere, the system - or the AI, or the owner - proposes a hypothesis.",
    "ADMIN: only the owner rejects it, asks to investigate further, or approves an experiment. None of them "
    "changes a rule.",
    "EXPERIMENT and BACKTEST: an approved experiment runs in research, judged by the same gate as every model.",
    "SHADOW and MARKET: what passes its backtest is followed prospectively against the market before anyone sees it.",
    "EVALUATION: the result is judged against its gate and recorded with the hypothesis.",
    "PROMOTION: nothing reaches users without a passed gate AND the owner's explicit promotion. A bad result never "
    "edits a rule, and the AI never promotes anything.",
]

HYPOTHESES_SQL = """
SELECT h.id, h.proposed_by, h.title, h.hypothesis, h.rationale, h.evidence, h.status, h.experiment_ids, h.created_at,
       h.decided_at, u.email AS decided_by, h.decision_note, h.target, h.stage_history, h.outcome
  FROM analytics.research_hypotheses h LEFT JOIN auth.users u ON u.id = h.decided_by
 ORDER BY (h.status IN ('PROPOSED', 'INVESTIGATING')) DESC, h.created_at DESC, h.id DESC
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


CODE_CACHE_SECONDS = 300
"""The trace scans a month of predictions (about 4 s on the server): an answer is kept five minutes, the page never refreshes it by itself."""
CODE_TIMEOUT = "60s"
"""The API's own ten seconds are for the boards; this request may take longer, and only this one."""


@shared(CODE_CACHE_SECONDS)
def code_promotions(conn: Conn, *, days: int = trace.DEFAULT_DAYS, at: datetime | None = None) -> Envelope[CodePromotions]:
    """THE MODEL CODE AGAINST ITS PROMOTIONS (plan F12): every fingerprint of the model packages that production forecast with in the last
    ``days`` days, the decision that covers each and the count the plan's criterion is made of. Reading only: ``fbi.research.trace`` reads and
    nothing here writes, and the connection could not."""
    conn.execute(f"SET LOCAL statement_timeout = '{CODE_TIMEOUT}'")
    at = at or now()
    report = trace.trace(conn, now=at, days=days)
    recorded = trace.load_recorded(conn)
    used = {f["fingerprint"] for f in report["fingerprints"]}
    running = model_code_version()
    in_force = report["ledger_in_force"]
    fingerprints = [CodeFingerprint(
        fingerprint=f["fingerprint"], status=f["status"], appeared_at=f["appeared_at"], last_use=f["last_use"], in_force_now=f["in_force_now"],
        versions=f["versions"], models=f["models"], rows=f["rows"],
        promotion=None if f["promotion"] is None else CodePromotionRow(**f["promotion"])) for f in report["fingerprints"]]
    ledger = [CodeLedgerEntry(
        fingerprint=e.fingerprint, decided_at=e.decided_at, decided_by=e.decided_by, phase=e.phase, reason=e.reason, baseline=e.baseline,
        evidence=e.evidence, recorded=e.fingerprint in recorded, used=e.fingerprint in used) for e in promotions.LEDGER]
    return ok(CodePromotions(
        now=report["now"], since=report["since"], days=report["days"], running_code=running, ledger_in_force=in_force,
        ledger_since=report["ledger_since"], in_force_matches_running=in_force is not None and in_force == running,
        fingerprints=fingerprints, counts=CodeCounts(**report["counts"]), coverage=report["coverage"], ledger=ledger, other=report["other"]))


def propose(body: HypothesisIn, *, at: datetime | None = None) -> int:
    with write_connection() as conn:
        hid = evolution.propose(conn, title=body.title, hypothesis=body.hypothesis, rationale=body.rationale,
                                evidence={}, proposed_by="owner", at=at or now(), target=body.target)
    assert hid is not None
    return hid


def _refused(exc: evolution.DecisionError) -> ApiError:
    status = 404 if "no such" in str(exc) else 409
    return ApiError(status, "not_found" if status == 404 else "conflict", str(exc))


def decide(hypothesis_id: int, *, decision: str, user_id: int, note: str | None, at: datetime | None = None) -> str:
    try:
        with write_connection() as conn:
            return evolution.decide(conn, hypothesis_id, decision=decision, user_id=user_id, note=note,
                                    at=at or now())
    except evolution.DecisionError as exc:
        raise _refused(exc) from exc


def promote(hypothesis_id: int, *, user_id: int, note: str | None, at: datetime | None = None) -> str:
    """Records the owner's promotion of an experiment whose gate passed. It does not change production by
    itself: the change ships as its own versioned release (a model promotion, a rule's new version)."""
    try:
        with write_connection() as conn:
            return evolution.promote(conn, hypothesis_id, user_id=user_id, at=at or now(), note=note)
    except evolution.DecisionError as exc:
        raise _refused(exc) from exc

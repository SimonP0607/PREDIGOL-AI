"""How the agents of phase 5 reach the model: ONLY through the Message Batches API, ONLY in the LAB workspace, and only while the LAB has room.

The Post-Match Reviewer and the Learning Analyst never wait for an answer and nothing waits for them: the day's step records its tasks in the queue and
sends them in one batch; the answers are taken by the worker's poll (``ai_batch_poll``), which hands each one to the handler its module registered. A
task is not asked when the LAB has no key or no envelope (``fbi.ai.lab.blockers``), when the model the deployment configured for its tier is not the one
the router names for the task (it is the registry's pin: another model is another version), or when the estimate of its cost does not fit in what the
LAB may still spend today (``budget_v3.lab_day``). A failure of any of this costs the attribution nothing: it is computed by code before and without.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import psycopg

from fbi.ai import budget_v3, router
from fbi.ai.batch import BatchClient, BatchQueue, Task, estimate_cost
from fbi.ai.config import AiSettings, Tier
from fbi.ai.lab import blockers
from fbi.ai.usage import UsageLedger, with_effort

LEVEL_OF_TIER = {tier: level for level, tier in router.TIER_OF_LEVEL.items()}
"""bulk -> simple, analysis -> complex, final -> critical."""


@dataclass(slots=True)
class Submitted:
    """What one submission did: how many tasks were recorded and sent, and why the others were not."""

    tasks: int = 0
    queued: int = 0
    already: int = 0
    sent: int = 0
    estimate: Decimal = Decimal(0)
    stopped: str | None = None
    refused: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tasks": self.tasks, "queued": self.queued, "already": self.already, "sent": self.sent,
                               "estimate_usd": str(self.estimate.quantize(Decimal("0.0001")))}
        if self.stopped:
            out["stopped"] = self.stopped
        if self.refused:
            out["refused"] = dict(self.refused)
        if self.blockers:
            out["blockers"] = list(self.blockers)
        return out


def model_matches_router(settings: AiSettings, tier: Tier) -> bool:
    """Whether the LAB's model for a tier is the one the router names for that tier's level."""
    tm = settings.tier(tier, lab=True)
    level = LEVEL_OF_TIER.get(tier)
    return tm is not None and level is not None and tm.model == router.MODELS[level]


def submit(conn: psycopg.Connection[Any], settings: AiSettings, tasks: Sequence[Task], *, at: datetime, ledger: UsageLedger | None = None,
           client: BatchClient | None = None, transport: httpx.BaseTransport | None = None) -> Submitted:
    """Record the tasks in the queue and send them: in order, until the LAB has no room for the next one. Every task must be a LAB task. Commits when it
    sends (the queue does); records nothing when there is nothing to send."""
    out = Submitted(tasks=len(tasks))
    if not tasks:
        return out
    tiers: list[Tier] = sorted({t.tier for t in tasks})
    stop = blockers(settings, tiers)
    if stop:
        out.blockers = stop
        out.stopped = "lab_blocked"
        return out
    room = budget_v3.lab_day(conn, at=at, settings=settings)
    if not room.can_spend:
        out.stopped = f"lab_day:{room.reason}"
        return out
    queue = BatchQueue(conn, settings, at=at, ledger=ledger, client=client, transport=transport)
    left = room.remaining
    for task in tasks:
        if not task.lab:
            raise ValueError("an agent of phase 5 asks in the LAB only")
        if not model_matches_router(settings, task.tier):
            out.refused["model_not_configured"] = out.refused.get("model_not_configured", 0) + 1
            continue
        tm = settings.tier(task.tier, lab=True)
        assert tm is not None
        guess = estimate_cost(tm.model, with_effort(task.request, task.tier), typical_output=task.typical_output, at=at)
        if guess > left:
            out.stopped = "lab_room"
            break
        admitted = queue.add(task)
        if admitted.status == "queued":
            out.queued += 1
            out.estimate += admitted.est_cost
            left -= admitted.est_cost
        elif admitted.pending:
            out.already += 1
        else:
            out.refused[admitted.reason or "refused"] = out.refused.get(admitted.reason or "refused", 0) + 1
    report = queue.flush()
    out.sent = report.sent
    if report.error:
        out.stopped = report.error
    return out

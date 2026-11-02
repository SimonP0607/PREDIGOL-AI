"""The evolution loop in the Admin Console: proposals for the owner, and what was learned."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

HypothesisStatus = Literal["PROPOSED", "INVESTIGATING", "ACCEPTED", "REJECTED", "RUNNING", "SHADOW", "DONE",
                           "PROMOTED"]
"""PROPOSED -> (INVESTIGATING) -> ACCEPTED -> RUNNING (backtest) -> SHADOW -> DONE -> PROMOTED, or REJECTED.
Only the owner moves a hypothesis out of PROPOSED/INVESTIGATING and into PROMOTED."""
Target = Literal["models", "backtesting", "analytics", "features", "rankings", "pick_engine", "decision_rules", "data",
                 "ai", "other"]


CodeStatus = Literal["BASELINE", "PROMOTED", "AFTER_USE", "PENDING_SYNC", "UNTRACED", "PRE_LEDGER"]
"""What covers one fingerprint of the model code (``fbi.research.trace``): the baseline recorded after the fact, a decision dated before the code
first ran, a decision dated after it, an entry not yet copied to the database, nothing at all, or a change older than the ledger (listed, not counted)."""


class CodePromotionRow(Contract):
    """The CHAMPION row of ``intel.promotions`` that covers a fingerprint."""

    id: int
    decided_by: str
    decided_at: datetime
    reason: str
    evidence: dict[str, Any] = Field(description="What the decision rested on: the hypothesis, the experiments, the gate, the release.")


class CodeFingerprint(Contract):
    """One fingerprint of the model packages that production forecast with in the window, and what covers it."""

    fingerprint: str = Field(description="``mc`` and ten hex digits, as the model versions carry it; ``legacy`` for the versions keyed by a commit.")
    status: CodeStatus
    appeared_at: datetime = Field(description="When its first model version came into being.")
    last_use: datetime
    in_force_now: bool = Field(description="Used in the last two days. It is NOT 'the code in force': see ``CodePromotions.running_code``.")
    versions: int
    models: list[str]
    rows: dict[str, int] = Field(description="What it produced in the window, by source: predictions, forecasts, decisions.")
    promotion: CodePromotionRow | None


class CodeCounts(Contract):
    fingerprints: int
    counted: int = Field(description="The changes since the ledger began: the fingerprints that are not PRE_LEDGER.")
    traced: int = Field(description="Of those, the ones with a promotion on record (BASELINE, PROMOTED, AFTER_USE).")
    untraced: int
    pending_sync: int
    after_use: int
    pre_ledger: int


class CodeLedgerEntry(Contract):
    """One decision of ``fbi.research.promotions.LEDGER`` - the ledger carried by the code this server runs."""

    fingerprint: str
    decided_at: datetime
    decided_by: str
    phase: str
    reason: str
    baseline: bool
    evidence: dict[str, Any]
    recorded: bool = Field(description="``intel.promotions`` has its CHAMPION row.")
    used: bool = Field(description="Production forecast with it in the window.")


class CodePromotions(Contract):
    """The model code against its promotions (plan F12): every fingerprint that forecast in production, and the decision that covers each."""

    now: datetime
    since: datetime
    days: int
    running_code: str = Field(description="The fingerprint of the model code this server runs (``mc`` + ten hex digits).")
    ledger_in_force: str | None = Field(description="The last entry of the ledger: the code the ledger says production forecasts with.")
    ledger_since: datetime | None
    in_force_matches_running: bool = Field(description="The code running is the one the ledger has in force.")
    fingerprints: list[CodeFingerprint]
    counts: CodeCounts
    coverage: float | None = Field(description="``traced / counted`` as a fraction of 1; null when nothing changed since the ledger began.")
    ledger: list[CodeLedgerEntry]
    other: dict[str, int] = Field(description="The promotions of the other kinds of change in the same window, for context.")


class Hypothesis(Contract):
    id: int
    proposed_by: Literal["ai", "owner", "system"]
    title: str
    hypothesis: str
    rationale: str
    evidence: dict[str, Any]
    status: HypothesisStatus
    experiment_ids: list[int]
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None = Field(description="The deciding account's email.")
    decision_note: str | None
    target: Target = Field(default="other", description="What the hypothesis would change if ever promoted.")
    stage_history: list[dict[str, Any]] = Field(default_factory=list, description="Every move, who and when.")
    outcome: dict[str, Any] | None = Field(default=None, description="The experiment's judged result "
                                           "(gate_passed decides whether it can be promoted).")


class MemoryEntry(Contract):
    id: int
    topic: str
    finding: str
    evidence: dict[str, Any]
    source: Literal["research_v2", "prospective", "audit", "owner"]
    created_at: datetime
    versions: int = Field(description="How many findings this topic has had, this one included.")


class LastRun(Contract):
    name: str
    code_version: str | None
    model_code: str | None = Field(default=None, description="Fingerprint of the model code the run used; null "
                                   "for runs stored before 5 Oct 2026.")
    dataset_version: str | None = Field(default=None, description="The MODEL_READY dataset version it learned "
                                        "from; null for runs stored before dataset versions existed.")
    finished_at: datetime | None


class EvolutionOverview(Contract):
    loop: list[str]
    hypotheses: list[Hypothesis]
    memory: list[MemoryEntry] = Field(description="Each topic's current finding; earlier ones are kept, superseded.")
    last_monitor: datetime | None
    last_v2: LastRun | None
    v2_due: str | None = Field(description="Why the weekly research-V2 job would run now, or null.")
    research_frozen: str | None = Field(default=None, description="Why research is frozen (no run stores a model), "
                                        "or null. While frozen, v2_due says what WOULD make a run due.")
    v2_due_code: str | None = Field(default=None, description="Stable name of the v2_due reason (no_run, new_dataset, "
                                    "unknown_model_code, model_code_changed, four_weeks), for the reader's language.")
    v2_due_vars: dict[str, str] = Field(default_factory=dict, description="The values the v2_due reason names.")


class HypothesisIn(Contract):
    title: str = Field(min_length=5, max_length=160)
    hypothesis: str = Field(min_length=5, max_length=600)
    rationale: str = Field(min_length=5, max_length=1000)
    target: Target = "other"


class DecisionIn(Contract):
    decision: Literal["reject", "investigate", "approve_experiment", "accept"] = Field(
        description="RECHAZAR, INVESTIGAR or APROBAR EXPERIMENTO (``accept`` is its earlier name). None of them "
                    "changes a rule, a model or a pick.")
    note: str | None = Field(default=None, max_length=500)


class PromoteIn(Contract):
    note: str | None = Field(default=None, max_length=500)
    confirm: Literal["PROMOTE"] = Field(description="Typed by the owner: promotion is never a single click.")

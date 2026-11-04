"""The shadow of phase 3, for the Admin Console (plan IA, sections 22-24 and 33): the seven arms side by side, the contradictions ``contra-v1``
found, the runs of the agents and the file of one match. Reading only: nothing here calls a model, creates a task or changes a pick.

What these shapes carry is what the orchestrator wrote - counts, codes, the server's numbers and ids. A model's free text is not in any of them
(``aa-v1`` and ``cd-v1`` have no field for one), an address is not either, and the plan's gates are not decided here: the "enough data" flags are
counts and days against the thresholds of ``ai-gate-v2``, never a verdict."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.ai_layer import CycleRow
from fbi.api.contracts.common import Contract

Decision = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
Treatment = Literal["kept", "lowered", "abstained", "none"]
"""What an engine's Council did with a candidate a contradiction touches, read from its verdict: ``kept`` (APPROVE), ``lowered`` (DOWNGRADE or
REJECT), ``abstained`` (ABSTAIN) or ``none`` (the engine has no verdict for it: it did not run, was paused, or answered nothing that stands). The
Council has no field to say it saw a contradiction, so "ignored" is not a thing the data can tell from "kept"."""


# ── the switches ───────────────────────────────────────────────────────────────────────────────────────────────────

class SwitchWord(Contract):
    name: str = Field(description="The owner's word, as it is written in app.env: FBI_AI_ENGINES, FBI_AI_SHADOW_SAMPLE, FBI_AI_AGENTS.")
    value: str
    on: bool = Field(description="This word, by itself, lets the shadow run.")


class ShadowSwitches(Contract):
    """Whether the Orchestrator may run, and the words that decide it (``AiSettings.orchestrate``): the three words and a layer that is not off."""

    mode: str
    orchestrate: bool
    words: list[SwitchWord]
    engines: list[str]
    shadow_engines: list[str]
    shadow_sample: str
    agents: list[str]


# ── the arms ───────────────────────────────────────────────────────────────────────────────────────────────────────

class Decisions(Contract):
    approved: int = 0
    downgraded: int = 0
    rejected: int = 0
    abstained: int = 0


class ArmSettled(Contract):
    """What the latest stored report of ``fbi.ai.shadow`` (``ai.shadow_reports``) says of an engine over the selections that have settled: the counts
    and the measures it computed, and no verdict. ``None`` for an engine nothing has settled for."""

    report_at: datetime
    window_from: datetime | None = None
    window_to: datetime | None = None
    selections: int = Field(description="Settled selections the engine reviewed before kick-off (the report's ``model`` arm).")
    kept: int
    rejected: int
    clv_kept: float | None = None
    clv_rejected: float | None = None
    roi_kept: float | None = None
    roi_rejected: float | None = None


class ArmRow(Contract):
    arm: Literal["model", "rules", "gap", "llm", "council_solo", "ma-v1", "ma-v1-h"]
    engine: str | None = Field(default=None, description="The engine of ``ai.pick_reviews`` that is the arm; none for the two arms that are a rule.")
    kind: Literal["derived", "production", "shadow"] = Field(
        description="``derived``: computed from the rules reviewer's rows by the plan's definition, not a review; ``production``: today's reviewer; "
                    "``shadow``: an engine of the Orchestrator.")
    scope: Literal["lab", "production"] | None = Field(default=None, description="Whose money the arm's calls are (the ledger's scope).")
    reviews: int = Field(description="Reviews written in the window: one per selection and pass.")
    selections: int = Field(description="Distinct selections (match, market, selection, line) of those reviews.")
    decisions: Decisions | None = None
    statuses: dict[str, int] = Field(default_factory=dict, description="Reviews by status: ok, fallback, invalid_output, failed, over_budget.")
    invalid: int = Field(default=0, description="Reviews whose output did not validate (status ``invalid_output``).")
    on_sample: int = Field(
        default=0, description="Reviews of the selections the shadow also reviewed: the basis the arms are compared on.")
    selections_on_sample: int = 0
    decisions_on_sample: Decisions | None = None
    cost_usd: Decimal | None = Field(default=None, description="What the arm's reviews cost, as the orchestrator split it between its candidates.")
    ledger_usd: Decimal | None = Field(default=None, description="The calls the arm stands on, summed from the ledger (scope lab), shared calls included.")
    calls: int = Field(default=0, description="Distinct ledger rows (calls) behind the arm's reviews.")
    latency_p95_ms: int | None = Field(default=None, description="95th percentile of the latency of those calls, when the ledger stored one.")
    latency_n: int = 0
    paused: dict[str, int] = Field(default_factory=dict, description="Passes the arm did not run, by pause reason (runtime.PAUSE_REASONS).")
    not_answered: dict[str, int] = Field(default_factory=dict, description="Passes the arm ran without a verdict, by the code that says why.")
    settled: ArmSettled | None = None


class Assignments(Contract):
    experiment: str
    arms_version: str
    assigned: int
    sampled: int
    unsampled: int
    council_solo: int
    sampled_share: float | None = Field(default=None, description="``sampled / assigned``: what the hash gave, not what the owner asked.")
    by_share: list[dict[str, Any]] = Field(
        default_factory=list, description="The share in force when each match was assigned: shares are nested, so a later one only adds matches.")
    first_assigned_at: datetime | None = None
    last_assigned_at: datetime | None = None


class Enough(Contract):
    """The plan's thresholds for a comparison (``ai-gate-v2``, gate C): counts and days, and whether each was reached. NOT a verdict: reaching them
    says there is enough to look, never that anything passed."""

    days: int = Field(description="Bogotá days with at least one shadow review.")
    days_need: int
    days_reached: bool
    since: datetime | None = Field(default=None, description="The first shadow review ever written.")
    days_running: int = Field(description="Days since the first shadow review.")
    selections: int = Field(description="Selections reviewed by the multi-agent (ma-v1) AND by today's AI (llm).")
    selections_need: int
    selections_reached: bool


class LabSpend(Contract):
    window_usd: Decimal = Field(description="Everything the LAB spent in the window (ledger scope lab).")
    shadow_usd: Decimal = Field(description="Of it, the calls behind the shadow's reviews, each counted once.")
    calls: int


class ShadowArms(Contract):
    days: int
    since: datetime
    switches: ShadowSwitches
    assignments: Assignments
    arms: list[ArmRow]
    enough: Enough
    lab: LabSpend
    last_cycle: CycleRow | None = None


# ── the contradictions ─────────────────────────────────────────────────────────────────────────────────────────────

class ContraCount(Contract):
    code: str
    n: int = Field(description="Contradictions of this code written in the window.")
    passes: int = Field(description="Passes (a match at a moment) with at least one.")
    matches: int
    confirmed: int = Field(description="Of them, those the server marks as resting on CONFIRMED evidence (C01 and C02).")
    treatment: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Per engine: how many (contradiction, candidate) pairs ended kept, lowered, abstained or none.")


class ContraCandidate(Contract):
    key: str
    market: str | None = None
    selection: str | None = None
    line: str | None = None


class ContraItem(Contract):
    code: str
    fixture_id: int
    match: str | None = None
    kickoff_at: datetime | None = None
    pass_kind: str
    known_at: datetime
    created_at: datetime
    subject: str
    candidates: list[ContraCandidate]
    refs: list[str]
    confirmed: bool = False
    official_lineup: bool = False
    starters_out: int = 0
    gap: str | None = None
    requires: str | None = None
    treatment: dict[str, dict[str, Treatment]] = Field(
        default_factory=dict, description="Per engine, per touched candidate: what the Council did with it.")


class Contradictions(Contract):
    days: int
    since: datetime
    switches: ShadowSwitches
    passes: int = Field(description="Shadow states written in the window.")
    with_contradictions: int
    total: int
    counts: list[ContraCount]
    recent: list[ContraItem]


# ── the runs of the agents ─────────────────────────────────────────────────────────────────────────────────────────

class AgentRunItem(Contract):
    id: int
    run_kind: str
    started_at: datetime
    fixture_id: int | None = None
    match: str | None = None
    pass_kind: str
    agent: str
    agent_version: str
    task_kind: str
    model: str | None = None
    effort: str | None = None
    status: str
    verdict: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: Decimal
    latency_ms: int | None = None
    escalation: str | None = Field(default=None, description="The rule of ``router-v1`` (E1-E7) that sent the task to Opus, when one did.")
    fired: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, description="The code the run ended with, cut: never a model's text.")
    idem: str
    workspace: str | None = None
    parent_run_id: int | None = None


class OpusDay(Contract):
    day: str
    calls: int = Field(description="Paid Opus calls of the shadow on this Bogotá day (a call that served both arms counts once).")
    cap: int = Field(description="``router-v1``: the shadow's cap of Opus calls per day.")
    remaining: int
    skipped: int = Field(description="Escalation tasks of the day that were not made.")
    cost_usd: Decimal


class AgentRuns(Contract):
    day: str
    switches: ShadowSwitches
    opus: OpusDay
    total: int
    cost_usd: Decimal
    by_status: dict[str, int]
    runs: list[AgentRunItem]


# ── the file of a match ────────────────────────────────────────────────────────────────────────────────────────────

class FileAssignment(Contract):
    experiment: str
    bucket: int
    sampled: bool
    council_solo: bool
    share: str
    assigned_at: datetime
    engines: list[str] = Field(description="The shadow engines the match is assigned to (what ``runnable`` could run if the owner names them).")


class FilePass(Contract):
    id: int
    pass_kind: str
    known_at: datetime
    created_at: datetime
    packet_id: int | None = None
    status: str = Field(description="``ran``, or ``not_run`` when no model could be asked at all.")
    reason: str | None = None
    elapsed_ms: int | None = None


class FileCandidate(Contract):
    key: str | None = Field(default=None, description="c1..c12: the name the server gave the selection. None for one left out.")
    family: str | None = None
    market: str
    selection: str
    line: str
    odds: str | None = None
    p_model: str | None = None
    p_market: str | None = None
    edge: str | None = None
    ev: str | None = None
    left_out: str | None = Field(default=None, description="Why a selection production reviewed is not one the agents read.")


class Cell(Contract):
    """One engine's verdict on one candidate."""

    engine: str
    decision: Decision | None = None
    confidence: str | None = None
    level: str | None = Field(default=None, description="The Council's confidence word (LOW, MEDIUM, HIGH), when the review carries it.")
    status: str | None = None
    model: str | None = None
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    stances: dict[str, str] = Field(default_factory=dict, description="The Match Agent's stance on it, by assessment (match_context, match_evaluation).")
    escalation: dict[str, Any] | None = None
    reason: str | None = None
    cost_usd: Decimal | None = None
    review_id: int | None = None


class FileVerdicts(Contract):
    candidate: str
    cells: list[Cell]


class FileArm(Contract):
    engine: str
    status: str | None = None
    reason: str | None = None
    paused: list[str] = Field(default_factory=list)
    escalated: dict[str, str] = Field(default_factory=dict)
    escalation_skipped: dict[str, str] = Field(default_factory=dict)
    view: dict[str, Any] | None = None


class FileSignal(Contract):
    code: str
    direction: str
    strength: str
    refs: list[str]


class FileStance(Contract):
    candidate: str
    stance: str
    drivers: list[str]
    risks: list[str]
    refs: list[str]


class FileAssessment(Contract):
    """The Match Agent's answer in codes: ``aa-v1`` has no field for a sentence, and every value here was checked against its closed vocabulary."""

    label: str
    mode: str
    model: str | None = None
    status: str
    quality: str | None = None
    signals: list[FileSignal] = Field(default_factory=list)
    candidates: list[FileStance] = Field(default_factory=list)


class FileContradiction(Contract):
    code: str
    subject: str
    candidates: list[str]
    refs: list[str]
    confirmed: bool = False
    detail: dict[str, str] = Field(default_factory=dict)


class ShadowFile(Contract):
    fixture_id: int
    match: str | None = None
    kickoff_at: datetime | None = None
    competition: str | None = None
    switches: ShadowSwitches
    assignment: FileAssignment | None = None
    passes: list[FilePass]
    selected: FilePass | None = None
    candidates: list[FileCandidate] = Field(default_factory=list)
    assessments: list[FileAssessment] = Field(default_factory=list)
    contradictions: list[FileContradiction] = Field(default_factory=list)
    arms: list[FileArm] = Field(default_factory=list)
    verdicts: list[FileVerdicts] = Field(default_factory=list)
    evidence_ids: list[int] = Field(default_factory=list)
    calls: list[AgentRunItem] = Field(default_factory=list)
    cost_usd: Decimal = Decimal(0)

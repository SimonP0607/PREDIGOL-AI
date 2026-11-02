"""The agents of PrediGol Intelligence, for the Admin Console (plan IA, phase 1): the registry as the code has it, the engine each family of
markets reads, what the package job wrote about the matches, the Orchestrator's queue and the audit of what an agent may know. Reading only:
nothing here calls a model, creates a task or changes a pick."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.ai_layer import CycleRow
from fbi.api.contracts.common import Contract


class AgentTaskView(Contract):
    task: str
    prompt_version: str
    schema_version: str | None = None
    model: str | None = Field(default=None, description="The model the task is registered with (the agents of the plan pin one).")
    tier: str | None = Field(default=None, description="The tier of the old route; the model is the deployment's setting.")
    effort: str


class AgentView(Contract):
    """One line of the registry. ``status`` is ``built`` (the code has it), ``planned`` (a phase of the plan builds it) or ``postponed`` (it has
    no code until its gate). Only a built agent has a version in force, a fingerprint and ``in_sync``."""

    agent: str
    status: Literal["built", "planned", "postponed"]
    purpose: str
    contract: str | None = None
    reads: str | None = None
    version: str | None = None
    fingerprint: str | None = None
    born_as: str | None = None
    baseline: bool | None = None
    registered_at: datetime | None = None
    in_sync: bool | None = Field(default=None, description="The fingerprint of the code that runs equals the one the ledger holds.")
    retire_phase: int | None = None
    next_version: str | None = None
    next_phase: int | None = None
    phase: int | None = None
    replaces: str | None = None
    gate: str | None = None
    history: list[str] = Field(default_factory=list)
    tasks: list[AgentTaskView] = Field(default_factory=list)


class RegistryProblem(Contract):
    code: str
    subject: str
    text: str


class FamilyEngine(Contract):
    """Which engine a family of markets reads: the newest row of ``intel.promotions`` for the family decides; none means the language model of
    today (``llm``)."""

    family: str
    engine: Literal["llm", "agent"]
    promotion: str | None = Field(default=None, description="The model_name of the champion row: agent@version[+upstream version...].")
    agent: str | None = None
    version: str | None = None
    upstream: list[str] = Field(default_factory=list)
    since: datetime | None = None
    promotion_id: int | None = None


class PromotionRow(Contract):
    id: int
    at: datetime
    family: str | None
    promotion: str | None
    from_role: str | None
    to_role: str
    decided_by: Literal["owner", "system"]
    gate_version: str
    reason: str


class SliceStat(Contract):
    """The size of one slice of ``mcp-v1`` over the window, in real tokens, against its cap."""

    name: str
    states: int
    tokens_p50: int
    tokens_p95: int
    tokens_max: int
    cap: int
    trimmed: int = Field(description="States where something was cut to fit the cap.")
    over_cap: int = Field(description="States that still do not fit: a slice an agent would refuse.")


class Timing(Contract):
    p50: int | None = None
    p95: int | None = None
    max: int | None = None


class PackageDay(Contract):
    day: date = Field(description="A Bogotá day.")
    states: int
    matches: int
    blocked: int
    flagged: int


class PackageCycles(Contract):
    """The runs of the package job in the window (``ai.cycles``, kind ``package``). A pass that refuses is tried again at every run, so the
    count of refusals is the last run's and never a sum."""

    total: int
    ok: int
    partial: int
    failed: int
    running: int
    last: CycleRow | None = None


class PackageStats(Contract):
    days: int
    since: datetime
    states: int
    matches: int
    by_pass: dict[str, int]
    blocked: int = Field(description="States whose package carries something that blocks an agent (a class of competition or a quarantined validation).")
    flagged: int = Field(description="States where provider text read like an instruction and was marked.")
    slices: list[SliceStat]
    build_ms: Timing
    per_day: list[PackageDay]
    cycles: PackageCycles
    rule: dict[str, Any] = Field(default_factory=dict, description="The constants of the job: state and package versions, window, limit.")


class QueueStats(Contract):
    """The Orchestrator's tables. Empty in phase 1: nothing creates a task yet."""

    days: int
    tasks: dict[str, int] = Field(description="Tasks created in the window, by state (every state is present).")
    runs: dict[str, int] = Field(description="Attempts started in the window, by status (every status is present).")
    open: int = Field(description="Tasks planned, queued or running now, whatever their age.")
    reserved_usd: Decimal = Field(description="What the tasks queued or running have reserved of the budget.")


class AuditDay(Contract):
    day: date
    checked_at: datetime
    version: str
    n_checked: int
    n_violations: int
    examples: list[Any] = Field(default_factory=list)


class AuditRule(Contract):
    """One rule of the nightly leakage audit that concerns the agents: its latest verdict per day over the window."""

    rule: str
    days: list[AuditDay]
    days_audited: int
    checked: int
    violations: int


class AgentsOverview(Contract):
    registry: list[AgentView]
    problems: list[RegistryProblem]
    families: list[FamilyEngine]
    decisions: list[PromotionRow]
    package: PackageStats
    queue: QueueStats
    audit: list[AuditRule]
    settings: dict[str, Any]


class StateSlice(Contract):
    name: str
    hash: str
    tokens: int
    cap: int
    fits: bool
    trimmed: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)


class MatchStateRow(Contract):
    id: int
    fixture_id: int
    run_kind: str
    pass_kind: str
    known_at: datetime
    created_at: datetime
    state_version: str
    package_version: str | None
    package_hash: str | None
    packet_id: int | None
    elapsed_ms: int | None
    slices: list[StateSlice]
    blocking: list[str]
    flags: list[str]
    code: str | None = Field(default=None, description="The fingerprint of the model code the package was derived with.")
    agents: int = Field(description="Agents foreseen, run, failed or waiting for this state.")
    contradictions: int
    candidates: int
    risks: int
    final: bool = Field(description="A verdict of the Council was written into the state.")


class AgentTaskRow(Contract):
    id: int
    agent: str
    agent_version: str
    task_kind: str
    pass_kind: str
    state: str
    run_kind: str
    priority: int
    est_cost_usd: Decimal
    attempts: int
    reason: str
    created_at: datetime
    deadline_at: datetime


class AgentRunRow(Contract):
    id: int
    agent: str
    agent_version: str
    task_kind: str
    pass_kind: str
    run_kind: str
    status: str
    model: str | None
    verdict: str | None
    started_at: datetime
    finished_at: datetime
    cost_usd: Decimal
    reason: str


class MatchState(Contract):
    fixture_id: int
    current: MatchStateRow | None = Field(default=None, description="The newest live state: what ai.match_state says.")
    history: list[MatchStateRow]
    tasks: list[AgentTaskRow]
    runs: list[AgentRunRow]

"""C-11, the Intelligence console (AD-J08, IA-079): one private answer with what the owner checks before anything else.

``GET /api/v1/admin/intelligence/console`` (``require_admin``; no public projection - ``PRIVATE_ONLY``). Six blocks:

* ``shadow`` - «nada sale de la sombra»: the real state of ``FBI_PICKS_SOURCE`` and ``FBI_AI_MODE`` (with whether the AI's veto is in force),
  the selections published to readers, and every switch of Intelligence and of the readers' Intelligence screens, as the API process reads them
  and, where the worker keeps it, as the worker last recorded it. Read only: ``changeable_here`` is always false and no route of the console
  changes a switch.
* ``capabilities`` - the registry of capabilities (AD-003, IA-056): each one with one of its four states, its recorded safety and validation
  verdicts (the validation with its sample) and the newest rows of the gates it answers to.
* ``costs`` - each envelope of decision 12 and each new capability's cap against what it spent this month, and the joint ceiling (AD-A06, IA-058).
* ``security`` - the newest battery row, the newest leakage audit, the panel of the gates with their real verdict (IA-050; Gate B NO EVALUADO only
  with the owner's closure on file, AD-001) and whether the database's schema is the code's.
* ``protocols`` (1.1.0, IA-143) - every preregistered protocol that can be signed (the LAB ones and the chronicle's own), with its fingerprint
  of now and whether the owner's signature of THAT fingerprint is on file (``ai.protocol_signatures``). A signature turns nothing on.
* ``news_engine`` and ``alert_queue`` - absent with their reason until AD-G01 and AD-D08 exist.

A block the server could not read this time is a ``ReadFailure`` (the error's class, never its message): one table that is missing does not
blank the rest of the console. The words are the system's own (the gates', the registry's); nothing here decides, records or switches anything.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
)
from fbi.api.contracts.intelligence.vocab import CapabilityState

SWITCH_PATTERN: Final = r"^FBI_[A-Z0-9_]+$"
WORD_PATTERN: Final = r"^[a-z0-9][a-z0-9_,.-]*$"
ERROR_PATTERN: Final = r"^[A-Za-z][A-Za-z0-9_]*$"
USD_PATTERN: Final = r"^-?\d+(\.\d+)?$"

SafetyWord = Literal["PASA", "NO PASA", "PENDIENTE POR ACCIONES MANUALES", "PENDIENTE POR DEPENDENCIAS"]
"""The registry's safety words (``SAFETY`` of the registry of capabilities, IA-056)."""
ValidationWord = Literal["VALIDADO", "NO VALIDADO", "INSUFICIENTE", "PENDIENTE POR ACCIONES MANUALES", "PENDIENTE POR DEPENDENCIAS"]
"""The registry's validation words (``VALIDATION`` of the registry of capabilities, IA-056)."""
GateWord = Literal["PASA", "NO PASA"]
"""What the newest row of a gate of ``ai.feature_gates`` says."""
GateStatus = Literal["PASA", "NO PASA", "NO EVALUADO", "RECHAZA", "PENDIENTE POR ACCIONES MANUALES", "PENDIENTE POR TIEMPO REAL",
                     "PENDIENTE POR MUESTRA", "PENDIENTE POR DEPENDENCIAS"]
"""The panel of the gates' statuses (``fbi.ai.gates_panel.STATUSES``)."""
ShadowBreak = Literal["picks_source_intelligence", "ai_enforced", "picks_published"]
"""What would make «nada sale de la sombra» false: the Picks board reading Intelligence, the AI's veto in force over what readers see, a
selection published to readers."""
ShadowVerdict = Literal["se_cumple", "no_se_cumple", "sin_comprobar"]
Alert = Literal["ninguno", "80", "95"]
Envelope = Literal["production", "exa", "lab"]


class ReadFailure(IntelligenceModel):
    """A block the server could not read this time: the class of the error, never its message (it can carry SQL)."""

    read_failed: Literal[True] = True
    error: str = Field(pattern=ERROR_PATTERN, description="The class of the error (UndefinedTable, QueryCanceled...).")


# ── «nada sale de la sombra» ──────────────────────────────────────────────────────────────────────────────────────────────────

class SwitchState(IntelligenceModel):
    """One switch, read only. ``reads_as`` is the word the code makes of it (its own parser: a typo reads as the default), never the raw value."""

    switch: str = Field(pattern=SWITCH_PATTERN)
    audience: Literal["intelligence", "lector"] = Field(description="intelligence: the worker's shadow; lector: a reader's screen.")
    reads_as: str = Field(pattern=WORD_PATTERN, description="As the API process reads it.")
    default: str = Field(pattern=WORD_PATTERN, description="What it reads as while its line is absent.")
    at_default: bool
    worker_recorded: str | Missing = Field(description="The word in the worker's newest row of its ledger (ai.feature_gates, gate "
                                                       "switches), or why there is none (sin_datos: the worker does not record it).")
    effect: str = Field(min_length=1, description="What it does, in a line.")
    changeable_here: Literal[False] = Field(default=False, description="Never: the console shows a switch, it does not change one.")


class AiEnforcement(IntelligenceModel):
    """Whether the AI's veto is in force (``fbi.ai.gating.enforcement``): ``enforce`` alone is not enough - the newest report of ``combined``
    must say pass."""

    mode: Literal["off", "shadow", "enforce"]
    enforced: bool
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="mode_off, mode_shadow, no_shadow_report, shadow_gate_not_passed, "
                                                                   "enforced.")
    gate_verdict: str | Missing = Field(description="The verdict of the newest report of combined (ai-gate-v2).")


class WorkerLedger(IntelligenceModel):
    """The worker's newest row of the ledger of the owner's words."""

    row: int = Field(ge=1)
    at: UtcDatetime


class Shadow(IntelligenceModel):
    """«Nada sale de la sombra»: ``se_cumple`` when nothing breaks it, ``sin_comprobar`` when a read it needs failed."""

    verdict: ShadowVerdict
    breaks: list[ShadowBreak]
    picks_source: SwitchState
    ai_mode: SwitchState
    ai_enforcement: AiEnforcement | ReadFailure
    published_picks: int | ReadFailure = Field(description="Selections a reader can see as picks (picks.picks qualified or published).")
    switches: list[SwitchState] = Field(description="The switches of Intelligence's capabilities and of the readers' Intelligence screens.")
    worker_ledger: WorkerLedger | Missing | ReadFailure

    @model_validator(mode="after")
    def _verdict(self) -> Shadow:
        unread = isinstance(self.ai_enforcement, ReadFailure) or isinstance(self.published_picks, ReadFailure)
        expected = "no_se_cumple" if self.breaks else "sin_comprobar" if unread else "se_cumple"
        if self.verdict != expected:
            raise ValueError(f"verdict {self.verdict} with breaks {self.breaks} should be {expected}")
        if self.picks_source.switch != "FBI_PICKS_SOURCE" or self.ai_mode.switch != "FBI_AI_MODE":
            raise ValueError("picks_source is FBI_PICKS_SOURCE and ai_mode is FBI_AI_MODE")
        return self


# ── capabilities ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

class GateReading(IntelligenceModel):
    """The newest row of a gate a capability answers to, or why there is none."""

    gate: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    verdict: GateWord | Missing
    row: int | Missing
    at: UtcDatetime | Missing


class CapabilityView(IntelligenceModel):
    """One capability of the registry, with one of its four states."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    piece: str
    title: str
    switch: str | Missing = Field(description="Its switch, or sin_datos for a job of the worker that has none.")
    state: CapabilityState | Missing = Field(description="sin_datos: in the code's catalog, not yet registered.")
    since: UtcDatetime | Missing
    decided_by: Literal["system", "owner"] | Missing
    signed_by_owner: bool
    safety: SafetyWord | Missing
    validation: ValidationWord | Missing
    validation_sample: int | Missing
    safety_gates: list[GateReading]
    validation_gates: list[GateReading]
    warnings: list[str] = Field(description="What the registry says beside it: never a reason to read it as better than it is.")


class StateCount(IntelligenceModel):
    state: CapabilityState
    count: int = Field(ge=0)


class Capabilities(IntelligenceModel):
    registry_version: str
    by_state: list[StateCount] = Field(description="The four states, in their order.")
    unregistered: list[str]
    not_in_code: list[str]
    items: ItemList[CapabilityView]


# ── costs ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

class CostPart(IntelligenceModel):
    name: Literal["intelligence", "readers"]
    spent_usd: str = Field(pattern=USD_PATTERN)


class EnvelopeView(IntelligenceModel):
    """One envelope of decision 12 this month: what it spent against what the code gives it and what the owner decided."""

    scope: Envelope
    spent_usd: str = Field(pattern=USD_PATTERN)
    budget_usd: str = Field(pattern=USD_PATTERN, description="What the code applies (the environment).")
    decided_usd: str = Field(pattern=USD_PATTERN, description="What decision 12 gives it.")
    matches_decision: bool
    share: float | Missing = Field(description="spent / budget, or sin_datos for a budget of 0.")
    alert: Alert
    parts: list[CostPart] = Field(description="Production only: Intelligence's Claude and the readers' chronicle.")


class CapabilityCap(IntelligenceModel):
    """A new capability's monthly cap against what it spent (``capability-budget-v1``). A cap warns; it does not cut."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    piece: str
    envelope: Envelope
    monthly_usd: str = Field(pattern=USD_PATTERN)
    spent_usd: str = Field(pattern=USD_PATTERN)
    share: float | Missing
    alert: Alert
    tagged: bool = Field(description="False: its calls cannot be found in the ledger yet (a piece not built), so it spends 0.")
    source: str


class Declared(IntelligenceModel):
    envelope: Envelope
    declared_usd: str = Field(pattern=USD_PATTERN)
    envelope_usd: str = Field(pattern=USD_PATTERN)
    fits: bool


class JointCeiling(IntelligenceModel):
    usd: str = Field(pattern=USD_PATTERN)
    applies: bool = Field(description="False only with FBI_AI_ENVELOPES_INDEPENDENT on.")
    pending_owner: bool = Field(description="The owner has not confirmed whether decision 12 replaces it.")
    production_plus_lab_usd: str = Field(pattern=USD_PATTERN, description="The two envelopes the ceiling caps, added up.")


class Costs(IntelligenceModel):
    month: date
    budget_version: str
    envelopes: list[EnvelopeView]
    capabilities: list[CapabilityCap]
    declared: list[Declared]
    joint_ceiling: JointCeiling


# ── security ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

class Battery(IntelligenceModel):
    """The newest row of the adversarial battery's gate (``ai.feature_gates``, gate ``battery``)."""

    verdict: GateWord | Missing
    row: int | Missing
    at: UtcDatetime | Missing


class LeakRule(IntelligenceModel):
    rule: str
    checked: int = Field(ge=0)
    violations: int = Field(ge=0)


class LeakAudit(IntelligenceModel):
    """The newest night of the leakage audit (``intel.audit_checks``): every rule's newest row of that day."""

    day: date
    versions: list[str]
    rules: int = Field(ge=0)
    violations: int = Field(ge=0)
    with_violations: list[LeakRule] = Field(description="Only the rules that found something, most violations first.")


class GateView(IntelligenceModel):
    """One gate of the panel (``gates-panel-v1``), in its own words. ``approved`` is exactly ``status == PASA``."""

    id: str
    name: str
    piece: str
    status: GateStatus
    approved: bool
    recorded_row: int | Missing
    recorded_at: UtcDatetime | Missing
    evaluable_on: date | Missing
    why: list[str]

    @model_validator(mode="after")
    def _approved(self) -> GateView:
        if self.approved != (self.status == "PASA"):
            raise ValueError("approved is exactly status == PASA")
        return self


class StatusCount(IntelligenceModel):
    status: GateStatus
    count: int = Field(ge=0)


class Gates(IntelligenceModel):
    version: str
    as_of: UtcDatetime = Field(description="When the panel was read (the console keeps it five minutes).")
    rule_holds: bool = Field(description="No pending gate shown as approved (fbi.ai.gates_panel.violations).")
    summary: list[StatusCount]
    items: list[GateView]


class Schema(IntelligenceModel):
    """Whether the database is at the code's migration: a database behind it answers 500 in the routes that read what it lacks."""

    database_revision: str | Missing
    code_head: str | Missing
    up_to_date: bool
    missing_relations: list[str] = Field(description="Tables the console's routes read that the database does not have.")


class Security(IntelligenceModel):
    battery: Battery | ReadFailure
    leak_audit: LeakAudit | Missing | ReadFailure
    gates: Gates | ReadFailure
    schema_check: Schema | ReadFailure


# ── protocols ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

class ConsoleProtocol(IntelligenceModel):
    """One preregistered protocol as the code has it now, and the owner's signature of that fingerprint (IA-143)."""

    key: str = Field(pattern=r"^(INT|AD)-[A-Z][0-9]{2}$")
    version: str
    framework: Literal["lab-protocol-v1", "own-record-v1"]
    title: str
    registered_on: date
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", description="The fingerprint in force: the one a signature must name.")
    signed_by_owner: bool = Field(description="A signature of the owner of this very fingerprint is on file. It turns nothing on.")
    signed_at: UtcDatetime | Missing
    signature_row: int | Missing
    other_fingerprints: int = Field(ge=0, description="Signatures of earlier fingerprints of the same protocol: kept, and they do not count.")


class ConsoleProtocols(IntelligenceModel):
    register_version: str
    signed: int = Field(ge=0)
    pending: int = Field(ge=0)
    items: list[ConsoleProtocol]
    notice_es: str


# ── the contract ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

class ConsoleContract(IntelligenceContract):
    """C-11, private only."""

    CONTRACT_ID: ClassVar[str] = "C-11"
    CONTRACT_VERSION: ClassVar[str] = "1.1.0"
    PRIVATE_ONLY: ClassVar[bool] = True

    decides: Literal[False] = Field(default=False, description="Nothing here decides, records or switches anything.")
    shadow: Shadow
    capabilities: Capabilities | ReadFailure
    costs: Costs | ReadFailure
    security: Security
    protocols: ConsoleProtocols | Missing | ReadFailure = Field(
        description="The preregistered protocols and the owner's signatures (1.1.0); sin_datos before revision 0166.")
    news_engine: Missing = Field(description="The news engine (AD-G01): no_entregado until it exists.")
    alert_queue: Missing = Field(description="The private alerts' queue (AD-D08): no_entregado until it exists.")

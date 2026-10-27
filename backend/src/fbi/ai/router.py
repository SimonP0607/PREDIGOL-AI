"""``router-v1``: which model reads what, and whether anything may be asked of a model at all (Plan Maestro IA, section 17).

A PURE function: the same signals give the same decision, always. It reads no clock, no database, no setting and no network; the caller
measures the world (the budget's state, the day's money, what the package says is missing, the facts of the contradictions) and the
router says what to do with it. Every decision names the rule that made it and the reasons, so that the audit can replay it.

The seven rules, in order (the first that ends the question ends it), and where each one lives:

    1. BUDGET      ``route`` and ``permitted_levels``. EXHAUSTED: no model, the rules' reviewer decides. REDUCED: no Opus outside E1 and no
                   second round of the Council. CHEAP_ONLY is the OLD route's last step (the bulk tier only): the agents never change
                   judge, so what they cannot afford they do not do - the Council abstains and the rules' reviewer decides. An experiment's
                   arm never changes its model either: it is skipped, and that day leaves the analysis of the experiment.
    2. DATA        ``route``. Data that blocks (INSUFFICIENT, PRODUCT_ONLY, quarantine): no model is called. Data that will arrive (the
                   line-ups): wait for the ``final`` pass instead of going up a model.
    3. IMPORTANCE  ``fired_rules``. The Pick of the Day and the legs of the main parlay escalate by E1.
    4. UNCERTAINTY ``fired_rules``. Contradictions and surprises escalate by E2-E7.
    5. VALUE       ``order_key``. While no market has a VALIDATED edge no escalation is justified by the stake; afterwards the escalations
                   of one rule are ordered by the expected stake times the calibrated edge.
    6. COMPLEXITY  ``council_calls``. Two families with candidates in one match are resolved in ONE Council.
    7. RESEARCH    ``admit_research``. Asked by a model: only with a topic of the closed list, no fresh evidence for its key, at least 20
                   minutes to the kick-off and the day's envelope of searches available.

What the router can never do, by construction: go up a model because a call FAILED (there is no such input), because the budget is short
(the budget only takes options away), or because an interval is wide (the filter that follows already leaves that selection in CAUTELA).
It never goes down either: what it cannot afford it skips.

The caps (a share of the day's allocation per kind of work, the calls of Opus) and the thresholds of the escalations are PARAMETERS of the
version (``PARAMS``): with more budget they change, the rules do not (plan, section 44). Every decision carries the hash of the parameters
it was made with.

The router speaks for the AGENTS. The old route (L2 and L3) keeps ``fbi.ai.usage`` (its tiers, its downgrade) until it is retired; a test
holds what the router lets through to what that guard lets through.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, get_args

from fbi.ai.contracts.base import ResearchTopic
from fbi.ai.contracts.mcp import Blocking

if TYPE_CHECKING:  # names for the annotations only: the router imports nothing that could read the world
    from fbi.ai.contracts.mcp import PassKind
    from fbi.ai.usage import BudgetState

VERSION: Final = "router-v1"

Level = Literal["simple", "complex", "critical", "owner"]
Effort = Literal["low", "medium"]
Bucket = Literal["simple", "council", "analysis", "opus", "owner"]
Action = Literal["CALL", "WAIT_FINAL", "NO_MODEL", "RULES_ONLY", "SKIP"]
"""CALL: ask the model. WAIT_FINAL: the data that will arrive is waited for. NO_MODEL: the data does not allow a forecast. RULES_ONLY: the
budget is spent and the rules' reviewer decides. SKIP: this call is not made today (a cap, a level the budget took away, a rule that does
not fire) and nothing is put in its place."""
Rule = Literal["budget", "data", "importance", "uncertainty", "research", "task"]
Task = Literal["context", "evaluation", "extraction", "narrative", "council", "analyst", "loss_review", "escalation", "owner_research"]
Confidence = Literal["LOW", "MEDIUM", "HIGH"]
Scope = Literal["production", "shadow"]
Asker = Literal["match", "statistics", "council"]
Pending = Literal["lineups"]
TASKS: Final = get_args(Task)
BLOCKING_CODES: Final[tuple[str, ...]] = get_args(Blocking)
PENDING_CODES: Final[tuple[str, ...]] = get_args(Pending)

MODELS: Final[dict[str, str]] = {"simple": "claude-haiku-5-5", "complex": "claude-sonnet-5-5", "critical": "claude-opus-5-5",
                                 "owner": "claude-fable-5-1"}
"""The model of each level (the keys of ``fbi.ai.pricing.PRICES``, held equal by a test)."""
LEVEL_OF_MODEL: Final[dict[str, str]] = {model: level for level, model in MODELS.items()}
TIER_OF_LEVEL: Final[dict[str, str]] = {"simple": "bulk", "complex": "analysis", "critical": "final"}
"""The tiers the budget speaks of (``fbi.ai.usage.ALLOWED``) for each level; Fable has none: it is never automatic."""
BUCKET_OF_LEVEL: Final[dict[str, Bucket]] = {"simple": "simple", "complex": "analysis", "critical": "opus", "owner": "owner"}
"""Whose share of the day a call is counted against when an arm judges with a model other than its task's own (the Council with Haiku is
a simple task for the cap: plan, section 17)."""


@dataclass(frozen=True, slots=True)
class TaskSpec:
    level: str
    effort: Effort
    bucket: Bucket
    """Whose share of the day the call is counted against."""


SPECS: Final[dict[str, TaskSpec]] = {
    "context": TaskSpec("simple", "low", "simple"),
    "evaluation": TaskSpec("simple", "medium", "simple"),
    "extraction": TaskSpec("simple", "low", "simple"),
    "narrative": TaskSpec("simple", "low", "simple"),
    "council": TaskSpec("complex", "medium", "council"),
    "analyst": TaskSpec("complex", "medium", "analysis"),
    "loss_review": TaskSpec("complex", "medium", "analysis"),
    "escalation": TaskSpec("critical", "medium", "opus"),
    "owner_research": TaskSpec("owner", "medium", "owner"),
}
"""Haiku reads (``low`` for the context and the extraction, ``medium`` for an evaluation); Sonnet and Opus judge, at ``medium``: the effort is
not changed call by call - the reasoning is billed as output and changing it breaks the cache. Opus 5.5 always reasons: turning it off is a 400.
The Council has a cap of its own (65 % of the day); the analyst and the loss reviews have none in this version - the budget's state is what
limits them."""

PARAMS: Final[dict[str, Any]] = {
    "share": {"simple": "0.30", "council": "0.65", "opus": {"production": "0.20", "shadow": "0.30"}},
    "opus_calls": {"production": 10, "shadow": 3},
    "fable_month_usd": "10",
    "council_calls_per_match_and_pass": 2,
    "e2_hours_to_kickoff": 6,
    "e3_usual_starters_out": 4,
    "e6_gap": "0.20",
    "research_min_minutes": 20,
}
"""The thresholds and the caps of this version. ``params_hash`` goes with every decision."""

PRIORITY: Final[dict[str, int]] = {"E1": 1, "E2": 2, "E3": 2, "E4": 3, "E5": 3, "E6": 4, "E7": 5}
"""The order of the escalations when more than ``opus_calls`` qualify in a day (section 11 of the plan)."""
ESCALATIONS: Final = tuple(PRIORITY)


def params_hash() -> str:
    return hashlib.sha256(json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def _dec(path: str) -> Decimal:
    node: Any = PARAMS
    for part in path.split("."):
        node = node[part]
    return Decimal(str(node))


# -- the inputs ----------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Day:
    """The day's money, as the budget (v3) states it, and what each kind of work has spent of it."""

    allocation_usd: Decimal
    scope: Scope = "production"
    """Whose caps of Opus apply: the champion in production (10 calls, 20 %) or the arms in the shadow (3 calls, 30 %)."""
    spent_simple_usd: Decimal = Decimal(0)
    spent_council_usd: Decimal = Decimal(0)
    spent_opus_usd: Decimal = Decimal(0)
    opus_calls: int = 0
    fable_spent_month_usd: Decimal = Decimal(0)
    lab_has_margin: bool = False
    """Fable only runs in the LAB and only with room in its envelope."""


@dataclass(frozen=True, slots=True)
class Facts:
    """What the seven rules of escalation read. Every one is computed by code from the package, from ``cd-v1`` and from the contradictions
    (``contra-v1``); a model never says that it wants an escalation. There is no field for a failed call, for the budget or for the width of
    an interval: none of those escalates."""

    pick_of_the_day: bool = False
    main_parlay_leg: bool = False
    council_confidence: Confidence | None = None
    """What the Council said about the selection; None while it has not said anything."""
    confirmed_news_on_candidate: bool = False
    """A CONFIRMED evidence that fires C01 or C02 on a candidate."""
    hours_to_kickoff: Decimal | None = None
    official_lineup_surprise: bool = False
    """C03 with the official line-up."""
    usual_starters_out: int = 0
    c08_left_with_low_confidence: bool = False
    """SUPPORT against REJECT_SIGNAL on correlated selections that the Council leaves with low confidence."""
    c07_unresolved_after_research: bool = False
    model_market_gap: Decimal | None = None
    """C06: the gap between the model and the market, in probability."""
    approves_with_low_confidence: bool = False
    edge_validated: bool = False
    """Whether the market of the selection has an edge a person has VALIDATED with an experiment (today none does)."""
    expected_stake_times_edge: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Signals:
    """Everything ``route`` reads. ``blocking`` and ``data_pending`` describe the package a call is about; a call that reads no package
    (the analyst, a loss review) passes none."""

    task: Task
    day: Day
    budget_state: BudgetState = "NORMAL"
    pass_kind: PassKind = "pre"
    blocking: tuple[Blocking, ...] = ()
    """From the package: PRODUCT_ONLY, INSUFFICIENT, QUARANTINED."""
    data_pending: tuple[Pending, ...] = ()
    """Data that is not there yet and will be (the line-ups): the router waits for the ``final`` pass instead of going up a model."""
    facts: Facts = Facts()
    arm_model: str | None = None
    """The model an experiment's arm was registered with: it is never changed."""
    owner_request: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    task: str
    action: Action
    rule: Rule
    reasons: tuple[str, ...]
    version: str = VERSION
    params: str = ""
    model: str | None = None
    level: str | None = None
    tier: str | None = None
    effort: Effort | None = None
    bucket: Bucket | None = None
    escalation: str | None = None
    fired: tuple[str, ...] = ()
    priority: int | None = None
    leaves_analysis: bool = False
    """The arm of an experiment could not run as it was registered: the day leaves the experiment's analysis."""

    @property
    def call(self) -> bool:
        return self.action == "CALL"

    def record(self) -> dict[str, Any]:
        """What is kept of a decision (``ai.agent_tasks.routing``): the codes, never a text."""
        return {"version": self.version, "params": self.params, "task": self.task, "action": self.action, "rule": self.rule,
                "reasons": list(self.reasons), "model": self.model, "level": self.level, "effort": self.effort, "bucket": self.bucket,
                "escalation": self.escalation, "fired": list(self.fired), "priority": self.priority,
                "leaves_analysis": self.leaves_analysis}


# -- rule 1: what the budget leaves --------------------------------------------------------------------------------------------------

def permitted_levels(state: BudgetState, *, escalation: str | None = None) -> frozenset[str]:
    """The levels the budget leaves the agents, by its state. It never leaves more than ``fbi.ai.usage.ALLOWED`` does (a test holds it),
    except for the one thing the plan adds: in REDUCED, Opus for E1. CHEAP_ONLY leaves the bulk tier only, and what does not fit is not
    lowered to it: it is skipped. Fable is the owner's: only while the budget has no pressure at all (the LAB yields first)."""
    if state == "EXHAUSTED":
        return frozenset()
    if state == "CHEAP_ONLY":
        return frozenset({"simple"})
    if state == "REDUCED":
        return frozenset({"simple", "complex"} | ({"critical"} if escalation == "E1" else set()))
    return frozenset({"simple", "complex", "critical", "owner"})


def cap_reached(bucket: Bucket, day: Day) -> str | None:
    """Why the day's cap of this kind of work is reached, or None. The caps are shares of the day's allocation (and, for Opus, calls)."""
    allocation = day.allocation_usd
    if bucket == "simple" and day.spent_simple_usd >= _dec("share.simple") * allocation:
        return "cap:simple"
    if bucket == "council" and day.spent_council_usd >= _dec("share.council") * allocation:
        return "cap:council"
    if bucket == "opus":
        if day.opus_calls >= int(PARAMS["opus_calls"][day.scope]):
            return "cap:opus_calls"
        if day.spent_opus_usd >= _dec(f"share.opus.{day.scope}") * allocation:
            return "cap:opus_share"
    if bucket == "owner" and day.fable_spent_month_usd >= _dec("fable_month_usd"):
        return "cap:fable_month"
    return None


# -- rules 3-5: the escalation to Opus -----------------------------------------------------------------------------------------------

def fired_rules(f: Facts) -> tuple[str, ...]:
    """The rules E1-E7 that the facts trigger, in order. All are objective: a model cannot ask for one."""
    fired: list[str] = []
    if (f.pick_of_the_day or f.main_parlay_leg) and f.council_confidence in ("LOW", "MEDIUM"):
        fired.append("E1")
    if f.confirmed_news_on_candidate and f.hours_to_kickoff is not None and f.hours_to_kickoff < _dec("e2_hours_to_kickoff"):
        fired.append("E2")
    if f.official_lineup_surprise and f.usual_starters_out >= int(PARAMS["e3_usual_starters_out"]):
        fired.append("E3")
    if f.c08_left_with_low_confidence:
        fired.append("E4")
    if f.c07_unresolved_after_research:
        fired.append("E5")
    if f.model_market_gap is not None and f.model_market_gap > _dec("e6_gap"):
        fired.append("E6")
    if f.approves_with_low_confidence:
        fired.append("E7")
    return tuple(fired)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A selection that qualifies for Opus, for the order of the day. ``rule`` is the first rule that its facts fire."""

    key: str
    rule: str
    facts: Facts
    estimated_usd: Decimal = Decimal(0)


def qualify(key: str, facts: Facts, *, estimated_usd: Decimal | None = None) -> Candidate | None:
    """The selection as a candidate for Opus, or None when no rule fires."""
    fired = fired_rules(facts)
    return Candidate(key, fired[0], facts, estimated_usd or Decimal(0)) if fired else None


def order_key(c: Candidate) -> tuple[int, Decimal, Decimal, str]:
    """E1 first, then E2-E3, E4-E5, E6 (the larger the gap the earlier) and E7; inside a rule, by the expected stake times the edge when the
    market has a validated edge (rule 5) and otherwise by the key, so that the order never depends on how the candidates came in."""
    gap = (c.facts.model_market_gap or Decimal(0)) if c.rule == "E6" else Decimal(0)
    value = (c.facts.expected_stake_times_edge or Decimal(0)) if c.facts.edge_validated else Decimal(0)
    return PRIORITY[c.rule], -gap, -value, c.key


def escalation_order(candidates: Sequence[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=order_key)


@dataclass(frozen=True, slots=True)
class Admitted:
    admitted: tuple[Candidate, ...]
    deferred: tuple[tuple[Candidate, str], ...]
    """Each with the reason: the budget, the cap of calls or the cap of the day's share."""


def admit_escalations(candidates: Sequence[Candidate], state: BudgetState, day: Day) -> Admitted:
    """Which of the day's escalations are made: in the order of the plan, while the calls and the share of the day last. In REDUCED only E1.
    Once a cap closes the day, the less important ones that follow do not slip through behind it: a cheaper E7 never takes the place of an
    E2 that did not fit."""
    admitted: list[Candidate] = []
    deferred: list[tuple[Candidate, str]] = []
    calls = day.opus_calls
    spent = day.spent_opus_usd
    ceiling = _dec(f"share.opus.{day.scope}") * day.allocation_usd
    closed: str | None = None
    for c in escalation_order(candidates):
        if "critical" not in permitted_levels(state, escalation=c.rule):
            deferred.append((c, f"budget:{state}"))
            continue
        if closed is None:
            if calls >= int(PARAMS["opus_calls"][day.scope]):
                closed = "cap:opus_calls"
            elif spent + c.estimated_usd > ceiling:
                closed = "cap:opus_share"
        if closed is not None:
            deferred.append((c, closed))
            continue
        admitted.append(c)
        calls += 1
        spent += c.estimated_usd
    return Admitted(tuple(admitted), tuple(deferred))


# -- rule 6: the Council -------------------------------------------------------------------------------------------------------------

def council_calls(*, families_with_candidates: int, research_admitted: bool) -> int:
    """Two families with candidates in one match are ONE Council. A second call exists only after a research the router admitted."""
    if families_with_candidates < 1:
        return 0
    return min(int(PARAMS["council_calls_per_match_and_pass"]), 2 if research_admitted else 1)


# -- rule 7: the research a model asks for -------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ResearchRequest:
    topic: str
    fresh_evidence_for_key: bool
    minutes_to_kickoff: int | None
    exa_day_available: bool
    asked_by: Asker = "match"
    """The Council asks so that it can read again, and REDUCED has no second round; the specialists' requests feed the next pass."""


@dataclass(frozen=True, slots=True)
class Admission:
    admitted: bool
    reasons: tuple[str, ...]
    rule: Rule = "research"
    version: str = VERSION


def admit_research(r: ResearchRequest, state: BudgetState = "NORMAL") -> Admission:
    """A research is served only with a topic of the closed list, no fresh evidence for its key, at least 20 minutes before the kick-off
    and the day's envelope of searches available - and while the budget has a search to give (none in CHEAP_ONLY) and, for the Council,
    a second round (none in REDUCED). The server writes the searches; a model only names a topic."""
    reasons: list[str] = []
    if r.topic not in get_args(ResearchTopic):
        reasons.append("topic_not_in_the_list")
    if r.fresh_evidence_for_key:
        reasons.append("fresh_evidence_exists")
    if r.minutes_to_kickoff is None or r.minutes_to_kickoff < int(PARAMS["research_min_minutes"]):
        reasons.append("too_close_to_kickoff")
    if not r.exa_day_available:
        reasons.append("no_envelope_for_the_day")
    if state == "EXHAUSTED":
        reasons.append("budget_exhausted")
    elif state == "CHEAP_ONLY":
        reasons.append("budget_cheap_only_has_no_search")
    elif state == "REDUCED" and r.asked_by == "council":
        reasons.append("budget_reduced_has_no_second_round")
    return Admission(not reasons, tuple(reasons) or ("admitted",))


# -- the decision --------------------------------------------------------------------------------------------------------------------

def _codes(values: Sequence[str], vocabulary: Sequence[str]) -> list[str]:
    """The codes of a closed vocabulary, once each and in order; anything else is ``unknown``: a decision never carries a text it was handed."""
    return sorted({v if v in vocabulary else "unknown" for v in values})


def _end(s: Signals, action: Action, rule: Rule, *reasons: str, **fields: Any) -> Decision:
    return Decision(task=s.task, action=action, rule=rule, reasons=reasons, params=params_hash(), **fields)


def route(s: Signals) -> Decision:
    """The decision for one call. Pure."""
    spec = SPECS[s.task]
    arm = s.arm_model is not None
    if arm and s.arm_model not in LEVEL_OF_MODEL:
        return _end(s, "SKIP", "task", "arm_model_unknown", leaves_analysis=True)
    # 1. the budget: nothing at all
    if s.budget_state == "EXHAUSTED":
        if arm:
            return _end(s, "SKIP", "budget", "budget_exhausted", leaves_analysis=True)
        return _end(s, "RULES_ONLY", "budget", "budget_exhausted")
    # 2. the data
    if s.blocking:
        return _end(s, "NO_MODEL", "data", *(f"blocking:{code}" for code in _codes(s.blocking, BLOCKING_CODES)))
    if s.data_pending and s.pass_kind in ("first", "pre"):
        return _end(s, "WAIT_FINAL", "data", *(f"pending:{what}" for what in _codes(s.data_pending, PENDING_CODES)))
    # 3-5. importance, uncertainty, value: only the escalation to Opus reads them
    escalation: str | None = None
    fired: tuple[str, ...] = ()
    priority: int | None = None
    rule: Rule = "task"
    if s.task == "escalation":
        fired = fired_rules(s.facts)
        if not fired:
            return _end(s, "SKIP", "task", "no_escalation_rule_fires")
        escalation, priority = fired[0], PRIORITY[fired[0]]
        rule = "importance" if escalation == "E1" else "uncertainty"
    if s.task == "owner_research" and not (s.owner_request and s.day.lab_has_margin):
        return _end(s, "SKIP", "task", *(["owner_request_missing"] if not s.owner_request else ["lab_without_margin"]))
    # the model: fixed by the task, or by the arm of the experiment - never changed
    model = s.arm_model or MODELS[spec.level]
    level = LEVEL_OF_MODEL[model]
    if (level == "owner") != (s.task == "owner_research"):  # Fable is the owner's, by request, and nothing else is ever Fable
        return _end(s, "SKIP", "task", "owner_model_is_manual_only", leaves_analysis=arm)
    bucket = spec.bucket if level == spec.level else BUCKET_OF_LEVEL[level]
    common: dict[str, Any] = {"model": model, "level": level, "tier": TIER_OF_LEVEL.get(level), "effort": spec.effort, "bucket": bucket,
                              "escalation": escalation, "fired": fired, "priority": priority}
    if level not in permitted_levels(s.budget_state, escalation=escalation):
        return _end(s, "SKIP", "budget", f"budget_{s.budget_state.lower()}_leaves_no_{level}", leaves_analysis=arm, **common)
    if (why := cap_reached(bucket, s.day)) is not None:
        return _end(s, "SKIP", "budget", why, leaves_analysis=arm, **common)
    return _end(s, "CALL", rule, *(fired or ("task",)), **common)

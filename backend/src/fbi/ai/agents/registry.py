"""The registry of the agents (Plan Maestro IA, sections 11 and 25, phase 1): which agents the code has, in which version, and the decision that
put each one there.

An AGENT is its prompts, the contract of its answer, its model and its effort. Changing any one of them is a NEW VERSION of the agent; a new
version is born CHALLENGER and reaches CHAMPION only through a row the owner signs in ``intel.promotions`` (entity ``agent``, one family at a
time, section 25). The registry lives in the repository and is held to the code by a test, as the model-code ledger of F12 is
(``fbi.research.promotions``): the fingerprint of an agent is computed from the code that is running, ``LEDGER`` says which fingerprint each
version was put in force with, and ``tests/unit/test_ai_registry.py`` fails the moment a prompt, a schema, a model or an effort changes without
a new entry - and the message it fails with is the entry to add.

Three things live here, each with a different relation to the code:

* ``AGENTS``     what the code HAS. Every agent here has a live definition (read from ``fbi.ai.prompts`` and ``fbi.ai.claims``, never copied), a
                 fingerprint and an entry in the ledger. Today that is the AI that runs in production (engine ``llm``), recorded as it is: CHAMPION
                 by baseline, because the decision was taken before there was a registry and the entry says so.
* ``PLANNED``    what the plan builds, phase by phase: the version it will be born as, its contract, what it reads, the model and the effort of
                 each task and the label of each prompt. Nothing here has code. The test holds it to the router, the contracts and the price list
                 (so that the plan cannot drift from what the code will be able to do) and fails the day a planned prompt appears in
                 ``fbi.ai.prompts`` without the agent having moved to ``AGENTS``.
* ``POSTPONED``  what the plan decided NOT to build until a gate (the Player Agent): no tokens, no code, nothing to register.

One rule beyond the fingerprint, because everything that follows rests on it (``fbi.ai.idempotency``, the reviews that record the version they
were made with): a PROMPT LABEL NEVER NAMES TWO TEXTS. The ledger keeps, for every task of every version, the label and a hash of the text and of
the schema; a label whose text has changed since is an edit in place - the one thing ``fbi.ai.prompts`` says is never done - and it fails.

The registry holds the identity of an agent, not its authority: whether an agent runs, for which matches and with which model is the router's
and the orchestrator's; whether its answers count is the owner's, in ``intel.promotions``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from fbi.ai import claims, prompts, router
from fbi.ai.config import TIERS, Tier
from fbi.ai.contracts import CONTRACTS, schema_of
from fbi.ai.contracts.base import ASSESSMENT, CLAIM, COUNCIL, LEARNING, OUTPUTS, POST_MATCH
from fbi.ai.contracts.mcp import SLICE_NAMES, PassKind
from fbi.ai.idempotency import EFFORTS, Effort, TaskIdentity, Workspace
from fbi.ai.pricing import PRICES

FINGERPRINT_VERSION: Final = "agent-fp-v1"
"""The method of the fingerprint. Changing how it is made changes the fingerprint of every agent: a new method is a new name here, and every
entry of the ledger is written again with it, in the same commit (a golden value in the tests tells the method from the code)."""
FINGERPRINT: Final = re.compile(r"^ag[0-9a-f]{10}$")
"""How a version names its code: ``ag`` and the first ten hex digits of the hash of its definition (``ag3f9a1c2b7d``)."""
SHA12: Final = re.compile(r"^[0-9a-f]{12}$")
AGENT_ID: Final = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
VERSION_LABEL: Final = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*-v[1-9][0-9]{0,2}$")
DECIDERS: Final = ("owner", "system")
MIN_REASON: Final = 40
"""A registration without a reason a person can look back on is not a decision."""
VIEWS: Final = ("council_view", "settled_match", "week")
"""What an agent reads that is not a slice of ``mcp-v1``: the Council's compact view (phase 3), a settled match with its runs (phase 5) and a week
of them (phase 5)."""
UNSERVED_TASKS: Final = frozenset({"owner_research"})
"""The router's tasks no agent serves: the owner's own research with Fable, started by hand and never by the system."""
VERSION_SUFFIX: Final = "_VERSION"
"""``fbi.ai.prompts`` names the version of each prompt by a constant that ends like this (``BRIEF_VERSION``)."""

Born = Literal["CHAMPION", "CHALLENGER"]
Status = Literal["built", "planned", "postponed"]


class RegistryError(ValueError):
    """Something asked of the registry that it cannot answer: an agent it does not have, a task it does not run."""


@dataclass(frozen=True, slots=True)
class Definition:
    """What the code says a task is, read from the code that is running."""

    prompt_version: str
    prompt: str
    schema_version: str
    schema: Mapping[str, Any]
    """The schema the answer is read against: a contract's wire schema, or - for the AI that runs today, which versions its schema with its
    prompt - the dictionary ``fbi.ai.prompts`` keeps next to it."""


@dataclass(frozen=True, slots=True)
class Part:
    """One task of one version as the ledger keeps it: the labels and a hash of each text (the first twelve hex digits of a sha256)."""

    prompt_version: str
    prompt_sha: str
    schema_version: str
    schema_sha: str


@dataclass(frozen=True, slots=True)
class BuiltTask:
    """One thing an agent does that the code can already do: with which prompt and schema (``definition``), on which model, at which effort."""

    task: str
    effort: Effort
    definition: Callable[[], Definition]
    model: str | None = None
    """The model the task is registered with. The agents of the plan pin one; changing it is a new version."""
    tier: Tier | None = None
    """The tier of the old route (``bulk``, ``analysis``, ``final``): the model is the deployment's setting (``FBI_AI_MODEL_*``). Exactly one
    of ``model`` and ``tier``."""


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """An agent the code has."""

    agent: str
    purpose: str
    tasks: tuple[BuiltTask, ...]
    contract: str | None = None
    """The contract of its answer (``aa-v1``...). None for the AI that runs today: it versions its schema with its prompt."""
    reads: str | None = None
    """A slice of ``mcp-v1`` (``SLICE_NAMES``) or a view of its own (``VIEWS``); None when it reads neither (the extractor reads search results)."""
    retire_phase: int | None = None
    """The phase of the plan that retires it, when the plan says so."""
    replaces: str | None = None
    """The agent of this registry it takes over from if the owner promotes it (``claim_extractor`` replaces ``extractor``). Until then both are
    in the code and the switch of the phase decides which one runs: a new version that has to run beside the old one for a comparison is another
    agent here, because the registry holds exactly one version of an agent, the one the code has."""


@dataclass(frozen=True, slots=True)
class PlannedTask:
    task: str
    model: str
    effort: Effort
    prompt_version: str


@dataclass(frozen=True, slots=True)
class PlannedAgent:
    """An agent, or a new version of one, that the plan builds in ``phase``."""

    agent: str
    version: str
    purpose: str
    phase: int
    contract: str
    tasks: tuple[PlannedTask, ...]
    reads: str | None = None
    replaces: str | None = None
    """The version of the same agent it takes over from."""


@dataclass(frozen=True, slots=True)
class PostponedAgent:
    agent: str
    purpose: str
    gate: str
    """What has to be true before it has any code."""


@dataclass(frozen=True, slots=True)
class Registration:
    """One decision: this version of this agent is the code, with this fingerprint, from ``registered_at``."""

    agent: str
    version: str
    registered_at: datetime
    decided_by: str
    phase: str
    reason: str
    fingerprint: str
    parts: Mapping[str, Part]
    """Task by task: the labels and the hashes the version was registered with."""
    born_as: Born = "CHALLENGER"
    baseline: bool = False
    """True for the entry that starts an agent that was already in force: recorded after the fact, and said so. It is the only kind of entry
    born CHAMPION."""


@dataclass(frozen=True, slots=True)
class Problem:
    """One way the registry disagrees with the code or with itself."""

    code: str
    subject: str
    text: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.subject}: {self.text}"


# -- reading the code ----------------------------------------------------------------------------------------------------------------

def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def part_of(definition: Definition) -> Part:
    return Part(definition.prompt_version, sha12(definition.prompt), definition.schema_version, sha12(canonical(definition.schema)))


def live_parts(spec: AgentSpec) -> dict[str, Part]:
    """The parts of an agent as the code that is running has them."""
    return {t.task: part_of(t.definition()) for t in spec.tasks}


def fingerprint_body(spec: AgentSpec, parts: Mapping[str, Part]) -> dict[str, Any]:
    """Everything that makes the agent what it is: the contract it answers in, what it reads, and for each task its model or tier, its effort, and the
    labels and the hashes of its prompt and schema. Not its purpose, not when the plan retires it, not the order of its tasks."""
    return {"method": FINGERPRINT_VERSION, "agent": spec.agent, "contract": spec.contract, "reads": spec.reads,
            "tasks": {t.task: {"model": t.model, "tier": t.tier, "effort": t.effort,
                               "prompt": [parts[t.task].prompt_version, parts[t.task].prompt_sha],
                               "schema": [parts[t.task].schema_version, parts[t.task].schema_sha]} for t in spec.tasks}}


def fingerprint_of(spec: AgentSpec, parts: Mapping[str, Part]) -> str:
    """``ag`` and ten hex digits of the hash of ``fingerprint_body``."""
    return "ag" + hashlib.sha256(canonical(fingerprint_body(spec, parts)).encode("ascii")).hexdigest()[:10]


def live_fingerprint(spec: AgentSpec) -> str:
    return fingerprint_of(spec, live_parts(spec))


def live_prompt_versions(module: Any = prompts) -> dict[str, str]:
    """Every version label ``fbi.ai.prompts`` declares (``BRIEF_VERSION``...) by the name of its constant."""
    return {name: value for name, value in vars(module).items()
            if name.endswith(VERSION_SUFFIX) and name.isupper() and isinstance(value, str)}


def stub(spec: AgentSpec, version: str) -> str:
    """The entry to add to ``LEDGER`` for the code as it is: what the test prints when the code and the ledger disagree."""
    parts = live_parts(spec)
    lines = [f'Registration(agent="{spec.agent}", version="{version}", registered_at=datetime(...), decided_by="owner", phase="IA-?",',
             '             reason="why this is a new version, in a sentence a person can look back on",',
             f'             fingerprint="{fingerprint_of(spec, parts)}",', "             parts={"]
    for task, p in sorted(parts.items()):
        lines.append(f'                 "{task}": Part("{p.prompt_version}", "{p.prompt_sha}", "{p.schema_version}", "{p.schema_sha}"),')
    lines.append("             }),")
    return "\n".join(lines)


# -- the agents the code has ---------------------------------------------------------------------------------------------------------

def _brief() -> Definition:
    return Definition(prompts.BRIEF_VERSION, prompts.BRIEF_SYSTEM, prompts.BRIEF_VERSION, prompts.BRIEF_SCHEMA)


def _review() -> Definition:
    return Definition(prompts.REVIEW_VERSION, prompts.REVIEW_SYSTEM, prompts.REVIEW_VERSION, claims.REVIEW_SCHEMA)


def _extract() -> Definition:
    return Definition(prompts.EXTRACT_VERSION, prompts.EXTRACT_SYSTEM, prompts.EXTRACT_VERSION, prompts.EXTRACT_SCHEMA)


def _extract_v2() -> Definition:
    return Definition(prompts.EXTRACT_V2_VERSION, prompts.EXTRACT_V2_SYSTEM, CLAIM, schema_of(CLAIM))


def _match_context() -> Definition:
    return Definition(prompts.MATCH_CONTEXT_VERSION, prompts.MATCH_CONTEXT_SYSTEM, ASSESSMENT, schema_of(ASSESSMENT))


def _match_assess() -> Definition:
    return Definition(prompts.MATCH_ASSESS_VERSION, prompts.MATCH_ASSESS_SYSTEM, ASSESSMENT, schema_of(ASSESSMENT))


def _stats_assess() -> Definition:
    return Definition(prompts.STATS_ASSESS_VERSION, prompts.STATS_ASSESS_SYSTEM, ASSESSMENT, schema_of(ASSESSMENT))


def _postmortem() -> Definition:
    return Definition(prompts.POSTMORTEM_VERSION, prompts.POSTMORTEM_SYSTEM, prompts.POSTMORTEM_VERSION, prompts.POSTMORTEM_SCHEMA)


def _pick_postmortem() -> Definition:
    return Definition(prompts.PICK_PM_VERSION, prompts.PICK_PM_SYSTEM, prompts.PICK_PM_VERSION, prompts.PICK_PM_SCHEMA)


def _learning() -> Definition:
    return Definition(prompts.LEARNING_VERSION, prompts.LEARNING_SYSTEM, prompts.LEARNING_VERSION, prompts.LEARNING_SCHEMA)


def _pmr() -> Definition:
    return Definition(prompts.PMR_VERSION, prompts.PMR_SYSTEM, POST_MATCH, schema_of(POST_MATCH))


def _la() -> Definition:
    return Definition(prompts.LA_VERSION, prompts.LA_SYSTEM, LEARNING, schema_of(LEARNING))


def _council() -> Definition:
    return Definition(prompts.COUNCIL_VERSION, prompts.COUNCIL_SYSTEM, COUNCIL, schema_of(COUNCIL))


def _council_opus() -> Definition:
    return Definition(prompts.COUNCIL_OPUS_VERSION, prompts.COUNCIL_OPUS_SYSTEM, COUNCIL, schema_of(COUNCIL))


AGENTS: Final[tuple[AgentSpec, ...]] = (
    AgentSpec("brief", "L1: the first reading of a match of the day that has a market - what matters, who is out, what changed, the three cards "
              "and what to look into. Retired by the Match Agent's context mode (phase 9).",
              (BuiltTask("context", "low", _brief, tier="bulk"),), retire_phase=9),
    AgentSpec("reviewer", "L2 and L3: the review of one candidate selection - approve, downgrade, reject or abstain. Retired by the Council (phase 9).",
              (BuiltTask("review_analysis", "medium", _review, tier="analysis"), BuiltTask("review_final", "medium", _review, tier="final")),
              retire_phase=9),
    AgentSpec("extractor", "Extracts dated facts about who can or cannot play from the pages a search returned.",
              (BuiltTask("extraction", "low", _extract, tier="bulk"),)),
    AgentSpec("claim_extractor", "The extractor of the Research Service v2: typed claims (claim-v1) about the subjects of a match, from the pages a search "
              "returned for an entity and a topic. It runs beside the extractor of today for a week of comparison (FBI_AI_RESEARCH_V2) and replaces it "
              "only by the owner's signature.",
              (BuiltTask("extraction", "low", _extract_v2, tier="bulk"),), contract=CLAIM, replaces="extractor"),
    AgentSpec("postmortem", "The post-mortem narrative of a finished match, for the owner.",
              (BuiltTask("narrative", "low", _postmortem, tier="bulk"),)),
    AgentSpec("post_match_reviewer", "The post-mortem narrative of one selection after its match, for the owner; the Post-Match Reviewer of phase 5 "
              "grows out of it.",
              (BuiltTask("narrative", "low", _pick_postmortem, tier="bulk"), BuiltTask("loss_review", "medium", _pick_postmortem, tier="analysis"))),
    AgentSpec("learning_analyst", "The weekly lessons from the post-mortems; the Learning Analyst of phase 5 is its evolution.",
              (BuiltTask("analyst", "medium", _learning, tier="analysis"),)),
    AgentSpec("match", "The Match Agent: signals and an evaluation per candidate for the families of goals and result; its context mode takes "
              "over from brief-v8.",
              (BuiltTask("context", router.SPECS["context"].effort, _match_context, model=router.MODELS[router.SPECS["context"].level]),
               BuiltTask("evaluation", router.SPECS["evaluation"].effort, _match_assess, model=router.MODELS[router.SPECS["evaluation"].level])),
              contract=ASSESSMENT, reads="match"),
    AgentSpec("stats", "The Statistics Agent: an evaluation per candidate for the families of counts (corners and cards of the whole match), from the stats slice. "
              "It runs in shadow in the LAB and feeds the Council only inside the shadow arms; its answers reach no decision until the owner signs a row in "
              "intel.promotions for its family.",
              (BuiltTask("evaluation", router.SPECS["evaluation"].effort, _stats_assess, model=router.MODELS[router.SPECS["evaluation"].level]),),
              contract=ASSESSMENT, reads="stats"),
    AgentSpec("council", "The Council: the one verdict per selection of a match, in codes (cd-v1), from the compact view of the numbers, the assessments, the "
              "contradictions and the evidence index. Sonnet reads every match; Opus only the cases a rule of router-v1 escalates (E1-E7); the Haiku arm of the "
              "experiment (ma-v1-h) reads the same prompt, so the registry pins the task's own model.",
              (BuiltTask("council", router.SPECS["council"].effort, _council, model=router.MODELS[router.SPECS["council"].level]),
               BuiltTask("escalation", router.SPECS["escalation"].effort, _council_opus,
                         model=router.MODELS[router.SPECS["escalation"].level])),
              contract=COUNCIL, reads="council_view"),
    AgentSpec("pmr", "The Post-Match Reviewer (phase 5): after the result, the class of the misses the attribution of the code left UNKNOWN and a short "
              "narrative for the owner, in pmr-v1. Haiku for the narrative, Sonnet for the losses worth explaining; Batch, LAB. It runs beside "
              "post_match_reviewer (pick-postmortem-v4) and takes over from it only by the owner's signature.",
              (BuiltTask("narrative", router.SPECS["narrative"].effort, _pmr, model=router.MODELS[router.SPECS["narrative"].level]),
               BuiltTask("loss_review", router.SPECS["loss_review"].effort, _pmr, model=router.MODELS[router.SPECS["loss_review"].level])),
              contract=POST_MATCH, reads="settled_match", replaces="post_match_reviewer"),
    AgentSpec("la", "The Learning Analyst (phase 5): at most five hypotheses a week, each for one version of one agent and each citing the attributions "
              "it rests on, in la-v1. It only proposes. Sonnet; Batch, LAB, Mondays. It runs beside learning_analyst (learning-v2) and takes over from "
              "it only by the owner's signature.",
              (BuiltTask("analyst", router.SPECS["analyst"].effort, _la, model=router.MODELS[router.SPECS["analyst"].level]),),
              contract=LEARNING, reads="week", replaces="learning_analyst"),
)

PLANNED: Final[tuple[PlannedAgent, ...]] = (
)

POSTPONED: Final[tuple[PostponedAgent, ...]] = (
    PostponedAgent("player", "The Player Agent: props of a player (goals, assists, shots, cards, saves). No tokens and no code until its gate F-Player.",
                   "F-Player (plan, section 14): a market with a validated model, a settlement rule and a reference price"),
)

REGISTERED = datetime(2026, 10, 25, 16, 0, tzinfo=UTC)
BASELINE_NOTE: Final = ("Baseline of the registry (25 Oct 2026): the prompt and schema in force in production when the registry was started, in the "
                        "engine llm. The decision to run it was taken before the registry existed; this entry records it after the fact.")


def _baseline(agent: str, version: str, fingerprint: str, parts: Mapping[str, Part], since: str) -> Registration:
    return Registration(agent, version, REGISTERED, "system", "IA-1", f"{BASELINE_NOTE} {version}: {since}.", fingerprint, parts,
                        born_as="CHAMPION", baseline=True)


LEDGER: Final[tuple[Registration, ...]] = (
    _baseline("brief", "brief-v8", "ag4aefd93b43", {"context": Part("brief-v8", "f19c03954c60", "brief-v8", "b8cc54533409")},
              "the first reading of the day since plan F6 (pre-match v3)"),
    _baseline("reviewer", "review-v2", "ag7681a6f04f", {
        "review_analysis": Part("review-v2", "65f287206c7b", "review-v2", "43b62578845d"),
        "review_final": Part("review-v2", "65f287206c7b", "review-v2", "43b62578845d")},
              "one prompt for L2 and L3, asked with a set effort, since 8 Oct 2026"),
    _baseline("extractor", "extract-v1", "agba25dbdfaa", {"extraction": Part("extract-v1", "3b74a2baf341", "extract-v1", "602ce229861c")},
              "the extraction of who can play from search results"),
    _baseline("postmortem", "postmortem-v3", "agbd3b7e47cc", {"narrative": Part("postmortem-v3", "3d60dc899e4e", "postmortem-v3", "165677842852")},
              "the narrative of a finished match, since 9 Oct 2026"),
    _baseline("post_match_reviewer", "pick-postmortem-v4", "ag5ce7d821af", {
        "loss_review": Part("pick-postmortem-v4", "9f595a8945e6", "pick-postmortem-v4", "bc72b026a5ae"),
        "narrative": Part("pick-postmortem-v4", "9f595a8945e6", "pick-postmortem-v4", "bc72b026a5ae")},
              "the narrative of a selection, with the two price numbers named apart, since 22 Oct 2026 (plan F0, defect 7)"),
    _baseline("learning_analyst", "learning-v2", "ag23805385d8", {"analyst": Part("learning-v2", "7bdb67711a7d", "learning-v2", "1ea34b6c1585")},
              "the weekly lessons, since 9 Oct 2026"),
    Registration(agent="claim_extractor", version="extract-v2", registered_at=datetime(2026, 10, 26, 5, 30, tzinfo=UTC), decided_by="owner", phase="IA-2",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 2, section 8): the extractor of the Research Service v2 answers in "
                        "claim-v1 about subjects the server lists, one research per entity and topic; it runs beside extract-v1 for a week of comparison "
                        "and becomes the champion only by a row the owner signs.",
                 fingerprint="ag851f0d8c93",
                 parts={"extraction": Part("extract-v2", "16a3d6d616f2", "claim-v1", "732492401844")}),
    Registration(agent="match", version="match-v1", registered_at=datetime(2026, 11, 3, 12, 0, tzinfo=UTC), decided_by="owner", phase="IA-3",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 3, section 9): the Match Agent reads the match slice of mcp-v1 "
                        "and answers in aa-v1, a context mode and an evaluation per candidate, both on Haiku 5.5. It is born CHALLENGER: it runs in "
                        "shadow in the LAB workspace and its answers reach no decision until the owner signs a row in intel.promotions.",
                 fingerprint="ag23a84c189f",
                 parts={"context": Part("match-context-v1", "e055ea4d9bc1", "aa-v1", "ab5f098304ef"),
                        "evaluation": Part("match-assess-v1", "f360df0b38ae", "aa-v1", "ab5f098304ef")}),
    Registration(agent="match", version="match-v2", registered_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC), decided_by="owner", phase="IA-009",
                 reason="IA-009: 28 of the 66 shadow runs of match-v1 (42 %, measured from 3 to 6 Nov 2026) were refused by aa-v1 - a key the "
                        "contract does not have, a signal code out of the list, more than 8 refs - and gate B allows 3 %. The same rules and tasks "
                        "end with an output checklist written from the contract's enums and caps (match-context-v2, match-assess-v2); the contract, "
                        "the reader, the model and the effort do not change. It is born CHALLENGER and runs in shadow in place of match-v1; it "
                        "reaches a decision only by a row the owner signs in intel.promotions.",
                 fingerprint="agc09b002b34",
                 parts={"context": Part("match-context-v2", "528be450eb83", "aa-v1", "ab5f098304ef"),
                        "evaluation": Part("match-assess-v2", "efab832be700", "aa-v1", "ab5f098304ef")}),
    Registration(agent="match", version="match-v3", registered_at=datetime(2026, 11, 7, 16, 0, tzinfo=UTC), decided_by="owner", phase="IA-014",
                 reason="IA-014: 20 of the 250 answered shadow runs of match-v2 (8.0 %, measured from 6 Nov 16:55 to 7 Nov 15:00 UTC) were refused "
                        "by aa-v1 - a key at the top level, a reference the package does not have, a signal code out of the list, a pair written "
                        "twice, nine refs - and gate B allows 3 %. The same rules and tasks; the message now lists the references of the package "
                        "(written by the server) and the checklist (match-context-v3, match-assess-v3) says to copy them, one signal per code and "
                        "direction, and never a key of the second object. The contract, the reader, the model and the effort do not change. It is "
                        "born CHALLENGER and runs in shadow in place of match-v2; it reaches a decision only by a row the owner signs in "
                        "intel.promotions.",
                 fingerprint="ag7b031b5901",
                 parts={"context": Part("match-context-v3", "b63b15a78ecf", "aa-v1", "ab5f098304ef"),
                        "evaluation": Part("match-assess-v3", "6eb32492e520", "aa-v1", "ab5f098304ef")}),
    Registration(agent="council", version="council-v1", registered_at=datetime(2026, 11, 3, 11, 0, tzinfo=UTC), decided_by="owner", phase="IA-3",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 3, section 11): the Council gives the one verdict per selection "
                        "in cd-v1, Sonnet for every match and Opus only where a rule of router-v1 escalates; it is born CHALLENGER, runs in shadow in the "
                        "LAB and becomes the champion only by a row the owner signs.",
                 fingerprint="ag0ba76f3e1c",
                 parts={"council": Part("council-v1", "25ba480edcbb", "cd-v1", "f9b614bec399"),
                        "escalation": Part("council-opus-v1", "1eb30e6112e6", "cd-v1", "f9b614bec399")}),
    Registration(agent="stats", version="stats-v1", registered_at=datetime(2026, 11, 3, 18, 0, tzinfo=UTC), decided_by="owner", phase="IA-4",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 4, section 10): the Statistics Agent reads the stats slice of mcp-v1 "
                        "and answers in aa-v1, an evaluation per candidate of corners and cards of the whole match, on Haiku 5.5 at effort medium. It is born "
                        "CHALLENGER: it runs in shadow in the LAB workspace, feeds the Council only inside the shadow arms and its answers reach no decision "
                        "until the owner signs a row in intel.promotions for its family.",
                 fingerprint="aga50a72bba7",
                 parts={"evaluation": Part("stats-assess-v1", "3e902d08074b", "aa-v1", "ab5f098304ef")}),
    Registration(agent="stats", version="stats-v2", registered_at=datetime(2026, 11, 6, 12, 1, tzinfo=UTC), decided_by="owner", phase="IA-009",
                 reason="IA-009: the Statistics Agent answers in the same aa-v1 whose Match Agent prompts had 42 % of their shadow answers refused; "
                        "before it is switched on, its prompt (stats-assess-v2) ends with the same output checklist written from the contract, with "
                        "its own signal codes and directions and research always []. Contract, reader, model and effort do not change. It is born "
                        "CHALLENGER, runs in shadow in place of stats-v1 and reaches a decision only by a row the owner signs in intel.promotions.",
                 fingerprint="aga044ea3270",
                 parts={"evaluation": Part("stats-assess-v2", "c5747a251230", "aa-v1", "ab5f098304ef")}),
    Registration(agent="pmr", version="pmr-v1", registered_at=datetime(2026, 11, 3, 13, 0, tzinfo=UTC), decided_by="owner", phase="IA-5",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 5, section 12): after the result, the class of the misses the "
                        "attribution of the code left UNKNOWN and a short narrative, in pmr-v1, Haiku for the narrative and Sonnet for the losses worth "
                        "explaining, in the Batch of the LAB. It is born CHALLENGER and takes over from pick-postmortem-v4 only by a row the owner signs.",
                 fingerprint="ag1181bf8275",
                 parts={"loss_review": Part("pmr-v1", "1a3e7572d971", "pmr-v1", "a57a3df3f837"),
                        "narrative": Part("pmr-v1", "1a3e7572d971", "pmr-v1", "a57a3df3f837")}),
    Registration(agent="la", version="la-v1", registered_at=datetime(2026, 11, 3, 13, 1, tzinfo=UTC), decided_by="owner", phase="IA-5",
                 reason="Built under the Plan Maestro IA the owner approved in full (phase 5, section 13): once a week, at most five hypotheses, each for "
                        "one version of one agent and each citing the attributions it rests on, in la-v1, Sonnet, in the Batch of the LAB. It only "
                        "proposes; it is born CHALLENGER and takes over from learning-v2 only by a row the owner signs.",
                 fingerprint="agcf22e218b2",
                 parts={"analyst": Part("la-v1", "e3746420c593", "la-v1", "1daff1cc3c97")}),
)
"""Oldest first, by agent; the last entry of an agent is its version in force. To change an agent - a prompt, a schema, a model, an effort - change
it, add the entry below the last one of the agent and bump the label of the prompt that changed, in the same commit."""


# -- the registry ----------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Registry:
    agents: tuple[AgentSpec, ...] = AGENTS
    planned: tuple[PlannedAgent, ...] = PLANNED
    postponed: tuple[PostponedAgent, ...] = POSTPONED
    ledger: tuple[Registration, ...] = LEDGER

    def spec(self, agent: str) -> AgentSpec:
        for spec in self.agents:
            if spec.agent == agent:
                return spec
        raise RegistryError(f"{agent!r} is not an agent the code has")

    def history(self, agent: str) -> tuple[Registration, ...]:
        return tuple(r for r in self.ledger if r.agent == agent)

    def in_force(self, agent: str) -> Registration:
        """The registration of the version the code has of an agent: the last one."""
        history = self.history(agent)
        if not history:
            raise RegistryError(f"{agent!r} has no entry in the ledger")
        return history[-1]

    def identity_for(self, agent: str, task: str, *, workspace: Workspace, input_version: str, input_hash: str, pass_kind: PassKind,
                     fixture_id: int, candidates: Sequence[str] = (), model: str | None = None) -> TaskIdentity:
        """The identity of a task of an agent - what ``idem_key`` is made of - from the registry's own row, so that the six fields that say WHICH
        agent asks the question cannot be written by hand. ``model`` is the router's choice for an arm that judges with another model than the
        task's own; a task of the old route (a tier, not a model) needs it."""
        spec = self.spec(agent)
        built = next((t for t in spec.tasks if t.task == task), None)
        if built is None:
            raise RegistryError(f"{agent!r} does not run a task {task!r}")
        chosen = model or built.model
        if chosen is None:
            raise RegistryError(f"{agent}/{task} runs on a tier ({built.tier}), not on a model: say which model")
        if ("anthropic", chosen) not in PRICES:
            raise RegistryError(f"{chosen!r} is not in the price list: a model nobody can bill")
        definition = built.definition()
        return TaskIdentity(workspace=workspace, agent=agent, agent_version=self.in_force(agent).version,
                            prompt_version=definition.prompt_version, schema_version=definition.schema_version, model=chosen, effort=built.effort,
                            input_version=input_version, input_hash=input_hash, pass_kind=pass_kind, fixture_id=fixture_id,
                            candidates=tuple(sorted(candidates)))

    def problems(self, *, prompt_versions: Mapping[str, str] | None = None) -> list[Problem]:
        """Every way the registry disagrees with the code or with itself (all of them, not the first). Empty when it holds."""
        found: list[Problem] = []
        labels = live_prompt_versions() if prompt_versions is None else dict(prompt_versions)
        found += self._agent_problems()
        found += self._ledger_problems()
        found += self._label_problems()
        found += self._planned_problems(set(labels.values()))
        found += self._coverage_problems(labels)
        return found

    def _agent_problems(self) -> list[Problem]:
        found: list[Problem] = []
        seen: set[str] = set()
        for spec in self.agents:
            who = spec.agent
            if not AGENT_ID.fullmatch(who):
                found.append(Problem("agent_id", who, "an agent is named in lower-case words joined by _"))
            if who in seen:
                found.append(Problem("duplicate_agent", who, "two agents with one name"))
            seen.add(who)
            found += _spec_shape_problems(spec)
            if spec.replaces is not None and (spec.replaces == who or spec.replaces not in {s.agent for s in self.agents}):
                found.append(Problem("replaces", who, f"{spec.replaces!r} is not another agent of the registry: an agent takes over from one the code has"))
            try:
                parts = live_parts(spec)
            except Exception as exc:  # the definition reads the code: whatever is wrong with it is a finding, not a crash
                found.append(Problem("definition", who, f"the live definition cannot be read: {type(exc).__name__}: {exc}"))
                continue
            history = self.history(who)
            if not history:
                found.append(Problem("unregistered", who, "the code has this agent and the ledger has no entry for it. Add:\n" + stub(spec, "<version>")))
                continue
            current = history[-1]
            live = fingerprint_of(spec, parts)
            if live != current.fingerprint:
                found.append(Problem(
                    "fingerprint", who, f"the code fingerprints as {live} and the ledger has {current.fingerprint} ({current.version}) in force: a prompt, "
                    "a schema, a model or an effort changed without a new version. Add this entry to LEDGER (and bump the label of the prompt that "
                    "changed in fbi.ai.prompts):\n" + stub(spec, "<the new version>")))
        return found

    def _ledger_problems(self) -> list[Problem]:
        found: list[Problem] = []
        known = {s.agent for s in self.agents}
        for r in self.ledger:
            who = f"{r.agent}/{r.version}"
            if r.agent not in known:
                found.append(Problem("orphan", who, "an entry of the ledger for an agent the code does not have"))
            if not VERSION_LABEL.fullmatch(r.version):
                found.append(Problem("version_label", who, "a version is named like its prompt: words joined by -, then -v and a number"))
            if not FINGERPRINT.fullmatch(r.fingerprint):
                found.append(Problem("fingerprint_form", who, f"{r.fingerprint!r} is not a fingerprint (ag and ten hex digits)"))
            if r.registered_at.tzinfo is None:
                found.append(Problem("registered_at", who, "a moment with its zone"))
            if r.decided_by not in DECIDERS:
                found.append(Problem("decided_by", who, f"{r.decided_by!r} is not one of {DECIDERS}"))
            if not r.phase.strip():
                found.append(Problem("phase", who, "the phase of the plan that decided it"))
            if len(r.reason) < MIN_REASON:
                found.append(Problem("reason", who, "a registration without a reason is not a decision"))
            if (r.born_as == "CHAMPION") != r.baseline:
                found.append(Problem("born_as", who, "only the baseline of an agent that was already in force is born CHAMPION; a new version is born CHALLENGER"))
            if not r.parts:
                found.append(Problem("parts", who, "an entry keeps the labels and hashes of every task of the version"))
            for task, p in r.parts.items():
                if not (SHA12.fullmatch(p.prompt_sha) and SHA12.fullmatch(p.schema_sha)):
                    found.append(Problem("sha", f"{who}/{task}", "twelve hex digits for each text"))
        for agent in {r.agent for r in self.ledger}:
            history = self.history(agent)
            versions = [r.version for r in history]
            if len(set(versions)) != len(versions):
                found.append(Problem("duplicate_version", agent, "a version is registered once"))
            moments = [r.registered_at for r in history if r.registered_at.tzinfo is not None]
            if moments != sorted(set(moments)):
                found.append(Problem("order", agent, "oldest first, and never two at one moment"))
            if any(r.baseline for r in history[1:]):
                found.append(Problem("baseline", agent, "only the first entry of an agent can be the baseline"))
        return found

    def _label_problems(self) -> list[Problem]:
        """A prompt label never names two texts, and a schema label never two schemas: across the whole ledger and the code as it is."""
        seen: dict[tuple[str, str], set[str]] = {}
        for r in self.ledger:
            for p in r.parts.values():
                seen.setdefault(("prompt", p.prompt_version), set()).add(p.prompt_sha)
                seen.setdefault(("schema", p.schema_version), set()).add(p.schema_sha)
        for spec in self.agents:
            for p in _safe_parts(spec).values():  # a definition that cannot be read is said by _agent_problems
                seen.setdefault(("prompt", p.prompt_version), set()).add(p.prompt_sha)
                seen.setdefault(("schema", p.schema_version), set()).add(p.schema_sha)
        return [Problem("label_text", label, f"the {kind} label {label!r} names {len(shas)} different texts: it was edited in place. A changed {kind} "
                        f"is a NEW version (a new label in fbi.ai.prompts), never an edit")
                for (kind, label), shas in sorted(seen.items()) if len(shas) > 1]

    def _planned_problems(self, live_labels: set[str]) -> list[Problem]:
        found: list[Problem] = []
        label_owner: dict[str, str] = {}
        registered = {(r.agent, r.version) for r in self.ledger}
        for plan in self.planned:
            who = f"{plan.agent}/{plan.version}"
            if not AGENT_ID.fullmatch(plan.agent):
                found.append(Problem("agent_id", who, "an agent is named in lower-case words joined by _"))
            if not VERSION_LABEL.fullmatch(plan.version):
                found.append(Problem("version_label", who, "words joined by -, then -v and a number"))
            if (plan.agent, plan.version) in registered:
                found.append(Problem("planned_is_built", who, "this version is in the ledger: it is built, take it out of PLANNED"))
            if not 2 <= plan.phase <= 10:
                found.append(Problem("phase", who, "a phase of the plan after the one that creates the registry"))
            if plan.contract not in OUTPUTS:
                found.append(Problem("contract", who, f"{plan.contract!r} is not a contract an agent answers in ({', '.join(OUTPUTS)})"))
            if plan.reads is not None and plan.reads not in SLICE_NAMES and plan.reads not in VIEWS:
                found.append(Problem("reads", who, f"{plan.reads!r} is neither a slice of the package nor a view"))
            if plan.replaces is not None and plan.replaces not in {r.version for r in self.history(plan.agent)}:
                found.append(Problem("replaces", who, f"{plan.replaces!r} is not a version of {plan.agent} in the ledger"))
            if not plan.tasks or len({t.task for t in plan.tasks}) != len(plan.tasks):
                found.append(Problem("tasks", who, "at least one task, and each named once"))
            for t in plan.tasks:
                found += _planned_task_problems(who, t)
                if t.prompt_version in live_labels:
                    found.append(Problem("planned_is_built", f"{who}/{t.task}", f"the prompt {t.prompt_version!r} is in fbi.ai.prompts: the agent is "
                                         "built, move it from PLANNED to AGENTS with its entry in the ledger"))
                if label_owner.setdefault(t.prompt_version, plan.agent) != plan.agent:
                    found.append(Problem("planned_label", f"{who}/{t.task}", f"the label {t.prompt_version!r} is already another agent's"))
        return found

    def _coverage_problems(self, labels: Mapping[str, str]) -> list[Problem]:
        found: list[Problem] = []
        built: set[str] = set()
        for spec in self.agents:
            built |= {p.prompt_version for p in _safe_parts(spec).values()}
        for name, label in sorted(labels.items()):
            if label not in built:
                found.append(Problem("prompt_unregistered", name, f"fbi.ai.prompts declares {label!r} and no agent of the registry uses it: a prompt "
                                     "outside the registry is a prompt nobody decided"))
        served = {t.task for s in self.agents for t in s.tasks} | {t.task for p in self.planned for t in p.tasks}
        for task in router.TASKS:
            if task not in served and task not in UNSERVED_TASKS:
                found.append(Problem("task_unserved", task, "a task of the router that no agent of the registry runs or will run"))
        contracts = {s.contract for s in self.agents} | {p.contract for p in self.planned}
        for contract in OUTPUTS:
            if contract not in contracts:
                found.append(Problem("contract_unwritten", contract, "a contract that no agent of the registry answers in"))
        taken = {s.agent for s in self.agents} | {p.agent for p in self.planned}
        for post in self.postponed:
            if post.agent in taken:
                found.append(Problem("postponed_is_built", post.agent, "a postponed agent has code or a phase in the plan: it is not postponed"))
            if not AGENT_ID.fullmatch(post.agent) or not post.gate.strip():
                found.append(Problem("postponed", post.agent, "a name and the gate that has to pass first"))
        return found

    def snapshot(self) -> list[dict[str, Any]]:
        """The registry as plain data, for the administrator's tab: built agents with the version in force, then planned ones, then postponed ones."""
        out: list[dict[str, Any]] = []
        for spec in self.agents:
            history = self.history(spec.agent)
            current = history[-1] if history else None
            planned = next((p for p in self.planned if p.agent == spec.agent), None)
            tasks = []
            for t in spec.tasks:
                d = t.definition()
                tasks.append({"task": t.task, "prompt_version": d.prompt_version, "schema_version": d.schema_version, "model": t.model, "tier": t.tier,
                              "effort": t.effort})
            out.append({"agent": spec.agent, "status": "built", "purpose": spec.purpose, "contract": spec.contract, "reads": spec.reads,
                        "retire_phase": spec.retire_phase, "version": current.version if current else None,
                        "fingerprint": current.fingerprint if current else None, "born_as": current.born_as if current else None,
                        "baseline": current.baseline if current else None,
                        "registered_at": current.registered_at.isoformat() if current else None,
                        "in_sync": current is not None and live_fingerprint(spec) == current.fingerprint, "tasks": tasks,
                        "next_version": planned.version if planned else None, "next_phase": planned.phase if planned else None,
                        "replaces": spec.replaces, "history": [r.version for r in history]})
        for plan in self.planned:
            out.append({"agent": plan.agent, "status": "planned", "purpose": plan.purpose, "contract": plan.contract, "reads": plan.reads,
                        "version": plan.version, "phase": plan.phase, "replaces": plan.replaces,
                        "tasks": [{"task": t.task, "prompt_version": t.prompt_version, "model": t.model, "effort": t.effort} for t in plan.tasks]})
        for post in self.postponed:
            out.append({"agent": post.agent, "status": "postponed", "purpose": post.purpose, "gate": post.gate})
        return out


def _safe_parts(spec: AgentSpec) -> dict[str, Part]:
    try:
        return live_parts(spec)
    except Exception:
        return {}


def _spec_shape_problems(spec: AgentSpec) -> list[Problem]:
    found: list[Problem] = []
    who = spec.agent
    if not spec.tasks or len({t.task for t in spec.tasks}) != len(spec.tasks):
        found.append(Problem("tasks", who, "at least one task, and each named once"))
    if spec.contract is not None and spec.contract not in CONTRACTS:
        found.append(Problem("contract", who, f"{spec.contract!r} is not a contract an agent answers in"))
    if spec.reads is not None and spec.reads not in SLICE_NAMES and spec.reads not in VIEWS:
        found.append(Problem("reads", who, f"{spec.reads!r} is neither a slice of the package nor a view"))
    for t in spec.tasks:
        if (t.model is None) == (t.tier is None):
            found.append(Problem("task_runs_on", f"{who}/{t.task}", "exactly one of a model (an agent of the plan) and a tier (the old route)"))
        if t.model is not None and ("anthropic", t.model) not in PRICES:
            found.append(Problem("model", f"{who}/{t.task}", f"{t.model!r} is not in the price list: a model nobody can bill"))
        if t.tier is not None and t.tier not in TIERS:
            found.append(Problem("tier", f"{who}/{t.task}", f"{t.tier!r} is not one of {TIERS}"))
        if t.effort not in EFFORTS:
            found.append(Problem("effort", f"{who}/{t.task}", f"{t.effort!r} is not one of {EFFORTS}"))
    return found


def _planned_task_problems(who: str, t: PlannedTask) -> list[Problem]:
    found: list[Problem] = []
    spec = router.SPECS.get(t.task)
    if spec is None:
        return [Problem("task", f"{who}/{t.task}", f"{t.task!r} is not a task of the router ({', '.join(router.TASKS)})")]
    if t.model != router.MODELS[spec.level]:
        found.append(Problem("model", f"{who}/{t.task}", f"the router runs {t.task} on {router.MODELS[spec.level]}, the plan registers {t.model}"))
    if t.effort != spec.effort:
        found.append(Problem("effort", f"{who}/{t.task}", f"the router runs {t.task} at {spec.effort}, the plan registers {t.effort}"))
    if not VERSION_LABEL.fullmatch(t.prompt_version):
        found.append(Problem("prompt_label", f"{who}/{t.task}", "a prompt is named like a version: words joined by -, then -v and a number"))
    return found


REGISTRY: Final = Registry()
"""The registry of the code as it is."""


# -- the names of the promotions -------------------------------------------------------------------------------------------------------

PROMOTION_NAME: Final = re.compile(r"^(?P<agent>[a-z][a-z0-9]*(?:_[a-z0-9]+)*)@(?P<version>[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v[1-9][0-9]{0,2})"
                                   r"(?P<upstream>(?:\+[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v[1-9][0-9]{0,2})*)$")


@dataclass(frozen=True, slots=True)
class PromotionName:
    agent: str
    version: str
    upstream: tuple[str, ...] = ()

    def __str__(self) -> str:
        return promotion_name(self.agent, self.version, self.upstream)


def promotion_name(agent: str, version: str, upstream: Sequence[str] = ()) -> str:
    """The ``model_name`` of a row of ``intel.promotions`` whose entity is ``agent``: the agent, its version and - for an agent that reads the answers
    of others - the versions of those, sorted (``council@council-v1+match-v1``). A promotion is of the pipeline a verdict came through, not of the last
    agent alone."""
    name = f"{agent}@{version}" + "".join(f"+{u}" for u in sorted(set(upstream)))
    if not PROMOTION_NAME.fullmatch(name):
        raise RegistryError(f"{name!r} is not the name of a promotion: agent@version[+upstream version...]")
    return name


def parse_promotion_name(name: str) -> PromotionName:
    match = PROMOTION_NAME.fullmatch(name)
    if match is None:
        raise RegistryError("not the name of a promotion: agent@version[+upstream version...]")
    upstream = tuple(u for u in match["upstream"].split("+") if u)
    return PromotionName(match["agent"], match["version"], upstream)

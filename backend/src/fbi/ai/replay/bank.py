"""Which stored runs of the shadow can be asked again exactly as they were asked (IA-047): the bank. Read-only.

A run of ``ai.agent_runs`` (``run_kind = 'shadow'``, with an answer that was paid: ``ok``, ``abstain`` or
``invalid``) is ADMITTED when the code in force derives again, byte for byte, everything its question was
made of, and proves it with the hashes the shadow stored:

1. the run's agent, version, prompt, schema, model and effort are the registry's in force for its task
   (``REGISTRY.identity_for``): the variant is the one that ran;
2. the shadow's state of the pass (``ai.match_runs``, the same match, pass and moment) names the same package,
   whose stored packet is derived again by ``fbi.ai.package.derive`` with the version and the model code the
   state names - with the leak audit's second reading when the forecasts of the counts were not visible yet
   (``fbi.intel.leakage``) - into the very ``package_hash`` of the run;
3. the slice the agent read is cut again into its ``slice_hash`` (the set of slices the state names);
4. the candidates are named again as the pass named them: the ``rules`` reviews of that packet written by the
   start of the run (``orchestrator_store.REVIEWED_SQL`` read as of that moment) and, with the Statistics
   Agent on, the families' decisions known by the moment of the pass, which must be the ones the state lists;
5. the findings of ``contra-v1`` are detected again; for the Council, over the stored answers of the agents of
   the same pass that stood (what it read as ``A:<label>``), and its view (``council-view-v1``) is built again;
6. the identity of the task (``fbi.ai.idempotency``: the agent row, the slice or the view hash, the pass, the
   match and the candidates) is the run's ``idem_key``, and the hash of the request
   (``match.input_hash``, ``stats.input_hash``, ``player.input_hash``, ``council.input_hash``) is the
   ``input_hash`` the ledger recorded for the call (``ai.usage``);
7. no optimisation that shapes a request (the gates ``batch``, ``native_schema``, ``cache_layout`` and the
   owner's switches of them) changed after the run started.

Every other run is EXCLUDED and counted with one closed code (``REASONS``). The escalation to Opus is out of
this version of the bank (``escalation_out_of_bank``): its question is built from the first round of the
Council and the rules the router fired, it is at most three a day, and the plan's first variants are of the
agents and of the Council's own round.

Nothing here writes, calls a model or reads a clock: ``build`` reads with the caller's connection and returns
what it found. A failure of one pass (a packet written by hand, a version this code cannot derive) excludes the
runs of that pass with its code and never stops the others; a failure of the DATABASE is raised (it is no
verdict about a run).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, cast

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import contra
from fbi.ai import package as mcp_package
from fbi.ai.agents import council, match, player, stats
from fbi.ai.agents.common import (
    Assessed,
    Contradiction,
    Naming,
    assessment_label,
    name_candidates,
    name_with_counts,
)
from fbi.ai.agents.registry import REGISTRY, RegistryError
from fbi.ai.contracts.assessment import AssessmentOut
from fbi.ai.contracts.mcp import DEFAULT_SLICE_SET, SLICE_SETS, PassKind
from fbi.ai.contracts.player import PlayerAssessmentOut
from fbi.ai.gate_a import OPTIMISATIONS
from fbi.ai.idempotency import IdempotencyError, TaskIdentity
from fbi.ai.orchestrator_store import REVIEWED_SQL, family_counts
from fbi.ai.providers.base import JsonRequest
from fbi.ai.replay import VERSION
from fbi.ai.review import Candidate

# -- what the bank speaks of ------------------------------------------------------------------------------------------------

AGENTS: Final = (match.AGENT, stats.AGENT, player.AGENT, council.AGENT)
ARMS: Final[dict[str, tuple[council.CouncilLevel, bool]]] = {
    "ma-v1": ("complex", True), "ma-v1-h": ("simple", True), "cs-v1": ("complex", False)}
"""The Council's arms of the shadow (``fbi.ai.orchestrator.ENGINE_LEVEL`` and ``WITH_MATCH``): the level that judges
and whether its view carries the other agents' assessments."""
SCOPES: Final = ("match/context", "match/evaluation", "stats/evaluation", "player/evaluation", "council/ma-v1",
                 "council/ma-v1-h", "council/cs-v1")
"""What the bank measures apart: one agent's task, or one arm of the Council."""
PAID: Final = ("ok", "abstain", "invalid")
REASONS: Final = (
    "escalation_out_of_bank", "agent_out_of_bank", "version_not_in_force", "prompt_not_in_force", "schema_not_in_force",
    "model_not_in_force", "effort_not_in_force", "optimisations_changed_since", "no_state_of_the_pass",
    "state_names_another_package", "known_at_after_kickoff", "package_version_not_derivable", "packet_missing",
    "packet_of_another_match", "package_leak", "package_not_rebuilt", "slice_set_unknown", "slice_not_rebuilt",
    "counts_not_rebuilt", "naming_not_rebuilt", "assessment_unreadable", "input_not_rebuilt", "request_hash_unknown",
    "request_not_rebuilt", "rebuild_failed")
"""Why a stored run is not in the bank, in the order the checks are made (the first that applies is the one
said). ``rebuild_failed`` carries the type of the error after a colon."""
SHA256_ZERO: Final = "0" * 64

# -- reading -----------------------------------------------------------------------------------------------------------------

RUNS_COLUMNS: Final = """
SELECT r.id, r.fixture_id, r.pass_kind, r.task_kind, r.known_at, r.started_at, r.agent, r.agent_version, r.prompt_version,
       r.schema_version, r.model, r.effort, r.idem_key, r.package_hash, r.slice_hash, r.candidates, r.status, r.output,
       r.cost_usd, r.batch_id IS NOT NULL AS in_batch, r.input_tokens, r.output_tokens, u.input_hash AS request_hash,
       m.id AS state_id, m.packet_id, m.package_version, m.package_hash AS state_package_hash, m.model_status,
       f.kickoff_at, p.built_at AS packet_built_at
  FROM ai.agent_runs r
  LEFT JOIN ai.usage u ON u.id = r.usage_id
  LEFT JOIN ai.match_runs m
         ON m.fixture_id = r.fixture_id AND m.run_kind = 'shadow' AND m.pass_kind = r.pass_kind AND m.known_at = r.known_at
  LEFT JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN ai.match_packets p ON p.id = m.packet_id
"""
RUNS_SQL: Final = RUNS_COLUMNS + """
 WHERE r.run_kind = 'shadow' AND r.status = ANY(%(paid)s) AND r.fixture_id IS NOT NULL
   AND r.started_at >= %(since)s AND r.started_at < %(until)s
 ORDER BY r.id
 LIMIT %(limit)s
"""
"""The paid runs of the shadow that STARTED in a window, with the ledger's hash of their request and the
shadow's state of their pass. Joins by primary key and by the unique key of ``ai.match_runs`` only."""
RUNS_BY_ID_SQL: Final = RUNS_COLUMNS + """
 WHERE r.run_kind = 'shadow' AND r.status = ANY(%(paid)s) AND r.id = ANY(%(ids)s)
 ORDER BY r.id
"""
PASS_RUNS_SQL: Final = """
SELECT r.agent, r.task_kind, r.slice_hash, r.output
  FROM ai.agent_runs r
 WHERE r.run_kind = 'shadow' AND r.status = 'ok' AND r.fixture_id = %(fixture)s AND r.pass_kind = %(pass)s
   AND r.known_at = %(known)s AND r.agent = ANY(%(agents)s)
 ORDER BY r.id
"""
"""The answers that stood of the agents of one pass: what the Council of the arms that read assessments read."""

_REVIEWED_ANCHOR: Final = "AND r.p_model IS NOT NULL"
if REVIEWED_SQL.count(_REVIEWED_ANCHOR) != 1:  # pragma: no cover - a guard on the text this module builds on
    raise RuntimeError("orchestrator_store.REVIEWED_SQL changed shape: the replay bank reads it as of a moment")
REVIEWED_AS_OF_SQL: Final = REVIEWED_SQL.replace(_REVIEWED_ANCHOR, _REVIEWED_ANCHOR + " AND r.reviewed_at <= %(at)s")
"""``orchestrator_store.REVIEWED_SQL`` - the selections production reviewed in the pass - with the reviews written by
the start of the run only: a review written later is not what the pass read."""

OPTIMISATION_ROWS_SQL: Final = """
SELECT gate, at, passed, evidence FROM ai.feature_gates WHERE gate = ANY(%(gates)s) ORDER BY at, id
"""
SWITCH_WORDS: Final = ("batch", "cache", "native_schema")
"""The owner's switches that shape a request (``gates.SWITCH_ENV``; ``cache`` also decides the layout)."""


@dataclass(frozen=True, slots=True)
class StoredRun:
    """A paid run of the shadow as the database keeps it, with the state of its pass."""

    id: int
    fixture_id: int
    pass_kind: str
    task_kind: str
    known_at: datetime
    started_at: datetime
    agent: str
    agent_version: str
    prompt_version: str
    schema_version: str
    model: str | None
    effort: str | None
    idem_key: str
    package_hash: str | None
    slice_hash: str | None
    candidates: tuple[str, ...]
    status: str
    output: dict[str, Any] | None
    cost: Decimal = Decimal(0)
    in_batch: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_hash: str | None = None
    state_id: int | None = None
    packet_id: int | None = None
    package_version: str | None = None
    state_package_hash: str | None = None
    model_status: Mapping[str, Any] = field(default_factory=dict)
    kickoff_at: datetime | None = None
    packet_built_at: datetime | None = None

    @classmethod
    def from_row(cls, r: Mapping[str, Any]) -> StoredRun:
        status = r["model_status"]
        return cls(
            id=int(r["id"]), fixture_id=int(r["fixture_id"]), pass_kind=str(r["pass_kind"]), task_kind=str(r["task_kind"]),
            known_at=r["known_at"], started_at=r["started_at"], agent=str(r["agent"]), agent_version=str(r["agent_version"]),
            prompt_version=str(r["prompt_version"]), schema_version=str(r["schema_version"]), model=r["model"], effort=r["effort"],
            idem_key=str(r["idem_key"]), package_hash=r["package_hash"], slice_hash=r["slice_hash"],
            candidates=tuple(r["candidates"] or ()), status=str(r["status"]),
            output=dict(r["output"]) if isinstance(r["output"], dict) else None, cost=Decimal(r["cost_usd"] or 0),
            in_batch=bool(r["in_batch"]), input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            request_hash=r["request_hash"], state_id=r["state_id"], packet_id=r["packet_id"], package_version=r["package_version"],
            state_package_hash=r["state_package_hash"], model_status=dict(status) if isinstance(status, dict) else {},
            kickoff_at=r["kickoff_at"], packet_built_at=r["packet_built_at"])

    @property
    def pass_key(self) -> tuple[int, str, datetime]:
        """One pass of the shadow: ``ai.match_runs`` has one state per match, pass and moment (``match_runs_once``)."""
        return self.fixture_id, self.pass_kind, self.known_at


def read_runs(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, limit: int = 20_000) -> list[StoredRun]:
    """The paid runs of the shadow that started in ``[since, until)``, oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RUNS_SQL, {"paid": list(PAID), "since": since, "until": until, "limit": limit})
        return [StoredRun.from_row(r) for r in cur.fetchall()]


def read_runs_by_id(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[StoredRun]:
    if not ids:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RUNS_BY_ID_SQL, {"paid": list(PAID), "ids": sorted(set(ids))})
        return [StoredRun.from_row(r) for r in cur.fetchall()]


def optimisations_changed_at(conn: psycopg.Connection[Any]) -> datetime | None:
    """The last moment an optimisation that shapes a request changed: a gate of ``gate_a.OPTIMISATIONS`` whose answer
    moved (the first row that passes, or a later row that says otherwise - ``gate_a.flips`` with its moment) or a
    row of the ledger of the owner's words whose switches of ``SWITCH_WORDS`` differ from the row before. None when
    nothing ever changed."""
    last: datetime | None = None
    state: dict[str, bool] = {}
    words: dict[str, Any] | None = None
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OPTIMISATION_ROWS_SQL, {"gates": [*OPTIMISATIONS, "switches"]})
        rows = cur.fetchall()
    for gate, at, passed, evidence in rows:
        if gate == "switches":
            said = evidence.get("words") if isinstance(evidence, dict) else None
            switches = said.get("switches") if isinstance(said, dict) else None
            now = {k: v for k, v in switches.items() if k in SWITCH_WORDS} if isinstance(switches, dict) else None
            if now is None:
                continue
            if words is not None and now != words:
                last = at
            words = now
            continue
        if bool(passed) != state.get(str(gate), False):
            last = at
        state[str(gate)] = bool(passed)
    return last


# -- the pieces of an ask ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Ask:
    """One question the code in force asks for a pass, as the orchestrator would build it."""

    scope: str
    agent: str
    task_kind: str
    identity: TaskIdentity
    request: JsonRequest
    request_hash: str
    mode: str | None = None
    """``CONTEXT`` or ``EVALUATION`` for the agents that assess; None for the Council."""
    arm: str | None = None
    view: council.CouncilView | None = None

    @property
    def key(self) -> str:
        return self.identity.key


@dataclass(frozen=True, slots=True)
class PassInputs:
    """What one pass was made of, derived again: everything a request and the reading of its answer need."""

    package: mcp_package.Package
    slices: dict[str, mcp_package.Slice]
    naming: Naming
    contra0: tuple[Contradiction, ...]
    assessed: tuple[Assessed, ...]
    contra1: tuple[Contradiction, ...]
    stats_on: bool
    player_on: bool

    @property
    def at(self) -> datetime:
        """The moment of the pass: what every request of the pass says the time is."""
        return self.slices["match"].known_at


def _identity(agent: str, task: str, inputs: PassInputs, *, input_version: str, input_hash: str, candidates: Sequence[str],
              model: str | None = None) -> TaskIdentity:
    pkg = inputs.package
    return REGISTRY.identity_for(agent, task, workspace="lab", input_version=input_version, input_hash=input_hash,
                                 pass_kind=pkg.pass_kind, fixture_id=pkg.fixture_id, candidates=candidates, model=model)


def asks_of(inputs: PassInputs) -> dict[str, Ask]:
    """Every question the orchestrator asks of a pass with these inputs (``fbi.ai.orchestrator._Runner``: the Match
    Agent's two tasks, the Statistics Agent's and the Player Agent's when they were on, and the Council of each arm),
    by idempotency key. A request the agent's module refuses to build is not a question (the orchestrator skips it).
    Pure."""
    out: dict[str, Ask] = {}
    pkg, at, naming = inputs.package, inputs.at, inputs.naming
    match_slice = inputs.slices["match"]

    def add(ask: Ask) -> None:
        out.setdefault(ask.key, ask)

    try:
        request = match.context_request(match_slice, at=at)
    except ValueError:
        request = None
    if request is not None:
        add(Ask("match/context", match.AGENT, "context", _identity(match.AGENT, "context", inputs, input_version=pkg.version,
                                                                    input_hash=match_slice.hash, candidates=()),
                request, match.input_hash(request), mode="CONTEXT"))
    keys = match.asked_keys(naming)
    if keys:
        try:
            request = match.evaluation_request(match_slice, naming, at=at, contradictions=inputs.contra0)
        except ValueError:
            request = None
        if request is not None:
            add(Ask("match/evaluation", match.AGENT, "evaluation",
                    _identity(match.AGENT, "evaluation", inputs, input_version=pkg.version, input_hash=match_slice.hash,
                              candidates=keys),
                    request, match.input_hash(request), mode="EVALUATION"))
    stats_slice = inputs.slices.get("stats")
    if inputs.stats_on and stats_slice is not None and (skeys := stats.asked_keys(naming)):
        try:
            request = stats.evaluation_request(stats_slice, naming, at=at, contradictions=inputs.contra0)
        except ValueError:
            request = None
        if request is not None:
            add(Ask("stats/evaluation", stats.AGENT, stats.TASK,
                    _identity(stats.AGENT, stats.TASK, inputs, input_version=pkg.version, input_hash=stats_slice.hash,
                              candidates=skeys),
                    request, stats.input_hash(request), mode=stats.MODE))
    player_slice = inputs.slices.get("player")
    if inputs.player_on and player_slice is not None and player.wanted(player_slice, naming) is None:
        try:
            request = player.evaluation_request(player_slice, naming, at=at, contradictions=inputs.contra0)
        except ValueError:
            request = None
        if request is not None:
            add(Ask("player/evaluation", player.AGENT, player.TASK,
                    _identity(player.AGENT, player.TASK, inputs, input_version=pkg.version, input_hash=player_slice.hash,
                              candidates=player.asked_keys(naming)),
                    request, player.input_hash(request), mode=player.MODE))
    views: dict[bool, council.CouncilView] = {}
    for arm, (level, with_assessments) in ARMS.items():
        if with_assessments not in views:
            views[with_assessments] = council.council_view(
                match_slice, naming, assessments=inputs.assessed if with_assessments else (),
                contradictions=inputs.contra1 if with_assessments else inputs.contra0)
        view = views[with_assessments]
        if not view.fits or not naming.keys:
            continue
        request = council.council_request(view, naming, level=level, at=at)
        identity = _identity(council.AGENT, "council", inputs, input_version=council.VIEW_VERSION, input_hash=view.hash,
                             candidates=naming.keys, model=council.model_of(level))
        add(Ask(f"council/{arm}", council.AGENT, "council", identity, request, council.input_hash(request), arm=arm, view=view))
    return out


def reread_assessments(rows: Iterable[tuple[str, str, str | None, Mapping[str, Any] | None]],
                       slices: Mapping[str, mcp_package.Slice]) -> tuple[Assessed, ...]:
    """The assessments the Council of the arms that read them was handed: the stored answers that stood of the Match,
    Statistics and Player Agents of the pass ``(agent, task, slice hash, output)``, each under the label it is cited
    by. Only an answer over the slice of THIS pass counts (the same key is the same slice, wherever it was stored).
    Raises ValueError for a stored answer that is not its contract any more: the view could not be the one it was."""
    found: dict[str, Assessed] = {}
    for agent, task, slice_hash, output in rows:
        name = "match" if agent == match.AGENT else agent
        own = slices.get(name)
        if own is None or slice_hash != own.hash or not isinstance(output, Mapping):
            continue
        out: AssessmentOut | PlayerAssessmentOut
        if agent == player.AGENT:
            out = PlayerAssessmentOut.model_validate(dict(output))
        else:
            out = AssessmentOut.model_validate(dict(output))
        label = assessment_label(out.agent, out.mode)
        if (agent, task) not in ((match.AGENT, "context"), (match.AGENT, "evaluation"), (stats.AGENT, stats.TASK),
                                 (player.AGENT, player.TASK)) or label in found:
            continue
        found[label] = Assessed(label, out)
    return tuple(found[k] for k in sorted(found))


def naming_of(reviewed: Sequence[Candidate], counts: Sequence[Candidate], *, stats_on: bool) -> Naming:
    """The names of the pass, as the orchestrator gives them (``shadow``): goals and result alone, or with the counts
    after them when the Statistics Agent was on."""
    if stats_on:
        return name_with_counts((*reviewed, *counts))
    return name_candidates(reviewed)


def inputs_of(package: mcp_package.Package, *, slice_set: str, reviewed: Sequence[Candidate], counts: Sequence[Candidate],
              stats_on: bool, player_on: bool,
              assessments: Iterable[tuple[str, str, str | None, Mapping[str, Any] | None]] = ()) -> PassInputs:
    """The inputs of a pass from its package and what the database keeps of it. Pure. Raises KeyError for a set of
    slices this code does not know and ValueError for a stored answer that does not read back."""
    names = SLICE_SETS[slice_set]
    slices = mcp_package.slices_of(package, names)
    naming = naming_of(reviewed, counts, stats_on=stats_on)
    at = slices["match"].known_at
    contra0 = contra.detect(package.document, naming=naming, assessments=(), at=at)
    assessed = reread_assessments(assessments, slices)
    contra1 = contra.detect(package.document, naming=naming, assessments=assessed, at=at)
    return PassInputs(package, dict(slices), naming, contra0, assessed, contra1, stats_on, player_on)


# -- the units the gate compares -----------------------------------------------------------------------------------------

def units_of(agent: str, task_kind: str, output: Mapping[str, Any] | None) -> dict[str, str]:
    """What the gate compares of an answer that stood: the stance of each candidate (``aa-v1``, ``pa-v1``), the
    verdict of each candidate (``cd-v1``) or, for the Match Agent's context (no candidate), the set of its signals as
    ``code:direction`` words. Codes only: nothing the model wrote in another form. Empty for an answer that did not
    stand."""
    if not isinstance(output, Mapping):
        return {}
    if agent == council.AGENT:
        verdicts = output.get("verdicts")
        return {str(v["candidate"]): str(v["verdict"]) for v in verdicts or () if isinstance(v, Mapping)
                and isinstance(v.get("candidate"), str) and isinstance(v.get("verdict"), str)}
    if task_kind == "context":
        signals = output.get("signals")
        words = sorted({f"{s.get('code')}:{s.get('direction')}" for s in signals or () if isinstance(s, Mapping)})
        return {"signals": ";".join(words) if words else "-"}
    candidates = output.get("candidates")
    return {str(c["candidate"]): str(c["stance"]) for c in candidates or () if isinstance(c, Mapping)
            and isinstance(c.get("candidate"), str) and isinstance(c.get("stance"), str)}


def confidence_of(agent: str, output: Mapping[str, Any] | None) -> dict[str, str]:
    """The Council's confidence of each verdict (LOW, MEDIUM, HIGH): reported beside the verdicts, never decided on.
    Empty for another agent or an answer that did not stand."""
    if agent != council.AGENT or not isinstance(output, Mapping):
        return {}
    verdicts = output.get("verdicts")
    return {str(v["candidate"]): str(v["confidence"]) for v in verdicts or () if isinstance(v, Mapping)
            and isinstance(v.get("candidate"), str) and isinstance(v.get("confidence"), str)}


# -- the verdict about one run ---------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Item:
    """An admitted run: the stored run, the question it was asked (``ask``, its request byte for byte) and what the
    gate compares of its stored answer."""

    run: StoredRun
    ask: Ask
    inputs: PassInputs
    units: dict[str, str]
    confidence: dict[str, str] = field(default_factory=dict)

    @property
    def scope(self) -> str:
        return self.ask.scope


@dataclass(frozen=True, slots=True)
class Exclusion:
    run: StoredRun
    scope: str
    reason: str


@dataclass(frozen=True, slots=True)
class Build:
    """What ``build`` found: the admitted runs, the excluded ones with their code, and the window it read."""

    items: tuple[Item, ...]
    excluded: tuple[Exclusion, ...]
    since: datetime | None = None
    until: datetime | None = None
    optimisations_changed_at: datetime | None = None

    def counts(self) -> dict[str, Any]:
        """Per scope: the runs read, the admitted ones, and the excluded ones by code."""
        by_scope: dict[str, dict[str, Any]] = {}
        for i in self.items:
            row = by_scope.setdefault(i.scope, {"read": 0, "admitted": 0, "excluded": Counter()})
            row["read"] += 1
            row["admitted"] += 1
        for e in self.excluded:
            row = by_scope.setdefault(e.scope, {"read": 0, "admitted": 0, "excluded": Counter()})
            row["read"] += 1
            row["excluded"][e.reason] += 1
        return {s: {"read": v["read"], "admitted": v["admitted"], "excluded": dict(sorted(v["excluded"].items()))}
                for s, v in sorted(by_scope.items())}


def scope_guess(run: StoredRun) -> str:
    """The scope of a run before its pass is derived: the agent's task, or the arm of the Council its model can be
    (Haiku: ``ma-v1-h``; Sonnet: ``ma-v1`` until the view says it was ``cs-v1``)."""
    if run.agent == council.AGENT:
        if run.task_kind != "council":
            return f"council/{run.task_kind}"
        return "council/ma-v1-h" if run.model == council.model_of("simple") else "council/ma-v1"
    return f"{run.agent}/{run.task_kind}"


def quick_reason(run: StoredRun, *, changed_at: datetime | None) -> str | None:
    """Why a run cannot be in the bank, from its own row alone (no derivation): its task, its variant against the
    registry in force, or an optimisation changed after it. None when it may be."""
    if run.agent == council.AGENT and run.task_kind == "escalation":
        return "escalation_out_of_bank"
    if run.agent not in AGENTS:
        return "agent_out_of_bank"
    try:
        expected = REGISTRY.identity_for(run.agent, run.task_kind, workspace="lab", input_version="replay", input_hash=SHA256_ZERO,
                                         pass_kind=cast(PassKind, run.pass_kind), fixture_id=run.fixture_id,
                                         model=run.model if run.agent == council.AGENT else None)
    except (RegistryError, IdempotencyError):
        return "agent_out_of_bank"
    if run.agent_version != expected.agent_version:
        return "version_not_in_force"
    if run.prompt_version != expected.prompt_version:
        return "prompt_not_in_force"
    if run.schema_version != expected.schema_version:
        return "schema_not_in_force"
    allowed = {council.model_of(level) for level, _ in ARMS.values()} if run.agent == council.AGENT else {expected.model}
    if run.model not in allowed:
        return "model_not_in_force"
    if run.effort != expected.effort:
        return "effort_not_in_force"
    if changed_at is not None and run.started_at < changed_at:
        return "optimisations_changed_since"
    return None


def state_reason(run: StoredRun) -> str | None:
    """Why the shadow's state of the pass cannot be the source of the run's package (before deriving it)."""
    if run.state_id is None or run.packet_id is None:
        return "no_state_of_the_pass"
    if run.state_package_hash is None or run.state_package_hash != run.package_hash:
        return "state_names_another_package"
    if run.kickoff_at is not None and run.known_at >= run.kickoff_at:
        return "known_at_after_kickoff"
    if run.package_version not in mcp_package.DERIVABLE:
        return "package_version_not_derivable"
    return None


def slice_name_of(run: StoredRun) -> str:
    """The slice a run read: its agent's own, and the Match Agent's for the Council (its view is cut from it)."""
    return run.agent if run.agent in (stats.AGENT, player.AGENT) else "match"


def admit(runs: Sequence[StoredRun], inputs: PassInputs) -> tuple[list[Item], list[Exclusion]]:
    """The runs of one pass against its inputs derived again: each must have the slice, the identity and the request
    hash the shadow stored. Pure."""
    asks = asks_of(inputs)
    items: list[Item] = []
    excluded: list[Exclusion] = []
    for run in runs:
        own = inputs.slices.get(slice_name_of(run))
        ask = asks.get(run.idem_key)
        if own is None or own.hash != run.slice_hash:
            excluded.append(Exclusion(run, ask.scope if ask is not None else scope_guess(run), "slice_not_rebuilt"))
        elif ask is None:
            excluded.append(Exclusion(run, scope_guess(run), "input_not_rebuilt"))
        elif run.request_hash is None:
            excluded.append(Exclusion(run, ask.scope, "request_hash_unknown"))
        elif run.request_hash != ask.request_hash:
            excluded.append(Exclusion(run, ask.scope, "request_not_rebuilt"))
        else:
            stood = run.output if run.status != "invalid" else None
            items.append(Item(run, ask, inputs, units_of(run.agent, run.task_kind, stood), confidence_of(run.agent, stood)))
    return items, excluded


# -- what the database keeps of a pass -----------------------------------------------------------------------------------

def reviewed_as_of(conn: psycopg.Connection[Any], *, fixture_id: int, packet_id: int, at: datetime) -> tuple[Candidate, ...]:
    """The selections production reviewed in the pass (``orchestrator_store.reviewed``), as of the start of the run."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REVIEWED_AS_OF_SQL, {"fixture": fixture_id, "packet": packet_id, "at": at})
        rows = cur.fetchall()
    return tuple(Candidate(fixture_id=fixture_id, market_key=str(r["market_key"]), selection=str(r["selection"]), line=Decimal(r["line"]),
                           p_model=Decimal(r["p_model"]), kickoff_at=r["kickoff_at"], pick_id=r["pick_id"], odds=r["odds"],
                           bookmaker_id=r["bookmaker_id"], bookmaker=r["bookmaker"], p_low=r["p_low"], p_market=r["p_market"],
                           ev=r["ev"])
                 for r in rows)


def pass_assessments(conn: psycopg.Connection[Any], run: StoredRun) -> list[tuple[str, str, str | None, dict[str, Any] | None]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PASS_RUNS_SQL, {"fixture": run.fixture_id, "pass": run.pass_kind, "known": run.known_at,
                                    "agents": [match.AGENT, stats.AGENT, player.AGENT]})
        return [(str(a), str(t), s, o if isinstance(o, dict) else None) for a, t, s, o in cur.fetchall()]


@dataclass(frozen=True, slots=True)
class Derived:
    """A pass derived again from the database, or the code of why it could not be."""

    inputs: PassInputs | None
    reason: str | None = None


def unseen_families(conn: psycopg.Connection[Any], run: StoredRun) -> list[datetime]:
    """The leak audit's second reading (``fbi.intel.leakage``, v9): the sets of the counts stamped by the moment but
    not yet visible when the packet was built."""
    from fbi.intel.leakage import (  # the audit's own text, read where it is kept
        FAMILY_JOB,
        UNSEEN_FAMILIES,
    )

    if run.packet_built_at is None:
        return []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(UNSEEN_FAMILIES, {"fixture": run.fixture_id, "version": mcp_package.FAMILY_VERSION,
                                      "families": list(mcp_package.FAMILY_ORDER), "at": run.known_at, "job": FAMILY_JOB,
                                      "built": run.packet_built_at})
        return [r[0] for r in cur.fetchall()]


def derive_pass(conn: psycopg.Connection[Any], run: StoredRun) -> Derived:
    """The inputs of the pass of ``run`` (any run of the pass: they share its state), from the database. Never raises
    for what a row says; a database that fails raises."""
    assert run.packet_id is not None and run.package_version is not None
    status = run.model_status
    try:
        package = mcp_package.derive(conn, run.packet_id, pass_kind=cast(PassKind, run.pass_kind),
                                     model_code=str(status.get("code") or ""), version=run.package_version)
        if package is not None and package.hash != run.package_hash:
            unseen = unseen_families(conn, run)
            if unseen:
                package = mcp_package.derive(conn, run.packet_id, pass_kind=cast(PassKind, run.pass_kind),
                                             model_code=str(status.get("code") or ""), version=run.package_version,
                                             unseen_families=unseen)
    except mcp_package.PackageLeakError:
        return Derived(None, "package_leak")
    if package is None:
        return Derived(None, "packet_missing")
    if package.fixture_id != run.fixture_id:
        return Derived(None, "packet_of_another_match")
    if package.hash != run.package_hash or package.known_at != run.known_at:
        return Derived(None, "package_not_rebuilt")
    slice_set = str(status.get("slices") or DEFAULT_SLICE_SET)
    if slice_set not in SLICE_SETS:
        return Derived(None, "slice_set_unknown")
    stats_status = status.get("stats")
    stats_on = isinstance(stats_status, Mapping)
    player_on = isinstance(status.get("player"), Mapping)
    reviewed = reviewed_as_of(conn, fixture_id=run.fixture_id, packet_id=run.packet_id, at=run.started_at)
    counts: tuple[Candidate, ...] = ()
    if stats_on:
        assert isinstance(stats_status, Mapping)
        recorded = stats_status.get("counts")
        if isinstance(recorded, Mapping):
            got = family_counts(conn, run.fixture_id, at=run.known_at)
            if sorted(got.decision_ids) != sorted(int(x) for x in recorded.get("decisions") or ()):
                return Derived(None, "counts_not_rebuilt")
            counts = got.candidates
    try:
        inputs = inputs_of(package, slice_set=slice_set, reviewed=reviewed, counts=counts, stats_on=stats_on,
                           player_on=player_on, assessments=pass_assessments(conn, run))
    except (ValueError, TypeError):
        return Derived(None, "assessment_unreadable")
    if stats_on:
        assert isinstance(stats_status, Mapping)
        if (stats_status.get("naming") not in (None, inputs.naming.version)
                or list(stats_status.get("asked") or ()) != list(stats.asked_keys(inputs.naming))):
            return Derived(None, "naming_not_rebuilt")
    return Derived(inputs)


def build(conn: psycopg.Connection[Any], *, runs: Sequence[StoredRun], changed_at: datetime | None,
          since: datetime | None = None, until: datetime | None = None) -> Build:
    """The bank over ``runs``: every run admitted or excluded with its code. Each pass is derived once, and only when
    one of its runs passed the checks of its own row."""
    items: list[Item] = []
    excluded: list[Exclusion] = []
    by_pass: dict[tuple[int, str, datetime], list[StoredRun]] = defaultdict(list)
    for run in runs:
        reason = quick_reason(run, changed_at=changed_at) or state_reason(run)
        if reason is not None:
            excluded.append(Exclusion(run, scope_guess(run), reason))
        else:
            by_pass[run.pass_key].append(run)
    for key in sorted(by_pass, key=lambda k: (k[2], k[0], k[1])):
        group = by_pass[key]
        try:
            derived = derive_pass(conn, group[0])
        except psycopg.Error:
            raise
        except Exception as exc:  # a pass that cannot be derived is a verdict about its runs, never a stop of the others
            derived = Derived(None, f"rebuild_failed:{type(exc).__name__}")
        if derived.inputs is None:
            excluded.extend(Exclusion(r, scope_guess(r), derived.reason or "rebuild_failed") for r in group)
            continue
        got, out = admit(group, derived.inputs)
        items.extend(got)
        excluded.extend(out)
    items.sort(key=lambda i: i.run.id)
    excluded.sort(key=lambda e: e.run.id)
    return Build(tuple(items), tuple(excluded), since, until, changed_at)


def select(items: Sequence[Item], *, scopes: Sequence[str] | None, limit_per_scope: int | None, seed: str) -> list[Item]:
    """The admitted runs a run asks about: those of ``scopes`` (all by default) and, per scope, at most
    ``limit_per_scope`` in an order fixed by the seed (the same ones every time, whatever order they were read in)."""
    chosen: list[Item] = []
    by_scope: dict[str, list[Item]] = defaultdict(list)
    for i in items:
        if scopes is None or i.scope in scopes:
            by_scope[i.scope].append(i)
    for scope in sorted(by_scope):
        ordered = sorted(by_scope[scope], key=lambda i: hashlib.sha256(f"{seed}:{i.run.id}".encode()).hexdigest())
        chosen.extend(ordered if limit_per_scope is None else ordered[:limit_per_scope])
    return sorted(chosen, key=lambda i: i.run.id)


def digest(items: Sequence[Item]) -> str:
    """A fingerprint of a selection: the scopes and stored runs it asks about."""
    body = json.dumps(sorted([i.scope, i.run.id, i.run.idem_key] for i in items), separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


__all__ = ["AGENTS", "ARMS", "PAID", "REASONS", "SCOPES", "VERSION", "Ask", "Build", "Derived", "Exclusion", "Item", "PassInputs",
           "StoredRun", "admit", "asks_of", "build", "confidence_of", "derive_pass", "digest", "inputs_of", "naming_of",
           "optimisations_changed_at", "quick_reason", "read_runs", "read_runs_by_id", "reread_assessments", "reviewed_as_of", "scope_guess",
           "select", "state_reason", "units_of"]

"""The corpus as a whole: the targets, their bases and cases, the request every ask makes, and the fingerprints that say whether a measurement
is of THIS corpus and of the prompts in force.

* ``corpus_hash``: the cases and the bases - what is attacked and how. A change to either is a new ``VERSION`` (a test pins the hash).
* ``requests_hash``: the bytes of every request of a target - the corpus AND the prompts, the schemas and the layout it is asked with. A
  prompt or a schema that changes changes it, and a measurement made with another one is stale (``fbi.ai.battery.run.status``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Final

from fbi.ai.agents import council, match, player, stats
from fbi.ai.battery import (
    AGENT_TARGETS,
    EVERY_TARGET,
    MIN_CASES,
    SHADOW_TARGETS,
    TARGETS,
    VERSION,
    agentworld,
    attacks_agents,
    attacks_claims,
    attacks_extract,
    attacks_review,
    claims,
    extractor,
    reviewer,
)
from fbi.ai.battery.model import Base, Case, make_case
from fbi.ai.config import Tier
from fbi.ai.contracts.base import ASSESSMENT, COUNCIL, PLAYER_ASSESSMENT
from fbi.ai.prompts import (
    COUNCIL_OPUS_VERSION,
    COUNCIL_VERSION,
    EXTRACT_V2_VERSION,
    EXTRACT_VERSION,
    MATCH_ASSESS_VERSION,
    MATCH_CONTEXT_VERSION,
    PLAYER_ASSESS_VERSION,
    REVIEW_VERSION,
    STATS_ASSESS_VERSION,
)
from fbi.ai.providers.base import JsonRequest

Builder = Callable[[str, Case | None, bool], JsonRequest]
Door = Callable[[Case, JsonRequest, JsonRequest], list[tuple[str, str]]]
Reader = Callable[[JsonRequest], list[Any]]


@dataclass(frozen=True, slots=True)
class Target:
    """A prompt of PrediGol that reads text someone else wrote."""

    name: str
    prompt: str
    """The version of the prompt under test (``review-v2``)."""
    tier: Tier
    """The tier production asks it with: the battery asks the same."""
    typical_output: int
    """Tokens an answer is expected to write: the reservation of the cost of an ask."""
    bases: dict[str, Base]
    build: Builder
    door: Door | None = None
    """A target whose text goes through a door of PrediGol's before the model reads it (``fbi.ai.untrusted``) says what became of the text of a
    case in the request, as findings ``(check, detail)``; the deterministic layer asks it instead of looking for the raw text in the request."""
    agent: str = ""
    """The version of the agent the target is (``match-v2``), or empty for a prompt that is no agent's: what Gate B reads to know that every
    agent that runs is covered."""
    prompts: tuple[str, ...] = ()
    """Every prompt the requests of the target are asked with, when there is more than ``prompt`` (an agent with two modes or two levels)."""
    contract: str = ""
    """The contract its answer is read in (``aa-v1``, ``cd-v1``), or empty for a prompt with a schema of its own."""
    base_tiers: tuple[tuple[str, Tier], ...] = ()
    """A base asked with another tier than the target's (the Council's escalation is Opus': ``final``)."""
    reader: Reader | None = None
    """The JSON documents of a user message, for a target whose layout is not one document (``fbi.ai.battery.offline.documents``)."""
    may_add: frozenset[str] = frozenset()
    """The key paths a door may add to a request that the clean one has not (the flags of a summary): every other new key is an attack that
    broke out of its string."""

    def tier_of(self, base: str) -> Tier:
        """The tier an ask of ``base`` is asked with."""
        return dict(self.base_tiers).get(base, self.tier)

    @property
    def tiers(self) -> tuple[Tier, ...]:
        """Every tier the target's asks need, sorted."""
        return tuple(sorted({self.tier, *(t for _, t in self.base_tiers)}))

    @property
    def every_prompt(self) -> tuple[str, ...]:
        return self.prompts or (self.prompt,)

    def covers(self) -> dict[str, Any]:
        """What the target speaks for, as the evidence lists it."""
        return {"target": self.name, "agent": self.agent or None, "prompts": list(self.every_prompt), "contract": self.contract or None,
                "tiers": list(self.tiers)}


def _agent(name: str, agent: str, prompts: tuple[str, ...], contract: str, tier: Tier, typical: int) -> Target:
    return Target(name, "+".join(prompts), tier, typical, agentworld.BASES[name],
                  lambda base, case, native: agentworld.request(name, base, case, native=native), door=agentworld.door, agent=agent,
                  prompts=prompts, contract=contract, base_tiers=agentworld.TIERS[name],
                  reader=agentworld.documents, may_add=agentworld.MAY_ADD[name])


TARGET_SPECS: Final[dict[str, Target]] = {
    "review": Target("review", REVIEW_VERSION, "analysis", 1000, reviewer.BASES,
                     lambda base, case, native: reviewer.request(base, case, native=native)),
    "extract": Target("extract", EXTRACT_VERSION, "bulk", 400, extractor.BASES,
                      lambda base, case, native: extractor.request(base, case, native=native)),
    "claims": Target("claims", EXTRACT_V2_VERSION, "bulk", 500, claims.BASES,
                     lambda base, case, native: claims.request(base, case, native=native), door=claims.door),
    "match": _agent("match", match.VERSION, (MATCH_CONTEXT_VERSION, MATCH_ASSESS_VERSION), ASSESSMENT, "bulk", 1200),
    "stats": _agent("stats", stats.VERSION, (STATS_ASSESS_VERSION,), ASSESSMENT, "bulk", 1200),
    "council": _agent("council", council.VERSION, (COUNCIL_VERSION, COUNCIL_OPUS_VERSION), COUNCIL, "analysis", 1500),
    "player": _agent("player", player.VERSION, (PLAYER_ASSESS_VERSION,), PLAYER_ASSESSMENT, "bulk", 1000),
}
"""The tier of an agent is the one of the level the router gives its task (``router.TIER_OF_LEVEL``: Haiku is ``bulk``, Sonnet ``analysis``,
Opus ``final``); ``typical_output`` is what an answer of a few hundred tokens writes with the thinking of its effort."""

CASES: Final[tuple[Case, ...]] = (tuple(make_case("review", a) for a in attacks_review.ATTACKS)
                                  + tuple(make_case("extract", a) for a in attacks_extract.ATTACKS)
                                  + tuple(make_case("claims", a) for a in attacks_claims.ATTACKS)
                                  + tuple(make_case(t, a) for t in AGENT_TARGETS for a in attacks_agents.ATTACKS[t]))
"""The corpus of ``battery-v3``: what ``corpus_hash`` and the evidence of the gate speak for."""
SHADOW_CASES: Final[tuple[Case, ...]] = tuple(make_case(t, a) for t in SHADOW_TARGETS for a in attacks_agents.ATTACKS[t])
"""IA-017: the cases of the targets of agents born OFF (``SHADOW_TARGETS``), outside the corpus of the gate while their agent is off."""
EVERY_CASE: Final[tuple[Case, ...]] = CASES + SHADOW_CASES
BY_ID: Final[dict[str, Case]] = {c.id: c for c in EVERY_CASE}


def target(name: str) -> Target:
    try:
        return TARGET_SPECS[name]
    except KeyError:
        raise ValueError(f"unknown target {name!r} (the targets are {', '.join(EVERY_TARGET)})") from None


def cases_of(name: str) -> tuple[Case, ...]:
    target(name)
    return tuple(c for c in (*CASES, *SHADOW_CASES) if c.target == name)  # read when asked: a test may put another corpus in their place


def case_of(case_id: str) -> Case:
    try:
        return BY_ID[case_id]
    except KeyError:
        raise ValueError(f"unknown case {case_id!r}") from None


def request_for(name: str, base: str, case: Case | None = None, *, native: bool = False) -> JsonRequest:
    """The request of an ask: the base clean (a control) or with the case's text in its place."""
    spec = target(name)
    if base not in spec.bases:
        raise ValueError(f"unknown base {base!r} of the target {name!r}")
    if case is not None and (case.target != name or case.base != base):
        raise ValueError(f"the case {case.id} is not an attack on the base {base!r} of {name!r}")
    return spec.build(base, case, native)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def fingerprint(request: JsonRequest) -> str:
    """sha256 of everything that defines a request: what the model is told, the schema, how it is asked."""
    return hashlib.sha256(_canonical(asdict(request)).encode()).hexdigest()


def requests_hash(name: str, *, native: bool = False) -> str:
    """sha256 of the fingerprints of every request of a target: its bases clean and each of its cases."""
    spec = target(name)
    parts = [[f"base:{b}", fingerprint(request_for(name, b, native=native))] for b in sorted(spec.bases)]
    parts += [[f"case:{c.id}", fingerprint(request_for(name, c.base, c, native=native))] for c in sorted(cases_of(name), key=lambda c: c.id)]
    return hashlib.sha256(_canonical([VERSION, spec.prompt, parts]).encode()).hexdigest()


def corpus_hash() -> str:
    """sha256 of the corpus: every base and every case, with what the deterministic layer and the evaluator expect of it."""
    bases = [[t, b.id, b.note] for t in TARGETS for b in sorted(target(t).bases.values(), key=lambda b: b.id)]
    cases = [[c.id, c.canary, asdict(c.attack)] for c in sorted(CASES, key=lambda c: c.id)]
    return hashlib.sha256(_canonical([VERSION, bases, cases]).encode()).hexdigest()


def check_sizes() -> list[str]:
    """What is wrong with the size of the corpus - the plan's «≥ 40 casos» of each target - or nothing."""
    return [f"{t}: {n} cases, {MIN_CASES} needed" for t in EVERY_TARGET if (n := len(cases_of(t))) < MIN_CASES]

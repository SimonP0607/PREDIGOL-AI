"""What the agents of phase 3 share: the NAME of a candidate (``c1``, ``c2``...) and the labels of the assessments the Council cites
(Plan Maestro IA, sections 9 and 11; contracts ``aa-v1`` and ``cd-v1``).

The contracts never carry a market, a selection or a price: they carry ``c1``... and the server resolves the name. This is the one place
that decides which candidate is ``c1``, so that the Match Agent, the detector ``contra-v1``, the Council and the orchestrator that stores
what they say all speak of the same selection. The names are a pure function of the candidates: the same candidates give the same names
whatever order they came in, and a candidate that is left out (more than the contract takes, or a family no agent of the phase reads) is
said and never renamed into a free name.

Nothing here reads a clock, a database or a setting.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, get_args

from fbi.ai.contracts.assessment import CANDIDATES_MAX, AssessmentOut
from fbi.ai.contracts.base import COUNTS, FAMILIES, GOALS_RESULT, REF, Agent, Family, Mode, paths_of
from fbi.ai.contracts.mcp import family_of
from fbi.ai.review import Candidate

NAMING_VERSION: Final = "cand-names-v1"
"""The method of the names. Changing it changes which selection is ``c1`` in every stored run: it is a new name here, never an edit."""
NAMING_COUNTS_VERSION: Final = "cand-names-v2"
"""The method of the names when the Statistics Agent is on (phase 4, ``name_with_counts``): the names of goals and result are EXACTLY those of
``cand-names-v1`` and the selections of corners and cards follow them. Nothing already stored changes name."""
HALF_TOKENS: Final = frozenset({"1H", "2H", "HT", "FH", "SH", "H1", "H2", "HALF"})
"""The parts of a market key that say it is about ONE half. The settlement rules of the catalogue (``fbi.market.rules``) cannot grade the corners
of a half (``no_period_data``: the provider gives corners as a total of the match), and the owner has not chosen a convention for the cards of a
half: neither is ever named for an agent."""
FAMILY_ORDER: Final[dict[str, int]] = {family: i for i, family in enumerate(FAMILIES)}
"""The families in the order of the contracts (1X2, DC, AH, OU, BTTS, CORNERS, CARDS): the order the names follow."""


@dataclass(frozen=True, slots=True)
class Named:
    """A candidate with the name the agents know it by."""

    key: str
    candidate: Candidate
    family: Family


@dataclass(frozen=True, slots=True)
class Naming:
    """The candidates of one match as the agents see them, and those that were left out (with the reason)."""

    named: tuple[Named, ...]
    left_out: tuple[tuple[Candidate, str], ...] = ()
    version: str = NAMING_VERSION

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(n.key for n in self.named)

    def resolve(self, key: str) -> Named | None:
        """The candidate a name stands for, or None for a name this match does not have."""
        return next((n for n in self.named if n.key == key), None)

    def of_family(self, families: Collection[str]) -> tuple[Named, ...]:
        return tuple(n for n in self.named if n.family in families)


def _identity(c: Candidate) -> tuple[int, str, str, Decimal]:
    return c.key


def _order(c: Candidate, family: Family) -> tuple[int, str, str, Decimal]:
    return FAMILY_ORDER[family], c.market_key, c.selection, c.line


def _worth(c: Candidate) -> tuple[int, Decimal, str, str, Decimal]:
    """Who stays when there are more candidates than the contract takes: the one with the larger expected value first, one without a value
    last, and ties by identity so that the choice never depends on the order they came in."""
    has_ev = 0 if c.ev is not None else 1
    return has_ev, -(c.ev if c.ev is not None else Decimal(0)), c.market_key, c.selection, c.line


def name_candidates(candidates: Iterable[Candidate], *, families: Collection[str] = GOALS_RESULT,
                    limit: int = CANDIDATES_MAX) -> Naming:
    """``c1``... for the candidates of ONE match. Only the families asked for (the Match Agent's five by default) are named; a market of a
    family nobody reads is left out (``family_not_read``), a candidate seen twice is named once, and when there are more than ``limit`` the
    ones with the larger expected value stay (``beyond_the_limit``). The names follow the order of the families, then the market, the
    selection and the line - not the order the candidates came in."""
    seen: dict[tuple[int, str, str, Decimal], Candidate] = {}
    for c in candidates:
        seen.setdefault(_identity(c), c)
    kept: list[tuple[Candidate, Family]] = []
    left: list[tuple[Candidate, str]] = []
    for c in sorted(seen.values(), key=lambda x: (x.market_key, x.selection, x.line)):
        family = family_of(c.market_key)
        if family is None or family not in families:
            left.append((c, "family_not_read"))
        else:
            kept.append((c, family))
    if len(kept) > limit:
        ranked = sorted(kept, key=lambda pair: _worth(pair[0]))
        for c, _ in ranked[limit:]:
            left.append((c, "beyond_the_limit"))
        kept = ranked[:limit]
    kept.sort(key=lambda pair: _order(pair[0], pair[1]))
    named = tuple(Named(f"c{i}", c, family) for i, (c, family) in enumerate(kept, start=1))
    return Naming(named, tuple(left))


def is_full_time(market_key: str) -> bool:
    """Whether a market key is about the whole match: none of its parts (``CORNERS_OU_1H`` is ``CORNERS``, ``OU``, ``1H``) names a half."""
    return not (set(market_key.strip().upper().split("_")) & HALF_TOKENS)


def name_with_counts(candidates: Iterable[Candidate], *, limit: int = CANDIDATES_MAX) -> Naming:
    """The names of ONE match when the Statistics Agent is on: ``name_candidates`` for goals and result - the very same names - and, after them,
    the selections of corners and cards of the WHOLE match (``is_full_time``), in the order of the families, then market, selection and line.
    The contract takes ``limit`` names: goals and result keep theirs, and the counts take the places that are left, the larger expected value
    first (``beyond_the_limit`` for the rest). A count of a half is left out as ``period_not_settleable`` and a family nobody reads as before.
    Pure: the same candidates give the same names whatever order they came in."""
    every = tuple(candidates)
    base = name_candidates(every, limit=limit)
    pool: dict[tuple[int, str, str, Decimal], Candidate] = {}
    for c in every:
        if family_of(c.market_key) in COUNTS:
            pool.setdefault(_identity(c), c)
    left: list[tuple[Candidate, str]] = [(c, why) for c, why in base.left_out if family_of(c.market_key) not in COUNTS]
    kept: list[tuple[Candidate, Family]] = []
    for c in sorted(pool.values(), key=lambda x: (x.market_key, x.selection, x.line)):
        family = family_of(c.market_key)
        if family is None:
            continue
        if is_full_time(c.market_key):
            kept.append((c, family))
        else:
            left.append((c, "period_not_settleable"))
    room = max(0, limit - len(base.named))
    ranked = sorted(kept, key=lambda pair: _worth(pair[0]))
    left.extend((c, "beyond_the_limit") for c, _ in ranked[room:])
    chosen = sorted(ranked[:room], key=lambda pair: _order(pair[0], pair[1]))
    named = base.named + tuple(Named(f"c{len(base.named) + i}", c, family) for i, (c, family) in enumerate(chosen, start=1))
    left.sort(key=lambda pair: (pair[0].market_key, pair[0].selection, pair[0].line, pair[1]))
    return Naming(named, tuple(left), NAMING_COUNTS_VERSION)


# -- what the agents read of each other -----------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Assessed:
    """An assessment as the detector and the Council read it: the label it is cited by (``A:<label>``, ``assessment_label``) and the answer
    after ``contracts.assessment.check`` (a stance that rested on nothing is already ``NEUTRAL``)."""

    label: str
    out: AssessmentOut


ContraCode = Literal["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"]
CONTRA_CODES: Final = get_args(ContraCode)
Requires = Literal["cite_and_explain", "escalate", "research_first", "resolve_in_writing"]
REQUIRES: Final[dict[str, Requires]] = {
    "C01": "cite_and_explain", "C02": "cite_and_explain", "C03": "cite_and_explain", "C04": "cite_and_explain",
    "C05": "cite_and_explain", "C06": "escalate", "C07": "research_first", "C08": "resolve_in_writing"}
"""What each contradiction obliges (architecture, section 12): C01-C05 the Council must cite it and say why it keeps or lowers the selection;
C06 is the escalation to Opus (E6); C07 a research before deciding; C08 the Council must resolve it in writing (in codes)."""


@dataclass(frozen=True, slots=True)
class Contradiction:
    """One contradiction of ``contra-v1`` (written by code, never by a model). It names the candidates it touches by their ``c<n>`` name and
    cites what it rests on by typed references that exist in the package; ``detail`` holds codes and numbers computed by the server, never a
    text that came from outside. The typed fields are what ``router-v1`` reads to escalate (E2, E3, E5, E6), so that nobody parses ``detail``."""

    code: ContraCode
    subject: str
    """``match``, ``team:home``, ``team:away``, ``player:<id>``, ``referee`` or ``pair:c1+c4``."""
    candidates: tuple[str, ...]
    refs: tuple[str, ...] = ()
    confirmed: bool = False
    """C01 and C02: the evidence that fires it is CONFIRMED (E2 needs it)."""
    official_lineup: bool = False
    """C03: judged with the official line-up (E3 needs it)."""
    starters_out: int = 0
    """C03: how many usual starters the official line-up leaves out."""
    gap: Decimal | None = None
    """C06: the gap between the model and the market, in probability (absolute value)."""
    detail: tuple[tuple[str, str], ...] = ()

    @property
    def requires(self) -> Requires:
        return REQUIRES[self.code]

    def to_json(self) -> dict[str, Any]:
        """What ``ai.match_runs.contradictions`` keeps: codes, names, references and numbers - never a text."""
        out: dict[str, Any] = {"code": self.code, "subject": self.subject, "candidates": list(self.candidates), "refs": list(self.refs),
                               "requires": self.requires}
        if self.confirmed:
            out["confirmed"] = True
        if self.official_lineup:
            out["official_lineup"] = True
        if self.starters_out:
            out["starters_out"] = self.starters_out
        if self.gap is not None:
            out["gap"] = str(self.gap)
        if self.detail:
            out["detail"] = dict(self.detail)
        return out


# -- the references an answer may make -----------------------------------------------------------------------------------------------

def assessment_label(agent: Agent, mode: Mode) -> str:
    """How the Council cites an assessment (``A:match_evaluation``): the agent and the mode it wrote it in. One per pair in a view."""
    return f"{agent}_{mode.lower()}"


def known_refs(document: Mapping[str, Any]) -> tuple[frozenset[int], frozenset[str]]:
    """The evidence ids and the paths a slice or a view has, for ``contracts.*.check``: ``E:<id>`` must be in the first, ``P:<path>`` in the
    second. A path names a block or anything inside it; a list element is not addressed by index."""
    evidence = document.get("evidence")
    ids: set[int] = set()
    if isinstance(evidence, Sequence) and not isinstance(evidence, str):
        for item in evidence:
            if isinstance(item, Mapping) and isinstance(item.get("id"), int):
                ids.add(int(item["id"]))
    return frozenset(ids), frozenset(paths_of(dict(document)))


CITABLE_DEPTH: Final = 3
"""How deep the list of citable blocks goes (``citable_refs``): ``shared.absences.home`` is three keys. A block deeper than that is cited by the
block above it, as the prompts have always said; it is still a reference the reader accepts, only one the list does not offer."""


def citable_refs(document: Mapping[str, Any], *, depth: int = CITABLE_DEPTH) -> tuple[str, ...]:
    """The references a model may copy into an answer about ``document`` (IA-014), written by code from the document and never by a model: ``E:<id>``
    of every item of ``evidence`` (ascending) and then ``P:<path>`` of every BLOCK - a key whose value is an object or a list - down to ``depth``
    keys, in the order of the paths. A key that is not a reference (``REF``: lower case, digits and ``_``) is not offered, and nothing inside it.
    Every reference of the list is one ``known_refs`` accepts: the list is a part of what the reader takes, never more."""
    ids, _ = known_refs(document)
    blocks: list[str] = []

    def walk(node: Any, prefix: str, level: int) -> None:
        if not isinstance(node, Mapping) or level > depth:
            return
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (Mapping, list)) and REF.fullmatch(f"P:{path}") is not None:
                blocks.append(path)
                walk(value, path, level + 1)

    walk(document, "", 1)
    return (*(f"E:{i}" for i in sorted(ids)), *(f"P:{p}" for p in sorted(blocks)))


# -- the problems of an answer, in closed codes ----------------------------------------------------------------------------------------

EXTRA_KEY: Final = "extra_forbidden"
"""The kind of error of a key the contract does not have (Pydantic's ``extra="forbid"``)."""
NAMED_EXTRA_KEYS_IA009: Final = frozenset({
    "reasoning", "notes", "note", "summary", "analysis", "explanation", "rationale", "contradictions", "comments", "thinking", "assessment",
    "output", "answer", "result", "findings", "confidence", "stance"})
"""The words of IA-009 (6 Nov 2026)."""
NAMED_EXTRA_KEYS_IA014: Final = frozenset({
    # prose a model adds about its own answer
    "reason", "reasons", "justification", "comment", "remarks", "observations", "commentary", "thoughts", "description", "details",
    "conclusion", "conclusions", "recommendation", "recommendations", "decision", "verdict", "verdicts", "overall", "overall_stance",
    "caveats", "warnings", "limitations", "uncertainty", "assumptions", "key_factors", "factors", "evidence", "references", "sources",
    "citations",
    # a wrapper, or the schema echoed back
    "assessments", "evaluation", "evaluations", "context", "input", "arguments", "parameters", "properties", "type", "schema", "json", "data",
    "response", "content", "message", "status", "error", "errors", "metadata", "version", "submit_assessment",
    # the keys of the second object of the message, and of the package, copied into the answer
    "now", "minutes_to_kickoff", "package_age_minutes", "citable", "header", "market", "models", "shared", "missing", "match", "fixture_id",
    # a field of the contract in the wrong place or in the singular
    "stances", "signal", "driver", "risk", "ask", "request", "research_ask", "research_request", "quality"})
"""The words of IA-014 (7 Nov 2026): with ``match-v2`` 8 of 20 invalid answers still had a key at the top level whose name was none of IA-009's, so
it was cut and nobody knows it. These are the words a model is likely to write there - prose about the answer, a wrapper or the schema echoed back,
a key of the message copied into the answer, a field in the singular - so that the next measurement names them."""
NAMED_EXTRA_KEYS: Final = NAMED_EXTRA_KEYS_IA009 | NAMED_EXTRA_KEYS_IA014
"""The harmless English words a model is likely to add as a key of its own (IA-009, widened by IA-014). Where an answer has a key the contract does
not have, the problem names it ONLY when it is one of these (or a field of the contract): what is written is then this list's own word, never the
model's text. Any other name is cut, as before. The list is fixed here and grows only by a change of code."""
_KIND: Final = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def _position(step: str) -> bool:
    return step.isascii() and step.isdigit() and len(step) <= 3


def _named_key(step: str, fields: Collection[str]) -> str | None:
    """The name a key of the model's may be recorded with: a field of the contract as it is, or the word of ``NAMED_EXTRA_KEYS`` it is (without
    case or surrounding spaces). None for anything else."""
    if step in fields:
        return step
    word = step.strip().lower() if step.isascii() else ""
    return next((w for w in NAMED_EXTRA_KEYS if w == word), None)


def closed_problem(problem: str, fields: Collection[str]) -> str:
    """A problem of ``contracts.parse`` (``where:kind``) as a closed code ``schema:<where>:<kind>``. ``parse`` says where - the fields of the
    contract and the position in a list - and what KIND of error, never the value; but where an answer has a key the contract does not have, the
    location ends in that key, and its name is the model's to choose. Every step of a location that is not a field of the contract (``fields``)
    or a position is cut, so the code carries nothing the model wrote.

    One exception, for the diagnosis of IA-009: the key of an ``extra_forbidden`` error is named when it is a field of the contract or a word of
    ``NAMED_EXTRA_KEYS`` (what is written is the list's own word). At the top level the code is ``schema:answer.<name>:extra_forbidden``, so
    that a top-level key is never read as the field of the same name further down; inside an object it follows the location
    (``schema:signals.0.notes:extra_forbidden``). Any other name stays cut: ``schema:answer:extra_forbidden``, ``schema:signals.0:extra_forbidden``."""
    where, sep, kind = problem.rpartition(":")
    if not sep:
        return f"schema:{problem}" if _KIND.fullmatch(problem) else "schema:invalid"
    kind = kind if _KIND.fullmatch(kind) else "invalid"
    path = where.split(".")
    above = path[:-1]
    if kind == EXTRA_KEY and all(s in fields or _position(s) for s in above):
        name = _named_key(path[-1], fields)
        base = ".".join(above) or "answer"
        return f"schema:{base}.{name}:{kind}" if name is not None else f"schema:{base}:{kind}"
    steps: list[str] = []
    for step in path:
        if step in fields or _position(step):
            steps.append(step)
        else:
            break
    return f"schema:{'.'.join(steps) or 'answer'}:{kind}"

"""The contracts of PrediGol Intelligence (Plan Maestro IA, phase 1; IA-017 added the seventh): what goes into Claude and what may come out of it.

    mcp-v1    the package the backend writes: a match by slices (``fbi.ai.package``)            not an output
    claim-v1  what the Research Service's extractor (Haiku) returns about a page                 an output
    aa-v1     the Match Agent's and the Statistics Agent's assessments                           an output
    cd-v1     the Council's verdicts, one per selection                                          an output
    pmr-v1    the Post-Match Reviewer's attribution                                              an output
    la-v1     the Learning Analyst's weekly hypotheses                                           an output
    pa-v1     the Player Agent's positions (IA-017: aa-v1 narrowed - no strength, no research)  an output

Every OUTPUT contract is a Pydantic model that is also its JSON Schema, and the schema is what Anthropic's structured outputs can
take (``wire_schema``): closed values (enums), every field required, ``additionalProperties: false`` on every object - and NONE of
the constraints the API does not support (numeric bounds, string lengths, item counts; docs.claude.com, structured outputs,
"JSON Schema limitations"). The bounds are real all the same: Pydantic checks them AFTER the answer arrives, so a model that writes
a 900-character quote or a sixth hypothesis gets an ``invalid`` answer, the same as one that writes a verdict nobody knows.

What an output can NEVER carry, by construction and not by instruction (``FORBIDDEN_WORDS``, held by a test on every field name):
a probability, a price, a stake, an edge, a URL, a query or SQL. The server adds ``p_model`` and ``p_market`` from the package when
it stores a verdict (``fbi.ai.agents``, phase 3); a model never writes them. The assessments and verdicts carry CODES (the signals
and risks below), not prose: the less free text an agent can write, the less a poisoned page can say through it. The two outputs
that do carry prose - the post-match narrative and the hypotheses - are marked untrusted, never operational, and never measured.

References are typed (``Ref``): ``E:<n>`` an evidence of ``ai.evidence``, ``P:<path>`` a path of the package, ``A:<id>`` an
assessment of the agents (the Council cites those). ``check_refs`` says which of a list do not exist.

Versions. The ``contract`` field of every output says which one it is; an incompatible change is a NEW version, the reader accepts
every version it knows (``fbi.ai.contracts.parse``) and the old one is never edited in place.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict

MCP: Final = "mcp-v1"
CLAIM: Final = "claim-v1"
ASSESSMENT: Final = "aa-v1"
COUNCIL: Final = "cd-v1"
POST_MATCH: Final = "pmr-v1"
LEARNING: Final = "la-v1"
PLAYER_ASSESSMENT: Final = "pa-v1"
"""IA-017: what the Player Agent writes (``fbi.ai.contracts.player``). ``aa-v1`` cannot carry it unchanged - its ``agent`` enum has no
``player`` and its signals carry a ``strength`` - and ``aa-v1`` is never edited in place (the Match and the Statistics Agents answer in it, byte
for byte, and the registry holds its schema's hash); so the Player Agent has its own, the smallest that can say what it must."""

OUTPUTS: Final = (CLAIM, ASSESSMENT, COUNCIL, POST_MATCH, LEARNING, PLAYER_ASSESSMENT)
"""The contracts a model writes (the sixth, ``mcp-v1``, is what the model reads)."""

# ── the closed values ────────────────────────────────────────────────────────────────────────────────────────────────

Verdict = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
"""What the Council says of a selection. It can lower a state, never raise one: filter 6 of the decision layer combines as it always
did, the most conservative wins (``fbi.intel.decision``)."""
Stance = Literal["SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL"]
"""What an agent's evaluation says of a candidate."""
Level = Literal["LOW", "MEDIUM", "HIGH"]
Quality = Literal["GOOD", "FAIR", "POOR"]
Mode = Literal["CONTEXT", "EVALUATION"]
Agent = Literal["match", "stats"]
Side = Literal["home", "away", "both"]

SignalCode = Literal[
    "ABSENCES", "LINEUP", "SCHEDULE", "STAKES", "FORM", "H2H", "TACTICS", "VENUE", "REFEREE", "MARKET_MOVE",
    "MODEL_MARKET_GAP", "NEWS", "RATE", "DATA_QUALITY"]
"""What an assessment can point at (a topic, not a statement): who is out, the line-up and its rotation, rest and congestion, what each
side plays for, the form, the head-to-head, the observable tactics, the ground and the trip, the referee, the movement of the price,
the gap between the model and the market, news from outside the numbers, the rate of a count (corners, cards) and the quality of the
data. The direction and the strength say the rest."""
SIGNAL_CODES: Final = get_args(SignalCode)

Direction = Literal["HOME", "DRAW", "AWAY", "OVER", "UNDER", "BOTH_SCORE", "NOT_BOTH_SCORE", "NEUTRAL"]
"""Which way a signal pushes, in the words of the families of goals and result; ``OVER``/``UNDER`` also say more or fewer corners or cards."""

RiskCode = Literal[
    "LINEUP_UNCONFIRMED", "KEY_ABSENCE_OPEN", "CONTRADICTORY_NEWS", "RUMOUR_ONLY", "STALE_PRICE", "THIN_MARKET", "MODEL_UNCALIBRATED",
    "WIDE_INTERVAL", "LOW_STAKES", "ROTATION", "LATE_CHANGE", "DATA_GAP"]
"""What can make a candidate worse than it looks. A risk is a fact about the information, never a reason by itself to approve."""
RISK_CODES: Final = get_args(RiskCode)

Family = Literal["1X2", "DC", "AH", "OU", "BTTS", "CORNERS", "CARDS"]
"""The families of markets the agents work on: the five of goals and result (the Match Agent) and the two of counts (the Statistics Agent)."""
FAMILIES: Final = get_args(Family)
GOALS_RESULT: Final = ("1X2", "DC", "AH", "OU", "BTTS")
COUNTS: Final = ("CORNERS", "CARDS")

ResearchTopic = Literal["availability", "confirmation", "preview"]
"""What an agent may ASK the server to look into: the list of ``fbi.ai.research`` (held equal by a test). Never a query."""
ErrorClass = Literal["MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE", "UNKNOWN"]
"""Why a signal failed: the classes of ``fbi.intel.pm_questions`` (the post-mortem ``pm-v6``) - one vocabulary, not two."""
Outcome = Literal["HIT", "MISS", "VOID"]

# ── what an output may not have ─────────────────────────────────────────────────────────────────────────────────────

FORBIDDEN_WORDS: Final = frozenset({
    "p", "prob", "probability", "probabilities", "odds", "price", "prices", "stake", "stakes", "edge", "ev", "kelly", "sql", "url",
    "urls", "uri", "href", "link", "links", "query", "queries"})
"""A word that may not be a name in an output's schema. The words are taken from the name's parts (``p_model`` is ``p`` and ``model``)."""

UNSUPPORTED: Final = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "pattern", "format"})
"""What the structured outputs of the API do not take and the wire schema therefore never carries (``pattern`` and ``format`` are left
out for the same reason: only a few of either are supported, and a code the model must follow is an enum, not a regular expression)."""
NOISE: Final = frozenset({"title", "default", "description", "examples", "$defs", "definitions"})
"""What Pydantic writes that costs tokens on every call and says nothing the prompt does not."""
ALLOWED_KEYS: Final = frozenset({"type", "properties", "required", "additionalProperties", "items", "enum", "anyOf", "minItems"})
"""Everything a wire schema may contain, and nothing else."""


class Contract(BaseModel):
    """The base of every model of a contract: an unknown field is an error, and a field is its name and its type - nothing hidden."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


def _words(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w}


def forbidden_names(schema: dict[str, Any]) -> list[str]:
    """The names in a (wire) schema that are or contain a forbidden word - empty for every output contract."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                found.extend(sorted(n for n in props if _words(n) & FORBIDDEN_WORDS))
                for child in props.values():
                    walk(child)
            for key in ("items", "anyOf"):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    return found


# ── the wire schema ─────────────────────────────────────────────────────────────────────────────────────────────────

class SchemaError(ValueError):
    """A model that cannot be sent as a schema: recursion, an optional field, or a union the API compiles badly."""


def wire_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON Schema of ``model`` in the form structured outputs take (``output_config.format``): references inlined, ``const`` as a
    one-value enum, every property required, ``additionalProperties: false`` on every object, no bound of any kind, no title and no
    default. A field with a default (that is: optional) is refused - an agent's answer has every field, empty when it has nothing."""
    raw = model.model_json_schema()
    defs: dict[str, Any] = raw.get("$defs", {})

    def inline(node: Any, stack: tuple[str, ...], where: str) -> Any:
        if isinstance(node, list):
            return [inline(x, stack, where) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            if name in stack:
                raise SchemaError(f"{where}: {name} is recursive")
            return inline(defs[name], (*stack, name), f"{where}>{name}")
        out: dict[str, Any] = {}
        if "const" in node:
            out["type"] = node.get("type", "string")
            out["enum"] = [node["const"]]
        for key, value in node.items():
            if key in UNSUPPORTED or key in NOISE or (key in ("const", "type") and "const" in node):
                continue
            if key == "minItems":
                if value > 1:
                    continue  # a count is checked after the answer, not before
                out[key] = value
            elif key == "properties":
                out[key] = {n: inline(p, stack, f"{where}.{n}") for n, p in value.items()}
            elif key == "required":
                continue
            elif key == "items":
                out[key] = inline(value, stack, f"{where}[]")
            elif key == "anyOf":
                out[key] = [inline(v, stack, where) for v in value]
            elif key in ("type", "enum", "additionalProperties"):
                out[key] = value
            else:
                raise SchemaError(f"{where}: the schema keyword {key!r} is not one the API takes")
        if out.get("type") == "object" or "properties" in out:
            props = out.setdefault("properties", {})
            out["type"] = "object"
            out["required"] = list(props)
            out["additionalProperties"] = False
        return out

    schema: dict[str, Any] = inline({k: v for k, v in raw.items() if k != "$defs"}, (), model.__name__)
    _must_have_every_field_required(model)
    return schema


def _must_have_every_field_required(model: type[BaseModel]) -> None:
    seen: set[type[BaseModel]] = set()

    def visit(m: type[BaseModel]) -> None:
        if m in seen:
            return
        seen.add(m)
        for name, field in m.model_fields.items():
            if not field.is_required():
                raise SchemaError(f"{m.__name__}.{name} has a default: an output has every field")
            for sub in _models_in(field.annotation):
                visit(sub)

    visit(model)


def _models_in(annotation: Any) -> Iterable[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _models_in(arg)


def keys_of(schema: Any) -> set[str]:
    """Every JSON Schema keyword used in ``schema`` (property names are not keywords): what a test checks against ``ALLOWED_KEYS``."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                if key == "properties":
                    for child in value.values():
                        walk(child)
                else:
                    walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    return found


# ── typed references ────────────────────────────────────────────────────────────────────────────────────────────────

REF = re.compile(r"^(?:E:(?P<e>[1-9][0-9]{0,11})|P:(?P<p>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)|A:(?P<a>[a-z][a-z0-9_]*))$")
"""``E:12`` an evidence, ``P:shared.absences.home`` a path of the package, ``A:match_1`` an assessment. Nothing else is a reference."""
CANDIDATE = re.compile(r"^c[0-9]{1,3}$")
"""A candidate as the package names it (``c1``, ``c2``...): the server resolves it to a market, a selection and a line."""


@dataclass(frozen=True, slots=True)
class Ref:
    kind: Literal["E", "P", "A"]
    value: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


def parse_ref(text: str) -> Ref | None:
    m = REF.match(text)
    if m is None:
        return None
    if m.group("e") is not None:
        return Ref("E", m.group("e"))
    if m.group("p") is not None:
        return Ref("P", m.group("p"))
    return Ref("A", m.group("a"))


def paths_of(content: Any, prefix: str = "") -> set[str]:
    """Every dotted path of the keys of a package (lists are not walked into: a path names a block, not an element)."""
    found: set[str] = set()
    if isinstance(content, dict):
        for key, value in content.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.add(path)
            found |= paths_of(value, path)
    return found


def check_refs(refs: Iterable[str], *, evidence_ids: Collection[int], paths: Collection[str],
               assessments: Collection[str] = ()) -> list[str]:
    """The references that are not what they say: malformed, or naming an evidence, a block or an assessment the package does not have.
    A path is the path of a block (``P:shared.absences``) or of anything inside it; a list element is not addressed by index."""
    known_e = {str(i) for i in evidence_ids}
    known_p = set(paths)
    known_a = set(assessments)
    bad: list[str] = []
    for text in refs:
        ref = parse_ref(text)
        ok = (ref is not None and ((ref.kind == "E" and ref.value in known_e) or (ref.kind == "P" and ref.value in known_p)
                                    or (ref.kind == "A" and ref.value in known_a)))
        if not ok:
            bad.append(text)
    return bad


def values_of(literal: Any) -> tuple[str, ...]:
    """The values of a ``Literal`` alias, as the schema would list them."""
    return tuple(str(v) for v in get_args(literal))

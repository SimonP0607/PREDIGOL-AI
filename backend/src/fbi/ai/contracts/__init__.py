"""The six contracts of PrediGol Intelligence and the one door through which an answer of a model comes in (``parse``).

``base`` holds the closed values and the machinery (the wire schema, the typed references); ``claim``, ``assessment``, ``council``,
``postmatch`` and ``learning`` are the five outputs; ``mcp`` is the package a model reads. See ``base`` for what an output can never carry.

A model's answer is DATA until ``parse`` says otherwise: JSON that is not JSON, a contract name nobody accepts, a field that is not in
the schema, a value that is not in the list - every one is a ``problem``, none raises, and none echoes the text that caused it (the answer
of a model may be an attacker's: it goes into a log and a table as a short, closed description, not as the offending text).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Final

from pydantic import ValidationError

from fbi.ai.contracts.assessment import AssessmentOut
from fbi.ai.contracts.base import (
    ASSESSMENT,
    CLAIM,
    COUNCIL,
    LEARNING,
    MCP,
    OUTPUTS,
    POST_MATCH,
    Contract,
    wire_schema,
)
from fbi.ai.contracts.claim import ClaimsOut
from fbi.ai.contracts.council import CouncilOut
from fbi.ai.contracts.learning import LearningOut
from fbi.ai.contracts.postmatch import PostMatchOut

CONTRACTS: Final[dict[str, type[Contract]]] = {
    CLAIM: ClaimsOut, ASSESSMENT: AssessmentOut, COUNCIL: CouncilOut, POST_MATCH: PostMatchOut, LEARNING: LearningOut}
"""Every output contract by its name (the ``contract`` field of an answer)."""

WRITERS: Final[dict[str, str]] = {
    CLAIM: "extractor", ASSESSMENT: "match, stats", COUNCIL: "council", POST_MATCH: "post-match reviewer", LEARNING: "learning analyst"}

ACCEPTS: Final[dict[str, tuple[str, ...]]] = {name: (name,) for name in OUTPUTS}
"""The versions a reader takes for each contract. An incompatible change is a NEW name (``aa-v2``) and both are listed here until the old
one has no answer left to read; an old version is never edited in place."""

MAX_PROBLEMS: Final = 5
MAX_RAW: Final = 200_000
"""An answer longer than this (characters) is refused before it is parsed: no contract here needs a tenth of it."""


@dataclass(frozen=True, slots=True)
class Parsed:
    """The result of reading an answer: the value when there is one, otherwise what was wrong, in words that carry none of the answer."""

    contract: str
    value: Contract | None = None
    problems: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.problems


def schema_of(contract: str) -> dict[str, Any]:
    """The schema of an output, in the form structured outputs take (``base.wire_schema``)."""
    if contract not in CONTRACTS:
        raise KeyError(f"{contract!r} is not an output contract")
    return _schema(contract)


@cache
def _schema(contract: str) -> dict[str, Any]:
    return wire_schema(CONTRACTS[contract])


def parse(contract: str, raw: str | bytes | dict[str, Any]) -> Parsed:
    """An answer as the server reads it. ``contract`` is the one that was asked for; the answer's own ``contract`` field must be one of
    the versions the reader accepts for it. Never raises."""
    if contract not in CONTRACTS:
        return Parsed(contract, problems=("unknown_contract",))
    data: Any = raw
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_RAW:
            return Parsed(contract, problems=("too_long",))
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            return Parsed(contract, problems=("not_json",))
    if not isinstance(data, dict):
        return Parsed(contract, problems=("not_an_object",))
    said = data.get("contract")
    if said not in ACCEPTS[contract]:
        return Parsed(contract, problems=("wrong_contract",))
    try:
        value = CONTRACTS[said if isinstance(said, str) else contract].model_validate(data)
    except ValidationError as exc:
        return Parsed(contract, problems=_describe(exc))
    except (ValueError, TypeError, RecursionError):
        return Parsed(contract, problems=("invalid",))
    return Parsed(contract, value=value)


def _describe(exc: ValidationError) -> tuple[str, ...]:
    """The first few errors as ``where:kind`` - the location and the KIND of error (``missing``, ``enum``, ``extra_forbidden``...),
    never the value that was given."""
    out: list[str] = []
    for err in exc.errors(include_input=False, include_url=False, include_context=False)[:MAX_PROBLEMS]:
        where = ".".join(str(p) for p in err.get("loc", ())) or "answer"
        out.append(f"{where}:{err.get('type', 'invalid')}")
    return tuple(out) or ("invalid",)


__all__ = ["ACCEPTS", "CONTRACTS", "MCP", "WRITERS", "Parsed", "parse", "schema_of"]

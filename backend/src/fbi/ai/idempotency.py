"""``idem_key``: the key under which a task of an agent is paid once (Plan Maestro IA, sections 6 and 18).

Two tasks with the same key are the same question put to the same model in the same words: the second is not asked, it reads the stored
answer. So the key is made of everything that can change the answer, and of nothing else.

IN the key:

    workspace        production and the LAB pay separately and never read each other's answers (an arm's answer is for its analysis only)
    agent, agent_version, prompt_version, schema_version, model, effort
                     the registry's row of the agent: a new prompt, a new schema, a new model or another effort is another question
    input_version, input_hash
                     what the model READS: the hash of its slice (or of the Council's view) and the version of the code that derived it
    pass_kind, fixture_id, candidates
                     the pass (``first``, ``pre``, ``final``, ``request``), the match and the selections asked about (``c1``, ``c2``...)

NOT in it: the attempt, the way the task travels (Batch or real time), the clock, the budget - none of them changes what is asked - and
the package as a whole: an agent reads its SLICE, so a block it does not read moving does not make it pay again.

A change in how the key is made changes EVERY key, and every task would be paid again the day it ships. ``VERSION`` is the first thing
hashed and a golden value in the tests is the guard; a new way of making the key is a new version, never an edit of this one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args

from fbi.ai.contracts.assessment import CANDIDATES_MAX
from fbi.ai.contracts.base import CANDIDATE
from fbi.ai.contracts.mcp import PassKind

VERSION: Final = "idem-v1"
CUSTOM_ID_LENGTH: Final = 48
"""A Message Batch names each request with a ``custom_id`` of at most 64 characters; the first 48 of the key are as unique as the key
(192 bits) and match the convention of ``fbi.ai.batch.custom_id_of``."""

Workspace = Literal["production", "lab"]
Effort = Literal["low", "medium"]

WORKSPACES: Final[tuple[str, ...]] = get_args(Workspace)
EFFORTS: Final[tuple[str, ...]] = get_args(Effort)
PASS_KINDS: Final[tuple[str, ...]] = get_args(PassKind)
NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
"""An agent, a version or a model: ASCII, no spaces, nothing that could be read as a separator."""
SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
FIELDS: Final = ("workspace", "agent", "agent_version", "prompt_version", "schema_version", "model", "effort", "input_version", "input_hash",
                 "pass_kind", "fixture_id", "candidates")


class IdempotencyError(ValueError):
    """A task that is not well formed: nothing is hashed from it, and what is wrong with it is said in codes."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    """Everything that can change the answer to a task. Validated when it is made."""

    workspace: Workspace
    agent: str
    agent_version: str
    prompt_version: str
    schema_version: str
    model: str
    effort: Effort
    input_version: str
    """The version of the code that derived the input (``fbi.ai.package.VERSION``, a view's version)."""
    input_hash: str
    """The sha256 of what the model reads: ``Slice.hash``, or the hash of the Council's view."""
    pass_kind: PassKind
    fixture_id: int
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        problems = problems_of(self)
        if problems:
            raise IdempotencyError(problems)

    def fields(self) -> dict[str, Any]:
        """What is hashed, in a form that is kept next to the key to explain it: names, hashes, numbers and the sorted candidates."""
        return {"workspace": self.workspace, "agent": self.agent, "agent_version": self.agent_version,
                "prompt_version": self.prompt_version, "schema_version": self.schema_version, "model": self.model, "effort": self.effort,
                "input_version": self.input_version, "input_hash": self.input_hash, "pass_kind": self.pass_kind,
                "fixture_id": self.fixture_id, "candidates": sorted(self.candidates)}

    @property
    def key(self) -> str:
        return idem_key(self)


def problems_of(identity: TaskIdentity) -> list[str]:
    """Every way an identity is not well formed, as ``field:code`` (all of them, not the first)."""
    problems: list[str] = []
    for name in ("agent", "agent_version", "prompt_version", "schema_version", "model", "input_version"):
        value = getattr(identity, name)
        if not isinstance(value, str) or not NAME.fullmatch(value):
            problems.append(f"{name}:malformed")
    if identity.workspace not in WORKSPACES:
        problems.append("workspace:unknown")
    if identity.effort not in EFFORTS:
        problems.append("effort:unknown")
    if identity.pass_kind not in PASS_KINDS:
        problems.append("pass_kind:unknown")
    if not isinstance(identity.input_hash, str) or not SHA256.fullmatch(identity.input_hash):
        problems.append("input_hash:not_a_sha256")
    fixture = identity.fixture_id
    if not isinstance(fixture, int) or isinstance(fixture, bool) or fixture < 1:
        problems.append("fixture_id:not_a_positive_integer")
    candidates = identity.candidates
    if not isinstance(candidates, tuple):
        problems.append("candidates:not_a_tuple")
    else:
        if any(not isinstance(c, str) or not CANDIDATE.fullmatch(c) for c in candidates):
            problems.append("candidates:malformed")
        if len(set(candidates)) != len(candidates):
            problems.append("candidates:duplicated")
        if len(candidates) > CANDIDATES_MAX:
            problems.append("candidates:too_many")
    return problems


def canonical(fields: dict[str, Any]) -> str:
    """The text that is hashed: the version of the key, then the fields, in one JSON with sorted names and no spaces. Its own function
    (not ``fbi.ai.packet.canonical``): the key must not move when the packet's canonical form is touched for another reason."""
    return json.dumps({"key": VERSION, **fields}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def idem_key(identity: TaskIdentity) -> str:
    """The key of a task: 64 hex characters (the unique ``ai.agent_tasks.idem_key`` and the ``idem_key`` of ``ai.agent_runs``)."""
    return hashlib.sha256(canonical(identity.fields()).encode("ascii")).hexdigest()


def custom_id(key: str) -> str:
    """The name of the task inside a Message Batch: the first 48 characters of its key."""
    if not SHA256.fullmatch(key):
        raise IdempotencyError(["key:not_a_sha256"])
    return key[:CUSTOM_ID_LENGTH]


def changed_fields(a: TaskIdentity, b: TaskIdentity) -> tuple[str, ...]:
    """Which fields make two tasks different keys: the answer to "why was this paid again?"."""
    fa, fb = a.fields(), b.fields()
    return tuple(name for name in FIELDS if fa[name] != fb[name])

"""The API-Football v3 contract as the provider documents it, read from ``config/api_football/v3_contract.txt``.

The text is the provider's OpenAPI document (v3.9.3) written out operation by operation (format in
``v3_contract.meta.json``) and checked byte for byte against the documentation page. This module turns
it into endpoints, parameters, update frequencies, recommended call rates, pagination, id batch limits
and the documented response field paths - what ``scripts.audit_api_contract`` compares with what
PrediGol requests, stores and reads.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[4] / "config" / "api_football" / "v3_contract.txt"
TYPES = {"s": "string", "n": "number", "b": "boolean", "z": "null", "a": "array", "o": "object"}


@dataclass(frozen=True)
class Param:
    name: str
    where: str
    required: bool
    type: str
    format: str
    enum: tuple[str, ...]
    pattern: str
    minimum: str
    maximum: str
    min_length: str
    max_length: str
    description: str


@dataclass
class Endpoint:
    path: str
    tag: str
    operation_id: str
    summary: str
    params: list[Param] = field(default_factory=list)
    description: list[str] = field(default_factory=list)
    responses: dict[str, str] = field(default_factory=dict)
    skeleton: str = ""
    envelope: list[tuple[str, str]] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)

    @property
    def query_params(self) -> list[Param]:
        return [p for p in self.params if p.where == "query"]

    def _line(self, label: str) -> str | None:
        for d in self.description:
            m = re.match(r"\*\*" + label + r"\*\*\s*:\s*(.+)$", d)
            if m:
                return m.group(1).replace("`*`", "").strip()
        return None

    @property
    def update_frequency(self) -> str | None:
        return self._line("Update Frequency")

    @property
    def recommended_calls(self) -> str | None:
        return self._line("Recommended Calls")

    @property
    def page_size(self) -> int | None:
        for d in self.description:
            m = re.search(r"\*\*Pagination\*\*\s*:\s*(\d+) results per page", d)
            if m:
                return int(m.group(1))
        return None

    @property
    def requires_a_param(self) -> bool:
        return any("requires at least one parameter" in d for d in self.description)

    @property
    def batch_limits(self) -> dict[str, int]:
        """Parameters taking several ids in one call, with their documented maximum ("Maximum of 20 ...")."""
        out = {}
        for p in self.params:
            m = re.search(r"Maximum of (\d+)", p.pattern)
            if m:
                out[p.name] = int(m.group(1))
        return out

    @property
    def needs_no_param(self) -> bool:
        return any("does not require any parameters" in d for d in self.description)

    def fields(self) -> list[tuple[str, str]]:
        """The documented response field paths with their example types ("response[].fixture.id", "number")."""
        return list(field_paths(self.skeleton)) if self.skeleton else []


def _split_param(line: str) -> Param:
    parts = line.split("|")
    head, tail = parts[:6], parts[-5:]
    pattern = "|".join(parts[6:-5])
    name, where, req, typ, fmt, enum = head
    return Param(name, where, req == "req", typ, fmt, tuple(e for e in enum.split("/") if e), pattern.strip(),
                 tail[0], tail[1], tail[2], tail[3], tail[4].strip())


HEADER = re.compile(r"^## GET (\S+) \[([^\]]*)\] (\S*) :: (.*)$")


def parse(text: str) -> list[Endpoint]:
    out: list[Endpoint] = []
    cur: Endpoint | None = None
    for line in text.split("\n"):
        if not line:
            continue
        m = HEADER.match(line)
        if m:
            cur = Endpoint(m.group(1), m.group(2), m.group(3), m.group(4))
            out.append(cur)
            continue
        if cur is None:
            raise ValueError(f"line before any operation: {line[:60]!r}")
        kind, rest = line[:1], line[2:]
        if kind == "P":
            cur.params.append(_split_param(rest))
        elif kind == "D":
            cur.description.append(rest)
        elif kind == "R":
            code, _, desc = rest.partition(" ")
            cur.responses[code] = desc
        elif kind == "F":
            cur.skeleton = rest
        elif kind == "E":
            cur.envelope = [(p.rpartition(":")[0], TYPES.get(p.rpartition(":")[2], p.rpartition(":")[2]))
                            for p in rest.split()]
        elif kind == "U":
            cur.use_cases.append(rest)
        else:
            raise ValueError(f"unknown line kind {kind!r}: {line[:60]!r}")
    return out


@cache
def endpoints(path: Path = CONTRACT) -> tuple[Endpoint, ...]:
    return tuple(parse(path.read_text(encoding="utf-8")))


def by_path(path: Path = CONTRACT) -> dict[str, Endpoint]:
    return {e.path: e for e in endpoints(path)}


# ── the typed skeleton: {R[]:{fixture:{id:n,...},...}} ──────────────────────


def field_paths(skeleton: str) -> Iterator[tuple[str, str]]:
    """Leaf paths of a skeleton ("response[].league.standings[][].rank", "number")."""
    pos = 0

    def value(prefix: str) -> Iterator[tuple[str, str]]:
        nonlocal pos
        if skeleton[pos] == "{":
            pos += 1
            if skeleton[pos] == "}":
                pos += 1
                yield prefix, "object"
                return
            while True:
                start = pos
                while skeleton[pos] != ":":
                    pos += 1
                key = skeleton[start:pos]
                pos += 1
                name = "response" + key[1:] if key in ("R", "R[]") or key.startswith("R[") else key
                yield from value(f"{prefix}.{name}" if prefix else name)
                if skeleton[pos] == ",":
                    pos += 1
                    continue
                if skeleton[pos] == "}":
                    pos += 1
                    return
                raise ValueError(f"bad skeleton at {pos}: {skeleton[pos - 10:pos + 10]!r}")
        start = pos
        while pos < len(skeleton) and skeleton[pos] not in ",}":
            pos += 1
        yield prefix, "/".join(TYPES.get(t, t) for t in skeleton[start:pos].split("/"))

    yield from value("")

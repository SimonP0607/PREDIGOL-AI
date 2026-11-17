"""Whether a change of a contract's shape is additive or breaks it, and whether its version says so (AD-J01, IA-057).

A shape is reduced to a set of facts read from its JSON Schema (as the API serves it): each key path, whether it is always
present, the kind of value it holds, each value of a closed list, and the alternatives of a union. Then:

* a fact that disappears breaks the contract - a field removed, a field that may now be absent, a type changed, a closed
  value removed, a new alternative in a union (``x`` that can now be ``Missing``): the major version goes up;
* only new facts is an additive change - a new field, a new closed value: the minor version goes up;
* the same facts: the version may stay (or raise its patch for a change of descriptions).

Descriptions, defaults and numeric limits are not part of the shape.
"""

from __future__ import annotations

import json
from typing import Any, Literal

Bump = Literal["none", "minor", "major"]


def _label(node: dict[str, Any]) -> str:
    ref = node.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    if "const" in node:
        return f"const {json.dumps(node['const'], ensure_ascii=False)}"
    return str(node.get("type", "any"))


def schema_facts(schema: dict[str, Any]) -> frozenset[str]:
    defs: dict[str, Any] = schema.get("$defs", {})
    facts: set[str] = set()

    def walk(node: dict[str, Any], path: str, stack: frozenset[str]) -> None:
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name in stack:
                facts.add(f"{path} :: recursive {name}")
            else:
                walk(defs[name], path, stack | {name})
            return
        alternatives = node.get("anyOf") or node.get("oneOf")
        if alternatives:
            labels = sorted(_label(a) for a in alternatives)
            facts.add(f"{path} :: one of {', '.join(labels)}")
            for alternative in alternatives:
                walk(alternative, f"{path}|{_label(alternative)}", stack)
            return
        kind = str(node.get("type", "any")) + (f"/{node['format']}" if "format" in node else "")
        facts.add(f"{path} :: {kind}")
        values = node.get("enum", []) + ([node["const"]] if "const" in node else [])
        facts.update(f"{path} = {json.dumps(v, ensure_ascii=False)}" for v in values)
        required = set(node.get("required", []))
        for key, sub in node.get("properties", {}).items():
            facts.add(f"{path}.{key}")
            if key in required:
                facts.add(f"{path}.{key} !always")
            walk(sub, f"{path}.{key}", stack)
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{path}[]", stack)
        if isinstance(node.get("additionalProperties"), dict):
            walk(node["additionalProperties"], f"{path}{{}}", stack)

    walk(schema, "$", frozenset())
    return frozenset(facts)


def required_bump(old: frozenset[str] | set[str], new: frozenset[str] | set[str]) -> Bump:
    if set(old) - set(new):
        return "major"
    if set(new) - set(old):
        return "minor"
    return "none"


def parse(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def version_problem(old: str, new: str, bump: Bump) -> str | None:
    """Why ``new`` is not a valid version after a change of kind ``bump`` from ``old`` (None: it is)."""
    o, n = parse(old), parse(new)
    if n < o:
        return f"the version went back from {old} to {new}"
    if bump == "major" and n[0] <= o[0]:
        return f"a change that breaks the contract needs a new major version ({o[0] + 1}.0.0), not {new}"
    if bump == "minor" and n[:2] <= o[:2]:
        return f"an additive change needs at least a new minor version ({o[0]}.{o[1] + 1}.0), not {new}"
    return None

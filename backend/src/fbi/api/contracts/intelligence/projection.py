"""Two projections of one contract, and the check that the public one leaks nothing (AD-J01, IA-057).

The private projection is the full model. The public one is a class the private one inherits from: the private class adds
fields, each marked ``private(...)``, and may narrow a field to its private variant (a list of private selections where
the public has public ones) - never the reverse. ``to_public`` builds the public answer from the private one by copying
only the fields the public classes declare, at every depth, and validating the result with the public class: a private
field is not hidden, it is never copied. An item that answers ``shown_in_public() is False`` (a selection the owner did
not publish) is left out of its list, and a list left empty that way says ``sin_publicados`` - which tells a reader
nothing they would not see anyway.

``leaks`` is the generic test of a public answer: no key that only the private schema has, no key the public schema does
not have, no state of the cycle other than ``publicada``, ``en_juego`` or ``liquidada``, and ``projection: "public"``.
"""

from __future__ import annotations

import types
from collections.abc import Iterator
from functools import cache
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    is_private,
)
from fbi.api.contracts.intelligence.vocab import LifecycleState, PublicState

ROOTS: tuple[type[BaseModel], ...] = (IntelligenceModel, IntelligenceContract)
LIFECYCLE_ONLY = frozenset(get_args(LifecycleState)) - frozenset(get_args(PublicState))
"""The states of the cycle a reader never sees."""


class ProjectionError(ValueError):
    """The private answer cannot be turned into a public one (a contract that breaks the convention)."""


def _models_in(annotation: Any) -> Iterator[type[BaseModel]]:
    if get_origin(annotation) is Literal:
        return
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in get_args(annotation):
        yield from _models_in(arg)


def _untyped(annotation: Any) -> bool:
    """A field that could carry anything (``Any``, ``object``, a free ``dict``): the projection could not tell its keys."""
    if annotation is Any or annotation is object:
        return True
    origin = get_origin(annotation)
    if origin is dict or annotation is dict:
        return True
    if origin is Literal or (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        return False
    if origin in (Annotated, list, tuple, Union, types.UnionType):
        return any(_untyped(arg) for arg in get_args(annotation) if arg is not Ellipsis)
    return False


@cache
def reachable(model: type[BaseModel]) -> tuple[type[BaseModel], ...]:
    """Every model a model's fields can hold, itself first."""
    seen: list[type[BaseModel]] = []
    todo = [model]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.append(current)
        for field in current.model_fields.values():
            todo.extend(_models_in(field.annotation))
    return tuple(seen)


def private_fields(model: type[BaseModel]) -> tuple[str, ...]:
    return tuple(name for name in model.model_fields if is_private(model, name))


@cache
def has_private(model: type[BaseModel]) -> bool:
    """True when a private field is reachable from the model: then it belongs to a private projection."""
    return any(private_fields(m) for m in reachable(model))


def public_counterpart(model: type[BaseModel]) -> type[BaseModel]:
    """The public class a private one derives from: the nearest base with nothing private (the model itself if it has
    nothing private)."""
    if not has_private(model):
        return model
    for base in model.__mro__[1:]:
        if (isinstance(base, type) and issubclass(base, IntelligenceModel) and base not in ROOTS
                and not has_private(base)):
            return base
    raise ProjectionError(f"{model.__name__} has private fields and no public class to derive from")


def structure_problems(model: type[BaseModel]) -> list[str]:
    """What breaks the convention anywhere in a model's tree (empty: nothing)."""
    problems: list[str] = []
    for m in reachable(model):
        for name, field in m.model_fields.items():
            if _untyped(field.annotation):
                problems.append(f"{m.__name__}.{name} is untyped: every field of a contract has a declared shape")
        if not has_private(m):
            continue
        try:
            base = public_counterpart(m)
        except ProjectionError as exc:
            problems.append(str(exc))
            continue
        for name in m.model_fields.keys() - base.model_fields.keys():
            if not is_private(m, name):
                problems.append(f"{m.__name__}.{name} is added to {base.__name__} without being marked private")
    return problems


def _hidden(value: object) -> bool:
    return isinstance(value, IntelligenceModel) and not value.shown_in_public()


def _public_data(value: Any) -> Any:
    if isinstance(value, IntelligenceModel):
        if not value.shown_in_public():
            raise ProjectionError(f"a {type(value).__name__} that is not shown in public is not an item of a list")
        target = public_counterpart(type(value))
        data = {name: _public_data(getattr(value, name)) for name in target.model_fields}
        if isinstance(value, ItemList) and value.items and not data["items"]:
            data.update(missing_reason="sin_publicados", expected_piece=None, expected_at=None, sample=None,
                        min_sample=None)
        return data
    if isinstance(value, BaseModel):
        return {name: _public_data(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, list | tuple):
        return [_public_data(item) for item in value if not _hidden(item)]
    return value


def to_public[P: IntelligenceContract](answer: IntelligenceContract, public: type[P]) -> P:
    """The public projection of a private answer, built from the public class's fields only."""
    if not isinstance(answer, public):
        raise ProjectionError(f"{type(answer).__name__} does not derive from {public.__name__}")
    if has_private(public):
        raise ProjectionError(f"{public.__name__} carries private fields: it is not a public projection")
    data = _public_data(answer)
    data["projection"] = "public"
    return public.model_validate(data)


# ── the generic leak check ──────────────────────────────────────────────────────────────────────────────────────────

def schema_paths(schema: dict[str, Any]) -> frozenset[str]:
    """Every key path a JSON Schema allows (``$.selections.items[].lifecycle_state``), unions merged."""
    defs: dict[str, Any] = schema.get("$defs", {})
    found: set[str] = set()

    def walk(node: dict[str, Any], path: str, stack: frozenset[str]) -> None:
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in stack:
                walk(defs[name], path, stack | {name})
            return
        for alternative in node.get("anyOf", []) + node.get("oneOf", []) + node.get("allOf", []):
            walk(alternative, path, stack)
        for key, sub in node.get("properties", {}).items():
            found.add(f"{path}.{key}")
            walk(sub, f"{path}.{key}", stack)
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{path}[]", stack)

    walk(schema, "$", frozenset())
    return frozenset(found)


def payload_paths(payload: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    """Every key path of a JSON value, with the value found there."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield f"{path}.{key}", value
            yield from payload_paths(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for value in payload:
            yield from payload_paths(value, f"{path}[]")


def leaks(payload: Any, *, public_schema: dict[str, Any], private_schema: dict[str, Any]) -> list[str]:
    """Why a public answer (as JSON) is not public (empty: it is)."""
    public_paths = schema_paths(public_schema)
    private_only = schema_paths(private_schema) - public_paths
    problems: list[str] = []
    for path, value in payload_paths(payload):
        if path in private_only:
            problems.append(f"{path}: a private field in the public projection")
        elif path not in public_paths:
            problems.append(f"{path}: not in the public schema")
        if isinstance(value, str) and value in LIFECYCLE_ONLY:
            problems.append(f"{path}: the state {value!r} is not public")
        if path.endswith(".public_state") and value not in get_args(PublicState):
            problems.append(f"{path}: {value!r} is not publicada, en_juego or liquidada")
    if not isinstance(payload, dict) or payload.get("projection") != "public":
        problems.append("$.projection: the answer does not say it is the public projection")
    return problems

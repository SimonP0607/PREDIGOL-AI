"""The JSON Schema the provider's structured outputs accept (``output_config.format``) - and what is done with the rest.

The API takes a SUBSET of JSON Schema (Anthropic's documentation, read on 26 Oct 2026; the equivalence experiment ``equiv-v1`` found it the hard way:
210 of its 210 asks that sent the review schema as it is came back ``invalid_request_error``, and not one of them was an answer of the model).
Not supported: numerical constraints (``minimum``, ``maximum``, ``multipleOf``), string constraints (``minLength``, ``maxLength``), array constraints
beyond ``minItems`` of 0 or 1 (so no ``maxItems``), recursive schemas and an ``additionalProperties`` other than ``false``. Limits of one request:
24 optional parameters and 16 parameters with a union type (``anyOf`` or a list of types). An unsupported keyword is a HTTP 400.

Anthropic's own SDK helpers do two things with a schema that asks for more: they take the constraint out and write it in the description of the field
(``{minimum: 0, maximum: 1}``), and they check the answer against the original schema. PrediGol does the same:

* ``accepted`` is what is SENT: the same schema, with the constraints the API refuses moved into the descriptions (the model still reads them) and
  ``additionalProperties: false`` on every object. A schema with nothing to move comes out equal to what went in.
* The ORIGINAL schema's constraints stay enforced where they always were: the validators of each answer (the models of ``fbi.ai``) read what comes back,
  and a value outside them is an invalid output, exactly as with a forced tool call. Decoding is only guided by the simpler schema.
* ``problems`` says what is still wrong with a schema AS SENT - a keyword the API refuses, an object that is not closed, more optional or union
  parameters than a request may carry - so that a test over every schema PrediGol asks for catches a change that would make the API answer 400
  before it does so in production.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

MOVED = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "maxItems",
         "uniqueItems", "minProperties", "maxProperties")
"""Keywords the API refuses, wherever they appear in the schema. ``minItems`` is refused above 1 (0 and 1 are supported)."""
MAX_OPTIONAL = 24
MAX_UNIONS = 16
"""The limits of a request (documented): optional parameters, and parameters whose type is a union."""
_LISTS = ("anyOf", "allOf", "oneOf")


def _refused(key: str, value: Any) -> bool:
    return key in MOVED or (key == "minItems" and value not in (0, 1))


def accepted(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The schema as the API takes it (a new object: the argument is not touched). See the module's docstring."""
    node = _simplify(schema)
    assert isinstance(node, dict)
    return node


def _simplify(node: Any) -> Any:
    if isinstance(node, list):
        return [_simplify(n) for n in node]
    if not isinstance(node, Mapping):
        return copy.deepcopy(node)
    out: dict[str, Any] = {}
    moved: dict[str, Any] = {}
    for key, value in node.items():
        if _refused(key, value):
            moved[key] = value
        elif key == "properties" and isinstance(value, Mapping):
            out[key] = {name: _simplify(sub) for name, sub in value.items()}  # a property NAMED ``minimum`` is a name, not a keyword
        elif key in ("$defs", "definitions") and isinstance(value, Mapping):
            out[key] = {name: _simplify(sub) for name, sub in value.items()}
        elif key in _LISTS and isinstance(value, list):
            out[key] = [_simplify(sub) for sub in value]
        elif key in ("items", "additionalProperties") and isinstance(value, Mapping):
            out[key] = _simplify(value)
        else:
            out[key] = copy.deepcopy(value)
    if moved:
        note = "{" + ", ".join(f"{k}: {json.dumps(v)}" for k, v in moved.items()) + "}"
        said = out.get("description")
        out["description"] = f"{said} {note}" if isinstance(said, str) and said else note
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    return out


def problems(schema: Mapping[str, Any]) -> list[str]:
    """What the API would still refuse in a schema AS SENT (so: pass ``accepted(...)``): empty when nothing."""
    found: list[str] = []
    counts = {"optional": 0, "unions": 0}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, sub in enumerate(node):
                walk(sub, f"{path}[{i}]")
            return
        if not isinstance(node, Mapping):
            return
        for key, value in node.items():
            if _refused(key, value):
                found.append(f"{path or '$'}: '{key}' is not supported by structured outputs")
        if "$ref" in node:
            found.append(f"{path or '$'}: '$ref' is not checked here (a recursive schema is refused)")
        if node.get("type") == "object" or "properties" in node:
            if node.get("additionalProperties") is not False:
                found.append(f"{path or '$'}: an object must say additionalProperties: false")
            required = set(node.get("required") or [])
            counts["optional"] += sum(1 for name in (node.get("properties") or {}) if name not in required)
        if isinstance(node.get("anyOf"), list) or isinstance(node.get("type"), list):
            counts["unions"] += 1
        for name, sub in (node.get("properties") or {}).items():
            walk(sub, f"{path}.{name}" if path else name)
        for key in ("$defs", "definitions"):
            for name, sub in (node.get(key) or {}).items():
                walk(sub, f"{path}.{key}.{name}" if path else f"{key}.{name}")
        for key in _LISTS:
            if isinstance(node.get(key), list):
                walk(node[key], f"{path}.{key}" if path else key)
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), Mapping):
                walk(node[key], f"{path}.{key}" if path else key)

    walk(schema, "")
    if counts["optional"] > MAX_OPTIONAL:
        found.append(f"{counts['optional']} optional parameters; a request may carry {MAX_OPTIONAL}")
    if counts["unions"] > MAX_UNIONS:
        found.append(f"{counts['unions']} parameters with a union type; a request may carry {MAX_UNIONS}")
    return found

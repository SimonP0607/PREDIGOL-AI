"""The shape of what the client routes answer today, kept in a file so that a change of the user layer cannot change it unseen.

Plan UX, A0 ("instantáneas de forma"): the user layer consumes PrediGol Intelligence and must not alter what the API already answers.
For each of the six routes a client reads every day, the snapshot holds the route's parameters and the JSON Schema of its 200
answer with every schema it refers to, resolved from the application's own OpenAPI document (``create_app().openapi()``: the
models FastAPI validates every answer against, so the schema IS the shape of the data). ``tests/unit/test_client_api_shapes.py``
compares it on every run; a difference fails the test and prints what changed.

A change that is meant is written down, never slipped in: ``python -m scripts.api_shapes write --reason "..."`` rewrites the file
and appends the date and the reason to its ``changes`` list (it refuses to write without a reason, and refuses when nothing changed).

    python -m scripts.api_shapes check                     # exit 0 when the snapshot is current, 1 with the differences
    python -m scripts.api_shapes write --reason "A9: ..."  # after a deliberate change of a client route
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "snapshots" / "client_api_shapes.json"

ROUTES: tuple[tuple[str, str], ...] = (
    ("get", "/api/v1/home"),
    ("get", "/api/v1/picks"),
    ("get", "/api/v1/daily"),
    ("get", "/api/v1/odds/best"),
    ("get", "/api/v1/me/history"),
    ("get", "/api/v1/matches/{fixture_id}/center"),
)
"""The six client routes the plan names (section 4, "Instantáneas de forma"), as the API mounts them."""

REF = "#/components/schemas/"


def _openapi() -> dict[str, Any]:
    # the application refuses to start without a second-factor key only in production; a test key is enough to build it
    os.environ.setdefault("FBI_AUTH_SECRET_KEY", "dGVzdC1vbmx5LWtleS1mb3ItcHJlZGlnb2wtdGVzdHM=")
    from fbi.api.app import create_app

    return create_app().openapi()


def _refs(node: Any) -> set[str]:
    """The component names a schema refers to, at any depth."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(REF):
            found.add(ref[len(REF):])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def _closure(root: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """Every component reachable from ``root``, by name."""
    seen: dict[str, Any] = {}
    todo = sorted(_refs(root))
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen[name] = components[name]
        todo.extend(sorted(_refs(components[name]) - set(seen)))
    return dict(sorted(seen.items()))


def current() -> dict[str, Any]:
    """The shapes as the code answers them now."""
    spec = _openapi()
    components = spec.get("components", {}).get("schemas", {})
    routes: dict[str, Any] = {}
    for method, path in ROUTES:
        op = spec["paths"][path][method]
        answer = op["responses"]["200"]["content"]["application/json"]["schema"]
        params = sorted(
            ({"name": p["name"], "in": p["in"], "required": bool(p.get("required", False)), "schema": p.get("schema", {})}
             for p in op.get("parameters", [])),
            key=lambda p: (p["in"], p["name"]),
        )
        routes[f"{method.upper()} {path}"] = {"parameters": params, "answer": answer,
                                              "schemas": _closure(answer, components)}
    return routes


def stored() -> dict[str, Any]:
    return dict(json.loads(SNAPSHOT.read_text(encoding="utf-8")))


def differences(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What changed, route by route and schema by schema, in words a reader can act on."""
    lines: list[str] = []
    for route in sorted(set(old) | set(new)):
        if route not in new:
            lines.append(f"{route}: no longer in the snapshot routes")
            continue
        if route not in old:
            lines.append(f"{route}: not in the stored snapshot")
            continue
        a, b = old[route], new[route]
        if a["parameters"] != b["parameters"]:
            lines.append(f"{route}: parameters changed: {a['parameters']} -> {b['parameters']}")
        if a["answer"] != b["answer"]:
            lines.append(f"{route}: answer changed: {a['answer']} -> {b['answer']}")
        for name in sorted(set(a["schemas"]) | set(b["schemas"])):
            if name not in b["schemas"]:
                lines.append(f"{route}: schema {name} is no longer reachable")
            elif name not in a["schemas"]:
                lines.append(f"{route}: schema {name} is new")
            elif a["schemas"][name] != b["schemas"][name]:
                lines.append(f"{route}: schema {name} changed: "
                             f"{json.dumps(a['schemas'][name], sort_keys=True)[:300]} -> "
                             f"{json.dumps(b['schemas'][name], sort_keys=True)[:300]}")
    return lines


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="compare the code with the stored snapshot")
    write = sub.add_parser("write", help="rewrite the snapshot after a deliberate change")
    write.add_argument("--reason", required=True, help="why the shape changes: the phase and what it adds or removes")
    args = parser.parse_args(argv)
    now = current()
    if args.cmd == "check":
        diff = differences(stored()["routes"], now)
        print("\n".join(diff) if diff else "the stored snapshot is current")
        return 1 if diff else 0
    reason = args.reason.strip()
    if len(reason) < 10:
        print("a reason of a few words is required: what changes and why", file=sys.stderr)
        return 2
    previous: dict[str, Any] = stored() if SNAPSHOT.exists() else {"routes": {}, "changes": []}
    if previous["routes"] == now:
        print("nothing changed: the snapshot is already current", file=sys.stderr)
        return 2
    changes = list(previous.get("changes", []))
    changes.append({"date": datetime.now(UTC).strftime("%Y-%m-%d"), "reason": reason})
    SNAPSHOT.write_text(_dump({"routes": now, "changes": changes}), encoding="utf-8")
    print(f"wrote {SNAPSHOT.relative_to(Path.cwd()) if SNAPSHOT.is_relative_to(Path.cwd()) else SNAPSHOT} "
          f"({len(now)} routes, {sum(len(r['schemas']) for r in now.values())} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

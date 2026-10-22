"""Layering the code must keep: a ratchet over the package import graph of ``src/fbi``.

Measured 21 Oct 2026 (AST, every import including the lazy ones): 20 of 30 packages sat in ONE import cycle. Two
imports into ``fbi.api`` (``ops.baseline``, ``truth.v2.players/team_stats``) held most of it together - the domain
importing the layer that serves it. Cutting them left 9; moving the RAW store out of ``ingestion`` left 8.
Each number below may only go DOWN.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"

# Known inversions (the domain reaching into the API layer), kept visible so they can be removed, never added to.
MAY_IMPORT_API = {"api", "analyst", "picks"}
MAX_CYCLE = 8


def _imports() -> dict[tuple[str, str], list[str]]:
    """(importing package, imported package) -> the modules that do it. Lazy imports count."""
    edges: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in SRC.rglob("*.py"):
        parts = path.relative_to(SRC).with_suffix("").parts
        if len(parts) < 2:
            continue
        source = parts[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
            for name in names:
                head = name.split(".")
                if head[0] == "fbi" and len(head) > 1 and head[1] != source:
                    edges[(source, head[1])].append(".".join(parts))
    return edges


def _largest_cycle(edges: set[tuple[str, str]]) -> list[str]:
    graph: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    reach: dict[str, set[str]] = {}
    for start in list(graph):
        seen: set[str] = set()
        stack = [start]
        while stack:
            for nxt in graph[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        reach[start] = seen
    best: list[str] = []
    for node, seen in reach.items():
        cycle = sorted({node} | {m for m in seen if node in reach.get(m, set())})
        if len(cycle) > len(best) and node in seen:
            best = cycle
    return best


def test_the_domain_does_not_import_the_layer_that_serves_it() -> None:
    wrong = {p: m for (p, q), m in _imports().items() if q == "api" and p not in MAY_IMPORT_API}
    assert not wrong, f"these packages import fbi.api; move the code or inject it: {wrong}"


def test_the_provider_sits_below_ingestion() -> None:
    assert ("providers", "ingestion") not in _imports(), "the provider client may not depend on the ingestion layer"


def test_the_raw_store_depends_on_nothing_of_ours() -> None:
    assert not [q for (p, q) in _imports() if p == "storage"], "fbi.storage (RAW) is a leaf: it imports no fbi package"


def test_the_import_cycle_does_not_grow() -> None:
    cycle = _largest_cycle(set(_imports()))
    assert len(cycle) <= MAX_CYCLE, f"{len(cycle)} packages now import each other in a loop: {cycle}"

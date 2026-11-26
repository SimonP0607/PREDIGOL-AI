"""RP-6.1: Intelligence reads the statistics, it does not calculate them. The packages of the AI layer, the decision, the chronicle and the
intelligence read model may import ``fbi.stats.reading`` (and ``fbi.stats.doc``, the shape of a document) but not the modules that CALCULATE the
figures, so the same match cannot show one number in a text and another on the profile one tap away."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
INTELLIGENCE = ("ai", "intel", "chronicle", "decision", "council", "councilpass", "evalcycle", "evalpass", "narrator", "narrative", "knowledge",
                "newsdesk", "newsroom", "news", "evidence", "factlinks", "lifecycle", "shadowjobs", "parlays", "picks", "valuation", "portfolio")
CALCULATING = {"fbi.stats.team", "fbi.stats.player", "fbi.stats.data", "fbi.stats.extras", "fbi.stats.job", "fbi.stats.expected_table"}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            if node.module == "fbi.stats":
                out |= {f"fbi.stats.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
    return out


def test_intelligence_does_not_import_the_modules_that_calculate_the_statistics() -> None:
    wrong: dict[str, list[str]] = {}
    for package in INTELLIGENCE:
        for path in sorted((SRC / package).rglob("*.py")):
            bad = sorted(_imports(path) & CALCULATING)
            if bad:
                wrong[str(path.relative_to(SRC))] = bad
    assert not wrong, f"Intelligence must read fbi.stats.reading, not calculate: {wrong}"


def test_the_guard_sees_what_it_guards() -> None:
    assert (SRC / "stats" / "reading.py").is_file() and all((SRC / p).is_dir() for p in INTELLIGENCE), "a package moved: update the list"
    assert {p.stem for p in (SRC / "stats").glob("*.py")} >= {"team", "player", "data", "extras", "job", "expected_table", "reading", "doc"}

"""The Portfolio Engine (``fbi.portfolio``, ``portfolio-v1``) is in SHADOW: it computes and reports, and nothing that decides, publishes,
stakes for users or serves the API may import it. The scan reads every import (lazy ones too) of ``src/fbi``, ``apps`` and ``scripts``:
outside the package itself, the only importer is its own read-only command. A new importer fails here until someone decides it may read.
The package's own code is held too: it writes nothing, reaches no serving layer, and takes stake-v1's maths by import, never by copy."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.portfolio"
ALLOWED = {"scripts/ia_portfolio.py": "the command that prints the shadow portfolio (read-only)"}
SERVING = ("intel/", "picks/", "familydecisions/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/", "knowledge/",
           "decision/", "apps/")
"""What decides (``intel``, ``picks``, ``familydecisions``, ``decision``), stakes and combines (``parlays``), publishes or serves users."""


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level and path.parent == SRC:
            found.update(f"fbi.{a.name}" for a in node.names)
    return found


def imports_package(path: Path) -> bool:
    return any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_stakes_or_serves_imports_the_portfolio() -> None:
    wrong = [rel(p) for p in files(SRC, ROOT / "apps") if rel(p).startswith(SERVING) and imports_package(p)]
    assert not wrong, f"the portfolio is shadow-only; these modules import it: {wrong}"


def test_only_its_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps") if not rel(p).startswith("portfolio/") and imports_package(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.portfolio", "from fbi.portfolio import build", "from fbi.portfolio.stakes import allocate",
                 "def f():\n    from fbi.portfolio.build import build_day\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_package(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.parlays import persist", encoding="utf-8")
    assert not imports_package(probe)


def test_the_package_writes_nothing_and_reaches_no_serving_layer() -> None:
    own = files(SRC / "portfolio")
    assert own, "the package exists"
    writes = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\.\w+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE)\b", re.IGNORECASE)
    assert not [rel(p) for p in own if writes.search(p.read_text(encoding="utf-8"))]
    for p in own:
        bad = [n for n in imported(p) if n.split(".")[1:2] and n.split(".")[1] in ("api", "notify", "messaging", "customer", "narrative")]
        assert not bad, (rel(p), bad)
        assert not [n for n in imported(p) if n.endswith((".store", ".build_parlays", ".select_day", ".decide"))], rel(p)


def test_stake_v1_is_imported_never_copied() -> None:
    own = files(SRC / "portfolio")
    users = {rel(p) for p in own if "fbi.intel.stake" in imported(p)}
    assert "portfolio/stakes.py" in users
    for p in own:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        names = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign | ast.AnnAssign)
                 for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
        defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert not names & {"KELLY_FRACTION", "CAPS", "PARLAY_CAP", "STEP"}, rel(p)
        assert not defs & {"kelly", "stake_for"}, rel(p)

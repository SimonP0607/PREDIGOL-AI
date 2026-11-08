"""The budget by value of information (``fbi.budgeting``, ``voi-v1``) is in SHADOW: it computes and reports, and nothing that spends, decides or
publishes may import it. This test holds the door shut by scanning the imports (lazy ones too): no module of ``src/fbi`` outside the package
imports it, and among the scripts and apps only its own read-only command does. A new reader fails here until someone decides it may read.

The other direction is held too: the package itself imports nothing that writes or calls a model (the orchestrator, the runtime, the
providers, the API, the picks)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "budgeting"
MODULE = "fbi.budgeting"
ALLOWED = {"scripts/ia_voi.py": "the command that prints the replay of a day (read-only)"}
NEVER_IMPORTED_BY_IT = ("fbi.ai.orchestrator", "fbi.ai.runtime", "fbi.ai.providers", "fbi.ai.batch", "fbi.ai.cycle", "fbi.api",
                        "fbi.picks", "fbi.notify", "fbi.messaging", "fbi.familydecisions", "fbi.portfolio")


def imported(path: Path) -> set[str]:
    """Every module a file imports, lazy imports included; ``from a import b`` counts as ``a`` and ``a.b``."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(path.relative_to(SRC.parent).with_suffix("").parts[: -node.level])
                head = f"{base}.{node.module}" if node.module else base
            else:
                head = node.module or ""
            out.add(head)
            out |= {f"{head}.{a.name}" for a in node.names}
    return out


def imports_budgeting(path: Path) -> bool:
    return any(m == MODULE or m.startswith(MODULE + ".") for m in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_in_the_product_imports_the_voi_budget() -> None:
    wrong = [rel(p) for p in files(SRC) if PACKAGE not in p.parents and imports_budgeting(p)]
    assert not wrong, f"voi-v1 is shadow-only; these modules import it: {wrong}"


def test_only_its_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(ROOT / "scripts", ROOT / "apps") if imports_budgeting(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_it_imports_nothing_that_spends_or_publishes() -> None:
    for p in files(PACKAGE):
        bad = sorted(m for m in imported(p) if any(m == n or m.startswith(n + ".") for n in NEVER_IMPORTED_BY_IT))
        assert not bad, f"{rel(p)} imports {bad}"


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.budgeting", "import fbi.budgeting.tiers", "from fbi.budgeting import allocation",
                 "from fbi.budgeting.replay import replay_day", "def f():\n    from fbi import budgeting\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_budgeting(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.ai import budget_v3", encoding="utf-8")
    assert not imports_budgeting(probe)

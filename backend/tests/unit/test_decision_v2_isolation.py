"""decision-v2 (``fbi.decision``) is in SHADOW: it computes and reports, and nothing that decides, publishes, stakes or serves users may import
it. The scan reads every import (lazy ones too) of ``src/fbi``, ``apps`` and ``scripts``: outside the package itself, the only importer is its
own read-only command. A new importer fails here until someone decides it may read. The package's own imports are held too: it reaches the
signals of the market and the decision of the families only through the one module each, and never the stake."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.decision"
ALLOWED = {"scripts/ia_decision_v2.py": "the command that prints the replay (read-only)",
           "plugins/family.py": "the plug-in families (IA-018, shadow) compose the MarketFamily protocol",
           "plugins/registry.py": "the registry of plug-in families hands decision-v2 its families (shadow)",
           "plugins/_template/family.py": "the example plug-in's decision-v2 adapter (shadow, never active, not installed)"}
SERVING = ("intel/", "picks/", "familydecisions/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/", "knowledge/",
           "apps/")
"""What decides (``intel``, ``picks``, ``familydecisions``), stakes and combines (``parlays``), publishes or serves users."""


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def imports_package(path: Path) -> bool:
    return any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_stakes_or_serves_imports_decision_v2() -> None:
    wrong = [rel(p) for p in files(SRC, ROOT / "apps") if rel(p).startswith(SERVING) and imports_package(p)]
    assert not wrong, f"decision-v2 is shadow-only; these modules import it: {wrong}"


def test_only_its_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps") if not rel(p).startswith("decision/") and imports_package(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_package_reaches_the_signals_and_the_families_through_one_module_each_and_never_the_stake() -> None:
    own = {rel(p): imported(p) for p in files(SRC / "decision")}
    signals = {f for f, names in own.items() if any(n.startswith("fbi.market.signals") or n == "fbi.market.signals" for n in names)}
    assert signals == {"decision/market_inputs.py"}, signals
    families = {f for f, names in own.items() if any(n.startswith("fbi.familydecisions") for n in names)}
    assert families == {"decision/families.py"}, families
    assert not [f for f, names in own.items() if any(n.startswith("fbi.intel.stake") or n == "fbi.intel.stake" for n in names)]
    assert not [f for f, names in own.items() if any(n.split(".")[1:2] and n.split(".")[1] in ("api", "notify", "messaging", "parlays", "customer")
                                                      for n in names if n.startswith("fbi."))]


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.decision", "import fbi.decision.engine", "from fbi.decision import engine",
                 "from fbi.decision.replay import replay_day", "def f():\n    from fbi.decision import families\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_package(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.intel import decision", encoding="utf-8")
    assert not imports_package(probe)

"""The market's signals (``fbi.market.signals``, ``market-signals-v1``) are in SHADOW: computed and reported, never read by a decision, a
pick, a stake or anything a user can open. This test holds the door shut by scanning the imports (lazy ones too): nothing under
``fbi.intel.decision``, ``fbi.picks``, ``fbi.familydecisions`` or ``fbi.api`` imports the module, and the only code that imports it at
all is its own command. A new reader fails here until someone decides it may read."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"

MODULE = "fbi.market.signals"
FORBIDDEN = ("intel/decision.py", "picks/", "familydecisions/", "api/")
ALLOWED = {"scripts/ia_market_signals.py": "the command that prints the signals (read-only)",
           "decision/market_inputs.py": "decision-v2 in shadow (IA-012): the signals as risk inputs of an engine nothing that decides "
                                        "imports (tests/unit/test_decision_v2_isolation.py)",
           "council/contradictions.py": "the Council v2 protocol (IA-012, shadow) reads the market against the agents' stances",
           "council/protocol.py": "the Council v2 protocol (IA-012, shadow) reads each candidate's signals: reporting only"}


def imports_signals(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any(a.name == MODULE or a.name.startswith(MODULE + ".") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == MODULE or node.module.startswith(MODULE + "."):
                return True
            if node.module == "fbi.market" and any(a.name == "signals" for a in node.names):
                return True
        if (isinstance(node, ast.ImportFrom) and node.level and path.parent == SRC / "market"
                and (node.module == "signals" or (node.module is None and any(a.name == "signals" for a in node.names)))):
            return True
    return False


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_imports_the_signals() -> None:
    wrong = [rel(p) for p in files(SRC) if rel(p).startswith(FORBIDDEN) and imports_signals(p)]
    assert not wrong, f"the market signals are shadow-only; these decision/pick/API modules import them: {wrong}"


def test_only_the_signals_own_command_imports_them() -> None:
    importing = {rel(p) for p in files(SRC, SCRIPTS, APPS) if p != SRC / "market" / "signals.py" and imports_signals(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.market.signals", "from fbi.market.signals import market_signals", "from fbi.market import signals",
                 "def f():\n    from fbi.market import consensus, signals\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_signals(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.market import consensus", encoding="utf-8")
    assert not imports_signals(probe)

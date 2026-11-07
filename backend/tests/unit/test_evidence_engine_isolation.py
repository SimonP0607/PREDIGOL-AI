"""The Evidence Engine (``fbi.evidence``, ``evidence-engine-v1``, IA-012) is in SHADOW: computed and reported, never read by anything that
decides, publishes or serves a user. This test holds the door shut by scanning the imports (lazy ones too): nothing outside the package imports
it but its own command, and in particular nothing under the decision layer, the picks, the family decisions, the API, the notifications, the
narrative, the customer layer or the AI's own cycle and agents. A new reader fails here until someone decides it may read."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"

PACKAGE = "fbi.evidence"
FORBIDDEN = ("intel/", "picks/", "familydecisions/", "api/", "notify/", "narrative/", "customer/", "messaging/", "ai/", "parlays/",
             "predictions/", "forecasting/")
ALLOWED = {"scripts/ia_evidence.py": "the command that prints the evidence of a match or a day (read-only)"}


def imports_engine(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any(a.name == PACKAGE or a.name.startswith(PACKAGE + ".") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module == PACKAGE or node.module.startswith(PACKAGE + "."):
                return True
            if node.module == "fbi" and any(a.name == "evidence" for a in node.names):
                return True
    return False


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_or_serves_imports_the_engine() -> None:
    wrong = [rel(p) for p in files(SRC) if rel(p).startswith(FORBIDDEN) and imports_engine(p)]
    assert not wrong, f"the evidence engine is shadow-only; these modules import it: {wrong}"


def test_only_the_engine_s_own_command_imports_it() -> None:
    inside = SRC / "evidence"
    importing = {rel(p) for p in files(SRC, SCRIPTS, APPS) if inside not in p.parents and imports_engine(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_engine_writes_nothing() -> None:
    for path in files(SRC / "evidence"):
        text = path.read_text(encoding="utf-8").upper()
        for verb in ("INSERT INTO", "UPDATE AI.", "UPDATE CORE.", "DELETE FROM", ".COMMIT("):
            assert verb not in text, f"{rel(path)}: {verb}"


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.evidence", "import fbi.evidence.engine", "from fbi.evidence.engine import evidence_for", "from fbi.evidence import rules",
                 "from fbi import evidence", "def f():\n    from fbi.evidence import engine\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_engine(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.ai.evidence import store\nfrom fbi.ai import evidence", encoding="utf-8")
    assert not imports_engine(probe), "v1's evidence module is another module"

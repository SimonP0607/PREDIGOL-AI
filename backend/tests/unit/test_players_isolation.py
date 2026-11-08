"""The player engine (``fbi.players``, ``player-engine-v1``, IA-017) is in SHADOW: it computes and reports, and nothing that decides,
publishes, stakes or serves users may import it. The scan reads every import (lazy ones too) of ``src/fbi``, ``apps`` and ``scripts``:
outside the package itself, the only importer is its own read-only command. The package's own imports are held too: it reads no model
package, no decision, no stake, no AI layer and nothing that serves users, and it lives outside the model packages, so the model code
fingerprint does not move (``tests/unit/test_model_code_version.py``)."""

from __future__ import annotations

import ast
from pathlib import Path

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint
from tests.unit.test_model_code_version import RUNNING_MODEL_CODE

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.players"
ALLOWED = {"scripts/ia_players.py": "the command that prints the evaluation and a match's forecast (read-only)"}
SERVING = ("intel/", "picks/", "familydecisions/", "decision/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/",
           "knowledge/", "ai/", "council/", "forecasting/", "apps/")
"""What decides (``intel``, ``picks``, ``familydecisions``, ``decision``, ``council``, ``ai``), stakes and combines (``parlays``),
publishes or serves users."""
MAY_IMPORT = ("fbi.players", "fbi.families.counts", "fbi.core")
"""The package's own reach: itself, the NB2 count engine it reuses, and the platform's core."""


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def targets(path: Path) -> set[str]:
    """What a file reaches: each ``import x`` and each name of a ``from x import y`` as ``x.y`` (a relative import is flagged)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add("<relative>")
    return found


def imports_package(path: Path) -> bool:
    return any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_stakes_or_serves_imports_the_player_engine() -> None:
    wrong = [rel(p) for p in files(SRC, ROOT / "apps") if rel(p).startswith(SERVING) and imports_package(p)]
    assert not wrong, f"the player engine is shadow-only; these modules import it: {wrong}"


def test_only_its_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps") if not rel(p).startswith("players/") and imports_package(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_package_reaches_only_itself_the_count_engine_and_the_core() -> None:
    reach = {f: sorted(n for n in names if n == "<relative>" or (n.startswith("fbi.") and not n.startswith(MAY_IMPORT)))
             for f, names in ((rel(p), targets(p)) for p in files(SRC / "players"))}
    wrong = {f: names for f, names in reach.items() if names}
    assert not wrong, f"the player engine reaches outside its lane: {wrong}"


def test_the_engine_is_not_model_code_and_the_fingerprint_has_not_moved() -> None:
    assert "players" not in MODEL_PACKAGES
    assert not any((SRC / "players").is_relative_to(SRC / package) for package in MODEL_PACKAGES)
    assert model_code_fingerprint() == RUNNING_MODEL_CODE


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.players", "import fbi.players.props", "from fbi.players import rates",
                 "from fbi.players.backtest import Engine", "def f():\n    from fbi.players import availability\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_package(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.people import player_history", encoding="utf-8")
    assert not imports_package(probe)

"""The joint match simulator (``fbi.simulator``, ``sim-v1``) is in SHADOW: computed and reported, never read by anything that decides,
picks, publishes a forecast or serves the API. This test holds the door shut by scanning the imports (lazy ones too): nothing outside
the package imports it but its own command; the package asks no model client and writes nothing; and it is not model code - it lives
outside the packages whose fingerprint keys every model version, and that fingerprint is still the running one."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint
from tests.unit.test_model_code_version import RUNNING_MODEL_CODE

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "simulator"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"

MODULE = "fbi.simulator"
ALLOWED = {"scripts/ia_simulator.py": "the command that prints the check against the models in force (read-only)"}
DECIDES = ("intel/", "picks/", "familydecisions/", "decision/", "api/", "parlays/", "predictions/", "forecasting/", "families/",
           "ai/", "narrative/", "messaging/", "notify/", "customer/", "models/", "features/", "backtesting/", "domain/")
"""What decides a state, a pick or a stake, what writes a forecast, what serves or tells a user, and the model code itself."""

NO_MODEL = ("fbi.ai", "anthropic", "httpx", "requests", "fbi.picks", "fbi.intel", "fbi.decision", "fbi.forecasting", "fbi.predictions",
            "fbi.backtesting")
"""What the package may not import: a language model's client or anything of the AI layer (``fbi.ai.calendar`` apart, for the day), the
layers that decide, and the forecast writers. It reads the fitted models' code (``fbi.models``) as a library and the stored rows."""


def imported(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def imports_simulator(path: Path) -> bool:
    return any(name == MODULE or name.startswith(MODULE + ".") for name in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_or_serves_imports_the_simulator() -> None:
    wrong = [rel(p) for p in files(SRC) if rel(p).startswith(DECIDES) and imports_simulator(p)]
    assert not wrong, f"the simulator is shadow-only; these modules import it: {wrong}"


def test_only_the_simulators_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, SCRIPTS, APPS) if PACKAGE not in p.parents and imports_simulator(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_simulator_asks_no_model_and_writes_nothing() -> None:
    for path in [*files(PACKAGE), SCRIPTS / "ia_simulator.py"]:
        names = imported(path)
        bad = sorted(n for n in names if n.startswith(NO_MODEL) and not n.startswith("fbi.ai.calendar"))
        assert not bad, f"{rel(path)} imports {bad}"
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE)\b", source, flags=re.IGNORECASE), rel(path)
        assert ".commit(" not in source, rel(path)
    assert "default_transaction_read_only=on" in (SCRIPTS / "ia_simulator.py").read_text(encoding="utf-8")


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.simulator", "from fbi.simulator import markets", "from fbi.simulator.joint import build", "from fbi import simulator",
                 "def f():\n    from fbi.simulator import consistency\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_simulator(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi import models", encoding="utf-8")
    assert not imports_simulator(probe)


def test_the_simulator_is_not_model_code_and_leaves_the_fingerprint_untouched() -> None:
    """A file in a model package renews the version of every model (``tests/unit/test_model_code_version.py``). The simulator is outside
    them, no model package holds a file of it, and the fingerprint is still the one every running version is keyed by."""
    assert "simulator" not in MODEL_PACKAGES
    assert not any(PACKAGE.is_relative_to(SRC / package) for package in MODEL_PACKAGES)
    for package in MODEL_PACKAGES:
        assert not list((SRC / package).rglob("*simulat*")), package
    assert model_code_fingerprint() == RUNNING_MODEL_CODE

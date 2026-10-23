"""What PrediGol says about a match's context is not an input of what it predicts (plan F6, pre-match v3).

The weighted head-to-head, the scenarios of a table or a tie, the factors registry and the tactical profile are DESCRIPTIONS: the AI packet
carries them so the brief can reason about them, the match page shows them to the owner, and ``intel.context_factors`` says which of them
(if any) an experiment has shown to add something. Until one is promoted by a person with the evidence in the registry, no model, pick,
forecast or settlement reads them - and the fingerprint of the model code (``fbi.core.version``) does not move when they change, which is
only true because they live outside the packages it covers. Each module is listed with the files that import it, and why; a new importer
fails the test until someone decides it may."""

from __future__ import annotations

import ast
from pathlib import Path

from fbi.core.version import MODEL_PACKAGES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
SCRIPTS = ROOT / "scripts"

CONTEXT_MODULES: dict[str, dict[str, str]] = {
    "fbi.intel.h2h": {
        "ai/packet.py": "the packet: the head-to-head of the match, weighed, as of its moment",
        "intel/dossier.py": "the dossier: how much the head-to-head is worth (its words, read by the narrative)",
        "intel/factors.py": "the registry: the key and the version of the head-to-head, which a validation is about",
        "intel/leakage.py": "the nightly proof: the rule h2h_known (it reads the constant N and nothing else)",
        "api/services/center.py": "the match page: the same head-to-head, asked for now",
    },
    "fbi.intel.scenarios": {
        "ai/packet.py": "the packet: what the match alone does to its table and to its tie, as of its moment",
        "intel/factors.py": "the registry: the key and the version of the scenarios, which a validation is about",
    },
    "fbi.intel.tactics": {
        "intel/dossier.py": "the dossier: the observable tactics of each side, as of the packet's moment (and which sheets are crossed)",
        "intel/factors.py": "the registry: the key and the version of the tactics, which a validation is about",
        "intel/leakage.py": "the nightly proof: the rule tactics_known (it reads the constants N and WINDOW and nothing else)",
    },
    "fbi.intel.factors": {
        "ai/brief.py": "the brief: which block of the packet carries which factor, so that a reason for a selection that rests on a "
                       "DESCRIPTIVE one is refused (it reads the catalogue and the words DESCRIPTIVE and VALIDATED)",
        "ai/packet.py": "the packet: the status of each context factor as of its moment, and the status each block says",
        "intel/leakage.py": "the nightly proof: the rule factors_known (it reads the catalogue's keys and blocks and nothing else)",
        "api/services/intelligence.py": "the console's page of the registry: the catalogue, the standing of each factor and the decisions "
                                        "behind it, read and shown to the owner (it writes nothing: only the person's door below does)",
        "scripts/context_factors.py": "the person's door: list, history, promote and retire a factor",
    },
}
"""Module -> the files that may import it (a path under ``src/fbi``, or ``scripts/<name>``), each with its reason."""

DECIDING = set(MODEL_PACKAGES) | {"picks", "parlays", "market", "odds", "datasets", "forecasting", "settlement"}
"""The packages that train a model, predict, price, decide or settle."""


def python_files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else f"scripts/{path.name}"


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_the_modules_live_outside_the_model_packages() -> None:
    """A change to them must not renew the version of every model (``fbi.core.version``)."""
    for module in CONTEXT_MODULES:
        top = module.split(".")[1]
        assert top not in MODEL_PACKAGES, f"{module} would change the fingerprint of the model code"
        assert (SRC / Path(*module.split(".")[1:])).with_suffix(".py").exists(), f"{module} is listed and does not exist"


def test_only_the_listed_files_import_each_module() -> None:
    for module, allowed in CONTEXT_MODULES.items():
        own = (Path(*module.split(".")[1:])).with_suffix(".py").as_posix()
        importing = {
            rel(p) for p in python_files(SRC, SCRIPTS)
            if rel(p) != own and any(name == module or name.startswith(module + ".") for name in imports_of(p))
        }
        assert importing == set(allowed), (
            f"{module}: imported by files that are not listed: {sorted(importing - set(allowed))}; "
            f"listed files that no longer import it: {sorted(set(allowed) - importing)}")


def test_nothing_that_trains_predicts_prices_decides_or_settles_imports_them() -> None:
    deciding = [p for p in python_files(SRC) if rel(p).split("/")[0] in DECIDING]
    assert deciding, "the packages that decide are where the test looks"
    for path in deciding:
        names = imports_of(path)
        for module in CONTEXT_MODULES:
            assert not any(n == module or n.startswith(module + ".") for n in names), (
                f"{rel(path)} takes {module} as an input: it is context, not a model feature")

"""The Council v2's deterministic protocol (``fbi.council``, ``council-protocol-v1``) is in SHADOW: computed and reported, never read by
anything that decides, publishes, stakes or serves a user. This test holds the door shut by scanning the imports (lazy ones too): nothing
outside the package imports it but its own command, and the package itself imports no model client, no orchestrator and no writer.
A new reader fails here until someone decides it may read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "council"
SCRIPTS = ROOT / "scripts"
APPS = ROOT / "apps"

MODULE = "fbi.council"
ALLOWED = {"scripts/ia_council_v2.py": "the command that prints the deliberation (read-only)"}
DECIDES = ("intel/decision.py", "intel/state_v2.py", "intel/stake.py", "picks/", "familydecisions/", "api/", "parlays/", "ai/orchestrator.py",
           "ai/orchestrator_store.py", "ai/agents/", "ai/router.py", "narrative/", "messaging/", "notify/", "customer/", "predictions/")
"""What decides a state, a pick or a stake, what serves or tells a user, and what runs the agents: none of it may import the protocol."""

NO_MODEL = ("fbi.ai.providers", "fbi.ai.usage", "fbi.ai.runtime", "fbi.ai.orchestrator", "fbi.ai.orchestrator_store", "fbi.ai.batch",
            "fbi.ai.research", "fbi.ai.entity_research", "fbi.ai.prompts", "fbi.ai.agents.council", "fbi.ai.agents.match", "fbi.ai.agents.stats",
            "anthropic", "httpx", "requests")
"""What the package may not import directly: a model's client or its ledger, the orchestrator, the searches, the prompts and the agents
themselves. It reads what they stored; it never asks them anything."""


def imported(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def imports_council(path: Path) -> bool:
    return any(name == MODULE or name.startswith(MODULE + ".") for name in imported(path))


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_or_serves_imports_the_protocol() -> None:
    wrong = [rel(p) for p in files(SRC) if rel(p).startswith(DECIDES) and imports_council(p)]
    assert not wrong, f"the Council v2 protocol is shadow-only; these modules import it: {wrong}"


def test_only_the_protocols_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, SCRIPTS, APPS) if PACKAGE not in p.parents and imports_council(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_protocol_asks_no_model_and_writes_nothing() -> None:
    for path in files(PACKAGE):
        names = imported(path)
        bad = sorted(n for n in names if n.startswith(NO_MODEL))
        assert not bad, f"{rel(path)} imports {bad}"
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE)\b", source, flags=re.IGNORECASE), rel(path)
        assert ".commit(" not in source and "call_json" not in source, rel(path)


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.council", "from fbi.council import protocol", "from fbi.council.weights import weight_of", "from fbi import council",
                 "def f():\n    from fbi.council import contradictions\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_council(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi import intel", encoding="utf-8")
    assert not imports_council(probe)

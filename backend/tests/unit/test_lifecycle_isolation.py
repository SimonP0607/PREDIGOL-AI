"""IA-068 (AD-D02): the cycle of states lives beside the layers it reads and changes none of them.

* every statement of ``fbi.lifecycle`` that writes, writes ``intel.selection_lifecycle`` - an INSERT, never an UPDATE or a DELETE;
* the package does not import decision-v2 (``fbi.decision``) nor anything that decides, stakes, publishes or serves a reader;
* outside the package only the worker's job and its own command import it: no decision layer, pick, parlay or public page reads it;
* the worker schedules it only while ``FBI_SELECTION_LIFECYCLE`` says ``shadow``, with a deadline the watchdog knows.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apps.worker import scheduler

from fbi.lifecycle import store
from fbi.ops.run_watchdog import timeout_for

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "lifecycle"
WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE)\s+([a-z_]+\.[a-z_]+)?",
                   re.IGNORECASE)


def _strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


def test_the_package_writes_its_own_table_and_nothing_else() -> None:
    writes = [(p.name, m.group(1).upper().split()[0], (m.group(2) or "").lower())
              for p in PACKAGE.glob("*.py") for s in _strings(p) for m in WRITE.finditer(s)]
    assert writes == [("store.py", "INSERT", "intel.selection_lifecycle")], writes


def test_the_package_reaches_neither_decision_v2_nor_what_serves_a_reader() -> None:
    forbidden = ("fbi.decision", "fbi.picks", "fbi.parlays", "fbi.api", "fbi.notify", "fbi.messaging", "fbi.customer",
                 "fbi.narrative", "fbi.familydecisions", "fbi.intel.stake")
    found = {p.name: sorted(n for n in _imports(p) if n.startswith(forbidden) and not n.startswith("fbi.decision_"))
             for p in PACKAGE.glob("*.py")}
    assert all(not v for v in found.values()), found


def test_only_its_job_and_its_command_import_it() -> None:
    importers = set()
    for root in (SRC, ROOT / "apps", ROOT / "scripts"):
        for p in root.rglob("*.py"):
            if PACKAGE in p.parents or "__pycache__" in p.parts:
                continue
            if any(n == "fbi.lifecycle" or n.startswith("fbi.lifecycle.") for n in _imports(p)):
                importers.add(p.relative_to(ROOT).as_posix())
    # decision-v2's kept shadow (IA-093) hands its own decisions to the cycle through ``store.extend``: the cycle's API, not its table.
    # IA-096 (AD-E03): the private evaluation of corners and cards appends the chains of the selections it admits with the cycle's own
    # derivation and statement, under its own writer (count-eval-v1); it is itself imported only by its command
    # (tests/unit/test_count_private_evaluation.py)
    # IA-105 (AD-D06): the evaluation cycle builds the chains of its own verdicts with the cycle's machine and derivation (``chain.py``,
    # and ``reevaluate.py`` for the closed reasons) and appends them through ``store.extend_rows`` (``run.py``), under its own writer
    # (eval-cycle-v1); only fbi.shadowjobs.eval_cycle imports it (tests/unit/test_eval_cycle_isolation.py)
    # IA-109 (AD-E05): the tracking of loose selections takes the chains of decision-v2's shadow past kick-off on settle-v4 through the
    # cycle's API (``store.append``, ``derive.after_kickoff``); it is itself imported only by its worker door and its command
    # (tests/unit/test_tracking_ia109.py)
    # IA-112..IA-115 (AD-K01, AD-J03, AD-J04): the evaluation after the match reads the cycle's map of a decision and its family (pure
    # functions); the owner's C-02 and C-03 read the cycle through its reader (``reader.tracking``) and its machine (``public_state``):
    # read only: from its writer they import only the name of the writer (``WRITER``), never a pass
    # IA-131 (AD-J02 delivery 2): C-01 2.0.0 reads each selection's newest state of that writer's chains, as C-02 does: only ``WRITER``
    assert importers == {"apps/worker/scheduler.py", "scripts/ia_lifecycle.py", "src/fbi/api/routers/intelligence.py",
                         "src/fbi/api/services/match_intelligence_v2.py", "src/fbi/api/services/selection_intelligence.py", "src/fbi/api/services/tracking.py",
                         "src/fbi/countcal/private.py", "src/fbi/decision/shadow.py", "src/fbi/evalcycle/chain.py",
                         "src/fbi/evalcycle/reevaluate.py", "src/fbi/evalcycle/run.py", "src/fbi/evaluation/selection.py",
                         "src/fbi/tracking/selections.py"}, importers


def test_the_worker_schedules_it_only_in_the_shadow_with_a_deadline() -> None:
    tree = ast.parse(Path(scheduler.__file__).read_text())
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    assert ("lifecycle_shadow", "lifecycle_shadow") in found
    assert timeout_for("lifecycle_shadow").total_seconds() == 15 * 60
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == "lifecycle_shadow" for n in ast.walk(body))
    assert guarded, "the job is registered only while FBI_SELECTION_LIFECYCLE is shadow"
    assert store.EVERY == 30


def test_the_job_does_nothing_while_off(monkeypatch) -> None:
    monkeypatch.delenv(store.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._lifecycle_shadow_now()

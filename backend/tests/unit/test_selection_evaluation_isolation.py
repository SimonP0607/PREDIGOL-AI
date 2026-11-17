"""AD-K01/K02 (IA-112/113): the evaluation after the match and the board are in the SHADOW. The scan reads every import of ``src/fbi``,
``apps`` and ``scripts`` and every statement of the package: only the owner's views, the worker's door and the owner's command import it,
and the only table it writes is its own."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.evaluation"
PASS = "fbi.evalpass"
"""The pass (``reads`` and ``store``), apart so that the API layer that reads the package does not join the import cycle."""
PASS_ALLOWED = {
    "shadowjobs/selection_eval.py": "the worker's door: its switch and one pass",
    "scripts/ia_selection_eval.py": "the owner's read-only command (dry run and board)",
}
ALLOWED = {
    "api/services/selection_intelligence.py": "C-02: the selection's contract reads its evaluation and its market's verdict (owner's "
                                             "projection; the public one exists only for what the owner published)",
    "api/services/tracking.py": "C-03: the owner's tracking reads the families' counters and the evaluations",
    "api/services/post_evaluation.py": "C-08: the owner's evaluation after the match reads the evaluations of one match and the board "
                                       "(private only, require_admin)",
    "scripts/ia_selection_eval.py": "the owner's read-only command (dry run and board)",
}
DECIDES = ("intel/", "picks/", "familydecisions/", "parlays/", "decision/", "council/", "models/", "features/", "predictions/",
           "forecasting/", "customer/", "notify/", "messaging/", "narrative/", "knowledge/")
WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+\.[a-z_0-9]+)", re.IGNORECASE)


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files() -> list[Path]:
    return sorted(p for r in (SRC, ROOT / "apps", ROOT / "scripts") for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_only_the_owners_views_the_worker_and_the_command_import_the_package() -> None:
    importing = {rel(p) for p in files() if not rel(p).startswith(("evaluation/", "evalpass/"))
                 and any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imports(p))}
    assert importing == set(ALLOWED), f"unlisted: {sorted(importing - set(ALLOWED))}; gone: {sorted(set(ALLOWED) - importing)}"
    assert not [f for f in importing if f.startswith(DECIDES)]
    passing = {rel(p) for p in files() if not rel(p).startswith(("evaluation/", "evalpass/"))
               and any(n == PASS or n.startswith(PASS + ".") for n in imports(p))}
    assert passing == set(PASS_ALLOWED), f"unlisted: {sorted(passing - set(PASS_ALLOWED))}; gone: {sorted(set(PASS_ALLOWED) - passing)}"


def test_the_package_writes_only_its_own_table_and_reaches_no_decision() -> None:
    for path in [*(SRC / "evaluation").glob("*.py"), *(SRC / "evalpass").glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        targets = {t.lower() for _, t in WRITE.findall(text)}
        assert targets <= {"intel.selection_evaluations"}, (path.name, targets)
        assert not (targets and path.name != "store.py"), f"{path.name} writes; only store.py may"
        names = imports(path)
        assert not [n for n in names if n.startswith(("fbi.decision", "fbi.intel.decision", "fbi.picks.engine", "fbi.parlays",
                                                      "fbi.ai.agents", "anthropic"))], (path.name, names)


def test_the_worker_schedules_it_only_in_the_shadow() -> None:
    from fbi.shadowjobs import selection_eval as job

    assert job.mode({}) == "off" and job.mode({"FBI_SELECTION_EVAL": "on"}) == "off"
    assert job.mode({"FBI_SELECTION_EVAL": " Shadow "}) == "shadow"
    assert job.every_minutes({}) == 60 and job.every_minutes({"FBI_SELECTION_EVAL_MINUTES": "5"}) == 60
    assert job.every_minutes({"FBI_SELECTION_EVAL_MINUTES": "120"}) == 120
    scheduler = (ROOT / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")
    assert 'if sev.mode() == "shadow":' in scheduler and '"selection_eval_shadow"' in scheduler
    from fbi.ops.run_watchdog import timeout_for

    assert timeout_for("selection_eval_shadow").total_seconds() == 15 * 60

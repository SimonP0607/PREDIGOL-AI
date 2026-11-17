"""The evaluation cycle (IA-105..IA-108) is a shadow beside what decides and serves, and its E3 is code:

* E3's module and the dependency table import no client of a model of language (no ``anthropic``, no agent, no research, no prompt):
  every figure and every verdict is code;
* nothing that notifies, messages or serves a customer imports the cycle or its alerts (AD-D08: never a notice to a reader), nothing that
  decides, stakes or publishes imports it, and outside its package only the worker's door does;
* the C-05 service reads the alerts' table without importing the cycle, and no public route serves C-05 (it is private only);
* the cycle's statements write only its five tables, with INSERT (decision-v2's rows go through ``shadow.decide_evaluation``, the cycle of
  states through ``store.extend_rows``);
* the worker schedules its two jobs only while ``FBI_EVAL_CYCLE`` is ``shadow``, with deadlines the watchdog knows; off by default;
* revision 0156 chains on 0154 and makes five append-only tables.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from apps.worker import scheduler

from fbi.api.contracts.intelligence.alerts import AlertsContract
from fbi.api.contracts.intelligence.registry import by_id
from fbi.ops.run_watchdog import timeout_for
from fbi.shadowjobs import eval_cycle

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = SRC / "evalcycle"
WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE)\s+([a-z_]+\.[a-z_0-9]+)?",
                   re.IGNORECASE)
TABLES = {"intel.eval_runs", "intel.eval_facts", "intel.lineup_dependencies", "intel.eval_verdicts", "intel.private_alerts"}


def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_e3_and_the_dependencies_are_code_without_a_model_of_language() -> None:
    for name in ("reevaluate.py", "dependency.py", "clock.py", "chain.py", "alerts.py", "players.py"):
        found = {n for n in imports(PACKAGE / name) if n.startswith(("anthropic", "openai", "fbi.ai", "fbi.council", "fbi.narrator",
                                                                      "fbi.news", "fbi.newsroom", "exa"))}
        assert not found, f"{name} reaches {found}"
    reached = {n for n in imports(PACKAGE / "conditions.py") if n.startswith("fbi.ai")}
    assert reached <= {"fbi.ai", "fbi.ai.final_reread"}, reached
    reached = {n for n in imports(PACKAGE / "run.py") if n.startswith("fbi.ai")}
    assert reached <= {"fbi.ai", "fbi.ai.final_reread", "fbi.ai.gates", "fbi.ai.gates.typed_visible"}, reached


def test_nothing_that_notifies_decides_or_serves_imports_the_cycle_and_only_the_worker_door_does() -> None:
    importers = set()
    for p in [*SRC.rglob("*.py"), *(ROOT / "apps").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        if PACKAGE in p.parents or "__pycache__" in p.parts:
            continue
        if any(n == "fbi.evalcycle" or n.startswith("fbi.evalcycle.") for n in imports(p)):
            importers.add(p.relative_to(ROOT).as_posix())
    assert importers == {"src/fbi/shadowjobs/eval_cycle.py"}, importers
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith(("notify/", "messaging/", "customer/", "api/", "picks/", "parlays/", "intel/")):
            assert not any(n.startswith("fbi.evalcycle") or n.startswith("fbi.shadowjobs.eval_cycle") for n in imports(p)), rel


def test_c05_is_private_only_and_its_service_does_not_import_the_cycle() -> None:
    spec = by_id()["C-05"]
    assert spec.private is AlertsContract and spec.public is None and AlertsContract.PRIVATE_ONLY
    assert spec.private_routes == ("/api/v1/admin/intelligence/alerts",) and not spec.public_routes
    service = SRC / "api" / "services" / "intelligence_alerts.py"
    assert not {n for n in imports(service) if n.startswith(("fbi.evalcycle", "fbi.shadowjobs", "fbi.notify", "fbi.messaging"))}
    for p in (SRC / "api").rglob("*.py"):
        if "AlertsContract" in p.read_text(encoding="utf-8"):
            assert p.relative_to(SRC).as_posix() in {"api/contracts/intelligence/alerts.py", "api/contracts/intelligence/registry.py",
                                                    "api/services/intelligence_alerts.py", "api/routers/intelligence.py"}, p
    router = (SRC / "api" / "routers" / "intelligence.py").read_text(encoding="utf-8")
    assert '"/intelligence/alerts"' in router, "mounted only on the admin router (require_admin)"


def test_the_cycle_writes_only_its_tables_with_insert() -> None:
    writes = {(p.name, m.group(1).upper().split()[0], (m.group(2) or "").lower())
              for p in PACKAGE.glob("*.py") for s in strings(p) for m in WRITE.finditer(s)}
    assert {w[1] for w in writes} == {"INSERT"} and {w[0] for w in writes} == {"run.py"}, writes
    assert {w[2] for w in writes} == TABLES, writes


def test_the_worker_schedules_it_only_in_the_shadow_with_its_deadlines() -> None:
    assert eval_cycle.mode({}) == "off" and eval_cycle.mode({"FBI_EVAL_CYCLE": "on"}) == "off"
    assert eval_cycle.mode({"FBI_EVAL_CYCLE": " Shadow "}) == "shadow"
    assert eval_cycle.every_minutes({}) == 5 and eval_cycle.every_minutes({"FBI_EVAL_CYCLE_MINUTES": "30"}) == 5
    assert eval_cycle.e3_every_seconds({}) == 60 and eval_cycle.e3_every_seconds({"FBI_EVAL_CYCLE_E3_SECONDS": "10"}) == 60
    assert timeout_for("eval_cycle_shadow") == timedelta(minutes=20) and timeout_for("eval_cycle_e3") == timedelta(minutes=3)
    assert {"eval_cycle_shadow", "eval_cycle_e3"} <= scheduler.WORKER_JOB_TYPES
    tree = ast.parse(Path(scheduler.__file__).read_text())
    found = {(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)}
    assert {("eval_cycle_shadow", "eval_cycle_shadow"), ("eval_cycle_e3", "eval_cycle_e3")} <= found
    text = Path(scheduler.__file__).read_text()
    assert 'if ec.mode() == "shadow":' in text and 'if ec.mode() != "shadow":' in text


def migration() -> Any:
    path = ROOT / "migrations" / "versions" / "0156_eval_cycle.py"
    spec = importlib.util.spec_from_file_location("migration_0156", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0156_chains_on_0154_and_its_words_are_the_codes() -> None:
    from fbi.evalcycle import alerts, dependency, reevaluate
    from fbi.lifecycle import machine

    m = migration()
    assert (m.revision, m.down_revision) == ("0156", "0155")
    assert set(m.TABLES) == {t.split(".")[1] for t in TABLES}
    assert m.GROUPS == dependency.GROUPS and m.DEPENDENCY_STATUSES == dependency.STATUSES
    assert m.VERDICTS == reevaluate.VERDICTS and m.STATES == machine.STATES and m.ALERT_KINDS == alerts.KINDS
    assert m.EVALUATIONS == machine.EVALUATIONS
    text = (ROOT / "migrations" / "versions" / "0156_eval_cycle.py").read_text()
    up = text.split("def upgrade")[1].split("def downgrade")[0]
    assert not re.search(r"\b(INSERT\s+INTO|DELETE\s+FROM)\b|(?<!BEFORE )\bUPDATE\s+intel", up), "the migration writes no row"

"""The worker's ``chronicle_review`` job (IA-023): known to the watchdog, bounded, switchable off, and quiet when nothing is due.

``main()`` cannot be run in a unit test, so the registration is read from the source of ``apps.worker.scheduler`` (as for the other jobs)."""

from __future__ import annotations

import ast
from pathlib import Path

from apps.worker import scheduler

from fbi.chronicle import job as chronicle_review
from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

TREE = ast.parse(Path(scheduler.__file__).read_text())


def test_the_job_is_wrapped_with_a_deadline_and_the_watchdog_knows_it() -> None:
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(TREE)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    assert ("chronicle_review", "chronicle_review") in found
    assert chronicle_review.JOB == "chronicle_review"
    assert "chronicle_review" in scheduler.WORKER_JOB_TYPES, "a run left open by a restarted worker would never be closed"
    assert "chronicle_review" in JOB_TIMEOUTS
    assert timeout_for("chronicle_review").total_seconds() == 20 * 60


def test_it_is_registered_only_while_the_switch_is_on_and_runs_hourly_by_default() -> None:
    assert scheduler.CHRONICLE_REVIEW_MINUTES == 60
    guarded = False
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "CHRONICLE_REVIEW_ENABLED":
            guarded = any(isinstance(n, ast.Constant) and n.value == "chronicle_review" for n in ast.walk(ast.Module(body=node.body, type_ignores=[])))
    assert guarded, "FBI_CHRONICLE_REVIEW=0 must switch the registration off"

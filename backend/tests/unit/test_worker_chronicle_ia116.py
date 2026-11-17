"""The worker's jobs of IA-116 and IA-118 (``chronicle_update``, ``chronicle_review_v2``): wrapped with a deadline, known to the watchdog,
registered only while their switch is ``shadow`` (off by default); and the console shows the three new switches with their defaults.

``main()`` cannot be run in a unit test, so the registration is read from the source of ``apps.worker.scheduler``."""

from __future__ import annotations

import ast
from pathlib import Path

from apps.worker import scheduler

from fbi.ai.config import AiSettings
from fbi.api.services import intelligence_console as console
from fbi.chronicle import job, repetition, review_v2, update_job
from fbi.intel import capabilities
from fbi.ops.run_watchdog import JOB_TIMEOUTS

TREE = ast.parse(Path(scheduler.__file__).read_text())
JOBS = {"chronicle_update": update_job.JOB, "chronicle_review_v2": review_v2.JOB}


def test_each_job_is_wrapped_with_a_deadline_and_the_watchdog_knows_it() -> None:
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(TREE)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    for name, ledger_name in JOBS.items():
        assert name == ledger_name and (name, name) in found
        assert name in scheduler.WORKER_JOB_TYPES and name in JOB_TIMEOUTS
    assert job.JOB_V2 == review_v2.JOB


def test_each_job_is_registered_only_while_its_switch_is_shadow() -> None:
    guarded: dict[str, bool] = {}
    for node in ast.walk(TREE):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call)
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode"
                and isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value == "shadow"):
            body = ast.Module(body=node.body, type_ignores=[])
            for name in JOBS:
                if any(isinstance(n, ast.Constant) and n.value == name for n in ast.walk(body)):
                    guarded[name] = True
    assert guarded == dict.fromkeys(JOBS, True)


def test_the_switches_are_off_or_shadow_by_default_and_shown_in_the_console() -> None:
    assert update_job.mode({}) == "off" and review_v2.mode({}) == "off" and repetition.mode({}) == "shadow"
    specs = {s.switch: s.default for s in console.SPECS}
    assert specs["FBI_CHRONICLE_LINEUP"] == "off" and specs["FBI_CHRONICLE_REVIEW_V2"] == "off" and specs["FBI_CHRONICLE_REPEAT"] == "shadow"
    words = console.switch_words(AiSettings.from_env(), {})
    assert words["FBI_CHRONICLE_REPEAT"] == "shadow" and console.switch_words(AiSettings.from_env(),
                                                                             {"FBI_CHRONICLE_REPEAT": "ON"})["FBI_CHRONICLE_REPEAT"] == "on"
    keys = {c.key: c for c in capabilities.CATALOG}
    assert keys["chronicle_update"].switch == update_job.SWITCH and keys["chronicle_factcheck"].switch == review_v2.SWITCH
    assert keys["chronicle_repetition"].switch == repetition.SWITCH and keys["chronicle_retirement"].switch is None

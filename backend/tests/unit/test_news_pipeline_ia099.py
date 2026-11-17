"""IA-099..102: the switches of the news pipeline are born off, the worker schedules it only in shadow, with a deadline, and never raises;
the moderation package imports nothing of ``fbi.ai`` or ``fbi.news`` (the API reaches it without a loop in the import graph)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.news import pipeline, writer
from fbi.ops.run_watchdog import timeout_for

AT = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"


def test_both_switches_are_born_off_and_only_the_word_shadow_turns_them_on() -> None:
    for module in (pipeline, writer):
        assert module.mode({}) == "off"
        assert module.mode({module.SWITCH: "on"}) == "off" and module.mode({module.SWITCH: "1"}) == "off"
        assert module.mode({module.SWITCH: " Shadow "}) == "shadow"


def test_off_reads_nothing() -> None:
    class NoConn:
        def cursor(self, *a: object, **k: object) -> None:
            raise AssertionError("no query while off")

    r = pipeline.run_pass(NoConn(), at=AT, env={})  # type: ignore[arg-type]
    assert r.skipped == "off" and r.new_items == 0


def test_the_worker_schedules_it_only_in_shadow_with_a_deadline_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker import scheduler

    tree = ast.parse(Path(scheduler.__file__).read_text())
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    assert ("news_stories", "news_stories") in found
    assert timeout_for("news_stories") == timedelta(minutes=25)
    assert "news_stories" in scheduler.WORKER_JOB_TYPES
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode" \
                and isinstance(node.test.left.func.value, ast.Name) and node.test.left.func.value.id == "news_pipeline":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == "news_stories" for n in ast.walk(body))
    assert guarded, "the job is registered only while FBI_NEWS_STORIES is shadow"
    monkeypatch.delenv(pipeline.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._news_stories_now()
    monkeypatch.setenv(pipeline.SWITCH, "shadow")
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    scheduler._news_stories_now()  # logged, never raised


def test_the_newsroom_imports_nothing_of_the_ai_or_the_news_pipeline() -> None:
    for f in (SRC / "newsroom").glob("*.py"):
        tree = ast.parse(f.read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not {m for m in mods if m.startswith("fbi.")}, f


def test_the_lab_cap_is_two_dollars_and_declared_as_a_capability() -> None:
    from fbi.ai import capability_budget

    cap = capability_budget.get("news_text_shadow")
    assert cap is not None and cap.envelope == "lab" and cap.monthly_usd == writer.PIECE_MONTHLY_USD == Decimal("2.00")
    assert capability_budget.capability_of("lab", writer.PROMPT_VERSION, "other") == "news_text_shadow"

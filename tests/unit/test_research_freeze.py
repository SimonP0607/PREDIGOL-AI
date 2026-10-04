"""While the data truth audit runs, research trains and stores nothing: the freeze switch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fbi.research import loop


def test_no_switch_no_freeze(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FBI_RESEARCH_FROZEN", raising=False)
    monkeypatch.setattr(loop, "FREEZE_FILE", tmp_path / "research.frozen")
    assert loop.frozen() is None


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_a_false_environment_value_does_not_freeze(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                   value: str) -> None:
    monkeypatch.setenv("FBI_RESEARCH_FROZEN", value)
    monkeypatch.setattr(loop, "FREEZE_FILE", tmp_path / "research.frozen")
    assert loop.frozen() is None


def test_the_file_freezes_and_says_why(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FBI_RESEARCH_FROZEN", raising=False)
    flag = tmp_path / "research.frozen"
    flag.write_text("data truth audit V2 in progress\n")
    monkeypatch.setattr(loop, "FREEZE_FILE", flag)
    assert loop.frozen() == "data truth audit V2 in progress"
    flag.write_text("")
    assert loop.frozen() == str(flag)


def test_the_environment_freezes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FBI_RESEARCH_FROZEN", "audit")
    monkeypatch.setattr(loop, "FREEZE_FILE", tmp_path / "absent")
    assert loop.frozen() == "FBI_RESEARCH_FROZEN=audit"


def test_the_weekly_job_does_not_even_open_the_database_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker import scheduler

    opened: list[int] = []

    def refuse() -> None:
        opened.append(1)
        raise RuntimeError("must not connect")

    monkeypatch.setenv("FBI_RESEARCH_FROZEN", "audit")
    monkeypatch.setattr(scheduler, "_connect", refuse)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: opened.append(2))
    scheduler._research_weekly_now()
    assert opened == []


def test_the_research_script_refuses_to_store_when_frozen(monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import research_v2

    monkeypatch.setenv("FBI_RESEARCH_FROZEN", "audit")
    monkeypatch.setattr(research_v2, "dirty", lambda: False)
    monkeypatch.setattr("sys.argv", ["research_v2", "--apply"])
    assert research_v2.main() == 3
    assert "research is frozen" in capsys.readouterr().err

"""Where the research writes (RP-1.5): the weekly research died on ``PermissionError: /app/data/reports`` from 9 Oct 2026 and left no trace."""

from __future__ import annotations

from pathlib import Path

import pytest

from fbi.research import dirs


def test_the_default_is_used_when_it_can_be_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(dirs.ENV, raising=False)
    assert dirs.writable("reports", tmp_path / "data" / "reports") == tmp_path / "data" / "reports"


def test_the_owner_can_name_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dirs.ENV, str(tmp_path / "mine"))
    assert dirs.writable("experiments", Path("/app/data/experiments")) == tmp_path / "mine" / "experiments"


def test_an_unwritable_default_falls_back_to_the_raw_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The production case: ``/app/data`` belongs to root and the worker is not root; the raw volume is writable."""
    from fbi.core.config import settings

    monkeypatch.delenv(dirs.ENV, raising=False)
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(settings.runtime, "raw_store_dir", str(raw))
    blocked = Path("/app/data/reports")
    monkeypatch.setattr(dirs, "_can_write", lambda p: not str(p).startswith("/app/data"))
    assert dirs.writable("reports", blocked) == raw / dirs.SUBFOLDER / "reports"


def test_with_nothing_writable_the_temporary_folder_lets_the_run_finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.core.config import settings

    monkeypatch.delenv(dirs.ENV, raising=False)
    monkeypatch.setattr(settings.runtime, "raw_store_dir", str(tmp_path / "raw"))
    monkeypatch.setattr(dirs, "_can_write", lambda p: False)
    got = dirs.writable("reports", Path("/app/data/reports"))
    assert got.parts[-2:] == ("fbi-research", "reports")


def test_can_write_looks_at_the_nearest_existing_folder_and_creates_nothing(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    assert dirs._can_write(target) is True
    assert not (tmp_path / "a").exists()


def test_the_research_scripts_no_longer_name_a_fixed_folder() -> None:
    root = Path(dirs.__file__).resolve().parents[3]
    for rel in ("scripts/research_v2.py", "scripts/run_backtest.py", "src/fbi/research/experiments.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "writable(" in text, rel

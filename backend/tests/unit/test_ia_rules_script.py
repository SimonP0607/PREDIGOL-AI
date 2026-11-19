"""IA-072: ``scripts/ia_rules.py`` - ``check`` and ``show`` need no database; ``load --dry-run`` plans without writing."""

from __future__ import annotations

import json

import pytest
from scripts import ia_rules


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, object]]:
    code = ia_rules.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_check_validates_the_repository_files(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "check")
    assert code == 0 and out["valid"] is True and out["leagues"] == 83


def test_show_answers_coded_with_the_rules_or_not_coded_with_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "show", "--league", "239", "--season", "2026")
    assert code == 0 and out["status"] == "coded" and out["rules"]["league_id"] == 239  # type: ignore[index]
    code, out = _run(capsys, "show", "--league", "13", "--season", "2026")
    assert code == 0 and out["status"] == "reglamento_no_codificado" and out["reason"] == "source_unreachable"
    code, _ = _run(capsys, "show")
    assert code == 2


def test_load_dry_run_plans_every_file_and_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "load", "--dry-run")
    assert code == 0 and out["dry_run"] is True
    planned = out["planned"]
    assert isinstance(planned, list) and len(planned) == 13

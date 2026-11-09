"""CI-015 - the migrations a pull request adds are read by squawk, which needs each revision to render to SQL without a database."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "lint_new_migrations.sh"
WORKFLOW = BACKEND.parent / ".github" / "workflows" / "migrations-lint.yml"


def _config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def test_the_newest_revision_renders_to_sql_without_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_DATABASE_URL", "postgresql+psycopg://lint@localhost/lint")  # offline mode never connects
    cfg = _config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None
    revision = ScriptDirectory.from_config(cfg).get_revision(head)
    assert revision is not None and isinstance(revision.down_revision, str)
    buffer = StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{revision.down_revision}:{head}", sql=True)
    sql = buffer.getvalue()
    assert f"Running upgrade {revision.down_revision} -> {head}" in sql
    assert sql.lstrip().startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;")


def test_the_lint_script_parses_and_reads_only_the_added_files() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    assert subprocess.run([bash, "-n", "scripts/lint_new_migrations.sh"], cwd=BACKEND, capture_output=True, text=True, check=False).returncode == 0
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--diff-filter=A" in text and "set -euo pipefail" in text


def test_squawk_is_configured_for_postgresql_16_and_names_why_each_rule_is_left_out() -> None:
    text = (BACKEND / ".squawk.toml").read_text(encoding="utf-8")
    assert 'pg_version = "16"' in text
    excluded = re.search(r"excluded_rules = \[(.*?)\]", text)
    assert excluded is not None
    for rule in re.findall(r'"([a-z-]+)"', excluded[1]):
        assert rule in text.split("excluded_rules")[0], f"{rule} is excluded without a reason written above"


def test_the_workflow_pins_squawk_and_verifies_the_download() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"SQUAWK_SHA256: '[0-9a-f]{64}'", text) and "sha256sum -c -" in text
    assert "continue-on-error: true" in text, "informative until it is trusted (CI-015)"
    assert "persist-credentials: false" in text
    assert os.access(SCRIPT, os.R_OK)

"""Migration 0172 (PM-12-06, PM-12-01): the two append-only tables of the private evaluation and nothing else - no row written, no
existing table touched, no foreign key outside them, a bounded lock wait, a downgrade that never deletes a measure, and their block in
``grants.sql`` (the privileges themselves in ``tests/integration/test_db_roles.py``)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0172_model_evaluation_board.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0172", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


def render(direction: str) -> list[str]:
    module = load()
    recorder = Recorder()
    vars(module)["op"] = recorder
    getattr(module, direction)()
    return recorder.statements


def test_revision_chains_on_0171() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0172", "0171")


def test_upgrade_creates_the_two_tables_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert sql.count("CREATE TABLE") == 2
    assert "CREATE TABLE analytics.evaluation_reports (" in sql and "CREATE TABLE analytics.evaluation_segments (" in sql
    assert sql.count("REFERENCES") == 1 and "REFERENCES analytics.evaluation_reports(id)" in sql
    assert sql.count("CREATE INDEX") == 1
    for word in ("INSERT", "UPDATE ", "DELETE", "ALTER TABLE", "DROP"):
        assert word not in sql, word
    assert "CHECK (verdict IN ('apta', 'sin_habilidad', 'insuficiente'))" in sql
    assert "CHECK (verdict <> 'apta' OR (skill_high IS NOT NULL AND skill_high < 0))" in sql


def test_downgrade_refuses_to_delete_measures() -> None:
    sql = " ".join(render("downgrade"))
    assert "holds measures" in sql and "DELETE" not in sql
    assert sql.index("DROP TABLE IF EXISTS analytics.evaluation_segments") < sql.index("DROP TABLE IF EXISTS analytics.evaluation_reports")


def test_grants_append_only_for_the_worker_and_read_only_for_the_api() -> None:
    text = GRANTS.read_text(encoding="utf-8")
    block = text[text.index("DO $evaluation_board$"):text.index("$evaluation_board$;")]
    assert "'analytics.evaluation_reports', 'analytics.evaluation_segments'" in block
    assert "GRANT SELECT, INSERT ON %s TO predigol_worker" in block
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM predigol_worker" in block
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %s FROM predigol_api" in block

"""Migration 0176 (PM-14-07): the one table of the readers' «solo fútbol» mode and pause, and nothing else: no row written, no existing
table touched, nothing kept but a flag and a date, a bounded lock wait, a downgrade that never deletes a choice. The privileges are proved
in ``tests/integration/test_db_roles.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0176_wellbeing.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0176", MIGRATION)
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


def test_revision_chains_on_0175() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0176", "0175")


def test_upgrade_creates_the_table_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert sql.count("CREATE TABLE customer.wellbeing (") == 1 and sql.count("CREATE TABLE") == 1
    assert sql.count("CREATE INDEX") == 0 and sql.count("CREATE UNIQUE INDEX") == 0
    assert "REFERENCES auth.users(id) ON DELETE RESTRICT" in sql and sql.count("REFERENCES") == 1
    for word in ("INSERT", "UPDATE ", "ALTER TABLE", "DROP", "email", "reason", "counter"):
        assert word not in sql, word


def test_the_table_keeps_a_flag_and_a_date_and_nothing_else() -> None:
    sql = " ".join(render("upgrade"))
    block = sql[sql.index("CREATE TABLE customer.wellbeing"):sql.index("COMMENT ON TABLE")]
    columns = [line.split()[0] for line in block.splitlines()[1:] if line.strip() and not line.strip().startswith(("CHECK", ")"))]
    assert columns == ["user_id", "football_only", "paused_until", "created_at", "updated_at"]
    assert "football_only BOOLEAN      NOT NULL DEFAULT false" in block


def test_downgrade_refuses_while_a_choice_exists_and_deletes_nothing() -> None:
    statements = render("downgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    assert "IF EXISTS (SELECT 1 FROM customer.wellbeing) THEN" in statements[1] and "RAISE EXCEPTION" in statements[1]
    sql = " ".join(statements)
    assert "DELETE" not in sql and "TRUNCATE" not in sql
    assert statements[2:] == ["DROP TABLE IF EXISTS customer.wellbeing"]


def test_grants_sql_names_the_table() -> None:
    grants = GRANTS.read_text(encoding="utf-8")
    assert "'customer.wellbeing:INSERT, UPDATE, DELETE'," in grants

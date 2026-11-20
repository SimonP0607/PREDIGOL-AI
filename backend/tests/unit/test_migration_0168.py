"""Migration 0168 (PM-01-02): three new tables - requests by endpoint and lane, the daily summary of the per-minute peaks and the history of
the database's size - and nothing else: no row written, no existing table touched, a bounded lock wait, a downgrade that never deletes a
measure. The database side is proved in ``tests/integration/test_migration_0168_provider_usage.py``; the privileges in
``tests/integration/test_db_roles.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0168_provider_usage_history.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0168", MIGRATION)
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


def test_revision_chains_on_0167() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0168", "0167")


def test_upgrade_creates_the_three_tables_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    for table in ("raw.provider_endpoint_usage", "raw.provider_minute_daily", "audit.db_size_history"):
        assert f"CREATE TABLE {table} (" in sql
    assert "PRIMARY KEY (provider, usage_date, endpoint, lane, job)" in sql
    assert "PRIMARY KEY (provider, usage_date)" in sql
    for word in ("INSERT", "UPDATE raw", "DELETE", "ALTER TABLE", "DROP", "CREATE INDEX"):
        assert word not in sql, word


def test_downgrade_refuses_while_a_measure_exists_and_deletes_nothing() -> None:
    statements = render("downgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    refusal = statements[1]
    for table in load().TABLES:
        assert f"IF EXISTS (SELECT 1 FROM {table}) THEN" in refusal
    assert "RAISE EXCEPTION" in refusal
    sql = " ".join(statements)
    assert "DELETE" not in sql and "TRUNCATE" not in sql
    assert statements[2:] == [f"DROP TABLE IF EXISTS {t}" for t in reversed(load().TABLES)]


def test_grants_sql_names_the_three_tables() -> None:
    grants = GRANTS.read_text(encoding="utf-8")
    assert "$provider_usage$" in grants
    for table in load().TABLES:
        assert f"'{table}'" in grants
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit.db_size_history FROM predigol_api, predigol_worker" in grants

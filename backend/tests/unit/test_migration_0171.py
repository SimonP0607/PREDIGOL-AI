"""Migration 0171 (PM-14-06): the one table of the readers' secret calendar links, and nothing else: no row written, no existing table
touched, the secret never stored (only its SHA-256), one live link per reader, a bounded lock wait, a downgrade that never deletes a link.
The privileges are proved in ``tests/integration/test_db_roles.py`` and the table in ``tests/integration/test_migration_0171_calendar.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0171_calendar_feeds.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0171", MIGRATION)
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


def test_revision_chains_on_0170() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0171", "0170")


def test_upgrade_creates_the_table_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert "CREATE TABLE customer.calendar_feeds (" in sql
    assert sql.count("CREATE TABLE") == 1 and sql.count("CREATE UNIQUE INDEX") == 1 and sql.count("CREATE INDEX") == 0
    assert "CREATE UNIQUE INDEX calendar_feeds_one_live ON customer.calendar_feeds (user_id) WHERE revoked_at IS NULL" in sql
    assert "token_hash    TEXT          NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$')" in sql
    assert "REFERENCES auth.users(id) ON DELETE RESTRICT" in sql and sql.count("REFERENCES") == 1
    for word in ("INSERT", "UPDATE ", "DELETE", "ALTER TABLE", "DROP", "email", "token TEXT"):
        assert word not in sql.replace("ON DELETE RESTRICT", ""), word


def test_downgrade_refuses_while_a_link_exists_and_deletes_nothing() -> None:
    statements = render("downgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    assert "IF EXISTS (SELECT 1 FROM customer.calendar_feeds) THEN" in statements[1] and "RAISE EXCEPTION" in statements[1]
    sql = " ".join(statements)
    assert "DELETE" not in sql and "TRUNCATE" not in sql
    assert statements[2:] == ["DROP TABLE IF EXISTS customer.calendar_feeds"]


def test_grants_sql_names_the_table() -> None:
    grants = GRANTS.read_text(encoding="utf-8")
    assert "'customer.calendar_feeds:INSERT, UPDATE, DELETE'," in grants

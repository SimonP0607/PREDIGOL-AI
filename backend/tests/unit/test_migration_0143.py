"""Migration 0143 (IA-072): one new append-only table, ``core.competition_rules``, and its refusing function - nothing else, no data,
a bounded lock wait. Its states and schema version are the code's. Read back from a database in
``tests/integration/test_migration_0143_competition_rules.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fbi.competitions import rules as rl

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0143_competition_rules.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0143", MIGRATION)
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


def test_revision_chains_on_the_highest_in_this_tree() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0143", "0142")


def test_upgrade_creates_one_append_only_table_and_writes_no_row() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = "\n".join(statements)
    assert sql.count("CREATE TABLE") == 1 and "CREATE TABLE core.competition_rules" in sql
    assert "BEFORE UPDATE OR DELETE ON core.competition_rules" in sql and "core.refuse_rules_change()" in sql
    assert "UNIQUE (league_id, rules_version, file_sha256)" in sql
    assert f"schema_version = '{rl.SCHEMA}'" in sql and "state IN ('coded', 'retired')" in sql
    for verb in ("INSERT", "UPDATE core.", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
        assert verb not in sql


def test_downgrade_drops_only_what_it_created() -> None:
    statements = render("downgrade")
    assert statements == ["SET LOCAL lock_timeout = '10s'", "DROP TABLE IF EXISTS core.competition_rules",
                          "DROP FUNCTION IF EXISTS core.refuse_rules_change()"]

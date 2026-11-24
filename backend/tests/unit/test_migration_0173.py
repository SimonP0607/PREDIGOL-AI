"""Migration 0173 (C-10 1.1): one more allowed source of ``core.entity_aliases`` (``localized``) and nothing else - no row
written, no other table or column touched, a bounded lock wait, the constraint added NOT VALID and then validated, and a
downgrade that never deletes an alias."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0173_localized_aliases.py"
BEFORE = ROOT / "migrations" / "versions" / "0141_entity_ids_aliases.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0173", MIGRATION)
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


def test_revision_chains_on_0172() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0173", "0172")


def test_the_old_sources_are_the_ones_0141_allowed_and_one_is_added() -> None:
    m = load()
    text = BEFORE.read_text(encoding="utf-8")
    for source in m.SOURCES_BEFORE:
        assert f"'{source}'" in text, source
    assert m.NEW_SOURCES == ("localized",) and m.SOURCES == m.SOURCES_BEFORE + m.NEW_SOURCES


def test_upgrade_only_replaces_the_source_check() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert sql.count("ALTER TABLE core.entity_aliases") == 3
    assert "DROP CONSTRAINT entity_aliases_source_check" in sql
    assert "'localized')) NOT VALID" in sql and "VALIDATE CONSTRAINT entity_aliases_source_check" in sql
    for word in ("INSERT", "UPDATE ", "DELETE", "CREATE TABLE", "ADD COLUMN", "DROP TABLE", "DROP COLUMN"):
        assert word not in sql, word


def test_downgrade_refuses_while_an_alias_has_the_new_source() -> None:
    sql = " ".join(render("downgrade"))
    assert "RAISE EXCEPTION" in sql and "WHERE source IN ('localized')" in sql
    assert "DELETE" not in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP CONSTRAINT")

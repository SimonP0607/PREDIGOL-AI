"""Migration 0174 (C-06 1.1): four more allowed categories of ``news.stories`` and nothing else - no row written, no other table or
column touched, a bounded lock wait, NOT VALID then validated, and a downgrade that refuses while a story has a new category."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fbi.news import vocab

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0174_news_categories.py"
BEFORE = ROOT / "migrations" / "versions" / "0146_news_schema.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0174", MIGRATION)
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


def test_revision_chains_on_0173_and_the_list_is_the_vocabularys() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0174", "0173")
    assert m.CATEGORIES == vocab.CATEGORIES
    before = BEFORE.read_text(encoding="utf-8")
    assert all(f'"{c}"' in before for c in m.CATEGORIES_BEFORE)


def test_upgrade_only_replaces_the_category_check() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert sql.count("ALTER TABLE news.stories") == 3
    assert "'actualidad')) NOT VALID" in sql and "VALIDATE CONSTRAINT stories_category_check" in sql
    for word in ("INSERT", "UPDATE ", "DELETE", "CREATE TABLE", "ADD COLUMN", "DROP TABLE", "DROP COLUMN"):
        assert word not in sql, word


def test_downgrade_refuses_while_a_story_has_a_new_category() -> None:
    sql = " ".join(render("downgrade"))
    assert "RAISE EXCEPTION" in sql and sql.index("RAISE EXCEPTION") < sql.index("DROP CONSTRAINT")
    assert "DELETE" not in sql and "UPDATE " not in sql

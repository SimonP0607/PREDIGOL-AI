"""Migration 0159 (IA-118): ``ai.chronicle_reviews`` also keeps ``chronicle-review-v2`` - one new nullable column, two checks, one index; no
row written, rewritten or deleted; a bounded lock wait; a downgrade that refuses to run while a v2 review exists (it never deletes one). The
database side is proved in ``tests/integration/test_chronicle_ia116_db.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fbi.chronicle import review_v2

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0159_chronicle_reviews_v2.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0159", MIGRATION)
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


def test_revision_chains_on_0158() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0159", "0158")


def test_upgrade_adds_the_column_and_the_checks_and_writes_no_row() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert "ADD COLUMN chronicle_id BIGINT;" in sql and "DROP NOT NULL" in sql
    assert "num_nonnulls(narrative_id, chronicle_id) = 1" in sql
    assert "'^(user-narrative|chronicle)-v[0-9]+$'" in sql
    assert "ON ai.chronicle_reviews (chronicle_id, version)" in sql and "WHERE chronicle_id IS NOT NULL" in sql
    for word in ("INSERT", "UPDATE ai.", "DELETE", "DROP TABLE", "DISABLE TRIGGER"):
        assert word not in sql, word


def test_the_code_writes_what_the_new_checks_accept() -> None:
    assert review_v2.VERSION == "chronicle-review-v2"
    assert "NULL, %(chronicle)s" in review_v2.INSERT_SQL and "ON CONFLICT (chronicle_id, version) WHERE chronicle_id IS NOT NULL" in review_v2.INSERT_SQL


def test_downgrade_restores_0132_and_deletes_nothing() -> None:
    sql = " ".join(render("downgrade"))
    assert "CHECK (narrative_version ~ '^user-narrative-v[0-9]+$')" in sql and "SET NOT NULL" in sql and "DROP COLUMN chronicle_id" in sql
    assert "DELETE" not in sql and "DISABLE TRIGGER" not in sql

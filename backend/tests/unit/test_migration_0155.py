"""Migration 0155 (IA-103/IA-104): one new append-only table, ``ai.chronicles`` - nothing else, no data, a bounded lock wait. Its statuses,
abstentions and versions are the code's. Read back from a database in ``tests/integration/test_chronicle_v4_db.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fbi.chronicle import plan as cp
from fbi.chronicle import v4_job, verify, writer

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0155_chronicles_v4.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0155", MIGRATION)
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


def test_revision_chains_on_0154() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0155", "0154")


def test_upgrade_creates_one_append_only_table_and_writes_no_row() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = "\n".join(statements)
    assert sql.count("CREATE TABLE") == 1 and "CREATE TABLE ai.chronicles" in sql
    assert "BEFORE UPDATE OR DELETE ON ai.chronicles" in sql and "ai.refuse_change()" in sql
    for verb in ("INSERT", "UPDATE ai.", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
        assert verb not in sql


def test_the_tables_words_are_the_codes() -> None:
    m = load()
    assert set(m.ABSTENTIONS) == set(cp.ABSTENTIONS)
    assert set(v4_job.ANSWERED) | {"abstained", "failed"} == set(m.STATUSES)
    sql = "\n".join(render("upgrade"))
    for version, pattern in ((writer.VERSION, "chronicle-v"), (cp.VERSION, "content-plan-v"), (verify.VERSION, "chronicle-verify-v")):
        assert version.startswith(pattern) and f"'^{pattern}[0-9]+$'" in sql


def test_downgrade_drops_only_what_it_created() -> None:
    assert render("downgrade") == ["SET LOCAL lock_timeout = '10s'", "DROP TABLE IF EXISTS ai.chronicles"]

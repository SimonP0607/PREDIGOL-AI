"""Migration 0127 (Gate B) holds to the code without a database: its list is the code's vocabulary, its downgrade refuses while a row of the new
words exists, it waits at most ten seconds for a lock, and the chain of the revisions has one head. The same lists are read back out of the
database in ``tests/integration/test_migration_0127.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.script import ScriptDirectory

from fbi.ai import gate_b, gates

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0127_ia_gate_b_and_lab_plan.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0127", MIGRATION)
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


def test_the_list_of_the_migration_is_the_list_of_the_code() -> None:
    m = load()
    assert m.GATES == gates.GATES and m.NEW_GATES == (gate_b.GATE, gates.LAB_PLAN) == ("gate_b", "lab_plan")
    assert gates.GATES[: -len(m.NEW_GATES)] == m.GATES_BEFORE and m.GATES_BEFORE[-1] == gates.SWITCHES


def test_upgrade_widens_the_check_and_writes_nothing() -> None:
    first, sql = render("upgrade")
    assert first == "SET LOCAL lock_timeout = '10s'"
    assert "CHECK (gate IN ('batch', 'native_schema', 'cache_layout', 'gate_a', 'battery', 'research_v2', 'switches', 'gate_b', 'lab_plan'))" in sql
    assert "NOT VALID" not in sql
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert verb not in sql.upper()


def test_downgrade_refuses_while_rows_of_the_new_words_exist_and_restores_the_old_list() -> None:
    first, sql = render("downgrade")
    assert first == "SET LOCAL lock_timeout = '10s'"
    assert "IF EXISTS (SELECT 1 FROM ai.feature_gates WHERE gate IN ('gate_b', 'lab_plan'))" in sql and "RAISE EXCEPTION" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP CONSTRAINT"), "it refuses before touching the constraint"
    assert "CHECK (gate IN ('batch', 'native_schema', 'cache_layout', 'gate_a', 'battery', 'research_v2', 'switches'))" in sql
    for verb in ("INSERT", "UPDATE", "DELETE FROM", "TRUNCATE"):
        assert verb not in sql.upper(), "a ledger is evidence: nothing is deleted to go down"


def test_the_chain_has_one_head_and_this_migration_follows_0126() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    revision = script.get_revision("0127")
    assert revision is not None and revision.down_revision == "0126"
    assert "0127" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}

"""Migration 0120 (Plan Maestro IA, phase 5) holds to the code, and to the rules of the migrations that came before it.

The migration writes the code's vocabularies into the CHECK constraints of the attribution table (the shadow engines, the agents, the signals, the
classes of error). A list copied by hand is a list that drifts: here nothing needs a database, and ``tests/integration/test_migration_0120.py`` reads the
same lists back out of the constraints the database holds.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from fbi.ai import config
from fbi.ai.agents import attribution, registry
from fbi.ai.contracts import base, learning, postmatch
from fbi.intel import pm_questions

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0120_ia_phase5_attributions.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0120", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load()


class Recorder:
    """Stands in for ``alembic.op``: keeps the SQL the migration would send, in order."""

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


def code(sql: str) -> str:
    """The SQL without its comments and the text of its COMMENT ON statements: what it does, not what it says."""
    kept = [line.split("--", 1)[0] for line in sql.splitlines()]
    return re.sub(r"COMMENT ON [^;]*?IS\s+'(?:[^']|'')*';", "", "\n".join(kept), flags=re.DOTALL)


# -- the chain -----------------------------------------------------------------------------------------------------------------------

def test_it_chains_on_the_shadow_arms_migration_and_nothing_else() -> None:
    assert (M.revision, M.down_revision, M.branch_labels, M.depends_on) == ("0120", "0119", None, None)


def test_the_chain_has_one_head_and_it_is_this_migration_or_one_that_came_after_it() -> None:
    cfg = Config(os.fspath(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", os.fspath(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert heads[0] >= "0120"
    revision = script.get_revision("0120")
    assert revision is not None and revision.down_revision == "0119"


# -- the words -----------------------------------------------------------------------------------------------------------------------

def test_the_words_of_the_table_are_the_words_of_the_code() -> None:
    assert M.SHADOW_ENGINES == config.SHADOW_ENGINES
    assert get_args(postmatch.Attributed) == M.AGENTS
    assert get_args(postmatch.AttributedSignal) == M.SIGNALS
    assert M.CLASSES == pm_questions.CLASSES
    assert get_args(base.Outcome) == M.OUTCOMES
    assert get_args(learning.Subject) == M.SUBJECTS
    assert M.CLASSIFIERS == ("code", "pmr-v1")
    assert get_args(postmatch.AttributionClass) == (*M.CLASSES, "NONE")
    assert registry.VERSION_LABEL.pattern == M.VERSION
    assert attribution.SOURCES == ("live", "batch")
    assert set(M.SETTLED) == attribution.SETTLED


# -- the upgrade ---------------------------------------------------------------------------------------------------------------------

def test_the_upgrade_waits_no_longer_than_ten_seconds_and_alters_the_busy_tables_before_it_creates_anything() -> None:
    up = render("upgrade")
    assert up[0] == "SET LOCAL lock_timeout = '10s'"
    first_alter = next(i for i, sql in enumerate(up) if "ALTER TABLE analytics.research_hypotheses" in sql)
    first_create = next(i for i, sql in enumerate(up) if re.search(r"\bCREATE\b", sql))
    assert first_alter < first_create, "a lock that cannot be had stops the migration before it has done anything"
    assert all("lock_timeout" not in sql for sql in up[1:]), "the timeout is set once, for the transaction"


def test_the_upgrade_alters_the_two_tables_it_names_and_creates_only_its_own() -> None:
    sql = code("\n".join(render("upgrade")))
    assert set(re.findall(r"ALTER\s+TABLE\s+([\w.]+)", sql)) == {"analytics.research_hypotheses", "analytics.experiments"}
    assert re.findall(r"CREATE\s+TABLE\s+([\w.]+)", sql) == ["intel.agent_attributions"]
    assert re.findall(r"CREATE\s+TRIGGER\s+(\w+)\s+BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+([\w.]+)", sql) == [
        ("agent_attributions_append_only", "intel.agent_attributions")]
    assert "EXECUTE FUNCTION intel.refuse_change()" in sql, "the guard of the siblings, not one of its own"
    assert not re.search(r"\bDROP\b", sql), "an upgrade that only adds"


def test_the_new_columns_are_nullable_and_come_in_pairs() -> None:
    sql = "\n".join(render("upgrade"))
    assert "ADD COLUMN agent         TEXT," in sql and "ADD COLUMN agent_version TEXT," in sql
    assert "NOT NULL" not in sql[:sql.index("CREATE TABLE")], "rows written before stay as they are"
    assert sql.count("CHECK ((agent IS NULL) = (agent_version IS NULL))") == 2


def test_the_upgrade_writes_no_row_and_names_no_role() -> None:
    writes = re.compile(r"^\s*(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE)\b", flags=re.IGNORECASE | re.MULTILINE)
    roles = re.compile(r"\b(GRANT|REVOKE|CREATE\s+ROLE|ALTER\s+ROLE|DROP\s+ROLE|OWNER\s+TO|SECURITY\s+DEFINER|SET\s+ROLE|SET\s+SESSION\s+AUTHORIZATION)\b",
                       flags=re.IGNORECASE)
    for sql in render("upgrade"):
        assert not writes.search(code(sql)), code(sql)
        assert not roles.search(code(sql)), code(sql)


def test_the_new_table_points_to_no_other_table() -> None:
    assert "REFERENCES" not in code("\n".join(render("upgrade"))).upper(), "no foreign key to a busy table, or to any"


def test_the_table_is_idempotent_by_a_unique_key_and_a_refinement_is_one_per_row() -> None:
    sql = "\n".join(render("upgrade"))
    assert "CREATE UNIQUE INDEX agent_attributions_once" in sql
    assert "CREATE UNIQUE INDEX agent_attributions_one_refinement ON intel.agent_attributions (basis_id) WHERE basis_id IS NOT NULL" in sql
    assert "(outcome = 'MISS') = (error_class <> 'NONE')" in sql
    assert "(classified_by = 'code') = (basis_id IS NULL)" in sql


def test_the_table_and_the_columns_that_need_saying_say_what_they_are() -> None:
    sql = "\n".join(render("upgrade"))
    assert "COMMENT ON TABLE intel.agent_attributions IS" in sql
    for column in ("classified_by", "engine", "signal", "stance", "outcome", "error_class", "toward_close", "calibration", "source"):
        assert f"COMMENT ON COLUMN intel.agent_attributions.{column} IS" in sql, column
    assert all(sql.count("'") % 2 == 0 for sql in render("upgrade")), "an apostrophe in a comment would end the text early"


# -- the downgrade -------------------------------------------------------------------------------------------------------------------

def test_the_downgrade_waits_no_longer_than_ten_seconds_and_drops_only_what_the_upgrade_made() -> None:
    down = render("downgrade")
    assert down[0] == "SET LOCAL lock_timeout = '10s'"
    sql = code("\n".join(down))
    assert re.findall(r"DROP\s+TABLE\s+([\w.]+)", sql) == ["intel.agent_attributions"]
    assert not re.search(r"\bDELETE\b|\bTRUNCATE\b|\bUPDATE\b", sql)
    up = code("\n".join(render("upgrade")))
    assert set(re.findall(r"ALTER\s+TABLE\s+([\w.]+)", sql)) == set(re.findall(r"ALTER\s+TABLE\s+([\w.]+)", up))
    assert set(re.findall(r"DROP CONSTRAINT\s+(\w+)", sql)) == set(re.findall(r"ADD CONSTRAINT\s+(\w+)", up)) - {
        "agent_attributions_a_miss_has_a_class", "agent_attributions_a_refinement_refines", "agent_attributions_a_refinement_refines_a_miss"}


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_nothing_in_the_migration_depends_on_the_database_it_runs_in(direction: str) -> None:
    assert render(direction) == render(direction)

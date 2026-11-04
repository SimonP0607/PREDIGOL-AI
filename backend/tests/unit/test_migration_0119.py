"""Migration 0119 (Plan Maestro IA, phase 3) holds to the code, and to the rules of the migrations that came before it.

The migration writes the code's vocabularies into two CHECK constraints - the engines a review can carry and the kinds of cycle the AI jobs open -
and a rule of the sample into a third on its own table. A list copied by hand is a list that drifts: here nothing needs a database, and
``tests/integration/test_migration_0119.py`` reads the same lists back out of the constraints the database holds.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from fbi.ai import arms, config, idempotency

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0119_ia_phase3_shadow_arms.py"
CODE = [ROOT / "src", ROOT / "apps"]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0119", MIGRATION)
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
    """What ``upgrade`` or ``downgrade`` would execute - f-strings and all - without a database."""
    module = load()
    recorder = Recorder()
    vars(module)["op"] = recorder
    getattr(module, direction)()
    return recorder.statements


def code(sql: str) -> str:
    """The SQL without its comments and the text of its COMMENT ON statements: what it does, not what it says."""
    kept = [line.split("--", 1)[0] for line in sql.splitlines()]
    return re.sub(r"COMMENT ON [^;]*?IS\s+'(?:[^']|'')*';", "", "\n".join(kept), flags=re.DOTALL)


# ── the chain ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_it_chains_on_the_family_learning_migration_and_nothing_else() -> None:
    assert (M.revision, M.down_revision, M.branch_labels, M.depends_on) == ("0119", "0118", None, None)


def test_the_chain_has_one_head_and_it_is_this_migration_or_one_that_came_after_it() -> None:
    cfg = Config(os.fspath(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", os.fspath(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert heads[0] >= "0119"
    revision = script.get_revision("0119")
    assert revision is not None and revision.down_revision == "0118"


# ── the words ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_shadow_engines_are_those_of_the_configuration_and_the_old_ones_are_those_0072_left() -> None:
    assert M.ENGINES == config.PRODUCTION_ENGINES == ("rules", "llm", "combined")
    assert M.SHADOW_ENGINES == config.SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1")
    assert not set(M.ENGINES) & set(M.SHADOW_ENGINES)
    assert set(config.KNOWN_ENGINES) | {"combined"} == set(M.ENGINES) | set(M.SHADOW_ENGINES), "every engine the owner can name, and the one they add up to"


def test_the_kinds_are_the_ones_0112_left_and_the_code_opens_no_kind_that_is_neither_those_nor_the_new_one() -> None:
    assert M.KINDS == ("analysis", "postmortem", "learning", "evaluation", "day_start", "prepare", "package")
    opened: set[str] = set()
    for root in CODE:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            constants = {t.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str) for t in n.targets if isinstance(t, ast.Name)}
            constants |= {n.target.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                          and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
            for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
                name = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else ""
                if name != "open_cycle" or len(call.args) < 2:
                    continue
                kind = call.args[1]
                if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
                    opened.add(kind.value)
                elif isinstance(kind, ast.Name) and kind.id in constants:
                    opened.add(constants[kind.id])
    assert {"analysis", "learning", "package"} <= opened, f"the scan found {sorted(opened)}: it must see the calls it guards"
    assert opened <= set(M.KINDS) | {"orchestrate"}, f"a job opens a kind the table would refuse: {sorted(opened - set(M.KINDS) - {'orchestrate'})}"


def test_the_name_of_an_experiment_is_named_the_way_everything_else_of_the_agents_is() -> None:
    assert idempotency.NAME.pattern == M.NAME


def test_the_sample_rule_the_table_holds_is_the_one_the_arms_apply() -> None:
    """The constants the database repeats are the code's: a table that counted buckets another way would refuse the rows the code writes - or,
    worse, accept the ones it should not."""
    assert M.BUCKETS == arms.BUCKETS
    assert M.SHADOW_ENGINES == (arms.MULTIAGENT, arms.MULTIAGENT_HAIKU, arms.COUNCIL_SOLO)
    assert arms.EXPERIMENT.pattern == M.NAME
    assert f"sampled = (bucket < share * {arms.BUCKETS})" in "\n".join(render("upgrade"))
    assert f"CHECK (bucket BETWEEN 0 AND {arms.BUCKETS - 1})" in "\n".join(render("upgrade"))


# ── the upgrade ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_upgrade_waits_no_longer_than_ten_seconds_and_alters_the_busy_tables_before_it_creates_anything() -> None:
    up = render("upgrade")
    assert up[0] == "SET LOCAL lock_timeout = '10s'"
    first_alter = next(i for i, sql in enumerate(up) if "ALTER TABLE ai.pick_reviews" in sql)
    cycles_alter = next(i for i, sql in enumerate(up) if "ALTER TABLE ai.cycles" in sql)
    first_create = next(i for i, sql in enumerate(up) if re.search(r"\bCREATE\b", sql))
    assert first_alter < first_create and cycles_alter < first_create, "a lock that cannot be had stops the migration before it has done anything"
    assert all("lock_timeout" not in sql for sql in up[1:]), "the timeout is set once, for the transaction"


def test_the_upgrade_alters_the_two_tables_it_names_and_creates_only_its_own() -> None:
    sql = code("\n".join(render("upgrade")))
    assert set(re.findall(r"ALTER\s+TABLE\s+([\w.]+)", sql)) == {"ai.pick_reviews", "ai.cycles"}
    assert re.findall(r"CREATE\s+TABLE\s+([\w.]+)", sql) == ["ai.shadow_assignments"]
    assert re.findall(r"CREATE\s+TRIGGER\s+(\w+)\s+BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+([\w.]+)", sql) == [("shadow_assignments_append_only", "ai.shadow_assignments")]
    assert "EXECUTE FUNCTION ai.refuse_change()" in sql, "the guard of the siblings, not one of its own"
    assert re.findall(r"\bDROP\s+(\w+)\s+(\w+)", sql) == [("CONSTRAINT", "pick_reviews_engine_check"), ("CONSTRAINT", "cycles_kind_check")], \
        "an upgrade that only adds: the one thing it takes away is the old list of each of the two"


def test_the_upgrade_rewrites_each_check_once_with_the_old_words_and_the_new_ones() -> None:
    sql = "\n".join(render("upgrade"))
    assert re.findall(r"ADD CONSTRAINT pick_reviews_engine_check CHECK \(engine IN \(([^)]*)\)\);", sql) == [
        "'rules', 'llm', 'combined', 'ma-v1', 'ma-v1-h', 'cs-v1'"]
    assert re.findall(r"ADD CONSTRAINT cycles_kind_check CHECK \(kind IN \(([^)]*)\)\);", sql) == [
        "'analysis', 'postmortem', 'learning', 'evaluation', 'day_start', 'prepare', 'package', 'orchestrate'"]
    assert "NOT VALID" not in sql, "an upgrade validates what it writes"
    assert len(re.findall(r"DROP CONSTRAINT", sql)) == 2


def test_the_upgrade_writes_no_row_and_names_no_role() -> None:
    """Nothing is written, copied or moved, and a restore made with --no-privileges, or into a cluster that lacks a role, finds nothing here that it
    cannot create (the privileges of a new table are the default ones of ``deploy/vps/db/grants.sql``)."""
    writes = re.compile(r"^\s*(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE)\b", flags=re.IGNORECASE | re.MULTILINE)
    roles = re.compile(r"\b(GRANT|REVOKE|CREATE\s+ROLE|ALTER\s+ROLE|DROP\s+ROLE|OWNER\s+TO|SECURITY\s+DEFINER|SET\s+ROLE|SET\s+SESSION\s+AUTHORIZATION)\b",
                       flags=re.IGNORECASE)
    for sql in render("upgrade"):
        assert not writes.search(code(sql)), code(sql)
        assert not roles.search(code(sql)), code(sql)


def test_the_new_table_points_to_no_other_table() -> None:
    assert "REFERENCES" not in code("\n".join(render("upgrade"))).upper(), "no foreign key to a busy table, or to any"


def test_the_table_has_the_columns_and_the_rules_of_the_plan() -> None:
    sql = "\n".join(render("upgrade"))
    body = sql[sql.index("CREATE TABLE ai.shadow_assignments"):sql.index("COMMENT ON TABLE ai.shadow_assignments")]
    assert re.findall(r"^\s+(\w+)\s+(TEXT|BIGINT|INTEGER|BOOLEAN|NUMERIC|TIMESTAMPTZ)\b", body, flags=re.MULTILINE) == [
        ("experiment", "TEXT"), ("fixture_id", "BIGINT"), ("bucket", "INTEGER"), ("sampled", "BOOLEAN"), ("council_solo", "BOOLEAN"),
        ("share", "NUMERIC"), ("assigned_at", "TIMESTAMPTZ")]
    assert "PRIMARY KEY (experiment, fixture_id)" in body, "a match is assigned once in an experiment"
    assert "NUMERIC(" not in body, "the share is stored as it came: a rounded share could contradict the sample rule"
    assert f"CHECK (experiment ~ '{M.NAME}')" in body
    assert "CHECK (fixture_id >= 1)" in body and "CHECK (bucket BETWEEN 0 AND 9999)" in body and "CHECK (share > 0 AND share <= 1)" in body
    assert "CONSTRAINT shadow_assignments_solo_is_sampled CHECK (NOT council_solo OR sampled)" in body
    assert "CONSTRAINT shadow_assignments_sample_rule CHECK (sampled = (bucket < share * 10000))" in body
    assert M.BUCKETS == 10000


def test_the_table_and_the_columns_that_need_saying_say_what_they_are() -> None:
    sql = "\n".join(render("upgrade"))
    assert "COMMENT ON TABLE ai.shadow_assignments IS" in sql
    for column in ("experiment", "fixture_id", "bucket", "council_solo", "share"):
        assert f"COMMENT ON COLUMN ai.shadow_assignments.{column} IS" in sql, column
    assert all(sql.count("'") % 2 == 0 for sql in render("upgrade")), "an apostrophe in a comment would end the text early"


# ── the downgrade ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_downgrade_waits_no_longer_than_ten_seconds_and_deletes_no_row() -> None:
    down = render("downgrade")
    assert down[0] == "SET LOCAL lock_timeout = '10s'"
    sql = code("\n".join(down))
    assert not re.search(r"\bDELETE\b|\bTRUNCATE\b", sql), "a review is evidence: the reviews of the shadow stay"
    assert re.findall(r"DROP\s+TABLE\s+([\w.]+)", sql) == ["ai.shadow_assignments"], "the one table the upgrade made, and no other"
    assert re.findall(r"UPDATE\s+([\w.]+)", sql) == ["ai.cycles"]


def test_the_downgrade_puts_the_old_lists_back_not_valid_and_closes_the_cycles_the_old_list_would_refuse_first() -> None:
    down = "\n".join(render("downgrade"))
    assert re.findall(r"ADD CONSTRAINT pick_reviews_engine_check CHECK \(engine IN \(([^)]*)\)\) NOT VALID;", down) == ["'rules', 'llm', 'combined'"]
    assert re.findall(r"ADD CONSTRAINT cycles_kind_check CHECK \(kind IN \(([^)]*)\)\) NOT VALID;", down) == [
        "'analysis', 'postmortem', 'learning', 'evaluation', 'day_start', 'prepare', 'package'"]
    closing = down.index("UPDATE ai.cycles")
    assert "kind = 'orchestrate' AND status = 'running'" in down and "status = 'failed', finished_at = started_at" in down
    assert closing < down.index("ALTER TABLE ai.cycles"), "the cycle the old list would refuse is closed before the list is put back"
    assert down.index("DROP TABLE") < closing


def test_the_downgrade_and_the_upgrade_touch_the_same_objects() -> None:
    up, down = code("\n".join(render("upgrade"))), code("\n".join(render("downgrade")))
    assert set(re.findall(r"(?:ALTER|DROP)\s+TABLE\s+([\w.]+)", down)) == set(re.findall(r"(?:ALTER|CREATE)\s+TABLE\s+([\w.]+)", up))
    assert set(re.findall(r"DROP CONSTRAINT\s+(\w+)", down)) == set(re.findall(r"DROP CONSTRAINT\s+(\w+)", up))


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_nothing_in_the_migration_depends_on_the_database_it_runs_in(direction: str) -> None:
    """The statements are plain text with no connection to read from: the same text goes to every database."""
    assert render(direction) == render(direction)

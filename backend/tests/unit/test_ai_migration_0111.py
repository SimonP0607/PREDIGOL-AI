"""Migration 0111 (Plan Maestro IA, phase 1) and the database-role scripts hold to the code.

The migration writes the code's vocabularies into CHECK constraints - the families, the tasks, the passes, the way an agent, a version and
a promotion are named - and the role scripts say the same thing in two places (the cluster that exists, the cluster that is born). A list
copied by hand is a list that drifts: here nothing needs a database, and ``tests/integration/test_agent_tables_0111.py`` reads the same
lists back out of the constraints the database holds.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest

from fbi.ai import idempotency, router
from fbi.ai.agents import registry
from fbi.ai.contracts import base, mcp

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0111_ia_phase1_agent_tasks_runs_state.py"
VPS_DB = ROOT / "deploy" / "vps" / "db"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0111", MIGRATION)
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


def test_it_chains_on_the_ledger_migration_and_nothing_else() -> None:
    assert (M.revision, M.down_revision) == ("0111", "0110")


def test_the_states_and_the_statuses_are_those_the_plan_draws() -> None:
    assert M.TASK_STATES == ("planned", "queued", "running", "done", "failed", "skipped", "expired")
    assert M.RUN_STATUSES == ("ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip")


def test_the_upgrade_locks_the_one_busy_table_first_and_waits_no_longer_than_ten_seconds() -> None:
    up = render("upgrade")
    assert up[:2] == ["SET LOCAL lock_timeout = '10s'", "LOCK TABLE intel.promotions IN ACCESS EXCLUSIVE MODE"]


def test_the_downgrade_refuses_before_it_drops_anything() -> None:
    down = render("downgrade")
    assert down[:3] == ["SET LOCAL lock_timeout = '10s'", "SET LOCAL fbi.ai_maintenance = 'on'",
                        "LOCK TABLE intel.promotions IN ACCESS EXCLUSIVE MODE"]
    refusal = next(i for i, sql in enumerate(down) if "0111 cannot be downgraded" in sql)
    first_drop = next(i for i, sql in enumerate(down) if re.search(r"\bDROP\b", sql))
    assert refusal < first_drop, "the decisions of the owner are never destroyed, and nothing is touched before that is known"


def test_the_ddl_is_free_of_roles() -> None:
    """A restore made with --no-privileges, or into a cluster that lacks the role, finds nothing here that it cannot create."""
    forbidden = re.compile(r"\b(GRANT|REVOKE|CREATE\s+ROLE|ALTER\s+ROLE|DROP\s+ROLE|OWNER\s+TO|SECURITY\s+DEFINER|SET\s+ROLE|SET\s+SESSION\s+AUTHORIZATION)\b",
                           flags=re.IGNORECASE)
    for sql in render("upgrade") + render("downgrade"):
        code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
        assert not forbidden.search(code), code


def test_the_new_tables_hold_a_foreign_key_to_the_table_they_are_born_with_and_to_no_busy_one() -> None:
    referenced = set(re.findall(r"REFERENCES\s+([\w.]+)", "\n".join(render("upgrade"))))
    assert referenced == {"ai.agent_runs"}


def test_the_only_existing_table_the_upgrade_alters_is_the_one_it_locked() -> None:
    sql = "\n".join(render("upgrade"))
    assert set(re.findall(r"ALTER\s+TABLE\s+([\w.]+)", sql)) == {"intel.promotions"}
    assert set(re.findall(r"CREATE\s+POLICY\s+\w+\s+ON\s+([\w.]+)", sql)) == {"intel.promotions"}


def test_the_families_are_those_of_the_contracts() -> None:
    assert M.FAMILIES == base.FAMILIES
    assert M.FAMILIES == base.GOALS_RESULT + base.COUNTS


def test_the_passes_are_those_of_the_package_and_of_the_key() -> None:
    assert get_args(mcp.PassKind) == M.PASS_KINDS
    assert tuple(idempotency.PASS_KINDS) == M.PASS_KINDS


def test_the_tasks_are_those_the_router_and_the_registry_know() -> None:
    registry_tasks = {t.task for spec in registry.REGISTRY.agents for t in spec.tasks}
    registry_tasks |= {t.task for plan in registry.REGISTRY.planned for t in plan.tasks}
    assert set(M.TASKS) == set(router.TASKS) | registry_tasks, "a task the code can plan must be one the queue admits, and the other way round"
    assert len(set(M.TASKS)) == len(M.TASKS)


def test_the_roles_of_a_promotion_are_those_the_table_has_always_had() -> None:
    assert M.ROLES == ("CHAMPION", "CHALLENGER", "RETIRED", "REJECTED", "VALIDATED", "NOT_VALIDATED")
    assert M.ENTITIES[:-1] == ("calibrator", "market_edge", "selection_rule", "model"), "the four of 0076, in the same order"
    assert M.ENTITIES[-1] == "agent"


def test_a_name_is_checked_as_the_idempotency_key_checks_it() -> None:
    assert idempotency.NAME.pattern == M.NAME


def test_a_gate_is_named_as_a_version_of_the_registry_is() -> None:
    assert registry.VERSION_LABEL.pattern == M.GATE_VERSION


NAMES = [
    "council@council-v1", "council@council-v1+match-v1", "council@council-v1+match-v1+stats-v1", "match@match-v1", "post_match_reviewer@pmr-v1",
    "learning_analyst@la-v12", "council@council-v999",
    "", "council", "council@", "@council-v1", "Council@council-v1", "council@council", "council@council-v0", "council@council-v1000",
    "council@council-v1+", "council@council-v1+match", "council@council-v1 +match-v1", "council@council-v1+match-v1\x00", "council @council-v1",
    "council@council-v1,match-v1", "council@council_v1", "1council@council-v1", "council@1council-v1", "council@council-v1+Match-v1",
    "council@council-v1++match-v1", "co@un@council-v1", "council-v1", "ñ@council-v1",
]


@pytest.mark.parametrize("name", NAMES)
def test_a_promotion_is_named_as_the_registry_names_it(name: str) -> None:
    """The database refuses a name by the migration's expression and the code by the registry's: they must agree on every one."""
    in_sql = re.search(M.PROMOTION_NAME, name) is not None
    in_code = registry.PROMOTION_NAME.fullmatch(name) is not None
    assert in_sql == in_code, name


def test_the_names_the_registry_makes_are_names_the_database_takes() -> None:
    for agent, version, upstream in (("council", "council-v1", ("match-v1",)), ("council", "council-v2", ("match-v2", "stats-v1")),
                                     ("match", "match-v1", ()), ("learning_analyst", "la-v1", ())):
        name = registry.promotion_name(agent, version, upstream)
        assert re.search(M.PROMOTION_NAME, name), name


# ── the scripts of the roles ────────────────────────────────────────────────────────────────────────────────────────────────────────

CREATE = "CREATE ROLE predigol_rollback NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;"
GRANT = "GRANT predigol_rollback TO predigol_worker WITH INHERIT FALSE, SET TRUE;"


def comment_of(text: str) -> str:
    found = re.findall(r"^COMMENT ON ROLE predigol_rollback IS '[^']*';$", text, flags=re.MULTILINE)
    assert len(found) == 1, found
    return found[0]


def test_a_cluster_that_exists_and_one_that_is_born_get_the_same_role() -> None:
    existing = (VPS_DB / "roles.sql").read_text()
    born = (VPS_DB / "initdb" / "10-predigol-roles.sh").read_text()
    for statement in (CREATE, GRANT):
        assert statement in existing, statement
        assert statement in born, statement
    assert comment_of(existing) == comment_of(born)


def test_the_role_of_the_policy_is_the_role_the_scripts_create() -> None:
    assert M.ROLLBACK_ROLE == "predigol_rollback"
    assert CREATE.startswith(f"CREATE ROLE {M.ROLLBACK_ROLE} ")
    assert GRANT.startswith(f"GRANT {M.ROLLBACK_ROLE} TO predigol_worker ")
    assert sum(f"current_user = '{M.ROLLBACK_ROLE}'" in sql for sql in render("upgrade")) == 1, "the policy names the role once, as the user that is acting"


def test_the_role_can_log_in_nowhere_and_nothing_bypasses_the_policy() -> None:
    flags = set(CREATE.rstrip(";").split()[3:])
    assert flags == {"NOLOGIN", "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS"}


def test_the_membership_is_to_set_the_role_and_not_to_inherit_its_privileges() -> None:
    for script in ("roles.sql", "initdb/10-predigol-roles.sh"):
        text = (VPS_DB / script).read_text()
        assert GRANT in text, "the worker must not hold the role's privileges until it asks for them (SET ROLE)"
        assert not re.search(r"GRANT\s+predigol_rollback\s+TO\s+predigol_api", text), "the API never reaches the role"


def test_the_grants_give_the_role_two_privileges_on_one_table_and_nothing_else() -> None:
    text = (VPS_DB / "grants.sql").read_text()
    block = text.split("DO $rollback$", 1)[1].split("$rollback$;", 1)[0]
    statements = sorted(re.sub(r"\s+", " ", s).strip() for s in re.findall(r"^\s*(GRANT [^;]*;|EXECUTE format\([^;]*;)", block, flags=re.MULTILINE))
    assert statements == sorted([
        "GRANT USAGE ON SCHEMA intel TO predigol_rollback;",
        "GRANT SELECT, INSERT ON intel.promotions TO predigol_rollback;",
        "EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO predigol_rollback', pg_get_serial_sequence('intel.promotions', 'id'));",
    ])
    outside = text.replace(block, "")
    # outside its own block the file names the role only in comments: the generic loops, which grant by schema, never reach it
    code = "\n".join(line for line in outside.splitlines() if not line.lstrip().startswith("--"))
    assert "predigol_rollback" not in code, "only the block above grants anything to the role"


def test_the_grants_leave_a_cluster_without_the_role_alone() -> None:
    block = (VPS_DB / "grants.sql").read_text().split("DO $rollback$", 1)[1]
    assert "pg_roles WHERE rolname = 'predigol_rollback'" in block
    assert block.index("RETURN;") < block.index("GRANT USAGE ON SCHEMA intel"), "nothing is granted to a role that does not exist"

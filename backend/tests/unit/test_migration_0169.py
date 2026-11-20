"""Migration 0169 (PM-02-02): the five tables of the availability matrix - coverage cells, markets, the facts of each match, the history of
their levels and the shadow's discrepancies - and nothing else: no row written, no existing table touched, no foreign key (no lock on core), a bounded lock
wait, a downgrade that never deletes a measure. The database side is proved in ``tests/integration/test_migration_0169_availability.py``;
the privileges in ``tests/integration/test_db_roles.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0169_availability_matrix.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0169", MIGRATION)
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


def test_revision_chains_on_0168() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0169", "0168")


def test_upgrade_creates_the_five_tables_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    for table in load().TABLES:
        assert f"CREATE TABLE {table} (" in sql
    assert "PRIMARY KEY (competition_season_id, phase_key, datum)" in sql
    assert "PRIMARY KEY (competition_season_id, market_key)" in sql
    assert "UNIQUE (day, fixture_id, module, subject)" in sql
    assert "fixture_id             BIGINT        PRIMARY KEY" in sql
    # the one index is on a table created by this very revision
    assert sql.count("CREATE INDEX") == 1
    assert "CREATE INDEX coverage_fixture_facts_season ON analytics.coverage_fixture_facts (competition_season_id, kickoff_at)" in sql
    for word in ("INSERT", "UPDATE ", "DELETE", "ALTER TABLE", "DROP", "REFERENCES"):
        assert word not in sql, word


def test_the_levels_are_the_vocabulary_of_the_rules() -> None:
    from fbi.coverage import levels

    sql = " ".join(render("upgrade"))
    assert "IN ('" + "', '".join(levels.LEVELS) + "')" in sql
    assert all(len(d) <= 32 for d in levels.DATA) and all(len(m) <= 64 for m in levels.MARKETS)


def test_downgrade_refuses_while_a_measure_exists_and_deletes_nothing() -> None:
    statements = render("downgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    refusal = statements[1]
    for table in load().TABLES:
        assert f"IF EXISTS (SELECT 1 FROM {table}) THEN" in refusal
    assert "RAISE EXCEPTION" in refusal
    sql = " ".join(statements)
    assert "DELETE" not in sql and "TRUNCATE" not in sql
    assert statements[2:] == [f"DROP TABLE IF EXISTS {t}" for t in reversed(load().TABLES)]


def test_grants_sql_names_the_five_tables() -> None:
    grants = GRANTS.read_text(encoding="utf-8")
    assert "$availability$" in grants
    for table in load().TABLES:
        assert f"'{table}'" in grants
    assert "EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM predigol_worker', t);" in grants

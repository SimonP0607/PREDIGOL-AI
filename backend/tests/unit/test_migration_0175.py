"""Migration 0175 (PM-05-01, PM-05-02): the table of team statistics by half and the register of what was asked for them, and nothing
else - no row written, no existing table touched, only the foreign keys the match table itself has, a bounded lock wait, a downgrade that
never deletes a measure, and their block in ``grants.sql`` (the privileges themselves in ``tests/integration/test_db_roles.py``)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0175_period_statistics.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0175", MIGRATION)
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


def test_revision_chains_on_0174() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0175", "0174")


def test_upgrade_creates_the_two_tables_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert sql.count("CREATE TABLE") == 2
    assert "CREATE TABLE core.fixture_team_stats_period (" in sql and "CREATE TABLE core.fixture_period_asks (" in sql
    # the foreign keys are the match table's own (the fixture and the payload) - to nothing else
    assert sorted(re.findall(r"REFERENCES ([a-z_.]+)\(", sql)) == sorted(
        ["core.fixtures", "raw.ingestion_payloads", "core.fixtures", "raw.ingestion_payloads"])
    for word in ("INSERT", "UPDATE ", "DELETE FROM", "ALTER TABLE", "DROP", "TRUNCATE"):
        assert word not in sql, word


def test_a_figure_not_sent_is_null_never_zero() -> None:
    """The columns are the match table's, none NOT NULL and none with a default: not sent is NULL."""
    sql = " ".join(render("upgrade"))
    block = sql[sql.index("CREATE TABLE core.fixture_team_stats_period"):sql.index("CREATE TABLE core.fixture_period_asks")]
    for column in ("shots", "corners", "fouls", "offsides", "yellow_cards", "red_cards", "saves", "possession_pct", "expected_goals"):
        line = next(ln for ln in block.splitlines() if ln.strip().startswith(column + " "))
        assert "NOT NULL" not in line and "DEFAULT" not in line, line
    assert "CHECK (period IN ('1h', '2h'))" in block
    assert "PRIMARY KEY (fixture_id, team_side, period, source)" in block


def test_downgrade_refuses_to_delete_measures() -> None:
    sql = " ".join(render("downgrade"))
    assert "holds measures" in sql and "DELETE" not in sql
    assert sql.index("DROP TABLE IF EXISTS core.fixture_period_asks") < sql.index("DROP TABLE IF EXISTS core.fixture_team_stats_period")


def test_grants_insert_and_update_for_the_worker_and_read_only_for_the_api() -> None:
    text = GRANTS.read_text(encoding="utf-8")
    block = text[text.index("DO $period_stats$"):text.index("$period_stats$;")]
    assert "'core.fixture_team_stats_period', 'core.fixture_period_asks'" in block
    assert "GRANT SELECT, INSERT, UPDATE ON %s TO predigol_worker" in block
    assert "REVOKE DELETE, TRUNCATE ON %s FROM predigol_worker" in block
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %s FROM predigol_api" in block

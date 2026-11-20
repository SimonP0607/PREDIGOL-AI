"""Migration 0170 (PM-05-07): the one table of the market's margin and dispersion by competition, market and day, and nothing else: no
row written, no existing table touched, no foreign key (no lock on core), a bounded lock wait, a downgrade that never deletes a measure.
The database side is proved in ``tests/integration/test_migration_0170_league_daily.py``; the privileges in
``tests/integration/test_db_roles.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0170_market_league_daily_margin.py"
GRANTS = ROOT / "deploy" / "vps" / "db" / "grants.sql"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0170", MIGRATION)
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


def test_revision_chains_on_0169() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0170", "0169")


def test_upgrade_creates_the_table_and_nothing_else() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = " ".join(statements)
    assert "CREATE TABLE market.league_daily_stats (" in sql
    assert "PRIMARY KEY (day, competition_id, market_key, line)" in sql
    assert sql.count("CREATE TABLE") == 1
    # the one index is on the table created by this very revision
    assert sql.count("CREATE INDEX") == 1
    assert "CREATE INDEX league_daily_stats_competition ON market.league_daily_stats (competition_id, day)" in sql
    for word in ("INSERT", "UPDATE ", "DELETE", "ALTER TABLE", "DROP", "REFERENCES"):
        assert word not in sql, word
    for column in ("margin_mean", "margin_median", "margin_p10", "margin_p90"):
        assert f"CHECK ({column} > 0 AND {column} < 1)" in sql
    assert "CHECK (source IN ('final_prematch'))" in sql


def test_downgrade_refuses_while_a_measure_exists_and_deletes_nothing() -> None:
    statements = render("downgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    refusal = statements[1]
    assert "IF EXISTS (SELECT 1 FROM market.league_daily_stats) THEN" in refusal
    assert "RAISE EXCEPTION" in refusal
    sql = " ".join(statements)
    assert "DELETE" not in sql and "TRUNCATE" not in sql
    assert statements[2:] == ["DROP TABLE IF EXISTS market.league_daily_stats"]


def test_grants_sql_names_the_table() -> None:
    grants = GRANTS.read_text(encoding="utf-8")
    assert "$league_daily$" in grants
    assert "GRANT SELECT, INSERT, UPDATE ON market.league_daily_stats TO predigol_worker;" in grants
    assert "REVOKE DELETE, TRUNCATE ON market.league_daily_stats FROM predigol_worker;" in grants
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON market.league_daily_stats FROM predigol_api;" in grants

"""Migration 0178 (PM-03-07): the tier check of ``raw.backfill_tasks`` becomes wider (1 to 30), under the same name, validated, with a bounded
lock wait and no row read or written; the downgrade restores the range of 0023 and refuses, by its own validation, to hide history."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "versions" / "0178_backfill_tier_range.py"
ORIGIN = ROOT / "migrations" / "versions" / "0023_migration_units.py"
CONFIG = ROOT / "config" / "expansion.yaml"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0178", MIGRATION)
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


def test_revision_chains_on_0177() -> None:
    m = load()
    assert (m.revision, m.down_revision) == ("0178", "0177")


def test_upgrade_widens_the_check_under_its_own_name_and_validates_it() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    assert statements[1] == "ALTER TABLE raw.backfill_tasks DROP CONSTRAINT IF EXISTS backfill_tasks_tier_check"
    assert statements[2] == "ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_tier_check CHECK (tier BETWEEN 1 AND 30) NOT VALID"
    assert statements[3] == "ALTER TABLE raw.backfill_tasks VALIDATE CONSTRAINT backfill_tasks_tier_check"
    assert len(statements) == 4
    sql = " ".join(statements)
    for word in ("INSERT", "UPDATE ", "DELETE", "DROP TABLE", "DROP COLUMN", "ADD COLUMN", "CREATE "):
        assert word not in sql, word


def test_downgrade_puts_back_the_range_of_0023() -> None:
    sql = " ".join(render("downgrade"))
    assert "CHECK (tier BETWEEN 1 AND 9) NOT VALID" in sql and "VALIDATE CONSTRAINT backfill_tasks_tier_check" in sql
    assert "DELETE" not in sql


def test_the_old_range_is_the_one_0023_wrote_and_the_new_one_covers_every_expansion_tier() -> None:
    assert "tier            SMALLINT    CHECK (tier BETWEEN 1 AND 9)" in ORIGIN.read_text(encoding="utf-8")
    tiers = [int(t) for t in re.findall(r"^\s*tier:\s*(\d+)", CONFIG.read_text(encoding="utf-8"), re.M)]
    assert tiers and max(tiers) <= 30, tiers

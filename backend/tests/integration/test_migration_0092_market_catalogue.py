"""Migration 0092 (the catalogue of markets, plan F9): additive, empty and reversible.

Deploying must change nothing the system does: 0092 adds two tables, one view and the function of one trigger, and one foreign key from
``market_definitions.settle_rule`` to the table of rules; nothing that existed is altered, no row is written (the rules and the keys are
written by ``fbi.market.catalogue.sync``, so the five markets of the pipeline and everything that counts them see what they always saw),
and going back leaves the database as it came. Run on a scratch database at revision 0091, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0092"
RULES = "market.settlement_rules"
OUTCOMES = "market.fixture_outcomes"
RUNS = "market.catalogue_runs"
DEFINITIONS = "market.market_definitions"
OWN = {RULES, OUTCOMES, RUNS}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view the migrations must leave alone (all but their own three)."""
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw', 'audit') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if f"{r[0]}.{r[1]}" not in OWN]


def _triggers(c: psycopg.Connection[Any], table: str) -> set[str]:
    return {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal", (table,)).fetchall()}


def _indexes(c: psycopg.Connection[Any], schema: str, table: str) -> set[str]:
    return {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = %s", (schema, table)).fetchall()}


def _comment(c: psycopg.Connection[Any], name: str) -> str | None:
    row = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
    return None if row is None else row[0]


def test_0092_adds_three_objects_and_one_key_and_nothing_else_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0091")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in OWN)
            before = _shape(c)
            markets_before = c.execute("SELECT key, is_tracked, is_model_enabled FROM market.markets ORDER BY key").fetchall()
            definitions_triggers = _triggers(c, DEFINITIONS)
            definitions_indexes = _indexes(c, "market", "market_definitions")
            old_comment = c.execute("SELECT col_description(%s::regclass, attnum) FROM pg_attribute WHERE attrelid = %s::regclass "
                                    "AND attname = 'settle_rule'", (DEFINITIONS, DEFINITIONS)).fetchone()
        assert len(markets_before) == 5, "the five markets of the pipeline"

        command.upgrade(_cfg(), "0092")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in OWN)
            assert _shape(c) == before, "nothing that existed was changed: not a column more or less, in any table or view"
            assert _triggers(c, DEFINITIONS) == definitions_triggers and _indexes(c, "market", "market_definitions") == definitions_indexes
            assert c.execute("SELECT key, is_tracked, is_model_enabled FROM market.markets ORDER BY key").fetchall() == markets_before, (
                "the migration writes no key: the code does, and a key in the catalogue is not a market that is followed")
            for name in (RULES, RUNS):
                assert c.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,), "and no rule, no matrix"
            assert c.execute(f"SELECT count(*) FROM {OUTCOMES}").fetchone() == (0,)
            fks = [r[0] for r in c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND "
                                           "conname = 'market_definitions_settle_rule_fk'", (DEFINITIONS,)).fetchall()]
            assert fks == ["FOREIGN KEY (settle_rule) REFERENCES market.settlement_rules(rule_key)"], "a definition names a rule that exists"
            assert _triggers(c, RULES) == {"settlement_rules_immutable"}, "a rule is never edited or deleted: a new convention is a new version"
            assert _indexes(c, "market", "catalogue_runs") >= {"catalogue_runs_pkey"}
            for name in OWN:
                assert _comment(c, name), f"{name} says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0092",)

        command.downgrade(_cfg(), "0091")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in OWN)
            assert _shape(c) == before and _triggers(c, DEFINITIONS) == definitions_triggers
            assert c.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'market_definitions_settle_rule_fk'").fetchone() == (0,)
            assert c.execute("SELECT col_description(%s::regclass, attnum) FROM pg_attribute WHERE attrelid = %s::regclass "
                             "AND attname = 'settle_rule'", (DEFINITIONS, DEFINITIONS)).fetchone() == old_comment, "and the comment it had"
            assert c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'refuse_rule_change'").fetchone() == (0,)

        command.upgrade(_cfg(), "0092")  # and applies again
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in OWN)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()

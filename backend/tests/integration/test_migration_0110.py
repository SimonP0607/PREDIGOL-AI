"""Migration 0110 (Plan Maestro IA, Phase 0) on a database that already holds the ledger: what was written stays, what is
new defaults safely, the rules of the new tables hold, the downgrade undoes it - and on a live database it never waits for
a lock while holding others (the lesson of 0076)."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0110"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), revision)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


BATCH_USAGE = ("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, batch_id, custom_id) "
               "VALUES (%s, 'pick_review', 'analysis', 'anthropic', 'claude-sonnet-5-5', 0.02, 'ok', %s, 'task_a')")


def _columns(c: psycopg.Connection, table: str) -> set[str]:
    rows = c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'ai' AND table_name = %s",
                     (table,)).fetchall()
    return {r[0] for r in rows}


USAGE_INSERT = ("INSERT INTO ai.usage (at, purpose, tier, provider, model, input_tokens, output_tokens, cost_usd, status) "
                "VALUES (%s, %s, %s, %s, %s, 1000, 100, %s, 'ok')")


def test_0110_keeps_what_was_written_defaults_the_new_and_enforces_its_rules() -> None:
    with scratch_at("0093") as dsn:
        with psycopg.connect(dsn) as c:
            c.execute(USAGE_INSERT, ("2026-10-20 10:00+00", "pick_review", "analysis", "anthropic", "claude-sonnet-5-5", "0.05"))
            c.execute(USAGE_INSERT, ("2026-10-20 10:01+00", "web_search", "search", "exa", "exa-auto", "0.015"))
            c.execute("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
                      "VALUES ('2026-10-01', 50, now(), 90, 180)")
        command.upgrade(_cfg(), "0110")
        with psycopg.connect(dsn) as c:
            assert {"cache_write_tokens", "cache_write_1h_tokens", "cache_ttl", "thinking_tokens", "batch_id",
                    "custom_id", "workspace", "key_label", "run_id", "agent"} <= _columns(c, "usage")
            old = c.execute("SELECT cache_write_tokens, workspace, batch_id, scope FROM ai.usage_scoped "
                            "ORDER BY id").fetchall()
            assert old == [(None, None, None, "production"), (None, None, None, "exa")], \
                "rows written before keep NULL; the scope is derived: searches are Exa's money, the rest production's"
            assert c.execute("SELECT scope, kind FROM ai.budget_alerts").fetchall() == [("production", "month")], \
                "the alert the earlier code wrote takes the defaults"
            # the scope of a call made with the LAB workspace's key
            assert c.execute("SELECT ai.scope_of('analysis', 'PREDIGOL-LAB'), ai.scope_of('analysis', 'PREDIGOL'), "
                             "ai.scope_of('search', 'PREDIGOL-LAB'), ai.scope_of('bulk', NULL)").fetchone() \
                == ("lab", "production", "exa", "production")

            # the new unique key: the same threshold may alert once per scope and kind, never twice for the same
            insert = ("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd, scope, kind) "
                      "VALUES ('2026-10-01', 95, now(), 100, 190, %s, %s)")
            for scope, kind in (("production", "month"), ("lab", "month"), ("exa", "month"), ("production", "projection")):
                c.execute(insert, (scope, kind))
            c.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(insert, ("lab", "month"))
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(insert, ("production", "weekly"))
            c.rollback()

            # a Batch result is recorded once; an open task exists once
            c.execute("INSERT INTO ai.batches (batch_ref, provider, workspace, key_label, kind, status, created_at, n_items) "
                      "VALUES ('msgbatch_test', 'anthropic', 'PREDIGOL', 'worker-prod', 'production', 'in_progress', now(), 2)")
            batch = c.execute("SELECT id FROM ai.batches").fetchone()
            assert batch is not None
            item = ("INSERT INTO ai.batch_items (batch_id, custom_id, purpose, tier, model, input_hash, status, created_at) "
                    "VALUES (%s, %s, 'pick_review', 'analysis', 'claude-sonnet-5-5', 'h', %s, now())")
            c.execute(item, (batch[0], "task_a", "submitted"))
            c.execute(item, (batch[0], "task_b", "submitted"))
            c.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(item, (batch[0], "task_a", "submitting"))  # same task, same batch
            c.rollback()
            c.execute("INSERT INTO ai.batches (batch_ref, provider, workspace, key_label, kind, status, created_at, n_items) "
                      "VALUES ('msgbatch_test2', 'anthropic', 'PREDIGOL', 'worker-prod', 'production', 'in_progress', now(), 1)")
            other = c.execute("SELECT id FROM ai.batches WHERE batch_ref = 'msgbatch_test2'").fetchone()
            assert other is not None
            c.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(item, (other[0], "task_a", "submitted"))  # the same task open in another batch: refused
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(item, (other[0], "not a valid id!", "submitted"))
            c.rollback()
            c.execute(BATCH_USAGE, ("2026-10-21 10:00+00", batch[0]))
            c.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(BATCH_USAGE, ("2026-10-21 10:05+00", batch[0]))  # the same result recorded twice
            c.rollback()
            # a write for one hour cannot exceed all the written tokens
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, cache_write_tokens, "
                          "cache_write_1h_tokens) VALUES (now(), 'other', 'bulk', 'anthropic', 'm', 0, 'ok', 100, 200)")
            c.rollback()

            # the evidence of a gate and the limit hits are append-only
            c.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
                      "VALUES ('batch', now(), true, '{}'::jsonb, repeat('a', 64), 'script')")
            c.commit()
            with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                c.execute("UPDATE ai.feature_gates SET passed = false")
            c.rollback()
            c.execute("INSERT INTO ai.limit_hits (at, provider, workspace, kind, http_status) "
                      "VALUES (now(), 'anthropic', 'PREDIGOL-LAB', 'workspace_limit', 400)")
            c.commit()
            with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                c.execute("DELETE FROM ai.limit_hits")
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
                          "VALUES ('something-else', now(), true, '{}'::jsonb, repeat('a', 64), 'script')")
            c.rollback()

        # the downgrade undoes it: the old key is back, the new tables are gone, the ledger keeps its rows
        command.downgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM ai.usage").fetchone() == (3,), "every cost the ledger had stays"
            assert "batch_id" not in _columns(c, "usage") and "scope" not in _columns(c, "budget_alerts")
            assert c.execute("SELECT to_regclass('ai.batches'), to_regclass('ai.feature_gates'), "
                             "to_regclass('ai.usage_scoped')").fetchone() == (None, None, None)
            assert c.execute("SELECT count(*) FROM ai.budget_alerts").fetchone() == (2,), \
                "the month's alerts of production stay (50 and 95); the lab, exa and projection ones go with their scope"
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
                          "VALUES ('2026-10-01', 50, now(), 91, 180)")
            c.rollback()
        command.upgrade(_cfg(), "0110")  # and up again
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0110",)


def test_0110_never_waits_for_a_lock_while_holding_others() -> None:
    with scratch_at("0093") as dsn:
        holder = psycopg.connect(dsn)  # the notifier, or a report: a long transaction that has read the ledger
        holder.execute("LOCK TABLE ai.usage IN ACCESS SHARE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                command.upgrade(_cfg(), "0110")
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate)
        worker.start()
        time.sleep(2)  # the migration now waits for its lock on the ledger
        with psycopg.connect(dsn) as writer:  # the worker's writes go on meanwhile (they take ROW EXCLUSIVE)
            writer.execute("SET lock_timeout = '2s'")
            writer.execute("LOCK TABLE core.fixtures IN ROW EXCLUSIVE MODE")
            writer.execute("LOCK TABLE picks.picks IN ROW EXCLUSIVE MODE")
            writer.execute("LOCK TABLE ai.pick_reviews IN ROW EXCLUSIVE MODE")
            writer.rollback()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and "lock timeout" in str(failure[0]).lower(), failure
        assert time.monotonic() - started < 40
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0093",)
            assert c.execute("SELECT to_regclass('ai.batches')").fetchone() == (None,), "nothing half done"
            assert "batch_id" not in _columns(c, "usage")
        command.upgrade(_cfg(), "0110")  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0110",)

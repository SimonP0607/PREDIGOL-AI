"""Migration 0111 (Plan Maestro IA, phase 1) on a database that already holds what the worker has written: nothing written is lost,
the new tables and the row policy of the promotions work, the downgrade undoes it - and refuses to destroy a decision of the owner -,
the upgrade never waits for a lock while holding others, and a dump of the result restores the way the VPS restores it (without
owners, without privileges, in parallel) into a cluster that does not have the role the policy names.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from tests.integration.agent_tables import (
    HASH,
    insert,
    match_values,
    run_values,
    shaped,
    task_values,
)
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, Seed, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0111"
RESTORED = "fbi_test_m0111_restored"
SEED = cast(Seed, SimpleNamespace(fixture_id=777))  # the new tables hold no foreign key to the fixtures: only the id is read


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop(SCRATCH)
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
        _drop(SCRATCH)


PROMOTION = ("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, "
             "reason, decided_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
# what the worker and the owner have written in the table since 0076: four kinds of entity, none of them an agent
WRITTEN: list[tuple[Any, ...]] = [
    ("2026-10-01 09:00+00", "calibrator", "1X2", "isotonic-v3", 7, None, "CHALLENGER", "cal-gate-v1", {"n": 412}, "fitted by the weekly job", "system"),
    ("2026-10-08 09:00+00", "calibrator", "1X2", "isotonic-v3", 7, "CHALLENGER", "CHAMPION", "cal-gate-v1", {"brier": 0.19},
     "beat the champion on 300 matches", "owner"),
    ("2026-10-09 09:00+00", "market_edge", "OU", "edge-gate-v1", None, None, "VALIDATED", "edge-gate-v1", {"roi": 0.04},
     "the edge holds out of sample", "system"),
    ("2026-10-10 09:00+00", "selection_rule", "BTTS", "sel-v2", None, "CHAMPION", "RETIRED", "sel-gate-v1", {}, "the rule stopped selling", "owner"),
    ("2026-10-11 09:00+00", "model", None, "poisson-v4", None, None, "REJECTED", "model-gate-v1", {"logloss": 1.05}, "worse than the baseline", "system"),
]


def write(c: psycopg.Connection[Any], row: tuple[Any, ...]) -> None:
    c.execute(PROMOTION, (*row[:8], Jsonb(row[8]), *row[9:]))


def agent_row(model: str = "council@council-v1", *, family: str = "1X2", at: str = "2026-10-26 12:00+00", from_role: str | None = None,
              to_role: str = "CHAMPION", by: str = "owner") -> tuple[Any, ...]:
    """A promotion of an agent as the plan's section 25 draws it."""
    return (at, "agent", family, model, None, from_role, to_role, "ma-gate-v1", {"report_hash": HASH},
            "the owner signs the report of the gate after reading it", by)


def promotions(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT * FROM intel.promotions ORDER BY id").fetchall()


def new_tables(c: psycopg.Connection[Any]) -> tuple[Any, ...]:
    row = c.execute("SELECT to_regclass('ai.agent_tasks'), to_regclass('ai.agent_runs'), to_regclass('ai.match_runs'), "
                    "to_regclass('ai.match_state'), to_regprocedure('intel.agent_champion(text)'), "
                    "to_regprocedure('ai.agent_tasks_guard()'), to_regprocedure('ai.candidates_ok(text[])')").fetchone()
    assert row is not None
    return row


def row_security(c: psycopg.Connection[Any]) -> tuple[bool, list[str]]:
    enabled = c.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'intel.promotions'::regclass").fetchone()
    assert enabled is not None
    names = c.execute("SELECT policyname FROM pg_policies WHERE schemaname = 'intel' AND tablename = 'promotions' ORDER BY 1").fetchall()
    return bool(enabled[0]), [n[0] for n in names]


def fill_the_new_tables(c: psycopg.Connection[Any]) -> None:
    run = insert(c, "ai.agent_runs", run_values(SEED, 1))
    insert(c, "ai.agent_tasks", task_values(SEED, 1, **shaped("done", run)))
    insert(c, "ai.match_runs", match_values(SEED))


def test_0111_keeps_what_was_written_admits_the_agent_and_is_undone_without_destroying_a_decision() -> None:
    with scratch_at("0110") as dsn:
        with psycopg.connect(dsn) as c:
            for row in WRITTEN:
                write(c, row)
            c.commit()
            before = promotions(c)
            assert len(before) == len(WRITTEN)
            with pytest.raises(psycopg.errors.CheckViolation, match="promotions_entity_check"):
                write(c, agent_row())  # 0110 knows no agent
            c.rollback()
            assert new_tables(c) == (None,) * 7
            assert row_security(c) == (False, [])

        command.upgrade(_cfg(), "0111")
        with psycopg.connect(dsn) as c:
            assert promotions(c) == before, "every promotion written before is as it was: same ids, same content"
            assert all(n is not None for n in new_tables(c))
            assert row_security(c) == (True, ["promotions_change", "promotions_read", "promotions_remove", "promotions_write"])
            for table in ("agent_tasks", "agent_runs", "match_runs"):
                assert c.execute(f"SELECT count(*) FROM ai.{table}").fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM ai.match_state").fetchone() == (0,)
            write(c, WRITTEN[0])  # the old code goes on writing what it wrote
            write(c, agent_row())  # and the owner can sign an agent
            fill_the_new_tables(c)
            c.commit()
            with pytest.raises(psycopg.errors.CheckViolation, match="promotions_agent_shape"):
                write(c, agent_row("Council@council-v1", at="2026-10-27 12:00+00"))
            c.rollback()
            assert c.execute("SELECT model_name FROM intel.agent_champion('1X2')").fetchall() == [("council@council-v1",)]

        # the owner's decision stays: the downgrade refuses and has changed nothing
        with pytest.raises(DBAPIError, match="0111 cannot be downgraded"):
            command.downgrade(_cfg(), "0110")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0111",)
            assert all(n is not None for n in new_tables(c)), "nothing half done"
            assert row_security(c)[0] is True
            assert c.execute("SELECT count(*) FROM intel.promotions WHERE entity = 'agent'").fetchone() == (1,)
            assert c.execute("SELECT count(*) FROM ai.agent_tasks").fetchone() == (1,)
            # the owner repairs by hand (the table is append-only; the repair is a maintenance act, in one transaction)
            c.execute("SET LOCAL fbi.intel_maintenance = 'on'")
            c.execute("DELETE FROM intel.promotions WHERE entity = 'agent'")
            c.commit()
            kept = promotions(c)

        command.downgrade(_cfg(), "0110")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0110",)
            assert new_tables(c) == (None,) * 7, "the tables, the view and the functions go"
            assert row_security(c) == (False, [])
            assert promotions(c) == kept, "the promotions of the other entities stay"
            with pytest.raises(psycopg.errors.CheckViolation, match="promotions_entity_check"):
                write(c, agent_row())
            c.rollback()
            assert c.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'promotions_agent_shape'").fetchone() == (0,)

        command.upgrade(_cfg(), "0111")  # and up again, as new
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0111",)
            assert c.execute("SELECT count(*) FROM ai.agent_tasks").fetchone() == (0,)
            assert promotions(c) == kept


def test_0111_never_waits_for_a_lock_while_holding_others() -> None:
    with scratch_at("0110") as dsn:
        holder = psycopg.connect(dsn)  # the worker, reading the roles of the calibrators in a long transaction
        holder.execute("LOCK TABLE intel.promotions IN ACCESS SHARE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                command.upgrade(_cfg(), "0111")
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate)
        worker.start()
        time.sleep(2)  # the migration now waits for its lock on the promotions
        with psycopg.connect(dsn) as writer:  # the writes of the worker go on meanwhile: the migration holds nothing else
            writer.execute("SET lock_timeout = '2s'")
            for table in ("core.fixtures", "picks.picks", "ai.pick_reviews", "ai.match_briefs", "ai.match_packets", "ai.usage"):
                writer.execute(f"LOCK TABLE {table} IN ROW EXCLUSIVE MODE")
            writer.rollback()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and "lock timeout" in str(failure[0]).lower(), failure
        assert time.monotonic() - started < 40
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0110",)
            assert new_tables(c) == (None,) * 7, "nothing half done"
            assert row_security(c) == (False, [])
        command.upgrade(_cfg(), "0111")  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0111",)
            assert all(n is not None for n in new_tables(c))


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} is not installed")
    return found


def catalogue(c: psycopg.Connection[Any]) -> dict[str, Any]:
    """What the migration leaves in the catalogue, in a form that two databases can be compared by."""
    policies = c.execute("SELECT policyname, permissive, roles::text, cmd, qual, with_check FROM pg_policies "
                         "WHERE schemaname = 'intel' AND tablename = 'promotions' ORDER BY 1").fetchall()
    constraints = c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN "
                            "('intel.promotions'::regclass, 'ai.agent_tasks'::regclass, 'ai.agent_runs'::regclass, 'ai.match_runs'::regclass) "
                            "ORDER BY 1, 2").fetchall()
    functions = c.execute("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname IN ('agent_champion', 'agent_tasks_guard', 'candidates_ok') "
                          "ORDER BY proname").fetchall()
    view = c.execute("SELECT pg_get_viewdef('ai.match_state'::regclass)").fetchone()
    triggers = c.execute("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid IN "
                         "('ai.agent_tasks'::regclass, 'ai.agent_runs'::regclass, 'ai.match_runs'::regclass) AND NOT tgisinternal ORDER BY 1").fetchall()
    return {"policies": policies, "row_security": row_security(c), "constraints": constraints, "functions": functions, "view": view,
            "triggers": triggers}


def test_0111_comes_back_from_a_dump_the_way_the_vps_restores_one(tmp_path: Path) -> None:
    """``pg_restore --no-owner --no-privileges --jobs=2`` (deploy/vps/bin/restore-test.sh) into a database of a cluster where the role
    of the policy does not exist: every object of 0111 is created, and it behaves."""
    with scratch_at("0111") as dsn:
        with psycopg.connect(dsn) as c:
            for row in WRITTEN:
                write(c, row)
            write(c, agent_row())  # a champion of 1X2 that the system then demotes ...
            write(c, agent_row(at="2026-10-27 12:00+00", from_role="CHAMPION", to_role="RETIRED", by="system"))
            write(c, agent_row("match@match-v1", family="OU", at="2026-10-28 12:00+00"))  # ... and one that stays
            fill_the_new_tables(c)
            c.commit()
            source = catalogue(c)
            source_rows = promotions(c)
            source_champions = [c.execute("SELECT model_name FROM intel.agent_champion(%s)", (family,)).fetchall() for family in ("1X2", "OU", "DC")]
            source_state = c.execute("SELECT fixture_id, pass_kind, state_version FROM ai.match_state").fetchall()
        assert source_champions == [[], [("match@match-v1",)], []]
        assert source_state == [(777, "first", "ms-v1")]

        dump = tmp_path / "m0111.dump"
        made = subprocess.run([tool("pg_dump"), "--format=custom", "--compress=6", f"--file={dump}", dsn], capture_output=True, text=True, check=False)
        assert made.returncode == 0, made.stderr

        _drop(RESTORED)
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{RESTORED}"')
        try:
            restored = subprocess.run([tool("pg_restore"), "--no-owner", "--no-privileges", "--jobs=2", f"--dbname={_dsn(RESTORED)}", str(dump)],
                                      capture_output=True, text=True, check=False)
            assert restored.returncode == 0, restored.stderr
            with psycopg.connect(_dsn(RESTORED)) as c:
                assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0111",)
                assert catalogue(c) == source, "the same policies, constraints, functions, view and triggers"
                assert promotions(c) == source_rows
                assert [c.execute("SELECT model_name FROM intel.agent_champion(%s)", (family,)).fetchall() for family in ("1X2", "OU", "DC")] \
                    == source_champions
                assert c.execute("SELECT fixture_id, pass_kind, state_version FROM ai.match_state").fetchall() == source_state
                assert c.execute("SELECT count(*) FROM ai.agent_tasks").fetchone() == (1,)
                with pytest.raises(psycopg.errors.CheckViolation, match="promotions_agent_shape"):
                    write(c, agent_row("Council@council-v1", at="2026-10-29 12:00+00"))
                c.rollback()
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                    c.execute("UPDATE ai.agent_runs SET cost_usd = 0")
                c.rollback()
        finally:
            _drop(RESTORED)

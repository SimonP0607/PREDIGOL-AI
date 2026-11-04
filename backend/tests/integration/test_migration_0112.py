"""Migration 0112 (Plan Maestro IA, phase 1): the ledger of the AI jobs learns the kind ``package``, and nothing else changes.

The upgrade is one CHECK rewritten: what was written is as it was, the kind is accepted, nonsense is still refused, no other rule of the
schema moves, and it never waits for a lock longer than ten seconds. The downgrade puts the old list back without deleting a row: the rows
of the new kind stay, the old list judges only what is written from then on, and a cycle of the new kind left running is closed first so that
the recovery of the code that ran before (one statement over every cycle left running) does not stumble on it.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError

from tests.integration.agent_tables import refuses
from tests.integration.test_migration_0111 import _cfg, scratch_at

pytestmark = pytest.mark.integration

OLD_KINDS = ("analysis", "postmortem", "learning", "evaluation", "day_start", "prepare")
NOON = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
CONSTRAINT = "cycles_kind_check"


def cycle(c: psycopg.Connection[Any], kind: str, *, status: str = "ok", at: datetime = NOON) -> int:
    """A row of the ledger as ``open_cycle`` and ``close_cycle`` leave it: a cycle that ended, or one that is still running."""
    row = c.execute("INSERT INTO ai.cycles (kind, started_at, finished_at, status, mode, budget_state, counts) "
                    "VALUES (%s, %s, %s, %s, 'shadow', 'ok', '{}'::jsonb) RETURNING id",
                    (kind, at, None if status == "running" else at, status)).fetchone()
    assert row is not None
    return int(row[0])


def ledger(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT * FROM ai.cycles ORDER BY id").fetchall()


def kind_check(c: psycopg.Connection[Any]) -> tuple[str, bool]:
    """The definition of the constraint on the kind, and whether it has been validated against the rows."""
    row = c.execute("SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint WHERE conname = %s AND conrelid = 'ai.cycles'::regclass",
                    (CONSTRAINT,)).fetchone()
    assert row is not None
    return row[0], bool(row[1])


def kinds_of(definition: str) -> list[str]:
    """The words a definition of the constraint allows, in order: ``CHECK ((kind = ANY (ARRAY['analysis'::text, ...])))``."""
    return re.findall(r"'([^']*)'::text", definition)


def other_rules(c: psycopg.Connection[Any]) -> list[tuple[str, str, str]]:
    """Every constraint of every table of the AI schema except the one on the kind, and the indexes of the ledger: what must not move."""
    rules = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                      "WHERE connamespace = 'ai'::regnamespace AND NOT (conrelid = 'ai.cycles'::regclass AND conname = %s) ORDER BY 1, 2",
                      (CONSTRAINT,)).fetchall()
    indexes = c.execute("SELECT 'index', indexname, indexdef FROM pg_indexes WHERE schemaname = 'ai' AND tablename = 'cycles' ORDER BY 2").fetchall()
    return [(a, b, d) for a, b, d in [*rules, *indexes]]


def test_0112_keeps_what_was_written_accepts_the_new_kind_and_moves_nothing_else() -> None:
    with scratch_at("0111") as dsn:
        with psycopg.connect(dsn) as c:
            written = [cycle(c, kind) for kind in OLD_KINDS] + [cycle(c, "analysis", status="running"), cycle(c, "prepare", status="failed")]
            c.commit()
            before, rules, (old_def, validated) = ledger(c), other_rules(c), kind_check(c)
            assert len(before) == len(OLD_KINDS) + 2 and validated
            assert kinds_of(old_def) == list(OLD_KINDS) and " OR " not in old_def
            with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                cycle(c, "package")  # 0111 knows no such job

        command.upgrade(_cfg(), "0112")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0112",)
            assert ledger(c) == before, "every cycle written before is as it was: same ids, same content"
            assert [r[0] for r in before] == written
            new_def, validated = kind_check(c)
            assert validated and kinds_of(new_def) == [*OLD_KINDS, "package"] and " OR " not in new_def, new_def
            assert other_rules(c) == rules, "no other constraint, no index of the ledger moved"
            ok = cycle(c, "package")
            assert c.execute("SELECT kind, status FROM ai.cycles WHERE id = %s", (ok,)).fetchone() == ("package", "ok")
            running = cycle(c, "package", status="running")
            assert c.execute("SELECT status, finished_at FROM ai.cycles WHERE id = %s", (running,)).fetchone() == ("running", None)
            for kind in (*OLD_KINDS, "package"):
                cycle(c, kind)  # every kind is accepted, the old ones as before
            for nonsense in ("packages", "Package", "package ", "", "match_runs", "pack"):
                with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                    cycle(c, nonsense)
            with refuses(c, psycopg.errors.CheckViolation):
                cycle(c, "package", status="nonsense")  # the rules about the state of a cycle are as they were
            c.rollback()


def test_0112_downgrade_deletes_no_row_and_the_old_list_judges_only_what_comes_after() -> None:
    with scratch_at("0112") as dsn:
        with psycopg.connect(dsn) as c:
            package = [cycle(c, "package"), cycle(c, "package", status="failed")]
            stuck = cycle(c, "package", status="running")  # a worker killed in the middle of one
            old = cycle(c, "analysis", status="running")  # and one of the other jobs, left running by the same kill
            done = cycle(c, "learning")
            c.commit()
            before = {r[0]: r for r in ledger(c)}

        command.downgrade(_cfg(), "0111")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0111",)
            after = {r[0]: r for r in ledger(c)}
            assert set(after) == set(before), "no row was deleted"
            assert [after[i] for i in (*package, old, done)] == [before[i] for i in (*package, old, done)], "and no other row was changed"
            row = c.execute("SELECT kind, status, started_at, finished_at, error FROM ai.cycles WHERE id = %s", (stuck,)).fetchone()
            assert row == ("package", "failed", NOON, NOON, "interrupted: the schema went back before the cycle finished")
            definition, validated = kind_check(c)
            assert not validated and kinds_of(definition) == list(OLD_KINDS) and " OR " not in definition
            with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                cycle(c, "package")
            cycle(c, "analysis")  # the code that ran before goes on writing what it wrote
            # and its recovery of the cycles a stopped worker left running (one statement over all of them) is not stopped by the rows kept
            closed = c.execute("UPDATE ai.cycles SET status = 'failed', finished_at = %s, error = 'interrupted' WHERE status = 'running' "
                               "AND started_at < %s", (NOON, NOON.replace(year=2027))).rowcount
            assert closed == 1 and c.execute("SELECT status FROM ai.cycles WHERE id = %s", (old,)).fetchone() == ("failed",)
            c.rollback()


def test_0112_goes_down_and_up_again_with_the_rows_of_both_times() -> None:
    with scratch_at("0112") as dsn:
        with psycopg.connect(dsn) as c:
            first = cycle(c, "package")
            c.commit()
        command.downgrade(_cfg(), "0111")
        with psycopg.connect(dsn) as c:
            between = cycle(c, "analysis")
            c.commit()
        command.upgrade(_cfg(), "0112")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0112",)
            assert kind_check(c)[1] is True, "validated again, against every row"
            assert [r[0] for r in ledger(c)] == [first, between]
            cycle(c, "package")
            c.commit()
        command.downgrade(_cfg(), "0111")
        command.upgrade(_cfg(), "0112")  # and again, with a row of the new kind written after the first return
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM ai.cycles WHERE kind = 'package'").fetchone() == (2,)


@pytest.mark.parametrize("direction", ["up", "down"])
def test_0112_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    before, after = ("0111", "0112") if direction == "up" else ("0112", "0111")

    def move() -> None:
        (command.upgrade if direction == "up" else command.downgrade)(_cfg(), after)

    with scratch_at(before) as dsn:
        holder = psycopg.connect(dsn)  # the worker, with a cycle open in a transaction
        holder.execute("LOCK TABLE ai.cycles IN ROW EXCLUSIVE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                move()
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate, daemon=True)  # a migration that waited for ever must fail the test, not hang the run
        worker.start()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and isinstance(failure[0], DBAPIError) and "lock timeout" in str(failure[0]).lower(), failure
        assert 8 < time.monotonic() - started < 40, "it waited for the lock, ten seconds, and then let go"
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (before,)
            definition, validated = kind_check(c)
            assert kinds_of(definition) == ([*OLD_KINDS, "package"] if direction == "down" else list(OLD_KINDS)), "nothing half done"
            assert validated, "and as validated as it was"
        move()  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (after,)
            assert kinds_of(kind_check(c)[0]) == ([*OLD_KINDS, "package"] if direction == "up" else list(OLD_KINDS))


def test_the_head_of_the_chain_is_this_migration_after_0111() -> None:
    """The chain of the revisions: 0112 follows 0111 and nothing in the repository follows it yet (the next phase starts at 0113)."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0112")
    assert revision is not None and revision.down_revision == "0111"
    assert script.get_revision("0111") is not None
    heads = script.get_heads()
    # "or one that came after it" by the chain, not by the number: the UX chain 0095-0106 hangs from 0119
    assert len(heads) == 1, heads
    assert "0112" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads

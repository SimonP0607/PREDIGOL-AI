"""Migration 0127 (Plan Maestro IA, Gate B): the evidence learns ``gate_b`` (the verdict of Gate B) and ``lab_plan`` (the owner's plan of the LAB),
and nothing else changes.

The upgrade is one CHECK rewritten: what was written is as it was, the two words are accepted, nonsense is still refused, no other rule of the
schema moves (the table stays append-only), the words of the database are the words of the code, and it never waits for a lock longer than ten
seconds. The downgrade puts 0116's list back, validated, only while no row of the new words exists; with one it refuses and changes nothing (the
table is append-only: a ledger is evidence).

Its own scratch database (``<FBI_TEST_DB>_m0127``), so it never collides with the other migration tests."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError

from fbi.ai import gate_b, gates
from tests.integration.agent_tables import refuses
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg
from tests.integration.test_migration_0116 import (
    CONSTRAINT,
    NOON,
    evidence,
    gate_check,
    gate_row,
    gates_of,
    other_rules,
)

pytestmark = pytest.mark.integration

GATES_0116 = ("batch", "native_schema", "cache_layout", "gate_a", "battery", "research_v2", "switches")
NEW = ("gate_b", "lab_plan")
SCRATCH = f"{TEST_DB}_m0127"


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
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


def version(c: psycopg.Connection[object]) -> object:
    return c.execute("SELECT version_num FROM alembic_version").fetchone()


def test_0127_keeps_what_was_written_accepts_the_two_words_and_moves_nothing_else() -> None:
    with scratch_at("0126") as dsn:
        with psycopg.connect(dsn) as c:
            written = [gate_row(c, g, passed=i % 2 == 0, at=NOON + timedelta(minutes=i)) for i, g in enumerate(GATES_0116)]
            c.commit()
            before, rules, (old_def, validated) = evidence(c), other_rules(c), gate_check(c)
            assert validated and gates_of(old_def) == list(GATES_0116)
            for word in NEW:
                with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                    gate_row(c, word)  # 0126 knows no such gate: Gate B could not be recorded

        command.upgrade(_cfg(), "0127")
        with psycopg.connect(dsn) as c:
            assert version(c) == ("0127",)
            assert evidence(c) == before and [r[0] for r in before] == written, "every row written before is as it was"
            new_def, validated = gate_check(c)
            assert validated and gates_of(new_def) == [*GATES_0116, *NEW] and " OR " not in new_def, new_def
            assert other_rules(c) == rules, "no other constraint, no index and no trigger of the evidence moved"
            row = gate_row(c, "gate_b", passed=False, evidence={"gate": "gate_b", "verdict": "NO PASA"})
            gate_row(c, "lab_plan", decided_by="owner", evidence={"kind": "lab-plan-v1", "planned_excluded_days": 2, "reason": "x"})
            assert c.execute("SELECT gate, passed, decided_by FROM ai.feature_gates WHERE id = %s", (row,)).fetchone() == ("gate_b", False, "script")
            for nonsense in ("gate_B", "gateb", "gate_c", "lab-plan", "labplan", "lab_plan ", "", "LAB_PLAN"):
                with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                    gate_row(c, nonsense)
            with refuses(c, psycopg.errors.CheckViolation):
                gate_row(c, "lab_plan", decided_by="somebody")  # who may decide is as it was
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("UPDATE ai.feature_gates SET passed = true WHERE id = %s", (row,))  # a verdict is never rewritten
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("DELETE FROM ai.feature_gates WHERE id = %s", (row,))
            c.rollback()


def test_0127_the_words_of_the_database_are_the_words_of_the_code() -> None:
    """A gate added to ``gates.GATES`` without a migration, or the other way round, fails here instead of failing on the day it is first
    recorded."""
    with scratch_at("0127") as dsn, psycopg.connect(dsn) as c:
        assert gates_of(gate_check(c)[0]) == list(gates.GATES)
        assert gate_b.GATE in gates.GATES and gate_b.LAB_PLAN in gates.GATES
        for gate in gates.GATES:
            gate_row(c, gate)
        c.rollback()


def test_0127_goes_down_while_no_row_of_the_new_words_exists_and_up_again() -> None:
    with scratch_at("0127") as dsn:
        with psycopg.connect(dsn) as c:
            kept = [gate_row(c, "gate_a"), gate_row(c, "switches", at=NOON + timedelta(minutes=1))]
            c.commit()
            before = evidence(c)

        command.downgrade(_cfg(), "0126")
        with psycopg.connect(dsn) as c:
            assert version(c) == ("0126",)
            assert evidence(c) == before and [r[0] for r in before] == kept, "no row was deleted and none was changed"
            definition, validated = gate_check(c)
            assert validated and gates_of(definition) == list(GATES_0116), "0116's list, validated against every row"
            for word in NEW:
                with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                    gate_row(c, word)
            for gate in GATES_0116:
                gate_row(c, gate, at=NOON + timedelta(days=1))  # the code that ran before goes on writing what it wrote
            c.commit()

        command.upgrade(_cfg(), "0127")
        with psycopg.connect(dsn) as c:
            assert version(c) == ("0127",) and gate_check(c)[1] is True
            assert len(evidence(c)) == len(kept) + len(GATES_0116)
            gate_row(c, "gate_b", at=NOON + timedelta(days=2))
            c.commit()


@pytest.mark.parametrize("word", NEW)
def test_0127_downgrade_refuses_with_a_row_of_a_new_word_and_changes_nothing(word: str) -> None:
    with scratch_at("0127") as dsn:
        with psycopg.connect(dsn) as c:
            gate_row(c, "gate_a")
            gate_row(c, word, decided_by="owner" if word == "lab_plan" else "script", at=NOON + timedelta(minutes=1))
            c.commit()
            before, (definition, _) = evidence(c), gate_check(c)

        with pytest.raises(DBAPIError, match="the code goes back, the list stays"):
            command.downgrade(_cfg(), "0126")
        with psycopg.connect(dsn) as c:
            assert version(c) == ("0127",), "the revision did not move"
            assert evidence(c) == before, "and no row was touched: the ledger is evidence"
            assert gate_check(c) == (definition, True) and gates_of(definition) == [*GATES_0116, *NEW]


@pytest.mark.parametrize("direction", ["up", "down"])
def test_0127_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    before, after = ("0126", "0127") if direction == "up" else ("0127", "0126")

    def move() -> None:
        (command.upgrade if direction == "up" else command.downgrade)(_cfg(), after)

    with scratch_at(before) as dsn:
        holder = psycopg.connect(dsn)  # a script recording a gate, with its transaction open
        holder.execute("LOCK TABLE ai.feature_gates IN ROW EXCLUSIVE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                move()
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate, daemon=True)
        worker.start()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and isinstance(failure[0], DBAPIError) and "lock timeout" in str(failure[0]).lower(), failure
        assert 8 < time.monotonic() - started < 40, "it waited for the lock, ten seconds, and then let go"
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert version(c) == (before,)
            assert gates_of(gate_check(c)[0]) == ([*GATES_0116, *NEW] if direction == "down" else list(GATES_0116)), "nothing half done"
        move()
        with psycopg.connect(dsn) as c:
            assert version(c) == (after,)


def test_the_chain_of_the_revisions_has_this_migration_after_0126_and_one_head() -> None:
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0127")
    assert revision is not None and revision.down_revision == "0126" and re.fullmatch(r"\d{4}", revision.revision)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert "0127" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads

"""Migration 0113 (Plan Maestro IA, phase 1): the evidence of the optimisations learns the gate ``battery``, and nothing else changes.

The upgrade is one CHECK rewritten: what was written is as it was, the gate is accepted, nonsense is still refused, no other rule of the
schema moves (the table stays append-only), the words of the database are the words of the code, and it never waits for a lock longer than
ten seconds. The downgrade puts the old list back without deleting a row: the evidence of the new gate stays (a measurement is evidence), the
old list judges only what is written from then on, and the code that ran before goes on reading the gates it knows.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from fbi.ai import gates
from tests.integration.agent_tables import refuses
from tests.integration.test_migration_0111 import _cfg, scratch_at

pytestmark = pytest.mark.integration

OLD_GATES = ("batch", "native_schema", "cache_layout", "gate_a")
NOON = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
CONSTRAINT = "feature_gates_gate_check"


def gate_row(c: psycopg.Connection[Any], gate: str, *, passed: bool = True, at: datetime = NOON, decided_by: str = "script",
             evidence: dict[str, Any] | None = None, digest: str | None = None) -> int:
    """A row of the evidence as ``gates.record_gate`` writes it."""
    evidence = {"note": f"evidence of {gate}"} if evidence is None else evidence
    digest = digest if digest is not None else hashlib.sha256(json.dumps([gate, passed, at.isoformat(), evidence], sort_keys=True).encode()).hexdigest()
    row = c.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by, code_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'test') RETURNING id", (gate, at, passed, Jsonb(evidence), digest, decided_by)).fetchone()
    assert row is not None
    return int(row[0])


def evidence(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT * FROM ai.feature_gates ORDER BY id").fetchall()


def gate_check(c: psycopg.Connection[Any]) -> tuple[str, bool]:
    """The definition of the constraint on the gate, and whether it has been validated against the rows."""
    row = c.execute("SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint WHERE conname = %s AND conrelid = 'ai.feature_gates'::regclass",
                    (CONSTRAINT,)).fetchone()
    assert row is not None
    return row[0], bool(row[1])


def gates_of(definition: str) -> list[str]:
    """The words a definition of the constraint allows, in order: ``CHECK ((gate = ANY (ARRAY['batch'::text, ...])))``."""
    return re.findall(r"'([^']*)'::text", definition)


def other_rules(c: psycopg.Connection[Any]) -> list[tuple[str, str, str]]:
    """Every constraint of every table of the AI schema except the one on the gate, and the indexes and triggers of the evidence: what must
    not move."""
    rules = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                      "WHERE connamespace = 'ai'::regnamespace AND NOT (conrelid = 'ai.feature_gates'::regclass AND conname = %s) ORDER BY 1, 2",
                      (CONSTRAINT,)).fetchall()
    indexes = c.execute("SELECT 'index', indexname, indexdef FROM pg_indexes WHERE schemaname = 'ai' AND tablename = 'feature_gates' ORDER BY 2").fetchall()
    triggers = c.execute("SELECT 'trigger', tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                         "WHERE tgrelid = 'ai.feature_gates'::regclass AND NOT tgisinternal ORDER BY 2").fetchall()
    assert triggers, "the evidence is append-only: there must be a trigger to keep"
    return [(a, b, d) for a, b, d in [*rules, *indexes, *triggers]]


def test_0113_keeps_what_was_written_accepts_the_new_gate_and_moves_nothing_else() -> None:
    with scratch_at("0112") as dsn:
        with psycopg.connect(dsn) as c:
            written = [gate_row(c, g, passed=i % 2 == 0, at=NOON + timedelta(minutes=i)) for i, g in enumerate(OLD_GATES)]
            written.append(gate_row(c, "gate_a", passed=False, at=NOON + timedelta(hours=1), decided_by="owner"))
            c.commit()
            before, rules, (old_def, validated) = evidence(c), other_rules(c), gate_check(c)
            assert len(before) == len(OLD_GATES) + 1 and validated
            assert gates_of(old_def) == list(OLD_GATES) and " OR " not in old_def
            with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                gate_row(c, "battery")  # 0112 knows no such gate

        command.upgrade(_cfg(), "0113")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0113",)
            assert evidence(c) == before, "every row written before is as it was: same ids, same content"
            assert [r[0] for r in before] == written
            new_def, validated = gate_check(c)
            assert validated and gates_of(new_def) == [*OLD_GATES, "battery"] and " OR " not in new_def, new_def
            assert other_rules(c) == rules, "no other constraint, no index and no trigger of the evidence moved"
            ok = gate_row(c, "battery", passed=False, evidence={"battery": "battery-v1", "verdict": "NO PASA"})
            assert c.execute("SELECT gate, passed, decided_by FROM ai.feature_gates WHERE id = %s", (ok,)).fetchone() == ("battery", False, "script")
            for gate in (*OLD_GATES, "battery"):
                gate_row(c, gate, at=NOON + timedelta(days=1))  # every gate is accepted, the old ones as before
            for nonsense in ("batteries", "Battery", "battery ", "", "gate_b", "adversarial", "BATTERY"):
                with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                    gate_row(c, nonsense)
            with refuses(c, psycopg.errors.CheckViolation):
                gate_row(c, "battery", decided_by="somebody")  # who may decide is as it was
            with refuses(c, psycopg.errors.CheckViolation):
                gate_row(c, "battery", digest="not a digest")  # and so is the shape of the digest
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("UPDATE ai.feature_gates SET passed = true WHERE id = %s", (ok,))  # a measurement is never rewritten
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("DELETE FROM ai.feature_gates WHERE id = %s", (ok,))
            c.rollback()


def test_0113_leaves_the_five_words_of_its_time_and_the_code_still_knows_them() -> None:
    """The words of the database at 0113. That the database and ``gates.GATES`` agree is held at the head (``test_migration_0115``): the list
    of the code grows with every phase, this one is what 0113 left."""
    with scratch_at("0113") as dsn, psycopg.connect(dsn) as c:
        assert gates_of(gate_check(c)[0]) == [*OLD_GATES, "battery"]
        assert set(gates.GATES) >= {*OLD_GATES, "battery"}, "the code never forgets a gate it once wrote"
        for gate in (*OLD_GATES, "battery"):
            gate_row(c, gate)
        c.rollback()


def test_0113_downgrade_deletes_no_row_and_the_old_list_judges_only_what_comes_after() -> None:
    with scratch_at("0113") as dsn:
        with psycopg.connect(dsn) as c:
            kept = [gate_row(c, "gate_a", at=NOON), gate_row(c, "battery", passed=True, at=NOON + timedelta(minutes=1)),
                    gate_row(c, "battery", passed=False, at=NOON + timedelta(minutes=2), evidence={"battery": "battery-v1", "verdict": "NO PASA"}),
                    gate_row(c, "batch", at=NOON + timedelta(minutes=3))]
            c.commit()
            before = evidence(c)

        command.downgrade(_cfg(), "0112")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0112",)
            assert evidence(c) == before, "no row was deleted and none was changed"
            assert [r[0] for r in before] == kept
            definition, validated = gate_check(c)
            assert not validated and gates_of(definition) == list(OLD_GATES) and " OR " not in definition
            with refuses(c, psycopg.errors.CheckViolation, constraint=CONSTRAINT):
                gate_row(c, "battery")
            for gate in OLD_GATES:
                gate_row(c, gate, at=NOON + timedelta(days=1))  # the code that ran before goes on writing what it wrote
            newest = c.execute(gates.STATE_SQL, ("gate_a",)).fetchone()
            assert newest is not None and newest[0] == NOON + timedelta(days=1), "and reading it: the newest row of its gate decides"
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("DELETE FROM ai.feature_gates WHERE gate = 'battery'")  # the evidence of the new gate cannot be removed by the old schema either
            c.rollback()


def test_0113_goes_down_and_up_again_with_the_rows_of_both_times() -> None:
    with scratch_at("0113") as dsn:
        with psycopg.connect(dsn) as c:
            first = gate_row(c, "battery", passed=True)
            c.commit()
        command.downgrade(_cfg(), "0112")
        with psycopg.connect(dsn) as c:
            between = gate_row(c, "batch", at=NOON + timedelta(hours=1))
            c.commit()
        command.upgrade(_cfg(), "0113")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0113",)
            assert gate_check(c)[1] is True, "validated again, against every row"
            assert [r[0] for r in evidence(c)] == [first, between]
            gate_row(c, "battery", passed=False, at=NOON + timedelta(hours=2))
            c.commit()
        command.downgrade(_cfg(), "0112")
        command.upgrade(_cfg(), "0113")  # and again, with a row of the new gate written after the first return
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'battery'").fetchone() == (2,)


@pytest.mark.parametrize("direction", ["up", "down"])
def test_0113_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    before, after = ("0112", "0113") if direction == "up" else ("0113", "0112")

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
            definition, validated = gate_check(c)
            assert gates_of(definition) == ([*OLD_GATES, "battery"] if direction == "down" else list(OLD_GATES)), "nothing half done"
            assert validated, "and as validated as it was"
        move()  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (after,)
            assert gates_of(gate_check(c)[0]) == ([*OLD_GATES, "battery"] if direction == "up" else list(OLD_GATES))


def test_the_chain_of_the_revisions_has_this_migration_after_0112() -> None:
    """0113 follows 0112 and nothing in the repository sits between them."""
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0113")
    assert revision is not None and revision.down_revision == "0112"
    heads = script.get_heads()
    # "or one that came after it" by the chain, not by the number: the UX chain 0095-0106 hangs from 0119
    assert len(heads) == 1, heads
    assert "0113" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads
    assert re.fullmatch(r"\d{4}", revision.revision)

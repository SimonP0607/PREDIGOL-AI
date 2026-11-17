"""Migration 0138 (IA-056, AD-003): the registry of capabilities - two append-only tables, the seed of what already runs in shadow, the
database's own refusal of what the rules forbid, and nothing else moves. Its own scratch database (``<FBI_TEST_DB>_m0138``)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Jsonb

from fbi.intel import capabilities as reg
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0138"
TABLES = {"capabilities", "capability_transitions"}
AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
SIGNATURE = "Autorizo esta capacidad, el dueño, 2026-11-20"


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


def schema(c: psycopg.Connection[Any]) -> dict[str, list[Any]]:
    columns = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns WHERE table_schema IN ('intel', 'ai') ORDER BY 1, 2, ordinal_position").fetchall()
    constraints = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE connamespace IN ('intel'::regnamespace, 'ai'::regnamespace) ORDER BY 1, 2").fetchall()
    return {"columns": columns, "constraints": constraints}


def raw_insert(c: psycopg.Connection[Any], *, key: str = "council", previous: int | None, from_state: str | None, to_state: str,
               safety: str = reg.PENDING_ACTIONS, validation: str = reg.PENDING_DEPENDENCIES, sample: int | None = None,
               by: str = "system", signature: str | None = None, safety_evidence: dict[str, Any] | None = None,
               validation_evidence: dict[str, Any] | None = None) -> int:
    """A row written straight to the table, bypassing the code: what the DATABASE alone accepts."""
    row = c.execute(
        "INSERT INTO intel.capability_transitions (capability_key, capability_id, previous_id, at, from_state, to_state, safety, "
        "safety_evidence, validation, validation_evidence, validation_sample, reason, decided_by, owner_signature, evidence_hash) "
        "SELECT %s, id, %s, now(), %s, %s, %s, %s, %s, %s, %s, 'prueba', %s, %s, repeat('0', 64) FROM intel.capabilities "
        "WHERE key = %s AND version = 1 RETURNING id",
        (key, previous, from_state, to_state, safety, Jsonb(safety_evidence or {}), validation, Jsonb(validation_evidence or {}),
         sample, by, signature, key)).fetchone()
    assert row is not None
    return int(row[0])


def tip_id(c: psycopg.Connection[Any], key: str = "council") -> int:
    row = c.execute("SELECT max(id) FROM intel.capability_transitions WHERE capability_key = %s", (key,)).fetchone()
    assert row is not None
    return int(row[0])


def refused(c: psycopg.Connection[Any], **kw: Any) -> str:
    """The name of the constraint (or the error) that refused the row; the transaction is rolled back to before it."""
    c.execute("SAVEPOINT s")
    try:
        raw_insert(c, **kw)
    except psycopg.errors.IntegrityError as exc:
        c.execute("ROLLBACK TO SAVEPOINT s")
        return str(exc.diag.constraint_name or exc.sqlstate)
    raise AssertionError(f"the database took {kw}")


def test_0138_adds_two_append_only_tables_seeds_them_and_goes_down_and_up_again() -> None:
    with scratch_at("0137") as dsn:
        with psycopg.connect(dsn) as c:
            before = schema(c)
        command.upgrade(_cfg(), "0138")
        with psycopg.connect(dsn) as c:
            after = schema(c)
            added = {t for s, t, *_ in after["columns"] if s == "intel"} - {t for s, t, *_ in before["columns"] if s == "intel"}
            assert added == TABLES
            assert [r for r in after["columns"] if r[1] not in TABLES] == before["columns"], "no column of another table moved"
            assert set(before["constraints"]) <= set(after["constraints"]), "no constraint was dropped or rewritten"
            foreign = sorted(d for t, _, d in after["constraints"] if "FOREIGN KEY" in d and t.removeprefix("intel.") in TABLES)
            assert all("REFERENCES intel.capabilit" in d for d in foreign) and len(foreign) == 3
            for table in TABLES:
                assert c.execute(f"SELECT count(*) FROM pg_trigger WHERE tgrelid = 'intel.{table}'::regclass AND NOT tgisinternal "
                                 f"AND tgname = '{table}_append_only'").fetchone() == (1,)
            seeded = c.execute("SELECT c.key, t.to_state, t.safety, t.validation, t.decided_by, t.previous_id FROM intel.capabilities c "
                               "JOIN intel.capability_transitions t ON t.capability_id = c.id ORDER BY c.id").fetchall()
            assert [r[0] for r in seeded] == [cap.key for cap in reg.CATALOG]
            assert {r[1:] for r in seeded} == {("en_sombra", reg.PENDING_ACTIONS, reg.PENDING_DEPENDENCIES, "system", None)}
            hashes = c.execute("SELECT evidence_hash, safety, safety_evidence, validation, validation_evidence, validation_sample, "
                               "reason, observed FROM intel.capability_transitions").fetchall()
            for h, *doc in hashes:
                assert h == reg.evidence_hash(dict(zip(("safety", "safety_evidence", "validation", "validation_evidence",
                                                        "validation_sample", "reason", "observed"), doc, strict=True)))
        command.downgrade(_cfg(), "0137")
        with psycopg.connect(dsn) as c:
            assert schema(c) == before
        command.upgrade(_cfg(), "0138")
        with psycopg.connect(dsn) as c:
            assert schema(c) == after


def test_the_database_refuses_what_the_rules_forbid_and_every_change_of_a_row() -> None:
    with scratch_at("0138") as dsn, psycopg.connect(dsn) as c:
        seed = tip_id(c)
        passed: dict[str, Any] = {"safety": reg.PASS, "safety_evidence": {"gate": "battery"}}
        assert refused(c, previous=seed, from_state="en_sombra", to_state="autorizada", **passed, by="owner",
                       signature=SIGNATURE) == "capability_transitions_no_skip"
        assert refused(c, previous=seed, from_state="en_sombra", to_state="lista_para_revision") == "capability_transitions_review"
        assert refused(c, previous=seed, from_state="en_sombra", to_state="en_sombra", safety=reg.FAIL,
                       safety_evidence={"gate": "battery"}) == "capability_transitions_safety_holds"
        assert refused(c, previous=seed, from_state="en_sombra", to_state="en_sombra",
                       validation=reg.VALIDATED, validation_evidence={"p": 1}) == "capability_transitions_sample"
        assert refused(c, previous=seed, from_state="en_sombra", to_state="en_sombra", safety=reg.PASS) == \
            "capability_transitions_safety_evidence"
        assert refused(c, previous=seed, from_state="en_sombra", to_state="en_sombra", by="owner") == "capability_transitions_signature"
        assert refused(c, previous=seed, from_state="construida", to_state="en_sombra") == "capability_transitions_previous_fk"
        assert refused(c, previous=None, from_state=None, to_state="en_sombra") == "intel_capability_transitions_one_successor"
        assert refused(c, key="readers", previous=seed, from_state="en_sombra", to_state="en_sombra") == \
            "capability_transitions_previous_fk", "a row names a row of its own capability"
        review = raw_insert(c, previous=seed, from_state="en_sombra", to_state="lista_para_revision", **passed,
                            validation=reg.NOT_VALIDATED, sample=40, validation_evidence={"p": 1})
        assert refused(c, previous=seed, from_state="en_sombra", to_state="en_sombra") == "intel_capability_transitions_one_successor"
        assert refused(c, previous=review, from_state="lista_para_revision", to_state="autorizada", **passed) == \
            "capability_transitions_authorised"
        assert refused(c, previous=review, from_state="lista_para_revision", to_state="autorizada", **passed, by="system",
                       signature=SIGNATURE) in ("capability_transitions_authorised", "capability_transitions_signature")
        authorised = raw_insert(c, previous=review, from_state="lista_para_revision", to_state="autorizada", **passed, by="owner",
                                signature=SIGNATURE)
        back = raw_insert(c, previous=authorised, from_state="autorizada", to_state="construida", safety=reg.FAIL,
                          safety_evidence={"gate": "battery", "row": 21})
        assert back > authorised
        for statement in ("UPDATE intel.capability_transitions SET reason = 'x'", "DELETE FROM intel.capability_transitions",
                          "UPDATE intel.capabilities SET title = 'x'", "DELETE FROM intel.capabilities"):
            c.execute("SAVEPOINT s")
            with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                c.execute(statement)
            c.execute("ROLLBACK TO SAVEPOINT s")
        c.rollback()


def test_the_code_records_reads_and_syncs_through_the_rules() -> None:
    with scratch_at("0138") as dsn, psycopg.connect(dsn) as c:
        assert reg.sync_plan(reg.catalog_rows(c)) == [], "the seed is the code catalog"
        with pytest.raises(PermissionError):
            reg.record(c, reg.Proposal("council", reg.AUTHORISED, reg.PASS, reg.VALIDATED, "r", {"g": 1}, {"p": 1}, 300), at=AT)
        with pytest.raises(ValueError, match="no state is skipped"):
            reg.record(c, reg.Proposal("council", reg.AUTHORISED, reg.PASS, reg.VALIDATED, "r", {"g": 1}, {"p": 1}, 300,
                                       decided_by="owner", owner_signature=SIGNATURE), at=AT, confirmed_by_owner=True)
        c.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
                  "VALUES ('battery', now(), false, '{}'::jsonb, repeat('a', 64), 'script')")
        with pytest.raises(ValueError, match="says NO PASA"):
            reg.record(c, reg.Proposal("council", reg.REVIEW, reg.PASS, reg.INSUFFICIENT, "r", {"g": 1}, {"p": 1}, 20), at=AT)
        view = reg.overview(c, at=AT)
        council = next(i for i in view["capabilities"] if i["key"] == "council")
        assert council["live"]["safety_gates"][0]["verdict"] == reg.FAIL and any("NO PASA" in w for w in council["warnings"])
        c.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
                  "VALUES ('battery', now() + interval '1 second', true, '{}'::jsonb, repeat('b', 64), 'script')")
        row = reg.record(c, reg.Proposal("council", reg.REVIEW, reg.PASS, reg.INSUFFICIENT, "r", {"g": 1}, {"p": 1}, 20), at=AT)
        signed = reg.record(c, reg.Proposal("council", reg.AUTHORISED, reg.PASS, reg.INSUFFICIENT, "el dueño autoriza", {"g": 1}, {"p": 1},
                                            20, decided_by="owner", owner_signature=SIGNATURE), at=AT, confirmed_by_owner=True)
        assert signed > row
        view = reg.overview(c, at=AT)
        council = next(i for i in view["capabilities"] if i["key"] == "council")
        assert council["state"] == reg.AUTHORISED and council["signed_by_owner"] and council["transitions"] == 3
        assert council["validation"] == {"verdict": reg.INSUFFICIENT, "sample": 20, "evidence": {"p": 1}}
        assert any("no validada" in w for w in council["warnings"]), "authorised is never shown as validated"
        assert view["by_state"] == {"construida": 0, "en_sombra": 6, "lista_para_revision": 0, "autorizada": 1}
        assert [r["to_state"] for r in reg.history(c, "council")] == ["en_sombra", "lista_para_revision", "autorizada"]
        c.rollback()

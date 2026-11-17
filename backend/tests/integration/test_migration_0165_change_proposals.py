"""Migration 0165 (IA-139, AD-K07): proposals, signatures and applications, append-only, on a scratch database at the revision below it.
The database itself refuses a change that names a probability, a kind whose target does not fit, a proposal without a new version, a
signature of other evidence, a second decision, a signature not in the owner's words, and - the criterion of AD-K07 - an application
without a «firmada» signature of the same proposal. The register (``fbi.proposals.store``) goes through the whole way, back included."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from fbi.proposals import SIGNED, Proposal
from fbi.proposals import store as register
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0165"
BELOW = "0163"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def shape(c: psycopg.Connection[Any]) -> list[Any]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema IN ('ai', 'intel') ORDER BY 1, 2, 3").fetchall()


P = Proposal("umbral", "threshold:fbi.decision.policy.MIN_EV", "decision-v2.1", "decision-v2.2", {"from": 0.03, "to": 0.04, "direction": "raise"},
             {"board": "board-v1", "sample": 412}, ({"table": "intel.selection_evaluations", "from": "2026-11-01"},), "the board supports it")
RAW = ("INSERT INTO ai.change_proposals (version, kind, target, current_version, proposed_version, rollback_to, change, evidence, "
       "evidence_refs, evidence_hash, proposed_by, reason) VALUES ('proposals-v1', %s, %s, 'v1', %s, %s, %s, %s, %s, repeat('b', 64), "
       "'system', 'r')")


def test_0165_adds_three_append_only_tables_that_refuse_an_unsigned_change_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
        command.upgrade(_cfg(), "0165")
        with psycopg.connect(dsn) as c:
            added = {(r[0], r[1]) for r in sorted(set(shape(c)) - set(before))}
            assert added == {("ai", "change_proposals"), ("ai", "change_signatures"), ("ai", "change_applications")}
            pid = register.register(c, P, code_version="test")
            assert pid is not None and register.register(c, P) is None, "the same proposal is registered once"
            c.commit()
            refs = Jsonb([{"table": "x"}])
            for args in (("umbral", "threshold:a", "v2", "v1", Jsonb({"p_model": 0.6}), Jsonb({"n": 1}), refs),   # names a probability
                         ("umbral", "source:a", "v2", "v1", Jsonb({}), Jsonb({"n": 1}), refs),                  # kind and target disagree
                         ("umbral", "threshold:a", "v1", "v1", Jsonb({}), Jsonb({"n": 1}), refs),               # not a new version
                         ("umbral", "threshold:a", "v2", "v0", Jsonb({}), Jsonb({"n": 1}), refs),               # its way back is not kept
                         ("umbral", "threshold:a", "v2", "v1", Jsonb({}), Jsonb({}), refs),                     # without evidence
                         ("train", "threshold:a", "v2", "v1", Jsonb({}), Jsonb({"n": 1}), refs)):               # an unknown kind
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(RAW, args)
                c.rollback()
            sql_sig = "INSERT INTO ai.change_signatures (proposal_id, evidence_hash, decision, signed_by, signature) VALUES (%s, %s, %s, %s, %s)"
            for sig_args, error in (((pid, "0" * 64, "firmada", "owner", "Firmo la subida"), psycopg.errors.ForeignKeyViolation),  # other evidence
                                ((pid, P.hash, "firmada", "system", "Firmo la subida"), psycopg.errors.CheckViolation),     # not the owner
                                ((pid, P.hash, "firmada", "owner", "ok"), psycopg.errors.CheckViolation)):                 # not their words
                with pytest.raises(error):
                    c.execute(sql_sig, sig_args)
                c.rollback()
            sql_app = ("INSERT INTO ai.change_applications (proposal_id, signature_id, decision, kind, version, recorded_by, note) "
                       "VALUES (%s, %s, %s, 'aplicada', 'decision-v2.2', 'owner', 'aplicada a mano')")
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute(sql_app, (pid, 999, "firmada"))  # an application without a signature
            c.rollback()
            with pytest.raises(ValueError, match="not signed"):
                register.record(c, pid, kind="aplicada", note="aplicada sin firma")
            c.rollback()
            with pytest.raises(ValueError, match="evidence"):
                register.sign(c, pid, decision=SIGNED, signature="Firmo la subida, el dueño", seen_hash="1" * 64)
            c.rollback()
            sid = register.sign(c, pid, decision=SIGNED, signature="Firmo la subida, el dueño", seen_hash=P.hash)
            c.commit()
            with pytest.raises(ValueError, match="already"):
                register.sign(c, pid, decision="rechazada", signature="Mejor no, el dueño", seen_hash=P.hash)
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(sql_app, (pid, sid, "rechazada"))
            c.rollback()
            with pytest.raises(ValueError, match="only what was applied"):
                register.record(c, pid, kind="revertida", note="vuelta atrás sin aplicar")
            c.rollback()
            register.record(c, pid, kind="aplicada", note="decision-v2.2 encendida por el dueño")
            register.record(c, pid, kind="revertida", note="vuelta a decision-v2.1 por el dueño")
            c.commit()
            [row] = register.rows(c, proposal_id=pid)
            assert row.status == "revertida" and row.proposal.rollback_to == "decision-v2.1"
            versions = c.execute("SELECT kind, version FROM ai.change_applications ORDER BY id").fetchall()
            assert versions == [("aplicada", "decision-v2.2"), ("revertida", "decision-v2.1")]
            assert register.summary(c) == {"by_status": {"revertida": 1}, "applied_without_signature": 0}
            for t in ("change_proposals", "change_signatures", "change_applications"):
                for sql in (f"UPDATE ai.{t} SET id = id", f"DELETE FROM ai.{t}"):
                    with pytest.raises(psycopg.Error):
                        c.execute(sql)
                    c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before

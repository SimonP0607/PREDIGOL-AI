"""Migration 0162 (IA-126 / IA-127): ``ai.source_credibility``, append-only, and the gate ``extract_protocol`` admitted in
``ai.feature_gates``, on a scratch database at the revision below it; its checks refuse an incoherent row and a second one at the same moment;
the downgrade is refused while the gate has a row, and is clean otherwise."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0162"
BELOW = "0161"


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
                     "WHERE table_schema IN ('intel', 'ai', 'core') ORDER BY 1, 2, 3").fetchall()


ROW = ("INSERT INTO ai.source_credibility (version, digest, as_of, outlet, tier, fact_type, resolved, corroborated, value, basis, prior, "
       "rate, ci_low, ci_high, sufficient, min_resolved, typed) VALUES ('credibility-v2', 'abcdef012345', '2026-11-17 12:00+00', %s, 'C', "
       "%s, %s, %s, %s, %s, 0.6, %s, %s, %s, %s, 30, false)")
GATE = ("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
        "VALUES (%s, now(), false, '{}', repeat('a', 64), 'owner')")


def test_0162_adds_one_append_only_table_admits_the_gate_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(GATE, ("extract_protocol",))
            c.rollback()
        command.upgrade(_cfg(), "0162")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {(r[0], r[1]) for r in added} == {("ai", "source_credibility")}
            c.execute(ROW, ("diario.example", "baja", 40, 30, 0.72, "learned", 0.75, 0.6, 0.86, True))
            c.execute(ROW, ("diario.example", "titularidad", 0, 0, 0.6, "prior", None, None, None, False))
            c.commit()
            for sql in ("UPDATE ai.source_credibility SET value = 0.1", "DELETE FROM ai.source_credibility"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
            for args in (("diario.example", "baja", 40, 30, 0.72, "learned", 0.75, 0.6, 0.86, True),      # the same moment again
                         ("otro.example", "baja", 5, 6, 0.6, "learned", 1.2, 0.5, 0.9, False),            # more hits than resolved
                         ("otro.example", "baja", 0, 0, 0.6, "learned", None, None, None, False),         # learned from nothing
                         ("otro.example", "baja", 10, 5, 0.6, "learned", 0.5, 0.2, 0.8, True),           # sufficient below the minimum
                         ("otro.example", "baja", 10, 5, 0.6, "learned", None, None, None, False),        # resolved without an interval
                         ("otro.example", "duda", 10, 5, 0.6, "learned", 0.5, 0.2, 0.8, False)):          # a doubt is not a type
                with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation)):
                    c.execute(ROW, args)
                c.rollback()
            c.execute(GATE, ("extract_protocol",))
            c.execute(GATE, ("research_v2",))
            c.commit()
        with pytest.raises(Exception, match="extract_protocol"):
            command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            c.execute("ALTER TABLE ai.feature_gates DISABLE TRIGGER USER")  # the scratch database only: the table is append-only
            c.execute("DELETE FROM ai.feature_gates WHERE gate = 'extract_protocol'")
            c.execute("ALTER TABLE ai.feature_gates ENABLE TRIGGER USER")
            c.commit()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before

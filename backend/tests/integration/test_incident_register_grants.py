"""The application roles never touch the incident register (security plan S3): db/grants.sql takes back, after every migration, what its loop gives.

The roles are created here as on the server (db/initdb) and dropped afterwards; the owner is the migrations' role. The loop of grants.sql hands the API
SELECT and the worker every privilege on every table of every schema, so without the revoke at the end of it a deploy would give both of them the register
(the API could read the evidence of an incident; the worker could write events that never happened)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

GRANTS = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "db" / "grants.sql"
ROLES = ("predigol_worker", "predigol_api")
REGISTER = ("audit.incident_events", "audit.incidents")


@pytest.fixture(scope="module")
def granted(migrated_database: str) -> Iterator[str]:
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        owner = conn.execute("SELECT current_user").fetchone()
        assert owner is not None
        if owner[0] != "fbi":
            pytest.skip("grants.sql names the owner 'fbi'; this cluster's migrations ran as another role")
        for role in ROLES:
            conn.execute(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        conn.execute(GRANTS.read_text())
        conn.execute(GRANTS.read_text())  # idempotent: the second run changes nothing
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for role in ROLES:
            conn.execute(f"DROP OWNED BY {role}")
            conn.execute(f"DROP ROLE IF EXISTS {role}")


def can(conn: psycopg.Connection, role: str, table: str, privilege: str) -> bool:
    row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege)).fetchone()
    return bool(row and row[0])


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("table", REGISTER)
@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_neither_application_role_has_any_privilege_on_the_register(granted: str, role: str, table: str, privilege: str) -> None:
    with psycopg.connect(granted) as conn:
        assert not can(conn, role, table, privilege)


@pytest.mark.parametrize("role", ROLES)
def test_neither_application_role_may_take_a_number_from_its_sequence(granted: str, role: str) -> None:
    with psycopg.connect(granted) as conn:
        row = conn.execute("SELECT has_sequence_privilege(%s, 'audit.incident_events_id_seq', 'USAGE')", (role,)).fetchone()
        assert row is not None and row[0] is False


def test_the_owner_still_reads_and_writes_it(granted: str) -> None:
    with psycopg.connect(granted) as conn:
        for privilege in ("SELECT", "INSERT"):
            assert can(conn, "fbi", "audit.incident_events", privilege)
        assert can(conn, "fbi", "audit.incidents", "SELECT")


def test_the_revoke_is_narrow_the_other_tables_of_the_schema_keep_what_the_loop_gave(granted: str) -> None:
    with psycopg.connect(granted) as conn:
        assert can(conn, "predigol_worker", "audit.data_repairs", "INSERT"), "the worker still writes the repairs it makes"
        assert can(conn, "predigol_api", "audit.data_repairs", "SELECT"), "and the API still reads them"
        assert can(conn, "predigol_api", "audit.evidence_ledger", "UPDATE"), "the owner's verdict on an evidence-ledger entry is still the API's"


def test_grants_sql_says_so() -> None:
    text = GRANTS.read_text(encoding="utf-8")
    assert "audit.incident_events" in text and "audit.incidents" in text and "REVOKE ALL ON audit.incident_events" in text

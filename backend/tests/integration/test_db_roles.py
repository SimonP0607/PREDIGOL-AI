"""Least privilege in the database (deploy/vps/db/grants.sql): the worker and the API get exactly what they use, and
the worker, which may not create a partition, carries on when one is missing. Plus the owner's retention job.

The roles are created here as on the server (db/initdb) and dropped afterwards; the owner is the migrations' role.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from fbi.odds.partitions import ensure_partitions

GRANTS = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "db" / "grants.sql"
ROLES = ("predigol_worker", "predigol_api")


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
        conn.execute(GRANTS.read_text())  # idempotent
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for role in ROLES:
            conn.execute(f"DROP OWNED BY {role}")
            conn.execute(f"DROP ROLE IF EXISTS {role}")


def can(conn: psycopg.Connection, role: str, table: str, privilege: str) -> bool:
    row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege)).fetchone()
    return bool(row and row[0])


@pytest.mark.parametrize(("role", "table", "privilege", "expected"), [
    ("predigol_worker", "core.fixtures", "INSERT", True),
    ("predigol_worker", "market.odds_snapshots", "INSERT", True),
    ("predigol_worker", "picks.user_picks", "UPDATE", True),          # it settles them
    ("predigol_worker", "raw.ingestion_payloads", "DELETE", True),
    ("predigol_worker", "public.alembic_version", "SELECT", True),
    ("predigol_worker", "public.alembic_version", "UPDATE", False),
    ("predigol_api", "core.fixtures", "SELECT", True),
    ("predigol_api", "core.fixtures", "INSERT", False),
    ("predigol_api", "market.odds_snapshots", "UPDATE", False),
    ("predigol_api", "models.predictions", "DELETE", False),
    ("predigol_api", "picks.picks", "INSERT", False),
    ("predigol_api", "auth.users", "UPDATE", True),
    ("predigol_api", "auth.audit_events", "INSERT", True),
    ("predigol_api", "auth.recovery_codes", "DELETE", True),
    ("predigol_api", "picks.user_picks", "INSERT", True),
    ("predigol_api", "picks.user_parlay_legs", "DELETE", True),
    ("predigol_api", "analytics.ai_runs", "UPDATE", True),
    ("predigol_api", "analytics.research_hypotheses", "INSERT", True),
    ("predigol_api", "audit.evidence_ledger", "UPDATE", True),
    ("predigol_api", "audit.evidence_ledger", "INSERT", False),
    ("predigol_api", "public.alembic_version", "UPDATE", False),
    ("predigol_api", "ai.run_requests", "INSERT", True),
    ("predigol_api", "ai.pick_reviews", "SELECT", True),
    ("predigol_api", "ai.pick_reviews", "INSERT", False),
    ("predigol_api", "ai.usage", "INSERT", False),
    ("predigol_api", "ai.match_analyses", "UPDATE", False),
    ("predigol_worker", "ai.pick_reviews", "INSERT", True),
    ("predigol_worker", "ai.usage", "INSERT", True),
])
def test_each_role_gets_exactly_what_it_uses(granted: str, role: str, table: str, privilege: str,
                                            expected: bool) -> None:
    with psycopg.connect(granted) as conn:
        assert can(conn, role, table, privilege) is expected


def test_the_worker_sees_nothing_of_the_accounts(granted: str) -> None:
    with psycopg.connect(granted) as conn:
        row = conn.execute("SELECT has_schema_privilege('predigol_worker', 'auth', 'USAGE')").fetchone()
        assert row == (False,)
        assert not can(conn, "predigol_worker", "auth.users", "SELECT")


def test_a_table_a_future_migration_adds_is_covered_by_the_default_privileges(granted: str) -> None:
    with psycopg.connect(granted, autocommit=True) as conn:
        conn.execute("CREATE TABLE core.zz_future_table (id bigserial PRIMARY KEY, v int)")
        try:
            assert can(conn, "predigol_api", "core.zz_future_table", "SELECT")
            assert not can(conn, "predigol_api", "core.zz_future_table", "INSERT")
            assert can(conn, "predigol_worker", "core.zz_future_table", "INSERT")
            seq = conn.execute("SELECT has_sequence_privilege('predigol_worker', "
                               "'core.zz_future_table_id_seq', 'USAGE')").fetchone()
            assert seq == (True,)
        finally:
            conn.execute("DROP TABLE core.zz_future_table")


def test_the_worker_may_not_create_a_partition_and_carries_on(granted: str) -> None:
    with psycopg.connect(granted) as conn:
        conn.execute("SET ROLE predigol_worker")
        far = date(2031, 3, 1)
        assert ensure_partitions(conn, today=far, months_ahead=0) == []
        # the connection is usable afterwards, and nothing was created
        row = conn.execute("SELECT to_regclass('market.odds_snapshots_2031_03')").fetchone()
        assert row == (None,)
        conn.execute("RESET ROLE")
    with psycopg.connect(granted) as owner:
        created = ensure_partitions(owner, today=far, months_ahead=0)
        assert created == ["market.odds_snapshots_2031_03"]
        owner.execute("DROP TABLE market.odds_snapshots_2031_03")
        owner.commit()


def test_retention_removes_only_old_operational_rows_after_a_fresh_backup(granted: str, tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import db_maintenance

    old = datetime.now(UTC) - timedelta(days=40)
    with psycopg.connect(granted, autocommit=True) as conn:
        conn.execute("DELETE FROM raw.provider_minute_usage")
        conn.execute("INSERT INTO raw.provider_minute_usage (provider, minute, spent) VALUES "
                     "('api-football', %s, 3), ('api-football', now(), 2)", (old,))
    try:
        with psycopg.connect(granted) as conn:
            assert db_maintenance.cmd_retention(conn, confirm=False, backups=tmp_path) == 0
            # no recent backup: refused, nothing removed
            assert db_maintenance.cmd_retention(conn, confirm=True, backups=tmp_path) == 1
            (tmp_path / "predigol-x.dump").write_bytes(b"x")
            (tmp_path / "predigol-x.json").write_text(json.dumps({"created_at": datetime.now(UTC).isoformat()}))
            assert db_maintenance.cmd_retention(conn, confirm=True, backups=tmp_path) == 0
            left = conn.execute("SELECT count(*) FROM raw.provider_minute_usage").fetchone()
            assert left == (1,)
            rec = conn.execute("SELECT rows, verified FROM audit.storage_cleanups WHERE kind = 'retention' "
                               "AND subject = 'raw.provider_minute_usage' ORDER BY id DESC LIMIT 1").fetchone()
            assert rec == (1, True)
    finally:
        # Shared test database: later tests walk the migrations down through 0071, which refuses while
        # 'retention' rows exist (by design). Leave none behind.
        with psycopg.connect(granted, autocommit=True) as conn:
            conn.execute("DELETE FROM audit.storage_cleanups WHERE kind = 'retention'")
            conn.execute("DELETE FROM raw.provider_minute_usage")

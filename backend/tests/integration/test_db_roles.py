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
    # the readers' narrative (plan UX, A11): written by the worker (append-only by trigger), read by the API
    ("predigol_worker", "ai.user_narratives", "INSERT", True),
    ("predigol_worker", "ai.evidence_translations", "INSERT", True),
    ("predigol_worker", "ai.user_usage", "INSERT", True),
    ("predigol_api", "ai.user_narratives", "SELECT", True),
    ("predigol_api", "ai.user_narratives", "INSERT", False),
    ("predigol_api", "ai.evidence_translations", "SELECT", True),
    ("predigol_api", "ai.evidence_translations", "INSERT", False),
    ("predigol_api", "ai.user_usage", "SELECT", True),
    ("predigol_api", "ai.user_usage", "INSERT", False),
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
    # the referee queue (plan F3): a person decides pairs and moves aliases; only the worker's pass makes aliases and officials
    ("predigol_api", "core.referees", "UPDATE", True),
    ("predigol_api", "core.referees", "INSERT", True),            # a split makes a referee
    ("predigol_api", "core.referees", "DELETE", False),
    ("predigol_api", "core.referee_aliases", "UPDATE", True),
    ("predigol_api", "core.referee_aliases", "INSERT", False),
    ("predigol_api", "core.referee_aliases", "DELETE", False),
    ("predigol_api", "core.fixture_officials", "SELECT", True),
    ("predigol_api", "core.fixture_officials", "INSERT", False),
    ("predigol_api", "core.fixture_officials", "UPDATE", False),
    ("predigol_api", "core.referee_candidates", "DELETE", True),
    ("predigol_api", "core.referee_events", "INSERT", True),
    ("predigol_api", "core.referee_events", "DELETE", False),
    ("predigol_worker", "core.fixture_officials", "INSERT", True),
    ("predigol_worker", "core.referee_aliases", "INSERT", True),
    ("predigol_worker", "ai.pick_reviews", "INSERT", True),
    ("predigol_worker", "ai.usage", "INSERT", True),
    # Match Knowledge (plan F7): the worker builds it and rewrites what each line of the events is; the API only reads
    ("predigol_api", "intel.match_knowledge", "SELECT", True),
    ("predigol_api", "intel.match_knowledge", "INSERT", False),
    ("predigol_api", "intel.match_knowledge_latest", "SELECT", True),
    ("predigol_api", "core.fixture_event_kinds", "SELECT", True),
    ("predigol_api", "core.fixture_event_kinds", "INSERT", False),
    ("predigol_worker", "intel.match_knowledge", "INSERT", True),
    ("predigol_worker", "core.fixture_event_kinds", "INSERT", True),
    ("predigol_worker", "core.fixture_event_kinds", "DELETE", True),
    # the customer's own data (plan UX, A4): the API writes what the rules allow, the worker sees nothing
    ("predigol_api", "customer.consents", "SELECT", True),
    ("predigol_api", "customer.consents", "INSERT", True),
    ("predigol_api", "customer.consents", "UPDATE", False),
    ("predigol_api", "customer.consents", "DELETE", False),
    ("predigol_api", "customer.support_tickets", "INSERT", True),
    ("predigol_api", "customer.support_tickets", "UPDATE", True),
    ("predigol_api", "customer.support_tickets", "DELETE", False),
    ("predigol_api", "customer.ticket_messages", "INSERT", True),
    ("predigol_api", "customer.ticket_messages", "UPDATE", False),
    ("predigol_worker", "customer.consents", "SELECT", False),
    ("predigol_worker", "customer.support_tickets", "SELECT", False),
    ("predigol_worker", "customer.ticket_messages", "INSERT", False),
    # the messages to readers (plan UX, A5): the API and the messenger (the API's role) queue and record their fate,
    # never delete one; the owner's notices and the messenger's cycles; the worker reads none of the readers' side
    ("predigol_api", "customer.messages_outbox", "INSERT", True),
    ("predigol_api", "customer.messages_outbox", "UPDATE", True),
    ("predigol_api", "customer.messages_outbox", "DELETE", False),
    ("predigol_api", "customer.preferences", "INSERT", True),
    ("predigol_api", "customer.preferences", "UPDATE", True),
    ("predigol_api", "customer.preferences", "DELETE", True),     # A7: anonymising an account removes them
    ("predigol_api", "audit.notifications", "INSERT", True),
    ("predigol_api", "audit.notifications", "UPDATE", False),
    ("predigol_api", "audit.notifications", "DELETE", False),
    ("predigol_api", "raw.ingestion_runs", "INSERT", True),
    ("predigol_api", "raw.ingestion_runs", "UPDATE", True),
    ("predigol_api", "raw.ingestion_runs", "DELETE", False),
    ("predigol_api", "raw.ingestion_payloads", "INSERT", False),
    ("predigol_worker", "customer.messages_outbox", "SELECT", False),
    ("predigol_worker", "customer.preferences", "SELECT", False),
    ("predigol_worker", "audit.notifications", "UPDATE", True),   # its notifier sends the messenger's drafts
    # product analytics (plan UX, A6): the API records, the messenger aggregates and purges (once the owner says so)
    ("predigol_api", "customer.product_events", "INSERT", True),
    ("predigol_api", "customer.product_events", "UPDATE", False),
    ("predigol_api", "customer.product_events", "DELETE", True),
    ("predigol_api", "customer.activity_daily", "INSERT", True),
    ("predigol_api", "customer.activity_daily", "UPDATE", True),
    ("predigol_api", "customer.activity_daily", "DELETE", True),
    ("predigol_worker", "customer.product_events", "SELECT", False),
    ("predigol_worker", "customer.activity_daily", "SELECT", False),
    # a reader's favourite leagues and teams (plan UX, A13): chosen or removed by the API, never edited; deleted when the
    # account is anonymised; the worker of PrediGol Intelligence never reads them (personalisation never feeds a pick)
    ("predigol_api", "customer.favorites", "SELECT", True),
    ("predigol_api", "customer.favorites", "INSERT", True),
    ("predigol_api", "customer.favorites", "DELETE", True),
    ("predigol_api", "customer.favorites", "UPDATE", False),
    ("predigol_worker", "customer.favorites", "SELECT", False),
    ("predigol_worker", "customer.favorites", "INSERT", False),
    # what readers think of PrediGol (plan UX, B6): the API records the survey and «¿Te sirvió?» (a vote changes: UPDATE),
    # deletes them when the account is anonymised and, as the messenger, past their 24 months; the worker of PrediGol
    # Intelligence never reads them (the opinion never enters the models)
    ("predigol_api", "customer.feedback", "SELECT", True),
    ("predigol_api", "customer.feedback", "INSERT", True),
    ("predigol_api", "customer.feedback", "UPDATE", True),
    ("predigol_api", "customer.feedback", "DELETE", True),
    ("predigol_worker", "customer.feedback", "SELECT", False),
    ("predigol_worker", "customer.feedback", "INSERT", False),
    # each customer's state of the day (plan UX, B11): the messenger (the API's role) writes it once and never edits it
    # (the table's trigger refuses it too); the rows go with an anonymised account and past 24 months; the worker of
    # PrediGol Intelligence reads none of it
    ("predigol_api", "customer.lifecycle_snapshots", "SELECT", True),
    ("predigol_api", "customer.lifecycle_snapshots", "INSERT", True),
    ("predigol_api", "customer.lifecycle_snapshots", "DELETE", True),
    ("predigol_api", "customer.lifecycle_snapshots", "UPDATE", False),
    ("predigol_worker", "customer.lifecycle_snapshots", "SELECT", False),
    ("predigol_worker", "customer.lifecycle_snapshots", "INSERT", False),
    # the readers' notices on their devices (plan UX, B7): the API subscribes and revokes a browser, rings and silences a
    # match's bell and queues the account's notices; the messenger (the API's role) writes the rest, sends them, records
    # each one's fate and purges; the worker of PrediGol Intelligence reads none of it
    *(("predigol_api", f"customer.{table}", privilege, True)
      for table in ("push_subscriptions", "match_alerts", "push_notices")
      for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")),
    *(("predigol_worker", f"customer.{table}", privilege, False)
      for table in ("push_subscriptions", "match_alerts", "push_notices")
      for privilege in ("SELECT", "INSERT", "UPDATE")),
    # an account's one-use links (plan UX, A7): the API issues and redeems them, the messenger arms them and purges
    # them (the API's role); the worker of PrediGol Intelligence sees none of them
    ("predigol_api", "auth.account_tokens", "SELECT", True),
    ("predigol_api", "auth.account_tokens", "INSERT", True),
    ("predigol_api", "auth.account_tokens", "UPDATE", True),
    ("predigol_api", "auth.account_tokens", "DELETE", True),
    ("predigol_worker", "auth.account_tokens", "SELECT", False),
    ("predigol_worker", "auth.account_tokens", "UPDATE", False),
    # A7: what anonymising an account removes or masks, as the API (fbi.auth.anonymize)
    ("predigol_api", "picks.user_picks", "DELETE", True),
    ("predigol_api", "picks.user_parlays", "DELETE", True),
    ("predigol_api", "auth.sessions", "DELETE", True),
    ("predigol_api", "auth.audit_events", "UPDATE", True),
    # A8: the membership - recorded by the owner's console and the messenger, never edited or deleted; the worker reads
    # none of it
    ("predigol_api", "customer.payments", "INSERT", True),
    ("predigol_api", "customer.payments", "UPDATE", False),
    ("predigol_api", "customer.payments", "DELETE", False),
    ("predigol_api", "customer.membership_periods", "INSERT", True),
    ("predigol_api", "customer.membership_periods", "UPDATE", False),
    ("predigol_api", "customer.membership_events", "INSERT", True),
    ("predigol_api", "customer.membership_events", "DELETE", False),
    ("predigol_worker", "customer.payments", "SELECT", False),
    ("predigol_worker", "customer.membership_periods", "SELECT", False),
    ("predigol_worker", "customer.membership_events", "SELECT", False),
    # UX-005: the coupons - created and disabled (an update the table's trigger limits to that) by the console, a holder
    # recorded and never edited; the worker reads none of it
    ("predigol_api", "customer.coupons", "INSERT", True),
    ("predigol_api", "customer.coupons", "UPDATE", True),
    ("predigol_api", "customer.coupons", "DELETE", False),
    ("predigol_api", "customer.coupon_redemptions", "INSERT", True),
    ("predigol_api", "customer.coupon_redemptions", "UPDATE", False),
    ("predigol_worker", "customer.coupons", "SELECT", False),
    ("predigol_worker", "customer.coupon_redemptions", "SELECT", False),
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
    # Plan UX, A7: nor their one-use links - tried as the worker itself, not only asked of the catalog
    with psycopg.connect(granted, autocommit=True) as conn:
        conn.execute("SET ROLE predigol_worker")
        try:
            for table in ("auth.account_tokens", "auth.users"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
        finally:
            conn.execute("RESET ROLE")


def test_the_worker_sees_nothing_of_the_customers_data(granted: str) -> None:
    """Plan UX, A4: the worker of PrediGol Intelligence cannot read the customer schema - not its tables, not its
    sequences, and not a table a later migration adds to it."""
    with psycopg.connect(granted, autocommit=True) as conn:
        row = conn.execute("SELECT has_schema_privilege('predigol_worker', 'customer', 'USAGE')").fetchone()
        assert row == (False,)
        seq = conn.execute("SELECT has_sequence_privilege('predigol_worker', 'customer.consents_id_seq', 'USAGE')"
                           ).fetchone()
        assert seq == (False,)
        assert conn.execute("SELECT has_sequence_privilege('predigol_api', 'customer.consents_id_seq', 'USAGE')"
                            ).fetchone() == (True,)
        conn.execute("CREATE TABLE customer.zz_future_table (id bigserial PRIMARY KEY, v int)")
        try:
            assert can(conn, "predigol_api", "customer.zz_future_table", "SELECT")
            assert not can(conn, "predigol_worker", "customer.zz_future_table", "SELECT")
            assert not can(conn, "predigol_worker", "customer.zz_future_table", "INSERT")
        finally:
            conn.execute("DROP TABLE customer.zz_future_table")
        conn.execute("SET ROLE predigol_worker")
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT 1 FROM customer.consents LIMIT 1")
        finally:
            conn.execute("RESET ROLE")


def test_the_api_numbers_the_readers_devices_and_notices_and_the_worker_cannot(granted: str) -> None:
    """Plan UX, B7: a browser allowed and a notice queued take their numbers from sequences of their own."""
    with psycopg.connect(granted, autocommit=True) as conn:
        for seq in ("customer.push_subscriptions_id_seq", "customer.push_notices_id_seq"):
            assert conn.execute("SELECT has_sequence_privilege('predigol_api', %s, 'USAGE')", (seq,)).fetchone() == (True,)
            assert conn.execute("SELECT has_sequence_privilege('predigol_worker', %s, 'USAGE')",
                                (seq,)).fetchone() == (False,)


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
        row = conn.execute("SELECT to_regclass('market.odds_quotes_2031_03')").fetchone()
        assert row == (None,)
        conn.execute("RESET ROLE")
    with psycopg.connect(granted) as owner:
        created = ensure_partitions(owner, today=far, months_ahead=0)
        assert created == ["market.odds_snapshots_2031_03", "market.odds_quotes_2031_03"]
        owner.execute("DROP TABLE market.odds_snapshots_2031_03")
        owner.execute("DROP TABLE market.odds_quotes_2031_03")
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


def test_the_messenger_does_its_work_with_the_apis_role_and_nothing_more(granted: str) -> None:
    """Plan UX, A5 (SECURITY): the messenger runs as predigol_api - its cycle in the job ledger, the queue, the owner's
    notices - and that role cannot delete a message nor touch PrediGol Intelligence; the worker cannot read the queue."""
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.messaging import notices, outbox
    from fbi.messaging.provider import Outgoing
    from fbi.notify.service import Draft

    class Provider:
        name = "fake"

        def send(self, message: Outgoing) -> str:
            return f"roles-{message.idempotency_key[-6:]}"

    with psycopg.connect(granted) as conn:
        uid = conn.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                           "('roles.messenger@example.org', 'R', '$argon2id$v=19$m=65536,t=3,p=4$cm9sZXM$cm9sZXM') "
                           "RETURNING id").fetchone()
        assert uid is not None
        conn.commit()
        try:
            conn.execute("SET ROLE predigol_api")
            ledger = RunLedger(conn)
            run_id = ledger.open("messenger_cycle")
            assert outbox.enqueue(conn, user_id=uid[0], template="privacy_request_answered",
                                  params={"request": "privacy_query", "ticket": "1"},
                                  dedup_key="roles:messenger:1") is not None
            conn.commit()
            report = outbox.dispatch(conn, Provider(), at=datetime.now(UTC))
            assert report.sent == 1
            assert notices.write(conn, [Draft("ticket_new", "ticket_new:roles", "t", "b", {"last_id": 0})]) == 1
            ledger.close(run_id, RunCounters(rows_updated=1))
            for sql in ("DELETE FROM customer.messages_outbox", "UPDATE audit.notifications SET status = 'sent'",
                        "UPDATE picks.picks SET status = status", "INSERT INTO models.model_registry (name) VALUES ('x')",
                        "DELETE FROM raw.ingestion_runs WHERE job_type = 'messenger_cycle'"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(sql)
                conn.rollback()
            conn.execute("SET ROLE predigol_worker")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT 1 FROM customer.messages_outbox LIMIT 1")
            conn.rollback()
        finally:
            conn.rollback()
            conn.execute("RESET ROLE")
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            conn.execute("DELETE FROM customer.messages_outbox WHERE dedup_key = 'roles:messenger:1'")
            conn.execute("DELETE FROM audit.notifications WHERE dedup_key = 'ticket_new:roles'")
            conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'messenger_cycle'")
            conn.execute("DELETE FROM auth.users WHERE email = 'roles.messenger@example.org'")
            conn.commit()

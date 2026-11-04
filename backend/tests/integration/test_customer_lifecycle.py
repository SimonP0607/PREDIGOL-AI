"""Each customer's state of the day against the migrated database (plan UX, B11; section 23 of the plan).

* The daily calculation writes one row per reader and Bogota day with its state and its reasons - the owner and the
  disabled are left out - and a second run the same day adds nothing.
* The history is append-only: the table refuses an edit or a delete; the maintenance switch is only for the anonymisation
  and the 24 months' retention (counted with ``dry``, deleted with ``on``).
* The console reads it: the at-risk and invited views, the state on each row, the card's history.
* Support's queue puts the request of a reader at risk first within its priority, and says so.
* The owner's morning count carries numbers and a link, never a name; metrics hide shares of fewer than 30 readers.
* An anonymised account takes its history with it; the messenger's cycle calculates the day and survives a failure.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import anonymize, crypto, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import events, lifecycle, membership, support
from fbi.messaging import notices, runner
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

HABIT = "habito.b11@example.org"
SILENT = "silencio.b11@example.org"
UNHAPPY = "triste.b11@example.org"
INVITED = "invitada.b11@example.org"
ENDING = "vence.b11@example.org"
WAITING = "espera.b11@example.org"
GONE = "retirada.b11@example.org"
OWNER = "owner.b11@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
READERS = (HABIT, SILENT, UNHAPPY, INVITED, ENDING, WAITING)
AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)  # 10:00 in Bogota


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.activity_daily", "customer.messages_outbox",
                          "customer.preferences", "customer.ticket_messages", "customer.support_tickets",
                          "customer.consents", "customer.feedback"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind = 'lifecycle_daily'")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_WEB_BASE_URL", "https://predigol.example")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email in (*READERS, GONE):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role="USER",
                                       password=PASSWORD, language="es", timezone="America/Bogota")
    service.create_user_unattended(email=OWNER, display_name="owner", role="SUPER_ADMIN", password=PASSWORD,
                                   language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def world(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Six readers in six situations, as the passing of time would leave them."""
    throttle.reset_all()
    forget_sign_in_failures()
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    with psycopg.connect(database, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.product_events", "customer.activity_daily", "customer.ticket_messages",
                          "customer.support_tickets", "customer.feedback", "customer.membership_events",
                          "customer.membership_periods", "customer.payments", "customer.lifecycle_snapshots"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM audit.notifications WHERE kind = 'lifecycle_daily'")
        conn.execute("UPDATE auth.users SET status = 'active', created_at = %s WHERE role = 'USER'",
                     (AT - timedelta(days=40),))
        ids = {e: uid(database, e) for e in (*READERS, GONE)}
        conn.execute("UPDATE auth.users SET status = 'invited' WHERE id = %s", (ids[INVITED],))
        for email, ends in ((HABIT, 60), (SILENT, 60), (UNHAPPY, 60), (INVITED, 60), (ENDING, 3), (WAITING, 60),
                            (GONE, 60)):
            conn.execute("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, reason) "
                         "VALUES (%s, 'courtesy', %s, %s, 'prueba del ciclo')",
                         (ids[email], AT - timedelta(days=20), AT + timedelta(days=ends)))

        def use(email: str, days_ago: tuple[int, ...]) -> None:
            subject = crypto.product_id(ids[email])
            assert subject is not None, "the tests carry the pseudonym's key"
            for d in days_ago:
                moment = AT - timedelta(days=d)
                conn.execute("INSERT INTO customer.activity_daily (day, subject, events, counts, first_at, last_at) "
                             "VALUES (%s, %s, 2, %s, %s, %s)", (events.bogota_day(moment), subject,
                                                               json.dumps({"match_opened": 2}), moment, moment))

        use(HABIT, (0, 1, 2, 4))
        use(UNHAPPY, (0, 1))
        use(ENDING, (0,))
        use(WAITING, (1, 2))
        use(SILENT, (12,))
        use(GONE, (0, 1))
        conn.execute("INSERT INTO customer.feedback (user_id, kind, score, context, created_at) "
                     "VALUES (%s, 'csat', 2, '{}', %s)", (ids[UNHAPPY], AT - timedelta(days=3)))
        conn.execute("INSERT INTO customer.support_tickets (user_id, kind, category, status, opened_at) "
                     "VALUES (%s, 'support', 'technical', 'open', %s)", (ids[WAITING], AT - timedelta(hours=80)))
    membership.forget()
    yield database
    with psycopg.connect(database, autocommit=True) as conn, conn.transaction():
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.lifecycle_snapshots")


def stored(dsn: str) -> dict[str, tuple[str, list[str]]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT u.email, s.state, s.reasons FROM customer.lifecycle_snapshots s "
                            "JOIN auth.users u ON u.id = s.user_id").fetchall()
    return {r[0]: (r[1], list(r[2])) for r in rows}


def run_day(dsn: str, at: datetime = AT) -> int:
    with psycopg.connect(dsn) as conn:
        n = lifecycle.compute_day(conn, at=at)
        conn.commit()
    return n


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def test_the_day_is_written_once_with_its_reasons(world: str) -> None:
    assert run_day(world) == 7
    got = stored(world)
    assert OWNER not in got
    assert got[HABIT] == ("habitual", ["used_3_of_7_days"])
    assert got[SILENT] == ("at_risk", ["silent_7d"])
    assert got[UNHAPPY] == ("at_risk", ["low_survey"])
    assert got[WAITING] == ("at_risk", ["ticket_waiting_72h"])
    assert got[INVITED] == ("invited", ["account_invited"])
    assert got[ENDING] == ("expiring", ["membership_expiring"])
    assert got[GONE] == ("activated", ["account_activated", "some_use"])
    assert run_day(world) == 0, "a second run the same day adds nothing"
    assert len(stored(world)) == 7


def test_a_disabled_account_has_no_state(world: str) -> None:
    with psycopg.connect(world, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET status = 'disabled' WHERE email = %s", (GONE,))
    try:
        assert run_day(world) == 6
        assert GONE not in stored(world)
    finally:
        with psycopg.connect(world, autocommit=True) as conn:
            conn.execute("UPDATE auth.users SET status = 'active' WHERE email = %s", (GONE,))


def test_the_history_is_append_only_and_its_retention_is_the_owners_switch(world: str) -> None:
    run_day(world)
    with psycopg.connect(world, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute("UPDATE customer.lifecycle_snapshots SET state = 'habitual'")
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute("DELETE FROM customer.lifecycle_snapshots")
        with pytest.raises(psycopg.errors.IntegrityError), conn.transaction():
            conn.execute("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) "
                         "SELECT id, DATE '2020-01-01', 'vip', ARRAY['x'] FROM auth.users LIMIT 1")
        with pytest.raises(psycopg.errors.IntegrityError), conn.transaction():
            conn.execute("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) "
                         "SELECT id, DATE '2020-01-01', 'invited', ARRAY['Mal Escrito'] FROM auth.users LIMIT 1")
        # two years and a day old: counted with dry, kept with off, deleted with on
        old = AT - timedelta(days=lifecycle.RETENTION.days + 2)
        conn.execute("SET fbi.customer_maintenance = 'on'")
        conn.execute("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) "
                     "SELECT id, %s, 'invited', ARRAY['account_invited'] FROM auth.users WHERE email = %s",
                     (events.bogota_day(old), HABIT))
        conn.execute("RESET fbi.customer_maintenance")
    with psycopg.connect(world) as conn:
        assert lifecycle.purge(conn, at=AT, mode="off") == lifecycle.PurgeReport("off", 0)
        assert lifecycle.purge(conn, at=AT, mode="dry") == lifecycle.PurgeReport("dry", 1)
        conn.rollback()
        assert lifecycle.purge(conn, at=AT, mode="on") == lifecycle.PurgeReport("on", 1)
        conn.commit()
        assert scalar(conn.execute("SELECT count(*) FROM customer.lifecycle_snapshots")) == 7, "today's rows stay"


def test_the_console_reads_the_states(world: str) -> None:
    owner = client(OWNER)
    with psycopg.connect(world) as conn:
        lifecycle.compute_day(conn, at=AT)
        conn.commit()
    risky = owner.get("/api/v1/admin/customers", params={"view": "at_risk"}).json()
    assert sorted(i["email"] for i in risky["items"]) == sorted([SILENT, UNHAPPY, WAITING])
    invited = owner.get("/api/v1/admin/customers", params={"view": "invited"}).json()
    assert [i["email"] for i in invited["items"]] == [INVITED]
    assert invited["items"][0]["lifecycle"] == "invited" and invited["items"][0]["lifecycle_reasons"] == ["account_invited"]
    counts = {v["view"]: v["count"] for v in invited["views"]}
    assert counts["invited"] == 1 and counts["at_risk"] == risky["total"]
    card = owner.get(f"/api/v1/admin/customers/{uid(world, INVITED)}").json()
    assert card["lifecycle"]["state"] == "invited"
    assert [c["state"] for c in card["lifecycle_history"]] == ["invited"]


def test_a_card_lists_only_the_changes(world: str) -> None:
    habit = uid(world, HABIT)
    with psycopg.connect(world) as conn:
        for days_ago, state in ((3, "activated"), (2, "activated"), (1, "habitual")):
            day = events.bogota_day(AT - timedelta(days=days_ago))
            conn.execute("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) VALUES (%s, %s, %s, "
                         "ARRAY['some_use'])", (habit, day, state))
        conn.commit()
        history = lifecycle.history(conn, habit)
    assert [(h["state"]) for h in history] == ["habitual", "activated"], "newest first, one line per change"


def test_support_puts_the_request_of_a_reader_at_risk_first_and_says_so(world: str) -> None:
    with psycopg.connect(world, autocommit=True) as conn:
        for email, hours in ((HABIT, 60), (UNHAPPY, 1)):
            conn.execute("INSERT INTO customer.support_tickets (user_id, kind, category, status, opened_at) "
                         "VALUES (%s, 'support', 'suggestion', 'open', %s)",
                         (uid(world, email), AT - timedelta(hours=hours)))
    with psycopg.connect(world) as conn:
        queue = support.inbox(conn, status="open", category="suggestion", priority=None)
        assert [t.email for t in queue] == [HABIT, UNHAPPY], "before the lifecycle, the oldest first"
        lifecycle.compute_day(conn, at=AT)
        conn.commit()
        queue = support.inbox(conn, status="open", category="suggestion", priority=None)
    assert [t.email for t in queue] == [UNHAPPY, HABIT], "newer, but their reader is at risk"
    assert [t.at_risk for t in queue] == [True, False]
    owner = client(OWNER)
    body = owner.get("/api/v1/admin/support").json()
    flags = {t["email"]: t["at_risk"] for t in body["tickets"]}
    assert flags[UNHAPPY] is True and flags[HABIT] is False


def test_the_morning_count_has_numbers_and_a_link_and_no_names(world: str) -> None:
    run_day(world)
    before = AT.replace(hour=11)  # 06:00 in Bogota: too early
    with psycopg.connect(world) as conn:
        assert notices.lifecycle_daily(conn, at=before) == []
        [draft] = notices.lifecycle_daily(conn, at=AT)
    assert draft.kind == "lifecycle_daily" and draft.dedup_key == "lifecycle_daily:2026-11-03"
    assert "3 clientes están en riesgo" in draft.body and "1 cliente está por vencer" in draft.body
    assert "1 invitación sigue sin activar" in draft.body
    assert "/admin/customers" in draft.body
    assert not any(name in draft.body + draft.title for name in ("habito", "silencio", "triste", ".org", "@"))
    assert draft.payload == {"expiring": 1, "at_risk": 3, "invited": 1}
    with psycopg.connect(world) as conn:
        assert notices.write(conn, [draft]) == 1 and notices.write(conn, [draft]) == 0, "once a day"


def test_metrics_hide_shares_of_a_handful(world: str) -> None:
    run_day(world)
    with psycopg.connect(world) as conn:
        m = lifecycle.metrics(conn, at=AT)
    assert m.states["at_risk"] == 3 and m.states["invited"] == 1
    for r in (m.renewal_30d, m.activation_7d, m.retention_d7, m.retention_d30):
        assert r.value is None, "under 30 readers: no percentage"
    owner = client(OWNER)
    body = owner.get("/api/v1/admin/product").json()
    assert body["lifecycle"]["activation_7d"]["value"] is None and body["lifecycle"]["states"]["invited"] >= 0


def test_the_readers_copy_of_their_data_carries_their_states(world: str) -> None:
    from fbi.customer import privacy

    run_day(world)
    with psycopg.connect(world) as conn:
        mine = privacy.export(conn, uid(world, HABIT))["lifecycle"]
        other = privacy.export(conn, uid(world, SILENT))["lifecycle"]
    assert [(r["state"], r["reasons"]) for r in mine] == [("habitual", ["used_3_of_7_days"])]
    assert [r["state"] for r in other] == ["at_risk"], "each reader gets only their own"


def test_an_anonymised_account_takes_its_history_with_it(world: str) -> None:
    run_day(world)
    gone = uid(world, GONE)
    assert gone is not None and GONE in stored(world)
    owner = uid(world, OWNER)
    anonymize.anonymise(principal("SUPER_ADMIN", user_id=owner), gone, confirm=GONE, ip=None)
    assert GONE not in stored(world) and len(stored(world)) == 6
    with psycopg.connect(world, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET email = %s, status = 'active' WHERE id = %s", (GONE, gone))


def test_the_messengers_cycle_calculates_the_day_and_a_failure_does_not_stop_it(
        world: str, monkeypatch: pytest.MonkeyPatch) -> None:
    totals = runner.CycleTotals()
    with psycopg.connect(world) as conn:
        runner.start_of_cycle(conn, totals, sending=False, provider=False)
    assert totals.lifecycle == 7 and totals.lifecycle_purge is not None
    assert "lifecycle 7" in totals.notes(sending=False, provider=False)
    # switched off: nothing is calculated and nothing fails
    with psycopg.connect(world, autocommit=True) as conn, conn.transaction():
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.lifecycle_snapshots")
    monkeypatch.setenv("FBI_LIFECYCLE", "0")
    off = runner.CycleTotals()
    with psycopg.connect(world) as conn:
        runner.start_of_cycle(conn, off, sending=False, provider=False)
    assert off.lifecycle == 0 and not [e for e in off.errors if e.startswith("lifecycle")]
    assert stored(world) == {}
    # a failure is recorded and the cycle goes on
    monkeypatch.delenv("FBI_LIFECYCLE")

    def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("no day today")

    monkeypatch.setattr(lifecycle, "compute_day", boom)
    failed = runner.CycleTotals()
    with psycopg.connect(world) as conn:
        runner.start_of_cycle(conn, failed, sending=False, provider=False)
    assert any(e.startswith("lifecycle:") for e in failed.errors)

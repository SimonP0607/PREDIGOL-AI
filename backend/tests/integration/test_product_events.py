"""Product analytics against the migrated database (plan UX, A6 and section 39).

* The browser's events over HTTP: a session's own, behind the switch (born off), never the owner's or the robot's,
  only with the analytics consent in ``consent`` mode; a batch with anything outside the catalog is refused whole.
* The rows carry a pseudonym (not the account's id, not Sentry's pseudonym) and nothing personal.
* The daily aggregate equals the raw events, day by Bogotá day, and recomputing it changes nothing.
* The purge counts in ``dry`` and deletes only in ``on``; only what is past its retention.
* The owner's view: global figures only with enough readers; 403 to a reader.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from fbi.auth import crypto, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, events
from fbi.customer.events import EventError
from tests.integration.helpers import forget_sign_in_failures

READER = "lector.eventos@example.org"
OTHER = "otro.eventos@example.org"
OWNER = "owner.eventos@predigol.test"
ROBOT = "robot.eventos@predigol.test"
PASSWORD = "Reader-pass-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
SAME_SITE = {"x-requested-with": "predigol"}


def wipe_events(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM customer.product_events")
        conn.execute("DELETE FROM customer.activity_daily")
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.consents")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_SYNTHETIC_EMAIL", ROBOT)
    reset_cache()
    reset_session_settings()

    def wipe() -> None:
        wipe_events(migrated_database)
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("SET fbi.customer_maintenance = 'on'")
            conn.execute("DELETE FROM customer.messages_outbox")
            conn.execute("DELETE FROM customer.preferences")
            conn.execute("DELETE FROM customer.ticket_messages")
            conn.execute("DELETE FROM customer.support_tickets")
            conn.execute("DELETE FROM auth.sessions")
            conn.execute("DELETE FROM auth.audit_events")
            conn.execute("DELETE FROM picks.user_picks")
            conn.execute("DELETE FROM auth.users")

    wipe()
    for email, role in ((READER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN"), (ROBOT, "USER")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    yield migrated_database
    wipe()
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    wipe_events(database)
    consents._clear.clear()
    from fbi.api.routers import events as events_router

    events_router.EVENT_LIMIT.reset()
    monkeypatch.delenv(consents.GATE_ENV, raising=False)
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    monkeypatch.delenv("FBI_PRODUCT_MIN_SUBJECTS", raising=False)
    monkeypatch.delenv("FBI_EVENTS_PURGE", raising=False)
    yield database


def client(email: str) -> TestClient:
    from fbi.api.app import create_app

    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def user_id(conn: psycopg.Connection[Any], email: str) -> int:
    row = conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,)).fetchone()
    assert row is not None
    return int(row[0])


def rows(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT subject, name, props FROM customer.product_events ORDER BY id").fetchall()


JOURNEY = [{"name": "session_started", "props": {"device": "phone", "width": 390, "client": "browser", "lang": "es"}},
           {"name": "match_opened", "props": {"origin": "home", "match_id": 9001}},
           {"name": "match_section_opened", "props": {"section": "markets", "match_id": 9001}},
           {"name": "term_explained", "props": {"term": "fair_odds"}}]


def test_a_readers_journey_is_recorded_with_a_pseudonym_and_nothing_personal(fresh: str) -> None:
    r = client(READER).post("/api/v1/events", json={"events": JOURNEY})
    assert r.status_code == 200, r.text
    assert r.json() == {"recorded": 4}
    found = rows(fresh)
    with psycopg.connect(fresh) as conn:
        uid = user_id(conn, READER)
    pseudonym = crypto.product_id(uid)
    assert pseudonym is not None and pseudonym != str(uid) and pseudonym != crypto.observability_id(uid)
    assert [(s, n) for s, n, _ in found] == [(pseudonym, e["name"]) for e in JOURNEY]
    assert [p for _, _, p in found] == [e["props"] for e in JOURNEY]
    assert READER not in str(found)
    with psycopg.connect(fresh) as conn:
        columns = {c for (c,) in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'customer' "
            "AND table_name IN ('product_events', 'activity_daily')").fetchall()}
    assert not columns & {"user_id", "email", "ip", "user_agent", "text", "query", "url"}


def test_a_batch_with_anything_outside_the_catalog_is_refused_whole(fresh: str) -> None:
    c = client(READER)
    for bad in ({"name": "match_opened", "props": {"query": "texto libre"}},
                {"name": "account_activated", "props": {}},
                {"name": "no_such_event", "props": {}},
                {"name": "match_opened", "props": {"origin": "the reader's words"}}):
        r = c.post("/api/v1/events", json={"events": [JOURNEY[0], bad]})
        assert r.status_code == 422, (bad, r.text)
    assert c.post("/api/v1/events", json={"events": [JOURNEY[1]] * 21}).status_code == 422
    assert c.post("/api/v1/events", json={"events": [], "extra": 1}).status_code == 422
    assert rows(fresh) == []


def test_nothing_is_recorded_switched_off_for_the_owner_the_robot_or_without_consent(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for email in (OWNER, ROBOT):
        assert client(email).post("/api/v1/events", json={"events": JOURNEY}).json() == {"recorded": 0}
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "off")
    assert client(READER).post("/api/v1/events", json={"events": JOURNEY}).json() == {"recorded": 0}
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "consent")
    reader = client(READER)
    assert reader.post("/api/v1/events", json={"events": JOURNEY}).json() == {"recorded": 0}
    assert rows(fresh) == []
    with psycopg.connect(fresh) as conn:
        conn.execute("""
            INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, statement,
                                           source)
            VALUES (%s, 'analytics', true, 'privacy', '2026-10-25-draft1', %s, 'es', 'Acepto la analítica', 'profile')
        """, (user_id(conn, READER), "0" * 64))
    assert reader.post("/api/v1/events", json={"events": JOURNEY[:1]}).json() == {"recorded": 1}


def test_only_a_session_of_this_site_may_send(fresh: str) -> None:
    from fbi.api.app import create_app

    anon = TestClient(create_app(), headers=SAME_SITE)
    assert anon.post("/api/v1/events", json={"events": JOURNEY}).status_code == 401
    reader = client(READER)
    bare = TestClient(reader.app)
    bare.cookies = reader.cookies
    assert bare.post("/api/v1/events", json={"events": JOURNEY}).status_code == 403
    assert rows(fresh) == []


def test_the_limit_per_minute_stops_a_loop(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.limits import SlidingWindow
    from fbi.api.routers import events as events_router

    monkeypatch.setattr(events_router, "EVENT_LIMIT", SlidingWindow(per_window=5, window_s=60.0))
    c = client(READER)
    assert c.post("/api/v1/events", json={"events": JOURNEY}).status_code == 200
    r = c.post("/api/v1/events", json={"events": JOURNEY})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def put(conn: psycopg.Connection[Any], subject: str, name: str, at: datetime, props: dict[str, Any] | None = None,
        ) -> None:
    conn.execute("INSERT INTO customer.product_events (subject, name, props, at) VALUES (%s, %s, %s, %s)",
                 (subject, name, Json(props or {}), at))


A, B = "a" * 20, "b" * 20


def test_the_daily_aggregate_equals_the_raw_events_day_by_bogota_day(fresh: str) -> None:
    day = date(2026, 10, 20)
    start, end = events.day_bounds(day)
    with psycopg.connect(fresh) as conn:
        put(conn, A, "match_opened", start)                          # 00:00 in Bogotá: that day
        put(conn, A, "match_opened", start + timedelta(hours=3))
        put(conn, A, "term_explained", end - timedelta(seconds=1))   # 23:59:59 in Bogotá: still that day
        put(conn, A, "match_opened", end)                            # the next day
        put(conn, B, "session_started", start + timedelta(hours=12))
        conn.commit()
        assert events.rollup(conn, [day, day + timedelta(days=1)]) == 3
        conn.commit()
        daily = {(d, s): (n, c) for d, s, n, c in conn.execute(
            "SELECT day, subject, events, counts FROM customer.activity_daily").fetchall()}
        assert daily == {(day, A): (3, {"match_opened": 2, "term_explained": 1}),
                         (day, B): (1, {"session_started": 1}),
                         (day + timedelta(days=1), A): (1, {"match_opened": 1})}
        raw = Counter((events.bogota_day(at), s, n) for s, n, at in conn.execute(
            "SELECT subject, name, at FROM customer.product_events").fetchall())
        agg: Counter[tuple[date, str, str]] = Counter()
        for (d, s), (_, counts) in daily.items():
            for n, k in counts.items():
                agg[(d, s, n)] += k
        assert raw == agg, "the aggregate equals the raw events"
        assert events.rollup(conn, [day]) == 2, "recomputing changes nothing but recomputes"
        put(conn, B, "pick_saved", start + timedelta(hours=13), {"origin": "pick"})
        events.rollup(conn, [day])
        conn.commit()
        assert conn.execute("SELECT events FROM customer.activity_daily WHERE day = %s AND subject = %s",
                            (day, B)).fetchone() == (2,)


def test_the_purge_counts_when_dry_and_deletes_only_what_is_past_its_retention_when_on(fresh: str) -> None:
    now = datetime(2026, 10, 25, 15, 0, tzinfo=UTC)
    with psycopg.connect(fresh) as conn:
        put(conn, A, "match_opened", now - timedelta(days=91))
        put(conn, A, "match_opened", now - timedelta(days=89))
        for d, s in ((events.bogota_day(now) - timedelta(days=400), A), (events.bogota_day(now) - timedelta(days=30), A)):
            conn.execute("INSERT INTO customer.activity_daily (day, subject, events, counts, first_at, last_at) "
                         "VALUES (%s, %s, 1, '{\"match_opened\": 1}', now(), now())", (d, s))
        conn.commit()
        assert events.purge(conn, at=now) == events.PurgeReport("dry", 1, 1)
        assert events.purge(conn, at=now, mode_="off") == events.PurgeReport("off", 0, 0)
        conn.commit()
        assert conn.execute("SELECT count(*) FROM customer.product_events").fetchone() == (2,)
        assert events.purge(conn, at=now, mode_="on") == events.PurgeReport("on", 1, 1)
        conn.commit()
        assert conn.execute("SELECT count(*) FROM customer.product_events").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM customer.activity_daily").fetchone() == (1,)


def test_the_owner_sees_global_figures_only_with_enough_readers(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    today_start = events.day_bounds(events.bogota_day(now))[0]
    at = max(now - timedelta(minutes=5), today_start)  # today in Bogotá, even a minute after its midnight
    with psycopg.connect(fresh) as conn:
        for i, subject in enumerate((A, B, "c" * 20)):
            put(conn, subject, "session_started", at,
                {"device": "tablet" if i else "phone", "width": 800, "client": "browser", "lang": "es"})
            put(conn, subject, "match_opened", at, {"origin": "home", "match_id": 1})
        put(conn, A, "error_shown", at, {"code": "unreachable", "status": 0})
        events.rollup(conn, [events.bogota_day(now) - timedelta(days=1), events.bogota_day(now)])
        conn.commit()
        thin = events.overview(conn, at=now)
        assert thin.status == "insufficient_data" and thin.active_30d == 3 and thin.min_subjects == 20
        assert thin.usage == [] and thin.funnel == [] and thin.active == {}
        monkeypatch.setenv("FBI_PRODUCT_MIN_SUBJECTS", "3")
        full = events.overview(conn, at=now)
    assert full.status == "ok" and full.active == {"d1": 3, "d7": 3, "d30": 3} and full.dau_mau is None
    assert {u["name"]: u["events_7d"] for u in full.usage} == {"session_started": 3, "match_opened": 3,
                                                                "error_shown": 1}
    assert {f["step"]: f["subjects"] for f in full.funnel}["first_value"] == 3
    assert full.devices == {"phone": 1, "tablet": 2} and full.errors_per_active == round(1 / 3, 3)
    owner = client(OWNER).get("/api/v1/admin/product")
    assert owner.status_code == 200 and owner.json()["status"] == "ok"
    assert client(READER).get("/api/v1/admin/product").status_code == 403


def test_a_server_event_is_recorded_in_the_callers_transaction(fresh: str) -> None:
    with psycopg.connect(fresh) as conn:
        assert events.record_server(conn, user_id(conn, READER), "account_activated")
        assert not events.record_server(conn, user_id(conn, OWNER), "account_activated")
        with pytest.raises(EventError):
            events.record_server(conn, user_id(conn, READER), "match_opened")
        conn.rollback()
    assert rows(fresh) == [], "rolled back with the caller"


def test_the_readers_export_holds_their_own_events_and_nobody_elses(fresh: str) -> None:
    from fbi.customer import privacy

    assert client(READER).post("/api/v1/events", json={"events": JOURNEY[:2]}).json() == {"recorded": 2}
    assert client(OTHER).post("/api/v1/events", json={"events": JOURNEY[2:]}).json() == {"recorded": 2}
    with psycopg.connect(fresh) as conn:
        today = events.bogota_day(datetime.now(UTC))
        events.rollup(conn, [today - timedelta(days=1), today])
        conn.commit()
        document = privacy.export(conn, user_id(conn, READER))
    assert [e["name"] for e in document["product_events"]] == ["session_started", "match_opened"]
    assert sum(d["events"] for d in document["activity_daily"]) == 2
    assert "match_section_opened" not in str(document["product_events"])

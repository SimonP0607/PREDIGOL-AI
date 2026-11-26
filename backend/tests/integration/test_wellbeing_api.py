"""PM-14-07 through the API and a real database: off, nothing changes (the choice answers 404, every price is served); on, a reader who
chose «solo fútbol» or a pause gets 403 on every call that IS a price, keeps the football, cannot cut a running pause short, is left out
of the notices that mention a pick, and the account's anonymisation deletes the choice."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.switches import WELLBEING
from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import wellbeing
from tests.integration.helpers import forget_memberships, forget_sign_in_failures
from tests.integration.signed_in import SAME_SITE

pytestmark = pytest.mark.integration

READER = "lectora.wb014@example.org"
OTHER = "otro.wb014@example.org"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
PRICES = ("/api/v1/picks", "/api/v1/odds", "/api/v1/daily", "/api/v1/me/picks", "/api/v1/me/history", "/api/v1/parlays/daily",
          "/api/v1/transparency", "/api/v1/today/no-pick")
FOOTBALL = ("/api/v1/competitions", "/api/v1/me/favorites", "/api/v1/auth/me", "/api/v1/me/wellbeing")


def _wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.wellbeing WHERE user_id IN (SELECT id FROM auth.users WHERE email = ANY(%s))",
                     ([READER, OTHER],))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    _wipe(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users WHERE email = ANY(%s)", ([READER, OTHER],))
    for email in (READER, OTHER):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role="USER", password=PASSWORD, language="es",
                                       timezone="America/Bogota")
    yield migrated_database
    _wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    throttle.reset_all()
    forget_sign_in_failures()
    _wipe(database)
    monkeypatch.setenv(WELLBEING, "1")
    yield


def user_id(conn: psycopg.Connection, email: str) -> int:
    row = conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,)).fetchone()
    assert row is not None
    return int(row[0])


def status(c: TestClient, url: str) -> int:
    return c.get(url).status_code


def test_off_nothing_changes(database: str, fresh: None, monkeypatch: pytest.MonkeyPatch) -> None:
    c = client(READER)
    assert c.put("/api/v1/me/wellbeing", json={"football_only": True}).status_code == 200
    monkeypatch.delenv(WELLBEING, raising=False)
    assert c.get("/api/v1/me/wellbeing").status_code == 404 and c.put("/api/v1/me/wellbeing", json={}).status_code == 404
    for url in PRICES:
        assert status(c, url) != 403, f"{url}: the line is off, a price is served as it always was"
    me = c.get("/api/v1/auth/me").json()
    assert me["wellbeing"]["available"] is False and me["wellbeing"]["active"] is False


def test_without_a_choice_every_price_is_served(database: str, fresh: None) -> None:
    c = client(READER)
    me = c.get("/api/v1/auth/me").json()["wellbeing"]
    assert me == {"available": True, "active": False, "football_only": False, "paused_until": None, "pause_can_be_lifted": False}
    for url in PRICES:
        assert status(c, url) != 403, url


def test_the_mode_closes_every_price_and_keeps_the_football(database: str, fresh: None) -> None:
    c = client(READER)
    chosen = c.put("/api/v1/me/wellbeing", json={"football_only": True})
    assert chosen.status_code == 200 and chosen.json()["active"] is True and chosen.json()["football_only"] is True
    for url in PRICES:
        r = c.get(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "wellbeing_active", url
    for url in FOOTBALL:
        assert status(c, url) != 403, url
    assert client(OTHER).get("/api/v1/picks").status_code != 403, "another reader's choice is theirs alone"
    assert c.put("/api/v1/me/wellbeing", json={"football_only": False}).json()["active"] is False
    assert status(c, "/api/v1/picks") != 403, "the way back is the reader's"


def test_a_pause_runs_to_its_date_and_cannot_be_cut_short(database: str, fresh: None) -> None:
    c = client(READER)
    first = c.put("/api/v1/me/wellbeing", json={"pause_days": 7}).json()
    assert first["active"] is True and first["football_only"] is False and first["paused_until"] is not None
    assert status(c, "/api/v1/picks") == 403
    shorter = c.put("/api/v1/me/wellbeing", json={"pause_days": 1})
    assert shorter.status_code == 409 and shorter.json()["error"]["code"] == "pause_running"
    lifted = c.put("/api/v1/me/wellbeing", json={"pause_days": 0})
    assert lifted.status_code == 409 and lifted.json()["error"]["code"] == "pause_running"
    longer = c.put("/api/v1/me/wellbeing", json={"pause_days": 30}).json()
    assert longer["paused_until"] > first["paused_until"] and longer["active"] is True
    assert c.put("/api/v1/me/wellbeing", json={"pause_days": 5}).status_code == 422


def test_a_pause_that_ended_opens_the_prices_again(database: str, fresh: None) -> None:
    c = client(READER)
    c.put("/api/v1/me/wellbeing", json={"pause_days": 1})
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE customer.wellbeing SET paused_until = now() - interval '1 minute', "
                     "created_at = now() - interval '2 days', updated_at = now() - interval '1 day'")
    assert status(c, "/api/v1/picks") != 403
    assert c.get("/api/v1/me/wellbeing").json()["active"] is False


def test_the_notices_that_mention_a_pick_skip_the_readers_who_see_none(database: str, fresh: None) -> None:
    c = client(READER)
    client(OTHER)
    c.put("/api/v1/me/wellbeing", json={"football_only": True})
    at = datetime.now(UTC)
    with psycopg.connect(database) as conn:
        uid = user_id(conn, READER)
        other = user_id(conn, OTHER)
        assert wellbeing.hidden_prices(conn, at) == frozenset({int(uid)}) and other not in wellbeing.hidden_prices(conn, at)


def test_off_the_notices_ask_nobody_out(database: str, fresh: None, monkeypatch: pytest.MonkeyPatch) -> None:
    client(READER).put("/api/v1/me/wellbeing", json={"football_only": True})
    monkeypatch.delenv(WELLBEING, raising=False)
    with psycopg.connect(database) as conn:
        assert wellbeing.hidden_prices(conn, datetime.now(UTC)) == frozenset()


def test_the_database_keeps_only_a_flag_and_a_date_and_the_account_forgets_it(database: str, fresh: None) -> None:
    client(READER).put("/api/v1/me/wellbeing", json={"football_only": True, "pause_days": 1})
    with psycopg.connect(database, autocommit=True) as conn:
        row = conn.execute("SELECT football_only, paused_until > now() + interval '23 hours', paused_until < now() + interval '25 hours' "
                           "FROM customer.wellbeing").fetchone()
        assert row == (True, True, True)
        uid = user_id(conn, READER)
        wellbeing.forget(conn, int(uid))
        left = conn.execute("SELECT count(*) FROM customer.wellbeing WHERE user_id = %s", (uid,)).fetchone()
        assert left is not None and left[0] == 0

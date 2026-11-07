"""The welcome tour and the guides of each screen against the migrated database (UX-027; PLAN_BIENVENIDA_RECORRIDO).

* The state reaches the page in GET /auth/me (``guides``, ``guides_on``, ``guides_auto``), empty for a new account.
* PUT /me/guides/{guide}: needs a session (401); a guide, version, status or step outside the closed lists is refused (422);
  idempotent; within a version the status never goes down («completed» is not erased by a replay that is skipped); a newer
  version starts the guide over and an older one (a PWA left open from before) changes nothing.
* The first guide of Perfil is owed: it cannot be skipped before it is completed (409) and, once completed, a skip changes
  nothing.
* Each reader sees and changes only their own; FBI_GUIDES=0 is told to the page and keeps what was recorded.
* ``guides_auto`` through PATCH /auth/me/preferences.
* What the account keeps: the guides are in the reader's export and go when the account is anonymised.
* The migration goes down while no reader has a row, and refuses when one has.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import anonymize, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import guides, privacy
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

READER = "lectora.ux027@example.org"
OTHER = "otro.ux027@example.org"
OWNER = "owner.ux027@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.guide_progress", "customer.favorites", "customer.messages_outbox",
                          "customer.preferences", "customer.ticket_messages", "customer.support_tickets",
                          "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_picks")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email, role in ((READER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.guide_progress")
        conn.execute("UPDATE customer.preferences SET guides_auto = TRUE")
    monkeypatch.delenv(guides.SWITCH, raising=False)
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def put(c: TestClient, guide: str, version: int = 1, status: str = "in_progress", step: int = 0) -> Any:
    return c.put(f"/api/v1/me/guides/{guide}", json={"version": version, "status": status, "step": step})


def mine(c: TestClient) -> dict[str, dict[str, Any]]:
    return {g["guide"]: g for g in c.get("/api/v1/auth/me").json()["guides"]}


def test_a_new_account_has_no_guide_seen_and_the_switches_on(fresh: str) -> None:
    me = client(READER).get("/api/v1/auth/me").json()
    assert (me["guides"], me["guides_on"], me["guides_auto"]) == ([], True, True)


def test_it_needs_a_session_and_the_closed_lists(fresh: str) -> None:
    anonymous = TestClient(create_app(), headers=SAME_SITE)
    assert put(anonymous, "picks").status_code == 401
    reader = client(READER)
    assert put(reader, "nothing").status_code == 422, "a guide the list does not have"
    assert put(reader, "picks", version=0).status_code == 422
    assert put(reader, "picks", version=100).status_code == 422
    assert put(reader, "picks", status="seen").status_code == 422
    assert put(reader, "picks", step=3).status_code == 422, "a screen has 3 steps (0 to 2)"
    assert put(reader, "profile", step=5).status_code == 200 and put(reader, "profile", step=6).status_code == 422
    assert reader.put("/api/v1/me/guides/picks", json={"version": 1, "status": "pending", "extra": 1}).status_code == 422
    assert mine(reader).keys() == {"profile"}, "nothing else was recorded"


def test_the_first_visit_then_started_then_completed(fresh: str) -> None:
    reader = client(READER)
    seen = put(reader, "picks", status="pending").json()
    assert (seen["status"], seen["started_at"], seen["first_seen_at"] is not None) == ("pending", None, True)
    started = put(reader, "picks", status="in_progress", step=1).json()
    assert (started["status"], started["step"]) == ("in_progress", 1) and started["started_at"] is not None
    assert started["first_seen_at"] == seen["first_seen_at"], "the first visit stays"
    done = put(reader, "picks", status="completed", step=2).json()
    assert done["status"] == "completed" and done["completed_at"] is not None and done["skipped_at"] is None
    again = put(reader, "picks", status="completed", step=2).json()
    assert again == done, "idempotent: the first moment stays"
    assert mine(reader)["picks"] == done


def test_within_a_version_the_status_never_goes_down(fresh: str) -> None:
    reader = client(READER)
    done = put(reader, "match", status="completed", step=2).json()
    assert put(reader, "match", status="skipped", step=0).json() == done, "a replay skipped does not erase «completed»"
    assert put(reader, "match", status="in_progress", step=1).json() == done
    assert put(reader, "match", status="pending").json() == done
    skipped = put(reader, "odds", status="skipped", step=1).json()
    assert skipped["status"] == "skipped" and skipped["skipped_at"] is not None and skipped["step"] == 1
    assert put(reader, "odds", status="in_progress", step=2).json() == skipped, "a paused replay does not undo a skip"
    assert put(reader, "odds", status="completed", step=2).json()["status"] == "completed"
    assert mine(reader)["odds"]["skipped_at"] is None


def test_a_newer_version_starts_over_and_an_older_one_changes_nothing(fresh: str) -> None:
    reader = client(READER)
    v1 = put(reader, "picks", version=2, status="completed", step=2).json()
    assert put(reader, "picks", version=1, status="skipped").json() == v1, "a PWA left open from before"
    v3 = put(reader, "picks", version=3, status="pending").json()
    assert (v3["version"], v3["status"], v3["completed_at"], v3["started_at"]) == (3, "pending", None, None)
    assert v3["first_seen_at"] == v1["first_seen_at"]
    assert put(reader, "picks", version=3, status="skipped", step=0).json()["status"] == "skipped"


def test_the_first_guide_of_profile_is_owed(fresh: str) -> None:
    reader = client(READER)
    refused = put(reader, "profile", status="skipped", step=2)
    assert refused.status_code == 409
    assert put(reader, "profile", status="in_progress", step=2).json()["step"] == 2, "every step is recorded"
    assert put(reader, "profile", status="in_progress", step=3).json()["step"] == 3
    assert put(reader, "profile", status="skipped", step=3).status_code == 409, "paused, not skipped"
    assert put(reader, "profile", status="completed", step=5).json()["status"] == "completed"
    assert put(reader, "profile", status="skipped", step=0).json()["status"] == "completed", "done stays done"
    newer = put(reader, "profile", version=2, status="skipped", step=0)
    assert newer.status_code == 200 and newer.json()["status"] == "skipped", "a new version of what was done is optional"
    assert put(client(OTHER), "profile", version=2, status="skipped").status_code == 409, "never done: still owed"


def test_each_reader_sees_and_changes_only_their_own(fresh: str) -> None:
    reader, other = client(READER), client(OTHER)
    put(reader, "picks", status="completed", step=2)
    put(reader, "general", status="skipped", step=1)
    assert mine(reader).keys() == {"general", "picks"}
    assert mine(other) == {}
    assert put(other, "picks", status="skipped", step=0).json()["status"] == "skipped"
    assert mine(reader)["picks"]["status"] == "completed"


def test_the_switch_is_told_to_the_page_and_keeps_what_was_recorded(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = client(READER)
    put(reader, "home", status="completed", step=2)
    monkeypatch.setenv(guides.SWITCH, "0")
    me = reader.get("/api/v1/auth/me").json()
    assert me["guides_on"] is False and [g["guide"] for g in me["guides"]] == ["home"]


def test_the_readers_own_switch(fresh: str, database: str) -> None:
    reader, other = client(READER), client(OTHER)
    off = reader.patch("/api/v1/auth/me/preferences", json={"guides_auto": False})
    assert off.status_code == 200 and off.json()["guides_auto"] is False
    assert reader.get("/api/v1/auth/me").json()["guides_auto"] is False
    assert other.get("/api/v1/auth/me").json()["guides_auto"] is True, "the reader's own"
    on = reader.patch("/api/v1/auth/me/preferences", json={"guides_auto": True, "language": "en"}).json()
    assert (on["guides_auto"], on["language"]) == (True, "en")
    assert reader.patch("/api/v1/auth/me/preferences", json={"guides_auto": "maybe"}).status_code == 422
    reader.patch("/api/v1/auth/me/preferences", json={"language": "es"})
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT guides_auto FROM customer.preferences WHERE user_id = %s",
                            (uid(database, READER),)).fetchone() == (True,)


def test_the_guides_are_in_the_export_and_go_when_the_account_is_anonymised(fresh: str, database: str) -> None:
    reader = client(OTHER)
    put(reader, "picks", status="completed", step=2)
    put(reader, "profile", status="in_progress", step=1)
    other_id, owner_id = uid(database, OTHER), uid(database, OWNER)
    with psycopg.connect(database) as conn:
        document = privacy.export(conn, other_id)
    assert [(g["guide"], g["version"], g["status"], g["step"]) for g in document["guides"]] == [
        ("picks", 1, "completed", 2), ("profile", 1, "in_progress", 1)]
    anonymize.anonymise(principal("SUPER_ADMIN", user_id=owner_id), other_id, confirm=OTHER, ip=None)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM customer.guide_progress WHERE user_id = %s",
                            (other_id,)).fetchone() == (0,)


def test_the_migration_goes_down_while_nobody_has_a_row_and_refuses_when_someone_has(fresh: str, database: str) -> None:
    cfg = Config("alembic.ini")
    uid_ = uid(database, READER)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.guide_progress (user_id, guide, version, status) VALUES (%s, 'picks', 1, 'pending')",
                     (uid_,))
    with pytest.raises(Exception, match="guide progress"):
        command.downgrade(cfg, "0124")
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.guide_progress")
    command.downgrade(cfg, "0124")
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT to_regclass('customer.guide_progress')").fetchone() == (None,)
    command.upgrade(cfg, "head")
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT to_regclass('customer.guide_progress')").fetchone() != (None,)

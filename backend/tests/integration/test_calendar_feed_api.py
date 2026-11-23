"""PM-14-06 (BE-084) through the API and a real database: off, every route of the calendar answers 404; on, a reader makes a secret link,
a calendar reads the fixtures of the teams they follow with it (and nothing else), the database keeps only the secret's hash, a new link
revokes the old one, revoking stops it, a client that keeps guessing is held back, and anonymising the account deletes the links."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.routers import calendar_feed as router
from fbi.api.switches import CALENDAR_FEED
from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import calendar_feed as feeds
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE

pytestmark = pytest.mark.integration

READER = "lectora.cal084@example.org"
OTHER = "otro.cal084@example.org"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
PROVIDER = range(7784000, 7784100)


def _wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for email in (READER, OTHER):
            uid = conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,)).fetchone()
            if uid is None:
                continue
            with conn.transaction():
                conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
                for table in ("customer.calendar_feeds", "customer.favorites", "customer.preferences", "customer.consents"):
                    conn.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid[0],))
            conn.execute("DELETE FROM auth.sessions WHERE user_id = %s", (uid[0],))
            conn.execute("DELETE FROM auth.audit_events WHERE actor_user_id = %s OR target_user_id = %s", (uid[0], uid[0]))
        conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN %s AND %s", (PROVIDER.start, PROVIDER.stop))
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN "
                     "(SELECT id FROM core.competitions WHERE provider_league_id BETWEEN %s AND %s)", (PROVIDER.start, PROVIDER.stop))
        conn.execute("DELETE FROM core.competitions WHERE provider_league_id BETWEEN %s AND %s", (PROVIDER.start, PROVIDER.stop))
        conn.execute("DELETE FROM core.teams WHERE provider_team_id BETWEEN %s AND %s", (PROVIDER.start, PROVIDER.stop))


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


@pytest.fixture(scope="module")
def world(database: str) -> dict[str, int]:
    """Two teams of one competition, the reader following one of them; three fixtures: soon, far, and one of other teams."""
    now = datetime.now(UTC)
    with psycopg.connect(database, autocommit=True) as conn:
        comp = scalar(conn.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                                   "competition_type, is_tracked) VALUES (7784001, 'Liga Calendario', 'Colombia', 'league', 'club', "
                                   "'domestic_league', true) RETURNING id"))
        cs = scalar(conn.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                                 "RETURNING id", (comp,)))
        teams = [int(scalar(conn.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                         (7784010 + i, name)))) for i, name in enumerate(("Club Seguido", "Club Rival", "Otro A", "Otro B"))]
        ids: dict[str, int] = {}
        for key, (h, a, days) in {"soon": (0, 1, 2), "far": (1, 0, 300), "others": (2, 3, 3)}.items():
            ids[key] = int(scalar(conn.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, round, "
                "status_short, status_group, venue_name, venue_city) VALUES (%s, %s, %s, %s, %s, 'Fecha 18', 'NS', 'scheduled', "
                "'Estadio Uno', 'Medellín') RETURNING id", (7784020 + len(ids), cs, teams[h], teams[a], now + timedelta(days=days)))))
        uid = scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (READER,)))
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'team', %s, %s)", (uid, teams[0], teams[0]))
    return {"user": int(uid), **ids}


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    throttle.reset_all()
    forget_sign_in_failures()
    router.MISSES._hits.clear()  # a clean window per test
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.calendar_feeds")
    monkeypatch.setenv(CALENDAR_FEED, "1")
    yield


def test_off_every_route_answers_404(database: str, world: dict[str, int], fresh: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CALENDAR_FEED, raising=False)
    c = client(READER)
    assert c.get("/api/v1/me/calendar-feed").status_code == 404
    assert c.post("/api/v1/me/calendar-feed").status_code == 404
    assert c.delete("/api/v1/me/calendar-feed").status_code == 404
    assert TestClient(create_app()).get(f"/api/v1/calendar/feed/{feeds.new_token()}.ics").status_code == 404


def test_a_link_reads_the_followed_teams_fixtures_and_only_its_hash_is_kept(database: str, world: dict[str, int], fresh: None) -> None:
    c = client(READER)
    assert c.get("/api/v1/me/calendar-feed").json() == {"active": False, "created_at": None, "last_read_at": None, "teams": 1}
    made = c.post("/api/v1/me/calendar-feed")
    assert made.status_code == 200, made.text
    path = made.json()["path"]
    token = path.rsplit("/", 1)[1].removesuffix(".ics")
    assert path.startswith("/api/v1/calendar/feed/") and feeds.looks_like_token(token)
    with psycopg.connect(database) as conn:
        stored = conn.execute("SELECT link_sha256, row_to_json(f)::text FROM customer.calendar_feeds f WHERE user_id = %s",
                              (world["user"],)).fetchall()
    assert len(stored) == 1 and stored[0][0] == feeds.token_id(token) and token not in stored[0][1]
    anonymous = TestClient(create_app())  # a calendar app: no session, no same-site header
    r = anonymous.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and f"UID:fixture-{world['soon']}@predigol" in body
    assert f"fixture-{world['far']}@" not in body, "beyond the window"
    assert f"fixture-{world['others']}@" not in body, "a team the reader does not follow"
    assert "Club Seguido vs Club Rival" in body and READER not in body and "lectora" not in body
    assert client(READER).get("/api/v1/me/calendar-feed").json()["last_read_at"] is not None


def test_a_new_link_revokes_the_old_one_and_revoking_stops_it(database: str, world: dict[str, int], fresh: None) -> None:
    c = client(READER)
    first = c.post("/api/v1/me/calendar-feed").json()["path"]
    second = c.post("/api/v1/me/calendar-feed").json()["path"]
    anonymous = TestClient(create_app())
    assert anonymous.get(first).status_code == 404 and anonymous.get(second).status_code == 200
    assert c.delete("/api/v1/me/calendar-feed").json()["active"] is False
    assert anonymous.get(second).status_code == 404
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT array_agg(revoked_why ORDER BY id) FROM customer.calendar_feeds WHERE user_id = %s",
                            (world["user"],)).fetchone() == (["replaced", "reader"],)


def test_another_reader_never_sees_the_link(database: str, world: dict[str, int], fresh: None) -> None:
    client(READER).post("/api/v1/me/calendar-feed")
    assert client(OTHER).get("/api/v1/me/calendar-feed").json()["active"] is False


def test_a_client_that_keeps_guessing_is_held_back(database: str, world: dict[str, int], fresh: None) -> None:
    anonymous = TestClient(create_app())
    answers = [anonymous.get(f"/api/v1/calendar/feed/{feeds.new_token()}.ics").status_code for _ in range(router.MISSES._max)]
    assert set(answers) == {404}
    assert anonymous.get(f"/api/v1/calendar/feed/{feeds.new_token()}.ics").status_code == 429
    assert anonymous.get("/api/v1/calendar/feed/not-a-token.ics").status_code == 429


def test_the_export_lists_the_links_without_their_secret(database: str, world: dict[str, int], fresh: None) -> None:
    from fbi.customer import privacy

    c = client(READER)
    token = c.post("/api/v1/me/calendar-feed").json()["path"].rsplit("/", 1)[1].removesuffix(".ics")
    with psycopg.connect(database) as conn:
        document = privacy.export(conn, world["user"])
    links = document["calendar_links"]
    assert len(links) == 1 and set(links[0]) == {"created_at", "revoked_at", "revoked_why", "last_read_at"}
    raw = str(document)
    assert token not in raw and feeds.token_id(token) not in raw


def test_anonymising_the_account_deletes_its_links(database: str, world: dict[str, int], fresh: None) -> None:
    client(READER).post("/api/v1/me/calendar-feed")
    with psycopg.connect(database) as conn:
        feeds.forget(conn, world["user"])
        assert conn.execute("SELECT count(*) FROM customer.calendar_feeds WHERE user_id = %s", (world["user"],)).fetchone() == (0,)
        conn.rollback()

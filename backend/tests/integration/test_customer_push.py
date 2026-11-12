"""The readers' notices on their devices against the migrated database (plan UX, B7 and section 34), signed in for real.

* Without PrediGol's key (P12), or with FBI_PUSH=0: nothing is offered (no key to subscribe with) and nothing is subscribed.
* Devices: a known push service only, keys that can encrypt; the same browser keeps its row, another account taking it
  replaces the first's; a reader stops only their own; at most ten live.
* Categories, the reader's own test (409 without a device, three a day), the bell of a match (15, 30 or 60 minutes; not
  started; within seven days).
* The jobs write each notice once, only for readers with a live device and the category on: a saved pick and a parlay
  settled, the line-ups of a followed team's match, the bell's reminder at its minute, the day's summary from 09:00, the
  membership's end within a day, a new sign-in.
* The dispatch: to every live device, encrypted for each; the quiet hours postpone, the expiry and a category switched off
  drop; the daily ceiling drops results, line-ups and summaries, never the reader's own reminder; 404 or 410 revoke the
  device; 5xx tries again later; a device failing again and again is revoked.
* What the account keeps: the export (never the push service's address nor the keys), anonymisation, retention.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.auth import account_mail, anonymize, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import privacy
from fbi.customer import push as rules
from fbi.messaging import push, push_jobs
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

READER = "lectora.b7@example.org"
OTHER = "otro.b7@example.org"
OWNER = "owner.b7@predigol.test"
PASSWORD = "Bright-lantern-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
KEY = push.new_private_key()
TEAMS = {"nacional": (7714011, "Atlético Nacional"), "millonarios": (7714012, "Millonarios"),
         "santafe": (7714013, "Santa Fe"), "junior": (7714014, "Junior")}
LEAGUE = (7714001, "Liga B7")


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        forget_memberships(conn)
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.messages_outbox", "customer.preferences", "customer.favorites",
                          "customer.ticket_messages", "customer.support_tickets", "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_parlays")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM auth.users")
        conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 7714100 AND 7714199")
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN "
                     "(SELECT id FROM core.competitions WHERE provider_league_id = %s)", (LEAGUE[0],))
        conn.execute("DELETE FROM core.competitions WHERE provider_league_id = %s", (LEAGUE[0],))
        conn.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", ([p for p, _ in TEAMS.values()],))
        conn.execute("DELETE FROM raw.ingestion_payloads WHERE hash = 'pushB7'")


class World:
    """The committed football of this module: one league, four teams, matches to be created by the tests."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.ids: dict[str, int] = {}
        self.n = 7714100
        with psycopg.connect(dsn, autocommit=True) as conn:
            self.league = int(scalar(conn.execute(
                "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                "is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id", LEAGUE)))
            self.season = int(scalar(conn.execute(
                "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                "RETURNING id", (self.league,))))
            for key, (provider, name) in TEAMS.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (provider, name))))
            run = scalar(conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                                      "VALUES ('test', 'test_b7', 'completed', now()) RETURNING id"))
            conn.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                         "bytes) VALUES ('pushB7', %s, '/fixtures/lineups', now(), 200, 'x', 1)", (run,))

    def match(self, home: str, away: str, kickoff: datetime, group: str = "scheduled") -> int:
        self.n += 1
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            return int(scalar(conn.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_group) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (self.n, self.season, self.ids[home], self.ids[away], kickoff, group))))

    def lineups(self, fixture: int, sides: tuple[str, ...] = ("home", "away")) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            for side in sides:
                conn.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, payload_hash, "
                             "fetched_at) VALUES (%s, %s, 'api-football', '4-3-3', 'pushB7', now())", (fixture, side))


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


@pytest.fixture(scope="module")
def world(database: str) -> World:
    return World(database)


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    with psycopg.connect(database, autocommit=True) as conn:
        for table in ("customer.push_notices", "customer.match_alerts", "customer.push_subscriptions"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE customer.preferences SET push_off = '{}'")
        conn.execute("DELETE FROM picks.user_parlays")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM customer.favorites")
    monkeypatch.delenv(rules.SWITCH, raising=False)
    monkeypatch.delenv(push.HOSTS_ENV, raising=False)
    monkeypatch.setenv(push.KEY_ENV, KEY)
    yield database


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def code(r: Any) -> str:
    return str(r.json().get("error", {}).get("code"))


class Browser:
    """A browser's subscription, as PushSubscription.toJSON() gives it, with the device's private key to read its notices."""

    def __init__(self, endpoint: str | None = None) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        point = self.private.public_key().public_bytes(serialization.Encoding.X962,
                                                       serialization.PublicFormat.UncompressedPoint)
        self.p256dh = push.b64url_encode(point)
        self.auth = push.b64url_encode(uuid.uuid4().bytes)
        self.endpoint = endpoint or f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"

    def body(self, **extra: Any) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}, "family": "chrome",
                "system": "android", **extra}

    def read(self, content: bytes) -> dict[str, Any]:
        return dict(json.loads(push.decrypt(content, self.private, self.auth)))


def notices(dsn: str, user: int) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return list(cur.execute("SELECT category, dedup_key, title, body, url, status, devices, dropped, not_before, "
                                "expires_at FROM customer.push_notices WHERE user_id = %s ORDER BY id", (user,)).fetchall())


def run_jobs(dsn: str, at: datetime) -> push_jobs.JobsReport:
    with psycopg.connect(dsn) as conn:
        return push_jobs.collect(conn, at=at)


Handler = Callable[[httpx.Request], httpx.Response]


def dispatch(dsn: str, at: datetime, handler: Handler | None = None) -> tuple[push_jobs.DispatchReport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request) if handler else httpx.Response(201)
    with psycopg.connect(dsn) as conn, httpx.Client(transport=httpx.MockTransport(record)) as http:
        report = push_jobs.dispatch(conn, at=at, client=http)
    return report, seen


# ── what is offered, and when nothing is ──────────────────────────────────────────────────────────────────────────────


def test_without_the_owners_key_or_with_the_switch_off_nothing_is_offered_nor_subscribed(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = client(READER)
    state = reader.get("/api/v1/me/push").json()
    assert state["available"] is True and len(push.b64url_decode(state["public_key"])) == 65
    assert (state["quiet_start"], state["quiet_end"], state["daily_cap"]) == ("22:00", "08:00", 3)
    assert state["categories"] == {"result": True, "lineup": True, "digest": True, "account": True}
    monkeypatch.delenv(push.KEY_ENV)
    state = reader.get("/api/v1/me/push").json()
    assert (state["available"], state["public_key"]) == (False, None), "no key (P12): nothing offered"
    r = reader.post("/api/v1/me/push/devices", json=Browser().body())
    assert (r.status_code, code(r)) == (404, "push_off")
    monkeypatch.setenv(push.KEY_ENV, KEY)
    monkeypatch.setenv(rules.SWITCH, "0")
    assert reader.get("/api/v1/me/push").json()["available"] is False, "FBI_PUSH=0"
    assert (reader.post("/api/v1/me/push/test").status_code, run_jobs(fresh, datetime.now(UTC)).total) == (404, 0)


# ── devices ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_browser_is_subscribed_once_only_with_a_known_push_service_and_usable_keys(fresh: str) -> None:
    reader, other = client(READER), client(OTHER)
    me, them = uid(fresh, READER), uid(fresh, OTHER)
    phone = Browser()
    r = reader.post("/api/v1/me/push/devices", json=phone.body(installed=True))
    assert r.status_code == 201, r.text
    device = r.json()
    assert (device["family"], device["system"], device["installed"]) == ("chrome", "android", True)
    again = reader.post("/api/v1/me/push/devices", json=phone.body())
    assert again.json()["id"] == device["id"] and again.json()["installed"] is True, "the same browser, the same row"
    bad = [("https://evil.example/push/1", phone.p256dh, phone.auth, "unknown_push_service"),
           ("http://fcm.googleapis.com/fcm/send/x", phone.p256dh, phone.auth, "unknown_push_service"),
           ("https://fcm.googleapis.com/fcm/send/y", "B" + "A" * 86, phone.auth, "bad_key")]
    for endpoint, p256dh, auth, why in bad:
        r = reader.post("/api/v1/me/push/devices", json={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}})
        assert (r.status_code, code(r)) == (422, why), endpoint
    # a shared device: another account signs in on the same browser - it is theirs now, no longer the first's
    taken = other.post("/api/v1/me/push/devices", json=phone.body())
    assert taken.status_code == 201 and taken.json()["id"] != device["id"]
    with psycopg.connect(fresh) as conn:
        rows = conn.execute("SELECT user_id, revoked_reason FROM customer.push_subscriptions ORDER BY id").fetchall()
    assert rows == [(me, "replaced"), (them, None)]
    assert reader.get("/api/v1/me/push").json()["devices"] == []
    # a reader stops only their own: by address from that browser, by id from the list
    laptop = Browser("https://updates.push.services.mozilla.com/wpush/v2/" + uuid.uuid4().hex)
    mine = reader.post("/api/v1/me/push/devices", json=laptop.body(family="firefox", system="windows")).json()
    assert reader.post("/api/v1/me/push/devices/stop", json={"device_id": taken.json()["id"]}).status_code == 204
    assert len(other.get("/api/v1/me/push").json()["devices"]) == 1, "another reader's device is not mine to stop"
    assert reader.post("/api/v1/me/push/devices/stop", json={"device_id": mine["id"]}).status_code == 204
    assert reader.get("/api/v1/me/push").json()["devices"] == []
    assert other.post("/api/v1/me/push/devices/stop", json={"endpoint": phone.endpoint}).status_code == 204
    assert other.get("/api/v1/me/push").json()["devices"] == []


def test_at_most_ten_live_browsers_the_oldest_gives_way(fresh: str) -> None:
    reader = client(READER)
    ids = [reader.post("/api/v1/me/push/devices", json=Browser().body()).json()["id"] for _ in range(rules.MAX_DEVICES + 2)]
    live = [d["id"] for d in reader.get("/api/v1/me/push").json()["devices"]]
    assert sorted(live) == sorted(ids[2:])


def test_categories_the_test_and_the_bell(fresh: str, world: World) -> None:
    reader = client(READER)
    r = reader.put("/api/v1/me/push/categories", json={"digest": False, "lineup": False})
    assert r.json() == {"result": True, "lineup": False, "digest": False, "account": True}
    assert reader.put("/api/v1/me/push/categories", json={"lineup": True}).json()["lineup"] is True
    assert reader.put("/api/v1/me/push/categories", json={"spam": True}).status_code == 422
    r = reader.post("/api/v1/me/push/test")
    assert (r.status_code, code(r)) == (409, "no_device")
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    for _ in range(rules.TESTS_PER_DAY):
        assert reader.post("/api/v1/me/push/test").status_code == 201
    r = reader.post("/api/v1/me/push/test")
    assert (r.status_code, code(r)) == (429, "too_many_tests")
    now = datetime.now(UTC)
    soon = world.match("nacional", "millonarios", now + timedelta(hours=5))
    far = world.match("santafe", "junior", now + timedelta(days=9))
    started = world.match("junior", "nacional", now - timedelta(minutes=5), "live")
    assert reader.get(f"/api/v1/me/match-alerts/{soon}").json()["on"] is False
    r = reader.put(f"/api/v1/me/match-alerts/{soon}", json={"minutes_before": 60})
    assert r.status_code == 200 and (r.json()["on"], r.json()["minutes_before"]) == (True, 60)
    assert reader.put(f"/api/v1/me/match-alerts/{soon}", json={"minutes_before": 15}).json()["minutes_before"] == 15
    assert reader.put(f"/api/v1/me/match-alerts/{soon}", json={"minutes_before": 45}).status_code == 422
    for fixture, why in ((far, "too_far"), (started, "match_started")):
        r = reader.put(f"/api/v1/me/match-alerts/{fixture}", json={"minutes_before": 30})
        assert (r.status_code, code(r)) == (422, why)
    assert reader.put("/api/v1/me/match-alerts/999999999", json={}).status_code == 404
    assert reader.delete(f"/api/v1/me/match-alerts/{soon}").status_code == 204
    assert reader.get(f"/api/v1/me/match-alerts/{soon}").json()["on"] is False


# ── the jobs ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def save(dsn: str, user: int, fixture: int, status: str, settled: datetime | None, *, line: int = 0) -> int:
    """A pick the reader saved (one per line: the table keeps one per market, selection and line)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        return int(scalar(conn.execute("""
            INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, snapshot, saved_at,
                                          status, profit_units, settled_at)
            VALUES (%s, %s, '1X2', 'Home', %s, 'market', 2.1, '{}', %s, %s, %s, %s) RETURNING id
        """, (user, fixture, line, (settled or datetime.now(UTC)) - timedelta(hours=4), status,
              1.1 if status == "WIN" else (-1 if status == "LOSS" else None), settled))))


def test_a_settled_pick_and_parlay_are_told_once_to_a_reader_with_a_device_and_the_category_on(fresh: str,
                                                                                              world: World) -> None:
    reader = client(READER)
    me, them = uid(fresh, READER), uid(fresh, OTHER)
    at = datetime.now(UTC)
    played = world.match("nacional", "millonarios", at - timedelta(hours=3), "finished")
    won = save(fresh, me, played, "WIN", at - timedelta(minutes=30))
    save(fresh, me, played, "PENDING", None, line=1)
    save(fresh, me, played, "LOSS", at - timedelta(days=2), line=2)  # settled long ago: not news any more
    save(fresh, them, played, "WIN", at - timedelta(minutes=30))  # a reader without a device: nothing
    with psycopg.connect(fresh, autocommit=True) as conn:
        parlay = int(scalar(conn.execute(
            "INSERT INTO picks.user_parlays (user_id, name, created_at, combined_odds, validation, status, profit_units, "
            "settled_at) VALUES (%s, 'Sábado', %s, 3.4, '{}', 'LOST', -1, %s) RETURNING id",
            (me, at - timedelta(hours=6), at - timedelta(minutes=20)))))
    assert run_jobs(fresh, at).results == 0, "no device: nothing written"
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    report = run_jobs(fresh, at)
    assert report.results == 2 and report.errors == []
    rows = notices(fresh, me)
    assert [(n["category"], n["dedup_key"], n["title"], n["url"]) for n in rows] == [
        ("result", f"result:pick:{won}", "Ganado: tu pick de Atlético Nacional\u2013Millonarios", f"/matches/{played}#postmatch"),
        ("result", f"result:parlay:{parlay}", "Perdido: tu parlay «Sábado»", "/my-picks")]
    assert run_jobs(fresh, at).results == 0, "each once"
    assert notices(fresh, them) == []
    reader.put("/api/v1/me/push/categories", json={"result": False})
    save(fresh, me, played, "WIN", at - timedelta(minutes=5), line=3)
    assert run_jobs(fresh, at).results == 0, "the category off: nothing written"


def test_line_ups_of_a_followed_teams_match_the_bells_reminder_and_the_days_summary(fresh: str, world: World) -> None:
    reader = client(READER)
    me = uid(fresh, READER)
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'team', %s, %s)",
                     (me, world.ids["nacional"], world.ids["nacional"]))
    # 09:30 in Bogotá: the summary's hour
    at = datetime(2026, 11, 3, 14, 30, tzinfo=UTC)
    soon = world.match("millonarios", "nacional", at + timedelta(hours=2))
    later = world.match("nacional", "santafe", at + timedelta(hours=8))
    other = world.match("santafe", "junior", at + timedelta(hours=1))
    world.lineups(soon)
    world.lineups(later)  # out early, but the match is 8 hours away: not yet
    world.lineups(other, ("home",))
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.match_alerts (user_id, fixture_id, minutes_before) VALUES (%s, %s, 30)",
                     (me, other))
    report = run_jobs(fresh, at)
    assert (report.lineups, report.reminders, report.digests, report.errors) == (1, 0, 1, [])
    rows = {n["category"]: n for n in notices(fresh, me)}
    assert rows["lineup"]["dedup_key"] == f"lineup:{soon}" and rows["lineup"]["url"] == f"/matches/{soon}#lineups"
    assert rows["lineup"]["body"] == "Empieza a las 11:30." and rows["lineup"]["expires_at"] == at + timedelta(hours=2)
    assert rows["digest"]["dedup_key"] == "digest:2026-11-03" and rows["digest"]["url"] == "/home"
    assert rows["digest"]["body"] == "Millonarios\u2013Atlético Nacional y 1 partido más: mira su análisis."
    # the bell: queued ten minutes before its minute, to go at that minute
    lead = run_jobs(fresh, at + timedelta(minutes=22))
    assert lead.reminders == 1
    reminder = next(n for n in notices(fresh, me) if n["category"] == "reminder")
    assert (reminder["dedup_key"], reminder["not_before"], reminder["title"]) == (
        f"reminder:{other}:30", at + timedelta(minutes=30), "Empieza en 30 minutos")
    assert run_jobs(fresh, at + timedelta(minutes=40)).total == 0, "each once, the summary once a day"


def test_a_followed_team_with_its_bell_off_gets_no_line_up_notice_and_stays_out_of_the_summary(
        fresh: str, world: World) -> None:
    """Decision 8 of the plan maestro UX/UI 2026 (BE-039): the bell of a followed team. The reminder a reader asked of a
    match is theirs whatever the bell says."""
    reader = client(READER)
    me = uid(fresh, READER)
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id, notify) "
                     "VALUES (%s, 'team', %s, %s, false)", (me, world.ids["nacional"], world.ids["nacional"]))
    at = datetime(2026, 11, 3, 14, 30, tzinfo=UTC)
    soon = world.match("millonarios", "nacional", at + timedelta(hours=2))
    other = world.match("santafe", "junior", at + timedelta(hours=1))
    world.lineups(soon)
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.match_alerts (user_id, fixture_id, minutes_before) VALUES (%s, %s, 30)",
                     (me, other))
    report = run_jobs(fresh, at)
    assert (report.lineups, report.digests, report.errors) == (0, 0, []), "the bell is off: neither notice"
    assert run_jobs(fresh, at + timedelta(minutes=22)).reminders == 1, "the reminder they asked for still goes"
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE customer.favorites SET notify = true WHERE user_id = %s", (me,))
    again = run_jobs(fresh, at + timedelta(minutes=23))
    assert again.lineups >= 1 and again.digests == 1, "on again: the notices come back"


def test_the_summary_waits_for_09_00_and_the_membership_and_a_new_sign_in_are_the_accounts(fresh: str,
                                                                                           world: World) -> None:
    reader = client(READER)
    me = uid(fresh, READER)
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
                     (me, world.league, world.league))
    early = datetime(2026, 11, 4, 12, 30, tzinfo=UTC)  # 07:30 in Bogotá
    world.match("junior", "santafe", early + timedelta(hours=9))
    assert run_jobs(fresh, early).digests == 0, "before 09:00"
    at = datetime.now(UTC)
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, created_at, reason) "
                     "VALUES (%s, 'courtesy', %s, %s, %s, 'por la prueba')",
                     (me, at - timedelta(days=29), at + timedelta(hours=12), at - timedelta(days=29)))
    assert run_jobs(fresh, at).membership == 1
    assert run_jobs(fresh, at).membership == 0, "once per period"
    notice = next(n for n in notices(fresh, me) if n["category"] == "account")
    assert (notice["title"], notice["url"]) == ("Tu membresía vence mañana", "/profile#membership")
    # a sign-in from a browser the account had not used: on its devices too (the e-mail needs FBI_SELF_SERVICE)
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE auth.sessions SET user_agent = 'Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0' "
                     "WHERE user_id = %s", (me,))
        user = conn.execute("SELECT id, email, language, timezone FROM auth.users WHERE id = %s", (me,)).fetchone()
        assert user is not None
        told = account_mail.notify_new_device(
            conn, {"id": user[0], "email": user[1], "language": user[2], "timezone": user[3]},
            session_id="s" * 40, user_agent="Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36")
    assert told is True
    sign_in = next(n for n in notices(fresh, me) if n["dedup_key"].startswith("account:sign_in:"))
    assert (sign_in["title"], sign_in["body"]) == ("Nuevo inicio de sesión en tu cuenta",
                                                   "Desde Chrome en Android. ¿No fuiste tú? Revisa tu seguridad.")


# ── the dispatch ──────────────────────────────────────────────────────────────────────────────────────────────────────


def queue(dsn: str, user: int, category: str, key: str, at: datetime, *, expires: timedelta = timedelta(hours=6),
          not_before: datetime | None = None) -> int | None:
    with psycopg.connect(dsn) as conn:
        got = rules.queue(conn, user_id=user, category=category, key=key, title=f"Título {key}",  # type: ignore[arg-type]
                          body="Una línea.", url="/my-picks", at=at, expires_at=at + expires, zone="America/Bogota",
                          not_before=not_before)
        conn.commit()
    return got


def test_a_notice_reaches_every_live_device_encrypted_for_each(fresh: str) -> None:
    reader = client(READER)
    me = uid(fresh, READER)
    phone, laptop = Browser(), Browser("https://web.push.apple.com/" + uuid.uuid4().hex)
    reader.post("/api/v1/me/push/devices", json=phone.body())
    reader.post("/api/v1/me/push/devices", json=laptop.body(family="safari", system="ios", installed=True))
    noon = datetime(2026, 11, 5, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
    queue(fresh, me, "result", "result:pick:1", noon)
    report, seen = dispatch(fresh, noon)
    assert (report.sent, report.devices) == (1, 2)
    by_endpoint = {str(r.url): r for r in seen}
    for browser in (phone, laptop):
        request = by_endpoint[browser.endpoint]
        assert browser.read(request.content) == {"title": "Título result:pick:1", "body": "Una línea.", "url": "/my-picks",
                                                 "tag": "result:pick:1", "category": "result"}
        assert request.headers["authorization"].startswith("vapid t=")
    [n] = notices(fresh, me)
    assert (n["status"], n["devices"]) == ("sent", 2)
    assert dispatch(fresh, noon + timedelta(minutes=1))[1] == [], "sent once"


def test_quiet_hours_postpone_the_expiry_and_a_category_off_drop_the_ceiling_spares_the_readers_reminder(fresh: str) -> None:
    reader = client(READER)
    me = uid(fresh, READER)
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    night = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)  # 23:00 in Bogotá
    # written in the quiet hours, it waits for 08:00 - and is dropped if it is no use by then
    queue(fresh, me, "lineup", "lineup:1", night, expires=timedelta(hours=12))
    assert queue(fresh, me, "lineup", "lineup:2", night, expires=timedelta(hours=2)) is None, "useless by 08:00: not written"
    [waiting] = notices(fresh, me)
    assert waiting["not_before"] == datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    # the reader's own reminder goes at its minute, quiet hours or not
    queue(fresh, me, "reminder", "reminder:7:30", night)
    report, seen = dispatch(fresh, night)
    assert report.sent == 1 and len(seen) == 1
    morning = datetime(2026, 11, 6, 13, 5, tzinfo=UTC)
    reader.put("/api/v1/me/push/categories", json={"digest": False})
    queue(fresh, me, "digest", "digest:2026-11-06", morning)
    for i in range(3):
        queue(fresh, me, "result", f"result:pick:{100 + i}", morning)
    queue(fresh, me, "account", "account:membership:9", morning)
    queue(fresh, me, "reminder", "reminder:8:15", morning)
    report, seen = dispatch(fresh, morning)
    by_key = {n["dedup_key"]: n for n in notices(fresh, me)}
    assert by_key["digest:2026-11-06"]["dropped"] == "category_off"
    # three a day of results, line-ups and summaries - the line-ups waiting since the night first
    assert [by_key[k]["status"] for k in ("lineup:1", "result:pick:100", "result:pick:101", "result:pick:102")] == [
        "sent", "sent", "sent", "dropped"]
    assert by_key["result:pick:102"]["dropped"] == "daily_cap"
    assert by_key["account:membership:9"]["status"] == by_key["reminder:8:15"]["status"] == "sent", "not counted"
    expired_at = morning + timedelta(hours=7)
    queue(fresh, me, "result", "result:pick:200", expired_at - timedelta(hours=7), expires=timedelta(hours=1))
    dispatch(fresh, expired_at)
    assert {n["dedup_key"]: n for n in notices(fresh, me)}["result:pick:200"]["dropped"] == "expired"


def test_a_device_gone_is_revoked_a_server_error_tries_later_and_a_failing_device_is_revoked(fresh: str) -> None:
    reader = client(READER)
    me = uid(fresh, READER)
    gone, flaky = Browser(), Browser()
    reader.post("/api/v1/me/push/devices", json=gone.body())
    reader.post("/api/v1/me/push/devices", json=flaky.body())
    noon = datetime(2026, 11, 7, 17, 0, tzinfo=UTC)

    def answers(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410 if str(request.url) == gone.endpoint else 503)
    queue(fresh, me, "result", "result:pick:1", noon)
    report, _ = dispatch(fresh, noon, answers)
    assert (report.gone, report.later, report.sent) == (1, 1, 0)
    with psycopg.connect(fresh) as conn:
        states: dict[str, str | None] = dict(conn.execute(
            "SELECT endpoint, revoked_reason FROM customer.push_subscriptions").fetchall())
        failures = scalar(conn.execute("SELECT failures FROM customer.push_subscriptions WHERE endpoint = %s",
                                       (flaky.endpoint,)))
    assert states == {gone.endpoint: "gone", flaky.endpoint: None} and failures == 1
    [n] = notices(fresh, me)
    assert (n["status"], n["not_before"]) == ("queued", noon + push_jobs.RETRY_IN), "tried again in five minutes"
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE customer.push_subscriptions SET failures = %s WHERE endpoint = %s",
                     (push_jobs.MAX_FAILURES - 1, flaky.endpoint))
    dispatch(fresh, noon + push_jobs.RETRY_IN, answers)
    with psycopg.connect(fresh) as conn:
        assert scalar(conn.execute("SELECT revoked_reason FROM customer.push_subscriptions WHERE endpoint = %s",
                                   (flaky.endpoint,))) == "failing"
    assert notices(fresh, me)[0]["dropped"] == "failed"


# ── what the account keeps ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_export_never_carries_the_address_or_the_keys_anonymising_takes_everything_and_old_rows_go(
        fresh: str, world: World) -> None:
    reader = client(READER)
    me, owner = uid(fresh, READER), uid(fresh, OWNER)
    phone = Browser()
    reader.post("/api/v1/me/push/devices", json=phone.body())
    soon = world.match("nacional", "junior", datetime.now(UTC) + timedelta(days=1))
    reader.put(f"/api/v1/me/match-alerts/{soon}", json={"minutes_before": 30})
    reader.post("/api/v1/me/push/test")
    with psycopg.connect(fresh) as conn:
        document = privacy.export(conn, me)
    raw = json.dumps(document, default=str)
    assert [d["family"] for d in document["push_devices"]] == ["chrome"]
    assert [a["fixture_id"] for a in document["match_alerts"]] == [soon]
    assert [n["category"] for n in document["push_notices"]] == ["test"]
    for secret in (phone.endpoint, phone.p256dh, phone.auth):
        assert secret not in raw
    # retention: notices past 90 days and devices revoked 30 days ago - counted dry, deleted on, never what is fresh
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE customer.push_notices SET created_at = now() - interval '91 days', "
                     "expires_at = now() - interval '90 days', status = 'dropped', dropped = 'expired' WHERE user_id = %s", (me,))
        conn.execute("INSERT INTO customer.push_subscriptions (user_id, endpoint, p256dh, auth, family, system, created_at, "
                     "revoked_at, revoked_reason) VALUES (%s, %s, %s, %s, 'other', 'other', now() - interval '60 days', "
                     "now() - interval '31 days', 'gone')", (me, Browser().endpoint, phone.p256dh, phone.auth))
    with psycopg.connect(fresh) as conn:
        assert rules.purge(conn, at=datetime.now(UTC), mode="dry") == rules.PurgeReport("dry", 1, 1)
        assert rules.purge(conn, at=datetime.now(UTC), mode="on") == rules.PurgeReport("on", 1, 1)
        conn.commit()
        assert scalar(conn.execute("SELECT count(*) FROM customer.push_subscriptions WHERE user_id = %s", (me,))) == 1
    anonymize.anonymise(principal("SUPER_ADMIN", user_id=owner), me, confirm=READER, ip=None)
    with psycopg.connect(fresh) as conn:
        for table in ("customer.push_subscriptions", "customer.match_alerts", "customer.push_notices"):
            assert scalar(conn.execute(f"SELECT count(*) FROM {table} WHERE user_id = %s", (me,))) == 0, table
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET email = %s, status = 'active' WHERE id = %s", (READER, me))
        conn.execute("UPDATE auth.users SET password_hash = (SELECT password_hash FROM auth.users WHERE id = %s) "
                     "WHERE id = %s", (uid(fresh, OTHER), me))  # the module's next tests sign in as the reader again


def test_the_owners_view_counts_devices_and_notices_and_a_reader_cannot_open_it(fresh: str) -> None:
    reader, owner = client(READER), client(OWNER)
    reader.post("/api/v1/me/push/devices", json=Browser().body())
    reader.post("/api/v1/me/push/test")
    view = owner.get("/api/v1/admin/product/push")
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["available"] is True and body["readers"] == 1
    assert body["devices"] == [{"family": "chrome", "system": "android", "devices": 1}]
    assert body["notices"] == [{"category": "test", "sent": 0, "dropped": 0}]
    assert reader.get("/api/v1/admin/product/push").status_code == 403

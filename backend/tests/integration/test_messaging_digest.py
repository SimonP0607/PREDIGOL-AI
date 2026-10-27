"""The weekly summary by e-mail against the migrated database (plan UX, B8; section 33), the provider simulated.

* The box: offered only while the summary can reach the reader (FBI_DIGEST, the e-mail on and the commercial sender);
  asking for it otherwise is refused; leaving it is always possible, and a reader who asked for it still sees it to leave.
* Only consenting readers get it: on their day, from 09:00 in their zone, once a week, never the owner nor the robot,
  never an address that bounced; at most the day's cap.
* What it says: the week's settled picks of the reader (counts), their teams' matches of the next seven days and the
  week's Novedades - written into the queue as counts, never a name or an odd.
* When it leaves: by its own sender, with the one-click headers (RFC 8058) and a leaving link of its own; the consent
  checked again - a reader who left a minute ago, the switch off or the sender gone: suppressed.
* The one-click leaving: a POST without a session or an Origin (a mail client's) withdraws the consent at once (source
  ``email``, the text's version and sha256), a second click changes nothing, a forged link nothing at all - and it works
  with the summary switched off. The page the e-mail's link opens posts the token in the body (never in an address), from
  PrediGol's own pages only; a client that keeps presenting links that do not work is cut short.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from fbi.api.app import create_app
from fbi.api.routers import messaging as messaging_router
from fbi.auth import service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, legal
from fbi.messaging import digest, outbox, unsubscribe
from fbi.messaging.provider import Outgoing
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE

READER = "lector.b8@example.org"
READER_EN = "reader.b8@example.org"
OTHER = "otra.b8@example.org"
OWNER = "owner.b8@predigol.test"
ROBOT = "robot.b8@predigol.test"
PASSWORD = "Weekly-letter-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
TEAMS = {"nacional": (7718011, "Atlético Nacional"), "millonarios": (7718012, "Millonarios"),
         "medellin": (7718013, "Independiente Medellín")}
LEAGUE = (7718001, "Liga B8")
ACCOUNT_FROM = "PrediGol <hola@mail.predigol.example>"
COMMERCIAL_FROM = "PrediGol <resumen@news.predigol.example>"


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        forget_memberships(conn)
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.messages_outbox", "customer.favorites", "customer.preferences", "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_picks")
        conn.execute("DELETE FROM auth.users")
        conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 7718100 AND 7718199")
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN "
                     "(SELECT id FROM core.competitions WHERE provider_league_id = %s)", (LEAGUE[0],))
        conn.execute("DELETE FROM core.competitions WHERE provider_league_id = %s", (LEAGUE[0],))
        conn.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", ([p for p, _ in TEAMS.values()],))


class World:
    """One league, three teams; matches made by the tests."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.ids: dict[str, int] = {}
        self.n = 7718100
        with psycopg.connect(dsn, autocommit=True) as conn:
            league = int(scalar(conn.execute(
                "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                "is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id", LEAGUE)))
            self.season = int(scalar(conn.execute(
                "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                "RETURNING id", (league,))))
            for key, (provider, name) in TEAMS.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (provider, name))))

    def match(self, home: str, away: str, kickoff: datetime, group: str = "scheduled") -> int:
        self.n += 1
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            return int(scalar(conn.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_group) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (self.n, self.season, self.ids[home], self.ids[away], kickoff, group))))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    mp.setenv("FBI_SYNTHETIC_EMAIL", ROBOT)
    mp.setenv("FBI_WEB_BASE_URL", "https://predigol.example")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email, role, lang in ((READER, "USER", "es"), (READER_EN, "USER", "en"), (OTHER, "USER", "es"),
                              (OWNER, "SUPER_ADMIN", "es"), (ROBOT, "USER", "es")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language=lang, timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture(scope="module")
def world(database: str) -> World:
    return World(database)


def on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three things the summary needs: its switch, the e-mail on and its own sender."""
    monkeypatch.setenv(digest.ENV, "1")
    monkeypatch.setenv("FBI_EMAIL_SEND", "1")
    monkeypatch.setenv("FBI_EMAIL_FROM", ACCOUNT_FROM)
    monkeypatch.setenv(digest.FROM_ENV, COMMERCIAL_FROM)


@pytest.fixture()
def fresh(database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    throttle.reset_all()
    forget_sign_in_failures()
    monkeypatch.setattr(messaging_router, "LEAVE_TRIES", throttle.FailureWindow(max_failures=20, window_s=900))
    with psycopg.connect(database, autocommit=True) as conn, conn.transaction():
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        for table in ("customer.messages_outbox", "customer.favorites", "customer.preferences", "customer.consents"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM picks.user_picks")
    consents._clear.clear()
    for name in (digest.ENV, "FBI_EMAIL_SEND", digest.FROM_ENV, digest.CAP_ENV, consents.GATE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FBI_EMAIL_FROM", ACCOUNT_FROM)
    yield database
    consents._clear.clear()


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


def grant(email: str, dsn: str, granted: bool = True) -> None:
    consents.record(uid(dsn, email), [consents.Decision("marketing_email", granted, legal.current("privacy").version)],
                    locale="es", source="profile")


def latest(dsn: str, user: int) -> dict[str, Any] | None:
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM customer.consents WHERE user_id = %s AND kind = 'marketing_email' "
                    "ORDER BY at DESC, id DESC LIMIT 1", (user,))
        return cur.fetchone()


def summaries(dsn: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM customer.messages_outbox WHERE template = 'weekly_digest' ORDER BY id")
        return list(cur.fetchall())


def day_of_reader(user: int, hour_utc: int = 15) -> datetime:
    """A moment on this reader's day of the week (10:00 in Bogotá with hour 15)."""
    base = datetime(2026, 10, 26, hour_utc, 0, tzinfo=UTC)  # a Monday
    return base + timedelta(days=digest.day_of(user))


def soon(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """A moment just ahead of the clock (the queue stamps its rows with the real time, and a summary older than two days
    is not sent), at 15:00 UTC - 10:00 in Bogotá - made every reader's day."""
    now = datetime.now(UTC)
    at = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if at <= now + timedelta(minutes=5):
        at += timedelta(days=1)
    weekday = at.astimezone(digest._zone("America/Bogota")).weekday()
    monkeypatch.setattr(digest, "day_of", lambda _user: weekday)
    return at


def run_queue(dsn: str, at: datetime) -> digest.DigestReport:
    with psycopg.connect(dsn) as conn:
        return digest.queue(conn, at=at)


class Sink:
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[Outgoing] = []

    def send(self, message: Outgoing) -> str:
        self.sent.append(message)
        return f"prov-{uuid.uuid4().hex}"


def send_all(dsn: str, at: datetime) -> tuple[Sink, outbox.DispatchReport]:
    sink = Sink()
    with psycopg.connect(dsn) as conn:
        report = outbox.dispatch(conn, sink, at=at)
    return sink, report


# ── the box ───────────────────────────────────────────────────────────────────────────

def test_the_box_is_offered_only_while_the_summary_can_reach_the_reader(fresh: str,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    reader = client(READER)
    kinds = lambda: [p["kind"] for p in reader.get("/api/v1/me/consents?lang=es").json()["purposes"]]  # noqa: E731
    version = legal.current("privacy").version
    ask = {"decisions": [{"kind": "marketing_email", "granted": True, "version": version}], "locale": "es",
           "source": "profile"}
    assert "marketing_email" not in kinds(), "born off: no box that promises nothing"
    r = reader.post("/api/v1/me/consents", json=ask)
    assert (r.status_code, code(r)) == (422, "not_offered")
    on(monkeypatch)
    purposes = {p["kind"]: p for p in reader.get("/api/v1/me/consents?lang=es").json()["purposes"]}
    box = purposes["marketing_email"]
    assert (box["required"], box["withdrawable"], box["document"]) == (False, True, "privacy")
    assert box["statement"].startswith("Quiero recibir por correo el resumen semanal de PrediGol")
    r = reader.post("/api/v1/me/consents", json=ask)
    assert r.status_code == 200, r.text
    row = latest(fresh, uid(fresh, READER))
    assert row is not None and row["granted"] and row["source"] == "profile" and row["version"] == version
    assert reader.get("/api/v1/auth/me").status_code == 200
    monkeypatch.setenv(digest.ENV, "0")  # the owner switches it off: the reader still sees the box, to leave it
    assert "marketing_email" in kinds()
    leave = {**ask, "decisions": [{**ask["decisions"][0], "granted": False}]}
    assert reader.post("/api/v1/me/consents", json=leave).status_code == 200
    assert "marketing_email" not in kinds()
    assert latest(fresh, uid(fresh, READER))["granted"] is False  # type: ignore[index]


def test_the_gate_never_asks_for_it(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    reader = client(OTHER)
    state = reader.get("/api/v1/me/consents?lang=es").json()
    assert "marketing_email" not in state["due"] and "marketing_email" in [p["kind"] for p in state["purposes"]]


# ── who gets it, when ─────────────────────────────────────────────────────────────────

def test_only_consenting_readers_get_it_on_their_day_from_nine_once_a_week(fresh: str,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER)
    for email in (READER, OWNER, ROBOT):
        grant(email, fresh)
    grant(OTHER, fresh)
    grant(OTHER, fresh, granted=False)  # asked and left
    at = day_of_reader(me)
    assert run_queue(fresh, at - timedelta(hours=2)).queued == 0, "08:00 in Bogotá: not yet"
    assert run_queue(fresh, at + timedelta(days=1)).queued == 0, "another day"
    report = run_queue(fresh, at)
    rows = summaries(fresh)
    assert report.queued == 1 and [r["user_id"] for r in rows] == [me]
    assert rows[0]["category"] == "marketing" and rows[0]["status"] == "queued"
    assert rows[0]["dedup_key"] == digest.dedup_key(me, "America/Bogota", at)
    assert run_queue(fresh, at + timedelta(hours=5)).queued == 0, "once a week"
    assert run_queue(fresh, at + timedelta(days=7)).queued == 1, "and again the next week"


def test_nothing_is_queued_while_any_of_the_three_is_missing(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    grant(READER, fresh)
    at = day_of_reader(uid(fresh, READER))
    on(monkeypatch)
    for name, value, why in ((digest.ENV, "0", "FBI_DIGEST off"), ("FBI_EMAIL_SEND", "0", "FBI_EMAIL_SEND off"),
                             (digest.FROM_ENV, "PrediGol <otro@mail.predigol.example>",
                              "no commercial sender (FBI_DIGEST_FROM)")):
        with monkeypatch.context() as m:
            m.setenv(name, value)
            report = run_queue(fresh, at)
            assert (report.queued, report.off) == (0, why)
    assert summaries(fresh) == []


def test_a_bounced_address_gets_no_summary_and_the_day_has_its_cap(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    monkeypatch.setattr(digest, "day_of", lambda _user: 0)  # everyone on Monday, to meet the cap
    monkeypatch.setenv(digest.CAP_ENV, "1")
    for email in (READER, READER_EN, OTHER):
        grant(email, fresh)
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.preferences (user_id, email_status, email_status_at) VALUES (%s, 'bounced', "
                     "now())", (uid(fresh, OTHER),))
    monday = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    report = run_queue(fresh, monday)
    assert (report.queued, report.capped) == (1, True)
    report = run_queue(fresh, monday + timedelta(hours=1))
    assert (report.queued, report.capped) == (0, True), "the day's cap counts what was queued today"
    assert run_queue(fresh, monday + timedelta(days=7)).queued == 1
    assert uid(fresh, OTHER) not in {r["user_id"] for r in summaries(fresh)}


# ── what it says ──────────────────────────────────────────────────────────────────────

def test_it_counts_the_weeks_settled_picks_the_teams_matches_and_the_weeks_novedades(
        fresh: str, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me, them = uid(fresh, READER), uid(fresh, OTHER)
    at = day_of_reader(me)
    played = world.match("nacional", "millonarios", at - timedelta(days=3), "finished")
    with psycopg.connect(fresh, autocommit=True) as conn:
        for line, (status, settled) in enumerate((("WIN", 2), ("HALF_WIN", 1), ("LOSS", 3), ("PUSH", 4), ("VOID", 5),
                                                  ("WIN", 9), ("PENDING", None))):
            conn.execute("""
                INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, snapshot,
                                              saved_at, status, settled_at)
                VALUES (%s, %s, '1X2', 'Home', %s, 'market', 2.1, '{}', %s, %s, %s)
            """, (me, played, line, at - timedelta(days=10), status,
                  None if settled is None else at - timedelta(days=settled)))
        conn.execute("""
            INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, snapshot,
                                          saved_at, status, settled_at)
            VALUES (%s, %s, '1X2', 'Home', 0, 'market', 2.1, '{}', %s, 'WIN', %s)
        """, (them, played, at - timedelta(days=10), at - timedelta(days=1)))
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, team_id) VALUES (%s, 'team', %s, %s)",
                     (me, world.ids["nacional"], world.ids["nacional"]))
    world.match("nacional", "medellin", at + timedelta(days=2))
    world.match("millonarios", "nacional", at + timedelta(days=6, hours=23))
    world.match("nacional", "millonarios", at + timedelta(days=8))  # beyond the week
    world.match("medellin", "millonarios", at + timedelta(days=1))  # not the reader's team
    world.match("nacional", "medellin", at + timedelta(days=3), "postponed")
    with psycopg.connect(fresh) as conn:
        params = digest.params_for(conn, me, "America/Bogota", at)
    assert params["won"] == "2" and params["lost"] == "1" and params["void"] == "2"
    assert (params["matches"], params["follows"]) == ("2", "yes")
    week = [u.id for u in digest.updates.between(at.date() - timedelta(days=6), at.date())][:3]
    assert params["news"] == (",".join(week) or "-")
    with psycopg.connect(fresh) as conn:
        assert digest.params_for(conn, them, "America/Bogota", at)["follows"] == "no"
    assert all(len(v) <= 200 for v in params.values())


# ── when it leaves ────────────────────────────────────────────────────────────────────

def test_it_leaves_by_its_own_sender_with_the_one_click_headers_and_a_link_of_its_own(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER)
    grant(READER, fresh)
    at = soon(monkeypatch)
    assert run_queue(fresh, at).queued == 1
    sink, report = send_all(fresh, at)
    assert report.sent == 1 and len(sink.sent) == 1
    sent = sink.sent[0]
    assert sent.sender == COMMERCIAL_FROM and sent.tags == {"category": "marketing", "template": "weekly_digest"}
    assert sent.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    post = sent.headers["List-Unsubscribe"]
    assert post.startswith("<https://predigol.example/api/v1/email/unsubscribe?t=") and post.endswith(">")
    token = post[len("<https://predigol.example/api/v1/email/unsubscribe?t="):-1]
    assert unsubscribe.read(token, at) == me
    assert f"https://predigol.example/unsubscribe#t={token}" in sent.text and sent.subject == "Tu semana en PrediGol"
    assert READER not in sent.text and "@" not in sent.text.split("--")[0]


def test_a_reader_who_left_the_switch_off_or_the_sender_gone_gets_nothing(fresh: str,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER)
    at = soon(monkeypatch)
    for change, why in ((lambda: grant(READER, fresh, granted=False), "left the weekly summary"),
                        (lambda: monkeypatch.setenv(digest.ENV, "0"), "switched off"),
                        (lambda: monkeypatch.setenv(digest.FROM_ENV, ACCOUNT_FROM), "no commercial sender")):
        on(monkeypatch)
        grant(READER, fresh)
        with psycopg.connect(fresh, autocommit=True) as conn, conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            conn.execute("DELETE FROM customer.messages_outbox")  # the same week again, for the next case
        assert run_queue(fresh, at).queued == 1
        assert me in {r["user_id"] for r in summaries(fresh)}
        change()
        sink, report = send_all(fresh, at)
        assert (report.sent, report.suppressed, sink.sent) == (0, 1, [])
        row = summaries(fresh)[-1]
        assert row["status"] == "suppressed" and why in row["last_error"]


def test_the_account_mail_goes_first_and_the_summary_last(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER)
    grant(READER, fresh)
    at = soon(monkeypatch)
    assert run_queue(fresh, at).queued == 1
    with psycopg.connect(fresh) as conn:
        outbox.enqueue(conn, user_id=me, template="new_sign_in",
                       params={"browser": "chrome", "system": "android", "when": at.isoformat()},
                       dedup_key=f"test:{uuid.uuid4().hex}")
        conn.commit()
    sink, _ = send_all(fresh, at)
    assert [m.tags["template"] for m in sink.sent] == ["new_sign_in", "weekly_digest"]
    assert sink.sent[0].sender is None and sink.sent[0].headers == {}, "the account's mail keeps its own sender"


# ── the one-click leaving ─────────────────────────────────────────────────────────────

def test_one_click_without_a_session_leaves_at_once_and_a_second_click_changes_nothing(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER_EN)
    grant(READER_EN, fresh)
    token = unsubscribe.make(me, datetime.now(UTC))
    monkeypatch.setenv(digest.ENV, "0")  # leaving works whatever the switches say
    mail_client = TestClient(create_app())  # no session, no Origin, no x-requested-with: a mail client
    r = mail_client.post(f"/api/v1/email/unsubscribe?t={token}", content="List-Unsubscribe=One-Click",
                         headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json() == {"left": True}, r.text
    row = latest(fresh, me)
    assert row is not None and row["granted"] is False and row["source"] == "email" and row["locale"] == "en"
    assert row["version"] == legal.current("privacy").version and len(row["sha256"]) == 64
    assert mail_client.post(f"/api/v1/email/unsubscribe?t={token}").json() == {"left": False}
    with psycopg.connect(fresh) as conn:
        assert int(scalar(conn.execute("SELECT count(*) FROM customer.consents WHERE user_id = %s AND source = 'email'",
                                       (me,)))) == 1
    user, day, mac = token.split("x", 2)
    forged = f"{uid(fresh, READER)}x{day}x{mac}"
    for bad in (forged, f"{user}x{day}x{'A' * 22}"):
        r = mail_client.post(f"/api/v1/email/unsubscribe?t={bad}")
        assert (r.status_code, code(r)) == (400, "invalid_link")
    assert mail_client.post("/api/v1/email/unsubscribe?t=short").status_code == 422


def test_a_link_never_writes_a_decision_the_reader_did_not_take(fresh: str) -> None:
    me = uid(fresh, OTHER)
    token = unsubscribe.make(me, datetime.now(UTC))
    r = TestClient(create_app()).post(f"/api/v1/email/unsubscribe?t={token}")
    assert r.json() == {"left": False} and latest(fresh, me) is None


def test_the_page_posts_the_token_in_the_body_from_predigols_own_pages(fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch)
    me = uid(fresh, READER)
    grant(READER, fresh)
    token = unsubscribe.make(me, datetime.now(UTC))
    client = TestClient(create_app())
    r = client.post("/api/v1/email/unsubscribe/link", json={"token": token})
    assert (r.status_code, code(r)) == (403, "csrf"), "a cross-site form cannot use the page's way"
    r = client.post("/api/v1/email/unsubscribe/link", json={"token": token}, headers=SAME_SITE)
    assert r.status_code == 200 and r.json() == {"left": True}, r.text
    row = latest(fresh, me)
    assert row is not None and row["granted"] is False and row["source"] == "email" and row["locale"] == "es"
    assert client.post("/api/v1/email/unsubscribe/link", json={"token": token}, headers=SAME_SITE).json() == {"left": False}
    r = client.post("/api/v1/email/unsubscribe/link", json={"token": token, "user_id": me}, headers=SAME_SITE)
    assert r.status_code == 422, "nothing but the token"
    r = client.post("/api/v1/email/unsubscribe/link", json={"token": "x" * 30}, headers=SAME_SITE)
    assert (r.status_code, code(r)) == (400, "invalid_link")


def test_a_client_that_keeps_presenting_links_that_do_not_work_is_cut_short(
        fresh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(messaging_router, "LEAVE_TRIES", throttle.FailureWindow(max_failures=3, window_s=900))
    me = uid(fresh, READER)
    grant(READER, fresh)
    good = unsubscribe.make(me, datetime.now(UTC))
    user, day, _ = good.split("x", 2)
    client = TestClient(create_app())
    for n in range(3):
        bad = f"{user}x{day}x{chr(ord('A') + n) * 22}"
        assert (client.post(f"/api/v1/email/unsubscribe?t={bad}").status_code) == 400
    r = client.post(f"/api/v1/email/unsubscribe?t={good}")
    assert (r.status_code, code(r)) == (429, "too_many_attempts") and int(r.headers["retry-after"]) > 0
    assert r.json()["error"]["retry_after"] == int(r.headers["retry-after"]), "the page says how long to wait"
    r = client.post("/api/v1/email/unsubscribe/link", json={"token": good}, headers=SAME_SITE)
    assert r.status_code == 429, "the page's way counts the same tries"
    assert latest(fresh, me)["granted"] is True, "nothing was written while cut short"  # type: ignore[index]

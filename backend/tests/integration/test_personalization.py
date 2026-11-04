"""What a reader's favourites and own use order, filter and suggest, against the migrated database (plan UX, B2; section 38).

* The markets the reader consults most come first, from their own events of the last 30 days (two times or more); the
  usual order is one tap away and back; another reader's events, or older ones, never count.
* Nothing is ordered or suggested while the reader's use is not counted (the analytics off, ``consent`` without their
  consent, the owner's account), nor with FBI_PERSONALIZATION=0.
* A league or a team the reader keeps opening outside what they follow is suggested with its reason; it is followed only
  when they confirm (their favourites with it), dismissed it never comes back, and past the limits it is not offered.
* Home's news are the news of the reader's leagues and teams - the suggested ones while they chose none or personalisation
  is off -, each match saying why it is theirs, and an item is the same for every reader who sees it.
* The rule of plan section 38: two readers with different favourites and different habits get the very same picks,
  forecasts, prices and states from every page that shows them; what is theirs lives under /me (a world with a published
  pick, rolled back).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from fbi.api.app import create_app
from fbi.api.routers import events as events_router
from fbi.api.routers import personal as personal_router
from fbi.api.services import forecast as forecast_service
from fbi.api.services import news as news_service
from fbi.api.services import reading as reading_service
from fbi.auth import crypto, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import consents, favorites
from fbi.picks.daily import product_day
from tests.integration.conftest import Seed
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE
from tests.integration.test_customer_favorites import (
    PERSONAL,
    VOLATILE,
    common_part,
    first_difference,
    reader_app,
)
from tests.integration.test_news_api import evidence
from tests.integration.test_transparency import World

pytestmark = pytest.mark.integration

READER = "lectora.b2@example.org"  # follows Liga Mía and Atlético Nacional
OTHER = "otro.b2@example.org"  # follows Serie Prueba
ALSO = "tambien.b2@example.org"  # follows Serie Prueba and Atlético Nacional
FRESH = "nueva.b2@example.org"  # chose nothing: the suggested ones
OWNER = "owner.b2@predigol.test"
PASSWORD = "Morning-pitch-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
LEAGUES = {"mia": (7714001, "Liga Mía B2", True), "serie": (7714002, "Serie Prueba B2", True),
           "betplay": (239, "Liga BetPlay", True), "lejana": (7714003, "Liga Lejana B2", False)}
"""Provider id, name, followed by PrediGol. 239 is one of the suggested leagues (fbi.core.suggestions)."""
TEAMS = {"inter": 7714011, "milan": 7714012, "juve": 7714013, "nacional": 7714014, "millos": 7714015,
         "junior": 7714016, "medellin": 7714017}
NAMES = {"inter": "Inter B2", "milan": "Milan B2", "juve": "Juve B2", "nacional": "Atlético Nacional",
         "millos": "Millonarios", "junior": "Junior", "medellin": "Medellín"}


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.favorites", "customer.messages_outbox", "customer.preferences",
                          "customer.ticket_messages", "customer.support_tickets", "customer.consents",
                          "customer.product_events", "customer.activity_daily"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_picks")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")
        with conn.transaction():  # this module's own evidence rows, which nothing else ever deletes
            conn.execute("SET LOCAL fbi.ai_maintenance = 'on'")
            conn.execute("DELETE FROM ai.evidence WHERE fixture_id IN (SELECT id FROM core.fixtures "
                         "WHERE provider_fixture_id BETWEEN 7714100 AND 7714199)")
        conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 7714100 AND 7714199")
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN (SELECT id FROM core.competitions "
                     "WHERE provider_league_id = ANY(%s))", ([p for p, _, _ in LEAGUES.values()],))
        conn.execute("DELETE FROM core.competitions WHERE provider_league_id = ANY(%s)",
                     ([p for p, _, _ in LEAGUES.values()],))
        conn.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", (list(TEAMS.values()),))


class Football:
    """The committed world: four competitions (one PrediGol does not follow), seven teams, three Serie matches played in
    the last days, three matches to come with confirmed news. ``ids`` maps a key of LEAGUES / TEAMS to its id."""

    def __init__(self, dsn: str, at: datetime) -> None:
        self.ids: dict[str, int] = {}
        self.fixtures: dict[str, int] = {}
        seasons: dict[str, int] = {}
        with psycopg.connect(dsn, autocommit=True) as conn:
            for key, (provider, name, tracked) in LEAGUES.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', 'domestic_league', %s) "
                    "RETURNING id", (provider, name, tracked))))
                seasons[key] = int(scalar(conn.execute(
                    "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                    "RETURNING id", (self.ids[key],))))
            for key, provider in TEAMS.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (%s, %s, false) RETURNING id",
                    (provider, NAMES[key]))))
            n = 7714100
            for name, league, home, away, kickoff, group in (
                    ("serie_1", "serie", "inter", "milan", at - timedelta(days=5), "finished"),
                    ("serie_2", "serie", "juve", "inter", at - timedelta(days=3), "finished"),
                    ("serie_3", "serie", "milan", "juve", at - timedelta(days=1), "finished"),
                    ("serie_soon", "serie", "inter", "juve", at + timedelta(hours=5), "scheduled"),
                    ("mia_soon", "mia", "nacional", "millos", at + timedelta(hours=4), "scheduled"),
                    ("betplay_soon", "betplay", "junior", "medellin", at + timedelta(hours=6), "scheduled")):
                n += 1
                self.fixtures[name] = int(scalar(conn.execute(
                    "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at, status_group) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (n, seasons[league], self.ids[home], self.ids[away], kickoff, group))))
            for match, team, player in (("serie_soon", "inter", "Uno"), ("mia_soon", "nacional", "Dos"),
                                        ("betplay_soon", "junior", "Tres")):
                evidence(conn, self.fixtures[match], self.ids[team], status="CONFIRMED", player=player,
                         claim=f"Según Sport, {player} es baja por lesión para este partido.")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    wipe(migrated_database)
    for email, role in ((READER, "USER"), (OTHER, "USER"), (ALSO, "USER"), (FRESH, "USER"), (OWNER, "SUPER_ADMIN")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()
    reset_session_settings()


@pytest.fixture(scope="module")
def football(database: str) -> Football:
    return Football(database, datetime.now(UTC))


@pytest.fixture()
def fresh(database: str, football: Football, monkeypatch: pytest.MonkeyPatch) -> Iterator[Football]:
    throttle.reset_all()
    forget_sign_in_failures()
    events_router.EVENT_LIMIT.reset()
    consents._clear.clear()
    f = football.ids
    with psycopg.connect(database, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.favorites", "customer.product_events", "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("UPDATE customer.preferences SET hints_seen = '{}'")
        for email, leagues, teams in ((READER, ["mia"], ["nacional"]), (OTHER, ["serie"], []),
                                      (ALSO, ["serie"], ["nacional"])):
            user = uid(database, email)
            for kind, keys in (("league", leagues), ("team", teams)):
                for key in keys:
                    conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id) "
                                 "VALUES (%s, %s, %s, %s, %s)", (user, kind, f[key], f[key] if kind == "league" else None,
                                                                 f[key] if kind == "team" else None))
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH, consents.GATE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    monkeypatch.setenv(news_service.USERS_SWITCH, "1")
    yield football


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def opened(dsn: str, email: str, fixture: int, at: datetime) -> None:
    """A ``match_opened`` the reader's page recorded at that moment (the API records «now»: the past is written here)."""
    subject = crypto.product_id(uid(dsn, email))
    assert subject is not None, "the tests' key makes the pseudonym"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO customer.product_events (subject, name, props, at) VALUES (%s, 'match_opened', %s, %s)",
                     (subject, Json({"origin": "matches", "match_id": fixture}), at))


def viewed(api: TestClient, market: str, times: int, match: int) -> None:
    r = api.post("/api/v1/events", json={"events": [{"name": "market_viewed", "props": {"market": market,
                                                                                         "match_id": match}}] * times})
    assert r.status_code == 200 and r.json()["recorded"] == times, r.text


def code(r: Any) -> str:
    body = r.json()
    return str(body.get("error", {}).get("code") or body.get("code") or body.get("detail"))


# ── the markets ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_markets_the_reader_consults_most_come_first_and_the_usual_order_is_a_tap_away(
        fresh: Football, database: str) -> None:
    reader, other = client(READER), client(OTHER)
    match = fresh.fixtures["mia_soon"]
    viewed(reader, "OU", 3, match)
    viewed(reader, "BTTS", 2, match)
    viewed(reader, "DC", 1, match)
    view = reader.get("/api/v1/me/personal").json()
    assert (view["personalization"], view["counted"]) == (True, True)
    markets = view["markets"]
    assert markets["first"] == ["OU", "BTTS"], "two times or more, most first; one look is not a habit"
    assert markets["views"] == [{"market": "OU", "views": 3}, {"market": "BTTS", "views": 2}], "the rule, said"
    assert (markets["common"], markets["window_days"], markets["min_views"]) == (False, 30, 2)

    usual = reader.put("/api/v1/me/personal/markets", json={"common": True}).json()["markets"]
    assert usual["first"] == [] and usual["common"] is True and usual["views"] == markets["views"], (
        "the usual order kept, what theirs would be still said")
    assert reader.get("/api/v1/me/personal").json()["markets"]["common"] is True, "kept"
    back = reader.put("/api/v1/me/personal/markets", json={"common": False}).json()["markets"]
    assert back["first"] == ["OU", "BTTS"] and back["common"] is False

    assert other.get("/api/v1/me/personal").json()["markets"]["first"] == [], "another reader's habits never count"
    subject = crypto.product_id(uid(database, OTHER))
    with psycopg.connect(database, autocommit=True) as conn:
        for _ in range(5):
            conn.execute("INSERT INTO customer.product_events (subject, name, props, at) VALUES (%s, 'market_viewed', %s, "
                         "now() - interval '31 days')", (subject, Json({"market": "DC", "match_id": match})))
    assert other.get("/api/v1/me/personal").json()["markets"]["first"] == [], "older than 30 days: forgotten"
    assert reader.put("/api/v1/me/personal/markets", json={"common": True, "x": 1}).status_code == 422


def test_nothing_is_ordered_or_suggested_while_the_use_is_not_counted_or_with_personalization_off(
        fresh: Football, database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = client(READER)
    match = fresh.fixtures["mia_soon"]
    viewed(reader, "OU", 2, match)
    for i, key in enumerate(("serie_1", "serie_2", "serie_3")):
        opened(database, READER, fresh.fixtures[key], datetime.now(UTC) - timedelta(days=4 - i))
    counted = reader.get("/api/v1/me/personal").json()
    assert counted["markets"]["first"] == ["OU"] and counted["suggestion"] is not None, "the world orders and suggests"

    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "off")
    off = reader.get("/api/v1/me/personal").json()
    assert (off["counted"], off["markets"]["first"], off["markets"]["views"], off["suggestion"]) == (False, [], [], None), (
        "the analytics off: what was counted before is not used")
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "consent")
    no_consent = reader.get("/api/v1/me/personal").json()
    assert (no_consent["counted"], no_consent["markets"]["first"], no_consent["suggestion"]) == (False, [], None), (
        "consent mode without the reader's consent: nothing of theirs is used")
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    monkeypatch.setenv(favorites.PERSONALIZATION_SWITCH, "0")
    common = reader.get("/api/v1/me/personal").json()
    assert (common["personalization"], common["counted"], common["markets"]["first"], common["suggestion"]) == (
        False, True, [], None), "FBI_PERSONALIZATION=0: the common view for everyone"
    monkeypatch.delenv(favorites.PERSONALIZATION_SWITCH)
    owner = client(OWNER).get("/api/v1/me/personal").json()
    assert (owner["counted"], owner["markets"]["first"], owner["suggestion"]) == (False, [], None), (
        "the owner's account is never counted")


# ── the suggestion ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_league_the_reader_keeps_opening_is_suggested_and_followed_only_when_they_confirm(
        fresh: Football, database: str) -> None:
    f, reader = fresh.ids, client(READER)
    assert reader.get("/api/v1/me/personal").json()["suggestion"] is None, "nothing opened yet"
    now = datetime.now(UTC)
    for i, key in enumerate(("serie_1", "serie_2", "serie_3")):
        opened(database, READER, fresh.fixtures[key], now - timedelta(days=4 - i))
    opened(database, READER, fresh.fixtures["mia_soon"], now)  # one of their own: never counts
    suggestion = reader.get("/api/v1/me/personal").json()["suggestion"]
    assert suggestion == {"kind": "league", "id": f["serie"], "name": "Serie Prueba B2", "matches": 3, "days": 3}, (
        "three different teams opened: their league")
    mine = reader.get("/api/v1/me/favorites").json()
    assert [x["name"] for x in mine["leagues"]] == ["Liga Mía B2"], "suggested, never followed by itself"

    added = reader.put("/api/v1/me/favorites", json={"leagues": [f["mia"], f["serie"]], "teams": [f["nacional"]]})
    assert added.status_code == 200, added.text
    assert reader.get("/api/v1/me/personal").json()["suggestion"] is None, "followed now: its matches are theirs"

    reader.put("/api/v1/me/favorites", json={"leagues": [f["mia"]], "teams": [f["nacional"]]})
    assert reader.get("/api/v1/me/personal").json()["suggestion"]["id"] == f["serie"], "removed again: suggested again"
    dismissed = reader.post("/api/v1/me/personal/suggestion/dismiss", json={"kind": "league", "id": f["serie"]})
    assert dismissed.status_code == 200 and dismissed.json()["suggestion"] is None, dismissed.text
    for i in range(3):  # more of the same never brings it back
        opened(database, READER, fresh.fixtures[f"serie_{i + 1}"], now - timedelta(hours=1 + i))
    assert reader.get("/api/v1/me/personal").json()["suggestion"] is None, "dismissed: it never comes back"
    with psycopg.connect(database) as conn:
        seen = scalar(conn.execute("SELECT hints_seen FROM customer.preferences WHERE user_id = %s",
                                   (uid(database, READER),)))
    assert f"suggest:league:{f['serie']}" in seen
    assert reader.get("/api/v1/me/onboarding").json()["hints_seen"] == [], "the pages' hints only"
    unknown = reader.post("/api/v1/me/personal/suggestion/dismiss", json={"kind": "league", "id": f["lejana"]})
    assert (unknown.status_code, code(unknown)) == (422, "unknown_league"), "a league PrediGol does not follow"
    assert reader.post("/api/v1/me/personal/suggestion/dismiss", json={"kind": "amount", "id": 1}).status_code == 422


def test_a_team_before_its_league_and_nothing_past_the_limits(
        fresh: Football, database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    f, other = fresh.ids, client(FRESH)
    now = datetime.now(UTC)
    for i, key in enumerate(("serie_1", "serie_2", "serie_soon")):  # Inter plays the three
        opened(database, FRESH, fresh.fixtures[key], now - timedelta(days=3 - i))
    suggestion = other.get("/api/v1/me/personal").json()["suggestion"]
    assert suggestion is not None and (suggestion["kind"], suggestion["id"], suggestion["name"]) == (
        "team", f["inter"], "Inter B2"), "the same team every time: the team, the nearer reason"
    monkeypatch.setattr(favorites, "MAX_TEAMS", 0)
    suggestion = other.get("/api/v1/me/personal").json()["suggestion"]
    assert suggestion is not None and (suggestion["kind"], suggestion["id"]) == ("league", f["serie"]), (
        "no room for a team: its league instead")
    monkeypatch.setattr(favorites, "MAX_LEAGUES", 0)
    assert other.get("/api/v1/me/personal").json()["suggestion"] is None, "no room for either: nothing offered"


# ── Home's news ──────────────────────────────────────────────────────────────────────────────────────────────────────


def news(api: TestClient) -> dict[str, Any]:
    body = api.get("/api/v1/today/news").json()
    assert body["status"] in ("ok", "empty"), body
    return body["data"]


def by_match(data: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for item in data["items"]:
        out.setdefault(item["match"]["fixture_id"], []).append(item)
    return out


def test_home_news_are_the_readers_leagues_and_teams_each_saying_why_and_the_same_item_for_all(
        fresh: Football, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = fresh.fixtures
    reader, other, also, new = (news(client(e)) for e in (READER, OTHER, ALSO, FRESH))
    mine, theirs, both, cold = (by_match(x) for x in (reader, other, also, new))
    assert set(mine) == {fx["mia_soon"]} and reader["suggested"] is False
    assert mine[fx["mia_soon"]][0]["match"]["followed"] == {"kind": "team", "names": ["Atlético Nacional"]}, (
        "the team first: the nearer reason")
    assert set(theirs) == {fx["serie_soon"]}
    assert theirs[fx["serie_soon"]][0]["match"]["followed"] == {"kind": "league", "names": ["Serie Prueba B2"]}
    assert set(both) == {fx["serie_soon"], fx["mia_soon"]}
    assert both[fx["mia_soon"]] == mine[fx["mia_soon"]], "an item is the same for every reader who sees it"
    assert set(cold) == {fx["betplay_soon"]} and new["suggested"] is True, "none chosen: the suggested ones, labelled"
    assert cold[fx["betplay_soon"]][0]["match"]["followed"] == {"kind": "league", "names": ["Liga BetPlay"]}

    monkeypatch.setenv(favorites.PERSONALIZATION_SWITCH, "0")
    common = news(client(READER))
    assert set(by_match(common)) == {fx["betplay_soon"]} and common["suggested"] is True, (
        "FBI_PERSONALIZATION=0: the common news, whatever the reader follows")


# ── only one's own ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_each_reader_reads_only_their_own_and_no_route_names_an_account(fresh: Football) -> None:
    paths = [getattr(route, "path", "") for route in personal_router.router.routes]
    assert paths and not [p for p in paths if "{" in p], "no route names an account: each reads the caller's own"
    anonymous = TestClient(create_app(), headers=SAME_SITE)
    assert anonymous.get("/api/v1/me/personal").status_code == 401
    assert anonymous.put("/api/v1/me/personal/markets", json={"common": True}).status_code == 401
    reader = client(READER)
    cross_site = TestClient(create_app())
    cross_site.cookies = reader.cookies
    assert cross_site.put("/api/v1/me/personal/markets", json={"common": True}).status_code == 403, (
        "from another site: refused")


# ── the rule of section 38 ───────────────────────────────────────────────────────────────────────────────────────────


def test_two_readers_with_different_favourites_and_habits_get_the_same_picks_prices_forecasts_and_states(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1")
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1")
    monkeypatch.setenv(news_service.USERS_SWITCH, "1")
    monkeypatch.setenv("FBI_PRODUCT_EVENTS", "on")
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH):
        monkeypatch.delenv(name, raising=False)
    world = World(db, seed)
    now = datetime.now(UTC)
    fid, _pick = world.item(product_day(now), "OU", "Over", "2.5", "PENDING", None, "1.95",
                            kickoff=now + timedelta(hours=5))
    second = world.fixture(now + timedelta(hours=8))
    other_league = int(scalar(db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
        "VALUES (7714901, 'Otra Liga B2', 'league', 'club', 'domestic_league', true) RETURNING id")))
    readers = [int(scalar(db.execute(
        "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES (%s, 'R', '$argon2id$x', 'USER') "
        "RETURNING id", (email,)))) for email in ("uno.b2@example.org", "dos.b2@example.org")]
    first, other = readers
    db.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
               (first, world.competition, world.competition))
    db.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
               (other, other_league, other_league))
    for user, market in ((first, "BTTS"), (other, "DC")):  # different habits
        subject = crypto.product_id(user)
        for _ in range(3):
            db.execute("INSERT INTO customer.product_events (subject, name, props) VALUES (%s, 'market_viewed', %s)",
                       (subject, Json({"market": market, "match_id": fid})))
        db.execute("INSERT INTO customer.product_events (subject, name, props) VALUES (%s, 'match_opened', %s)",
                   (subject, Json({"origin": "home", "match_id": second})))

    day_from, day_to = (now - timedelta(hours=12)).isoformat(), (now + timedelta(hours=12)).isoformat()
    paths = ["/api/v1/today", "/api/v1/today/no-pick", "/api/v1/home", "/api/v1/picks", "/api/v1/daily",
             "/api/v1/picks/started", f"/api/v1/matches/{fid}", f"/api/v1/matches/{fid}/forecast",
             f"/api/v1/matches/{fid}/reading", f"/api/v1/matches/{fid}/news", f"/api/v1/odds/fixtures/{fid}",
             "/api/v1/odds/best"]
    day = {"kickoff_after": day_from, "kickoff_before": day_to, "order": "asc", "limit": 200}
    answers: dict[int, dict[str, Any]] = {}
    for user in readers:
        api = reader_app(db, user)
        answers[user] = {}
        for path in paths:
            r = api.get(path)
            assert r.status_code == 200, (path, r.text)
            answers[user][path] = r.json()
        listed = api.get("/api/v1/matches", params=day)
        assert listed.status_code == 200, listed.text
        answers[user]["/api/v1/matches"] = listed.json()
        answers[user]["/me/personal"] = api.get("/api/v1/me/personal").json()
    daily = answers[first]["/api/v1/daily"]["data"]
    assert [i["match"]["fixture_id"] for i in daily["set"]["items"]] == [fid], "the world has a published pick to compare"
    for path in [*paths, "/api/v1/matches"]:
        mine, theirs = (common_part(answers[user][path], VOLATILE | PERSONAL) for user in readers)
        assert mine == theirs, f"{path}: {first_difference(mine, theirs)}"
    assert answers[first]["/me/personal"]["markets"]["first"] == ["BTTS"], "the comparison is not empty"
    assert answers[other]["/me/personal"]["markets"]["first"] == ["DC"], "each reader's own order, under /me only"

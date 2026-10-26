"""A reader's favourites, the welcome and the hints against the migrated database (plan UX, A13).

* The favourites over HTTP, signed in for real: the suggested ones for Colombia, labelled, until the reader chooses; exactly
  the ones chosen, in their order, idempotent; the limits and what cannot be followed refused (422, never trimmed); each
  reader sees and changes only their own; the options - every league PrediGol follows and the teams of those leagues by name,
  without accents or case.
* The welcome once per reader account (the whole one for a new account, the favourites alone for an older one), never for the
  owner's, never with FBI_ONBOARDING=0; a dismissed hint never comes back. Both reach the page through GET /auth/me.
* Home (GET /today): each of the reader's matches says why it is theirs, and the next match of each favourite is listed.
* What the account keeps: the favourites in the reader's export, gone when the account is anonymised.
* The rule of plan section 38 - personalise the experience, never the intelligence: two readers with different favourites
  get the very same forecasts, lines, picks and states from every page that shows them; only what is marked as theirs
  differs (on a world with a published pick, in a transaction rolled back afterwards).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.routers import favorites as favorites_router
from fbi.api.security import optional_principal
from fbi.api.services import forecast as forecast_service
from fbi.api.services import reading as reading_service
from fbi.auth import anonymize, service, throttle
from fbi.auth.settings import reset as reset_session_settings
from fbi.core.config import reset_cache
from fbi.customer import favorites, privacy
from fbi.picks.daily import product_day
from tests.integration.conftest import Seed
from tests.integration.helpers import forget_memberships, forget_sign_in_failures, scalar
from tests.integration.signed_in import SAME_SITE, principal
from tests.integration.test_transparency import World

pytestmark = pytest.mark.integration

READER = "lectora.a13@example.org"
OLDER = "antiguo.a13@example.org"
OTHER = "otro.a13@example.org"
OWNER = "owner.a13@predigol.test"
PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
LEAGUES = {"uno": (7713001, "Liga Uno", True), "dos": (7713002, "Copa Dos", True), "betplay": (239, "Liga BetPlay", True),
           "lejana": (7713003, "Liga Lejana", False)}
"""This module's competitions: provider id, name, followed by PrediGol. 239 is one of the suggested leagues (fbi.core.suggestions)."""
TEAMS = {"nacional": (7713011, "Atlético Nacional", False), "millonarios": (7713012, "Millonarios", False),
         "santafe": (7713013, "Santa Fe", False), "lejano": (7713014, "Club Lejano", False),
         "lejano2": (7713015, "Otro Lejano", False), "viejo": (7713016, "Equipo Viejo", False),
         "junior": (7713017, "Junior", False), "medellin": (7713018, "Medellín", False),
         "pereira": (7713019, "Pereira", False), "colombia": (7713020, "Colombia", True)}


def wipe_accounts(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("customer.favorites", "customer.messages_outbox", "customer.preferences",
                          "customer.ticket_messages", "customer.support_tickets", "customer.consents"):
                conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM auth.sessions")
        conn.execute("DELETE FROM auth.audit_events")
        conn.execute("DELETE FROM picks.user_picks")
        forget_memberships(conn)
        conn.execute("DELETE FROM auth.users")


def wipe_football(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 7713100 AND 7713199")
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id IN (SELECT id FROM core.competitions "
                     "WHERE provider_league_id = ANY(%s))", ([p for p, _, _ in LEAGUES.values()],))
        conn.execute("DELETE FROM core.competitions WHERE provider_league_id = ANY(%s)",
                     ([p for p, _, _ in LEAGUES.values()],))
        conn.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", ([p for p, _, _ in TEAMS.values()],))


class Football:
    """The committed world of this module: four competitions (one PrediGol does not follow), ten teams and their matches
    around now. ``ids`` maps a key of LEAGUES / TEAMS to its database id; ``fixtures`` a match's name to its id."""

    def __init__(self, dsn: str, at: datetime) -> None:
        self.ids: dict[str, int] = {}
        self.seasons: dict[str, int] = {}
        self.fixtures: dict[str, int] = {}
        with psycopg.connect(dsn, autocommit=True) as conn:
            for key, (provider, name, tracked) in LEAGUES.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', 'domestic_league', %s) "
                    "RETURNING id", (provider, name, tracked))))
                self.seasons[key] = int(scalar(conn.execute(
                    "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                    "RETURNING id", (self.ids[key],))))
            for key, (provider, name, national) in TEAMS.items():
                self.ids[key] = int(scalar(conn.execute(
                    "INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (%s, %s, %s) RETURNING id",
                    (provider, name, national))))
            n = 7713100
            for name, league, home, away, kickoff, group in (
                    ("today_uno", "uno", "millonarios", "nacional", at + timedelta(hours=3), "scheduled"),
                    ("today_dos", "dos", "santafe", "millonarios", at + timedelta(hours=6), "scheduled"),
                    ("past_uno", "uno", "nacional", "santafe", at - timedelta(days=10), "finished"),
                    ("ancient", "uno", "viejo", "millonarios", at - timedelta(days=500), "finished"),
                    ("far", "lejana", "lejano", "lejano2", at + timedelta(days=2), "scheduled"),
                    ("betplay_later", "betplay", "junior", "medellin", at + timedelta(days=20), "scheduled"),
                    ("betplay_past", "betplay", "pereira", "junior", at - timedelta(days=30), "finished"),
                    ("result_dos", "dos", "junior", "medellin", at - timedelta(hours=20), "finished")):
                n += 1
                self.fixtures[name] = int(scalar(conn.execute(
                    "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at, status_group) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (n, self.seasons[league], self.ids[home], self.ids[away], kickoff, group))))


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    reset_session_settings()
    wipe_accounts(migrated_database)
    wipe_football(migrated_database)
    for email, role in ((READER, "USER"), (OLDER, "USER"), (OTHER, "USER"), (OWNER, "SUPER_ADMIN")):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD,
                                       language="es", timezone="America/Bogota")
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET created_at = now() - interval '30 days' WHERE email = %s", (OLDER,))
    yield migrated_database
    wipe_accounts(migrated_database)
    wipe_football(migrated_database)
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
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM customer.favorites")
        conn.execute("UPDATE customer.preferences SET onboarded_at = NULL, hints_seen = '{}'")
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1")
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1")
    yield football


def client(email: str) -> TestClient:
    c = TestClient(create_app(), headers=SAME_SITE)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def uid(dsn: str, email: str) -> int:
    with psycopg.connect(dsn) as conn:
        return int(scalar(conn.execute("SELECT id FROM auth.users WHERE email = %s", (email,))))


def names(items: list[dict[str, Any]]) -> list[str]:
    return [i["name"] for i in items]


def code(r: Any) -> str:
    body = r.json()
    return str(body.get("error", {}).get("code") or body.get("code") or body.get("detail"))


# ── the favourites ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_suggested_ones_labelled_until_the_reader_chooses(fresh: Football) -> None:
    view = client(READER).get("/api/v1/me/favorites").json()
    assert view["suggested"] is True, "no choice yet: the suggested ones, labelled"
    assert "Liga BetPlay" in names(view["leagues"]) and "Liga Lejana" not in names(view["leagues"])
    assert names(view["teams"]) == ["Colombia"], "the national team suggested with them"
    assert (view["max_leagues"], view["max_teams"], view["personalization"]) == (10, 20, True)


def test_the_favourites_become_exactly_the_ones_chosen_in_the_readers_order(fresh: Football, database: str) -> None:
    f, reader = fresh.ids, client(READER)
    body = {"leagues": [f["dos"], f["uno"]], "teams": [f["santafe"], f["nacional"]]}
    first = reader.put("/api/v1/me/favorites", json=body)
    assert first.status_code == 200, first.text
    view = first.json()
    assert view["suggested"] is False
    assert names(view["leagues"]) == ["Copa Dos", "Liga Uno"] and names(view["teams"]) == ["Santa Fe", "Atlético Nacional"]
    assert reader.put("/api/v1/me/favorites", json=body).json() == view, "idempotent"
    with psycopg.connect(database) as conn:
        kept_at = conn.execute("SELECT created_at FROM customer.favorites WHERE kind = 'team' AND ref_id = %s",
                               (f["nacional"],)).fetchone()
    fewer = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [f["nacional"]]}).json()
    assert names(fewer["leagues"]) == ["Liga Uno"] and names(fewer["teams"]) == ["Atlético Nacional"]
    with psycopg.connect(database) as conn:
        rows = conn.execute("SELECT kind, ref_id, league_id, team_id, created_at FROM customer.favorites "
                            "WHERE user_id = %s ORDER BY kind", (uid(database, READER),)).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("league", f["uno"], f["uno"], None),
                                                         ("team", f["nacional"], None, f["nacional"])]
    assert (rows[1][4],) == kept_at, "a favourite kept is not chosen again"
    assert reader.get("/api/v1/me/favorites").json() == fewer
    empty = reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": []}).json()
    assert empty["suggested"] is True, "none left: the suggested ones again, labelled"


def test_the_limits_and_what_cannot_be_followed_are_refused_never_trimmed(fresh: Football) -> None:
    f, reader = fresh.ids, client(READER)
    assert reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": []}).status_code == 200
    refused = {
        "too_many_leagues": {"leagues": list(range(1, 12)), "teams": []},
        "too_many_teams": {"leagues": [], "teams": list(range(1, 22))},
        "unknown_league": {"leagues": [f["lejana"]], "teams": []},  # a league PrediGol does not follow
    }
    for expected, body in refused.items():
        r = reader.put("/api/v1/me/favorites", json=body)
        assert (r.status_code, code(r)) == (422, expected), r.text
    for team in ("lejano", "viejo"):  # only in a league PrediGol does not follow; last played there 500 days ago
        r = reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": [f[team]]})
        assert (r.status_code, code(r)) == (422, "unknown_team"), team
    assert reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": [], "amount": 5}).status_code == 422, (
        "only leagues and teams: never an amount, a bankroll or an appetite for risk")
    assert reader.put("/api/v1/me/favorites", json={"leagues": list(range(1, 52))}).status_code == 422
    assert names(reader.get("/api/v1/me/favorites").json()["leagues"]) == ["Liga Uno"], "nothing changed"


def test_each_reader_sees_and_changes_only_their_own(fresh: Football) -> None:
    f = fresh.ids
    reader, other = client(READER), client(OTHER)
    reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [f["nacional"]]})
    assert other.get("/api/v1/me/favorites").json()["suggested"] is True
    other.put("/api/v1/me/favorites", json={"leagues": [f["dos"]], "teams": []})
    assert names(reader.get("/api/v1/me/favorites").json()["leagues"]) == ["Liga Uno"]
    paths = [getattr(route, "path", "") for route in favorites_router.router.routes]
    assert paths and not [p for p in paths if "{" in p], "no route names an account: each reads the caller's own"
    anonymous = TestClient(create_app(), headers=SAME_SITE)
    assert anonymous.get("/api/v1/me/favorites").status_code == 401
    cross_site = TestClient(create_app())
    cross_site.cookies = reader.cookies
    assert cross_site.put("/api/v1/me/favorites", json={"leagues": [], "teams": []}).status_code == 403


def test_the_options_every_followed_league_and_the_teams_by_name_without_accents(fresh: Football) -> None:
    reader = client(READER)
    options = reader.get("/api/v1/me/favorites/options").json()
    assert {"Liga Uno", "Copa Dos", "Liga BetPlay"} <= set(names(options["leagues"]))
    assert "Liga Lejana" not in names(options["leagues"]) and options["teams"] == []
    for q in ("atletico", "ATLÉTICO nac", "Nacional"):
        assert names(reader.get("/api/v1/me/favorites/options", params={"q": q}).json()["teams"]) == [
            "Atlético Nacional"], q
    assert reader.get("/api/v1/me/favorites/options", params={"q": "a"}).json()["teams"] == [], "two letters or more"
    for q in ("lejano", "viejo", "%%", "__"):  # not followed, out of the window, no wildcard of a search
        assert reader.get("/api/v1/me/favorites/options", params={"q": q}).json()["teams"] == [], q
    medellin = reader.get("/api/v1/me/favorites/options", params={"q": "medellin"}).json()["teams"]
    assert names(medellin) == ["Medellín"], "a team that plays later in a followed league is found too"


# ── the welcome and the hints ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_welcome_once_for_a_reader_never_for_the_owner_nor_with_the_switch_off(
        fresh: Football, database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader, older, owner = client(READER), client(OLDER), client(OWNER)
    me = reader.get("/api/v1/auth/me").json()
    assert (me["welcome_due"], me["welcome_steps"], me["hints_seen"]) == (True, ["football", "about"], [])
    assert older.get("/api/v1/auth/me").json()["welcome_steps"] == ["football"], (
        "an account from before: the favourites alone, never the rest again")
    assert owner.get("/api/v1/auth/me").json()["welcome_due"] is False, "never the owner's accounts"
    state = reader.get("/api/v1/me/onboarding").json()
    assert (state["welcome_due"], state["onboarded_at"]) == (True, None)
    done = reader.post("/api/v1/me/onboarding").json()
    assert done["welcome_due"] is False and done["onboarded_at"] is not None
    again = reader.post("/api/v1/me/onboarding").json()
    assert again["onboarded_at"] == done["onboarded_at"], "recorded once: the first moment stays"
    assert reader.get("/api/v1/auth/me").json()["welcome_due"] is False
    monkeypatch.setenv(favorites.ONBOARDING_SWITCH, "0")
    assert older.get("/api/v1/auth/me").json()["welcome_due"] is False, "FBI_ONBOARDING=0: straight to Home"
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT onboarded_at FROM customer.preferences WHERE user_id = %s",
                            (uid(database, OLDER),)).fetchone() in (None, (None,)), "the switch writes nothing"


def test_a_dismissed_hint_never_comes_back(fresh: Football) -> None:
    reader, other = client(READER), client(OTHER)
    assert reader.post("/api/v1/me/hints", json={"hint": "picks"}).json()["hints_seen"] == ["picks"]
    assert reader.post("/api/v1/me/hints", json={"hint": "picks"}).json()["hints_seen"] == ["picks"], "once"
    assert reader.post("/api/v1/me/hints", json={"hint": "match"}).json()["hints_seen"] == ["picks", "match"]
    assert reader.post("/api/v1/me/hints", json={"hint": "everything"}).status_code == 422
    assert reader.get("/api/v1/auth/me").json()["hints_seen"] == ["picks", "match"]
    assert other.get("/api/v1/auth/me").json()["hints_seen"] == [], "the reader's own"
    assert reader.get("/api/v1/me/onboarding").json()["welcome_due"] is True, "a hint is not the welcome"


# ── Home ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_home_says_why_each_match_is_the_readers_and_lists_the_next_match_of_each_favourite(
        fresh: Football, monkeypatch: pytest.MonkeyPatch) -> None:
    f, fx = fresh.ids, fresh.fixtures
    reader = client(READER)
    reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"], f["betplay"]], "teams": [f["santafe"], f["pereira"]]})
    data = reader.get("/api/v1/today").json()["data"]
    matches = {m["fixture_id"]: m for m in data["matches"]["data"]}
    assert matches[fx["today_uno"]]["followed"] == {"kind": "league", "names": ["Liga Uno"]}
    assert matches[fx["today_dos"]]["followed"] == {"kind": "team", "names": ["Santa Fe"]}, (
        "Copa Dos is not followed: Santa Fe is")
    assert fx["far"] not in matches, "a league PrediGol does not follow is not on the board"
    assert fx["result_dos"] not in matches, "a finished match that is not the reader's is left out of their answer"
    following = data["following"]
    assert (following["suggested"], following["personalization"]) == (False, True)
    assert names(following["leagues"]) == ["Liga Uno", "Liga BetPlay"]
    assert names(following["teams"]) == ["Santa Fe", "Pereira"]
    nexts = [(n["followed"]["kind"], n["followed"]["names"], n["fixture_id"]) for n in following["next"]]
    assert nexts == [("league", ["Liga Uno"], fx["today_uno"]), ("team", ["Santa Fe"], fx["today_dos"]),
                     ("league", ["Liga BetPlay"], fx["betplay_later"])], (
        "kick-off order, beyond the board's 36 hours too; Pereira has no match ahead and is not listed")

    other = client(OTHER).get("/api/v1/today").json()["data"]
    assert other["following"]["suggested"] is True and "Liga BetPlay" in names(other["following"]["leagues"])
    others = {m["fixture_id"]: m for m in other["matches"]["data"]}
    assert others[fx["today_uno"]]["followed"] is None and others[fx["today_dos"]]["followed"] is None
    junior = client(OTHER)
    junior.put("/api/v1/me/favorites", json={"leagues": [], "teams": [f["junior"]]})
    mine = {m["fixture_id"]: m for m in junior.get("/api/v1/today").json()["data"]["matches"]["data"]}
    assert mine[fx["result_dos"]]["followed"] == {"kind": "team", "names": ["Junior"]}, "the result of a followed team"
    junior.put("/api/v1/me/favorites", json={"leagues": [], "teams": []})

    monkeypatch.setenv(favorites.PERSONALIZATION_SWITCH, "0")
    common = reader.get("/api/v1/today").json()["data"]
    assert (common["following"]["suggested"], common["following"]["personalization"]) == (True, False), (
        "FBI_PERSONALIZATION=0: the common view, whatever the reader follows")
    assert common["following"] == other["following"] | {"personalization": False}
    assert names(reader.get("/api/v1/me/favorites").json()["leagues"]) == ["Liga Uno", "Liga BetPlay"], (
        "the favourites stay")


# ── what the account keeps ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_favourites_are_in_the_export_and_go_when_the_account_is_anonymised(fresh: Football, database: str) -> None:
    f = fresh.ids
    reader = client(OTHER)
    reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [f["nacional"]]})
    reader.post("/api/v1/me/hints", json={"hint": "parlay"})
    reader.post("/api/v1/me/onboarding")
    other_id, owner_id = uid(database, OTHER), uid(database, OWNER)
    with psycopg.connect(database) as conn:
        document = privacy.export(conn, other_id)
    assert [(x["kind"], x["id"], x["name"]) for x in document["favorites"]] == [
        ("league", f["uno"], "Liga Uno"), ("team", f["nacional"], "Atlético Nacional")]
    assert document["welcome"]["hints_seen"] == ["parlay"] and document["welcome"]["onboarded_at"] is not None
    anonymize.anonymise(principal("SUPER_ADMIN", user_id=owner_id), other_id, confirm=OTHER, ip=None)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM customer.favorites WHERE user_id = %s", (other_id,)).fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM customer.preferences WHERE user_id = %s", (other_id,)).fetchone() == (0,)


# ── personalise the experience, never the intelligence ────────────────────────────────────────────────────────────────

VOLATILE = frozenset({"generated_at", "window_from", "window_to"})
"""What depends only on the moment of the request (when the answer was made; a parlay's window starts «now»)."""
PERSONAL = frozenset({"followed", "context", "following"})
"""What a reader's favourites may change on Home: why a match is theirs, the context kept for their own, their leagues and
teams. Everything else - the forecasts, the lines, the picks, their states and prices - must be the same for everyone."""


def common_part(value: Any, drop: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {k: common_part(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [common_part(v, drop) for v in value]
    return value


def first_difference(a: Any, b: Any, path: str = "") -> str | None:
    """Where two answers first differ (a path and both values), for the assertion's message."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            found = first_difference(a.get(k), b.get(k), f"{path}.{k}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def reader_app(db: psycopg.Connection[Any], user_id: int) -> TestClient:
    app = create_app()
    app.dependency_overrides[optional_principal] = lambda: principal("USER", user_id=user_id)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def test_two_readers_with_different_favourites_get_the_same_picks_forecasts_and_states(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1")
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1")
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH):
        monkeypatch.delenv(name, raising=False)
    world = World(db, seed)
    now = datetime.now(UTC)
    fid, _pick = world.item(product_day(now), "OU", "Over", "2.5", "PENDING", None, "1.95",
                            kickoff=now + timedelta(hours=5))
    world.fixture(now + timedelta(hours=8))  # a second match of the day, without a pick
    other_league = int(scalar(db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
        "VALUES (7713901, 'Otra Liga', 'league', 'club', 'domestic_league', true) RETURNING id")))
    readers = []
    for email in ("uno.a13@example.org", "dos.a13@example.org"):
        readers.append(int(scalar(db.execute(
            "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES (%s, 'R', '$argon2id$x', 'USER') "
            "RETURNING id", (email,)))))
    first, second = readers
    db.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
               (first, world.competition, world.competition))
    db.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id) VALUES (%s, 'league', %s, %s)",
               (second, other_league, other_league))

    paths = ["/api/v1/today", "/api/v1/today/no-pick", "/api/v1/home", "/api/v1/picks", "/api/v1/daily",
             f"/api/v1/matches/{fid}/forecast", f"/api/v1/matches/{fid}/reading"]
    answers: dict[int, dict[str, Any]] = {}
    for user in readers:
        api = reader_app(db, user)
        answers[user] = {}
        for path in paths:
            r = api.get(path)
            assert r.status_code == 200, (path, r.text)
            answers[user][path] = r.json()
    daily = answers[first]["/api/v1/daily"]["data"]
    assert [i["match"]["fixture_id"] for i in daily["set"]["items"]] == [fid], "the world has a published pick to compare"
    for path in paths:
        mine, theirs = (common_part(answers[user][path], VOLATILE | PERSONAL) for user in readers)
        assert mine == theirs, f"{path}: {first_difference(mine, theirs)}"
    mine = {m["fixture_id"]: m for m in answers[first]["/api/v1/today"]["data"]["matches"]["data"]}
    theirs = {m["fixture_id"]: m for m in answers[second]["/api/v1/today"]["data"]["matches"]["data"]}
    assert mine[fid]["followed"] == {"kind": "league", "names": ["Intel League"]} and theirs[fid]["followed"] is None, (
        "the comparison is not empty: the two readers' own parts differ")
    assert answers[first]["/api/v1/today"]["data"]["following"] != answers[second]["/api/v1/today"]["data"]["following"]

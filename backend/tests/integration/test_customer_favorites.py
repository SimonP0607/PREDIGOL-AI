"""A reader's favourites, the welcome and the hints against the migrated database (plan UX, A13 and closing plan 3.1).

* The favourites over HTTP, signed in for real: the suggested ones for Colombia, labelled, until the reader chooses; exactly
  the ones chosen, in their order, idempotent; the limits and what cannot be followed refused (422, never trimmed); each
  reader sees and changes only their own; the options - every league PrediGol follows and the teams of those leagues by name,
  without accents or case.
* Players and markets (3.1): followed in the reader's order, kept by a save that leaves them out (a page from before), cleared
  by an empty list; only players who appeared in a line-up of a league PrediGol follows within the window, but one already
  followed stays when it ages out; found by name from three letters; in the export, gone with the account.
* The welcome once per reader account (the whole one for a new account, the favourites alone for an older one), never for the
  owner's, never with FBI_ONBOARDING=0; a dismissed hint never comes back. Both reach the page through GET /auth/me.
* Home (GET /today): each of the reader's matches says why it is theirs, and the next match of each favourite is listed.
* «Para ti» (GET /me/today, closing plan 3.2): nothing until the reader chooses - the suggested leagues never count -; the
  players they follow with the state of the next match of his team (starter, bench, left out, missing, doubtful or waiting - the
  published line-up first, then the provider's current absences); which of the day's published picks are of their teams, leagues
  or markets (or none) and their bells; the same picks for every reader.
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


PLAYERS = {"james": (7713501, "James Rodríguez", "Midfielder"), "falcao": (7713502, "Radamel Falcao", "Attacker"),
           "viejo": (7713503, "Jugador Viejo", "Defender"), "lejano": (7713504, "Jugador Lejano", "Goalkeeper"),
           "sin": (7713505, "Sin Alineación", None)}
"""This module's players: provider id, name, position. James played for Millonarios in a match of Liga Uno today, Falcao for
Atlético Nacional ten days ago; Viejo only 500 days ago and Lejano only in a league PrediGol does not follow; Sin never
appears in a line-up."""


@pytest.fixture(scope="module")
def players(database: str, football: Football, seed: Seed) -> Iterator[dict[str, int]]:
    ids: dict[str, int] = {}
    fx = football.fixtures
    lineups = (("james", "today_uno", "home"), ("falcao", "past_uno", "home"), ("viejo", "ancient", "home"),
               ("lejano", "far", "home"))
    with psycopg.connect(database, autocommit=True) as conn:
        for key, (provider, name, position) in PLAYERS.items():
            ids[key] = int(scalar(conn.execute(
                "INSERT INTO core.players (provider_player_id, name, position) VALUES (%s, %s, %s) RETURNING id",
                (provider, name, position))))
        for key, fixture, side in lineups:
            conn.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                         "VALUES (%s, %s, 'api-football', %s, now())", (fx[fixture], side, seed.payload_hash))
            conn.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
                         "player_name, is_starter) VALUES (%s, %s, 'api-football', %s, %s, true)",
                         (fx[fixture], side, PLAYERS[key][0], PLAYERS[key][1]))
    yield ids
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("DELETE FROM core.players WHERE provider_player_id = ANY(%s)", ([p for p, _, _ in PLAYERS.values()],))


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


# ── players and markets (closing plan 3.1) ────────────────────────────────────────────────────────────────────────────


def test_players_and_markets_are_followed_in_the_readers_order_and_a_save_without_them_keeps_them(
        fresh: Football, players: dict[str, int], database: str) -> None:
    f, reader, other = fresh.ids, client(READER), client(OTHER)
    body = {"leagues": [f["uno"]], "teams": [f["nacional"]], "players": [players["falcao"], players["james"]],
            "markets": ["OU", "1X2"]}
    first = reader.put("/api/v1/me/favorites", json=body)
    assert first.status_code == 200, first.text
    view = first.json()
    assert [(p["name"], p["position"], p["team"]) for p in view["players"]] == [
        ("Radamel Falcao", "Attacker", "Atlético Nacional"), ("James Rodríguez", "Midfielder", "Millonarios")], (
        "in the reader's order, each with the team of its latest line-up")
    assert view["markets"] == ["OU", "1X2"] and (view["max_players"], view["max_markets"]) == (20, 5)
    assert reader.put("/api/v1/me/favorites", json=body).json() == view, "idempotent"
    with psycopg.connect(database) as conn:
        rows = conn.execute("SELECT kind, ref_id, league_id, team_id, player_id, market_key FROM customer.favorites "
                            "WHERE user_id = %s ORDER BY created_at, ref_id NULLS LAST", (uid(database, READER),)).fetchall()
    assert rows == [("league", f["uno"], f["uno"], None, None, None), ("team", f["nacional"], None, f["nacional"], None, None),
                    ("player", players["falcao"], None, None, players["falcao"], None),
                    ("player", players["james"], None, None, players["james"], None),
                    ("market", None, None, None, None, "OU"), ("market", None, None, None, None, "1X2")]
    # a page from before 3.1 sends leagues and teams alone: the players and the markets stay
    stale = reader.put("/api/v1/me/favorites", json={"leagues": [f["dos"]], "teams": []}).json()
    assert names(stale["leagues"]) == ["Copa Dos"] and stale["teams"] == []
    assert [p["name"] for p in stale["players"]] == ["Radamel Falcao", "James Rodríguez"] and stale["markets"] == ["OU", "1X2"]
    # [] clears one kind and leaves the other
    fewer = reader.put("/api/v1/me/favorites", json={"leagues": [f["dos"]], "teams": [], "players": [players["james"]],
                                                     "markets": []}).json()
    assert [p["name"] for p in fewer["players"]] == ["James Rodríguez"] and fewer["markets"] == []
    # only the players and the markets chosen: with no league nor team the suggested ones come back, labelled, and the
    # players and the markets are the reader's
    only = reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": [], "markets": ["BTTS"]}).json()
    assert only["suggested"] is True and [p["name"] for p in only["players"]] == ["James Rodríguez"]
    assert only["markets"] == ["BTTS"]
    seen = other.get("/api/v1/me/favorites").json()
    assert seen["players"] == [] and seen["markets"] == [], "each reader sees only their own"


def test_a_player_must_have_played_in_a_followed_league_and_a_market_must_be_one_predigol_reads(
        fresh: Football, players: dict[str, int]) -> None:
    f, reader = fresh.ids, client(READER)
    base = {"leagues": [f["uno"]], "teams": []}
    assert reader.put("/api/v1/me/favorites", json={**base, "players": [players["james"]]}).status_code == 200
    for key in ("viejo", "lejano", "sin"):  # 500 days ago; a league PrediGol does not follow; never in a line-up
        r = reader.put("/api/v1/me/favorites", json={**base, "players": [players[key]]})
        assert (r.status_code, code(r)) == (422, "unknown_player"), key
    unknown = reader.put("/api/v1/me/favorites", json={**base, "players": [players["james"], 987654321]})
    assert (unknown.status_code, code(unknown)) == (422, "unknown_player")
    many = reader.put("/api/v1/me/favorites", json={**base, "players": list(range(1, 22))})
    assert (many.status_code, code(many)) == (422, "too_many_players")
    for body in ({"markets": ["FOO"]}, {"markets": ["1X2"] * 11}, {"players": list(range(1, 52))},
                 {"markets": ["1X2"], "stake": 10}):  # an unknown market, too long a list, an amount: never
        assert reader.put("/api/v1/me/favorites", json={**base, **body}).status_code == 422, body
    after = reader.get("/api/v1/me/favorites").json()
    assert [p["name"] for p in after["players"]] == ["James Rodríguez"] and after["markets"] == [], "nothing changed"


def test_a_player_already_followed_stays_when_the_window_passes_and_never_blocks_a_save(
        fresh: Football, players: dict[str, int], database: str) -> None:
    f, reader = fresh.ids, client(READER)
    with psycopg.connect(database, autocommit=True) as conn:  # followed when it was in the window, aged out since
        conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, player_id) VALUES (%s, 'player', %s, %s)",
                     (uid(database, READER), players["viejo"], players["viejo"]))
    both = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [],
                                                    "players": [players["viejo"], players["james"]]})
    assert both.status_code == 200, both.text
    assert [p["name"] for p in both.json()["players"]] == ["Jugador Viejo", "James Rodríguez"]
    assert both.json()["players"][0]["team"] == "Equipo Viejo", "still listed, with the team of its latest line-up"
    dropped = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [], "players": [players["james"]]})
    assert [p["name"] for p in dropped.json()["players"]] == ["James Rodríguez"], "and the reader may drop it"
    again = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [],
                                                     "players": [players["viejo"]]})
    assert (again.status_code, code(again)) == (422, "unknown_player"), "once dropped it is asked for like any other"


def test_the_options_find_players_by_name_from_three_letters_without_accents(
        fresh: Football, players: dict[str, int]) -> None:
    reader = client(READER)
    found = {q: reader.get("/api/v1/me/favorites/options", params={"q": q}).json()["players"]
             for q in ("james", "RODRIGUEZ", "radamel", "ja", "viejo", "lejano", "sin ali", "%%%", "___")}
    assert [(p["id"], p["name"], p["team"]) for p in found["james"]] == [
        (players["james"], "James Rodríguez", "Millonarios")]
    assert names(found["RODRIGUEZ"]) == ["James Rodríguez"] and names(found["radamel"]) == ["Radamel Falcao"]
    assert found["ja"] == [], "three letters or more"
    for q in ("viejo", "lejano", "sin ali", "%%%", "___"):  # aged out, not followed, no line-up, no wildcard of a search
        assert found[q] == [], q
    assert reader.get("/api/v1/me/favorites/options").json()["players"] == [], "no search, no players"
    teams = reader.get("/api/v1/me/favorites/options", params={"q": "nacional"}).json()
    assert names(teams["teams"]) == ["Atlético Nacional"] and teams["players"] == []


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


def test_the_favourites_are_in_the_export_and_go_when_the_account_is_anonymised(
        fresh: Football, players: dict[str, int], database: str) -> None:
    f = fresh.ids
    reader = client(OTHER)
    reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [f["nacional"]],
                                             "players": [players["james"]], "markets": ["BTTS"],
                                             "catalog_markets": [CORNERS]})
    reader.post("/api/v1/me/hints", json={"hint": "parlay"})
    reader.post("/api/v1/me/onboarding")
    other_id, owner_id = uid(database, OTHER), uid(database, OWNER)
    with psycopg.connect(database) as conn:
        document = privacy.export(conn, other_id)
    assert [(x["kind"], x["id"], x["market"], x["name"]) for x in document["favorites"]] == [
        ("league", f["uno"], None, "Liga Uno"), ("team", f["nacional"], None, "Atlético Nacional"),
        ("player", players["james"], None, "James Rodríguez"), ("market", None, "BTTS", None),
        ("catalog", None, CORNERS, None)], (
        "a market has no id, only its key")
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
            "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES (%s, %s, '$argon2id$x', 'USER') "
            "RETURNING id", (email, email)))))
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


# ── «Para ti»: the reader's layer of Home (closing plan 3.2) ──────────────────────────────────────────────────────────


def test_me_today_is_empty_until_the_reader_chooses_and_the_suggested_ones_never_count(
        fresh: Football, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = {"personalization": True, "chosen": False, "players": [], "markets": [], "picks": None, "notices": None}
    reader = client(READER)
    assert reader.get("/api/v1/me/today").json() == empty, "the suggested leagues are not the reader's"
    assert client(OWNER).get("/api/v1/me/today").json() == empty, "the owner's console account has no layer of its own"
    reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": [], "markets": ["OU"]})
    body = reader.get("/api/v1/me/today").json()
    assert (body["chosen"], body["markets"], body["players"]) == (True, ["OU"], []), (
        "a market alone is a favourite: it makes «Para ti»")
    assert body["picks"]["items"] == [] and body["notices"]["bells"] == []
    monkeypatch.setenv(favorites.PERSONALIZATION_SWITCH, "0")
    assert reader.get("/api/v1/me/today").json() == empty | {"personalization": False}, (
        "FBI_PERSONALIZATION=0: the common view, whatever the reader follows")


def test_a_followed_player_says_what_the_next_match_of_his_team_has_for_him(
        fresh: Football, players: dict[str, int], database: str, seed: Seed) -> None:
    fx = fresh.fixtures
    reader = client(READER)
    assert reader.put("/api/v1/me/favorites", json={"leagues": [], "teams": [], "players": [
        players["james"], players["falcao"]]}).status_code == 200
    me = uid(database, READER)
    with psycopg.connect(database, autocommit=True) as conn:
        for key in ("viejo", "lejano", "sin"):  # kept from before: aged out, a league PrediGol does not follow, never listed
            conn.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, player_id) VALUES (%s, 'player', %s, %s)",
                         (me, players[key], players[key]))

    def states() -> dict[str, dict[str, Any]]:
        got = reader.get("/api/v1/me/today").json()["players"]
        return {p["name"]: p for p in got}

    first = reader.get("/api/v1/me/today").json()
    assert [p["name"] for p in first["players"]] == [
        "James Rodríguez", "Radamel Falcao", "Jugador Viejo", "Jugador Lejano", "Sin Alineación"], (
        "in the order the reader chose them")
    got = states()
    james, falcao = got["James Rodríguez"], got["Radamel Falcao"]
    assert (james["state"], james["team"]["name"], james["next"]["fixture_id"]) == ("starter", "Millonarios", fx["today_uno"])
    assert james["position"] == "Midfielder" and james["reason"] is None
    assert (falcao["state"], falcao["team"]["name"], falcao["next"]["fixture_id"]) == (
        "waiting", "Atlético Nacional", fx["today_uno"]), "his side's line-up is not out and nothing is reported"
    for name in ("Jugador Viejo", "Jugador Lejano", "Sin Alineación"):
        assert (got[name]["state"], got[name]["team"], got[name]["next"], got[name]["reason"]) == (
            "no_match", None, None, None), "never invent a match for a player with no team PrediGol follows"

    at = datetime.now(UTC)
    provider_fixture = 7713101
    falcao_provider = PLAYERS["falcao"][0]

    def report(conn: psycopg.Connection[Any], kind: str, reason: str, player: int, fetched: datetime) -> None:
        conn.execute("INSERT INTO core.player_absences (source, provider_fixture_id, provider_player_id, fixture_id, "
                     "player_name, absence_type, reason, payload_hash, fetched_at) VALUES ('api-football', %s, %s, %s, 'x', "
                     "%s, %s, %s, %s)", (provider_fixture, player, fx["today_uno"], kind, reason, seed.payload_hash, fetched))

    with psycopg.connect(database, autocommit=True) as conn:
        try:
            report(conn, "Missing Fixture", "Knee Injury", falcao_provider, at)
            hurt = states()["Radamel Falcao"]
            assert (hurt["state"], hurt["reason"]) == ("absent", "Knee Injury")
            conn.execute("UPDATE core.player_absences SET absence_type = 'Questionable' WHERE provider_player_id = %s",
                         (falcao_provider,))
            assert states()["Radamel Falcao"]["state"] == "doubtful"
            report(conn, "Missing Fixture", "Illness", PLAYERS["sin"][0], at + timedelta(minutes=5))
            recovered = states()["Radamel Falcao"]
            assert (recovered["state"], recovered["reason"]) == ("waiting", None), (
                "the provider's newest answer no longer names him: he has recovered or was never out")
            conn.execute("DELETE FROM core.player_absences WHERE fixture_id = %s", (fx["today_uno"],))

            conn.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                         "VALUES (%s, 'away', 'api-football', %s, now())", (fx["today_uno"], seed.payload_hash))
            conn.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
                         "player_name, is_starter) VALUES (%s, 'away', 'api-football', %s, 'Sin Alineación', true)",
                         (fx["today_uno"], PLAYERS["sin"][0]))
            assert states()["Radamel Falcao"]["state"] == "left_out", "the line-up is out and he is not in it"
            report(conn, "Missing Fixture", "Suspended", falcao_provider, at)
            assert states()["Radamel Falcao"]["state"] == "absent", "out of a published line-up and reported: absent"
            conn.execute("DELETE FROM core.player_absences WHERE fixture_id = %s", (fx["today_uno"],))
            conn.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
                         "player_name, is_starter) VALUES (%s, 'away', 'api-football', %s, 'Radamel Falcao', false)",
                         (fx["today_uno"], falcao_provider))
            assert states()["Radamel Falcao"]["state"] == "bench"
            conn.execute("UPDATE core.fixture_lineup_players SET is_starter = true WHERE provider_player_id = %s AND "
                         "fixture_id = %s", (falcao_provider, fx["today_uno"]))
            assert states()["Radamel Falcao"]["state"] == "starter"
            report(conn, "Missing Fixture", "Knee Injury", falcao_provider, at)
            assert states()["Radamel Falcao"]["state"] == "starter", "a player named in the line-up plays: it is newer"
        finally:
            conn.execute("DELETE FROM core.player_absences WHERE fixture_id = %s", (fx["today_uno"],))
            conn.execute("DELETE FROM core.fixture_lineups WHERE fixture_id = %s AND team_side = 'away'", (fx["today_uno"],))


def test_para_ti_marks_which_of_todays_picks_are_the_readers_and_their_bells(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH):
        monkeypatch.delenv(name, raising=False)
    world = World(db, seed)
    now = datetime.now(UTC)
    day = product_day(now)
    over, _ = world.item(day, "OU", "Over", "2.5", "PENDING", None, "1.95", kickoff=now + timedelta(hours=5))
    home, _ = world.item(day, "1X2", "Home", "0", "PENDING", None, "1.90", kickoff=now + timedelta(hours=6))
    home_team = int(scalar(db.execute("SELECT home_team_id FROM core.fixtures WHERE id = %s", (over,))))
    other_league = int(scalar(db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
        "VALUES (7713902, 'Otra Liga', 'league', 'club', 'domestic_league', true) RETURNING id")))
    users = {}
    for key in ("team", "league", "market", "elsewhere", "player"):
        users[key] = int(scalar(db.execute(
            "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES (%s, %s, '$argon2id$x', 'USER') "
            "RETURNING id", (f"{key}.p32@example.org", f"{key}.p32@example.org"))))

    def follow(who: str, kind: str, ref: int | None, market: str | None = None) -> None:
        db.execute("INSERT INTO customer.favorites (user_id, kind, ref_id, league_id, team_id, player_id, market_key) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (users[who], kind, ref, ref if kind == "league" else None, ref if kind == "team" else None,
                    ref if kind == "player" else None, market))

    follow("team", "team", home_team)
    follow("league", "league", world.competition)
    follow("market", "market", None, "1X2")
    follow("elsewhere", "league", other_league)
    db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (7713951, 'Jugador P32')")
    follow("player", "player", int(scalar(db.execute("SELECT id FROM core.players WHERE provider_player_id = 7713951"))))
    db.execute("INSERT INTO customer.match_alerts (user_id, fixture_id, minutes_before) VALUES (%s, %s, 30)",
               (users["team"], over))

    def answer(who: str) -> dict[str, Any]:
        r = reader_app(db, users[who]).get("/api/v1/me/today")
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        return body

    def picks(who: str) -> list[tuple[int, int, str | None, bool]]:
        got = answer(who)["picks"]
        assert got["published"] == 2 and got["day"] == day.isoformat()
        return [(i["rank"], i["fixture_id"], (i["followed"] or {}).get("kind"), i["market_followed"]) for i in got["items"]]

    assert picks("team") == [(1, over, "team", False)], "the team plays the first pick's match"
    assert picks("league") == [(1, over, "league", False), (2, home, "league", False)]
    assert picks("market") == [(2, home, None, True)], "a market alone: the pick of that market, and why"
    assert picks("elsewhere") == [], "none of today's two picks is theirs - the day has them, they are not the reader's"
    alone = answer("player")["picks"]
    assert alone is not None and alone["published"] == 2 and alone["items"] == [], (
        "a player without a match to come: the day's picks are not his, and it says so")
    assert [p["name"] for p in answer("player")["players"]] == ["Jugador P32"]
    assert answer("player")["players"][0]["state"] == "no_match"

    bells = answer("team")["notices"]
    assert [(b["fixture_id"], b["minutes_before"]) for b in bells["bells"]] == [(over, 30)]
    assert (bells["available"], bells["devices"], bells["lineup"]) == (False, 0, True), (
        "FBI_PUSH is off in the tests: no invitation, no device, the line-up category on by default")
    assert answer("league")["notices"]["bells"] == [], "each reader's own bells"

    shown = reader_app(db, users["team"]).get("/api/v1/daily").json()["data"]["set"]["items"]
    assert [(i["rank"], i["match"]["fixture_id"]) for i in shown] == [(1, over), (2, home)], (
        "the picks themselves are the day's, whoever reads: «Para ti» only says which are theirs")


# ── markets of the catalogue (CUOTAS, BE-025) ─────────────────────────────────────────────────────────────────────────

CORNERS, CARDS, BTTS_1H = "corners_over_under.FT.match", "yellow_cards_1x2.FT.home", "goals_btts.1H.match"


def test_markets_of_the_catalogue_are_followed_apart_from_the_five_classic_ones(
        fresh: Football, database: str) -> None:
    f, reader = fresh.ids, client(READER)
    base = {"leagues": [f["uno"]], "teams": []}
    first = reader.put("/api/v1/me/favorites", json={**base, "markets": ["OU"], "catalog_markets": [CORNERS, CARDS]})
    assert first.status_code == 200, first.text
    view = first.json()
    assert view["catalog_markets"] == [CORNERS, CARDS] and view["markets"] == ["OU"], "two lists, never mixed"
    assert (view["max_markets"], view["max_catalog_markets"]) == (5, 10)
    assert reader.put("/api/v1/me/favorites", json={**base, "markets": ["OU"],
                                                    "catalog_markets": [CORNERS, CARDS]}).json() == view, "idempotent"
    with psycopg.connect(database) as conn:
        rows = conn.execute("SELECT kind, market_key, catalog_key FROM customer.favorites WHERE user_id = %s "
                            "AND kind IN ('market', 'catalog') ORDER BY created_at, ref_id NULLS LAST",
                            (uid(database, READER),)).fetchall()
    assert rows == [("market", "OU", None), ("catalog", None, CORNERS), ("catalog", None, CARDS)]
    # a page from before BE-025 sends no catalogue markets: they stay; [] clears them and leaves the classic market
    stale = reader.put("/api/v1/me/favorites", json={**base, "markets": ["OU", "BTTS"]}).json()
    assert stale["catalog_markets"] == [CORNERS, CARDS] and stale["markets"] == ["OU", "BTTS"]
    swapped = reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": [CARDS, BTTS_1H]}).json()
    assert swapped["catalog_markets"] == [CARDS, BTTS_1H] and swapped["markets"] == ["OU", "BTTS"]
    cleared = reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": []}).json()
    assert cleared["catalog_markets"] == [] and cleared["markets"] == ["OU", "BTTS"]


def test_a_catalogue_market_must_be_one_the_taxonomy_names_within_the_limit(fresh: Football) -> None:
    f, reader = fresh.ids, client(READER)
    base = {"leagues": [f["uno"]], "teams": []}
    assert reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": [CORNERS]}).status_code == 200
    for key in ("FOO", "corners_over_under.FT", "corners_over_under.XX.match", "corners_over_under.FT.coach",
                "nonsense_market.FT.match", "bet_999999999.FT.match", "Corners_Over_Under.FT.match",
                "corners_over_under.FT.match; DROP TABLE x", "a" * 90):
        r = reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": [key]})
        assert (r.status_code, code(r)) == (422, "unknown_catalog_market"), key
    keys = [f"{c}.{p}.match" for c in ("corners_over_under", "goals_btts", "result_1x2") for p in ("FT", "1H", "2H")]
    many = reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": [*keys, "goals_odd_even.FT.match", "cards_over_under.FT.match"]})
    assert (many.status_code, code(many)) == (422, "too_many_catalog_markets")
    assert reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": keys + ["x"] * 12}).status_code == 422
    assert reader.put("/api/v1/me/favorites", json={**base, "catalog_markets": [CORNERS], "stake": 10}).status_code == 422
    after = reader.get("/api/v1/me/favorites").json()
    assert after["catalog_markets"] == [CORNERS], "nothing changed"


def test_a_followed_catalogue_market_never_blocks_a_save_when_the_taxonomy_forgets_it(
        fresh: Football, database: str) -> None:
    f, reader = fresh.ids, client(READER)
    with psycopg.connect(database, autocommit=True) as conn:  # followed when the taxonomy had it
        conn.execute("INSERT INTO customer.favorites (user_id, kind, catalog_key) VALUES (%s, 'catalog', 'retired_market.FT.match')",
                     (uid(database, READER),))
    r = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [],
                                                 "catalog_markets": ["retired_market.FT.match", CORNERS]})
    assert r.status_code == 200, r.text
    assert r.json()["catalog_markets"] == ["retired_market.FT.match", CORNERS]
    only_new = reader.put("/api/v1/me/favorites", json={"leagues": [f["uno"]], "teams": [], "catalog_markets": ["other_retired.FT.match"]})
    assert (only_new.status_code, code(only_new)) == (422, "unknown_catalog_market"), "a new one still has to be valid"

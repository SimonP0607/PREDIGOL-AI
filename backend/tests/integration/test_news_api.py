"""The news (plan UX, A10) in a real database: a match's cards in the order of section 27 with only its own items - never another
match's, never the data provider's reports or the owner's notes, never an article's text or title -, the exact empty answer, the
owner's switch, Home's confirmed or probable news of the suggested matches not yet over, and nothing written while they answer.
The transaction is rolled back."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import news as service
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
ARTICLE = "TEXTO-COMPLETO-DEL-ARTICULO-QUE-NUNCA-SALE"
_provider_ids = count(9_810_001)


def client(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1" if on else "0")
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def fixture(db: psycopg.Connection[Any], seed: Seed, kickoff: datetime, *, season: int | None = None,
            status: str = "scheduled") -> int:
    return int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
        "status_group) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (next(_provider_ids), season or seed.season_id, seed.home_team_id, seed.away_team_id, kickoff, status))))


def evidence(db: psycopg.Connection[Any], fid: int, team: int | None, *, status: str, claim: str, kind: str = "injury",
             assertion: str = "out", player: str | None = None, origin: str = "web", tier: str = "media",
             source: str = "www.sport.es", url: str | None = "https://www.sport.es/es/noticias/1",
             published: datetime | None = None, retrieved: datetime | None = None, story: str | None = None,
             title: str | None = None) -> int:
    retrieved = retrieved or NOW - timedelta(hours=1)
    story = story or f"{origin}:{fid}:{team}:{player or 'team'}:{kind}:{assertion}"
    attributes = {"assertion": assertion, "player_name": player}
    if title is not None:
        attributes["result_title"] = title
    digest = hashlib.sha256(json.dumps([story, claim, url, source, str(published)]).encode()).hexdigest()
    return int(scalar(db.execute(
        "INSERT INTO ai.evidence (fixture_id, team_id, kind, claim, origin, source_name, source_url, source_domain, "
        "source_tier, published_at, retrieved_at, story_key, content_hash, confidence, relevance, attributes, status, "
        "status_reason, status_changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0.5, 0.6, %s, %s, "
        "'test', %s) RETURNING id",
        (fid, team, kind, claim, origin, source, url, None, tier, published, retrieved, story, digest, Jsonb(attributes),
         status, retrieved))))


def test_a_matchs_news_in_the_order_of_section_27_with_only_its_own_items_and_never_an_articles_text(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    home, away = seed.home_team_id, seed.away_team_id
    match = fixture(db, seed, NOW + timedelta(hours=5))
    next_one = fixture(db, seed, NOW + timedelta(hours=30))  # the same teams, another match
    title = "Bruno Fernandes se pierde el partido ante el Liverpool por una lesión"
    story = f"web:{match}:home:bruno fernandes:injury:out"
    evidence(db, match, home, status="CONFIRMED", player="Bruno Fernandes", story=story, title=title,
             claim="Según Sport, Bruno Fernandes es baja por lesión para este partido.",
             published=NOW - timedelta(hours=3))
    evidence(db, match, home, status="CONFIRMED", player="Bruno Fernandes", story=story, source="as.com",
             url="https://as.com/futbol/1", published=NOW - timedelta(hours=2), title=title,
             claim="Según As, Bruno Fernandes no estará ante el Liverpool por una lesión muscular.")
    day = (NOW - timedelta(days=2)).replace(hour=0, minute=0, second=0)
    evidence(db, match, away, status="PROBABLE", kind="doubtful", assertion="doubtful", player="Mohamed Salah",
             source="www.marca.com", url="https://www.marca.com/1", published=day,
             claim="Según Marca, Mohamed Salah está en duda por unas molestias en el tobillo.")
    evidence(db, match, home, status="PROBABLE", player="Casemiro", published=NOW - timedelta(hours=1), title=title,
             claim=f"Según el medio, {title.lower()} y el club lo confirmará mañana.")
    evidence(db, match, home, status="PROBABLE", player=None, tier="unknown", source="www.hakimiyet.com",
             url="https://www.hakimiyet.com/1",
             claim="Gençlerbirliği'nden iki futbolcunun sakatlık nedeniyle kadroda olmaması bekleniyor.")  # noqa: RUF001
    evidence(db, match, home, status="PROBABLE", kind="news", assertion="info", player=None,
             claim="El entrenador dice esperar un partido difícil; el texto no informa de bajas.")
    evidence(db, match, away, status="CONTRADICTORY", kind="suspension", assertion="out", player="Luis Díaz",
             source="www.marca.com", url="https://www.marca.com/2", published=NOW - timedelta(hours=6),
             claim="Según Marca, Luis Díaz cumple sanción y no jugará este partido.")
    evidence(db, match, away, status="CONTRADICTORY", kind="suspension", assertion="available", player="Luis Diaz",
             source="as.com", url="https://as.com/2", published=NOW - timedelta(hours=4),
             claim="Según As, Luis Díaz ya cumplió su sanción y está disponible para este partido.")
    evidence(db, match, away, status="RUMOR", player="Virgil van Dijk", tier="aggregator", source="besoccer.com",
             url="https://besoccer.com/1", claim="Según un agregador, Virgil van Dijk sería baja por lesión.")
    evidence(db, match, home, status="OUTDATED", player="Lisandro Martínez", published=NOW - timedelta(days=12),
             claim="Según Sport, Lisandro Martínez es baja por lesión para este partido.")
    # never shown: the data provider's report, the owner's note, another match of the same teams
    evidence(db, match, home, status="CONFIRMED", origin="provider", url=None, source="API-Football /injuries",
             tier="provider", player="Harry Maguire", claim="H. Maguire (Manchester United): Missing Fixture - Injury")
    evidence(db, match, home, status="CONFIRMED", origin="owner", url=None, source="owner", tier="official",
             player="Owner Note", claim="Nota privada del dueño sobre este partido para su revisión.")
    evidence(db, next_one, home, status="CONFIRMED", player="Another Match",
             claim="Según Sport, Another Match es baja por lesión para el partido siguiente.")
    db.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES "
               "('url', %s, %s, %s, %s, %s)",
               (f"{match}:https://www.sport.es/es/noticias/1", NOW - timedelta(hours=1), NOW + timedelta(days=6), "d" * 64,
                Jsonb({"text": ARTICLE, "title": title})))

    r = client(db, monkeypatch).get(f"/api/v1/matches/{match}/news")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["meta"]["count"] == 8
    data = body["data"]
    items = data["items"]
    assert [(i["status"], i["player"], i["relevance"]) for i in items] == [
        ("CONFIRMED", "Bruno Fernandes", "high"),
        ("PROBABLE", "Casemiro", "high"), ("PROBABLE", "Mohamed Salah", "high"),
        ("PROBABLE", None, "medium"), ("PROBABLE", None, "low"),
        ("CONTRADICTORY", "Luis Diaz", "high"),
        ("RUMOR", "Virgil van Dijk", "high"),
        ("OUTDATED", "Lisandro Martínez", "high"),
    ]
    assert data["counts"] == {"CONFIRMED": 1, "PROBABLE": 4, "CONTRADICTORY": 1, "RUMOR": 1, "OUTDATED": 1}
    confirmed = items[0]
    assert confirmed["team"] == {"id": home, "name": "Manchester United", "side": "home"}
    [claim] = confirmed["claims"]
    assert claim["text"] == "Según As, Bruno Fernandes no estará ante el Liverpool por una lesión muscular."
    assert claim["lang"] == "es" and claim["assertion"] == "out"
    assert [(s["name"], s["tier"], s["url"]) for s in claim["sources"]] == [
        ("as.com", "media", "https://as.com/futbol/1"), ("sport.es", "media", "https://www.sport.es/es/noticias/1")]
    assert items[1]["claims"][0]["text"] is None, "a summary that repeats the source's title is not sent"
    salah = items[2]
    assert salah["published_day_only"] is True and salah["claims"][0]["sources"][0]["published_day_only"] is True
    assert items[3]["claims"][0]["text"] is None, "a summary that does not read as Spanish is not sent"
    contradiction = items[5]
    assert [(c["assertion"], c["sources"][0]["name"]) for c in contradiction["claims"]] == [("available", "as.com"),
                                                                                           ("out", "marca.com")]
    assert contradiction["team"]["side"] == "away"
    text = r.text
    for never in (ARTICLE, title, "Maguire", "Missing Fixture", "Nota privada", "Another Match", "result_title"):
        assert never not in text, never


def test_a_match_without_news_says_so_and_the_owner_can_turn_them_off(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    match = fixture(db, seed, NOW + timedelta(hours=5))
    evidence(db, match, seed.home_team_id, status="CONFIRMED", origin="provider", url=None, tier="provider",
             source="API-Football /injuries", player="Harry Maguire",
             claim="H. Maguire (Manchester United): Missing Fixture - Injury")
    api = client(db, monkeypatch)
    empty = api.get(f"/api/v1/matches/{match}/news").json()
    assert empty["status"] == "empty" and empty["reason"] and empty["data"]["items"] == []
    assert empty["data"]["counts"] == {"CONFIRMED": 0, "PROBABLE": 0, "CONTRADICTORY": 0, "RUMOR": 0, "OUTDATED": 0}
    assert api.get("/api/v1/matches/987654321/news").status_code == 404
    off = client(db, monkeypatch, on=False)
    hidden = off.get(f"/api/v1/matches/{match}/news").json()
    assert hidden["status"] == "not_available" and hidden["data"] is None
    assert off.get("/api/v1/today/news").json()["status"] == "not_available"


def test_home_news_are_a_summary_of_the_suggested_matches_not_yet_over(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    home = seed.home_team_id
    soon = fixture(db, seed, NOW + timedelta(hours=4))
    evidence(db, soon, home, status="RUMOR", player="Rumoured", tier="aggregator", source="besoccer.com",
             url="https://besoccer.com/1", claim="Según un agregador, Rumoured sería baja por lesión.")
    evidence(db, soon, home, status="OUTDATED", player="Old", claim="Según Sport, Old es baja por lesión para este partido.")
    evidence(db, soon, home, status="CONFIRMED", player="Confirmed",
             claim="Según Sport, Confirmed es baja por lesión para este partido.")
    for name in ("Uno", "Dos", "Tres"):
        evidence(db, soon, home, status="PROBABLE", player=name,
                 claim=f"Según Sport, {name} es baja por lesión para este partido.")
    played = fixture(db, seed, NOW - timedelta(hours=2), status="finished")
    evidence(db, played, home, status="CONFIRMED", player="Played", claim="Según Sport, Played es baja por lesión hoy.")
    later = fixture(db, seed, NOW + timedelta(hours=40))
    evidence(db, later, home, status="CONFIRMED", player="Later", claim="Según Sport, Later es baja por lesión ese día.")
    comp = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                             "is_tracked) VALUES (999002, 'Liga de Prueba', 'league', 'club', 'domestic_league', true) "
                             "RETURNING id"))
    season = int(scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) "
                                   "RETURNING id", (comp,))))
    elsewhere = fixture(db, seed, NOW + timedelta(hours=3), season=season)
    evidence(db, elsewhere, home, status="CONFIRMED", player="Elsewhere",
             claim="Según Sport, Elsewhere es baja por lesión para este partido.")

    official = fixture(db, seed, NOW + timedelta(hours=6))
    evidence(db, official, home, status="CONFIRMED", player="Official", tier="official", source="premierleague.com",
             url="https://www.premierleague.com/news/1", claim="Según el club, Official es baja por lesión para este partido.")

    body = client(db, monkeypatch).get("/api/v1/today/news").json()
    assert body["status"] == "ok"
    items = body["data"]["items"]
    assert {i["match"]["fixture_id"] for i in items} == {soon, official}, "only the matches not over, inside the window"
    assert [(i["match"]["fixture_id"], i["item"]["status"]) for i in items] == [
        (official, "CONFIRMED"), (soon, "PROBABLE"), (soon, "PROBABLE")], (
        "three at most, two per match; the confirmed one by an official source first, the one-outlet «confirmed» as probable, "
        "no room for the rumour")
    match = items[1]["match"]
    assert (match["home"], match["away"], match["competition"], match["status_group"]) == (
        "Manchester United", "Liverpool", "Premier League", "scheduled")


def test_home_news_say_one_rumour_when_there_is_room_and_scope_general_is_the_suggested_ones(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    soon = fixture(db, seed, NOW + timedelta(hours=4))
    evidence(db, soon, seed.home_team_id, status="PROBABLE", player="Uno",
             claim="Según Sport, Uno es baja por lesión para este partido.")
    for name in ("Dos", "Tres"):
        evidence(db, soon, seed.home_team_id, status="RUMOR", player=name, tier="aggregator", source="besoccer.com",
                 url=f"https://besoccer.com/{name}", claim=f"Según un agregador, {name} sería baja por lesión.")
    for scope in ("mine", "general"):
        body = client(db, monkeypatch).get("/api/v1/today/news", params={"scope": scope}).json()
        assert body["status"] == "ok", scope
        assert [i["item"]["status"] for i in body["data"]["items"]] == ["PROBABLE", "RUMOR"], (
            f"{scope}: the probable, then one rumour of the two")
        assert body["data"]["suggested"] is True, scope
    assert client(db, monkeypatch).get("/api/v1/today/news", params={"scope": "other"}).status_code == 422


INTELLIGENCE = ("picks", "intel", "models", "ai", "market", "core", "raw")
CHANGES_SQL = """
SELECT schemaname || '.' || relname AS t, n_tup_ins + n_tup_upd + n_tup_del AS n
  FROM pg_stat_xact_user_tables WHERE schemaname = ANY(%(s)s)
"""


def changes(db: psycopg.Connection[Any]) -> dict[str, int]:
    return {str(r[0]): int(r[1]) for r in db.execute(CHANGES_SQL, {"s": list(INTELLIGENCE)}).fetchall()}


def test_the_news_are_read_and_nothing_of_predigol_intelligence_changes(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan UX, A10: the news consume what PrediGol Intelligence verified; not an item, a status or a row of its data changes
    while they answer (the status of every item stays the one the server decided)."""
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    match = fixture(db, seed, NOW + timedelta(hours=4))
    evidence(db, match, seed.home_team_id, status="PROBABLE", player="Casemiro",
             claim="Según Sport, Casemiro es baja por lesión para este partido.")
    before = changes(db)
    assert before.get("ai.evidence", 0) >= 1, "the transaction's own writes are counted"
    api = client(db, monkeypatch)
    for path in (f"/api/v1/matches/{match}/news", "/api/v1/today/news"):
        assert api.get(path).status_code == 200, path
    after = changes(db)
    altered = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
    assert altered == {}, f"the news wrote to {altered}"

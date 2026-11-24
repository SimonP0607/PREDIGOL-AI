"""C-06 «Noticia» (IA-121, AD-G07) and the front page's order (IA-120, AD-G06) served from the news store against PostgreSQL: the
fictitious story of the store's own test (an official call-up told by the club, a radio pending its rights and an outlet that reserves
its text from AI; two players and a team named).

* one story: the club's article lets PrediGol show its own text; the other two only their link; the author never; who it names comes
  from ``news.item_entities`` (the homonym taken back is not there); taking the club's rights back hides the own text at once;
* the front page: the story leads (official), enters «Última hora» (structured dates) and «Tus equipos» of a reader who follows the club;
* the search finds it by PostgreSQL's full text without accents or case (``Ejémplo NORTE``), by its category and by a player; a filter
  that does not hold empties the results with ``sin_resultados``;
* the stories of a match: of its team, after the previous match only;
* a withdrawn story is ``retirado_por_derechos`` in both projections, out of every public list and in the owner's queue;
* the public route, through the app with both switches on and the policy as the database has it today: no source of the example
  is signed there, so nothing of it is shown (``pendiente_derechos``) - the state of production, with 0 signed sources.

Every test runs in one transaction rolled back at the end."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.ai import source_policy
from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.stories import News, StoryDetail
from fbi.api.services import news_v2
from fbi.newsdesk import reads
from fbi.newsroom import moderation
from tests.unit.news_world import AT, policy

from .test_news_store_db import OFICIAL, RADIO, RESERVADO, build_story

pytestmark = pytest.mark.integration
NOW = AT + timedelta(hours=3)
NORTE = 770001


@pytest.fixture
def conn(migrated_database: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as c:
        c.execute("SELECT 1")
        yield c
        c.rollback()


def publish_with(p: source_policy.SourcePolicy) -> news_v2.Publish:
    def publish(item: reads.Item) -> str:
        return reads.stricter(item.publish_level, source_policy.can_publish(p.standing(item.canonical_url)).level)

    return publish


SIGNED = publish_with(policy())


def test_one_story_is_served_from_the_store_with_what_each_source_allows(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    private = news_v2.build_story(conn, key, at=NOW, publish=SIGNED)
    public = to_public(private, News)
    assert isinstance(public.story, StoryDetail) and public.view == "noticia"
    s = public.story
    assert (s.id, s.category, s.level) == (key, "selecciones", "oficial")
    assert s.headline_es == "Club Ejemplo Norte cita a sus dos atacantes titulares" and s.essentials_es == s.summary_es
    assert [x.url for x in s.sources] == [RESERVADO, RADIO, OFICIAL], "newest first; one per article (its newest version)"
    assert all(x.author == Missing(missing_reason="pendiente_derechos") for x in s.sources), "the radio's author is not served"
    assert [(e.type, e.id, e.role) for e in s.entities] == [("team", NORTE, "protagonista"), ("player", 880009, "protagonista"),
                                                           ("player", 880010, "protagonista")], "the homonym taken back is not there"
    assert [t.source for t in s.timeline] == ["Club Ejemplo Norte (oficial)", "Radio Ejemplo", "Diario Reservado Ejemplo"]
    assert s.match_impact == Missing(missing_reason="sin_datos") and s.related.missing_reason == "sin_resultados"
    assert private.story_status == "activa"
    assert not isinstance(private.story, Missing) and private.story is not None
    assert [x.publish_level for x in private.story.sources] == ["link", "link", "summary"]

    unsigned = news_v2.build_story(conn, key, at=NOW, publish=publish_with(policy(signed=())))
    gone = to_public(unsigned, News).story
    assert isinstance(gone, StoryDetail) and gone.headline_es == Missing(missing_reason="pendiente_derechos")
    assert not isinstance(unsigned.story, Missing) and unsigned.story is not None
    assert unsigned.story.own_text.headline_es == s.headline_es, "the owner still sees the text he must moderate"

    # C-06 1.1: no English text stored yet -> sin_datos; once the writer stores it, it is served under the same rights
    assert s.headline_en == Missing(missing_reason="sin_datos") and s.essentials_en == Missing(missing_reason="sin_datos")
    from fbi.news import store

    store.revise_story(conn, key, at=NOW - timedelta(minutes=1), written_by="writer-v1", text_version="writer-v1",
                       headline_es=s.headline_es, summary_es=s.summary_es,
                       headline_en="Club Ejemplo Norte calls up its two first-choice forwards",
                       summary_en="The official squad includes J. Ejemplo and A. Ejemplo. The club reported no new absences.")
    english = to_public(news_v2.build_story(conn, key, at=NOW, publish=SIGNED), News).story
    assert isinstance(english, StoryDetail)
    assert english.headline_en == "Club Ejemplo Norte calls up its two first-choice forwards"
    assert english.essentials_en == english.summary_en and english.essentials_es == s.essentials_es
    hidden = to_public(news_v2.build_story(conn, key, at=NOW, publish=publish_with(policy(signed=()))), News).story
    assert isinstance(hidden, StoryDetail) and hidden.headline_en == Missing(missing_reason="pendiente_derechos")


def test_the_front_page_search_and_match_read_the_store(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    reader = news_v2.Followed(frozenset({NORTE}), frozenset())
    front = to_public(news_v2.build_front(conn, at=NOW, followed=reader, publish=SIGNED), News).front
    assert front is not None and not isinstance(front.lead_story, Missing) and front.lead_story.id == key
    assert [c.id for c in front.breaking.items] == [key] and [c.id for c in front.mine.items] == [key]
    assert front.featured.missing_reason == "sin_datos", "the only story leads: it is not repeated"
    nobody = to_public(news_v2.build_front(conn, at=NOW, followed=None, publish=SIGNED), News).front
    assert nobody is not None and nobody.mine.missing_reason == "sin_favoritos"

    def found(**kw: Any) -> list[str]:
        answer = to_public(news_v2.build_search(conn, news_v2.Filters(**kw), at=NOW, followed=reader, publish=SIGNED), News)
        assert answer.search is not None
        return [h.story_id for h in answer.search.results.items]

    assert found(q="Ejémplo NORTE") == [key], "full text without accents or case"
    assert found(q="convocatoria oficial", category="selecciones") == [key]
    assert found(player=880010) == [key] and found(team=NORTE, mine=True) == [key]
    assert found(q="Ejemplo Norte", level="rumor") == [] and found(q="inexistente") == []
    empty = to_public(news_v2.build_search(conn, news_v2.Filters(q="inexistente"), at=NOW, followed=None, publish=SIGNED), News)
    assert empty.search is not None and empty.search.results.missing_reason == "sin_resultados" and empty.search.total == 0

    team = conn.execute("INSERT INTO core.teams (id, provider_team_id, name) VALUES (%s, 770001, 'Club Ejemplo Norte') RETURNING id",
                        (NORTE,)).fetchone()
    # explicit ids everywhere: no sequence of the shared test database moves (other files' worlds read the ids they are given)
    other = conn.execute("INSERT INTO core.teams (id, provider_team_id, name) VALUES (770002, 770002, 'Club Ejemplo Sur') RETURNING id"
                         ).fetchone()
    comp = conn.execute("INSERT INTO core.competitions (id, provider_league_id, name, type, entity_scope, competition_type) "
                        "VALUES (7700, 7700, 'Liga Ejemplo', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
    assert team and other and comp
    season = conn.execute("INSERT INTO core.competition_seasons (id, competition_id, season) VALUES (7700, %s, 2026) RETURNING id",
                          (comp[0],)).fetchone()
    assert season
    ids = iter(range(97_700_001, 97_700_010))

    def fixture(at: datetime) -> int:
        fid = next(ids)
        row = conn.execute("INSERT INTO core.fixtures (id, provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                           "kickoff_at, status_group) VALUES (%s, %s, %s, %s, %s, %s, 'scheduled') RETURNING id",
                           (fid, fid, season[0], NORTE, other[0], at)).fetchone()
        assert row
        return int(row[0])

    fixture(AT - timedelta(days=5))
    upcoming = fixture(NOW + timedelta(hours=20))
    match = to_public(news_v2.build_match(conn, upcoming, at=NOW, publish=SIGNED), News).match
    assert match is not None and [c.id for c in match.stories.items] == [key] and match.window_from == AT - timedelta(days=5)
    # C-06 1.1 (AP-P11): never searched -> sin_datos and 0 pages, not «buscamos y no hubo nada»
    assert (match.searched_at, match.sources_checked) == (Missing(missing_reason="sin_datos"), 0)
    named = to_public(news_v2.build_story(conn, key, at=NOW, publish=SIGNED), News).story
    assert isinstance(named, StoryDetail) and named.entities[0].name == "Club Ejemplo Norte", "PrediGol's own name of the team"
    late = fixture(NOW + timedelta(days=30))
    later = to_public(news_v2.build_match(conn, late, at=NOW, publish=SIGNED), News).match
    assert later is not None and later.stories.missing_reason == "sin_resultados", "a club's news is not hung from its next match too"


def test_a_withdrawn_story_carries_nothing_and_waits_in_the_owner_s_queue(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    moderation.withdraw(conn, key, at=NOW - timedelta(minutes=5), reason="petición del medio", requested_by="medio")
    private = news_v2.build_story(conn, key, at=NOW, publish=SIGNED)
    assert private.story == Missing(missing_reason="retirado_por_derechos") and private.story_status == "retirada"
    assert to_public(private, News).story == Missing(missing_reason="retirado_por_derechos")
    front = news_v2.build_front(conn, at=NOW, followed=None, publish=SIGNED)
    assert front.front is not None and [c.id for c in front.front.queue.items] == [key]
    public = to_public(front, News).front
    assert public is not None and public.lead_story == Missing(missing_reason="sin_datos") and public.breaking.items == []


@pytest.fixture
def client(conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import fbi.api.switches as switches
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import Permission, Role
    from fbi.auth.service import Principal

    monkeypatch.setattr(switches, "environment", lambda: {"FBI_NEWS_FEED": "1", "FBI_NEWS_V2": "1"})
    reader = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role.USER, language="es",
                       timezone="America/Bogota", session_id="s", session_expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                       permissions=frozenset({Permission.APP}))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: reader
    app.dependency_overrides[get_db] = lambda: conn
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_the_public_route_shows_nothing_of_a_source_nobody_signed(conn: psycopg.Connection[Any], client: TestClient) -> None:
    key = build_story(conn)
    source_policy.reset_cache()
    answer = client.get(f"/api/v1/news/{key}")
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert (data["contract"], data["projection"], data["view"]) == ("C-06", "public", "noticia")
    assert data["story"] == {"missing_reason": "pendiente_derechos"}, "the example's outlets are not in the directory: nothing is shown"
    front = client.get("/api/v1/news/v2").json()["data"]
    assert front["front"]["lead_story"] == {"missing_reason": "sin_datos"} and front["front"]["featured"]["items"] == []
    assert client.get("/api/v1/news/st-no-existe-0000").status_code == 404

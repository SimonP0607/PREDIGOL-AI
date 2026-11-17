"""The news over HTTP (plan UX, A10). Reading only.

* ``GET /matches/{fixture_id}/news`` (product) - the match's news as PrediGol Intelligence found and verified them: per card
  PrediGol's own summary, the sources with their standing, the time, the relevance for the match, the status the server decided
  and the link to the original; confirmed first, rumours and the outdated last; a contradiction as one card with both sources.
  ``empty`` when there is none (the web says «No encontramos noticias verificadas relevantes para este partido.»).
* ``GET /today/news`` (product) - Home's «Noticias» as a summary (plan de Inicio, 3.3): the best few confirmed or probable news
  not yet over - and, with room left, one rumour - of the reader's own leagues and teams (two at most; the suggested ones,
  three, while they chose none) or, with ``scope=general``, of the suggested matches whatever they follow (three at most, the
  same for everyone). «Confirmed» needs an official source or two distinct outlets. Kept two minutes per set of favourites.

Both answer ``not_available`` while the owner keeps them off (``FBI_NEWS_USERS=0``). No route here searches the web, calls an
AI, sends an article's text or changes an item.

Contract C-06 (AD-G07, IA-121; the front page's order AD-G06, IA-120) is served beside them, on routes of its own - the three above keep
their shape and keep reading ``ai.evidence``. Public, 404 unless ``FBI_NEWS_FEED`` and ``FBI_NEWS_V2`` are both on:

* ``GET /news/v2`` - the front page (``view: portada``), or the search with ``q`` or any filter (``view: busqueda``);
* ``GET /news/{item_id}`` - one story by its key (``view: noticia``);
* ``GET /matches/{fixture_id}/news/v2`` - the stories of a match (``view: partido``).

Contract C-07 (AD-G08, IA-122): ``GET /matches/{fixture_id}/sources`` - the facts the match's analysis used, 404 while
``FBI_MATCH_INTELLIGENCE`` is off or the analysis is not published. The private projections of both (SUPER_ADMIN only, no switch) are
``GET /admin/intelligence/news``, ``/admin/intelligence/news/{item_id}``, ``/admin/intelligence/matches/{fixture_id}/news`` and
``/admin/intelligence/matches/{fixture_id}/sources``. All of them read only.

* ``GET /admin/matches/{fixture_id}/news/diagnostics`` (SUPER_ADMIN only, IA-019) - why a match has news or not: its competition's
  priority group and the guaranteed coverage, the market and the AI's day, the passes and the next one, the searches paid, Exa's
  envelope of the month, the web items by status and one verdict. Reading only, like the rest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Query

from fbi.api.contracts.intelligence.sources import AnalysisSources, AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.stories import STORY_KEY, Category, News, NewsPrivate, SortOrder
from fbi.api.contracts.intelligence.vocab import ConfirmationLevel
from fbi.api.contracts.news import (
    FeedStatus,
    MatchNews,
    NewsDiagnosis,
    NewsFeed,
    NewsKind,
    TodayNews,
)
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.problem import ApiError
from fbi.api.routers.today import follows_of, general_follows
from fbi.api.security import Admin, App
from fbi.api.services import analysis_sources, news, news_diagnosis, news_v2
from fbi.api.switches import news_feed_on

router = APIRouter(tags=["news"])
admin_router = APIRouter(tags=["admin: news"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]
StoryKey = Annotated[str, Path(pattern=STORY_KEY, description="A story's key (st-...).")]
EntityId = Annotated[int | None, Query(ge=1, le=2**62)]


def _filters(q: str | None, country: str | None, competition: int | None, team: int | None, player: int | None,
             since: datetime | None, until: datetime | None, category: Category | None, level: ConfirmationLevel | None, mine: bool,
             sort: SortOrder, limit: int, offset: int) -> news_v2.Filters:
    return news_v2.Filters(q=(q or "").strip() or None, country=(country or "").strip() or None, competition=competition, team=team,
                           player=player, since=since, until=until, category=category, level=level, mine=mine, sort=sort,
                           limit=limit, offset=offset)


Q = Annotated[str | None, Query(max_length=120, description="Full text over PrediGol's own words and the names the stories name.")]
Country = Annotated[str | None, Query(max_length=60)]
Since = Annotated[datetime | None, Query(alias="from", description="From this moment (UTC).")]
Until = Annotated[datetime | None, Query(alias="to", description="Up to this moment (UTC).")]
Mine = Annotated[bool, Query(description="Only the stories of the reader's favourite teams and players.")]
Page = Annotated[int, Query(ge=1, le=news_v2.MAX_PAGE)]
Offset = Annotated[int, Query(ge=0, le=5000)]


@router.get("/matches/{fixture_id}/news", response_model=Envelope[MatchNews | None])
def get_match_news(conn: Db, _: App, fixture_id: FixtureId) -> Envelope[MatchNews | None]:
    """NOTICIAS: what the sources say about the match outside the numbers - absences, doubts, returns, line-ups, the coach -
    each card with PrediGol's own summary (never the article), its sources and their standing, when it was published, how
    relevant it is for the match and its status: confirmed, probable, contradictory, rumour or outdated."""
    return news.match_news(conn, fixture_id)


@router.get("/today/news", response_model=Envelope[TodayNews | None])
def get_today_news(
    conn: Db, principal: App, scope: Annotated[Literal["mine", "general"], Query()] = "mine"
) -> Envelope[TodayNews | None]:
    """Home's NOTICIAS as a summary: confirmed - with an official source or two distinct outlets - or probable news, and at
    most one labelled rumour, of the matches not over from three hours ago to 36 hours ahead. ``scope=mine`` (default): the
    reader's leagues and teams, two at most, each match saying why it is theirs (the suggested ones, three, while they chose
    none or FBI_PERSONALIZATION=0). ``scope=general``: the suggested matches, three at most, the same for everyone."""
    follows = general_follows(conn) if scope == "general" else follows_of(conn, principal.user_id)
    return news.news_for(conn, follows)


@router.get("/news", response_model=Envelope[NewsFeed | None])
def get_news_feed(
    conn: Db, principal: App,
    mine: Annotated[bool, Query(description="Only the reader's leagues and teams (the suggested ones while they chose none).")] = False,
    status: Annotated[FeedStatus | None, Query(description="One status: CONFIRMED, PROBABLE, CONTRADICTORY or RUMOR.")] = None,
    kind: Annotated[NewsKind | None, Query(description="One kind of news.")] = None,
    team: Annotated[int | None, Query(ge=1, le=2**62, description="A team id: the items of its matches.")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> Envelope[NewsFeed | None]:
    """NOTICIAS as a section (plan maestro UX/UI 2026, decision 2): the items the matches' news already show, of the matches
    not yet over (three hours ago to 72 hours ahead), newest first, paged, with their sources and their status - a single
    outlet's «confirmed» reads as probable, an outdated item is never listed. Read only. Behind ``FBI_NEWS_FEED`` (404 while
    it is off); ``not_available`` while the owner keeps the news from readers."""
    if not news_feed_on():
        raise ApiError(404, "not_found", "not found")
    return news.feed(conn, follows_of(conn, principal.user_id), mine=mine, status=status, kind=kind, team=team,
                     limit=limit, offset=offset)


@router.get("/news/v2", response_model=Envelope[News | None])
def get_news_v2(conn: Db, principal: App, q: Q = None, country: Country = None, competition: EntityId = None, team: EntityId = None,
                player: EntityId = None, since: Since = None, until: Until = None, category: Category | None = None,
                level: ConfirmationLevel | None = None, mine: Mine = False, sort: SortOrder = "reciente", limit: Page = 20,
                offset: Offset = 0) -> Envelope[News | None]:
    """NOTICIAS v2 (C-06): the front page - the lead (oficial, dos orígenes or a statement; never a single outlet or a rumour), «Última
    hora» (only stories with a structured publication date), «Tus equipos» (the reader's favourites; ``sin_favoritos`` without them) and
    the featured stories by level and the nearness of a match (``front-v1``) - or, with ``q`` or any filter, the search with its facets.
    PrediGol's own words only; no article's text, title, author or picture. 404 unless FBI_NEWS_FEED and FBI_NEWS_V2 are on."""
    f = _filters(q, country, competition, team, player, since, until, category, level, mine, sort, limit, offset)
    if f.any():
        return news_v2.search(conn, f, user_id=principal.user_id, public=True)
    return news_v2.front(conn, user_id=principal.user_id, public=True)


@router.get("/news/{item_id}", response_model=Envelope[News | None])
def get_news_story(conn: Db, _: App, item_id: StoryKey) -> Envelope[News | None]:
    """One story (C-06, ``noticia``): PrediGol's headline and essentials (only while a source allows a summary), the level and why,
    every source with its time and link, who it names, «Cómo se fue sabiendo», the related stories and how it bears on a published
    analysis. A story withdrawn at a request is ``retirado_por_derechos`` and nothing of it travels. 404 when there is none."""
    return news_v2.story(conn, item_id, public=True)


@router.get("/matches/{fixture_id}/news/v2", response_model=Envelope[News | None])
def get_match_news_v2(conn: Db, _: App, fixture_id: FixtureId) -> Envelope[News | None]:
    """The stories of a match (C-06, ``partido``): naming the match, or one of its teams after the previous match of either - a club's
    news is not hung from all its matches."""
    return news_v2.match(conn, fixture_id, public=True)


@router.get("/matches/{fixture_id}/sources", response_model=Envelope[AnalysisSources])
def get_match_sources(conn: Db, _: App, fixture_id: FixtureId) -> Envelope[AnalysisSources]:
    """FUENTES DEL ANÁLISIS (C-07): the facts the published analysis of the match used - level, relation (a favor, en contra,
    contexto, no usada), when PrediGol knew each one (always before the evaluation) and its source. 404 while FBI_MATCH_INTELLIGENCE
    is off or the analysis is not published."""
    return analysis_sources.public(conn, fixture_id)


@admin_router.get("/intelligence/news", response_model=Envelope[NewsPrivate])
def get_news_private(conn: Db, principal: Admin, q: Q = None, country: Country = None, competition: EntityId = None,
                     team: EntityId = None, player: EntityId = None, since: Since = None, until: Until = None,
                     category: Category | None = None, level: ConfirmationLevel | None = None, mine: Mine = False,
                     sort: SortOrder = "reciente", limit: Page = 20, offset: Offset = 0) -> Envelope[NewsPrivate]:
    """C-06, private projection of the front page or the search: what the reader would get, the moderation state of every story, the
    queue of the window, the withheld sources and PrediGol's own text whatever the rights. No switch."""
    f = _filters(q, country, competition, team, player, since, until, category, level, mine, sort, limit, offset)
    if f.any():
        return news_v2.search(conn, f, user_id=principal.user_id, public=False)
    return news_v2.front(conn, user_id=principal.user_id, public=False)


@admin_router.get("/intelligence/news/{item_id}", response_model=Envelope[NewsPrivate])
def get_news_story_private(conn: Db, item_id: StoryKey) -> Envelope[NewsPrivate]:
    """C-06, private projection of one story: also every evaluation that used it (AD-G08). A story in moderation or withdrawn is
    opened in the moderation console (``/admin/news/stories/{story_key}``)."""
    return news_v2.story(conn, item_id, public=False)


@admin_router.get("/intelligence/matches/{fixture_id}/news", response_model=Envelope[NewsPrivate])
def get_match_news_private(conn: Db, fixture_id: FixtureId) -> Envelope[NewsPrivate]:
    """C-06, private projection of a match's stories, with the evaluations of the match that used them."""
    return news_v2.match(conn, fixture_id, public=False)


@admin_router.get("/intelligence/matches/{fixture_id}/sources", response_model=Envelope[AnalysisSourcesPrivate])
def get_match_sources_private(conn: Db, fixture_id: FixtureId) -> Envelope[AnalysisSourcesPrivate]:
    """C-07, private projection: the newest evaluation's facts with their effect on each selection, the facts the validator refused and
    why, and every evaluation's counts. No switch."""
    return analysis_sources.private(conn, fixture_id)


@admin_router.get("/matches/{fixture_id}/news/diagnostics", response_model=Envelope[NewsDiagnosis])
def get_news_diagnosis(conn: Db, fixture_id: FixtureId) -> Envelope[NewsDiagnosis]:
    """Why a match has news or not (IA-019), for the owner's «Avanzado / Auditoría»: the competition's priority group and whether the
    guaranteed coverage takes it, whether it has a market and its AI day (America/Bogota, from 00:05) has opened, its passes with their
    web counts and the pass it waits for, the searches paid for it, Exa's envelope of the month, the web items kept by status and one
    verdict - the first reason that applies. Reading only: nothing is searched, paid or written."""
    return news_diagnosis.diagnosis(conn, fixture_id)

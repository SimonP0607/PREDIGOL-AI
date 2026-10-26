"""The news over HTTP (plan UX, A10). Reading only.

* ``GET /matches/{fixture_id}/news`` (product) - the match's news as PrediGol Intelligence found and verified them: per card
  PrediGol's own summary, the sources with their standing, the time, the relevance for the match, the status the server decided
  and the link to the original; confirmed first, rumours and the outdated last; a contradiction as one card with both sources.
  ``empty`` when there is none (the web says «No encontramos noticias verificadas relevantes para este partido.»).
* ``GET /today/news`` (product) - Home's «Noticias»: the newest confirmed or probable news of the reader's matches not yet
  over - their leagues and teams (B2), the suggested ones while they chose none - each saying why it is theirs. Kept two
  minutes per set of favourites; the items are the same for every reader who sees them.

Both answer ``not_available`` while the owner keeps them off (``FBI_NEWS_USERS=0``). No route here searches the web, calls an
AI, sends an article's text or changes an item.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path

from fbi.api.contracts.news import MatchNews, TodayNews
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope
from fbi.api.routers.today import follows_of
from fbi.api.security import App
from fbi.api.services import news

router = APIRouter(tags=["news"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
FixtureId = Annotated[int, Path(ge=1, le=2**62)]


@router.get("/matches/{fixture_id}/news", response_model=Envelope[MatchNews | None])
def get_match_news(conn: Db, _: App, fixture_id: FixtureId) -> Envelope[MatchNews | None]:
    """NOTICIAS: what the sources say about the match outside the numbers - absences, doubts, returns, line-ups, the coach -
    each card with PrediGol's own summary (never the article), its sources and their standing, when it was published, how
    relevant it is for the match and its status: confirmed, probable, contradictory, rumour or outdated."""
    return news.match_news(conn, fixture_id)


@router.get("/today/news", response_model=Envelope[TodayNews | None])
def get_today_news(conn: Db, principal: App) -> Envelope[TodayNews | None]:
    """Home's NOTICIAS: the confirmed or probable news of the reader's matches - their leagues and teams (B2), the suggested
    ones while they chose none or FBI_PERSONALIZATION=0 - from three hours ago to 36 hours ahead that are not over, kick-off
    order, at most three per match, each match saying why it is theirs."""
    return news.news_for(conn, follows_of(conn, principal.user_id))

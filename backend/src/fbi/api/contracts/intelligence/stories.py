"""C-06, the news (AD-G07, IA-121; the front page's order AD-G06, IA-120): the stories of ``news.stories`` with their articles
(``news.items``) and who they name (``news.item_entities``), in four views - one body each, as ``view`` says:

* ``portada`` - the front page (maqueta 08): the lead, «Última hora», «Tus equipos», the featured stories (``front-v1``) and the count
  of each category;
* ``noticia`` - one story (maqueta 09): PrediGol's own headline and essentials, the level and why, every source with its time and link,
  who it names (role, method, confidence), how it bears on a match, «Cómo se fue sabiendo» and the related stories; a story withdrawn
  at a request is ``retirado_por_derechos`` and nothing of it travels (one in the moderation queue, ``pendiente_derechos``);
* ``busqueda`` - search and filters (maqueta 10): PostgreSQL's full text over PrediGol's own words and the names of what the stories
  name, by country, competition, team, player, dates, category and level, with the facets counted before the filters;
* ``partido`` - the stories of a match (maqueta 15): of the match or its two teams, inside its window.

Routes (additive: ``GET /news``, ``/today/news`` and ``/matches/{id}/news`` of BE-040 keep their shape and what they read):

* public, 404 unless ``FBI_NEWS_FEED`` and ``FBI_NEWS_V2`` are both on - ``GET /api/v1/news/v2`` (portada; ``busqueda`` with ``q`` or
  a filter), ``GET /api/v1/news/{item_id}`` (``item_id`` is the story's key), ``GET /api/v1/matches/{fixture_id}/news/v2``;
* private (``require_admin``, no switch) - the same under ``/api/v1/admin/intelligence/news…``.

What NEVER travels in the public projection: an article's text, title or picture (none is stored; the image is a monogram), its author
(``pendiente_derechos`` until the lawyer answers), a source that may publish nothing, PrediGol's own text of a story none of whose
sources allows a summary (``pendiente_derechos``), a story in moderation or withdrawn, and any link to a selection. Of an absence, only its
state: nothing medical. The private projection adds the moderation state, the withheld sources, the own text whatever the rights, the
author as seen and the links of the evaluations that used the story (AD-G08).
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.vocab import (
    ConfirmationLevel,
    EvaluationStep,
    FactRelation,
    StoryWarning,
)

STORY_KEY: Final = r"^st-[a-z0-9][a-z0-9-]{3,62}$"
NewsView = Literal["portada", "noticia", "busqueda", "partido"]
Category = Literal["fichajes", "bajas_y_sanciones", "declaraciones", "resultados_y_proximos", "selecciones", "colombia",
                   "internacional", "competiciones"]
"""The front page's categories (AD-G03, ``fbi.news.vocab.CATEGORIES``; a test holds the two equal)."""
EntityType = Literal["team", "player", "coach", "referee", "competition", "fixture", "venue"]
Role = Literal["protagonista", "mencionado"]
LinkMethod = Literal["plantilla", "alias", "proveedor", "manual"]
StoryStatus = Literal["activa", "en_moderacion", "retirada"]
PublishLevel = Literal["summary", "link", "none"]
FilterName = Literal["country", "competition", "team", "player", "from", "to", "category", "level", "mine"]
SortOrder = Literal["reciente", "relevante"]

RIGHTS_NOTICE_ES: Final = "Resumen elaborado por PrediGol; el artículo completo está en la fuente."
LEVEL_EXPLANATION_ES: Final[dict[str, str]] = {
    "oficial": "Lo comunicó una fuente oficial (club, liga o federación).",
    "dos_origenes": "Lo cuentan dos fuentes independientes entre sí.",
    "declaracion": "Es una declaración atribuida a su autor.",
    "un_medio": "Lo cuenta un solo medio; nadie más lo confirma todavía.",
    "rumor": "Es un rumor: ninguna fuente lo confirma.",
}
NO_LEVEL_ES: Final = "Sin nivel todavía: la historia no se ha clasificado."


class Image(IntelligenceModel):
    """Never a third party's picture: a monogram or a graphic of PrediGol's own."""

    kind: Literal["monograma", "grafico_propio"] = "monograma"


class StorySource(IntelligenceModel):
    """An article of the story: its outlet, its dates and its link. Its author waits for the lawyer (``pendiente_derechos``)."""

    name: str = Field(min_length=1)
    author: Missing
    published_at: UtcDatetime | Missing
    published_day_only: bool
    known_at: UtcDatetime = Field(description="When PrediGol first saw it.")
    url: str


class StorySourcePrivate(StorySource):
    publish_level: PublishLevel = private(description="What of it may be shown now: the stricter of the copy and the policy in force.")
    source_state: str = private(pattern=CODE_PATTERN, description="Its state in the directory when it was seen.")
    author_seen: str | Missing = private(description="The author the article gave (private metadata until the lawyer answers).")
    item_id: int = private(ge=1, description="The row of news.items.")


class EntityLink(IntelligenceModel):
    type: EntityType
    id: int = Field(ge=1)
    name: str | Missing
    role: Role
    method: LinkMethod
    confidence: float = Field(ge=0, le=1)


class OwnText(IntelligenceModel):
    headline_es: str | Missing
    summary_es: str | Missing
    text_version: str | Missing


class StoryCard(IntelligenceModel):
    """A story as a list shows it."""

    id: str = Field(pattern=STORY_KEY, description="The story's key: what GET /news/{item_id} takes.")
    headline_es: str | Missing = Field(description="PrediGol's own headline (AD-G04), only while a source allows a summary.")
    summary_es: str | Missing
    category: Category | Missing
    level: ConfirmationLevel | Missing
    warnings: list[StoryWarning]
    sources_count: int = Field(ge=1)
    latest_at: UtcDatetime
    sources: list[StorySource] = Field(description="Newest first.")
    entities: list[EntityLink] = Field(description="One per entity: protagonista first, then the most confident.")
    image: Image


class StoryCardPrivate(StoryCard):
    sources: list[StorySourcePrivate]  # type: ignore[assignment]  # the private variant of each source
    sources_count: int = Field(ge=0, description="The articles a reader may see: 0 for a story of the private queue none of whose sources "
                                                 "may be shown yet (the public card always has at least one).")
    status: StoryStatus = private(description="activa, en_moderacion (the private queue) or retirada (at a request).")
    status_reason: str | Missing = private(description="Why it is in moderation or withdrawn.")
    story_version: int = private(ge=1, description="The version of the story shown.")
    claim_type: str | Missing = private(description="The directory's type of claim of the story.")
    lang: str | Missing = private(description="Its language (AD-G03).")
    country: str | Missing = private(description="Its country (AD-G03).")
    own_text: OwnText = private(description="PrediGol's own text whatever the rights of its sources (the owner moderates it).")
    withheld_sources: list[StorySourcePrivate] = private(description="Articles whose source may publish nothing now.")

    def shown_in_public(self) -> bool:
        return self.status == "activa"


class CategoryCount(IntelligenceModel):
    category: Category
    n: int = Field(ge=0)


class Front(IntelligenceModel):
    """The front page (``front-v1``): each block empty with its reason, never filled with something else."""

    lead_story: StoryCard | Missing
    breaking: ItemList[StoryCard] = Field(description="«Última hora»: only stories with a structured publication date.")
    mine: ItemList[StoryCard] = Field(description="«Tus equipos»: sin_favoritos when the reader follows nothing.")
    featured: ItemList[StoryCard]
    counts: list[CategoryCount] = Field(description="Stories per category in the window, before any filter.")
    window_hours: int = Field(ge=1)
    order_version: str = Field(pattern=r"^front-v\d+$")


class FrontPrivate(Front):
    lead_story: StoryCardPrivate | Missing
    breaking: ItemList[StoryCardPrivate]  # type: ignore[assignment]
    mine: ItemList[StoryCardPrivate]  # type: ignore[assignment]
    featured: ItemList[StoryCardPrivate]  # type: ignore[assignment]
    queue: ItemList[StoryCardPrivate] = private(description="The stories of the window in moderation or withdrawn.")


class MatchImpact(IntelligenceModel):
    """«Cómo afecta al partido»: a published analysis of an upcoming match used a fact of this story (C-07)."""

    fixture_id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    aspect_es: str = Field(min_length=1)
    analysis_published: bool


class TimelineEntry(IntelligenceModel):
    """«Cómo se fue sabiendo»: each article as PrediGol saw it, with the story's level at that moment."""

    known_at: UtcDatetime
    level: ConfirmationLevel | Missing
    source: str = Field(min_length=1)


class RelatedStory(IntelligenceModel):
    id: str = Field(pattern=STORY_KEY)
    headline_es: str | Missing
    level: ConfirmationLevel | Missing


class AnalysisLink(IntelligenceModel):
    """An evaluation of a match that looked at a fact read from an article of this story (``intel.eval_sources``)."""

    fixture_id: int = Field(ge=1)
    evaluation: EvaluationStep
    evaluation_version: int = Field(ge=1)
    known_at: UtcDatetime
    relation: FactRelation


class StoryDetail(StoryCard):
    essentials_es: str | Missing = Field(description="Two or three sentences of PrediGol's own (AD-G04).")
    level_explanation_es: str
    match_impact: MatchImpact | Missing
    timeline: list[TimelineEntry]
    related: ItemList[RelatedStory]
    rights_notice_es: str = RIGHTS_NOTICE_ES


class StoryDetailPrivate(StoryDetail, StoryCardPrivate):
    analyses: ItemList[AnalysisLink] = private(description="Every evaluation that used it, published or not (AD-G08).")


class FilterApplied(IntelligenceModel):
    name: FilterName
    value: str = Field(min_length=1)


class FacetCount(IntelligenceModel):
    code: str = Field(pattern=CODE_PATTERN)
    n: int = Field(ge=0)


class Facets(IntelligenceModel):
    category: list[FacetCount]
    level: list[FacetCount]


class SearchHit(IntelligenceModel):
    story_id: str = Field(pattern=STORY_KEY)
    headline_es: str | Missing
    level: ConfirmationLevel | Missing
    category: Category | Missing
    sources_count: int = Field(ge=1)
    latest_at: UtcDatetime


class Search(IntelligenceModel):
    query: str
    normalized: str
    sort: SortOrder
    filters_applied: list[FilterApplied]
    facets: Facets = Field(description="Counted over the stories the text matched, before the other filters.")
    results: ItemList[SearchHit]
    total: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=1, exclude_if=lambda v: v is None,
                                    description="The offset of the next page; left out on the last one.")


class MatchStories(IntelligenceModel):
    fixture_id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    window_from: UtcDatetime = Field(description="The previous match of either team (or 14 days before): older news is not this match's.")
    stories: ItemList[StoryCard]


class MatchStoriesPrivate(MatchStories):
    stories: ItemList[StoryCardPrivate]  # type: ignore[assignment]
    analyses: ItemList[AnalysisLink] = private(description="The evaluations of this match that used a fact of these stories.")


def _absent(value: object) -> bool:
    return value is None


class News(IntelligenceContract):
    """C-06, public projection: one of ``front``, ``story``, ``search`` or ``match``, as ``view`` says."""

    CONTRACT_ID: ClassVar[str] = "C-06"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    view: NewsView
    front: Front | None = Field(default=None, exclude_if=_absent)
    story: StoryDetail | Missing | None = Field(default=None, exclude_if=_absent,
                                                description="retirado_por_derechos (withdrawn) or pendiente_derechos (in moderation).")
    search: Search | None = Field(default=None, exclude_if=_absent)
    match: MatchStories | None = Field(default=None, exclude_if=_absent)

    @model_validator(mode="after")
    def _one_body(self) -> News:
        want = {"portada": "front", "noticia": "story", "busqueda": "search", "partido": "match"}[self.view]
        given = [k for k in ("front", "story", "search", "match") if getattr(self, k) is not None]
        if given != [want]:
            raise ValueError(f"a {self.view} answer carries {want} and nothing else")
        return self


class NewsPrivate(News):
    """C-06, private projection (``require_admin``)."""

    front: FrontPrivate | None = Field(default=None, exclude_if=_absent)
    story: StoryDetailPrivate | Missing | None = Field(default=None, exclude_if=_absent)
    match: MatchStoriesPrivate | None = Field(default=None, exclude_if=_absent)
    story_status: StoryStatus | Missing = private(
        description="The status of the story asked for (noticia), even when not shown: a story in moderation or withdrawn is not served "
                    "here in either projection - the owner opens it in the moderation console (GET /admin/news/stories/{story_key}).")

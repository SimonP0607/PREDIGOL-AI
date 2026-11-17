"""Contract C-06, the news (AD-G07, IA-121; the front page's order AD-G06, IA-120), built from the news store (``fbi.newsdesk``).

Read only: no search of the web, no model, no write, and nothing of ``ai.evidence`` - the routes of BE-040 (``fbi.api.services.news``)
keep reading it as before. What of an article may be shown is the stricter of the copy written when it was seen and the source policy in
force (``publisher``; without a policy, nothing). The private answer is built first; the public one is the server's projection of it
(``to_public``): a private field is never copied, a story in moderation is left out of every list.

* ``front`` - the front page: the window of ``front.WINDOW``, ordered by ``front-v1``, with «Tus equipos» from the reader's own favourites
  (``customer.favorites``, read only; without them ``sin_favoritos``, the suggested ones do not fill it).
* ``story`` - one story by its key; 404 when there is none; in moderation or withdrawn: nothing of it (both projections).
* ``search`` - full text and filters over the stories of the window (30 days unless ``from``/``to`` say otherwise).
* ``match`` - the stories of a match: naming the match, or one of its teams after the previous match of either.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, cast, get_args

from fbi.ai import source_policy
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.stories import (
    LEVEL_EXPLANATION_ES,
    NO_LEVEL_ES,
    AnalysisLink,
    Category,
    CategoryCount,
    EntityLink,
    EntityType,
    FacetCount,
    Facets,
    FilterApplied,
    FilterName,
    FrontPrivate,
    Image,
    LinkMethod,
    MatchImpact,
    MatchStoriesPrivate,
    News,
    NewsPrivate,
    OwnText,
    RelatedStory,
    Role,
    Search,
    SearchHit,
    SortOrder,
    StoryCardPrivate,
    StoryDetailPrivate,
    StorySourcePrivate,
    StoryStatus,
    TimelineEntry,
)
from fbi.api.contracts.intelligence.vocab import (
    ConfirmationLevel,
    EvaluationStep,
    FactRelation,
    StoryWarning,
)
from fbi.api.envelope import Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn
from fbi.api.services.analysis_sources import fact_es
from fbi.api.services.news import users_may_see
from fbi.api.switches import news_feed_on, news_v2_on
from fbi.core.clock import now
from fbi.customer.favorites import personalization_on
from fbi.factlinks import views as factlinks
from fbi.newsdesk import front as order
from fbi.newsdesk import reads
from fbi.newsdesk.reads import Bundle, Item

NO_DATA: Final = Missing(missing_reason="sin_datos")
NO_RIGHTS: Final = Missing(missing_reason="pendiente_derechos")
WITHDRAWN: Final = Missing(missing_reason="retirado_por_derechos")
NOT_YET: Final = Missing(missing_reason="no_entregado", expected_piece="AD-G07")
LEVELS: Final = get_args(ConfirmationLevel)
CATEGORIES: Final = get_args(Category)
SEARCH_WINDOW: Final = timedelta(days=30)
RELATED_WINDOW: Final = timedelta(days=7)
MATCH_WINDOW: Final = timedelta(days=14)
MAX_RELATED: Final = 5
MAX_MATCH: Final = 20
MAX_PAGE: Final = 50
FAVORITES_SQL: Final = "SELECT kind, ref_id FROM customer.favorites WHERE user_id = %s AND kind IN ('team', 'player')"
UPCOMING_SQL: Final = """
SELECT t.team_id, min(f.kickoff_at) AS kickoff_at
  FROM unnest(%(teams)s::bigint[]) AS t(team_id)
  JOIN core.fixtures f ON (f.home_team_id = t.team_id OR f.away_team_id = t.team_id) AND f.kickoff_at >= %(now)s AND f.kickoff_at <= %(until)s
 GROUP BY t.team_id
"""
MATCH_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id,
       (SELECT max(p.kickoff_at) FROM core.fixtures p
         WHERE p.id <> f.id AND p.kickoff_at < f.kickoff_at
           AND (p.home_team_id IN (f.home_team_id, f.away_team_id) OR p.away_team_id IN (f.home_team_id, f.away_team_id))) AS previous
  FROM core.fixtures f WHERE f.id = %(f)s
"""

Publish = Callable[[Item], str]


@dataclass(frozen=True)
class Followed:
    """The reader's favourite teams and players (``None``: they follow nothing, or personalisation is off)."""

    teams: frozenset[int]
    players: frozenset[int]


@dataclass(frozen=True)
class Filters:
    q: str | None = None
    country: str | None = None
    competition: int | None = None
    team: int | None = None
    player: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    category: Category | None = None
    level: ConfirmationLevel | None = None
    mine: bool = False
    sort: SortOrder = "reciente"
    offset: int = 0
    limit: int = 20

    def any(self) -> bool:
        return any(v is not None for v in (self.q, self.country, self.competition, self.team, self.player, self.since, self.until,
                                           self.category, self.level)) or self.mine

    def applied(self) -> list[FilterApplied]:
        pairs: list[tuple[FilterName, object]] = [
            ("country", self.country), ("competition", self.competition), ("team", self.team), ("player", self.player),
            ("from", None if self.since is None else self.since.isoformat()), ("to", None if self.until is None else self.until.isoformat()),
            ("category", self.category), ("level", self.level), ("mine", "true" if self.mine else None)]
        return [FilterApplied(name=n, value=str(v)) for n, v in pairs if v is not None]


# ── what may be shown ────────────────────────────────────────────────────────────────────────────────────────────────

def publisher(conn: Conn) -> Publish:
    """The stricter of an article's copy and the policy in force; without a policy (it could not be read), nothing is shown."""
    policy = source_policy.load(conn)

    def publish(item: Item) -> str:
        now_level = "none" if policy is None else source_policy.can_publish(policy.standing(item.canonical_url)).level
        return reads.stricter(item.publish_level, now_level)

    return publish


def followed_of(conn: Conn, user_id: int | None) -> Followed | None:
    if user_id is None or not personalization_on():
        return None
    rows = conn.execute(FAVORITES_SQL, (user_id,)).fetchall()
    teams = frozenset(int(r[1]) for r in rows if r[0] == "team")
    players = frozenset(int(r[1]) for r in rows if r[0] == "player")
    return Followed(teams, players) if teams or players else None


# ── one story ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _source(i: Item, level: str) -> StorySourcePrivate:
    return StorySourcePrivate(name=i.source_name, author=NO_RIGHTS, published_at=i.published_at or NO_DATA,
                              published_day_only=i.published_at is not None and i.published_day_only, known_at=i.seen_at,
                              url=i.canonical_url, publish_level=cast(Literal["summary", "link", "none"], level),
                              source_state=i.source_state, author_seen=i.author or NO_DATA, item_id=i.id)


def entities(b: Bundle) -> list[EntityLink]:
    """One per entity of the articles shown: protagonista over mencionado, then the most confident. Pure."""
    shown = {i.id for i in b.shown()}
    best: dict[tuple[str, int], reads.Entity] = {}
    for e in b.entities:
        if e.item_id not in shown:
            continue
        old = best.get((e.type, e.id))
        if old is None or (e.role == "protagonista", e.confidence) > (old.role == "protagonista", old.confidence):
            best[(e.type, e.id)] = e
    ordered = sorted(best.values(), key=lambda e: (e.role != "protagonista", -e.confidence, e.type, e.id))
    return [EntityLink(type=cast(EntityType, e.type), id=e.id, name=e.name or NO_DATA, role=cast(Role, e.role),
                       method=cast(LinkMethod, e.method), confidence=float(e.confidence)) for e in ordered]


def _text(value: str | None, allowed: bool) -> str | Missing:
    if not value:
        return NO_DATA
    return value if allowed else NO_RIGHTS


def _level(value: str | None) -> ConfirmationLevel | Missing:
    return cast(ConfirmationLevel, value) if value in LEVELS else NO_DATA


def _category(value: str | None) -> Category | Missing:
    return cast(Category, value) if value in CATEGORIES else NO_DATA


def card_fields(b: Bundle, at: datetime) -> dict[str, Any]:
    s = b.story
    allowed = b.may_summarise()
    warnings: list[StoryWarning] = ["desactualizada"] if s.valid_until is not None and s.valid_until < at else []
    return {
        "id": s.key, "headline_es": _text(s.headline_es, allowed), "summary_es": _text(s.summary_es, allowed),
        "category": _category(s.category), "level": _level(s.level), "warnings": warnings, "sources_count": len(b.shown()),
        "latest_at": b.latest_at(), "sources": [_source(i, b.publish[i.id]) for i in b.shown()], "entities": entities(b),
        "image": Image(), "status": cast(StoryStatus, s.status), "status_reason": s.status_reason or NO_DATA, "story_version": s.version,
        "claim_type": s.claim_type or NO_DATA, "lang": s.lang or NO_DATA, "country": s.country or NO_DATA,
        "own_text": OwnText(headline_es=s.headline_es or NO_DATA, summary_es=s.summary_es or NO_DATA,
                            text_version=s.text_version or NO_DATA),
        "withheld_sources": [_source(i, "none") for i in b.withheld()],
    }


def card(b: Bundle, at: datetime) -> StoryCardPrivate:
    return StoryCardPrivate(**card_fields(b, at))


def public_ok(b: Bundle) -> bool:
    """Shown to a reader: active, with an article that may be shown."""
    return b.story.status == "activa" and bool(b.shown())


def _list[T](items: list[T], reason: str) -> ItemList[T]:
    if items:
        return ItemList[T](items=items)
    return ItemList[T](items=[], missing_reason=reason)  # type: ignore[arg-type]


def _head(at: datetime) -> dict[str, Any]:
    return {"freshness": Freshness(generated_at=at, stale=False)}


# ── the front page (AD-G06) ──────────────────────────────────────────────────────────────────────────────────────────

def candidate(b: Bundle) -> order.Candidate:
    return order.Candidate(b.story.key, b.story.level, b.latest_at(), b.structured_at(), frozenset(b.entity_keys()))


def upcoming_of(conn: Conn, teams: Iterable[int], at: datetime) -> dict[int, datetime]:
    ids = sorted(set(teams))
    if not ids:
        return {}
    rows = conn.execute(UPCOMING_SQL, {"teams": ids, "now": at, "until": at + order.UPCOMING}).fetchall()
    return {int(r[0]): r[1] for r in rows}


def front_of(bundles: Sequence[Bundle], hidden: Sequence[Bundle], *, at: datetime, followed: Followed | None,
             upcoming: Mapping[int, datetime]) -> FrontPrivate:
    """The front page from the window's stories. Pure."""
    shown = [b for b in bundles if public_ok(b)]
    by_key = {b.story.key: b for b in shown}
    f = order.order([candidate(b) for b in shown], now=at, upcoming=upcoming,
                    followed=order.Followed(followed.teams, followed.players) if followed else order.Followed())
    counts = Counter(b.story.category for b in shown if b.story.category in CATEGORIES)
    mine: ItemList[StoryCardPrivate]
    if f.mine is None:
        mine = ItemList[StoryCardPrivate](items=[], missing_reason="sin_favoritos")
    else:
        mine = _list([card(by_key[k], at) for k in f.mine], "sin_resultados")
    return FrontPrivate(
        lead_story=card(by_key[f.lead], at) if f.lead else NO_DATA,
        breaking=_list([card(by_key[k], at) for k in f.breaking], "sin_resultados"), mine=mine,
        featured=_list([card(by_key[k], at) for k in f.featured], "sin_datos"),
        counts=[CategoryCount(category=c, n=counts[c]) for c in CATEGORIES if counts[c]],
        window_hours=int(order.WINDOW.total_seconds() // 3600), order_version=order.VERSION,
        queue=_list([card(b, at) for b in [*hidden, *(b for b in bundles if b.story.status == "activa" and not b.shown())]], "sin_datos"))


def build_front(conn: Conn, *, at: datetime, followed: Followed | None, publish: Publish) -> NewsPrivate:
    since = at - order.WINDOW
    bundles = reads.bundles(conn, reads.recent(conn, since=since, until=at), publish)
    hidden = reads.bundles(conn, reads.recent(conn, since=since, until=at, statuses=("en_moderacion", "retirada")), publish)
    teams = {i for b in bundles for t, i in b.entity_keys() if t == "team"}
    return NewsPrivate(**_head(at), view="portada", front=front_of(bundles, hidden, at=at, followed=followed,
                                                                   upcoming=upcoming_of(conn, teams, at)), story_status=NO_DATA)


# ── one story ────────────────────────────────────────────────────────────────────────────────────────────────────────

def timeline(b: Bundle, versions: Sequence[reads.Version]) -> list[TimelineEntry]:
    """Each article shown, in the order PrediGol saw it, with the story's level at that moment. Pure."""
    out: list[TimelineEntry] = []
    for i in sorted(b.shown(), key=lambda i: (i.seen_at, i.id)):
        then = [v for v in versions if v.at <= i.seen_at]
        out.append(TimelineEntry(known_at=i.seen_at, level=_level(then[-1].level if then else None), source=i.source_name))
    return out


def aspect_es(use: factlinks.ItemUse) -> str:
    return fact_es(use.entity_name, use.entity_type, use.kind, use.assertion)


def impact_of(uses: Sequence[factlinks.ItemUse], published: Mapping[int, bool], at: datetime) -> MatchImpact | Missing:
    """The nearest upcoming match whose PUBLISHED analysis used a fact of this story; otherwise nothing public. Pure."""
    ahead = sorted((u for u in uses if u.kickoff_at >= at and published.get(u.fixture_id)), key=lambda u: (u.kickoff_at, u.fixture_id))
    if not ahead:
        return NO_DATA
    u = ahead[0]
    return MatchImpact(fixture_id=u.fixture_id, kickoff_at=u.kickoff_at, aspect_es=aspect_es(u), analysis_published=True)


def analysis_links(uses: Sequence[factlinks.ItemUse], reason: str = "sin_datos") -> ItemList[AnalysisLink]:
    seen: dict[tuple[int, str, int], AnalysisLink] = {}
    for u in uses:
        seen.setdefault((u.fixture_id, u.evaluation, u.evaluation_version), AnalysisLink(
            fixture_id=u.fixture_id, evaluation=cast(EvaluationStep, u.evaluation), evaluation_version=u.evaluation_version,
            known_at=u.known_at, relation=cast(FactRelation, u.relation)))
    return _list(list(seen.values()), reason)


def related_of(conn: Conn, b: Bundle, publish: Publish, at: datetime) -> list[RelatedStory]:
    since = at - RELATED_WINDOW
    keys: set[str] = set()
    for kind in ("team", "player"):
        ids = sorted({e.id for e in b.entities if e.type == kind and e.role == "protagonista"})
        keys.update(reads.naming(conn, kind, ids, since=since))
    keys.discard(b.story.key)
    found = [x for x in reads.bundles(conn, reads.by_keys(conn, sorted(keys)).values(), publish) if public_ok(x)]
    found.sort(key=lambda x: (-x.latest_at().timestamp(), x.story.key))
    return [RelatedStory(id=x.story.key, headline_es=_text(x.story.headline_es, x.may_summarise()), level=_level(x.story.level))
            for x in found[:MAX_RELATED]]


def build_story(conn: Conn, key: str, *, at: datetime, publish: Publish) -> NewsPrivate:
    story = reads.by_keys(conn, [key]).get(key)
    if story is None:
        raise ApiError(404, "not_found", "no such story")
    status = cast(StoryStatus, story.status)
    if story.status != "activa":
        return NewsPrivate(**_head(at), view="noticia", story=WITHDRAWN if story.status == "retirada" else NO_RIGHTS, story_status=status)
    (b,) = reads.bundles(conn, [story], publish)
    if not b.shown():
        return NewsPrivate(**_head(at), view="noticia", story=NO_RIGHTS, story_status=status)
    uses = factlinks.by_items(conn, [i.id for i in b.items])
    published = {f: factlinks.published_at(conn, f, at) is not None for f in {u.fixture_id for u in uses}}
    fields = card_fields(b, at)
    detail = StoryDetailPrivate(
        **fields, essentials_es=fields["summary_es"],
        level_explanation_es=LEVEL_EXPLANATION_ES.get(story.level or "", NO_LEVEL_ES), match_impact=impact_of(uses, published, at),
        timeline=timeline(b, reads.versions(conn, key)), related=_list(related_of(conn, b, publish, at), "sin_resultados"),
        analyses=analysis_links(uses))
    return NewsPrivate(**_head(at), view="noticia", story=detail, story_status=status)


# ── search and filters ───────────────────────────────────────────────────────────────────────────────────────────────

def matches_filters(b: Bundle, f: Filters, followed: Followed | None) -> bool:
    """Every filter but the text (applied before) and the facets' own two. Pure."""
    keys = b.entity_keys()
    if f.country is not None and (b.story.country or "").casefold() != f.country.casefold():
        return False
    if f.competition is not None and ("competition", f.competition) not in keys:
        return False
    if f.team is not None and ("team", f.team) not in keys:
        return False
    if f.player is not None and ("player", f.player) not in keys:
        return False
    if f.mine:
        wanted = set() if followed is None else {("team", t) for t in followed.teams} | {("player", p) for p in followed.players}
        if not keys & wanted:
            return False
    latest = b.latest_at()
    return (f.since is None or latest >= f.since) and (f.until is None or latest <= f.until)


def search_of(bundles: Sequence[Bundle], ranks: Mapping[str, float] | None, f: Filters, followed: Followed | None) -> Search:
    """The search answer from the window's stories (``ranks``: the full-text hits, None without a text). Pure."""
    pool = [b for b in bundles if public_ok(b) and (ranks is None or b.story.key in ranks)]
    facets = Facets(category=[FacetCount(code=c, n=n) for c, n in sorted(Counter(b.story.category for b in pool if b.story.category).items())],
                    level=[FacetCount(code=lv, n=n) for lv, n in sorted(Counter(b.story.level for b in pool if b.story.level).items())])
    hits = [b for b in pool if matches_filters(b, f, followed) and (f.category is None or b.story.category == f.category)
            and (f.level is None or b.story.level == f.level)]
    if f.sort == "relevante" and ranks is not None:
        hits.sort(key=lambda b: (-ranks.get(b.story.key, 0.0), -b.latest_at().timestamp(), b.story.key))
    else:
        hits.sort(key=lambda b: (-b.latest_at().timestamp(), b.story.key))
    page = hits[f.offset:f.offset + f.limit]
    results = [SearchHit(story_id=b.story.key, headline_es=_text(b.story.headline_es, b.may_summarise()), level=_level(b.story.level),
                         category=_category(b.story.category), sources_count=len(b.shown()), latest_at=b.latest_at()) for b in page]
    more = f.offset + f.limit < len(hits)
    return Search(query=f.q or "", normalized=reads.normalized(f.q or ""), sort=f.sort, filters_applied=f.applied(), facets=facets,
                  results=_list(results, "sin_resultados"), total=len(hits), next_offset=f.offset + f.limit if more else None)


def build_search(conn: Conn, f: Filters, *, at: datetime, followed: Followed | None, publish: Publish) -> NewsPrivate:
    until = min(f.until or at, at)
    since = f.since or until - SEARCH_WINDOW
    ranks = reads.search(conn, f.q, since=since, until=until) if f.q and reads.normalized(f.q) else None
    stories = reads.by_keys(conn, sorted(ranks)).values() if ranks is not None else reads.recent(conn, since=since, until=until)
    bundles = reads.bundles(conn, stories, publish)
    return NewsPrivate(**_head(at), view="busqueda", search=search_of(bundles, ranks, f, followed), story_status=NO_DATA)


# ── the stories of a match ───────────────────────────────────────────────────────────────────────────────────────────

def build_match(conn: Conn, fixture_id: int, *, at: datetime, publish: Publish) -> NewsPrivate:
    row = conn.execute(MATCH_SQL, {"f": fixture_id}).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "no such match")
    _, kickoff, home, away, previous = row
    start = max(kickoff - MATCH_WINDOW, previous) if previous is not None else kickoff - MATCH_WINDOW
    keys = set(reads.naming(conn, "fixture", [fixture_id], since=start)) | set(reads.naming(conn, "team", [home, away], since=start))
    bundles = [b for b in reads.bundles(conn, reads.by_keys(conn, sorted(keys)).values(), publish)
               if public_ok(b) and b.latest_at() >= start]
    bundles.sort(key=lambda b: (order.LEVEL_RANK.get(b.story.level, 5), -b.latest_at().timestamp(), b.story.key))
    uses = [u for u in factlinks.by_items(conn, [i.id for b in bundles for i in b.items]) if u.fixture_id == fixture_id]
    body = MatchStoriesPrivate(fixture_id=fixture_id, kickoff_at=kickoff, window_from=start,
                               stories=_list([card(b, at) for b in bundles[:MAX_MATCH]], "sin_resultados"),
                               analyses=analysis_links(uses))
    return NewsPrivate(**_head(at), view="partido", match=body, story_status=NO_DATA)


# ── the two projections ──────────────────────────────────────────────────────────────────────────────────────────────

Builder = Callable[[Publish], NewsPrivate]


def private_answer(conn: Conn, builder: Builder, *, at: datetime | None = None) -> Envelope[NewsPrivate]:
    if not reads.tables_exist(conn):
        raise ApiError(503, "unavailable", "the news store is not migrated yet (revision 0146)")
    return ok(builder(publisher(conn)), data_as_of=at)


def public_answer(conn: Conn, builder: Builder, *, at: datetime | None = None) -> Envelope[News | None]:
    """404 unless FBI_NEWS_FEED and FBI_NEWS_V2 are both on - checked before anything is read; ``not_available`` while the owner keeps
    the news from readers."""
    if not (news_feed_on() and news_v2_on()):
        raise ApiError(404, "not_found", "not found")
    if not users_may_see():
        return unavailable(None, "The news are not shown to users at the moment.")
    if not reads.tables_exist(conn):
        return unavailable(None, "The news store is not ready.")
    return ok(to_public(builder(publisher(conn)), News), data_as_of=at)


def front(conn: Conn, *, user_id: int | None, public: bool) -> Envelope[Any]:
    at = now()

    def builder(p: Publish) -> NewsPrivate:
        return build_front(conn, at=at, followed=followed_of(conn, user_id), publish=p)

    return public_answer(conn, builder, at=at) if public else private_answer(conn, builder, at=at)


def story(conn: Conn, key: str, *, public: bool) -> Envelope[Any]:
    at = now()

    def builder(p: Publish) -> NewsPrivate:
        return build_story(conn, key, at=at, publish=p)

    return public_answer(conn, builder, at=at) if public else private_answer(conn, builder, at=at)


def search(conn: Conn, f: Filters, *, user_id: int | None, public: bool) -> Envelope[Any]:
    at = now()

    def builder(p: Publish) -> NewsPrivate:
        return build_search(conn, f, at=at, followed=followed_of(conn, user_id), publish=p)

    return public_answer(conn, builder, at=at) if public else private_answer(conn, builder, at=at)


def match(conn: Conn, fixture_id: int, *, public: bool) -> Envelope[Any]:
    at = now()

    def builder(p: Publish) -> NewsPrivate:
        return build_match(conn, fixture_id, at=at, publish=p)

    return public_answer(conn, builder, at=at) if public else private_answer(conn, builder, at=at)

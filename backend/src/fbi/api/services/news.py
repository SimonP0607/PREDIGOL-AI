"""The news of a match for the reader (plan UX, A10; section 27 of the plan): what PrediGol Intelligence already found and
verified outside the numbers (``ai.evidence``, read only), as cards - PrediGol's own summary, the source and its standing,
the time, the relevance for the match, the status the server decided and the link to the original.

Reading only: no search is made for a reader, no model is called, nothing is written and no status is raised here - the status of
every item is the one ``fbi.ai.evidence`` decided (that module is neither imported nor touched). The one exception is Home's summary
(``digest``, plan de Inicio 3.3): a «confirmed» there needs an official source or two distinct outlets, and shows as «probable»
when it has neither. Only the
match's own items reach a reader: ``fixture_id`` is the match, never another one of the same teams, and never generic news to
fill the space.

What never leaves this module:

* an article's text, title or picture - the research cache (``ai.research_cache``) is never read, and the result's title kept
  with an item is used only to make sure the summary does not repeat it;
* the owner's own notes (``origin = 'owner'``) and the data provider's reports (``origin = 'provider'``: the injury report and
  the confirmed line-ups are the match's own data, shown in Alineaciones with their source, not news);
* a summary that does not read as Spanish (the extraction is asked for Spanish and once in a while answers in the source's
  language): the card keeps its kind, player, team, sources and status, and the web words it from them.

**The order** (section 27): confirmed first, then probable, contradictions, rumours and the outdated last; within a status the
most relevant first, then the newest. **Relevance** is said from what the item is about, because the stored number is the same
for every item the web search finds: high - who plays or does not (an absence, a doubt, a return or a line-up, of a named player
or the team's eleven); medium - the same without a name, or the coach; low - the rest of the context.

**A contradiction is shown as such, with both sources**: the items of one subject (the same player of the same team) that
contradict each other become one card with each claim and its own sources.

**Whether it was searched** (IA-016): the match's answer says whether PrediGol Intelligence searched the web for it, when it last did, how
many searches it paid and how many pages it read - from the ledger (``ai.usage``) and the passes of the day (``ai.fixture_passes``), read
only - so «not searched yet» is never said as «nothing found».

``FBI_NEWS_USERS`` (on since A10; ``=0`` hides the news again without a deploy, ``fbi.api.switches``).

**The other language** (plan UX, A11): an item's own headline in Spanish and English and its summary in English, written by the
readers' narrative in the worker and checked there one by one (``ai.evidence_translations``, keyed by the item's unchanging
content). Read here, never written; shown only while the owner has the narrative on (``FBI_USER_NARRATIVE=on``).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal, cast

import psycopg

from fbi.ai.gates import typed_visible
from fbi.api.cache import shared
from fbi.api.contracts.news import (
    Assertion,
    MatchNews,
    NewsClaim,
    NewsItem,
    NewsKind,
    NewsSearch,
    NewsSource,
    NewsStatus,
    NewsTeam,
    Tier,
    TodayNews,
    TodayNewsItem,
    TodayNewsMatch,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.follows import Follows, follow_reason
from fbi.api.services.reading import narrative_mode
from fbi.api.switches import user_switch
from fbi.core.clock import now

USERS_SWITCH: Final = "FBI_NEWS_USERS"
"""Every signed-in account sees the news: on since plan UX A10, ``FBI_NEWS_USERS=0`` hides them again without a deploy (the
API needs a restart to read it)."""

STATUS_ORDER: Final[tuple[NewsStatus, ...]] = ("CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR", "OUTDATED")
Relevance = Literal["high", "medium", "low"]
RELEVANCE_ORDER: Final[tuple[Relevance, ...]] = ("high", "medium", "low")
KINDS: Final = frozenset({"injury", "suspension", "doubtful", "lineup", "coach", "news", "transfer", "motivation",
                          "weather", "travel", "schedule", "other"})
ASSERTIONS: Final = frozenset({"out", "doubtful", "available", "starts", "info"})
TIERS: Final = frozenset({"official", "competition", "club", "provider", "journalist", "media", "aggregator", "social",
                          "unknown"})
AVAILABILITY: Final = frozenset({"injury", "suspension", "doubtful", "lineup"})
"""What says who plays: the kinds PrediGol Intelligence compares to outdate or contradict an item."""
MAX_READ: Final = 400
"""Items read per match, newest first: far above what one match gathers (the busiest had nine sources on one story)."""
MAX_SOURCES: Final = 4
TITLE_MIN: Final = 20
"""A stored result title this long found inside a summary means the summary repeats the source: it is not sent."""
URL: Final = re.compile(r"^https?://[^\s\"'<>]+$")
TODAY_BEFORE: Final = timedelta(hours=3)
TODAY_AFTER: Final = timedelta(hours=36)
TODAY_PER_MATCH: Final = 3
HOME_STATUSES: Final = frozenset({"CONFIRMED", "PROBABLE", "RUMOR"})
"""What Home may carry from a match: a rumour only as the one labelled exception (``digest``)."""
GENERAL_NEWS_MAX: Final = 3
"""Inicio's general «Noticias» (plan de Inicio, 3.3): a summary of three at most, the same for everyone."""
OWN_NEWS_MAX: Final = 2
"""The news of the reader's own teams and leagues («Para ti»): two at most."""
RUMORS_MAX: Final = 1
PER_MATCH_MAX: Final = 2
"""A match fills no more than two of the summary's places, so one busy match does not become the whole block."""
"""Home's block 4 shows only what is confirmed or probable (plan section 24)."""

# ── does a summary read as Spanish? ──────────────────────────────────────────────────────────────────────────────────

SPANISH: Final = frozenset({
    "el", "la", "los", "las", "del", "de", "en", "y", "es", "una", "un", "que", "por", "para", "con", "según", "segun",
    "se", "su", "sus", "al", "lo", "este", "esta", "está", "será", "sera", "pero", "sin", "como", "más", "tras", "ante",
    "sobre", "desde", "hasta", "también", "tambien", "ya", "aunque", "porque", "cuando", "donde", "partido", "baja",
    "bajas", "lesión", "lesion", "jugará", "jugara", "jugador", "equipo", "alineación", "alineacion", "titular", "duda",
    "entrenador", "convocatoria", "estará", "estara", "podría", "podria", "fuente", "indica", "informa"})
"""Common Spanish words: a summary needs two of them..."""
SPANISH_ONLY: Final = frozenset({
    "el", "los", "las", "y", "según", "segun", "está", "será", "jugará", "lesión", "alineación", "también", "aunque",
    "partido", "baja", "bajas", "entrenador", "convocatoria", "estará", "podría"})
"""...and one that the neighbouring languages do not use..."""
OTHER: Final = frozenset({
    # English
    "the", "is", "are", "and", "of", "to", "will", "has", "have", "with", "for", "from", "his", "he", "be", "was", "not",
    "that", "this", "after", "at", "by", "on", "in",
    # Portuguese
    "não", "nao", "uma", "com", "em", "os", "do", "da", "dos", "é", "ele", "foi", "pelo", "pela", "ao", "também",
    # Italian
    "il", "di", "che", "è", "non", "gli", "della", "sono", "per", "nel", "alla", "dei", "anche", "ha",
    # French
    "le", "les", "des", "est", "une", "pas", "du", "au", "avec", "selon", "pour", "sur", "qui",
    # German and Dutch
    "der", "die", "das", "und", "ist", "nicht", "mit", "von", "het", "een", "van", "niet", "op", "zijn", "ook",
    # Turkish
    "ve", "bir", "ile", "için", "icin", "olarak"})
"""...and at least twice as many as the words of another language."""
WORD: Final = re.compile(r"[^\W\d_]+")


def reads_as_spanish(text: str) -> bool:
    """Whether a summary reads as Spanish (pure): two common Spanish words, one only Spanish uses, and at least twice as many
    as the words of English, Portuguese, Italian, French, German, Dutch or Turkish. A name never decides it either way."""
    words = WORD.findall(text.lower())
    spanish = sum(1 for w in words if w in SPANISH)
    only = sum(1 for w in words if w in SPANISH_ONLY)
    other = sum(1 for w in words if w in OTHER)
    return spanish >= 2 and only >= 1 and spanish >= 2 * other


def own_summary(claim: str | None, title: str | None) -> str | None:
    """The summary a reader may get (pure): PrediGol's own sentence when it reads as Spanish, carries no link and does not
    repeat the source's title; otherwise nothing (the web words the card from its kind, player and team)."""
    if not claim:
        return None
    text = " ".join(claim.split())
    if len(text) < 5 or "http://" in text.lower() or "https://" in text.lower() or "www." in text.lower():
        return None
    if title:
        heading = " ".join(title.split()).lower()
        if len(heading) >= TITLE_MIN and heading in text.lower():
            return None
    return text if reads_as_spanish(text) else None


# ── one item as read, and its card ───────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Row:
    id: int
    fixture_id: int
    team_id: int | None
    kind: str
    claim: str
    source_name: str
    source_url: str | None
    tier: str
    published_at: datetime | None
    retrieved_at: datetime
    last_seen_at: datetime | None
    story_key: str
    status: str
    assertion: str
    player: str | None
    title: str | None
    headline_es: str | None = None
    headline_en: str | None = None
    claim_en: str | None = None

    @property
    def when(self) -> datetime:
        return self.published_at or self.retrieved_at

    @property
    def seen(self) -> datetime:
        return max(self.retrieved_at, self.last_seen_at or self.retrieved_at)


def _text(value: Any) -> str | None:
    return " ".join(str(value).split()) or None if value else None


def _row(r: Mapping[str, Any], *, translated: bool = False) -> Row:
    assertion = str(r.get("assertion") or "info")
    player = str(r["player"]).strip()[:80] if r.get("player") and str(r["player"]).strip() else None
    return Row(id=int(r["id"]), fixture_id=int(r["fixture_id"]), team_id=None if r["team_id"] is None else int(r["team_id"]),
               kind=str(r["kind"]), claim=str(r["claim"]), source_name=str(r["source_name"]), source_url=r["source_url"],
               tier=str(r["source_tier"]), published_at=r["published_at"], retrieved_at=r["retrieved_at"],
               last_seen_at=r["last_seen_at"], story_key=str(r["story_key"]), status=str(r["status"]),
               assertion=assertion if assertion in ASSERTIONS else "info", player=player, title=r.get("title"),
               headline_es=_text(r.get("headline_es")) if translated else None,
               headline_en=_text(r.get("headline_en")) if translated else None,
               claim_en=_text(r.get("claim_en")) if translated else None)


def day_only(moment: datetime | None) -> bool:
    """A publication the source dated only by its day: it reads 00:00:00 UTC (pure)."""
    return moment is not None and moment.astimezone(UTC).time() == time(0, 0)


def source_name(raw: str) -> str:
    name = raw.strip()
    if name.lower().startswith("www."):
        name = name[4:]
    return name[:80] or "?"


def relevance_of(kind: str, player: str | None) -> Relevance:
    """How much the item matters for this match, from what it is about (pure): see the module's docstring."""
    if kind in AVAILABILITY:
        return "high" if player or kind == "lineup" else "medium"
    if kind == "coach":
        return "medium"
    return "low"


def name_key(name: str | None) -> str:
    """A player's name to compare sources by: no accents, no case, no punctuation («Luis Suárez» is «Luis Suarez»)."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _sources(rows: Sequence[Row]) -> list[NewsSource]:
    out: list[NewsSource] = []
    seen: set[str] = set()
    for r in sorted(rows, key=lambda x: (x.when, x.id), reverse=True):
        url = r.source_url if r.source_url and URL.match(r.source_url) else None
        key = url or source_name(r.source_name)
        if key in seen:
            continue
        seen.add(key)
        out.append(NewsSource(name=source_name(r.source_name), tier=cast(Tier, r.tier if r.tier in TIERS else "unknown"),
                              url=url, published_at=r.published_at, published_day_only=day_only(r.published_at)))
        if len(out) == MAX_SOURCES:
            break
    return out


@dataclass(frozen=True)
class Story:
    """The items about one thing (one ``story_key``): one source each."""
    rows: tuple[Row, ...]

    @property
    def status(self) -> NewsStatus:
        statuses = {r.status for r in self.rows}
        if "CONTRADICTORY" in statuses:
            return "CONTRADICTORY"
        return min((s for s in statuses if s in STATUS_ORDER), key=STATUS_ORDER.index, default="RUMOR")

    @property
    def chosen(self) -> tuple[Row, ...]:
        """The items that carry the story's status (the others are older sources it already superseded)."""
        own = tuple(r for r in self.rows if r.status == self.status)
        return own or self.rows

    @property
    def newest(self) -> Row:
        return max(self.chosen, key=lambda r: (r.when, r.id))

    def claim(self) -> NewsClaim:
        text = None
        newest_first = sorted(self.chosen, key=lambda x: (x.when, x.id), reverse=True)
        source = newest_first[0]
        for r in newest_first:
            text = own_summary(r.claim, r.title)
            if text:
                source = r
                break
        return NewsClaim(text=text, lang="es", text_en=source.claim_en, assertion=cast(Assertion, self.newest.assertion),
                         sources=_sources(self.chosen))


def _card(stories: Sequence[Story], status: NewsStatus, teams: Mapping[int, NewsTeam]) -> NewsItem:
    ordered = sorted(stories, key=lambda s: (s.newest.when, s.newest.id), reverse=True)
    lead = ordered[0].newest
    rows = [r for s in ordered for r in s.chosen]
    published = max((r.published_at for r in rows if r.published_at is not None), default=None)
    relevance = min((relevance_of(s.newest.kind, s.newest.player) for s in ordered), key=RELEVANCE_ORDER.index)
    player = next((s.newest.player for s in ordered if s.newest.player), None)
    own = status != "CONTRADICTORY"  # a headline of one side would take that side
    return NewsItem(
        id=f"n{min(r.id for s in ordered for r in s.rows)}", kind=cast(NewsKind, lead.kind if lead.kind in KINDS else "other"),
        status=status, relevance=relevance, team=teams.get(lead.team_id) if lead.team_id is not None else None,
        player=player, claims=[s.claim() for s in ordered], published_at=published, published_day_only=day_only(published),
        seen_at=max(r.seen for r in rows), headline_es=lead.headline_es if own else None,
        headline_en=lead.headline_en if own else None)


def _order(item: NewsItem) -> tuple[int, int, float, str]:
    moment = item.published_at or item.seen_at
    return STATUS_ORDER.index(item.status), RELEVANCE_ORDER.index(item.relevance), -moment.timestamp(), item.id


def cards(rows: Iterable[Row], teams: Mapping[int, NewsTeam]) -> list[NewsItem]:
    """The cards of one match's items (pure), in the order of section 27."""
    by_story: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_story[r.story_key].append(r)
    stories = [Story(tuple(items)) for items in by_story.values()]
    out: list[NewsItem] = []
    against: dict[tuple[int | None, str], list[Story]] = defaultdict(list)
    for story in stories:
        lead = story.newest
        if story.status == "CONTRADICTORY" and name_key(lead.player):
            against[(lead.team_id, name_key(lead.player))].append(story)
        else:
            out.append(_card([story], story.status, teams))
    for group in against.values():
        out.append(_card(group, "CONTRADICTORY", teams))
    return sorted(out, key=_order)


# ── Home's summary (plan de Inicio, 3.3) ─────────────────────────────────────────────────────────────────────────────

COMPOUND: Final = frozenset({"com", "co", "org", "net", "gov", "edu", "ac"})
"""Second-level labels that make a country's suffix two labels long (``marca.com.co``, ``bbc.co.uk``)."""
OUTLETS: Final = frozenset({"official", "competition", "club", "journalist", "media"})
"""The standings that count as an outlet: an aggregator, a social post or an unknown site never corroborates."""


def outlet_key(source: NewsSource) -> str:
    """The outlet behind a source, so two pages of one site - or its subdomains - are one outlet (pure): the address's
    registered name (``es.marca.com`` and ``www.marca.com`` are ``marca.com``), else the name the search gave."""
    host = source.name.lower()
    if source.url and URL.match(source.url):
        host = re.sub(r"^https?://", "", source.url).split("/", 1)[0].split(":", 1)[0].lower()
    host = host.removeprefix("www.")
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return host
    keep = 3 if len(labels) >= 3 and labels[-2] in COMPOUND and len(labels[-1]) == 2 else 2
    return ".".join(labels[-keep:])


def corroborated(item: NewsItem) -> bool:
    """Whether Home may say «confirmed» (pure): an official source, or two distinct outlets - never one outlet twice, an
    aggregator or a social post. Each claim of the item is read on its own (a contradiction is never confirmed here)."""
    if item.status != "CONFIRMED" or len(item.claims) != 1:
        return False
    sources = [s for s in item.claims[0].sources if s.tier in OUTLETS]
    return any(s.tier == "official" for s in sources) or len({outlet_key(s) for s in sources}) >= 2


def for_home(item: NewsItem) -> NewsItem:
    """The item as Home shows it: a «confirmed» nobody corroborated reads as «probable»."""
    if item.status == "CONFIRMED" and not corroborated(item):
        return item.model_copy(update={"status": "PROBABLE"})
    return item


def digest(items: Sequence[TodayNewsItem], limit: int) -> list[TodayNewsItem]:
    """Home's summary of the news of several matches (pure), at most ``limit``: confirmed - by the rule above - first, then
    probable, each the most relevant and the newest first; at most two from one match; and, only if there is room left, one
    rumour (never one of low relevance) - the web labels it «Rumor»."""
    shaped = [TodayNewsItem(match=i.match, item=for_home(i.item)) for i in items if i.item.status in HOME_STATUSES]

    def rank(i: TodayNewsItem) -> tuple[int, int, float, int, str]:
        moment = i.item.published_at or i.item.seen_at
        return (STATUS_ORDER.index(i.item.status), RELEVANCE_ORDER.index(i.item.relevance), -moment.timestamp(),
                i.match.fixture_id, i.item.id)

    ordered = sorted(shaped, key=rank)
    firm = [i for i in ordered if i.item.status != "RUMOR"]
    rumors = [i for i in ordered if i.item.status == "RUMOR" and i.item.relevance != "low"]
    chosen: list[TodayNewsItem] = []
    per_match: dict[int, int] = defaultdict(int)
    for i in firm:
        if len(chosen) == limit:
            break
        if per_match[i.match.fixture_id] < PER_MATCH_MAX:
            per_match[i.match.fixture_id] += 1
            chosen.append(i)
    for i in rumors[:RUMORS_MAX]:
        if len(chosen) < limit and per_match[i.match.fixture_id] < PER_MATCH_MAX:
            chosen.append(i)
    return chosen


def counts(items: Sequence[NewsItem]) -> dict[NewsStatus, int]:
    found: dict[NewsStatus, int] = dict.fromkeys(STATUS_ORDER, 0)
    for item in items:
        found[item.status] += 1
    return found


def users_may_see() -> bool:
    return user_switch(USERS_SWITCH, default=True)


# ── the database ─────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, th.name AS home_name, f.away_team_id, ta.name AS away_name
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""

EVIDENCE_SQL = """
SELECT x.*, tes.headline AS headline_es, ten.headline AS headline_en, ten.claim AS claim_en FROM (
  SELECT e.id, e.fixture_id, e.team_id, e.kind, e.claim, e.source_name, e.source_url, e.source_tier, e.published_at,
         e.retrieved_at, e.last_seen_at, e.story_key, e.status, e.content_hash, e.attributes->>'assertion' AS assertion,
         e.attributes->>'player_name' AS player, e.attributes->>'result_title' AS title,
         row_number() OVER (PARTITION BY e.fixture_id ORDER BY e.retrieved_at DESC, e.id DESC) AS n
    FROM ai.evidence e
   WHERE e.fixture_id = ANY(%(fixtures)s) AND e.origin = 'web' AND e.retrieved_at <= %(at)s
     AND (e.subject_type IS NULL OR %(typed)s)
) x
LEFT JOIN LATERAL (SELECT t.headline FROM ai.evidence_translations t
                    WHERE t.evidence_id = x.id AND t.content_hash = x.content_hash AND t.lang = 'es'
                      AND t.headline IS NOT NULL AND %(translated)s
                    ORDER BY t.created_at DESC, t.id DESC LIMIT 1) tes ON true
LEFT JOIN LATERAL (SELECT t.headline, t.claim FROM ai.evidence_translations t
                    WHERE t.evidence_id = x.id AND t.content_hash = x.content_hash AND t.lang = 'en' AND %(translated)s
                    ORDER BY t.created_at DESC, t.id DESC LIMIT 1) ten ON true
WHERE x.n <= %(limit)s
"""
"""Only the web's items of the matches asked for (the data provider's reports and the owner's notes stay out), as of a moment -
and the claims of research v2 (``subject_type``) only while it is ``on`` (``fbi.ai.gates.typed_visible``, the IA plan's phase 2): in
``off`` and ``shadow`` they are written for the comparison and no reader sees them."""

FOLLOWED_MATCHES_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, th.name AS home_name, f.away_team_id, ta.name AS away_name,
       c.id AS competition_id, c.name AS competition
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND f.status_group IN ('scheduled', 'live')
   AND (c.id = ANY(%(leagues)s) OR f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s))
 ORDER BY f.kickoff_at, f.id
"""
"""The reader's matches not yet over (plan UX, B2): their leagues and teams, as ids - the suggested ones while they chose none."""


SEARCH_SQL = """
SELECT (SELECT max(u.at) FROM ai.usage u
         WHERE u.fixture_id = %(f)s AND u.purpose = 'web_search' AND u.status = 'ok' AND u.at <= %(at)s) AS paid_at,
       (SELECT count(*) FROM ai.usage u
         WHERE u.fixture_id = %(f)s AND u.purpose = 'web_search' AND u.status = 'ok' AND u.at <= %(at)s) AS searches,
       (SELECT max(p.finished_at) FROM ai.fixture_passes p
         WHERE p.fixture_id = %(f)s AND p.finished_at <= %(at)s
           AND (COALESCE((p.counts->>'web_asked')::int, 0) > 0 OR COALESCE((p.counts->>'web_searches')::int, 0) > 0)) AS pass_at,
       (SELECT sum((p.counts->>'web_read')::int) FROM ai.fixture_passes p
         WHERE p.fixture_id = %(f)s AND p.finished_at <= %(at)s AND p.counts ? 'web_read') AS sources_read,
       (SELECT count(*) FROM ai.fixture_passes p
         WHERE p.fixture_id = %(f)s AND p.finished_at <= %(at)s AND COALESCE((p.counts->>'web_searches')::int, 0) > 0
           AND NOT p.counts ? 'web_read') AS untracked
"""
"""What the cycle recorded about searching one match, as of a moment (IA-016): the searches paid for it (``ai.usage``, one row per search,
with the match), the newest pass that read the web - a search paid now, or answered by the cache (``web_asked``) - and the pages read
(``web_read``), with the passes that searched before that count existed (``untracked``: then the number of pages is not known)."""


def search_state(row: Mapping[str, Any] | None) -> NewsSearch:
    """Whether the match was searched, from ``SEARCH_SQL``'s row (pure). Searched when a search was paid for it or a pass read the web; the
    newest of the two is the last search. The pages read are said only when every pass that searched counted them."""
    if row is None:
        return NewsSearch(searched="unknown")
    moments = [m for m in (row.get("paid_at"), row.get("pass_at")) if m is not None]
    searches = int(row.get("searches") or 0)
    if not moments:
        return NewsSearch(searched="no", searches=searches, sources_read=0)
    read = row.get("sources_read")
    known = None if read is None or int(row.get("untracked") or 0) else int(read)
    return NewsSearch(searched="yes", last_searched_at=max(moments), searches=searches, sources_read=known)


def _search(conn: Conn, fixture_id: int, at: datetime) -> NewsSearch:
    """The match's search state; ``unknown`` when the record cannot be read (in a savepoint: a failure here never breaks the news)."""
    try:
        with conn.transaction():
            return search_state(fetch_one(conn, SEARCH_SQL, {"f": fixture_id, "at": at}))
    except psycopg.Error:
        return NewsSearch(searched="unknown")


def empty_reason(search: NewsSearch) -> str:
    """What an empty answer says (pure): not searched yet is not the same as nothing found."""
    if search.searched == "no":
        return "This match has not been searched for news yet."
    if search.searched == "yes":
        return "The web was searched for this match and no relevant news was found."
    return "No news relevant to this match."


def _teams(f: Mapping[str, Any]) -> dict[int, NewsTeam]:
    return {int(f["home_team_id"]): NewsTeam(id=int(f["home_team_id"]), name=f["home_name"], side="home"),
            int(f["away_team_id"]): NewsTeam(id=int(f["away_team_id"]), name=f["away_name"], side="away")}


def translations_shown() -> bool:
    """The items' own headlines and English summaries (A11) reach readers only while the narrative is on."""
    return narrative_mode() == "on"


def _read(conn: Conn, fixtures: Sequence[int], at: datetime) -> dict[int, list[Row]]:
    found: dict[int, list[Row]] = defaultdict(list)
    if not fixtures:
        return found
    translated = translations_shown()
    for r in fetch_all(conn, EVIDENCE_SQL, {"fixtures": list(fixtures), "at": at, "limit": MAX_READ,
                                            "translated": translated, "typed": typed_visible(conn)}):
        found[int(r["fixture_id"])].append(_row(r, translated=translated))
    return found


def stored_items(conn: Conn, fixture_id: int, *, at: datetime) -> list[Row]:
    """The web's items of one match exactly as its news read them (``EVIDENCE_SQL``): what the owner's diagnosis (IA-018) counts by status."""
    return _read(conn, [fixture_id], at).get(fixture_id, [])


def match_news(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[MatchNews | None]:
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not users_may_see():
        return unavailable(None, "The news are not shown to users at the moment.")
    moment = at or now()
    items = cards(_read(conn, [fixture_id], moment).get(fixture_id, []), _teams(fixture))
    search = _search(conn, fixture_id, moment)
    body = MatchNews(fixture_id=fixture_id, items=items, counts=counts(items), search=search)
    if not items:
        return unavailable(body, empty_reason(search), status=DataStatus.EMPTY, count=0)
    return ok(body, count=len(items), data_as_of=max(i.seen_at for i in items))


@shared(120)
def news_for(conn: Conn, follows: Follows, *, at: datetime | None = None) -> Envelope[TodayNews | None]:
    """Home's «Noticias» as a summary (plan UX, B2; plan de Inicio, 3.3): the best few confirmed or probable news - and, with
    room left, one rumour - of the matches of the leagues and teams ``follows`` names, not yet over, each match saying why it
    is theirs: three for the general layer (``follows.suggested``, the same for everyone), two for the reader's own («Para ti»).
    Kept two minutes per set of favourites; the items are the same for every reader who sees them."""
    if not users_may_see():
        return unavailable(None, "The news are not shown to users at the moment.")
    moment = at or now()
    fixtures = fetch_all(conn, FOLLOWED_MATCHES_SQL, {"since": moment - TODAY_BEFORE, "until": moment + TODAY_AFTER,
                                                      "leagues": list(follows.leagues), "teams": list(follows.teams)})
    rows = _read(conn, [int(f["id"]) for f in fixtures], moment)
    items: list[TodayNewsItem] = []
    for f in fixtures:
        fid = int(f["id"])
        if fid not in rows:
            continue
        reason = follow_reason((int(f["home_team_id"]), str(f["home_name"])), (int(f["away_team_id"]), str(f["away_name"])),
                               (int(f["competition_id"]), str(f["competition"])), follows)
        match = TodayNewsMatch(fixture_id=fid, kickoff_at=f["kickoff_at"], status_group=str(f["status_group"]),
                               home=f["home_name"], away=f["away_name"], competition=f["competition"], followed=reason)
        shown = [c for c in cards(rows[fid], _teams(f)) if c.status in HOME_STATUSES][:TODAY_PER_MATCH]
        items.extend(TodayNewsItem(match=match, item=c) for c in shown)
    body = TodayNews(items=digest(items, GENERAL_NEWS_MAX if follows.suggested else OWN_NEWS_MAX),
                     suggested=follows.suggested)
    if not body.items:
        return unavailable(body, "No confirmed or probable news of the reader's matches.", status=DataStatus.EMPTY,
                           count=0)
    return ok(body, count=len(body.items), data_as_of=max(i.item.seen_at for i in body.items))

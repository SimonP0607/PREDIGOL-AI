"""Reading the news store for C-06 (IA-121, AD-G07). Every read takes the newest row where the store is versioned (a story's newest
version, an item's newest link to a story, an item's newest version, an item's newest link to an entity) and filters by key, date and
LIMIT: no read sweeps a table.

What of an article may be shown is ``publish(item)``: the caller's word (``summary``, ``link`` or ``none``), the stricter of the copy
written when it was seen and the policy in force. An item at ``none`` is left out of everything public; a story's own headline and
summary are shown only while one of its items may publish a ``summary``.

The search is PostgreSQL's full text (``to_tsvector('simple', unaccent(...))``, without accents or case) over PrediGol's own words of a
story - its headline and summary - and the names of what it names (PrediGol's names; the names an article used, never shown). Never
the article's text: it is not stored."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.people.identity.names import alias_key

MAX_STORIES: Final = 300
MAX_ITEMS: Final = 2000
PUBLISH_ORDER: Final = {"none": 0, "link": 1, "summary": 2}
STATUSES: Final = ("activa", "en_moderacion", "retirada")


@dataclass(frozen=True, slots=True)
class Story:
    key: str
    id: int
    version: int
    at: datetime
    first_seen_at: datetime
    event_at: datetime | None
    valid_until: datetime | None
    claim_type: str | None
    category: str | None
    level: str | None
    lang: str | None
    country: str | None
    headline_es: str | None
    summary_es: str | None
    text_version: str | None
    status: str
    status_reason: str | None


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    story_key: str
    canonical_url: str
    source_name: str
    source_state: str
    publish_level: str
    author: str | None
    published_at: datetime | None
    published_day_only: bool
    published_structured: bool
    seen_at: datetime


@dataclass(frozen=True, slots=True)
class Entity:
    item_id: int
    type: str
    id: int
    name: str | None
    role: str
    method: str
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class Version:
    """One version of a story, for «Cómo se fue sabiendo»."""

    at: datetime
    level: str | None


@dataclass(frozen=True, slots=True)
class Bundle:
    """A story as C-06 reads it: its newest version, its articles (newest first, each with what it may show) and who they name."""

    story: Story
    items: list[Item] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    publish: dict[int, str] = field(default_factory=dict)

    def shown(self) -> list[Item]:
        """The articles that may be shown (at least the link)."""
        return [i for i in self.items if self.publish.get(i.id, "none") != "none"]

    def withheld(self) -> list[Item]:
        return [i for i in self.items if self.publish.get(i.id, "none") == "none"]

    def may_summarise(self) -> bool:
        return any(self.publish.get(i.id) == "summary" for i in self.items)

    def latest_at(self) -> datetime:
        shown = self.shown()
        return max((i.published_at or i.seen_at for i in shown), default=self.story.at)

    def structured_at(self) -> datetime | None:
        """The newest structured publication date of a shown article: only these enter «Última hora»."""
        return max((i.published_at for i in self.shown() if i.published_structured and i.published_at is not None), default=None)

    def entity_keys(self) -> set[tuple[str, int]]:
        shown = {i.id for i in self.shown()}
        return {(e.type, e.id) for e in self.entities if e.item_id in shown}


Publish = Callable[[Item], str]


def stricter(stored: str, now: str) -> str:
    return min(stored, now, key=lambda w: PUBLISH_ORDER.get(w, 0))


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


STORY_FIELDS: Final = ("story_key AS key, id, version, at, first_seen_at, event_at, valid_until, claim_type, category, level, lang, country, headline_es, "
                       "summary_es, text_version, status, status_reason")
TABLES_SQL: Final = "SELECT to_regclass('news.stories') IS NOT NULL AND to_regclass('news.item_entities') IS NOT NULL"
RECENT_SQL: Final = f"""
SELECT {STORY_FIELDS} FROM (
    SELECT DISTINCT ON (story_key) * FROM news.stories
     WHERE story_key IN (SELECT story_key FROM news.stories WHERE at >= %(since)s AND at <= %(until)s)
     ORDER BY story_key, version DESC
) s WHERE s.status = ANY(%(statuses)s)
 ORDER BY s.at DESC, s.id DESC LIMIT %(limit)s
"""
BY_KEY_SQL: Final = f"""
SELECT {STORY_FIELDS} FROM (
    SELECT DISTINCT ON (story_key) * FROM news.stories WHERE story_key = ANY(%(keys)s) ORDER BY story_key, version DESC
) s
"""
VERSIONS_SQL: Final = "SELECT at, level FROM news.stories WHERE story_key = %(key)s ORDER BY version LIMIT 200"
ITEMS_SQL: Final = """
WITH linked AS (
    SELECT DISTINCT ON (s.item_id) s.item_id, s.story_key, s.active
      FROM news.item_story s
     WHERE s.item_id IN (SELECT item_id FROM news.item_story WHERE story_key = ANY(%(keys)s))
     ORDER BY s.item_id, s.id DESC
)
SELECT DISTINCT ON (i.url_sha256) i.id, l.story_key, i.canonical_url, i.source_name, i.source_state, i.publish_level, i.author,
       i.published_at, i.published_day_only, i.published_structured, i.seen_at
  FROM linked l JOIN news.items i ON i.id = l.item_id
 WHERE l.story_key = ANY(%(keys)s) AND l.active
 ORDER BY i.url_sha256, i.version DESC
 LIMIT %(limit)s
"""
ENTITIES_SQL: Final = """
SELECT x.item_id, x.entity_type AS type, x.entity_id AS id, x.role, x.method, x.confidence,
       CASE x.entity_type WHEN 'team' THEN t.name WHEN 'player' THEN p.name WHEN 'competition' THEN c.name WHEN 'venue' THEN v.name
                          WHEN 'coach' THEN co.name WHEN 'referee' THEN r.name END AS name
  FROM (SELECT DISTINCT ON (item_id, entity_type, entity_id) item_id, entity_type, entity_id, role, method, confidence, active
          FROM news.item_entities WHERE item_id = ANY(%(ids)s) ORDER BY item_id, entity_type, entity_id, id DESC) x
  LEFT JOIN core.teams t ON x.entity_type = 'team' AND t.id = x.entity_id
  LEFT JOIN core.players p ON x.entity_type = 'player' AND p.id = x.entity_id
  LEFT JOIN core.competitions c ON x.entity_type = 'competition' AND c.id = x.entity_id
  LEFT JOIN core.venues v ON x.entity_type = 'venue' AND v.id = x.entity_id
  LEFT JOIN core.coaches co ON x.entity_type = 'coach' AND co.id = x.entity_id
  LEFT JOIN core.referees r ON x.entity_type = 'referee' AND r.id = x.entity_id
 WHERE x.active
"""
NAMING_SQL: Final = """
SELECT DISTINCT s.story_key
  FROM (SELECT DISTINCT ON (item_id) item_id, story_key, active FROM news.item_story
         WHERE item_id IN (SELECT item_id FROM news.item_entities WHERE entity_type = %(type)s AND entity_id = ANY(%(ids)s) AND at >= %(since)s)
         ORDER BY item_id, id DESC) s
  JOIN (SELECT DISTINCT ON (item_id, entity_type, entity_id) item_id, active FROM news.item_entities
         WHERE entity_type = %(type)s AND entity_id = ANY(%(ids)s) AND at >= %(since)s
         ORDER BY item_id, entity_type, entity_id, id DESC) e ON e.item_id = s.item_id
 WHERE s.active AND e.active
 LIMIT %(limit)s
"""
SEARCH_SQL: Final = f"""
WITH s AS (
    SELECT {STORY_FIELDS} FROM (
        SELECT DISTINCT ON (story_key) * FROM news.stories
         WHERE story_key IN (SELECT story_key FROM news.stories WHERE at >= %(since)s AND at <= %(until)s)
         ORDER BY story_key, version DESC
    ) v WHERE v.status = 'activa'
    LIMIT %(pool)s
), names AS (
    SELECT l.story_key, string_agg(DISTINCT coalesce(t.name, p.name, c.name, e.name_seen, ''), ' ') AS names
      FROM (SELECT DISTINCT ON (item_id) item_id, story_key, active FROM news.item_story
             WHERE story_key IN (SELECT key FROM s) ORDER BY item_id, id DESC) l
      JOIN news.item_entities e ON e.item_id = l.item_id AND e.active
      LEFT JOIN core.teams t ON e.entity_type = 'team' AND t.id = e.entity_id
      LEFT JOIN core.players p ON e.entity_type = 'player' AND p.id = e.entity_id
      LEFT JOIN core.competitions c ON e.entity_type = 'competition' AND c.id = e.entity_id
     WHERE l.active
     GROUP BY l.story_key
), docs AS (
    SELECT s.key, to_tsvector('simple', unaccent(coalesce(s.headline_es, '') || ' ' || coalesce(s.summary_es, '') || ' '
                                                 || coalesce(n.names, ''))) AS doc
      FROM s LEFT JOIN names n ON n.story_key = s.key
)
SELECT key, ts_rank(doc, plainto_tsquery('simple', unaccent(%(q)s))) AS rank FROM docs
 WHERE doc @@ plainto_tsquery('simple', unaccent(%(q)s))
"""


def tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute(TABLES_SQL).fetchone()
    return bool(row and row[0])


def _story(r: Mapping[str, Any]) -> Story:
    return Story(**{k: r[k] for k in Story.__dataclass_fields__})


def recent(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, statuses: Sequence[str] = ("activa",),
           limit: int = MAX_STORIES) -> list[Story]:
    """The stories with a version written between ``since`` and ``until``, by their newest version, newest first."""
    return [_story(r) for r in _rows(conn, RECENT_SQL, {"since": since, "until": until, "statuses": list(statuses),
                                                        "limit": max(1, min(limit, MAX_STORIES))})]


def by_keys(conn: psycopg.Connection[Any], keys: Sequence[str]) -> dict[str, Story]:
    if not keys:
        return {}
    return {r["key"]: _story(r) for r in _rows(conn, BY_KEY_SQL, {"keys": list(keys)})}


def versions(conn: psycopg.Connection[Any], key: str) -> list[Version]:
    return [Version(r["at"], r["level"]) for r in _rows(conn, VERSIONS_SQL, {"key": key})]


def bundles(conn: psycopg.Connection[Any], stories: Iterable[Story], publish: Publish) -> list[Bundle]:
    """Each story with its articles (one per article: its newest linked version; newest publication first) and its entities."""
    stories = list(stories)
    keys = [s.key for s in stories]
    items: dict[str, list[Item]] = {k: [] for k in keys}
    if keys:
        for r in _rows(conn, ITEMS_SQL, {"keys": keys, "limit": MAX_ITEMS}):
            items[r["story_key"]].append(Item(**{k: r[k] for k in Item.__dataclass_fields__}))
    ids = [i.id for xs in items.values() for i in xs]
    entities: dict[int, list[Entity]] = {i: [] for i in ids}
    if ids:
        for r in _rows(conn, ENTITIES_SQL, {"ids": ids}):
            entities[int(r["item_id"])].append(Entity(int(r["item_id"]), str(r["type"]), int(r["id"]), r["name"], str(r["role"]),
                                                      str(r["method"]), Decimal(r["confidence"])))
    out: list[Bundle] = []
    for s in stories:
        xs = sorted(items[s.key], key=lambda i: (i.published_at or i.seen_at, i.id), reverse=True)
        out.append(Bundle(s, xs, [e for i in xs for e in entities.get(i.id, [])], {i.id: publish(i) for i in xs}))
    return out


def naming(conn: psycopg.Connection[Any], entity_type: str, ids: Sequence[int], *, since: datetime, limit: int = MAX_STORIES) -> list[str]:
    """The stories whose articles name one of these entities (linked since ``since``)."""
    if not ids:
        return []
    return [str(r["story_key"]) for r in _rows(conn, NAMING_SQL, {"type": entity_type, "ids": list(ids), "since": since,
                                                                   "limit": max(1, min(limit, MAX_STORIES))})]


def search(conn: psycopg.Connection[Any], q: str, *, since: datetime, until: datetime) -> dict[str, float]:
    """The active stories of the window whose own words or entity names match ``q`` (full text), with their rank."""
    if not normalized(q):
        return {}
    return {str(r["key"]): float(r["rank"]) for r in _rows(conn, SEARCH_SQL, {"q": q, "since": since, "until": until,
                                                                              "pool": MAX_STORIES * 3})}


def normalized(q: str) -> str:
    """The query as it is compared: lower case, no accents, one space between words."""
    return alias_key(q)


__all__ = ["Bundle", "Entity", "Item", "Publish", "Story", "Version", "bundles", "by_keys", "naming", "normalized", "recent", "search",
           "stricter", "tables_exist", "versions"]

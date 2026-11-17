"""Reading the news store (IA-080, AD-G01): what C-06 (AD-G07) will be served from - ``news.items`` and ``news.item_entities``, with
their stories.

Every reader takes the newest row where the store is versioned (an item's newest version, a story's newest version, an item's newest
link to a story, an item's newest link to an entity) and filters by key, date and LIMIT - no reader sweeps a table.

The public side (``public=True``, the default) shows only what may be shown:

* a story that is not ``activa`` (in moderation, or withdrawn at a request) comes back as itself with ``hidden`` and NOTHING of it -
  no text, no items, no entities (C-06 answers ``retirado_por_derechos``; the rows stay);
* an item whose source may publish nothing is left out; the story's own headline and summary are shown only while at least one of its
  items may publish a ``summary`` (otherwise only the links); and an item's level is the STRICTER of the copy written when it was seen and
  the policy in force, when the caller passes one (``effective_publish``): a source whose rights were taken back stops showing at once.

Nothing here reads ``ai.evidence`` (the claims of an item are AD-G07's, through the typed-evidence filter of ``fbi.ai.gates``), writes,
calls a model or the web."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import source_policy
from fbi.news import vocab

MAX_LIMIT: Final = 200


@dataclass(frozen=True, slots=True)
class StoredItem:
    id: int
    url_sha256: str
    version: int
    canonical_url: str
    source_id: str | None
    source_domain: str
    source_name: str
    source_state: str
    store_level: str
    publish_level: str
    ai_reserved: bool
    source_title: str | None
    author: str | None
    lang: str | None
    published_at: datetime | None
    published_day_only: bool
    published_structured: bool
    seen_at: datetime
    event_at: datetime | None
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class StoredStory:
    id: int
    story_key: str
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
    headline_en: str | None
    summary_es: str | None
    summary_en: str | None
    status: str
    status_reason: str | None


@dataclass(frozen=True, slots=True)
class Entity:
    entity_type: str
    entity_id: int
    role: str
    method: str
    confidence: Decimal
    name_seen: str | None


@dataclass(frozen=True, slots=True)
class StoryView:
    """A story as a projection reads it. ``hidden``: not shown (in moderation or withdrawn) - then ``items`` and ``entities`` are
    empty and ``story`` keeps only its key and status for the reader to say why."""

    story: StoredStory
    hidden: bool
    items: list[StoredItem] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)


ITEM_FIELDS: Final = ", ".join(f"i.{f}" for f in StoredItem.__dataclass_fields__)
STORY_FIELDS: Final = ", ".join(StoredStory.__dataclass_fields__)


def _item(row: dict[str, Any]) -> StoredItem:
    return StoredItem(**{k: row[k] for k in StoredItem.__dataclass_fields__})


def _story(row: dict[str, Any]) -> StoredStory:
    return StoredStory(**{k: row[k] for k in StoredStory.__dataclass_fields__})


def _limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def effective_publish(item: StoredItem, policy: source_policy.SourcePolicy | None = None) -> str:
    """What of an item may be shown: the stricter of the copy written when it was seen and, if given, the policy in force. A story's
    own text (``summary``) needs ``summary``; ``link`` shows the medium, the date and the link; ``none`` nothing."""
    level = item.publish_level
    if policy is not None:
        now = source_policy.can_publish(policy.standing(item.canonical_url)).level
        level = min(level, now, key=lambda w: vocab.PUBLISH_ORDER[w])
    return level


def item(conn: psycopg.Connection[Any], item_id: int) -> StoredItem | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {ITEM_FIELDS} FROM news.items i WHERE i.id = %s", (item_id,))
        row = cur.fetchone()
    return None if row is None else _item(row)


def newest_item(conn: psycopg.Connection[Any], url_sha256: str) -> StoredItem | None:
    """The newest version of the article of that identity."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {ITEM_FIELDS} FROM news.items i WHERE i.url_sha256 = %s ORDER BY i.version DESC LIMIT 1", (url_sha256,))
        row = cur.fetchone()
    return None if row is None else _item(row)


def story(conn: psycopg.Connection[Any], story_key: str) -> StoredStory | None:
    """The newest version of a story."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {STORY_FIELDS} FROM news.stories WHERE story_key = %s ORDER BY version DESC LIMIT 1", (story_key,))
        row = cur.fetchone()
    return None if row is None else _story(row)


STORY_ITEMS_SQL: Final = f"""
    WITH linked AS (
        SELECT DISTINCT ON (s.item_id) s.item_id, s.story_key, s.active
          FROM news.item_story s
         WHERE s.item_id IN (SELECT item_id FROM news.item_story WHERE story_key = %(key)s)
         ORDER BY s.item_id, s.id DESC
    )
    SELECT DISTINCT ON (i.url_sha256) {ITEM_FIELDS}
      FROM linked l JOIN news.items i ON i.id = l.item_id
     WHERE l.story_key = %(key)s AND l.active
     ORDER BY i.url_sha256, i.version DESC
     LIMIT %(limit)s
"""


def story_items(conn: psycopg.Connection[Any], story_key: str, *, public: bool = True,
                policy: source_policy.SourcePolicy | None = None, limit: int = 50) -> list[StoredItem]:
    """The items whose newest link puts them in this story (one per article: its newest linked version), newest publication first.
    Public: without the ones that may publish nothing."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STORY_ITEMS_SQL, {"key": story_key, "limit": _limit(limit)})
        items = [_item(r) for r in cur.fetchall()]
    if public:
        items = [i for i in items if effective_publish(i, policy) != "none"]
    return sorted(items, key=lambda i: (i.published_at or i.seen_at, i.id), reverse=True)


ENTITIES_SQL: Final = """
    SELECT DISTINCT ON (item_id, entity_type, entity_id) item_id, entity_type, entity_id, role, method, confidence, name_seen, active
      FROM news.item_entities
     WHERE item_id = ANY(%(ids)s)
     ORDER BY item_id, entity_type, entity_id, id DESC
"""


def item_entities(conn: psycopg.Connection[Any], item_ids: list[int]) -> dict[int, list[Entity]]:
    """Who each item names, by the newest row of each item and entity (a link taken back is left out)."""
    if not item_ids:
        return {}
    out: dict[int, list[Entity]] = {i: [] for i in item_ids}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ENTITIES_SQL, {"ids": list(item_ids)})
        for r in cur.fetchall():
            if r["active"]:
                out[int(r["item_id"])].append(Entity(r["entity_type"], int(r["entity_id"]), r["role"], r["method"],
                                                     Decimal(r["confidence"]), r["name_seen"]))
    return out


def merged_entities(per_item: dict[int, list[Entity]]) -> list[Entity]:
    """The entities of a story: one per entity, protagonista over mencionado, then the highest confidence; ordered so."""
    best: dict[tuple[str, int], Entity] = {}
    for links in per_item.values():
        for e in links:
            key = (e.entity_type, e.entity_id)
            old = best.get(key)
            if old is None or (e.role == "protagonista", e.confidence) > (old.role == "protagonista", old.confidence):
                best[key] = e
    return sorted(best.values(), key=lambda e: (e.role != "protagonista", -e.confidence, e.entity_type, e.entity_id))


def story_view(conn: psycopg.Connection[Any], story_key: str, *, public: bool = True,
               policy: source_policy.SourcePolicy | None = None) -> StoryView | None:
    """A story with its items and entities, as C-06 reads it; None when there is no such story."""
    found = story(conn, story_key)
    if found is None:
        return None
    if public and found.status != "activa":
        bare = StoredStory(found.id, found.story_key, found.version, found.at, found.first_seen_at, None, None, None, None, None, None,
                           None, None, None, None, None, found.status, None)
        return StoryView(bare, hidden=True)
    items = story_items(conn, story_key, public=public, policy=policy)
    entities = merged_entities(item_entities(conn, [i.id for i in items]))
    if public and not any(effective_publish(i, policy) == "summary" for i in items):
        # PrediGol's own text stands on the sources that allow it: with none left (rights taken back), only the links are shown.
        found = replace(found, headline_es=None, headline_en=None, summary_es=None, summary_en=None)
    return StoryView(found, hidden=False, items=items, entities=entities)


ENTITY_ITEMS_SQL: Final = f"""
    WITH named AS (
        SELECT DISTINCT ON (item_id) item_id, active
          FROM news.item_entities
         WHERE entity_type = %(type)s AND entity_id = %(id)s AND at >= %(since)s
         ORDER BY item_id, id DESC
    )
    SELECT {ITEM_FIELDS} FROM named n JOIN news.items i ON i.id = n.item_id
     WHERE n.active
     ORDER BY coalesce(i.published_at, i.seen_at) DESC, i.id DESC
     LIMIT %(limit)s
"""


def items_for_entity(conn: psycopg.Connection[Any], entity_type: vocab.EntityType, entity_id: int, *, since: datetime,
                     public: bool = True, policy: source_policy.SourcePolicy | None = None, limit: int = 50) -> list[StoredItem]:
    """The items that name an entity (a team, a player ...), linked since ``since``, newest first - the filter of C-06 by team or
    player."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ENTITY_ITEMS_SQL, {"type": entity_type, "id": entity_id, "since": since, "limit": _limit(limit)})
        items = [_item(r) for r in cur.fetchall()]
    return [i for i in items if not public or effective_publish(i, policy) != "none"]


RECENT_SQL: Final = f"""
    SELECT {STORY_FIELDS} FROM (
        SELECT DISTINCT ON (story_key) * FROM news.stories
         WHERE story_key IN (SELECT story_key FROM news.stories WHERE at >= %(since)s)
         ORDER BY story_key, version DESC
    ) s
     WHERE s.status = ANY(%(statuses)s)
     ORDER BY s.at DESC, s.id DESC
     LIMIT %(limit)s
"""


def recent_stories(conn: psycopg.Connection[Any], *, since: datetime, public: bool = True, limit: int = 50) -> list[StoredStory]:
    """The stories with a version written since ``since``, by their newest version, newest first. Public: only ``activa``."""
    statuses = ["activa"] if public else list(vocab.STATUSES)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(RECENT_SQL, {"since": since, "statuses": statuses, "limit": _limit(limit)})
        return [_story(r) for r in cur.fetchall()]


__all__ = ["Entity", "StoredItem", "StoredStory", "StoryView", "effective_publish", "item", "item_entities", "items_for_entity",
           "merged_entities", "newest_item", "recent_stories", "story", "story_items", "story_view"]

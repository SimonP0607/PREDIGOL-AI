"""Writing the news store (IA-080, AD-G01): idempotent, deduplicated, append-only.

Every write is a NEW ROW or nothing - the five tables of migration 0146 refuse UPDATE and DELETE:

* ``write_item``: an article. Its identity is the sha256 of its canonical URL (``fbi.news.canonical``); the same content of the same
  URL is ``unchanged`` (nothing written), a new content is version n+1. The source policy of IA-063 decides first, and its answer is
  COPIED into the row: a source the policy lets keep nothing (``can_store`` = ``none``: not in the directory, excluded, blocked,
  unchecked) is never stored - ``refused`` - and without a registry nothing is (closed on failure). There is no parameter for an
  article's text or picture: the text given for the fingerprint is hashed and dropped.
* ``write_feed``: a feed or sitemap of a source, versioned the same way.
* ``write_story`` / ``revise_story``: a story's version - a version equal to the newest one is ``unchanged``.
* ``link_item_story`` / ``link_entity``: which story an item is in, who it names; a link equal to the newest one is ``unchanged``.

Writes of the same key are serialised by a transaction-scoped advisory lock, so two workers seeing the same article write one row.
Nothing here reads a key, calls a model or the web, or writes ``ai.evidence``: the claims of an item get ``item_id`` from their own
writer, when they are inserted (AD-G02). Nothing fills the store in production yet."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.ai import source_policy
from fbi.news import canonical, vocab

Outcome = Literal["created", "new_version", "unchanged", "refused"]
LOCK_SPACE: Final = 0x4E455753
"""``NEWS``: the first key of the advisory locks of this module (the second is the hash of the item's, feed's or story's key)."""
WRITER_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._:+-]{1,79}$")
LANG_RE: Final = re.compile(r"^[a-z]{2,3}$")
STORY_KEY_RE: Final = re.compile(r"^st-[a-z0-9][a-z0-9-]{3,62}$")


@dataclass(frozen=True, slots=True)
class Written:
    outcome: Outcome
    id: int | None = None
    version: int | None = None
    reason: str | None = None

    @property
    def wrote(self) -> bool:
        return self.outcome in ("created", "new_version")


@dataclass(frozen=True, slots=True)
class Article:
    """An article as the ingestion saw it. ``fingerprint_text`` is what it read (a body only from a source that allows extraction,
    otherwise the title and date): it is hashed, never stored."""

    url: str
    source_name: str
    fingerprint_text: str
    seen_at: datetime
    found_via: vocab.FoundVia
    written_by: str
    source_title: str | None = None
    author: str | None = None
    lang: str | None = None
    published_at: datetime | None = None
    published_day_only: bool = False
    published_structured: bool = False
    event_at: datetime | None = None
    valid_until: datetime | None = None
    feed_id: int | None = None
    simhash: int | None = None


@dataclass(frozen=True, slots=True)
class Feed:
    url: str
    kind: vocab.FeedKind
    source_id: str
    source_domain: str
    at: datetime
    added_by: Literal["loader", "owner", "system"]
    lang: str | None = None
    country: str | None = None
    active: bool = True
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Story:
    """One version of a story. ``at`` is when this version is written; the rest is its content."""

    story_key: str
    at: datetime
    first_seen_at: datetime
    written_by: str
    decided_by: vocab.Decider = "system"
    event_at: datetime | None = None
    valid_until: datetime | None = None
    claim_type: str | None = None
    category: vocab.Category | None = None
    level: vocab.Level | None = None
    lang: str | None = None
    country: str | None = None
    headline_es: str | None = None
    headline_en: str | None = None
    summary_es: str | None = None
    summary_en: str | None = None
    text_version: str | None = None
    status: vocab.Status = "activa"
    status_reason: str | None = None


STORY_CONTENT: Final = tuple(f.name for f in fields(Story) if f.name not in ("story_key", "at", "written_by", "decided_by"))
"""What makes two versions of a story different: everything but who wrote it and when."""


@dataclass(frozen=True, slots=True)
class EntityLink:
    entity_type: vocab.EntityType
    entity_id: int
    role: vocab.Role
    method: vocab.LinkMethod
    confidence: float | Decimal
    linker_version: str
    at: datetime
    name_seen: str | None = None
    active: bool = True


def _aware(name: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must carry its time zone")


def _writer(name: str, value: str) -> None:
    if not WRITER_RE.match(value or ""):
        raise ValueError(f"{name} is not a version word: {value!r}")


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    clean = " ".join(text.split())
    return clean[:limit] or None


def _lang(value: str | None) -> str | None:
    word = (value or "").strip().lower()
    return word if LANG_RE.match(word) else None


def _lock(cur: psycopg.Cursor[Any], key: str) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (LOCK_SPACE, key))


def story_key_for(seed: str) -> str:
    """A story key that is the same for the same seed (the first item's url_sha256, say): writing a story twice finds it."""
    return "st-" + canonical.sha256_hex(seed)[:24]


# ── items ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

ITEM_COLUMNS: Final = ("url_sha256", "version", "previous_id", "url", "canonical_url", "canon_version", "content_sha256",
                       "fingerprint_version", "simhash", "feed_id", "found_via", "source_id", "source_domain", "source_name",
                       "source_state", "ai_reserved", "store_level", "publish_level", "registry_version", "policy_version",
                       "source_title", "author", "lang", "published_at", "published_day_only", "published_structured", "seen_at",
                       "event_at", "valid_until", "written_by")
INSERT_ITEM: Final = (f"INSERT INTO news.items ({', '.join(ITEM_COLUMNS)}) VALUES ({', '.join(['%s'] * len(ITEM_COLUMNS))}) "
                      "RETURNING id")


def _refusal(article: Article) -> str | None:
    """Why an article cannot be stored as given (what the database would refuse), or None."""
    for name in ("seen_at", "published_at", "event_at", "valid_until"):
        _aware(name, getattr(article, name))
    _writer("written_by", article.written_by)
    if article.found_via not in vocab.FOUND_VIA:
        return f"invalid:found_via:{article.found_via}"
    if not (article.source_name or "").strip():
        return "invalid:source_name"
    if article.published_at is not None and article.published_at > article.seen_at:
        return "invalid:published_after_seen"
    if article.published_at is None and (article.published_day_only or article.published_structured):
        return "invalid:published_flags_without_date"
    if article.valid_until is not None and article.event_at is not None and article.valid_until < article.event_at:
        return "invalid:valid_until_before_event"
    if len(article.url.strip()) > 2000:
        return "invalid:url_too_long"
    return None


def write_item(conn: psycopg.Connection[Any], article: Article, policy: source_policy.SourcePolicy | None) -> Written:
    """Store an article once: ``created`` (version 1), ``new_version`` (the URL had another content), ``unchanged`` (this content of
    this URL is already there: its row) or ``refused`` (the policy lets keep nothing, the registry is unavailable, or the article is
    not valid - the reason says which). Inside a transaction of its own (a savepoint when the caller has one)."""
    bad = _refusal(article)
    if bad:
        return Written("refused", reason=bad)
    try:
        canon = canonical.canonical_url(article.url)
        content = canonical.fingerprint(article.fingerprint_text)
    except ValueError as exc:
        return Written("refused", reason=f"invalid:{type(exc).__name__}")
    if len(canon) > 2000:
        return Written("refused", reason="invalid:url_too_long")
    if policy is None:
        return Written("refused", reason="registry_unavailable")
    standing = policy.standing(article.url)
    store = source_policy.can_store(standing)
    if store == "none":
        return Written("refused", reason=f"store:none:{source_policy.can_extract(standing).reason}")
    publish = source_policy.can_publish(standing).level
    domain = standing.domain or standing.host
    if domain is None:
        return Written("refused", reason="invalid:host")
    key = canonical.sha256_hex(canon)
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        _lock(cur, key)
        cur.execute("SELECT id, version, content_sha256 FROM news.items WHERE url_sha256 = %s ORDER BY version DESC", (key,))
        rows = cur.fetchall()
        for r in rows:
            if r["content_sha256"] == content:
                return Written("unchanged", int(r["id"]), int(r["version"]))
        previous = (int(rows[0]["id"]), int(rows[0]["version"])) if rows else None
        values = (key, 1 if previous is None else previous[1] + 1, None if previous is None else previous[0], article.url.strip(), canon,
                  canonical.CANON_VERSION, content, canonical.FINGERPRINT_VERSION, article.simhash, article.feed_id, article.found_via,
                  standing.source_id, domain, _clip(article.source_name, 200), standing.state, standing.ai_reserved, store, publish,
                  policy.version[:200], source_policy.VERSION, _clip(article.source_title, 300), _clip(article.author, 200),
                  _lang(article.lang), article.published_at, article.published_day_only, article.published_structured, article.seen_at,
                  article.event_at, article.valid_until, article.written_by)
        cur.execute(INSERT_ITEM, values)
        new = cur.fetchone()
        assert new is not None
        return Written("created" if previous is None else "new_version", int(new["id"]), 1 if previous is None else previous[1] + 1)


# ── feeds ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

FEED_CONTENT: Final = ("url", "kind", "source_id", "source_domain", "lang", "country", "active")


def write_feed(conn: psycopg.Connection[Any], feed: Feed) -> Written:
    """A feed of a source: ``created``, ``new_version`` (anything of it changed, ``active`` included) or ``unchanged``."""
    _aware("at", feed.at)
    if feed.kind not in vocab.FEED_KINDS:
        raise ValueError(f"unknown feed kind {feed.kind!r}")
    url = feed.url.strip()
    key = canonical.sha256_hex(url)
    wanted = (url, feed.kind, feed.source_id, feed.source_domain, _lang(feed.lang), feed.country, feed.active)
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        _lock(cur, key)
        cur.execute(f"SELECT id, version, {', '.join(FEED_CONTENT)} FROM news.feeds WHERE url_sha256 = %s ORDER BY version DESC LIMIT 1",
                    (key,))
        row = cur.fetchone()
        if row is not None and tuple(row[c] for c in FEED_CONTENT) == wanted:
            return Written("unchanged", int(row["id"]), int(row["version"]))
        version = 1 if row is None else int(row["version"]) + 1
        cur.execute("INSERT INTO news.feeds (url_sha256, version, previous_id, url, kind, source_id, source_domain, lang, country, active, "
                    "at, added_by, reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (key, version, None if row is None else row["id"], *wanted, feed.at, feed.added_by, feed.reason))
        new = cur.fetchone()
        assert new is not None
        return Written("created" if row is None else "new_version", int(new["id"]), version)


# ── stories ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _check_story(story: Story) -> None:
    if not STORY_KEY_RE.match(story.story_key):
        raise ValueError(f"not a story key: {story.story_key!r}")
    for name in ("at", "first_seen_at", "event_at", "valid_until"):
        _aware(name, getattr(story, name))
    _writer("written_by", story.written_by)
    if story.text_version is not None:
        _writer("text_version", story.text_version)
    if story.status == "retirada" and story.decided_by != "owner":
        raise ValueError("only the owner withdraws a story")
    if story.status != "activa" and not (story.status_reason or "").strip():
        raise ValueError("a story that is not activa says why")


def newest_story_row(cur: psycopg.Cursor[dict[str, Any]], story_key: str) -> dict[str, Any] | None:
    cur.execute("SELECT * FROM news.stories WHERE story_key = %s ORDER BY version DESC LIMIT 1", (story_key,))
    return cur.fetchone()


def write_story(conn: psycopg.Connection[Any], story: Story) -> Written:
    """A version of a story: ``created``, ``new_version`` (its content differs from the newest) or ``unchanged``."""
    _check_story(story)
    wanted = {name: getattr(story, name) for name in STORY_CONTENT}
    wanted["lang"] = _lang(story.lang)
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        _lock(cur, story.story_key)
        newest = newest_story_row(cur, story.story_key)
        if newest is not None and all(newest[k] == v for k, v in wanted.items()):
            return Written("unchanged", int(newest["id"]), int(newest["version"]))
        version = 1 if newest is None else int(newest["version"]) + 1
        columns = ("story_key", "version", "previous_id", "at", "written_by", "decided_by", *STORY_CONTENT)
        values = (story.story_key, version, None if newest is None else newest["id"], story.at, story.written_by, story.decided_by,
                  *wanted.values())
        cur.execute(f"INSERT INTO news.stories ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id", values)
        new = cur.fetchone()
        assert new is not None
        return Written("created" if newest is None else "new_version", int(new["id"]), version)


def revise_story(conn: psycopg.Connection[Any], story_key: str, *, at: datetime, written_by: str, decided_by: vocab.Decider = "system",
                 **changes: Any) -> Written:
    """The newest version of a story with ``changes`` applied, as a new version (AD-G03 classifies, AD-G04 writes the text, AD-G05
    moderates). ``refused`` when the story does not exist; ``unchanged`` when the changes change nothing."""
    unknown = set(changes) - set(STORY_CONTENT)
    if unknown:
        raise ValueError(f"not a field of a story: {sorted(unknown)}")
    with conn.cursor(row_factory=dict_row) as cur:
        newest = newest_story_row(cur, story_key)
    if newest is None:
        return Written("refused", reason="no_such_story")
    base = Story(story_key=story_key, at=at, written_by=written_by, decided_by=decided_by,
                 **{name: newest[name] for name in STORY_CONTENT})
    return write_story(conn, replace(base, **changes))


# ── links ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def link_item_story(conn: psycopg.Connection[Any], item_id: int, story_key: str, *, at: datetime, method: vocab.GroupMethod,
                    grouper_version: str, score: float | Decimal | None = None, decided_by: vocab.Decider = "system",
                    active: bool = True) -> Written:
    """Put an item in a story (or, ``active=False``, take it out of the one it is in). ``unchanged`` when its newest link already says
    so; ``refused`` when the story does not exist."""
    _aware("at", at)
    _writer("grouper_version", grouper_version)
    if method not in vocab.GROUP_METHODS:
        raise ValueError(f"unknown grouping method {method!r}")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        _lock(cur, f"item:{item_id}")
        newest = newest_story_row(cur, story_key)
        if newest is None:
            return Written("refused", reason="no_such_story")
        cur.execute("SELECT id, story_key, active FROM news.item_story WHERE item_id = %s ORDER BY id DESC LIMIT 1", (item_id,))
        row = cur.fetchone()
        if row is not None and row["story_key"] == story_key and bool(row["active"]) == active:
            return Written("unchanged", int(row["id"]))
        if row is None and not active:
            return Written("unchanged")
        cur.execute("INSERT INTO news.item_story (item_id, story_id, story_key, at, active, method, score, grouper_version, decided_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (item_id, newest["id"], story_key, at, active, method, score, grouper_version, decided_by))
        new = cur.fetchone()
        assert new is not None
        return Written("created" if row is None else "new_version", int(new["id"]))


def _same_link(row: Mapping[str, Any], link: EntityLink) -> bool:
    return (row["role"] == link.role and row["method"] == link.method and bool(row["active"]) == link.active
            and Decimal(str(row["confidence"])) == Decimal(str(link.confidence)).quantize(Decimal("0.001"))
            and row["name_seen"] == _clip(link.name_seen, 120))


def link_entity(conn: psycopg.Connection[Any], item_id: int, link: EntityLink) -> Written:
    """Record that an item names an entity (or, ``active=False``, that it does not after all). ``unchanged`` when the newest row of
    the item and entity says the same (a new linker that agrees writes nothing)."""
    _aware("at", link.at)
    _writer("linker_version", link.linker_version)
    if link.entity_type not in vocab.ENTITY_TYPES or link.role not in vocab.ROLES or link.method not in vocab.LINK_METHODS:
        raise ValueError(f"not a link of the vocabulary: {link}")
    if link.entity_id < 1 or not 0 <= float(link.confidence) <= 1:
        raise ValueError(f"not a valid link: {link}")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        _lock(cur, f"item:{item_id}")
        cur.execute("SELECT id, role, method, confidence, active, name_seen FROM news.item_entities "
                    "WHERE item_id = %s AND entity_type = %s AND entity_id = %s ORDER BY id DESC LIMIT 1",
                    (item_id, link.entity_type, link.entity_id))
        row = cur.fetchone()
        if row is not None and _same_link(row, link):
            return Written("unchanged", int(row["id"]))
        if row is None and not link.active:
            return Written("unchanged")
        cur.execute("INSERT INTO news.item_entities (item_id, entity_type, entity_id, name_seen, role, method, confidence, active, "
                    "linker_version, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (item_id, link.entity_type, link.entity_id, _clip(link.name_seen, 120), link.role, link.method,
                     Decimal(str(link.confidence)).quantize(Decimal("0.001")), link.active, link.linker_version, link.at))
        new = cur.fetchone()
        assert new is not None
        return Written("created" if row is None else "new_version", int(new["id"]))


__all__ = ["Article", "EntityLink", "Feed", "Story", "Written", "link_entity", "link_item_story", "revise_story", "story_key_for",
           "write_feed", "write_item", "write_story"]

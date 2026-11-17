"""Reading a feed (IA-085, plan piece AD-C03): RSS 2.0, Atom, a sitemap, a Google News sitemap and a sitemap index - only what each
entry says of itself: its address, its title, its date and its author. ``feeds-v1``.

What is NOT read: the description, the content, the enclosures and the pictures of an entry (the store keeps no text or picture of a
third party - migration 0146), and nothing outside the XML.

Defensive by design: the bytes come from outside. A document with a ``DOCTYPE`` or an ``ENTITY`` is refused before it is parsed (no
entity is ever expanded), a document over ``MAX_BYTES`` is refused, at most ``MAX_ENTRIES`` entries are read, every text is cut to its
column's size, and an entry without an http(s) address is dropped. A date is ``structured`` only when the feed gave it in a field for
it (``pubDate``, ``updated``, ``lastmod``, ``news:publication_date``); a date without a time is ``day_only``."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final, Literal

VERSION: Final = "feeds-v1"
MAX_BYTES: Final = 5_000_000
MAX_ENTRIES: Final = 500
Kind = Literal["rss", "atom", "sitemap", "news_sitemap", "sitemap_index"]

_DANGEROUS = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_SPACE = re.compile(r"\s+")


class FeedError(ValueError):
    """Bytes that are not a feed this reader accepts (the reason is the message)."""


@dataclass(frozen=True, slots=True)
class Entry:
    url: str
    title: str | None
    published_at: datetime | None
    day_only: bool
    structured: bool
    author: str | None = None
    lang: str | None = None


@dataclass(frozen=True, slots=True)
class Parsed:
    kind: Kind
    entries: tuple[Entry, ...]
    children: tuple[str, ...] = ()
    """The sitemaps a sitemap index lists (newest first when they say when)."""
    truncated: bool = False


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _text(el: ET.Element | None, limit: int) -> str | None:
    if el is None:
        return None
    raw = "".join(el.itertext())
    clean = _SPACE.sub(" ", raw).strip()
    return clean[:limit] or None


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _descendant(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el.iter():
        if c is not el and _local(c.tag) in names:
            return c
    return None


def parse_date(raw: str | None) -> tuple[datetime | None, bool]:
    """(the moment, whether only the day was given). RFC 822 (RSS) or ISO 8601 (Atom, sitemaps); a moment without a zone is UTC."""
    text = (raw or "").strip()
    if not text:
        return None, False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.fromisoformat(text).replace(tzinfo=UTC), True
        except ValueError:
            return None, False
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None, False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC), False


def _http(url: str | None) -> str | None:
    u = (url or "").strip()
    return u[:2000] if u.lower().startswith(("http://", "https://")) else None


def _entry(url: str | None, title: str | None, date_raw: str | None, author: str | None, lang: str | None = None) -> Entry | None:
    link = _http(url)
    if link is None:
        return None
    when, day_only = parse_date(date_raw)
    return Entry(link, title, when, day_only, when is not None, author, lang)


def parse(data: bytes) -> Parsed:
    """The entries of a feed. Raises ``FeedError`` for what is not one (or is too big, or declares entities)."""
    if len(data) > MAX_BYTES:
        raise FeedError(f"too_big:{len(data)}")
    if _DANGEROUS.search(data[:4096]) or _DANGEROUS.search(data):
        raise FeedError("doctype_or_entity")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError(f"not_xml:{str(exc)[:80]}") from exc
    top = _local(root.tag)
    entries: list[Entry] = []
    children: list[tuple[datetime | None, str]] = []
    truncated = False
    kind: Kind
    if top == "rss" or top == "rdf":
        kind = "rss"
        found = _child(root, "channel")
        channel = root if found is None else found
        lang = _text(_child(channel, "language"), 12)
        items = [c for c in root.iter() if _local(c.tag) == "item"]
        for item in items:
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
            link = _text(_child(item, "link"), 2000) or _guid_link(item)
            e = _entry(link, _text(_child(item, "title"), 300), _text(_child(item, "pubdate", "date"), 64),
                       _text(_child(item, "creator", "author"), 200), lang)
            if e is not None:
                entries.append(e)
    elif top == "feed":
        kind = "atom"
        for item in (c for c in root if _local(c.tag) == "entry"):
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
            link = None
            for c in item:
                if _local(c.tag) == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                    link = c.get("href")
                    break
            author = _child(item, "author")
            e = _entry(link, _text(_child(item, "title"), 300), _text(_child(item, "published", "updated"), 64),
                       None if author is None else _text(_child(author, "name"), 200))
            if e is not None:
                entries.append(e)
    elif top == "urlset":
        news = any(_descendant(u, "news") is not None for u in list(root)[:20])
        kind = "news_sitemap" if news else "sitemap"
        for u in (c for c in root if _local(c.tag) == "url"):
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
            item_news = _descendant(u, "news")
            title = None if item_news is None else _text(_descendant(item_news, "title"), 300)
            when = None if item_news is None else _text(_descendant(item_news, "publication_date"), 64)
            lang = None if item_news is None else _text(_descendant(item_news, "language"), 12)
            e = _entry(_text(_child(u, "loc"), 2000), title, when or _text(_child(u, "lastmod"), 64), None, lang)
            if e is not None:
                entries.append(e)
    elif top == "sitemapindex":
        kind = "sitemap_index"
        for s in (c for c in root if _local(c.tag) == "sitemap"):
            loc = _http(_text(_child(s, "loc"), 2000))
            if loc is not None:
                children.append((parse_date(_text(_child(s, "lastmod"), 64))[0], loc))
        children.sort(key=lambda c: c[0] or datetime.min.replace(tzinfo=UTC), reverse=True)
    else:
        raise FeedError(f"unknown_root:{top[:40]}")
    return Parsed(kind, tuple(entries), tuple(u for _, u in children[:MAX_ENTRIES]), truncated)


def _guid_link(item: ET.Element) -> str | None:
    guid = _child(item, "guid")
    if guid is None or guid.get("isPermaLink", "true").lower() == "false":
        return None
    return _text(guid, 2000)


__all__ = ["MAX_BYTES", "MAX_ENTRIES", "VERSION", "Entry", "FeedError", "Parsed", "parse", "parse_date"]

"""The research cache: a search, a page or a story answered once, reused until it expires.

Keys are scoped (fixture, team, player, url, story, search). TTLs are short for what changes before a
match (a search: hours) and long for what does not (a page already read: days). A cache row is not a
record - what a page taught is stored as evidence (``ai.evidence``) - so refreshing it is an overwrite.

Research v2 (plan, phase 2) adds one scope, ``entity``: ONE answer per entity and topic (a team, its availability), shared by every match
and every agent that needs it, and a URL key that no longer names a match. The keys, the freshness of each topic and the read-through
live at the end of this module; the functions above are the same for v1 and v2.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.ai import research

SCOPES = frozenset({"fixture", "team", "player", "url", "story", "search", "entity"})


def get(conn: psycopg.Connection[Any], scope: str, key: str, *, at: datetime, max_age: timedelta | None = None) -> dict[str, Any] | None:
    """The answer in the cache if it has not expired. ``max_age`` (research v2) adds a second judgement, made NOW: the row must also have
    been fetched less than that long ago, whatever its own expiry says. One statement, so a reuse is counted only when it is a reuse."""
    if scope not in SCOPES:
        raise ValueError(f"unknown cache scope {scope!r}")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.research_cache SET hits = hits + 1, last_hit_at = %(at)s WHERE scope = %(scope)s AND key = %(key)s "
                    "AND expires_at > %(at)s AND (%(oldest)s::timestamptz IS NULL OR fetched_at > %(oldest)s::timestamptz) RETURNING payload",
                    {"at": at, "scope": scope, "key": key[:500], "oldest": None if max_age is None else at - max_age})
        row = cur.fetchone()
    return None if row is None else dict(row[0])


def put(conn: psycopg.Connection[Any], scope: str, key: str, payload: dict[str, Any], *, at: datetime,
        ttl: timedelta) -> None:
    if scope not in SCOPES:
        raise ValueError(f"unknown cache scope {scope!r}")
    body = json.dumps(payload, sort_keys=True, default=str)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (scope, key) DO UPDATE SET fetched_at = EXCLUDED.fetched_at, "
                    "expires_at = EXCLUDED.expires_at, content_hash = EXCLUDED.content_hash, payload = EXCLUDED.payload",
                    (scope, key[:500], at, at + ttl, hashlib.sha256(body.encode()).hexdigest(), Jsonb(json.loads(body))))


def purge_expired(conn: psycopg.Connection[Any], *, at: datetime, keep: timedelta = timedelta(days=14)) -> int:
    """Expired cache rows older than ``keep`` (a cache, not history)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("DELETE FROM ai.research_cache WHERE expires_at < %s", (at - keep,))
        return max(cur.rowcount, 0)


# ── research v2: one answer per entity and topic ────────────────────────────────────────────────────────────────────

KEY_VERSION: Final = "rk-v2"
"""Every key of v2 starts with it. A key of v1 is the hash of a query (forty hexadecimal characters) or ``<fixture>:<url>``, so the two
generations can share the table for the week they run side by side and neither reads a row of the other."""

ENTITY_KINDS: Final = ("TEAM", "PLAYER", "COACH", "REFEREE", "MATCH", "COMPETITION")
"""The subjects a claim can be about (``claim-v1``'s ``SubjectKind``; a test holds the two lists together)."""

LATE_WINDOW: Final = timedelta(hours=12)
EARLY_TTL: Final = timedelta(hours=24)
LATE_TTL: Final = timedelta(hours=4)
FRESHNESS: Final[dict[str, tuple[timedelta, timedelta]]] = dict.fromkeys(research.BY_KEY, (EARLY_TTL, LATE_TTL))
"""How long an answer on each topic is reused: (while the nearest kick-off is farther than ``LATE_WINDOW``, inside it). **Decision of mine,
declared:** v2 starts with exactly the freshness v1 has (a day, and four hours in the last twelve), for every topic, so that the week of
comparison measures the change of key and not a change of freshness; a topic gets its own number when that week gives evidence for one.
A test holds these to the constants of ``fbi.ai.collectors``."""

TRACKING = frozenset({"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid", "_ga"})
"""Query parameters that name who sent the reader and not what the page is."""


def entity_key(kind: str, entity_id: int, topic: str) -> str:
    """``rk-v2:team:42:availability`` - the key of what is known about an entity on a topic, whatever match asked."""
    if kind not in ENTITY_KINDS:
        raise ValueError(f"unknown entity kind {kind!r}")
    if topic not in research.BY_KEY:
        raise ValueError(f"unknown research topic {topic!r}")
    if isinstance(entity_id, bool) or not isinstance(entity_id, int) or entity_id <= 0:
        raise ValueError(f"an entity id is a positive integer, not {entity_id!r}")
    return f"{KEY_VERSION}:{kind.lower()}:{entity_id}:{topic}"


def canonical_url(url: str) -> str:
    """The address of a page with what does not make it another page taken away: scheme and host in lower case, no default port, no
    fragment, no tracking parameter, the rest of the query in order, no trailing slash. Only ``http`` and ``https`` (evidence needs that)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not a web address: {url!r}")
    scheme, host = parts.scheme, parts.hostname  # urlsplit already writes both in lower case
    port = parts.port
    netloc = host if port in (None, 80 if scheme == "http" else 443) else f"{host}:{port}"
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in TRACKING)
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), urlencode(query), ""))


def url_key(url: str) -> str:
    """A page read for one match is not read again for another: the key no longer carries the match."""
    return f"{KEY_VERSION}:url:{hashlib.sha256(canonical_url(url).encode()).hexdigest()[:40]}"


def ttl_for(topic: str, *, nearest_kickoff: datetime | None, at: datetime) -> timedelta:
    """How long an answer on ``topic`` found at ``at`` is reused. The nearest kick-off of the entity decides: a team with a match tomorrow and
    another in three days is read as a team with a match tomorrow."""
    early, late = FRESHNESS[topic]
    return late if nearest_kickoff is not None and nearest_kickoff - at <= LATE_WINDOW else early


def fresh_until(topic: str, *, retrieved_at: datetime, nearest_kickoff: datetime | None) -> datetime:
    """The moment until which what was retrieved at ``retrieved_at`` is reused without asking again (``ai.evidence.fresh_until``)."""
    return retrieved_at + ttl_for(topic, nearest_kickoff=nearest_kickoff, at=retrieved_at)


def fresh(conn: psycopg.Connection[Any], kind: str, entity_id: int, topic: str, *, at: datetime, nearest_kickoff: datetime | None
          ) -> dict[str, Any] | None:
    """What is known about an entity on a topic, if it is still fresh for the question asked NOW (the shorter of the answer's own expiry and
    the freshness of the topic for the kick-off the asker faces). A reuse is counted (``ai.research_cache.hits``) only when it is one."""
    return get(conn, "entity", entity_key(kind, entity_id, topic), at=at, max_age=ttl_for(topic, nearest_kickoff=nearest_kickoff, at=at))


def remember(conn: psycopg.Connection[Any], kind: str, entity_id: int, topic: str, answer: dict[str, Any], *, at: datetime,
             nearest_kickoff: datetime | None) -> None:
    """Keep what was found about an entity on a topic, for as long as the topic's freshness says (``ttl_for``)."""
    put(conn, "entity", entity_key(kind, entity_id, topic), answer, at=at, ttl=ttl_for(topic, nearest_kickoff=nearest_kickoff, at=at))


def through(conn: psycopg.Connection[Any], kind: str, entity_id: int, topic: str, search: Callable[[], dict[str, Any]], *, at: datetime,
            nearest_kickoff: datetime | None) -> tuple[dict[str, Any], bool]:
    """Read-through: the answer on the topic if one is still fresh, and otherwise ``search()`` once, kept. Returns the answer and whether
    it was searched. Two matches of the same team that ask inside the freshness of the topic search once, the second one reads.

    Fresh is judged at the moment of asking, by the kick-off the asker faces NOW and not only by the one the answer was found under: what
    was found a day before the match is not fresh for a pass that reads inside the last twelve hours (the plan's trigger: a ``pre`` pass whose
    last search is more than four hours old searches again). The answer's own expiry still holds, so the shorter of the two rules."""
    cached = fresh(conn, kind, entity_id, topic, at=at, nearest_kickoff=nearest_kickoff)
    if cached is not None:
        return cached, False
    found = search()
    remember(conn, kind, entity_id, topic, found, at=at, nearest_kickoff=nearest_kickoff)
    return found, True

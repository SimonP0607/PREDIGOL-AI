"""The one place the news pipeline reads ``ai.evidence`` (IA-099 to IA-101): read-only, research v2's claims only while it is on.

* ``claim_types`` - the type of claim of each article, from the claims its extractors wrote with ``item_id`` (``fbi.news.pipeline``);
* ``facts_of``    - the typed facts of the ELIGIBLE articles of a story, the only thing PrediGol's own text may say (``fbi.news.writer``);
* ``web_by_address`` - the web evidence of the last days by address, for the owner's replay of the grouping (``scripts/ia_news_stories.py``).

Every statement asks ``subject_type IS NULL OR %(typed)s`` with ``typed`` from ``fbi.ai.gates.typed_visible`` (the caller's), as every reader
of the table (``tests/unit/test_typed_evidence_guard.py``). Nothing here writes; nothing it reads reaches a packet, a decision or a pick."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import source_policy
from fbi.news import vocab

CLAIMS_SQL: Final = """
SELECT e.item_id, e.kind, e.attributes->>'claim_type' AS claim_type FROM ai.evidence e
 WHERE e.item_id = ANY(%(items)s) AND (e.subject_type IS NULL OR %(typed)s)
"""
FACTS_SQL: Final = """
SELECT e.id, e.kind, e.claim, e.source_name, e.source_tier, e.published_at, e.status, e.attributes->>'player_name' AS player_name,
       e.attributes->>'claim_type' AS claim_type
  FROM ai.evidence e
 WHERE e.item_id = ANY(%(items)s) AND (e.subject_type IS NULL OR %(typed)s) AND e.status <> 'OUTDATED'
 ORDER BY e.id
 LIMIT %(limit)s
"""
"""Index ``ai_evidence_item`` (0146)."""
WEB_SQL: Final = """
SELECT e.source_url, max(e.source_domain) AS domain, min(e.published_at) AS published_at, min(e.retrieved_at) AS seen_at,
       max(e.attributes->>'result_title') AS title, array_agg(DISTINCT e.kind) AS kinds,
       array_remove(array_agg(DISTINCT e.attributes->>'claim_type'), NULL) AS codes,
       array_remove(array_agg(DISTINCT e.team_id), NULL) AS teams, array_remove(array_agg(DISTINCT e.provider_player_id), NULL) AS players
  FROM ai.evidence e
 WHERE e.origin = 'web' AND e.retrieved_at > %(since)s AND (e.subject_type IS NULL OR %(typed)s)
 GROUP BY e.source_url
 LIMIT 20000
"""


def claim_word(claim_type: str | None, kind: str | None) -> str:
    """The directory's word for the type of a claim: research v2's code (``OUT``, ``DOUBT``, ``STARTER`` ...), a word of the directory as it
    is, or v1's ``kind`` (``injury`` ...); ``contexto`` otherwise (``source_policy.CLAIM_TYPE_OF``)."""
    for value in (claim_type, (claim_type or "").upper(), kind):
        if not value:
            continue
        if value in source_policy.CLAIM_TYPE_OF:
            return source_policy.CLAIM_TYPE_OF[value]
        if value.lower() in vocab.CLAIM_TYPES:
            return value.lower()
    return "contexto"


def claim_types(conn: psycopg.Connection[Any], item_ids: Sequence[int], *, typed: bool) -> dict[int, str]:
    if not item_ids:
        return {}
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLAIMS_SQL, {"items": list(item_ids), "typed": typed})
        for r in cur.fetchall():
            counts[int(r["item_id"])][claim_word(r["claim_type"], r["kind"])] += 1
    return {i: c.most_common(1)[0][0] for i, c in counts.items()}


def fact_rows(conn: psycopg.Connection[Any], item_ids: Sequence[int], *, typed: bool, limit: int) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FACTS_SQL, {"items": list(item_ids), "typed": typed, "limit": limit})
        return cur.fetchall()


def web_by_address(conn: psycopg.Connection[Any], *, since: datetime, typed: bool) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(WEB_SQL, {"since": since, "typed": typed})
        return cur.fetchall()


__all__ = ["claim_types", "claim_word", "fact_rows", "web_by_address"]

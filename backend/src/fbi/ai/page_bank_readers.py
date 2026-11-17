"""The reader of the bank of pages (IA-127, AD-C09): the pages the research of a window of matches already saved, as candidates of the bank.

Read only: every statement is a SELECT (the script opens its connection with ``default_transaction_read_only``). It reads the answers of
the search in ``ai.research_cache`` - the very keys v1 and research v2 wrote for each match (``fbi.ai.collectors.search_key``), early and
late, every level and side - WITHOUT their expiry (a page is copied to the bank before the cache's purge, 14 days after it expired) and
without counting a reuse (``hits`` is not touched). It never reads ``ai.evidence``: the bank is the page, not what an extractor wrote.

What is kept of a page is what the policy of sources lets be kept (``fbi.ai.source_policy.for_storage``, the same rule the cache applies):
a reserved or excluded source keeps its link and title, never its text, and a page without text is not a candidate. Nothing here
samples or scores (``fbi.ai.page_bank``, pure).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import cache, research, source_policy
from fbi.ai.collectors import LEVELS, language_of, queries_for, query_for_sides, search_key
from fbi.ai.page_bank import Page, stratum_of
from fbi.analyst.search import SearchResult

FIXTURES_SQL: Final = """
SELECT f.id, f.kickoff_at, th.name AS home_name, ta.name AS away_name, c.name AS competition, c.country,
       (th.is_national IS TRUE OR ta.is_national IS TRUE) AS national
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""
CACHE_SQL: Final = "SELECT key, fetched_at, payload FROM ai.research_cache WHERE scope = 'search' AND key = ANY(%(keys)s)"
MAX_FIXTURES: Final = 5000
BATCH: Final = 400


def keys_of(match: dict[str, Any]) -> dict[str, int]:
    """Every key of the search cache the research of a match could have written: early and late, each level, both sides and each one."""
    out: dict[str, int] = {}
    home, away, kickoff, country, comp = match["home_name"], match["away_name"], match["kickoff_at"], match["country"], match["competition"]
    for bucket in ("early", "late"):
        for level, query in zip(LEVELS, queries_for(home, away, kickoff, country, comp, levels=LEVELS), strict=True):
            out[search_key(query, bucket, level)] = level
            for side in ("home", "away"):
                q = query_for_sides(level, (side,), home=home, away=away, kickoff=kickoff, country=country, competition=comp)
                out[search_key(q, bucket, level)] = level
    return out


def page_id(url: str) -> str:
    return "pg:" + hashlib.sha256(cache.canonical_url(url).encode()).hexdigest()[:16]


def candidates(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, policy: source_policy.SourcePolicy | None
               ) -> tuple[list[Page], dict[str, int]]:
    """The pages with text saved for the matches that kick off in ``[start, end)``, one per canonical address (the first match that
    found it), and counts of what was left out and why."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute(FIXTURES_SQL, {"start": start, "end": end, "limit": MAX_FIXTURES})
        matches = [dict(r) for r in cur.fetchall()]
    wanted: dict[str, tuple[dict[str, Any], int]] = {}
    for m in matches:
        for key, level in keys_of(m).items():
            wanted.setdefault(key, (m, level))
    rows: list[dict[str, Any]] = []
    keys = sorted(wanted)
    for i in range(0, len(keys), BATCH):
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(CACHE_SQL, {"keys": keys[i:i + BATCH]})
            rows += [dict(r) for r in cur.fetchall()]
    counts = {"matches": len(matches), "answers": len(rows), "results": 0, "no_text": 0, "not_kept": 0, "repeated": 0}
    out: dict[str, Page] = {}
    for r in sorted(rows, key=lambda r: (wanted[r["key"]][0]["kickoff_at"], wanted[r["key"]][0]["id"], r["key"])):
        match, level = wanted[r["key"]]
        hits = [h for h in (r["payload"] or {}).get("results") or [] if isinstance(h, dict) and h.get("url")]
        counts["results"] += len(hits)
        found = [SearchResult(str(h["url"]), str(h.get("title") or ""), str(h.get("publisher") or ""), h.get("published_at"),
                              str(h.get("retrieved_at") or ""), str(h.get("snippet") or "")) for h in hits]
        kept = source_policy.for_storage(policy, found)
        counts["not_kept"] += len(found) - len(kept)
        for res in kept:
            if not res.snippet.strip():
                counts["no_text"] += 1
                continue
            try:
                pid = page_id(res.url)
            except ValueError:
                continue
            if pid in out:
                counts["repeated"] += 1
                continue
            lang = language_of(match["country"])
            topic = research.LEVEL_TOPIC.get(level, "other")
            out[pid] = Page(pid, stratum_of(national=match["national"], language=lang, topic=topic), {
                "url": res.url, "domain": source_policy.host_of(res.url) or "", "title": res.title, "published_at": res.published_at or "",
                "match": f"{match['home_name']} - {match['away_name']} ({match['kickoff_at'].isoformat()})", "fixture_id": int(match["id"]),
                "scope": "seleccion" if match["national"] else "club", "language": lang, "topic": topic, "level": level,
                "fetched_at": r["fetched_at"].isoformat(), "text": res.snippet})
    return list(out.values()), counts


def window_of(start: datetime, end: datetime) -> dict[str, str]:
    return {"kickoff_from": start.isoformat(), "kickoff_to": end.isoformat()}


__all__: Sequence[str] = ("candidates", "keys_of", "page_id", "window_of")

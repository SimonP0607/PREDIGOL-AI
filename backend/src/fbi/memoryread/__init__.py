"""ONE read layer over the memories PrediGol keeps (IA-138, AD-K06 of the plan of the definitive architecture 2026): ``memory-read-v1``.

Four stores hold what PrediGol Intelligence remembers, each written by its own writer, each in its own shape:

    ai.memory_events        the AI's log of events (``fbi.ai.memory``), append-only
    intel.entity_memory     memory-v4 (``fbi.intel.memory``): entity x aspect x Bogotá day; ``intel.entity_memory_latest`` its newest version
    intel.family_memory     memory-fam-v1 (``fbi.familydecisions.memory``); ``intel.family_memory_latest`` its newest snapshot
    intel.match_knowledge   Match Knowledge mk-v1 (``fbi.knowledge.builder``): the layers of a finished match

Until IA-138 every reader named the tables in its own SQL - the console of the AI, the console of Intelligence, the families' console, the
page of a finished match, the AI's daily report, the patterns and the day's report of Intelligence. Now every statement that READS one of
them lives here (``STATEMENTS``), with its store and its reader, and a guard (``tests/unit/test_memory_read_layer.py``) holds that no other
module of ``src/fbi`` reads them, except, each with its reason in ``OWN_READERS``: a writer reading the lineage it continues, and the
Knowledge Store ``ks-v1`` (``fbi.knowledge.store``), the record-level read in shadow that is the next step of this layer.

PARITY. Each statement was moved byte for byte from where it was (``chain5-FINAL``): its sha256 is pinned in the guard, so a reader reads
exactly what it read before. Changing one is a new statement, compared before it replaces the old.

NOTHING IS RETIRED HERE, NOTHING IS DELETED. The four stores are kept, written and readable as they were. Retiring a writer (one at a
time, compared before) or closing a store is the owner's decision: a proposal with its evidence in the registry of AD-K07
(``fbi.proposals``, ``retirada``). ``STORES[...].closed_on`` is the date of the owner's signed closure; today it is None for all four, and the
guard refuses a statement over a closed store.

Pure: strings and their catalogue; it imports nothing of ours, so every layer (the API, the AI, Intelligence) may read through it."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

VERSION: Final = "memory-read-v1"


@dataclass(frozen=True, slots=True)
class Store:
    table: str
    version: str
    writer: str
    what: str
    views: tuple[str, ...] = ()
    closed_on: date | None = None
    """The day the owner signed its closure (AD-K07); None while it is open."""


STORES: Final[Mapping[str, Store]] = {s.table: s for s in (
    Store("ai.memory_events", "ai-memory", "fbi.ai.memory", "el registro de eventos de la IA"),
    Store("intel.entity_memory", "memory-v4", "fbi.intel.memory", "memoria por entidad, aspecto y día",
          ("intel.entity_memory_latest",)),
    Store("intel.family_memory", "memory-fam-v1", "fbi.familydecisions.memory", "memoria de las familias",
          ("intel.family_memory_latest",)),
    Store("intel.match_knowledge", "mk-v1", "fbi.knowledge.builder", "conocimiento de un partido terminado"),
)}
NAMES: Final[Mapping[str, str]] = {name: s.table for s in STORES.values() for name in (s.table, *s.views)}
"""Every name a statement may read a store by (its table or one of its views) -> the store."""
READS: Final = re.compile(r"\b(?:FROM|JOIN)\s+(" + "|".join(re.escape(n) for n in sorted(NAMES, key=len, reverse=True)) + r")\b")
"""A statement that reads a store, as SQL names it (``FROM`` / ``JOIN`` in capitals, as every statement of the repository writes them)."""

OWN_READERS: Final[Mapping[str, str]] = {
    "fbi.intel.memory": "the writer of memory-v4 reads its own previous rows to continue its lineage",
    "fbi.familydecisions.memory": "the writer of memory-fam-v1 reads its own previous snapshot to continue it",
    "fbi.knowledge.builder": "the writer of Match Knowledge reads its newest build to decide whether to build again",
    "fbi.knowledge.store": "ks-v1, the record-level read over the four stores in shadow (the next step of this layer); isolated by its own tests",
    "fbi.memoryread": "this layer",
}
"""The only modules outside the layer that may read a store, each with its reason."""


def stores_read(sql: str) -> frozenset[str]:
    """The stores a statement reads (by table or view)."""
    return frozenset(NAMES[m] for m in READS.findall(sql))


AI_DAY_PATTERNS: Final = """
SELECT kind, entity_type, hypothesis FROM ai.memory_events
 WHERE created_at >= %(start)s AND created_at < %(end)s
   AND kind IN ('league_pattern', 'team_pattern', 'player_pattern', 'market_signal', 'model_failure',
                'model_success', 'context_error')
 ORDER BY id DESC LIMIT 40
"""
"""The AI's patterns and signals of the day, for its daily report - read by ``fbi.ai.daily_review``."""

AI_WINDOW_EVENTS: Final = """
SELECT id, kind, entity_type, entity_id, fixture_id, evidence, result, created_at
  FROM ai.memory_events WHERE created_at >= %(since)s AND created_at <= %(until)s
"""
"""The events of a window, which patterns-v1 counts into hypotheses for the owner - read by ``fbi.ai.patterns``."""

AI_CONSOLE_EVENTS: Final = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence, version
  FROM ai.memory_events WHERE (%(kind)s::text IS NULL OR kind = %(kind)s)
 ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""
"""The console's list of events (/admin/ai/memory) - read by ``fbi.api.services.ai_layer``."""

AI_CONSOLE_FINDINGS: Final = """
SELECT id, created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence, version
  FROM ai.memory_events
 WHERE created_at >= %(since)s AND created_at < %(until)s
   AND kind IN ('context_error', 'model_failure', 'model_success', 'league_pattern', 'team_pattern', 'player_pattern',
                'market_signal', 'news_signal')
 ORDER BY created_at DESC, id DESC LIMIT 30
"""
"""The console's findings of a day - read by ``fbi.api.services.ai_layer``."""

AI_EVENTS_OF_BASE_FIXTURE: Final = '(SELECT count(*) FROM ai.memory_events e WHERE e.fixture_id = b.id)'
"""How many events a match left (/admin/ai/match-memory); a fragment of its statement, ``b`` is its match - read by ``fbi.api.services.match_memory``."""

ENTITY_CONSOLE_LATEST: Final = """
        SELECT DISTINCT ON (entity_type, entity_id, aspect) entity_type, entity_id, entity_name, aspect, as_of_day,
               version, stats, delta, confidence::float8 AS confidence, evidence_ref
          FROM intel.entity_memory_latest
         WHERE (%(t)s::text IS NULL OR entity_type = %(t)s)
           AND (%(q)s::text IS NULL OR entity_name ILIKE '%%' || %(q)s || '%%')
           AND (%(a)s::text IS NULL OR aspect = %(a)s)
           AND NOT (entity_type = 'referee' AND entity_id !~ '^[0-9]+$')
         ORDER BY entity_type, entity_id, aspect, as_of_day DESC"""
"""The newest state of every entity and aspect (/admin/intelligence/memory) - read by ``fbi.api.services.intelligence``."""

ENTITY_CONSOLE_HISTORY: Final = 'SELECT aspect, as_of_day, entity_name, version, stats, delta, sources, built_at, confidence::float8 AS confidence, evidence_ref FROM intel.entity_memory_latest WHERE entity_type = %(t)s AND entity_id = %(i)s ORDER BY aspect, as_of_day'
"""The history of one entity (/admin/intelligence/memory/{type}/{id}) - read by ``fbi.api.services.intelligence``."""

ENTITY_REPORT_TEAMS: Final = "SELECT entity_type, entity_name, aspect, stats FROM intel.entity_memory_latest WHERE as_of_day = %s AND entity_type IN ('team', 'competition') AND (stats->>'decisions')::int >= 5 ORDER BY (stats->>'clv_mean')::float8 NULLS LAST LIMIT 12"
"""The teams and competitions of the day's report - read by ``fbi.intel.report``."""

ENTITY_REPORT_PLAYERS: Final = "SELECT entity_name, stats FROM intel.entity_memory_latest WHERE as_of_day = %s AND entity_type = 'player' AND (delta->>'started_anyway')::int > 0 LIMIT 15"
"""The players reported out who started anyway, in the day's report - read by ``fbi.intel.report``."""

FAMILY_CONSOLE_NEWEST: Final = """
WITH newest AS (
    SELECT DISTINCT ON (m.entity_type, m.entity_key) m.*
      FROM intel.family_memory m
     WHERE m.version = %(version)s
     ORDER BY m.entity_type, m.entity_key, m.as_of_day DESC, m.id DESC
), ranked AS (
    SELECT n.*, row_number() OVER (PARTITION BY n.entity_type ORDER BY (n.stats #>> '{all,n}')::int DESC NULLS LAST, n.entity_key) AS rn
      FROM newest n
)
SELECT entity_type, entity_key, entity_name, version, as_of_day, built_at, confidence::float8 AS confidence, stats, delta, evidence_ref
  FROM ranked
 WHERE entity_type IN ('family', 'market') OR rn <= %(top)s
 ORDER BY CASE entity_type WHEN 'family' THEN 0 WHEN 'market' THEN 1 WHEN 'competition' THEN 2 ELSE 3 END,
          (stats #>> '{all,n}')::int DESC NULLS LAST, entity_key
"""
"""The newest snapshot of the families' memory (console of the families) - read by ``fbi.api.services.families``."""

KNOWLEDGE_ROW: Final = """
SELECT id, supersedes, built_at, known_at, inputs_hash, content_hash, completeness, layers, quality
  FROM intel.match_knowledge
 WHERE fixture_id = %(f)s AND version = %(version)s AND built_at <= %(at)s
 ORDER BY id DESC LIMIT 1
"""
"""The newest build of a finished match by a moment - read by ``fbi.api.services.knowledge``."""

KNOWLEDGE_CHAIN: Final = """
SELECT id, supersedes, built_at, known_at, completeness, content_hash
  FROM intel.match_knowledge
 WHERE fixture_id = %(f)s AND version = %(version)s AND built_at <= %(at)s
 ORDER BY id LIMIT %(limit)s
"""
"""The chain of builds of a finished match - read by ``fbi.api.services.knowledge``."""

@dataclass(frozen=True, slots=True)
class Statement:
    name: str
    store: str
    reader: str
    sql: str


STATEMENTS: Final[tuple[Statement, ...]] = (
    Statement("AI_DAY_PATTERNS", "ai.memory_events", "fbi.ai.daily_review", AI_DAY_PATTERNS),
    Statement("AI_WINDOW_EVENTS", "ai.memory_events", "fbi.ai.patterns", AI_WINDOW_EVENTS),
    Statement("AI_CONSOLE_EVENTS", "ai.memory_events", "fbi.api.services.ai_layer", AI_CONSOLE_EVENTS),
    Statement("AI_CONSOLE_FINDINGS", "ai.memory_events", "fbi.api.services.ai_layer", AI_CONSOLE_FINDINGS),
    Statement("AI_EVENTS_OF_BASE_FIXTURE", "ai.memory_events", "fbi.api.services.match_memory", AI_EVENTS_OF_BASE_FIXTURE),
    Statement("ENTITY_CONSOLE_LATEST", "intel.entity_memory", "fbi.api.services.intelligence", ENTITY_CONSOLE_LATEST),
    Statement("ENTITY_CONSOLE_HISTORY", "intel.entity_memory", "fbi.api.services.intelligence", ENTITY_CONSOLE_HISTORY),
    Statement("ENTITY_REPORT_TEAMS", "intel.entity_memory", "fbi.intel.report", ENTITY_REPORT_TEAMS),
    Statement("ENTITY_REPORT_PLAYERS", "intel.entity_memory", "fbi.intel.report", ENTITY_REPORT_PLAYERS),
    Statement("FAMILY_CONSOLE_NEWEST", "intel.family_memory", "fbi.api.services.families", FAMILY_CONSOLE_NEWEST),
    Statement("KNOWLEDGE_ROW", "intel.match_knowledge", "fbi.api.services.knowledge", KNOWLEDGE_ROW),
    Statement("KNOWLEDGE_CHAIN", "intel.match_knowledge", "fbi.api.services.knowledge", KNOWLEDGE_CHAIN),
)
"""Every statement that reads a memory, with the store it reads and the module that runs it."""
BY_NAME: Final[Mapping[str, Statement]] = {s.name: s for s in STATEMENTS}


def inventory() -> list[dict[str, object]]:
    """Each store: its writer, its version, whether it is closed, and who reads it through the layer (the owner's view of AD-K06)."""
    return [{"store": s.table, "version": s.version, "writer": s.writer, "what_es": s.what, "views": list(s.views),
             "closed_on": None if s.closed_on is None else s.closed_on.isoformat(),
             "statements": [st.name for st in STATEMENTS if st.store == s.table],
             "readers": sorted({st.reader for st in STATEMENTS if st.store == s.table})} for s in STORES.values()]


__all__ = [
    "AI_CONSOLE_EVENTS",
    "AI_CONSOLE_FINDINGS",
    "AI_DAY_PATTERNS",
    "AI_EVENTS_OF_BASE_FIXTURE",
    "AI_WINDOW_EVENTS",
    "BY_NAME",
    "ENTITY_CONSOLE_HISTORY",
    "ENTITY_CONSOLE_LATEST",
    "ENTITY_REPORT_PLAYERS",
    "ENTITY_REPORT_TEAMS",
    "FAMILY_CONSOLE_NEWEST",
    "KNOWLEDGE_CHAIN",
    "KNOWLEDGE_ROW",
    "NAMES",
    "OWN_READERS",
    "READS",
    "STATEMENTS",
    "STORES",
    "VERSION",
    "Statement",
    "Store",
    "inventory",
    "stores_read",
]

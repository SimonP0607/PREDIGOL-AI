"""The AI's explicit memory: events, never weights.

Nothing here "learns" by changing a model. A result, an error, a signal is WRITTEN DOWN as an event with
its evidence, its sources, how confident the writer was and the writer's version (``ai.memory_events``,
append-only); patterns over many events become hypotheses for the owner (``fbi.ai.patterns``), and only
an experiment that passes its gate - and an explicit promotion - ever changes production.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

Kind = Literal["match_result", "pick_result", "context_error", "news_signal", "injury_signal", "market_signal",
               "model_failure", "model_success", "league_pattern", "team_pattern", "player_pattern", "review_quality",
               "pick_postmortem"]
EntityType = Literal["fixture", "pick", "team", "player", "competition", "market", "model", "source", "reviewer"]


def remember(conn: psycopg.Connection[Any], *, at: datetime, kind: Kind, entity_type: EntityType, entity_id: str,
             version: str, fixture_id: int | None = None, hypothesis: str | None = None,
             evidence: dict[str, Any] | None = None, result: str | None = None, confidence: float | None = None,
             sources: list[Any] | None = None, dedup_key: str | None = None) -> int | None:
    """One event; a keyed event is written once (None when it already exists)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "INSERT INTO ai.memory_events (created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, "
            "result, confidence, sources, version, dedup_key) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
            (at, kind, entity_type, entity_id[:200], fixture_id, None if hypothesis is None else hypothesis[:600],
             Jsonb(evidence or {}), None if result is None else result[:600],
             None if confidence is None else round(max(0.0, min(1.0, confidence)), 3), Jsonb(sources or []), version,
             dedup_key))
        row = cur.fetchone()
    return None if row is None else int(row[0])

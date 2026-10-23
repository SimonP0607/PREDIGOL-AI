"""POST-MORTEM: after a match, what was expected, what happened, and what that says - written down, never
acted on.

For every finished match the AI reviewed (rule ``pm-v1``):

* the outcome: the regulation score, who started (when the line-ups are stored);
* per reviewed selection: the model's and the market's probability, the review's decision, how it settled,
  each forecast's log loss on it, and the price move of the price taken (against the provider's final
  pre-match price of the same bookmaker, when it was read: ``price_move``, margin in both prices - NOT the
  closing-line value, which is the price at the closing fair probability: ``fbi.market.closing_value``);
* the evidence checked against what happened: a player reported OUT who started (a context error, by the
  source's tier), reported out and absent (confirmed), and key regulars absent from the starting line-up
  without any report (missing information);
* the match's 1X2 forecast: the model's against the market's closing consensus (log loss), a model failure
  or success when the difference is large.

Each of these becomes memory events (``ai.memory_events``); the narrative, when a model is configured and
the budget allows, is a short summary for the owner. Losses are studied as much as wins, but a single
match never proposes a change: patterns over many matches do (``fbi.ai.patterns``), and only as
hypotheses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.config import AiSettings
from fbi.ai.prompts import POSTMORTEM_SCHEMA, POSTMORTEM_SYSTEM, POSTMORTEM_VERSION
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.text import narrative_of
from fbi.ai.usage import UsageLedger, call_json
from fbi.intel.match_review import analyse, write_events
from fbi.picks.settlement import Status

VERSION = "pm-v1.1"
"""v1.1 (9 Oct 2026): a regular starter is one who started at least two of the team's last three matches (the line-ups),
no longer any player with many minutes this season - a player sold in August was "missing without a report"."""
MEMORY_KEY = "pm-v1"
"""The memory events keep the key of the first version: a match analysed again by a newer version is not remembered
twice (patterns count events - a duplicate would inflate their samples)."""
LOOKBACK = timedelta(days=7)
SETTLE_DELAY = timedelta(hours=3)
LARGE_LOGLOSS_DIFF = 0.25
MAX_NARRATIVES_PER_RUN = 10

DUE_SQL = """
SELECT DISTINCT f.id, f.kickoff_at
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s AND f.status_group = 'finished'
   AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
   AND EXISTS (SELECT 1 FROM ai.pick_reviews pr WHERE pr.fixture_id = f.id)
   AND NOT EXISTS (SELECT 1 FROM ai.postmortems pm WHERE pm.fixture_id = f.id AND pm.version = %(version)s)
 ORDER BY f.kickoff_at
 LIMIT %(limit)s
"""


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


@dataclass
class PostmortemReport:
    fixtures: int = 0
    memory_events: int = 0
    narratives: int = 0
    context_errors: int = 0
    errors: list[str] = field(default_factory=list)


def run_postmortems(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                    ledger: UsageLedger | None = None, limit: int = 200,
                    provider: tuple[LlmProvider, str] | None = None,
                    transport: httpx.BaseTransport | None = None) -> PostmortemReport:
    settings = settings or AiSettings.from_env()
    report = PostmortemReport()
    due = _rows(conn, DUE_SQL, {"since": at - LOOKBACK, "until": at - SETTLE_DELAY, "version": VERSION, "limit": limit})
    narratives_left = MAX_NARRATIVES_PER_RUN if (settings.llm_configured or provider is not None) else 0
    for row in due:
        fid = int(row["id"])
        try:
            got = analyse(conn, fid)
            if got is None:
                continue
            outcome, expected, findings = got
            narrative, usage_ids = None, []
            decisive = [s for s in expected["selections"] if s["decision"] in ("APPROVE", "REJECT")]
            if narratives_left > 0 and decisive:
                body = json.dumps({"outcome": outcome, "expected": expected, "findings": findings}, default=str,
                                  ensure_ascii=False)
                call = call_json(conn, settings, tier="bulk", purpose="postmortem",
                                 request=JsonRequest(POSTMORTEM_SYSTEM, body, POSTMORTEM_SCHEMA, "submit_postmortem",
                                                     max_tokens=3000), at=at, prompt_version=POSTMORTEM_VERSION,
                                 input_hash=str(fid), fixture_id=fid, ledger=ledger, transport=transport,
                                 provider=provider)
                if call.usage_id:
                    usage_ids.append(call.usage_id)
                if call.result is not None:
                    read = narrative_of(call.result.data, max_lessons=3)
                    if read is not None:
                        summary, _, lessons = read
                        narrative = summary + ("\n- " + "\n- ".join(lessons) if lessons else "")
                        narratives_left -= 1
                        report.narratives += 1
            with conn.cursor(row_factory=tuple_row) as cur:
                cur.execute("INSERT INTO ai.postmortems (fixture_id, created_at, version, outcome, expected, findings, "
                            "narrative, usage_ids) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (fid, at, VERSION, Jsonb(outcome), Jsonb(expected), Jsonb(findings), narrative, usage_ids))
            n, errors = write_memory(conn, fid, outcome, expected, findings, at=at)
            report.memory_events += n
            report.context_errors += errors
            report.fixtures += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            report.errors.append(f"{fid}: {type(exc).__name__}: {exc}"[:200])
    return report


def write_memory(conn: psycopg.Connection[Any], fixture_id: int, outcome: dict[str, Any], expected: dict[str, Any],
                 findings: dict[str, Any], *, at: datetime) -> tuple[int, int]:
    """The memory events of one match, stamped with this (frozen) writer's version; the work is ``write_events``."""
    return write_events(conn, fixture_id, outcome, expected, findings, at=at, version=VERSION)


__all__ = ["VERSION", "Status", "analyse", "run_postmortems", "write_memory"]

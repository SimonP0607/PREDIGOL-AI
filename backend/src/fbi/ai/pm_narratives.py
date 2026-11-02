"""The NARRATIVES of the post-mortems (plan F8): the short text a language model writes about a post-mortem that matters.

The post-mortem itself (``fbi.intel.postmortem``) is built by rules from stored numbers, for every selection PrediGol looked at, at no
cost. A narrative is something else: optional, paid for, and kept apart (``ai.postmortem_narratives``, one per post-mortem and version) so
that nothing that reads a post-mortem waits on, depends on or is billed for a language model. Until F8 the two were one row
(``ai.pick_postmortems.narrative``) and a narrative that was not written left a post-mortem half done.

Which post-mortems get one - the ones a person would want explained, as the first post-mortem by selection (pm-v2) chose them:

    * a loss of a selection the AI approved or only cautioned about (``approved_lost``, ``caution_lost``),
    * a selection the AI rejected that would have won (``rejected_would_have_won``),
    * a loss of a selection nobody reviewed that a person was shown (``unreviewed_lost``, no review decision at all).

The pick-of-the-day losses first, and with the intermediate model (at most three a run); the rest with the economical one (at most twelve
a run in all). The same prompt, the same schema and the same reading as before (``PICK_PM_*``, ``fbi.ai.text.narrative_of``), so the
narratives of the two eras read alike. A selection only the decision layer judged gets none: it has no AI review to explain.

A narrative is written once per post-mortem and version, from what the post-mortem already says (its answers) and what the review itself
wrote (reason, evidence, uncertainties); it never decides anything and nothing reads it but a person.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from fbi.ai.config import AiSettings, Tier
from fbi.ai.prompts import PICK_PM_SCHEMA, PICK_PM_SYSTEM, PICK_PM_VERSION
from fbi.ai.providers.base import JsonRequest, LlmProvider
from fbi.ai.text import DISAGREES, narrative_of
from fbi.ai.usage import UsageLedger, call_json
from fbi.intel.pm_facts import AI_ROLES
from fbi.intel.postmortem import SETTLE_DELAY

VERSION = "pmn-v1"
LOOKBACK = timedelta(days=7)
# SETTLE_DELAY (imported): the post-mortem is written this long after kick-off, and so is its narrative
MAX_NARRATIVES = 12
MAX_STRONG_NARRATIVES = 3
"""Narratives a run may pay for: the economical model for most, the intermediate one for the picks of the day that lost."""
CANDIDATES = 60
"""How many post-mortems a run reads to choose from: the picks of the day that lost, then the rest, the newest matches first (what
ended yesterday is what is learned today; a narrative nobody wrote in a week is not written)."""

QUESTIONS = ("expected", "happened", "model", "information", "ignored_signal", "odds_moved", "key_absence", "lineup_changed",
             "uncertainty", "variance", "win_quality")
"""The answers of the post-mortem the language model is shown: the ten questions of the AI (the answers of the decision layer's own
review are for a person, and shown to a model they would only make the prompt longer)."""
REVIEW_KEYS = ("reason", "positive_evidence", "negative_evidence", "uncertainties")

DUE_SQL = """
SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.roles, p.review_id, p.review_decision, p.review_verdict, p.loss_class,
       p.settled, p.answers, f.kickoff_at
  FROM intel.selection_postmortems p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at <= %(until)s
   AND p.roles && %(ai_roles)s
   AND (p.review_verdict IN ('approved_lost', 'caution_lost', 'rejected_would_have_won')
        OR (p.review_verdict = 'unreviewed_lost' AND p.review_decision IS NULL))
   AND NOT EXISTS (SELECT 1 FROM ai.postmortem_narratives n WHERE n.postmortem_id = p.id AND n.version = %(version)s)
 ORDER BY ('daily_pick' = ANY(p.roles) AND p.settled IN ('loss', 'half_loss')) DESC, f.kickoff_at DESC, p.id DESC
 LIMIT %(limit)s
"""

REVIEWS_SQL = "SELECT id, output FROM ai.pick_reviews WHERE id = ANY(%(ids)s)"


@dataclass
class NarrativeReport:
    due: int = 0
    written: int = 0
    strong: int = 0
    unavailable: int = 0
    """Calls that came back without a narrative (over budget, not configured, an answer that did not validate)."""
    errors: list[str] = field(default_factory=list)


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _is_pick_of_the_day_loss(row: dict[str, Any]) -> bool:
    return "daily_pick" in (row.get("roles") or []) and row.get("settled") in ("loss", "half_loss")


def run_narratives(conn: psycopg.Connection[Any], *, at: datetime, settings: AiSettings | None = None,
                   ledger: UsageLedger | None = None, provider: tuple[LlmProvider, str] | None = None,
                   transport: httpx.BaseTransport | None = None, lookback: timedelta = LOOKBACK) -> NarrativeReport:
    """Write the narratives that are due, within the run's limits and the day's budget. Does not commit (a savepoint per narrative: one
    failing loses that one, never the ones before it); a run without a configured model reads nothing and writes nothing."""
    settings = settings or AiSettings.from_env()
    report = NarrativeReport()
    if not (settings.llm_configured or provider is not None):
        return report
    due = _rows(conn, DUE_SQL, {"since": at - lookback, "until": at - SETTLE_DELAY, "ai_roles": sorted(AI_ROLES),
                                "version": VERSION, "limit": CANDIDATES})
    report.due = len(due)
    if not due:
        return report
    reviews = {int(r["id"]): r["output"] or {} for r in
               _rows(conn, REVIEWS_SQL, {"ids": sorted({int(r["review_id"]) for r in due if r["review_id"] is not None})})} \
        if any(r["review_id"] is not None for r in due) else {}
    left, strong_left = MAX_NARRATIVES, MAX_STRONG_NARRATIVES
    for r in due:  # already in the order that matters: the picks of the day that lost (they get the better model), the newest first
        if left <= 0:
            break
        fid, market, selection, line = int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), r["line"]
        try:
            strong = _is_pick_of_the_day_loss(r) and strong_left > 0
            tier: Tier = "analysis" if strong else "bulk"
            answers = r["answers"] or {}
            label = str((answers.get("expected") or {}).get("answer") or f"{market} {selection} {line}")
            output = reviews.get(int(r["review_id"]), {}) if r["review_id"] is not None else {}
            body = json.dumps({"selection": label, "verdict": r["review_verdict"], "class": r["loss_class"],
                               "answers": {k: answers[k] for k in QUESTIONS if k in answers},
                               "review": {k: output.get(k) for k in REVIEW_KEYS}, "roles": sorted(r["roles"] or [])},
                              ensure_ascii=False, default=str)
            with conn.transaction():
                call = call_json(conn, settings, tier=tier, purpose="postmortem",
                                 request=JsonRequest(PICK_PM_SYSTEM, body, PICK_PM_SCHEMA, "submit_postmortem", max_tokens=3000),
                                 at=at, prompt_version=PICK_PM_VERSION, input_hash=f"{VERSION}:{fid}:{market}:{selection}:{line}",
                                 fixture_id=fid, ledger=ledger, transport=transport, provider=provider)
                read = None if call.result is None else narrative_of(call.result.data, max_lessons=2)
                if read is None:
                    report.unavailable += 1
                    continue
                summary, agrees, lessons = read
                narrative = summary + ("" if agrees else DISAGREES) + ("\n- " + "\n- ".join(lessons) if lessons else "")
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative, usage_ids) "
                                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (int(r["id"]), at, VERSION, narrative, [call.usage_id] if call.usage_id else []))
            report.written += 1
            left -= 1
            if strong:
                report.strong += 1
                strong_left -= 1
        except Exception as exc:
            report.errors.append(f"{fid}: {market} {selection} {line}: {type(exc).__name__}: {exc}"[:240])
    return report


__all__ = ["VERSION", "NarrativeReport", "run_narratives"]

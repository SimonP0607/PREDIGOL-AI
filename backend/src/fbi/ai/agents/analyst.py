"""The Learning Analyst ``la-v1`` (Plan Maestro IA, section 13, phase 5): once a week, at most five hypotheses about the agents of the shadow, each for ONE
version of ONE agent and each resting on attributions it cites.

The server prepares everything the analyst reads: the attributions of the week (``intel.agent_attributions``, made by code) grouped by agent, version, arm,
signal, outcome and class - counts, and the ids of a few rows that illustrate each group - and the hypotheses it proposed before. The analyst answers in
``la-v1``: closed lists and short prose. It runs in the Batch of the LAB (Sonnet) and only PROPOSES. This module checks the answer before anything is
written, and writes each hypothesis that stands as ``PROPOSED`` in ``analytics.research_hypotheses`` with its agent and version:

* the agent and the version must be ones the week's attributions list (a version nobody ran cannot be the subject of a hypothesis);
* every cited attribution must exist AND belong to that agent and that version (a hypothesis about ``council-v1`` does not rest on ``match-v1``'s rows);
* its text is the analyst's prose: UNTRUSTED, normalised and shortened on its way in, shown to the owner, never an instruction. The experiment it describes is
  kept inside the hypothesis' evidence, as a draft: ``analytics.experiments`` rows are written by whoever RUNS an experiment (a draft would need a state the
  table does not have).

The write is made under the database role ``predigol_learning`` when the cluster has it (``deploy/vps/db/roles.sql``): a role that can insert hypotheses and can
touch nothing else - above all not ``intel.promotions``. The database says what the analyst can write, not the prompt. The switch is
``FBI_AI_LEARNING_ANALYST``; off, nothing here is called.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.agents import attribution
from fbi.ai.agents.lab_batch import Submitted, submit
from fbi.ai.batch import BatchClient, Resolved, Task, register
from fbi.ai.config import AiSettings
from fbi.ai.contracts import parse, schema_of
from fbi.ai.contracts.base import LEARNING
from fbi.ai.contracts.learning import Hypothesis, LearningOut
from fbi.ai.prompts import LA_SYSTEM, LA_VERSION
from fbi.ai.providers.base import JsonRequest
from fbi.ai.untrusted import sanitize
from fbi.ai.usage import UsageLedger
from fbi.research.evolution import propose

AGENT: Final = "la"
VERSION: Final = LA_VERSION
ROLE: Final = "predigol_learning"
"""The database role the analyst's writes run as (``deploy/vps/db/roles.sql``)."""
WINDOW: Final = timedelta(days=7)
MIN_STANCES: Final = 30
"""Fewer stance rows than this in the week and the analyst is not asked: a week with nothing in it has nothing to learn from, and the call is not free."""
EXAMPLES: Final = 3
"""Ids of illustrating rows kept for each group."""
GROUPS_MAX: Final = 80
HISTORY_MAX: Final = 10
TYPICAL_OUTPUT: Final = 2500
PURPOSE: Final = "learning"
TARGET: Final = "ai"
"""What a hypothesis of the analyst would change if it were ever promoted (``fbi.research.evolution.TARGETS``)."""

GROUPS_SQL: Final = """
WITH effective AS (
    SELECT a.id, a.agent, a.agent_version, a.engine, a.signal, a.outcome, a.toward_close,
           COALESCE(r.error_class, a.error_class) AS error_class, a.computed_at
      FROM intel.agent_attributions a
      LEFT JOIN intel.agent_attributions r ON r.basis_id = a.id AND r.classified_by = 'pmr-v1'
     WHERE a.classified_by = 'code' AND a.attribution_version = %(version)s AND a.computed_at >= %(since)s AND a.computed_at < %(until)s)
SELECT agent, agent_version, engine, signal, outcome, error_class, count(*) AS n,
       count(*) FILTER (WHERE toward_close) AS toward_close, count(*) FILTER (WHERE NOT toward_close) AS against_close,
       (array_agg(id ORDER BY id DESC))[1:%(examples)s] AS examples
  FROM effective GROUP BY agent, agent_version, engine, signal, outcome, error_class
 ORDER BY agent, agent_version, engine, signal, outcome, error_class
"""
HISTORY_SQL: Final = """
SELECT id, agent, agent_version, status, title FROM analytics.research_hypotheses
 WHERE proposed_by = 'ai' AND agent IS NOT NULL AND created_at >= %(since)s ORDER BY id DESC LIMIT %(limit)s
"""
CITED_SQL: Final = "SELECT id FROM intel.agent_attributions WHERE id = ANY(%(ids)s) AND agent = %(agent)s AND agent_version = %(version)s"


@dataclass(frozen=True, slots=True)
class Week:
    """What the analyst is shown: the groups of the week (counts and ids, all server-made) and the proposals it made before."""

    since: datetime
    until: datetime
    groups: tuple[dict[str, Any], ...]
    history: tuple[dict[str, Any], ...] = ()

    @property
    def stances(self) -> int:
        return sum(int(g["n"]) for g in self.groups if g["signal"] == "VERDICT")

    @property
    def versions(self) -> dict[str, list[str]]:
        found: dict[str, set[str]] = {}
        for g in self.groups:
            found.setdefault(str(g["agent"]), set()).add(str(g["agent_version"]))
        return {a: sorted(v) for a, v in sorted(found.items())}

    @property
    def offered(self) -> list[int]:
        return sorted({int(i) for g in self.groups for i in g["examples"]})

    def input_hash(self) -> str:
        body = json.dumps([VERSION, self.since.date().isoformat(), self.groups], sort_keys=True, default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:40]


def week_of(conn: psycopg.Connection[Any], *, at: datetime, window: timedelta = WINDOW) -> Week:
    since = at - window
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GROUPS_SQL, {"version": attribution.VERSION, "since": since, "until": at, "examples": EXAMPLES})
        groups = tuple(dict(r) for r in cur.fetchall())[:GROUPS_MAX]
        cur.execute(HISTORY_SQL, {"since": at - 8 * window, "limit": HISTORY_MAX})
        history = tuple({"id": int(r["id"]), "agent": r["agent"], "version": r["agent_version"], "status": r["status"],
                         "title": sanitize(r["title"], origin=VERSION, max_chars=160).as_block()} for r in cur.fetchall())
    return Week(since, at, groups, history)


def request_of(week: Week) -> JsonRequest:
    """The question: the week's groups as JSON - ids, codes and counts of the server - and the proposals it made before inside blocks that say they are data."""
    body = {"week": {"from": week.since.date().isoformat(), "to": week.until.date().isoformat()}, "agents": week.versions,
            "groups": [{"agent": g["agent"], "version": g["agent_version"], "engine": g["engine"], "signal": g["signal"], "outcome": g["outcome"],
                        "class": g["error_class"], "n": int(g["n"]), "toward_close": int(g["toward_close"]), "against_close": int(g["against_close"]),
                        "examples": [int(i) for i in g["examples"]]} for g in week.groups],
            "earlier": list(week.history)}
    return JsonRequest(LA_SYSTEM, json.dumps(body, ensure_ascii=False, sort_keys=True), schema_of(LEARNING), "submit_hypotheses", max_tokens=6000)


def task_of(week: Week, *, at: datetime) -> Task:
    context = {"la": 1, "week_from": week.since.date().isoformat(), "versions": week.versions, "offered": week.offered, "stances": week.stances,
               "at": at.isoformat()}
    return Task(purpose=PURPOSE, tier="analysis", request=request_of(week), prompt_version=VERSION, input_hash=week.input_hash(), lab=True, agent=AGENT,
                context=context, typical_output=TYPICAL_OUTPUT)


# -- what comes back ------------------------------------------------------------------------------------------------------------------

@dataclass(slots=True)
class Checked:
    """The hypotheses of an answer that stand, and what was dropped and why."""

    standing: list[Hypothesis] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)


def check(out: LearningOut, *, versions: Mapping[str, Sequence[str]], offered: Sequence[int], cited: Mapping[tuple[str, str], set[int]]) -> Checked:
    """Which hypotheses stand. ``versions`` are the agents and versions of the week, ``offered`` the ids the analyst was shown, and ``cited[(agent,
    version)]`` the ids that exist in the table for that agent and version (the database's word, looked up by the caller)."""
    verdict = Checked()
    seen: set[tuple[str, str, str]] = set()
    for h in out.hypotheses:
        if h.agent not in versions or h.agent_version not in versions[h.agent]:
            verdict.rejected["unknown_version"] += 1
        elif not set(h.attribution_ids) <= set(offered):
            verdict.rejected["evidence_not_offered"] += 1
        elif not set(h.attribution_ids) <= cited.get((h.agent, h.agent_version), set()):
            verdict.rejected["evidence_of_another_version"] += 1
        elif (h.agent, h.agent_version, " ".join(h.title.lower().split())) in seen:
            verdict.rejected["repeated"] += 1
        else:
            seen.add((h.agent, h.agent_version, " ".join(h.title.lower().split())))
            verdict.standing.append(h)
    return verdict


@contextmanager
def analyst_role(conn: psycopg.Connection[Any]) -> Iterator[str]:
    """Run the statements inside as the analyst's database role, when the cluster has one. Yields ``"role"`` (inside the role), or ``"no_role"`` (the cluster
    has none yet: the statements run as the worker, which still cannot sign an agent's promotion - the row policy of migration 0111). A role that exists and
    cannot be taken is an error: the analyst writes nothing rather than write with more than it should."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        exists = cur.fetchone() is not None
    if not exists:
        yield "no_role"
        return
    with conn.transaction():
        conn.execute(f"SET LOCAL ROLE {ROLE}")
        try:
            yield "role"
        finally:
            conn.execute("RESET ROLE")


def key_of(h: Hypothesis, week_from: str) -> str:
    text = " ".join(h.title.lower().split())
    return "la:" + hashlib.sha256(f"{VERSION}|{week_from}|{h.agent}|{h.agent_version}|{text}".encode()).hexdigest()[:24]


def write(conn: psycopg.Connection[Any], hypotheses: Sequence[Hypothesis], *, week_from: str, at: datetime) -> tuple[list[int], str]:
    """Each hypothesis as ``PROPOSED``, once (the key says which week, agent, version and title). Returns the ids written and how it was written."""
    ids: list[int] = []
    with analyst_role(conn) as how:
        for h in hypotheses:
            title = sanitize(h.title, origin=VERSION, max_chars=160).text
            if len(title) < 5:
                continue
            made = propose(
                conn, title=title, hypothesis=sanitize(h.hypothesis, origin=VERSION, max_chars=600).text,
                rationale=sanitize(h.rationale, origin=VERSION, max_chars=600).text,
                evidence={"la_version": VERSION, "attribution_ids": list(h.attribution_ids), "week_from": week_from,
                          "experiment": h.experiment.model_dump(), "impact": "por medir en el experimento"},
                proposed_by="ai", at=at, key=key_of(h, week_from), target=TARGET, agent=h.agent, agent_version=h.agent_version)
            if made is not None:
                ids.append(made)
    return ids, how


def settle(conn: psycopg.Connection[Any], r: Resolved) -> None:
    """The handler of the answers of the Batch: checks the answer against the week it was asked about and writes the hypotheses that stand."""
    ctx = r.item["context"] or {}
    if not ctx.get("la"):
        return
    summary: dict[str, Any] = {"la": 1, "usage_id": r.usage_id, "late": r.late}
    parsed = parse(LEARNING, r.result.data) if r.result is not None else None
    if parsed is None or not parsed.ok or not isinstance(parsed.value, LearningOut):
        summary |= {"ok": False, "error": "no_answer" if r.result is None else "invalid", "problems": [] if parsed is None else list(parsed.problems)}
    else:
        wanted = {(h.agent, h.agent_version): sorted(h.attribution_ids) for h in parsed.value.hypotheses}
        cited: dict[tuple[str, str], set[int]] = {}
        with conn.cursor(row_factory=tuple_row) as cur:
            for (agent, version), ids in wanted.items():
                cur.execute(CITED_SQL, {"ids": ids, "agent": agent, "version": version})
                cited[(agent, version)] = {int(row[0]) for row in cur.fetchall()}
        kept = check(parsed.value, versions=ctx.get("versions") or {}, offered=ctx.get("offered") or [], cited=cited)
        made, how = write(conn, kept.standing, week_from=str(ctx.get("week_from")), at=r.at)
        summary |= {"ok": True, "proposed": len(made), "hypothesis_ids": made, "written": how, "rejected": dict(kept.rejected)}
    with conn.cursor() as cur:
        cur.execute("UPDATE ai.batch_items SET context = context || %s WHERE id = %s", (Jsonb({"result": summary}), int(r.item["id"])))


register(PURPOSE, settle)


# -- the weekly step ------------------------------------------------------------------------------------------------------------------

def run(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, ledger: UsageLedger | None = None, client: BatchClient | None = None,
        transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """The Learning Analyst's part of the weekly step (``intel_weekly``, Mondays): send the week to the Batch of the LAB, if it holds enough to learn from.
    The hypotheses are written when the poll brings the answer."""
    week = week_of(conn, at=at)
    out: dict[str, Any] = {"groups": len(week.groups), "stances": week.stances}
    if week.stances < MIN_STANCES:
        return out | {"skipped": "too_few_stances", "needed": MIN_STANCES}
    sent: Submitted = submit(conn, settings, [task_of(week, at=at)], at=at, ledger=ledger, client=client, transport=transport)
    return out | sent.counts()


__all__ = ["VERSION", "Checked", "Week", "check", "key_of", "request_of", "run", "settle", "task_of", "week_of", "write"]

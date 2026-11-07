"""What the orchestrator reads from the database and what it writes back (Plan Maestro IA, phase 3; ``fbi.ai.orchestrator``).

The orchestrator is the only writer of the shadow of phase 3, and this module is the only place where it touches a table. Everything in it is a plain
statement over a connection the CALLER owns: nothing here commits, rolls back or calls a model.

READS (all read-only):

* ``pending``       the passes of the AI layer that stored a packet before the kick-off, finished well, whose match has no row of the shadow yet
                    and that are not in the sample of nobody (a match assigned outside the sample is never selected again);
* ``reviewed``      the selections production reviewed in that pass - the ``rules`` rows of ``ai.pick_reviews`` for that packet - rebuilt as
                    ``review.Candidate`` so that the arms compare on EXACTLY the same selections, with the three scores the rules reviewer computed;
* ``existing``      what is already stored for an idempotency key (a task and the run that paid for it);
* ``batch_tasks``   the tasks of a pass that travel in the Message Batches API, each with the state of its batch item and the raw answer the poll kept
                    (``batch_task`` the same for one idempotency key);
* ``opus_today``, ``spent_today``, ``arm_today``     the day's counters the router and ``runtime.arm_pause`` read, from the rows the shadow itself wrote.

WRITES (one transaction per match, the caller commits; nothing here touches ``ai.evidence``, ``ai.fixture_passes`` or a review of ``rules``, ``llm``
or ``combined``):

* ``write_task``    a task of ``ai.agent_tasks`` and the run of ``ai.agent_runs`` that ended it. The pair is inserted already in its final state
                    (a task asked in real time is planned, asked and answered inside one call, so it never waits in the queue and nothing has to move
                    it along the lines of the state machine). The run goes first because the task points at it.
* ``queue_task``    the other kind of task, the one that goes to the Message Batches API (the Batch calendar): inserted ``queued`` with the custom id
                    of its batch item in ``route`` (``route`` never changes afterwards), and no run yet.
* ``end_task``      the end of a queued task, in one transaction with the rest of its pass: the run, and the task moved ``queued > running > done |
                    failed | skipped | expired`` along the lines the guard allows. A pass written this way and one written with ``write_task`` leave rows
                    of the same shape.
* ``lapse``         the queued tasks of a pass whose kick-off went by: ended ``expired`` (``kickoff_passed``), nothing is left queued for ever.
* ``write_state``   ONE row of ``ai.match_runs`` with ``run_kind = 'shadow'`` (the view ``ai.match_state`` reads only ``live``).
* ``write_review``  ONE row of ``ai.pick_reviews`` per candidate and engine, ``mode = 'shadow'``, complete: the numbers are the server's.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.arms import SALT
from fbi.ai.calendar import day_bounds, local_day
from fbi.ai.contracts.mcp import PassKind
from fbi.ai.idempotency import TaskIdentity
from fbi.ai.packet import Packet
from fbi.ai.review import Candidate
from fbi.core.decision_versions import DECISION_FAMILIES

STATE_VERSION: Final = "orch-v1"
"""The rule that writes a row of ``ai.match_runs`` for the shadow (``state_version``)."""
WINDOW: Final = timedelta(days=2)
"""How far back a pass is still shadowed: the AI layer works on today's matches, and a pass of an older day is history."""
ABANDON_BEFORE: Final = timedelta(minutes=100)
"""The Batch calendar's last moment: the ``final`` pass starts when the match is 100 minutes away, so a Batch stage that is not settled by then is
given up (``too_late``) and is never asked again in real time."""
LATE_MARGIN: Final = timedelta(minutes=15)
"""The passes whose kick-off is nearer than this go last in the selection (``runtime.FINAL_MARGIN``; they would be too late anyway)."""
SHADOW_RUN: Final = "shadow"
RUN_STATUSES: Final = ("ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip")
PAID_STATUSES: Final = ("ok", "invalid", "abstain")
"""The runs that hold a model's answer: at most one per idempotency key."""
TASK_STATES: Final = ("done", "failed", "skipped", "expired")
"""The states a task of this phase is inserted in (it is asked and answered inside one call of the orchestrator)."""

PENDING_SQL: Final = """
SELECT x.fixture_id, x.pass_kind, x.packet_id, x.known_at, x.kickoff_at, x.passed_at FROM (
    SELECT DISTINCT ON (p.fixture_id, p.pass, p.packet_id)
           p.fixture_id, p.pass AS pass_kind, p.packet_id, k.as_of AS known_at, f.kickoff_at, p.finished_at AS passed_at
      FROM ai.fixture_passes p
      JOIN ai.match_packets k ON k.id = p.packet_id
      JOIN core.fixtures f ON f.id = p.fixture_id
     WHERE p.status IN ('ok', 'partial') AND p.packet_id IS NOT NULL AND p.finished_at >= %(since)s
       AND f.kickoff_at > %(at)s AND k.as_of < f.kickoff_at
       AND EXISTS (SELECT 1 FROM ai.pick_reviews r
                    WHERE r.fixture_id = p.fixture_id AND r.packet_id = p.packet_id AND r.engine = 'rules' AND r.p_model IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM ai.shadow_assignments a
                        WHERE a.experiment = %(experiment)s AND a.fixture_id = p.fixture_id AND NOT a.sampled)
       AND NOT EXISTS (SELECT 1 FROM ai.match_runs m
                        WHERE m.fixture_id = p.fixture_id AND m.run_kind = 'shadow' AND m.pass_kind = p.pass
                          AND (m.packet_id = p.packet_id OR m.known_at = k.as_of))
       AND NOT EXISTS (SELECT 1 FROM ai.agent_tasks t
                        WHERE t.fixture_id = p.fixture_id AND t.run_kind = 'shadow' AND t.pass_kind = p.pass
                          AND t.route ->> 'packet_id' = p.packet_id::text
                          AND (t.route ->> 'mode' IS DISTINCT FROM 'batch'
                               OR (f.kickoff_at - %(abandon)s > %(at)s
                                   AND EXISTS (SELECT 1 FROM ai.batch_items bi
                                                WHERE bi.custom_id = t.route ->> 'batch_custom_id' AND bi.status IN ('submitting', 'submitted')))))
     ORDER BY p.fixture_id, p.pass, p.packet_id, p.finished_at DESC
) x
ORDER BY (x.kickoff_at - %(late)s > %(at)s) DESC, x.passed_at DESC, x.packet_id DESC, x.pass_kind
LIMIT %(limit)s
"""
"""The passes still to shadow, newest first, those that can still be answered before T-15 ahead of those that cannot. A pass is "orchestrated" when
a row of the shadow in ``ai.match_runs`` exists for it OR a task of the shadow carries its packet (``route.packet_id``) - except a pass of the Batch
calendar (``route.mode = 'batch'``), whose tasks are written before its state: that one is selected again as soon as NONE of its batch items is open
any more (the next stage can be planned) or once ``ABANDON_BEFORE`` of the kick-off has come (what is still open is given up). Until then it waits
without costing a query of the run."""

REVIEWED_SQL: Final = """
SELECT DISTINCT ON (r.market_key, r.selection, r.line)
       r.id, r.pick_id, r.market_key, r.selection, r.line, r.odds, r.bookmaker_id, b.name AS bookmaker, r.p_model, r.p_low, r.p_market, r.ev,
       r.context_score, r.model_score, r.market_score, r.fair_odds, r.minimum_playable_odds, f.kickoff_at
  FROM ai.pick_reviews r
  JOIN core.fixtures f ON f.id = r.fixture_id
  LEFT JOIN market.bookmakers b ON b.id = r.bookmaker_id
 WHERE r.fixture_id = %(fixture)s AND r.packet_id = %(packet)s AND r.engine = 'rules' AND r.p_model IS NOT NULL
 ORDER BY r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""
"""The selections production reviewed in a pass: the newest ``rules`` review of each (market, selection, line) for that packet."""

EXISTING_SQL: Final = """
SELECT t.state, r.status, r.output, r.cost_usd, r.model
  FROM ai.agent_tasks t
  LEFT JOIN ai.agent_runs r ON r.idem_key = t.idem_key AND r.status IN ('ok', 'invalid', 'abstain')
 WHERE t.idem_key = %(key)s
"""
OPUS_SQL: Final = """
SELECT count(*), COALESCE(sum(cost_usd), 0)
  FROM ai.agent_runs
 WHERE run_kind = 'shadow' AND task_kind = 'escalation' AND status IN ('ok', 'invalid', 'abstain')
   AND started_at >= %(since)s AND started_at < %(until)s
"""
OPUS_QUEUED_SQL: Final = """
SELECT count(*), COALESCE(sum(est_cost_usd), 0)
  FROM ai.agent_tasks
 WHERE run_kind = 'shadow' AND task_kind = 'escalation' AND state IN ('queued', 'running')
   AND created_at >= %(since)s AND created_at < %(until)s
"""
SPENT_SQL: Final = """
SELECT model, COALESCE(sum(cost_usd), 0)
  FROM ai.agent_runs
 WHERE run_kind = 'shadow' AND task_kind <> 'escalation' AND status IN ('ok', 'invalid', 'abstain') AND model IS NOT NULL
   AND started_at >= %(since)s AND started_at < %(until)s
 GROUP BY model
"""
ARM_SQL: Final = """
SELECT engine, count(DISTINCT (fixture_id, packet_id)) FILTER (WHERE status IN ('ok', 'invalid_output')),
       count(DISTINCT (fixture_id, packet_id)) FILTER (WHERE status = 'invalid_output')
  FROM ai.pick_reviews
 WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1') AND mode = 'shadow' AND reviewed_at >= %(since)s AND reviewed_at < %(until)s
 GROUP BY engine
"""
USAGE_SQL: Final = """
SELECT input_tokens, output_tokens, cached_tokens, cache_write_tokens, thinking_tokens, latency_ms FROM ai.usage WHERE id = %(id)s
"""

RUN_SQL: Final = """
INSERT INTO ai.agent_runs (run_kind, reason, parent_run_id, task_kind, pass_kind, fixture_id, candidates, started_at, finished_at, known_at, model,
    effort, agent, agent_version, prompt_version, schema_version, router_version, package_hash, slice_hash, idem_key, attempt, evidence_ids,
    data_refs, output, verdict, input_tokens, output_tokens, cached_tokens, cache_write_tokens, thinking_tokens, cost_usd, workspace, key_label,
    usage_id, latency_ms, status, error, batch_id, custom_id)
VALUES ('shadow', %(reason)s, %(parent)s, %(task_kind)s, %(pass_kind)s, %(fixture)s, %(candidates)s, %(started)s, %(finished)s, %(known_at)s,
    %(model)s, %(effort)s, %(agent)s, %(agent_version)s, %(prompt_version)s, %(schema_version)s, %(router_version)s, %(package_hash)s,
    %(slice_hash)s, %(idem_key)s, 1, %(evidence)s, %(data_refs)s, %(output)s, %(verdict)s, %(input_tokens)s, %(output_tokens)s, %(cached)s,
    %(cache_write)s, %(thinking)s, %(cost)s, %(workspace)s, %(key_label)s, %(usage_id)s, %(latency_ms)s, %(status)s, %(error)s, %(run_batch)s, %(run_custom)s)
RETURNING id
"""
TASK_SQL: Final = """
INSERT INTO ai.agent_tasks (idem_key, custom_id, workspace, agent, agent_version, prompt_version, schema_version, model, effort, input_version,
    input_hash, pass_kind, fixture_id, candidates, run_kind, task_kind, reason, router_version, route, package_hash, priority, est_cost_usd, state,
    created_at, not_before, deadline_at, queued_at, started_at, finished_at, attempts, last_run_id)
VALUES (%(idem_key)s, %(custom_id)s, 'lab', %(agent)s, %(agent_version)s, %(prompt_version)s, %(schema_version)s, %(model)s, %(effort)s,
    %(input_version)s, %(input_hash)s, %(pass_kind)s, %(fixture)s, %(candidates)s, 'shadow', %(task_kind)s, %(reason)s, %(router_version)s, %(route)s,
    %(package_hash)s, %(priority)s, %(est)s, %(state)s, %(created)s, %(created)s, %(deadline)s, %(queued)s, %(started)s, %(finished)s, %(attempts)s,
    %(run_id)s)
RETURNING id
"""
STATE_SQL: Final = """
INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, package_hash, packet_id,
    elapsed_ms, slices, blocking, flags, data_status, market_status, model_status, research_status, agents, contradictions, candidates, risks, final)
VALUES (%(fixture)s, 'shadow', %(pass_kind)s, %(known_at)s, %(created_at)s, %(state)s, %(package_version)s, %(package_hash)s, %(packet)s,
    %(elapsed_ms)s, %(slices)s, %(blocking)s, %(flags)s, %(data_status)s, %(market_status)s, %(model_status)s, %(research_status)s, %(agents)s,
    %(contradictions)s, %(candidates)s, %(risks)s, %(final)s)
ON CONFLICT (fixture_id, run_kind, pass_kind, known_at) DO NOTHING
RETURNING id
"""
REVIEW_SQL: Final = """
INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, pick_id, market_key, selection, line, odds, bookmaker_id, p_model, p_low, p_market, edge, ev,
    engine, engine_version, provider, model, packet_id, input_hash, decision, confidence, context_score, model_score, market_score, fair_odds,
    minimum_playable_odds, output, sources, evidence_ids, tool_calls, usage_ids, cost_usd, mode, status, error)
VALUES (%(at)s, %(fixture)s, %(pick)s, %(market)s, %(selection)s, %(line)s, %(odds)s, %(bookmaker)s, %(p_model)s, %(p_low)s, %(p_market)s, %(edge)s,
    %(ev)s, %(engine)s, %(version)s, %(provider)s, %(model)s, %(packet)s, %(hash)s, %(decision)s, %(confidence)s, %(context)s, %(model_score)s,
    %(market_score)s, %(fair)s, %(minimum)s, %(output)s, %(sources)s, %(evidence)s, '[]'::jsonb, %(usage)s, %(cost)s, 'shadow', %(status)s, %(error)s)
RETURNING id
"""
NEWEST_SQL: Final = """
SELECT DISTINCT ON (engine) engine, id, engine_version, input_hash, mode FROM ai.pick_reviews
 WHERE fixture_id = %s AND market_key = %s AND selection = %s AND line = %s AND engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')
 ORDER BY engine, reviewed_at DESC, id DESC
"""


# -- reads ---------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Work:
    """A pass of the AI layer that stored a packet and has no shadow yet."""

    fixture_id: int
    pass_kind: PassKind
    packet_id: int
    known_at: datetime
    kickoff_at: datetime
    passed_at: datetime

    def where(self) -> str:
        return f"match {self.fixture_id}, pass {self.pass_kind}, packet {self.packet_id}"


def pending(
    conn: psycopg.Connection[Any], *, at: datetime, limit: int, experiment: str = SALT
) -> list[Work]:
    """The passes to shadow, newest first (see ``PENDING_SQL``). Read-only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            PENDING_SQL,
            {
                "since": at - WINDOW,
                "at": at,
                "late": LATE_MARGIN,
                "limit": limit,
                "experiment": experiment,
                "abandon": ABANDON_BEFORE,
            },
        )
        return [
            Work(
                fixture_id=int(r["fixture_id"]),
                pass_kind=r["pass_kind"],
                packet_id=int(r["packet_id"]),
                known_at=r["known_at"],
                kickoff_at=r["kickoff_at"],
                passed_at=r["passed_at"],
            )
            for r in cur.fetchall()
        ]


@dataclass(frozen=True, slots=True)
class Scores:
    """What the rules reviewer computed for a selection, all server-side: the three scores and the fair and minimum playable odds. The shadow rows
    carry them as the live reviewer's do; no model writes any of them."""

    context: Decimal | None = None
    model: Decimal | None = None
    market: Decimal | None = None
    fair: Decimal | None = None
    minimum: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Reviewed:
    """The selections production reviewed in one pass, with their server-side scores (by the candidate's ``key``)."""

    candidates: tuple[Candidate, ...]
    scores: dict[tuple[int, str, str, Decimal], Scores] = field(default_factory=dict)


def reviewed(conn: psycopg.Connection[Any], work: Work) -> Reviewed:
    """The selections production reviewed in this pass, rebuilt as ``review.Candidate`` (``Candidate.from_state`` has nothing to read: the reviewer
    stores the columns, not the state), ordered by market, selection and line."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(REVIEWED_SQL, {"fixture": work.fixture_id, "packet": work.packet_id})
        rows = cur.fetchall()
    candidates: list[Candidate] = []
    scores: dict[tuple[int, str, str, Decimal], Scores] = {}
    for r in rows:
        c = Candidate(
            fixture_id=work.fixture_id,
            market_key=str(r["market_key"]),
            selection=str(r["selection"]),
            line=Decimal(r["line"]),
            p_model=Decimal(r["p_model"]),
            kickoff_at=r["kickoff_at"],
            pick_id=r["pick_id"],
            odds=r["odds"],
            bookmaker_id=r["bookmaker_id"],
            bookmaker=r["bookmaker"],
            p_low=r["p_low"],
            p_market=r["p_market"],
            ev=r["ev"],
        )
        candidates.append(c)
        scores[c.key] = Scores(
            r["context_score"],
            r["model_score"],
            r["market_score"],
            r["fair_odds"],
            r["minimum_playable_odds"],
        )
    return Reviewed(tuple(candidates), scores)


COUNTS_SOURCE_VERSION: Final = "fam-counts-v1"
"""Where the Statistics Agent's candidates come from (IA-014): the decisions of the FAMILIES (``decision-fam-v1``) of the match as of the moment of the
pass, beside the selections production reviewed. Production never reviews a corner or a card (``ai.pick_reviews`` of ``rules`` are the picks of
``picks.picks``: goals and result), so a pass named from ``reviewed`` alone had no count to ask about, and the agent ran 0 times from 6 Nov 2026
(``model_status.stats.note = 'no_count_to_assess'``). A pass written before this source existed has no ``model_status.stats.counts`` and, in the
Batch calendar, no ``route.counts``: it is a pass whose counts came from ``reviewed`` alone, and it is resumed as one. Changing what is read, or how a
decision becomes a candidate, is a new name here, never an edit."""
COUNT_MARKETS: Final[dict[str, tuple[str, str]]] = {
    "CORNERS_OU": ("CORNERS", "corners_ft@v1"),
    "CORNERS_OU_HOME": ("CORNERS", "corners_ft@v1"),
    "CORNERS_OU_AWAY": ("CORNERS", "corners_ft@v1"),
    "CORNERS_1X2": ("CORNERS", "corners_ft@v1"),
    "CARDS_OU": ("CARDS", "cards_lines_ft@v1"),
    "CARDS_OU_HOME": ("CARDS", "cards_lines_ft@v1"),
    "CARDS_OU_AWAY": ("CARDS", "cards_lines_ft@v1"),
    "CARDS_1X2": ("CARDS", "cards_lines_ft@v1"),
}
"""``fam-counts-v1``: the markets of a family's decision that are a candidate of the Statistics Agent, with the agent's family (``contracts.base.COUNTS``)
and the settlement rule of the catalogue that grades it (``agents.stats.SETTLEMENT``; a test holds the three together). Only the WHOLE match: a key of
a half is never here (the catalogue cannot grade the corners of a half, and no convention exists for the cards of one), nor the yellow cards
(``yellow_ft`` is not the rule of the CARDS family), nor the goals of the halves (no agent reads them)."""

FAMILY_COUNTS_SQL: Final = """
SELECT DISTINCT ON (d.market_key, d.model_name)
       d.id, d.known_at, d.market_key, d.selection, d.line, d.model_name, d.odds, d.bookmaker_id, b.name AS bookmaker, d.price_at, d.n_bookmakers,
       d.p_model, d.p_low, d.p_high, d.p_push, d.p_market, d.ev_raw, d.kickoff_at
  FROM intel.decisions d
  LEFT JOIN market.bookmakers b ON b.id = d.bookmaker_id
 WHERE d.decision_version = %(version)s AND d.fixture_id = %(fixture)s AND d.market_key = ANY(%(markets)s)
   AND d.known_at <= %(at)s AND d.known_at < d.kickoff_at
 ORDER BY d.market_key, d.model_name, d.known_at DESC, d.id DESC
"""
"""The newest decision of each market of the families (per model) known by the moment of the pass. A family decides the best line of each market of
a match at each of its passes (``fbi.familydecisions.decide.candidates``) and writes only what is news, so the newest row of a market is the selection it
last chose there; an older line of the same market is one it moved away from. Read-only, and strictly as of ``at``: a decision written later is
never read, so the same pass reads the same candidates whenever it is derived again (the audit, a resumed pass of the Batch)."""


@dataclass(frozen=True, slots=True)
class FamilyCounts:
    """The count candidates of a match from the families' decisions, with the id of the decision each one comes from (in the same order)."""

    candidates: tuple[Candidate, ...] = ()
    decision_ids: tuple[int, ...] = ()
    source: str = COUNTS_SOURCE_VERSION

    def decision_of(self, c: Candidate) -> int | None:
        """The decision ``c`` is (the very candidate read here, not one of the same selection that came from elsewhere), or None."""
        return next((d for x, d in zip(self.candidates, self.decision_ids, strict=True) if x == c), None)


def family_counts(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, version: str = DECISION_FAMILIES) -> FamilyCounts:
    """The full-time corners and cards the families decided for a match by ``at`` (``FAMILY_COUNTS_SQL``), rebuilt as ``review.Candidate`` with the
    numbers the decision holds and nothing more: the model's probability and interval, the best price, its book and moment, the market's fair
    probability and the raw expected value. No pick stands behind them (``pick_id`` is None). Ordered by market, selection and line."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FAMILY_COUNTS_SQL, {"version": version, "fixture": fixture_id, "markets": sorted(COUNT_MARKETS), "at": at})
        rows = cur.fetchall()
    pairs: list[tuple[Candidate, int]] = []
    for r in rows:
        c = Candidate(
            fixture_id=fixture_id,
            market_key=str(r["market_key"]),
            selection=str(r["selection"]),
            line=Decimal(r["line"]),
            p_model=Decimal(r["p_model"]),
            kickoff_at=r["kickoff_at"],
            odds=r["odds"],
            bookmaker_id=r["bookmaker_id"],
            bookmaker=r["bookmaker"],
            p_low=r["p_low"],
            p_high=r["p_high"],
            p_push=r["p_push"],
            p_market=r["p_market"],
            ev=r["ev_raw"],
            model=r["model_name"],
            n_bookmakers=r["n_bookmakers"],
            price_at=r["price_at"],
        )
        pairs.append((c, int(r["id"])))
    pairs.sort(key=lambda pair: (pair[0].market_key, pair[0].selection, pair[0].line, pair[1]))
    return FamilyCounts(tuple(c for c, _ in pairs), tuple(i for _, i in pairs))


@dataclass(frozen=True, slots=True)
class Existing:
    """What is stored for an idempotency key: the task is there, and perhaps the run that paid for it."""

    state: str
    status: str | None
    output: dict[str, Any] | None
    cost: Decimal
    model: str | None


def existing(conn: psycopg.Connection[Any], key: str) -> Existing | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EXISTING_SQL, {"key": key})
        row = cur.fetchone()
    if row is None:
        return None
    return Existing(
        state=str(row["state"]),
        status=row["status"],
        output=None if row["output"] is None else dict(row["output"]),
        cost=Decimal(row["cost_usd"] or 0),
        model=row["model"],
    )


BATCH_TASK_SQL: Final = """
SELECT t.id, t.idem_key, t.state, t.task_kind, t.route, t.package_hash, t.created_at, t.deadline_at,
       i.id AS item_id, i.status AS item_status, i.error AS item_error, i.usage_id, i.model AS item_model, i.batch_id AS item_batch,
       i.context -> 'result' AS result, i.context ->> 'idem' AS item_idem, u.cost_usd AS item_cost
  FROM ai.agent_tasks t
  LEFT JOIN LATERAL (
        SELECT bi.* FROM ai.batch_items bi WHERE bi.custom_id = t.route ->> 'batch_custom_id'
         ORDER BY (bi.status IN ('submitting', 'submitted')) DESC, bi.id DESC LIMIT 1) i ON true
  LEFT JOIN ai.usage u ON u.id = i.usage_id
 WHERE t.run_kind = 'shadow' AND t.route ->> 'mode' = 'batch' AND {where}
 ORDER BY t.id
"""
"""A task of the Batch calendar with the batch item that carries it (the newest, an open one first) and what the poll kept of its answer
(``context.result``, written by ``lab.settle_lab`` for ``context.lab = 'shadow'``)."""
LAPSED_SQL: Final = """
SELECT t.id FROM ai.agent_tasks t JOIN core.fixtures f ON f.id = t.fixture_id
 WHERE t.run_kind = 'shadow' AND t.state = 'queued' AND t.route ->> 'mode' = 'batch' AND f.kickoff_at <= %(at)s
 ORDER BY t.id LIMIT %(limit)s
"""
CLOSING_SQL: Final = """
SELECT id, idem_key, task_kind, pass_kind, fixture_id, candidates, created_at, agent, agent_version, prompt_version, schema_version, router_version,
       package_hash, effort
  FROM ai.agent_tasks WHERE id = ANY(%(ids)s) AND state = 'queued' ORDER BY id
"""
LAPSE_RUN_SQL: Final = """
INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, candidates, started_at, finished_at, effort, agent, agent_version,
    prompt_version, schema_version, router_version, package_hash, idem_key, attempt, status, error, workspace)
VALUES ('shadow', %(reason)s, %(task_kind)s, %(pass_kind)s, %(fixture)s, %(candidates)s, %(started)s, %(finished)s,
    %(effort)s, %(agent)s, %(agent_version)s, %(prompt_version)s, %(schema_version)s, %(router_version)s, %(package_hash)s, %(idem_key)s, 1,
    'expired', %(error)s, NULL)
RETURNING id
"""


@dataclass(frozen=True, slots=True)
class StoredTask:
    """A task of the Batch calendar as the database holds it: the task, its batch item and the raw answer the poll kept."""

    task_id: int
    key: str
    state: str
    task_kind: str
    route: dict[str, Any]
    package_hash: str | None
    created_at: datetime
    deadline_at: datetime
    item_status: str | None = None
    """``ai.batch_items.status``: submitting, submitted (open), succeeded, late, invalid, errored, canceled, expired or abandoned; None = no item."""
    item_error: str | None = None
    usage_id: int | None = None
    item_model: str | None = None
    item_batch: int | None = None
    result: dict[str, Any] | None = None
    """What ``lab.settle_lab`` kept of the answer: ``{"shadow": 1, "ok": bool, "data": {...}, "model", "usage_id", "cost", "late", "error"}``."""
    item_idem: str | None = None
    """The idempotency key of the task that queued the item (another task with the same custom id shares the answer and does not pay it twice)."""
    cost: Decimal = Decimal(0)

    @property
    def custom_id(self) -> str:
        return str(self.route.get("batch_custom_id") or "")

    @property
    def open(self) -> bool:
        """The task still waits for its answer (the item is not settled)."""
        return self.state in ("planned", "queued", "running")


def _stored(r: dict[str, Any]) -> StoredTask:
    return StoredTask(
        task_id=int(r["id"]),
        key=str(r["idem_key"]),
        state=str(r["state"]),
        task_kind=str(r["task_kind"]),
        route=dict(r["route"] or {}),
        package_hash=r["package_hash"],
        created_at=r["created_at"],
        deadline_at=r["deadline_at"],
        item_status=r["item_status"],
        item_error=r["item_error"],
        usage_id=r["usage_id"],
        item_model=r["item_model"],
        item_batch=r["item_batch"],
        result=None if not isinstance(r["result"], dict) else dict(r["result"]),
        item_idem=r["item_idem"],
        cost=Decimal(r["item_cost"] or 0),
    )


def batch_tasks(conn: psycopg.Connection[Any], work: Work) -> list[StoredTask]:
    """The tasks of this pass that travel in the Message Batches API (empty = the pass is not a pass of the Batch calendar, or has not started)."""
    where = "t.fixture_id = %(fixture)s AND t.pass_kind = %(pass)s AND t.route ->> 'packet_id' = %(packet)s"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            BATCH_TASK_SQL.format(where=where),
            {"fixture": work.fixture_id, "pass": work.pass_kind, "packet": str(work.packet_id)},
        )
        return [_stored(r) for r in cur.fetchall()]


def batch_task(conn: psycopg.Connection[Any], key: str) -> StoredTask | None:
    """The task of the Batch calendar with this idempotency key, if there is one."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(BATCH_TASK_SQL.format(where="t.idem_key = %(key)s"), {"key": key})
        row = cur.fetchone()
    return None if row is None else _stored(row)


def close_tasks(conn: psycopg.Connection[Any], ids: Sequence[int], *, at: datetime, error: str) -> int:
    """End queued tasks of the Batch calendar WITHOUT an answer: an ``expired`` run (unpaid, ``error`` says why) and the task ``expired``. Whatever the
    provider still does with their items is the poll's: it keeps the raw answer and nobody reads it. Returns the number of tasks."""
    if not ids:
        return 0
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLOSING_SQL, {"ids": list(ids)})
        rows = list(cur.fetchall())
    done = 0
    for r in rows:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(START_SQL, {"started": at, "id": r["id"]})
            if cur.fetchone() is None:
                continue
            finished = max(at, r["created_at"])
            cur.execute(
                LAPSE_RUN_SQL,
                {
                    "reason": f"closed unanswered: {error}"[:200], "error": error[:300], "task_kind": r["task_kind"], "pass_kind": r["pass_kind"],
                    "fixture": r["fixture_id"], "candidates": list(r["candidates"]), "started": r["created_at"], "finished": finished,
                    "effort": r["effort"], "agent": r["agent"], "agent_version": r["agent_version"], "prompt_version": r["prompt_version"],
                    "schema_version": r["schema_version"], "router_version": r["router_version"], "package_hash": r["package_hash"],
                    "idem_key": r["idem_key"],
                },
            )
            run = cur.fetchone()
            assert run is not None
            cur.execute(END_SQL, {"state": "expired", "finished": finished, "run": run[0], "id": r["id"]})
            done += 1
    return done


def lapse(conn: psycopg.Connection[Any], *, at: datetime, limit: int = 50) -> int:
    """End the queued tasks of the Batch calendar whose match has started (``kickoff_passed``): a pass nobody finished leaves nothing queued for ever."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LAPSED_SQL, {"at": at, "limit": limit})
        ids = [int(r[0]) for r in cur.fetchall()]
    return close_tasks(conn, ids, at=at, error="kickoff_passed")


def opus_today(conn: psycopg.Connection[Any], at: datetime) -> tuple[int, Decimal]:
    """How many calls to Opus the shadow paid for on this Bogotá day and what they cost (the cap of ``router.PARAMS['opus_calls']['shadow']``).
    An Opus task waiting in the Message Batches API counts as a call at its estimate: it is a call already decided, and the cap must hold for the
    ones the poll has not answered yet."""
    since, until = day_bounds(local_day(at))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OPUS_SQL, {"since": since, "until": until})
        row = cur.fetchone()
        cur.execute(OPUS_QUEUED_SQL, {"since": since, "until": until})
        waiting = cur.fetchone()
    calls, cost = (int(row[0]), Decimal(row[1])) if row else (0, Decimal(0))
    if waiting:
        calls, cost = calls + int(waiting[0]), cost + Decimal(waiting[1])
    return calls, cost


def spent_today(conn: psycopg.Connection[Any], at: datetime) -> dict[str, Decimal]:
    """What the shadow's runs (but Opus') cost on this Bogotá day, by model."""
    since, until = day_bounds(local_day(at))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"since": since, "until": until})
        return {str(m): Decimal(c) for m, c in cur.fetchall()}


def arm_today(conn: psycopg.Connection[Any], engine: str, at: datetime) -> tuple[int, int]:
    """(answers, invalid outputs) of an arm on this Bogotá day: passes with a review of the arm that was answered / that was an invalid output."""
    since, until = day_bounds(local_day(at))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(ARM_SQL, {"since": since, "until": until})
        rows = {str(r[0]): (int(r[1]), int(r[2])) for r in cur.fetchall()}
    return rows.get(engine, (0, 0))


@dataclass(frozen=True, slots=True)
class Tokens:
    input: int = 0
    output: int = 0
    cached: int = 0
    cache_write: int = 0
    thinking: int = 0
    latency_ms: int | None = None


def tokens_of(conn: psycopg.Connection[Any], usage_id: int | None) -> Tokens | None:
    """The tokens the ledger billed for a call (None when the row is not visible)."""
    if usage_id is None:
        return None
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(USAGE_SQL, {"id": usage_id})
        row = cur.fetchone()
    if row is None:
        return None
    return Tokens(
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
        int(row[4] or 0),
        None if row[5] is None else int(row[5]),
    )


# -- writes --------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """A task and the run that ended it, as they are stored. ``parent_key`` is the idempotency key of the task whose run is this run's parent
    (Opus' run points at the Council's)."""

    identity: TaskIdentity
    task_kind: str
    reason: str
    route: dict[str, Any]
    est_cost: Decimal
    priority: int
    deadline_at: datetime
    state: str
    status: str
    started_at: datetime
    finished_at: datetime
    known_at: datetime
    package_hash: str
    slice_hash: str
    model: str | None = None
    """The model that answered (None when no call was made)."""
    attempts: int = 0
    output: dict[str, Any] | None = None
    verdict: str | None = None
    error: str | None = None
    tokens: Tokens | None = None
    cost: Decimal = Decimal(0)
    usage_id: int | None = None
    evidence_ids: tuple[int, ...] = ()
    data_refs: tuple[str, ...] = ()
    parent_key: str | None = None
    workspace: str = "PREDIGOL-LAB"
    key_label: str = "worker-lab"
    router_version: str = "router-v1"
    batch_id: int | None = None
    """``ai.batches.id`` of the batch item that answered (a task of the Batch calendar), for the run."""
    custom_id: str | None = None
    """The custom id of that batch item, for the run."""


def _money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.000001"))


def _insert_run(cur: psycopg.Cursor[Any], rec: TaskRecord, runs: dict[str, int]) -> int:
    """The run that ended a task, whatever came of it (the rules of the table are kept by building the row right: see ``write_task``)."""
    ident = rec.identity
    key = ident.key
    paid = rec.status in PAID_STATUSES
    t = rec.tokens or Tokens()
    unpaid_error = (
        rec.error if rec.error else ("not_ok" if rec.status not in ("ok", "abstain") else None)
    )
    cur.execute(
        RUN_SQL,
        {
            "reason": rec.reason[:200],
            "parent": runs.get(rec.parent_key) if rec.parent_key else None,
            "task_kind": rec.task_kind,
            "pass_kind": ident.pass_kind,
            "fixture": ident.fixture_id,
            "candidates": list(ident.candidates),
            "started": rec.started_at,
            "finished": max(rec.finished_at, rec.started_at),
            "known_at": rec.known_at,
            "model": rec.model if paid else None,
            "effort": ident.effort,
            "agent": ident.agent,
            "agent_version": ident.agent_version,
            "prompt_version": ident.prompt_version,
            "schema_version": ident.schema_version,
            "router_version": rec.router_version,
            "package_hash": rec.package_hash,
            "slice_hash": rec.slice_hash,
            "idem_key": key,
            "evidence": list(rec.evidence_ids),
            "data_refs": list(rec.data_refs),
            "output": Jsonb(rec.output)
            if rec.output is not None and rec.status in ("ok", "abstain")
            else None,
            "verdict": rec.verdict if rec.status in ("ok", "abstain") else None,
            "input_tokens": t.input if paid else None,
            "output_tokens": t.output if paid else None,
            "cached": t.cached if paid else None,
            "cache_write": t.cache_write if paid else None,
            "thinking": t.thinking if paid else None,
            "cost": _money(rec.cost) if paid else Decimal(0),
            "workspace": rec.workspace,
            "key_label": rec.key_label,
            "usage_id": rec.usage_id,
            "latency_ms": t.latency_ms if paid else None,
            "status": rec.status,
            "error": None
            if rec.status in ("ok", "abstain")
            else (unpaid_error or "not_ok")[:2000],
            "run_batch": rec.batch_id,
            "run_custom": rec.custom_id,
        },
    )
    run = cur.fetchone()
    assert run is not None
    run_id = int(run[0])
    runs[key] = run_id
    return run_id


def write_task(conn: psycopg.Connection[Any], rec: TaskRecord, runs: dict[str, int]) -> int:
    """The run, then the task that points at it; returns the run's id and remembers it in ``runs`` by idempotency key (a later run may be its child).

    The rules of the tables are kept by building the pair right: a paid run (``ok``, ``invalid``, ``abstain``) has the model and the three token
    counts, ``ok`` and ``abstain`` have the output, anything else has none; a run that was not paid (``skipped``, ``budget_skip``, ``timeout``) has
    cost zero and no tokens; every run that is not ``ok`` or ``abstain`` says why."""
    ident = rec.identity
    key = ident.key
    with conn.cursor(row_factory=tuple_row) as cur:
        run_id = _insert_run(cur, rec, runs)
        called = rec.state in ("done", "failed")
        cur.execute(
            TASK_SQL,
            {
                "idem_key": key,
                "custom_id": key[:48],
                "agent": ident.agent,
                "agent_version": ident.agent_version,
                "prompt_version": ident.prompt_version,
                "schema_version": ident.schema_version,
                "model": ident.model,
                "effort": ident.effort,
                "input_version": ident.input_version,
                "input_hash": ident.input_hash,
                "pass_kind": ident.pass_kind,
                "fixture": ident.fixture_id,
                "candidates": list(ident.candidates),
                "task_kind": rec.task_kind,
                "reason": rec.reason[:200],
                "router_version": rec.router_version,
                "route": Jsonb(rec.route),
                "package_hash": rec.package_hash,
                "priority": rec.priority,
                "est": _money(max(rec.est_cost, Decimal("0.000001"))),
                "state": rec.state,
                "created": rec.started_at,
                "deadline": max(rec.deadline_at, rec.started_at),
                "queued": rec.started_at if called else None,
                "started": rec.started_at if called else None,
                "finished": max(rec.finished_at, rec.started_at),
                "attempts": min(3, max(rec.attempts, 1 if called else 0)),
                "run_id": run_id,
            },
        )
    return run_id


QUEUED_SQL: Final = """
INSERT INTO ai.agent_tasks (idem_key, custom_id, workspace, agent, agent_version, prompt_version, schema_version, model, effort, input_version,
    input_hash, pass_kind, fixture_id, candidates, run_kind, task_kind, reason, router_version, route, package_hash, priority, est_cost_usd, state,
    created_at, not_before, deadline_at, queued_at, attempts, batch_id)
VALUES (%(idem_key)s, %(custom_id)s, 'lab', %(agent)s, %(agent_version)s, %(prompt_version)s, %(schema_version)s, %(model)s, %(effort)s,
    %(input_version)s, %(input_hash)s, %(pass_kind)s, %(fixture)s, %(candidates)s, 'shadow', %(task_kind)s, %(reason)s, %(router_version)s, %(route)s,
    %(package_hash)s, %(priority)s, %(est)s, 'queued', %(created)s, %(created)s, %(deadline)s, %(created)s, 0, %(batch)s)
RETURNING id
"""
START_SQL: Final = """
UPDATE ai.agent_tasks SET state = 'running', attempts = attempts + 1, started_at = %(started)s WHERE id = %(id)s AND state = 'queued' RETURNING id
"""
END_SQL: Final = """
UPDATE ai.agent_tasks SET state = %(state)s, finished_at = %(finished)s, last_run_id = %(run)s WHERE id = %(id)s AND state = 'running' RETURNING id
"""
OPEN_BATCH_SQL: Final = """
SELECT batch_id FROM ai.batch_items WHERE custom_id = %(cid)s AND status IN ('submitting', 'submitted') ORDER BY id DESC LIMIT 1
"""
LINK_SQL: Final = "UPDATE ai.agent_tasks SET batch_id = %(batch)s WHERE id = %(id)s AND state = 'queued' AND batch_id IS DISTINCT FROM %(batch)s"


def open_batch_of(conn: psycopg.Connection[Any], custom_id: str) -> int | None:
    """``ai.batches.id`` of the open batch item of a custom id (None when no item of it is open)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OPEN_BATCH_SQL, {"cid": custom_id})
        row = cur.fetchone()
    return None if row is None else int(row[0])


def link_batch(conn: psycopg.Connection[Any], task_id: int, batch_id: int | None) -> None:
    """Point a queued task at the batch that carries it now (a task whose item was abandoned and asked again moves to the new batch)."""
    if batch_id is None:
        return
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LINK_SQL, {"batch": batch_id, "id": task_id})


def queue_task(conn: psycopg.Connection[Any], rec: TaskRecord, *, custom_id: str, batch_id: int | None) -> int:
    """A task that goes to the Message Batches API, inserted ``queued`` with no run: ``route`` says ``mode = batch`` and the custom id of its item
    (the rows of the guard: ``route`` never changes, the state moves only along the plan's lines). Its ``batch_id`` takes it out of the reservations
    of the queue - the batch item holds its own. Returns the task's id."""
    ident = rec.identity
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            QUEUED_SQL,
            {
                "idem_key": ident.key,
                "custom_id": ident.key[:48],
                "agent": ident.agent,
                "agent_version": ident.agent_version,
                "prompt_version": ident.prompt_version,
                "schema_version": ident.schema_version,
                "model": ident.model,
                "effort": ident.effort,
                "input_version": ident.input_version,
                "input_hash": ident.input_hash,
                "pass_kind": ident.pass_kind,
                "fixture": ident.fixture_id,
                "candidates": list(ident.candidates),
                "task_kind": rec.task_kind,
                "reason": rec.reason[:200],
                "router_version": rec.router_version,
                "route": Jsonb(rec.route | {"mode": "batch", "batch_custom_id": custom_id}),
                "package_hash": rec.package_hash,
                "priority": rec.priority,
                "est": _money(max(rec.est_cost, Decimal("0.000001"))),
                "created": rec.started_at,
                "deadline": max(rec.deadline_at, rec.started_at),
                "batch": batch_id,
            },
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def end_task(conn: psycopg.Connection[Any], rec: TaskRecord, runs: dict[str, int], task_id: int) -> int:
    """The end of a queued task: its run, and the task along ``queued > running > (done | failed | skipped | expired)`` with the run as its last. The
    attempt counts when the task starts, as the guard demands. Returns the run's id. A task that is not queued any more is a bug: it raises."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(START_SQL, {"started": rec.started_at, "id": task_id})
        if cur.fetchone() is None:
            raise LookupError(f"task {task_id} is not queued")
        run_id = _insert_run(cur, rec, runs)
        cur.execute(
            END_SQL,
            {"state": rec.state, "finished": max(rec.finished_at, rec.started_at), "run": run_id, "id": task_id},
        )
        if cur.fetchone() is None:
            raise LookupError(f"task {task_id} did not end")
    return run_id


@dataclass(frozen=True, slots=True)
class StateRecord:
    """The shadow row of ``ai.match_runs`` for a pass: the package, the agents that ran, the contradictions, the candidates and the final."""

    work: Work
    created_at: datetime
    package_version: str
    package_hash: str
    elapsed_ms: int
    slices: list[dict[str, Any]]
    blocking: tuple[str, ...]
    flags: tuple[str, ...]
    model_status: dict[str, Any]
    research_status: dict[str, Any]
    agents: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    final: dict[str, Any]
    data_status: dict[str, Any] = field(default_factory=dict)
    market_status: dict[str, Any] = field(default_factory=dict)
    risks: list[Any] = field(default_factory=list)


def write_state(conn: psycopg.Connection[Any], rec: StateRecord) -> int | None:
    """The shadow row of the pass; None when one already exists (the same match, pass and moment of knowledge)."""
    w = rec.work
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            STATE_SQL,
            {
                "fixture": w.fixture_id,
                "pass_kind": w.pass_kind,
                "known_at": w.known_at,
                "created_at": max(rec.created_at, w.known_at),
                "state": STATE_VERSION,
                "package_version": rec.package_version,
                "package_hash": rec.package_hash,
                "packet": w.packet_id,
                "elapsed_ms": rec.elapsed_ms,
                "slices": Jsonb(rec.slices),
                "blocking": list(rec.blocking),
                "flags": list(rec.flags),
                "data_status": Jsonb(rec.data_status),
                "market_status": Jsonb(rec.market_status),
                "model_status": Jsonb(rec.model_status),
                "research_status": Jsonb(rec.research_status),
                "agents": Jsonb(rec.agents),
                "contradictions": Jsonb(rec.contradictions),
                "candidates": Jsonb(rec.candidates),
                "risks": Jsonb(rec.risks),
                "final": Jsonb(rec.final),
            },
        )
        row = cur.fetchone()
    return None if row is None else int(row[0])


@dataclass(frozen=True, slots=True)
class ReviewRow:
    """One review of the shadow: a candidate, an engine, a verdict. The numbers (odds, probabilities, edge, scores, fair and minimum odds) are the
    candidate's and the rules reviewer's - the server's."""

    candidate: Candidate
    scores: Scores
    engine: str
    version: str
    decision: str
    confidence: Decimal
    output: dict[str, Any]
    status: str
    input_hash: str
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    usage_ids: tuple[int, ...] = ()
    cost: Decimal = Decimal(0)
    evidence_ids: tuple[int, ...] = ()


def _q6(x: Decimal | None) -> Decimal | None:
    return None if x is None else x.quantize(Decimal("0.000001"))


def _q3(x: Decimal | None) -> Decimal | None:
    return None if x is None else x.quantize(Decimal("0.001"))


def write_review(
    conn: psycopg.Connection[Any], row: ReviewRow, *, packet: Packet, packet_id: int, at: datetime
) -> int:
    """The review, ``mode = 'shadow'``. If the newest review of the same candidate and engine has the same version, input and mode it is returned
    instead of writing another (the rule of ``review.store_review``): running the same pass again writes nothing twice."""
    c = row.candidate
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NEWEST_SQL, (c.fixture_id, c.market_key, c.selection, c.line))
        newest = next((r for r in cur.fetchall() if r[0] == row.engine), None)
        if newest is not None and (newest[2], newest[3], newest[4]) == (
            row.version,
            row.input_hash,
            "shadow",
        ):
            return int(newest[1])
        cur.execute(
            REVIEW_SQL,
            {
                "at": at,
                "fixture": c.fixture_id,
                "pick": c.pick_id,
                "market": c.market_key,
                "selection": c.selection,
                "line": c.line,
                "odds": c.odds,
                "bookmaker": c.bookmaker_id,
                "p_model": _q6(c.p_model),
                "p_low": _q6(c.p_low),
                "p_market": _q6(c.p_market),
                "edge": _q6(c.edge),
                "ev": _q6(c.ev),
                "engine": row.engine,
                "version": row.version,
                "provider": row.provider,
                "model": row.model,
                "packet": packet_id,
                "hash": row.input_hash,
                "decision": row.decision,
                "confidence": _q3(row.confidence),
                "context": _q3(row.scores.context),
                "model_score": _q3(row.scores.model),
                "market_score": _q3(row.scores.market),
                "fair": row.scores.fair,
                "minimum": row.scores.minimum,
                "output": Jsonb(row.output),
                "sources": Jsonb(packet.sources),
                "evidence": list(row.evidence_ids),
                "usage": list(row.usage_ids),
                "cost": _money(row.cost),
                "status": row.status,
                "error": None if row.error is None else row.error[:300],
            },
        )
        out = cur.fetchone()
    assert out is not None
    return int(out[0])


def distinct(values: Sequence[int]) -> tuple[int, ...]:
    """The ids once each, in order."""
    return tuple(dict.fromkeys(values))

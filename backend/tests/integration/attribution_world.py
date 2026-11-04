"""What the integration tests of phase 5 share: a finished match of the shadow - the pass that was recorded, the review of each shadow engine, the runs of the
Match Agent, and the post-mortem the result produced - written by hand with the columns the attribution reads.

The rows are the ones the orchestrator and the rules write (their tests hold that); here they are seeded so that each test can say which result, which stance
and which CLV it is about. The helpers of the leak audit of the shadow are reused: the same match, the same moments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_agent_shadow_leak_audit import (
    KICKOFF,
    KNOWN,
    MIN,
    REVIEWED,
    START,
    digest,
    evidence,
    packet,
)
from tests.integration.test_ai_decision_layer import Savepoints

D = Decimal
VERSIONS = {"council": "council-v1", "match": "match-v1"}
DAY = local_day(KICKOFF)
AFTER = KICKOFF + timedelta(hours=14)
"""When the step runs: the morning after the match."""


@dataclass
class Shadow:
    """One match of the shadow: its packet, its pass, and the rows written for it."""

    db: psycopg.Connection[Any]
    seed: Seed
    packet: int
    package: str
    state: int
    reviews: dict[tuple[str, str], int] = field(default_factory=dict)
    runs: dict[str, int] = field(default_factory=dict)
    postmortems: dict[str, int] = field(default_factory=dict)


def savepoints(db: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    """The connection as the worker sees it (commit and rollback stay inside the test's transaction), typed as the connection the code under test takes."""
    return cast("psycopg.Connection[Any]", Savepoints(db))


def finish(db: psycopg.Connection[Any], fixture: int) -> None:
    db.execute("UPDATE core.fixtures SET status_group = 'finished' WHERE id = %s", (fixture,))


def shadow(db: psycopg.Connection[Any], seed: Seed, *, versions: dict[str, str] | None = None, tag: str = "a", finished: bool = True,
           known: datetime = KNOWN) -> Shadow:
    """The pass of the shadow over a packet, recording the agents that ran in it and their versions, on the seeded match."""
    pk = packet(db, seed, tag=tag)
    package = digest(f"package-{tag}")
    agents = [{"agent": a, "version": v, "task": "council" if a == "council" else "evaluation", "status": "ok"} for a, v in (versions or VERSIONS).items()]
    state = int(scalar(db.execute(
        "INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, package_hash, packet_id, agents) "
        "VALUES (%s, 'shadow', 'pre', %s, %s, 'ms-v1', 'mcp-v1', %s, %s, %s) RETURNING id",
        (seed.fixture_id, known, START + 10 * MIN, package, pk, Jsonb(agents)))))
    if finished:
        finish(db, seed.fixture_id)
    return Shadow(db, seed, pk, package, state)


def review(w: Shadow, *, engine: str = "ma-v1", selection: str = "Home", market: str = "1X2", line: str = "0", verdict: str = "APPROVE",
           drivers: tuple[str, ...] = ("FORM",), assessment: dict[str, str] | None = None, candidate: str = "c1", at: datetime = REVIEWED,
           extra: dict[str, Any] | None = None, status: str = "ok", mode: str = "shadow") -> int:
    """The review of one shadow engine on a selection, with the output the orchestrator stores (codes, and prose that is not read)."""
    output: dict[str, Any] = {"version": "ma-v1", "engine": engine, "contract": "cd-v1", "candidate": candidate, "verdict": verdict, "drivers": list(drivers),
                              "risks": ["MARKET_MOVE"], "refs": ["P:market"]}
    if engine != "cs-v1":
        output["assessment"] = assessment if assessment is not None else {"match_evaluation": "SUPPORT"}
    output |= extra or {}
    rid = int(scalar(w.db.execute(
        "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, bookmaker_id, p_model, p_low, p_market, edge, ev, engine, "
        "engine_version, packet_id, input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, %s, %s, %s, 2.1, %s, 0.5, 0.45, 0.45, 0.05, "
        "0.05, %s, 'ma-v1', %s, %s, %s, 0.6, %s, %s, %s) RETURNING id",
        (at, w.seed.fixture_id, market, selection, D(line), w.seed.bookmaker_id, engine, w.packet, digest(f"{engine}-{selection}-{market}-{line}-{at}-{verdict}"),
         verdict if verdict in ("APPROVE", "DOWNGRADE", "REJECT") else "REJECT", Jsonb(output), mode, status))))
    w.reviews[(engine, selection)] = rid
    return rid


def match_run(w: Shadow, agent: str = "match", *, drivers: tuple[str, ...] = ("ABSENCES",), candidate: str = "c1", key: str | None = None) -> int:
    """The evaluation of the Match (or the Statistics) Agent the shadow stored over the package of the pass."""
    rid = int(scalar(w.db.execute(
        "INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, model, agent, agent_version, "
        "prompt_version, schema_version, router_version, package_hash, idem_key, output, verdict, input_tokens, output_tokens, status) VALUES "
        "('shadow', 'pre pass', 'evaluation', 'pre', %s, %s, %s, %s, 'claude-haiku-4-5', %s, %s, 'match-assess-v1', 'aa-v1', 'router-v1', %s, %s, %s, "
        "NULL, 100, 20, 'ok') RETURNING id",
        (w.seed.fixture_id, START, START + MIN, KNOWN, agent, VERSIONS.get(agent, f"{agent}-v1"), w.package, digest(key or f"run-{agent}"),
         Jsonb({"candidates": [{"candidate": candidate, "stance": "SUPPORT", "drivers": list(drivers)}]})))))
    w.runs[agent] = rid
    return rid


def postmortem(w: Shadow, *, selection: str = "Home", market: str = "1X2", line: str = "0", outcome: str = "lost", loss_class: str | None = "MODEL_ERROR",
               clv: str | None = "-0.055", p_model: str | None = "0.55", p_market: str | None = "0.50", p_close: str | None = "0.45",
               version: str = "pm-v6", at: datetime = AFTER, answers: dict[str, Any] | None = None) -> int:
    """The post-mortem the rules wrote for a selection once it settled (``outcome`` is the table's word: won, lost, half_won, half_lost, push, void)."""
    pid = int(scalar(w.db.execute(
        "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, answers, market_key, selection, line, "
        "roles, review_decision, review_verdict, loss_class, odds, close_odds, p_model, p_market, p_close, price_move, clv) VALUES (NULL, %s, %s, %s, %s, "
        "'BAD', 'ERROR', %s, %s, %s, %s, ARRAY['reviewed'], 'APPROVE', 'approved_lost', %s, 2.10, 2.00, %s, %s, %s, 0.05, %s) RETURNING id",
        (w.seed.fixture_id, at, version, outcome, Jsonb(answers or {}), market, selection, D(line), loss_class if outcome in ("lost", "half_lost") else None,
         None if p_model is None else D(p_model), None if p_market is None else D(p_market), None if p_close is None else D(p_close),
         None if clv is None else D(clv)))))
    w.postmortems[selection] = pid
    return pid


def attributions(db: psycopg.Connection[Any], *, columns: str = "*", where: str = "TRUE") -> list[tuple[Any, ...]]:
    return db.execute(f"SELECT {columns} FROM intel.agent_attributions WHERE {where} ORDER BY id").fetchall()


def complete(db: psycopg.Connection[Any], seed: Seed) -> Shadow:
    """The usual case: a Council that approved a selection the Match Agent supported, evidenced by a run, that lost."""
    w = shadow(db, seed)
    evidence(db, seed, "world")
    review(w)
    match_run(w)
    postmortem(w)
    return w

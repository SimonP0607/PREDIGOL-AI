"""The replay of a day under ``voi-v1`` (``fbi.budgeting.replay`` and ``scripts/ia_voi.py``) over a real migrated database: its own world of one
match with three reviewed selections, a shadow pass, its agent runs and their attribution. It reads only, splits the actual spend by selection
as documented, stays within budget v3's day and gives the same report twice."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from scripts import ia_voi

from fbi.ai.config import AiSettings
from fbi.ai.usage import Budget
from fbi.budgeting import replay
from tests.integration.agent_tables import insert, key, run_values
from tests.integration.conftest import Seed

D = Decimal

KICKOFF = datetime(2031, 3, 10, 20, tzinfo=UTC)  # 15:00 in Bogota
DAY = date(2031, 3, 10)
PASS_AT = KICKOFF - timedelta(hours=6)
REVIEW_AT = KICKOFF - timedelta(hours=5)


def world(db: psycopg.Connection[Any], seed: Seed) -> int:
    fixture = insert(db, "core.fixtures", {"provider_fixture_id": 990_001, "competition_season_id": seed.season_id,
                                           "home_team_id": seed.home_team_id, "away_team_id": seed.away_team_id, "kickoff_at": KICKOFF})
    for market, selection, line, odds, p, p_low, edge in (("1X2", "Home", "0", "2.2", "0.52", "0.47", "0.05"),
                                                          ("OU", "Over", "2.5", "1.9", "0.55", "0.53", "0.005"),
                                                          ("1X2", "Away", "0", "3.5", "0.20", "0.17", "-0.08")):
        for at, price in ((REVIEW_AT - timedelta(hours=10), D(odds) - D("0.1")), (REVIEW_AT, D(odds))):
            db.execute("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, p_model, p_low, edge, engine, "
                       "engine_version, input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                       "'rules', 'rules-review-v1', 'h', 'APPROVE', 0.6, '{}'::jsonb, 'shadow', 'ok')",
                       (at, fixture, market, selection, D(line), price, D(p), D(p_low), D(edge)))
    candidates = [{"candidate": "c1", "family": "1X2", "market": "1X2", "selection": "Home", "line": "0"},
                  {"candidate": "c2", "family": "OU", "market": "OU", "selection": "Over", "line": "2.50"},
                  {"candidate": "c3", "family": "1X2", "market": "1X2", "selection": "Away", "line": "0.00"}]
    insert(db, "ai.match_runs", {"fixture_id": fixture, "run_kind": "shadow", "pass_kind": "pre", "known_at": PASS_AT,
                                 "created_at": PASS_AT + timedelta(minutes=3), "state_version": "ms-v1",
                                 "candidates": Jsonb(candidates),
                                 "contradictions": Jsonb([{"code": "C06", "subject": "match", "candidates": ["c1"], "refs": [],
                                                           "requires": "escalation"}])})
    for n, (labels, cost, pass_kind) in enumerate(((["c1"], "0.05", "pre"), ([], "0.03", "pre"), (["c1"], "0.01", "first")), start=1):
        insert(db, "ai.agent_runs", run_values(seed, 900 + n, run_kind="shadow", fixture_id=fixture, pass_kind=pass_kind, candidates=labels,
                                               known_at=PASS_AT, started_at=PASS_AT + timedelta(minutes=1),
                                               finished_at=PASS_AT + timedelta(minutes=2), cost_usd=D(cost), idem_key=key(900 + n)))
    for signal, outcome in (("ABSENCES", "HIT"), ("FORM", "MISS"), ("VERDICT", "HIT")):
        db.execute("INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, "
                   "agent, agent_version, signal, stance, outcome, error_class, settled, review_id, postmortem_id, source, computed_at) VALUES "
                   "('attr-v1', 'code', %s, '1X2', 'Home', 0, 'ma-v1', 'match', 'match-v2', %s, 'SUPPORT', %s, %s, 'win', 1, 1, 'live', %s)",
                   (fixture, signal, outcome, "UNKNOWN" if outcome == "MISS" else "NONE", KICKOFF + timedelta(hours=3)))
    return fixture


def test_the_replay_of_a_day(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixture = world(db, seed)
    budget = Budget("NORMAL", D(0), D(40), D(6), D(185), D(9))
    rep = replay.replay_day(db, day=DAY, budget=budget)
    rows = {r.key: r for r in rep.rows}
    home, over, away = (f"{fixture}:1X2:Home:0.00", f"{fixture}:OU:Over:2.50", f"{fixture}:1X2:Away:0.00")
    assert set(rows) == {home, over, away}
    x = rows[home].inputs
    assert rows[home].as_of == REVIEW_AT and x is not None
    assert x.open_contradictions == 1 and x.material_contradiction
    assert x.ev == D("0.144")                                   # the newest review's price, not the older one
    assert (rows[home].tier, rows[over].tier, rows[away].tier) == ("D3", "D1", "D0")
    assert rows[away].policy_usd == 0 and rows[home].policy_usd > rows[over].policy_usd > 0
    assert (rows[home].actual_usd, rows[over].actual_usd, rows[away].actual_usd) == (D("0.06"), D("0.01"), D("0.01"))
    assert (rep.unattributed_usd, rep.unattributed_runs) == (D("0.01"), 1)    # the "first" pass has no row: counted, not guessed
    assert sum((r.policy_usd for r in rep.rows), D(0)) <= rep.allocation.limit_usd <= budget.daily
    doc = rep.as_json()
    assert doc["by_tier"]["D3"]["attribution"]["useful_signals"] == 1
    assert doc["by_tier"]["D3"]["attribution"]["cost_per_useful_signal_usd"] == "0.060000"
    assert "attribution" not in doc["by_tier"]["D1"]
    assert json.dumps(doc, sort_keys=True, default=str) == json.dumps(replay.replay_day(db, day=DAY, budget=budget).as_json(),
                                                                      sort_keys=True, default=str)

    late = replay.replay_day(db, day=DAY, budget=budget, at=REVIEW_AT - timedelta(hours=1))
    assert {r.key for r in late.rows if r.inputs is not None} == {home, over, away}
    assert all(r.as_of == REVIEW_AT - timedelta(hours=1) for r in late.rows if r.inputs is not None)
    early = replay.replay_day(db, day=DAY, budget=budget, at=REVIEW_AT - timedelta(hours=20))
    assert not [r for r in early.rows if r.inputs is not None]                 # nothing reviewed yet: no candidate


def test_the_command_reads_budget_v3_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    counts = "SELECT (SELECT count(*) FROM ai.agent_runs), (SELECT count(*) FROM ai.usage), (SELECT count(*) FROM ai.envelope_alerts)"
    before = db.execute(counts).fetchone()
    first, code = ia_voi.run(db, day=DAY, settings=AiSettings.from_env())
    second, _ = ia_voi.run(db, day=DAY, settings=AiSettings.from_env())
    assert code == ia_voi.OK and first == second
    assert db.execute(counts).fetchone() == before
    assert first["policy"] == "voi-v1" and first["budget_v3"]["state"] in ("NORMAL", "AJUSTE", "REDUCED", "CHEAP_ONLY", "EXHAUSTED")
    assert D(first["totals"]["policy_usd"]) <= D(first["allocation"]["limit_usd"])
    assert first["lines"][0].startswith("PRESUPUESTO POR VALOR DE LA INFORMACIÓN")

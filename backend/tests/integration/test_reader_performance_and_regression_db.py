"""AD-K03 / AD-K04 (IA-135 / IA-136) on PostgreSQL: every new statement runs against the real schema.

* perf-v1 reads one stance per selection and reader from ``intel.agent_attributions`` (the Match Agent once, each arm of the Council apart)
  with the rules' newest word BEFORE kick-off, and the facts of the kept evaluations;
* replay-regression-v1 judges what the bank collected, records it only with the signed tolerance, and never records a second verdict over
  the same stored runs."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.replay import SAME, VERSION, regression, regression_store
from fbi.evalpass import performance_reads as reads
from tests.integration.attribution_world import review, shadow
from tests.integration.conftest import Seed
from tests.integration.test_agent_shadow_leak_audit import KICKOFF

pytestmark = pytest.mark.integration


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def attribution(db: psycopg.Connection[Any], fixture: int, *, engine: str, agent: str, version: str, stance: str, review_id: int,
                signal: str = "VERDICT") -> None:
    db.execute("INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, "
               "agent, agent_version, signal, stance, outcome, error_class, settled, toward_close, calibration, clv, review_id, run_id, "
               "postmortem_id, basis_id, source, computed_at) VALUES ('attr-v1', 'code', %s, '1X2', 'Home', 0, %s, %s, %s, %s, %s, 'HIT', "
               "'NONE', 'loss', true, NULL, -0.0400, %s, NULL, 1, NULL, 'batch', %s)",
               (fixture, engine, agent, version, signal, stance, review_id, KICKOFF + timedelta(hours=14)))


def test_one_stance_per_selection_and_reader_with_the_rules_word_before_kick_off(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = shadow(db, seed)
    rules = review(w, engine="rules", verdict="APPROVE")
    review(w, engine="rules", verdict="REJECT", at=KICKOFF + timedelta(hours=1))  # after kick-off: not what the pass read
    for engine in ("ma-v1", "ma-v1-h"):
        attribution(db, seed.fixture_id, engine=engine, agent="match", version="match-v1", stance="CONCERN", review_id=rules)
        attribution(db, seed.fixture_id, engine=engine, agent="council", version="council-v1", stance="DOWNGRADE", review_id=rules)
    attribution(db, seed.fixture_id, engine="ma-v1", agent="match", version="match-v1", stance="CONCERN", review_id=rules, signal="FORM")
    got = reads.stances(db, start=KICKOFF - timedelta(days=1), end=KICKOFF + timedelta(days=1))
    assert sorted(j.reader for j in got) == ["council/council-v1@ma-v1", "council/council-v1@ma-v1-h", "match/match-v1"]
    assert {j.rules_word for j in got} == {"APPROVE"} and all(j.discordant and j.difference == pytest.approx(0.04) for j in got)
    assert reads.stances(db, start=KICKOFF + timedelta(days=1), end=KICKOFF + timedelta(days=2)) == []


def test_the_facts_of_the_kept_evaluations_are_read_with_the_question_of_the_typed_claims(db: psycopg.Connection[Any], seed: Seed) -> None:
    assert reads.cited(db, start=KICKOFF - timedelta(days=1), end=KICKOFF + timedelta(days=1)) == []
    assert reads.sources_by_id(db, [], typed=False) == {}


def bank(db: psycopg.Connection[Any], *, runs: range, matches: int, scope: str = "council/ma-v1", stored: str = "DOWNGRADE",
         replay: str = "DOWNGRADE", in_batch: bool = True) -> None:
    for run in runs:
        item = db.execute(
            "INSERT INTO ai.replay_bank_items (bank_version, source_run_id, created_at, scope, admitted, reason, fixture_id, pass_kind, known_at, "
            "run_started_at, agent, agent_version, prompt_version, schema_version, task_kind, model, effort, idem_key, package_hash, input_hash, "
            "request_hash, packet_id, package_version, candidates, stored_status, stored_units, stored_in_batch) VALUES (%s, %s, %s, %s, true, "
            "NULL, %s, 'pre', %s, %s, 'council', 'council-v1', 'council-v1', 'cd-v1', 'council', 'claude-sonnet-5-5', NULL, %s, %s, %s, %s, 1, "
            "'mcp-v1', '{c1}', 'ok', %s, %s) RETURNING id",
            (VERSION, run, KICKOFF, scope, 1 + run % matches, KICKOFF - timedelta(hours=3), KICKOFF - timedelta(hours=3), sha(f"i{run}"),
             sha(f"p{run}"), sha(f"n{run}"), sha(f"r{run}"), Jsonb({"c1": stored}), in_batch)).fetchone()
        assert item is not None
        for rep in (1, 2):
            db.execute("INSERT INTO ai.replay_results (bank_item_id, variant, repetition, batch_item_id, model, collected_at, status, output, "
                       "verdict, units) VALUES (%s, %s, %s, %s, 'claude-sonnet-5-5', %s, 'ok', %s, %s, %s)",
                       (item[0], SAME, rep, 10 * run + rep, KICKOFF, Jsonb({"verdicts": []}), replay, Jsonb({"c1": replay})))


def test_the_regression_judges_what_the_bank_collected_and_never_twice_over_the_same_runs(db: psycopg.Connection[Any], seed: Seed) -> None:
    bank(db, runs=range(1, 231), matches=40)
    report = regression_store.check(db, draws=200)
    entry = report["scopes"]["council/ma-v1"]
    assert entry["regression"]["verdict"] == regression.PASS and entry["regression"]["upper"] == 0.0
    assert entry["measured_version"] == "council-v1" and entry["runs"] == list(range(1, 231)) and report["decides"] is False
    assert report["protocol"]["protocol"] == "AD-K04"
    with pytest.raises(PermissionError):
        regression_store.record(db, report, at=KICKOFF, signed=False)
    first = regression_store.record(db, report, at=KICKOFF, signed=True)
    assert set(first["written"]) == {"council/ma-v1"} and first["refused_reused_runs"] == {}
    again = regression_store.record(db, regression_store.check(db, draws=200), at=KICKOFF + timedelta(days=1), signed=True)
    assert again["written"] == {} and again["refused_reused_runs"]["council/ma-v1"][:3] == [1, 2, 3]
    rows = db.execute("SELECT verdict, method, protocol, evidence -> 'regression' ->> 'verdict' FROM ai.replay_assessments "
                      "WHERE scope = 'council/ma-v1'").fetchall()
    assert rows == [("PASA", regression.METHOD, "proto-ad-k04-v1", "PASA")]


def test_a_scope_that_does_not_reproduce_carries_its_cause(db: psycopg.Connection[Any], seed: Seed) -> None:
    bank(db, runs=range(1, 231), matches=40, scope="council/ma-v1-h", stored="REJECT", replay="DOWNGRADE", in_batch=False)
    entry = regression_store.check(db, draws=200)["scopes"]["council/ma-v1-h"]
    assert entry["regression"]["verdict"] == regression.FAIL
    assert entry["diagnosis"]["cause"] == "muestra_insuficiente_para_explicar", "every run was real time: the route cannot be compared"
    assert entry["diagnosis"]["items"] == {"batch": 0, "tiempo_real": 230, "mismo_modelo": 230, "otro_modelo": 0}

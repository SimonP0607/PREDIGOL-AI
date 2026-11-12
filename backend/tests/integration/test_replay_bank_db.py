"""The replay bank (IA-047) on PostgreSQL: a run of the shadow stored the way the orchestrator stores it - its packet, its state,
its ledger row and its run - is derived again from the database and admitted with the very request it was sent; the plan
reads the LAB's day and writes nothing; an answer the worker's poll kept is collected into the bank's own table and judged; and
every table of the bank refuses to be rewritten. Every statement of ``fbi.ai.replay`` runs here against the real schema."""

from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import package as pk
from fbi.ai.agents import match
from fbi.ai.agents.registry import REGISTRY
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.packet import Packet, canonical, content_hash
from fbi.ai.replay import SAME, VERSION, bank, harness
from tests.integration.conftest import Seed
from tests.unit.synthetic_packet import AT, KICKOFF, packet

pytestmark = pytest.mark.integration

D = Decimal
CODE = "mc9a7bec97ca"
HAIKU = "claude-haiku-5-5"
STARTED = AT + timedelta(minutes=2)
CONTEXT = {"contract": "aa-v1", "agent": "match", "mode": "CONTEXT", "data_quality": "FAIR", "candidates": [], "research": [],
           "signals": [{"code": "FORM", "direction": "HOME", "strength": "LOW", "refs": ["P:header"]}]}
TABLES = ("ai.replay_bank_items", "ai.replay_runs", "ai.replay_results", "ai.replay_assessments")


def one(db: psycopg.Connection[Any], sql: str, params: Any = None) -> Any:
    row = db.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def stored_pass(db: psycopg.Connection[Any], seed: Seed) -> dict[str, Any]:
    """One pass of the shadow with the Match Agent's context answered, written as the orchestrator writes it."""
    fixture = one(db, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                      "VALUES (474747, %s, %s, %s, %s) RETURNING id", (seed.season_id, seed.home_team_id, seed.away_team_id, KICKOFF))
    synthetic = packet()
    content = copy.deepcopy(synthetic.content)
    content["fixture"]["id"] = fixture  # the package holds its header to its match
    stored = Packet(fixture_id=fixture, as_of=synthetic.as_of, content=content, sources=synthetic.sources,
                    missing=synthetic.missing, quality=synthetic.quality, version=synthetic.version)
    packet_id = one(db, "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, sources, missing, "
                        "quality) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (fixture, stored.version, stored.as_of, stored.as_of + timedelta(seconds=30), content_hash(stored.content),
                     Jsonb(stored.content), Jsonb(stored.sources), stored.missing, Jsonb(stored.quality)))
    package = pk.derive(db, packet_id, pass_kind="pre", model_code=CODE)
    assert package is not None
    slice_ = pk.slices_of(package)["match"]
    request = match.context_request(slice_, at=slice_.known_at)
    reading = match.read(CONTEXT, mode="CONTEXT", slice_=slice_)
    assert reading.assessment is not None, reading.problems
    identity = REGISTRY.identity_for("match", "context", workspace="lab", input_version=package.version, input_hash=slice_.hash,
                                     pass_kind="pre", fixture_id=fixture)
    usage = one(db, "INSERT INTO ai.usage (at, purpose, tier, provider, model, prompt_version, input_tokens, output_tokens, cost_usd, "
                    "status, input_hash) VALUES (%s, 'match_analysis', 'bulk', 'anthropic', %s, 'match-context-v4', 18000, 1500, 0.002, "
                    "'ok', %s) RETURNING id", (STARTED, HAIKU, match.input_hash(request)))
    db.execute("INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, "
               "package_hash, packet_id, model_status) VALUES (%s, 'shadow', 'pre', %s, %s, 'orch-v1', %s, %s, %s, %s)",
               (fixture, package.known_at, STARTED + timedelta(minutes=1), package.version, package.hash, packet_id,
                Jsonb({"code": CODE, "orchestrator": "orch-v1"})))
    run_id = one(db, "INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, "
                     "model, effort, agent, agent_version, prompt_version, schema_version, router_version, package_hash, slice_hash, "
                     "idem_key, output, verdict, input_tokens, output_tokens, cost_usd, usage_id, status) VALUES ('shadow', 'shadow context', "
                     "'context', 'pre', %s, %s, %s, %s, %s, %s, 'match', %s, %s, %s, 'router-v1', %s, %s, %s, %s, NULL, 18000, 1500, 0.002, "
                     "%s, 'ok') RETURNING id",
                     (fixture, STARTED, STARTED + timedelta(seconds=20), package.known_at, HAIKU, identity.effort, identity.agent_version,
                      identity.prompt_version, identity.schema_version, package.hash, slice_.hash, identity.key,
                      Jsonb(reading.assessment.model_dump(mode="json")), usage))
    return {"fixture": fixture, "packet": packet_id, "package": package, "request": request, "run": run_id, "identity": identity}


def settings() -> AiSettings:
    tiers = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", "claude-sonnet-5-5")}
    return AiSettings(tiers=tiers, keys={"anthropic": "k"}, lab_keys={"anthropic": "l"}, lab_monthly_budget=D(55))  # type: ignore[arg-type]


def counts(db: psycopg.Connection[Any]) -> dict[str, int]:
    return {t: one(db, f"SELECT count(*) FROM {t}") for t in TABLES}


def test_a_stored_run_is_rebuilt_from_the_database_planned_without_a_write_collected_and_judged(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    shadow = stored_pass(db, seed)
    runs = bank.read_runs(db, since=AT - timedelta(days=1), until=AT + timedelta(days=1))
    assert [r.id for r in runs] == [shadow["run"]] and runs[0].request_hash == match.input_hash(shadow["request"])
    built = bank.build(db, runs=runs, changed_at=bank.optimisations_changed_at(db), since=AT - timedelta(days=1), until=AT + timedelta(days=1))
    assert built.excluded == () and [i.scope for i in built.items] == ["match/context"]
    [item] = built.items
    assert item.ask.request.user == shadow["request"].user and item.ask.key == shadow["identity"].key
    assert bank.read_runs_by_id(db, [shadow["run"]])[0].idem_key == shadow["identity"].key

    before = counts(db)
    p = harness.plan(db, settings(), built, at=AT + timedelta(days=1))
    assert len(p.asks) == 2 and p.room is not None and counts(db) == before, "a plan writes nothing"
    assert canonical(p.asks[0].request.user) == canonical(shadow["request"].user) and p.asks[0].request.pinned

    ids = harness.write_bank(db, built, at=AT + timedelta(days=1))
    assert harness.write_bank(db, built, at=AT + timedelta(days=2)) == ids, "the bank is written once per stored run"
    bank_id = ids[shadow["run"]]
    row = db.execute("SELECT admitted, reason, scope, input_hash, request_hash, stored_units FROM ai.replay_bank_items WHERE id = %s",
                     (bank_id,)).fetchone()
    assert row == (True, None, "match/context", pk.slices_of(shadow["package"])["match"].hash, match.input_hash(shadow["request"]),
                   {"signals": "FORM:HOME"})

    batch = one(db, "INSERT INTO ai.batches (provider, workspace, key_label, kind, status, created_at, n_items, batch_ref) "
                    "VALUES ('anthropic', 'PREDIGOL-LAB', 'worker-lab', 'lab', 'ended', %s, 2, 'msgbatch_x') RETURNING id", (AT,))
    for k, data in ((1, CONTEXT), (2, dict(CONTEXT, signals=[]))):
        db.execute("INSERT INTO ai.batch_items (batch_id, custom_id, purpose, tier, model, input_hash, prompt_version, status, created_at, "
                   "context) VALUES (%s, %s, 'other', 'bulk', %s, %s, %s, 'succeeded', %s, %s)",
                   (batch, f"c{k}" * 20, HAIKU, harness.ask_hash(SAME, item.run.idem_key, k), VERSION, AT,
                    Jsonb({"lab": "replay", "bank": VERSION, "variant": SAME, "item": shadow["run"], "repetition": k,
                           "result": {"ok": True, "data": copy.deepcopy(data)}})))

    from fbi.research import protocol

    monkeypatch.setattr(protocol, "stamp", lambda key: {"protocol": key, "version": "proto-int-c02-v1", "fingerprint": "f" * 64,
                                                        "framework": protocol.VERSION})
    out = harness.report(db, at=AT + timedelta(days=3), record=True)
    assert out["collected"]["written"] == 2 and out["state"] == "ended"
    scope = out["scopes"]["match/context"]
    assert scope["complete_units"] == 1 and scope["changed_stored"] == 0 and scope["changed_repeat"] == 1
    assert scope["verdict"] == "INSUFICIENTE" and scope["assessment_id"] is not None
    again = harness.report(db, at=AT + timedelta(days=4), record=True)
    assert again["collected"]["written"] == 0 and again["scopes"]["match/context"]["assessment_id"] is None, "nothing new, no new row"
    results = db.execute("SELECT repetition, status, units FROM ai.replay_results ORDER BY repetition").fetchall()
    assert results == [(1, "ok", {"signals": "FORM:HOME"}), (2, "ok", {"signals": "-"})]
    assert one(db, "SELECT count(*) FROM ai.agent_runs") == 1, "the bank wrote no run of the shadow"


BANK_ROW = ("INSERT INTO ai.replay_bank_items (bank_version, source_run_id, created_at, scope, admitted, reason, fixture_id, pass_kind, "
            "known_at, run_started_at, agent, agent_version, prompt_version, schema_version, task_kind, idem_key, stored_status, "
            "stored_in_batch) VALUES ('replay-bank-v1', %s, now(), 'match/context', false, %s, 1, 'pre', now(), now(), 'match', "
            "'match-v4', 'p', 's', 'context', repeat('a', 64), 'ok', false) RETURNING id")
RUN_ROW = ("INSERT INTO ai.replay_runs (run_key, bank_version, variant, protocol, protocol_fingerprint, created_at, items, asks, repeats, "
           "estimate_usd, worst_usd, cap_usd, lab_remaining_usd, confirmed_by_owner, selection) VALUES (%s, 'replay-bank-v1', 'same', "
           "'proto-int-c02-v1', repeat('f', 64), now(), 1, 2, 2, %s, %s, 5, 40, %s, '{}')")


def test_every_table_of_the_bank_is_append_only(db: psycopg.Connection[Any]) -> None:
    item = one(db, BANK_ROW, (1, "version_not_in_force"))
    db.execute(RUN_ROW, ("k", D("0.01"), D("0.1"), True))
    db.execute("INSERT INTO ai.replay_results (bank_item_id, variant, repetition, batch_item_id, collected_at, status) "
               "VALUES (%s, 'same', 1, 9, now(), 'invalid')", (item,))
    db.execute("INSERT INTO ai.replay_assessments (at, bank_version, variant, scope, protocol, protocol_fingerprint, method, verdict, "
               "evidence, evidence_hash) VALUES (now(), 'replay-bank-v1', 'same', 'council/ma-v1', 'proto-int-c02-v1', repeat('f', 64), "
               "'replay-measure-v1', 'INSUFICIENTE', '{}', repeat('e', 64))")
    for table in TABLES:
        for statement in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            db.execute("SAVEPOINT s")
            with pytest.raises(psycopg.errors.Error):
                db.execute(statement)
            db.execute("ROLLBACK TO SAVEPOINT s")
        assert one(db, f"SELECT count(*) FROM {table}") == 1


def test_a_bank_row_says_why_it_is_out_and_a_run_row_cannot_plan_above_its_cap(db: psycopg.Connection[Any]) -> None:
    for sql, params in ((BANK_ROW, (2, None)), (RUN_ROW, ("k2", D(6), D(10), True)), (RUN_ROW, ("k3", D(1), D(2), False)),
                        (RUN_ROW, ("k4", D(1), D("0.5"), True))):
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(sql, params)
        db.execute("ROLLBACK TO SAVEPOINT s")

"""The Message Batches route for what can wait (Plan Maestro IA, section 29), on a stored match.

A review that can wait is RECORDED before anything leaves the machine, sent with the others of its cycle in one batch, collected by the
poll, priced at half, validated by the same function as a live answer and stored under the input hash the real-time path reuses - so the
same task is never paid twice, whichever route asked it. What fails (a batch that cannot be created, a request that errors, expires or
comes back unreadable) costs nothing it did not cost and sends the task back to real time. The money an open batch will cost is
reserved in the day's budget until its result arrives.

No network and no key: the provider is ``FakeBatches``. One transaction, rolled back."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai.batch import (
    CYCLE_LOCK,
    BatchQueue,
    Task,
    abandon_unsent,
    cycle_is_running,
    open_counts,
    poll,
)
from fbi.ai.config import AiSettings, Tier, TierModel
from fbi.ai.packet import Packet, store_packet
from fbi.ai.pricing import token_cost
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeBatches, FakeProvider
from fbi.ai.review import Candidate, Deferral, Reviewed, review_candidate
from fbi.ai.usage import UsageLedger, budget, reserved_by_day, shared

from .conftest import ADMIN_URL, Seed
from .test_ai_decision_layer import Savepoints, review_reply
from .test_brief_material import content, fixture_block

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=8)
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET),
         "final": TierModel("anthropic", OPUS)}


def settings(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": dict(TIERS), "keys": {"anthropic": "sk-test-not-a-key"},
                            "switches": {"batch": "on"}}
    return AiSettings(**(base | over))


SETTINGS = settings()


def candidate(seed: Seed, selection: str = "Home", **over: Any) -> Candidate:
    base: dict[str, Any] = {
        "fixture_id": seed.fixture_id, "market_key": "1X2", "selection": selection, "line": Decimal(0),
        "p_model": Decimal("0.5200"), "kickoff_at": KO, "odds": Decimal("2.400"), "bookmaker": "BK",
        "p_low": Decimal("0.4700"), "p_high": Decimal("0.5700"), "p_market": Decimal("0.4500"), "ev": Decimal("0.2480"),
        "model": "dixon_coles", "n_bookmakers": 8, "price_at": AT - timedelta(minutes=5)}
    return Candidate(**(base | over))


def answers(decision: str = "APPROVE") -> FakeProvider:
    return FakeProvider(lambda r: review_reply(decision), name="anthropic")


@dataclass
class Env:
    db: psycopg.Connection[Any]
    conn: Any
    seed: Seed
    fake: FakeBatches
    ledger: UsageLedger
    queue: BatchQueue
    packet: Packet
    packet_id: int

    def ask(self, cand: Candidate | None = None, *, tier: Tier = "analysis", queue: BatchQueue | None = None,
            settings_: AiSettings = SETTINGS, at: datetime = AT, pass_kind: str = "first", use_llm: bool = True,
            provider: tuple[Any, str] | None = None) -> Reviewed:
        """The review of a candidate, deferred to the cycle's queue (as ``cycle._pass`` asks it)."""
        q = queue or self.queue
        return review_candidate(self.conn, settings_, cand or candidate(self.seed), self.packet, self.packet_id, at=at,
                                use_llm=use_llm, tier=tier, ledger=self.ledger,
                                provider=provider, deferral=Deferral(q, self.packet_id, "shadow", pass_kind))

    def poll(self, *, at: datetime = AT + timedelta(minutes=30), settings_: AiSettings = SETTINGS) -> Any:
        return poll(self.conn, settings_, at=at, ledger=self.ledger, client=self.fake)

    def one(self, sql: str, *params: Any) -> Any:
        row = self.db.execute(sql, params).fetchone()
        return None if row is None else row[0] if len(row) == 1 else row

    def items(self, *columns: str) -> list[tuple[Any, ...]]:
        cols = ", ".join(columns) or "status"
        return self.db.execute(f"SELECT {cols} FROM ai.batch_items ORDER BY id").fetchall()


@pytest.fixture()
def env(db: psycopg.Connection[Any], seed: Seed) -> Env:
    conn: Any = Savepoints(db)
    ledger = UsageLedger(shared(db))
    fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    packet = Packet(seed.fixture_id, AT, content(seed) | {"fixture": fixture_block(seed, kickoff_at=KO.isoformat())})
    pid = store_packet(conn, packet, built_at=AT)
    return Env(db, conn, seed, fake, ledger, BatchQueue(conn, SETTINGS, at=AT, ledger=ledger, client=fake), packet, pid)


def other_queue(e: Env, *, at: datetime = AT, settings_: AiSettings = SETTINGS) -> BatchQueue:
    """Another cycle's queue (a new object: it holds none of the request bodies of the first)."""
    return BatchQueue(e.conn, settings_, at=at, ledger=e.ledger, client=e.fake)


# ── a review that can wait is recorded first ────────────────────────────────────────────────────────────────────

def test_a_review_that_can_wait_is_recorded_before_anything_is_sent(env: Env) -> None:
    reviewed = env.ask()
    assert reviewed.pending is not None and reviewed.llm is None and reviewed.carried is None
    assert reviewed.pending.status == "pending" and reviewed.pending.output["batch"] == "queued"
    assert reviewed.combined_output["pending_llm"]["batch"] == "queued", "the combined review says the model's is on its way"
    assert reviewed.decision == reviewed.rules.decision, "meanwhile the rules decide: the model's opinion is not waited for"
    assert env.fake.created == [] and env.fake.polls == 0, "nothing has left the machine"
    row = env.db.execute("SELECT i.status, i.purpose, i.tier, i.model, i.est_cost_usd, i.deadline_at, i.fixture_id, "
                         "i.prompt_version, b.status, b.workspace, b.key_label, b.kind, b.provider "
                         "FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id").fetchone()
    assert row is not None
    assert row[:4] == ("submitting", "pick_review", "analysis", SONNET) and row[4] > 0
    assert row[5] == KO - timedelta(minutes=60), "an answer after this is late"
    assert row[6] == env.seed.fixture_id and row[7] == REVIEW_VERSION
    assert row[8:] == ("submitting", "PREDIGOL", "worker-prod", "production", "anthropic")
    assert env.one("SELECT count(*) FROM ai.usage") == 0, "nothing is paid"
    assert env.one("SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm'") == 0, "and no model review is stored yet"


def test_what_the_item_keeps_is_what_the_answer_needs_and_never_a_key_or_a_prompt(env: Env) -> None:
    env.ask()
    ctx = env.one("SELECT context FROM ai.batch_items")
    assert set(ctx) >= {"candidate", "packet_id", "mode", "role", "pass", "at", "tier", "schema_name"}
    assert ctx["packet_id"] == env.packet_id and ctx["mode"] == "shadow" and ctx["pass"] == "first" and ctx["role"] == "candidate"
    assert Candidate.from_state(ctx["candidate"]) == candidate(env.seed), "the candidate comes back exactly as it was asked"
    text = json.dumps(ctx)
    assert "sk-test" not in text and "Eres un revisor" not in text and "submit_review" in text


def test_the_same_review_asked_again_is_one_item_and_one_reservation(env: Env) -> None:
    first = env.ask()
    assert first.pending is not None and first.pending.output["batch"] == "queued"
    reserved = env.one("SELECT sum(est_cost_usd) FROM ai.batch_items")
    again = env.ask()  # the same cycle asks it again, or the next one while the batch is out
    assert again.pending is not None and again.pending.output["batch"] == "in_flight"
    assert again.pending.output["custom_id"] == first.pending.output["custom_id"]
    assert env.one("SELECT count(*) FROM ai.batch_items") == 1 and env.one("SELECT sum(est_cost_usd) FROM ai.batch_items") == reserved
    later = env.ask(queue=other_queue(env, at=AT + timedelta(minutes=15)), at=AT + timedelta(minutes=15))
    assert later.pending is not None and later.pending.output["batch"] == "in_flight"
    assert env.one("SELECT count(*) FROM ai.batch_items") == 1
    assert open_counts(env.conn, "pick_review") == {"analysis": 1}


def test_a_different_tier_or_candidate_is_another_task(env: Env) -> None:
    env.ask()
    env.ask(tier="final")
    env.ask(candidate(env.seed, "Draw", p_model=Decimal("0.2500"), odds=Decimal("3.500")))
    assert env.one("SELECT count(DISTINCT custom_id) FROM ai.batch_items") == 3
    assert open_counts(env.conn, "pick_review") == {"analysis": 2, "final": 1}
    assert env.one("SELECT count(*) FROM ai.batches WHERE status = 'submitting'") == 1, "all in today's one batch"
    assert {r[0] for r in env.items("model")} == {SONNET, OPUS}


def test_the_model_of_the_tier_decides_the_model_of_the_request(env: Env) -> None:
    env.ask(tier="final")
    assert env.one("SELECT model FROM ai.batch_items") == OPUS


# ── what the budget does with an open batch ─────────────────────────────────────────────────────────────────────

def test_an_open_item_reserves_its_estimated_cost_in_the_days_budget(env: Env) -> None:
    before = budget(env.conn, at=AT, settings=SETTINGS)
    env.ask()
    est = env.one("SELECT est_cost_usd FROM ai.batch_items")
    assert est > 0 and reserved_by_day(env.conn, "production") == {AT.date(): est}
    after = budget(env.conn, at=AT, settings=SETTINGS)
    assert after.spent_today - before.spent_today == est, "the day counts it as spent until the result arrives"
    assert after.spent_month - before.spent_month == est
    assert reserved_by_day(env.conn, "lab") == {} and reserved_by_day(env.conn, "exa") == {}, "only production's money is reserved"


def test_the_v2_budget_reserves_too_so_a_rollback_to_it_keeps_the_ceiling(env: Env) -> None:
    v2 = settings(switches={"batch": "on", "budget_v3": "off"})
    before = budget(env.conn, at=AT, settings=v2)
    assert before.version == "v2"
    env.ask(settings_=v2)
    assert budget(env.conn, at=AT, settings=v2).spent_today - before.spent_today == env.one(
        "SELECT est_cost_usd FROM ai.batch_items")


def test_a_task_the_days_ceiling_cannot_hold_is_asked_in_real_time(env: Env) -> None:
    tight = settings(daily_budget=Decimal("0.001"), monthly_budget=Decimal("0.03"))
    queue = other_queue(env, settings_=tight)
    reviewed = env.ask(queue=queue, settings_=tight, provider=(answers(), SONNET))
    assert queue.refused and set(queue.refused) <= {"budget_cap", "budget_state"}, queue.refused
    assert env.one("SELECT count(*) FROM ai.batch_items") == 0, "refused: no reservation"
    assert reviewed.pending is None, "a refusal sends the task back to the first route"


def test_a_state_that_does_not_allow_the_tier_refuses_it(env: Env) -> None:
    env.db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, input_tokens, output_tokens, cost_usd, status) "
                   "VALUES (%s, 'pick_review', 'analysis', 'anthropic', %s, 1, 1, 500, 'ok')", (AT - timedelta(hours=1), SONNET))
    assert budget(env.conn, at=AT, settings=SETTINGS).state == "EXHAUSTED"
    reviewed = env.ask(provider=(answers(), SONNET))
    assert env.queue.refused == {"budget_state": 1} and reviewed.pending is None
    assert env.one("SELECT count(*) FROM ai.batch_items") == 0


def test_a_task_the_provider_failed_twice_in_a_day_is_asked_in_real_time(env: Env) -> None:
    down = FakeBatches(lambda r: review_reply(), fail_create="unavailable")
    for n in range(2):  # two cycles record it, and the batch cannot be created either time
        at = AT + timedelta(minutes=15 * n)
        q = BatchQueue(env.conn, SETTINGS, at=at, ledger=env.ledger, client=down)
        got = env.ask(queue=q, at=at)
        assert got.pending is not None and got.pending.output["batch"] == "queued"
        assert q.flush().failed == 1
    at = AT + timedelta(minutes=30)
    q = BatchQueue(env.conn, SETTINGS, at=at, ledger=env.ledger, client=down)
    live = env.ask(queue=q, at=at, provider=(answers(), SONNET))
    assert q.refused == {"attempts": 1} and live.pending is None, "failed enough: the first route"
    assert live.llm is not None and live.llm.status == "ok" and "via" not in live.llm.output
    assert env.one("SELECT count(*) FROM ai.batch_items") == 2, "and nothing was recorded for it"


def test_a_lab_task_needs_the_lab_envelope(env: Env) -> None:
    lab = settings(lab_keys={"anthropic": "sk-lab-not-a-key"}, lab_monthly_budget=Decimal(0))
    q = BatchQueue(env.conn, lab, at=AT, ledger=env.ledger, client=env.fake)
    req = JsonRequest(system="s", user="u", schema={"type": "object"}, schema_name="submit_review", max_tokens=1000)
    refused = q.add(Task(purpose="pick_review", tier="analysis", request=req, prompt_version="v", input_hash="x", lab=True))
    assert refused.status == "refused" and refused.reason == "lab_budget" and not refused.pending
    funded = settings(lab_keys={"anthropic": "sk-lab-not-a-key"}, lab_monthly_budget=Decimal(50))
    q2 = BatchQueue(env.conn, funded, at=AT, ledger=env.ledger, client=env.fake)
    ok = q2.add(Task(purpose="pick_review", tier="analysis", request=req, prompt_version="v", input_hash="x", lab=True))
    assert ok.status == "queued"
    assert env.one("SELECT kind FROM ai.batches WHERE status = 'submitting'") == "lab"
    assert reserved_by_day(env.conn, "production") == {}, "the LAB's reservation is the LAB's"
    assert sum(reserved_by_day(env.conn, "lab").values()) == ok.est_cost


def test_a_workspace_without_a_model_refuses_with_its_reason(env: Env) -> None:
    bare = AiSettings(mode="shadow")
    q = BatchQueue(env.conn, bare, at=AT, ledger=env.ledger, client=env.fake)
    req = JsonRequest(system="s", user="u", schema={}, schema_name="x")
    got = q.add(Task(purpose="pick_review", tier="analysis", request=req, prompt_version="v", input_hash="x"))
    assert got.status == "refused" and got.reason == "no_model" and q.refused == {"no_model": 1}


# ── sending ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_cycles_reviews_leave_in_one_batch_and_the_items_are_marked(env: Env) -> None:
    env.ask()
    env.ask(candidate(env.seed, "Draw", p_model=Decimal("0.2500"), odds=Decimal("3.500")))
    report = env.queue.flush()
    assert (report.batches, report.sent, report.failed, report.orphans, report.error) == (1, 2, 0, 0, None)
    assert len(env.fake.created) == 1 and len(env.fake.created[0]) == 2
    assert {r[0] for r in env.items("status")} == {"submitted"}
    batch = env.db.execute("SELECT status, batch_ref, n_items, submitted_at, expires_at FROM ai.batches").fetchone()
    assert batch is not None and batch[0] == "in_progress" and batch[1] == "msgbatch_fake_0001" and batch[2] == 2
    assert batch[3] == AT and batch[4] is not None
    ids = sorted(r[0] for r in env.items("custom_id"))
    assert ids == sorted(env.fake.custom_ids()), "the provider got exactly the keys the database holds"
    body = env.fake.created[0][0]
    assert body["params"]["model"] == SONNET and body["params"]["max_tokens"] == 8000
    assert "sk-test" not in json.dumps(env.fake.created), "the key is the transport's, never in a body"
    flags = env.one("SELECT context -> 'decode' FROM ai.batch_items LIMIT 1")
    assert flags["schema_name"] == "submit_review" and flags["native"] is False


def test_each_workspace_gets_its_own_batch(env: Env) -> None:
    lab = settings(lab_keys={"anthropic": "sk-lab-not-a-key"}, lab_monthly_budget=Decimal(50))
    q = BatchQueue(env.conn, lab, at=AT, ledger=env.ledger, client=env.fake)
    req = JsonRequest(system="s", user="u", schema={"type": "object"}, schema_name="submit_review", max_tokens=1000)
    q.add(Task(purpose="pick_review", tier="analysis", request=req, prompt_version="v", input_hash="prod"))
    q.add(Task(purpose="pick_review", tier="analysis", request=req, prompt_version="v", input_hash="lab", lab=True))
    report = q.flush()
    assert report.batches == 2 and report.sent == 2 and len(env.fake.created) == 2
    rows = env.db.execute("SELECT kind, workspace, key_label FROM ai.batches ORDER BY id").fetchall()
    assert rows == [("production", "PREDIGOL", "worker-prod"), ("lab", "PREDIGOL-LAB", "worker-lab")]


def test_a_batch_that_cannot_be_created_abandons_its_items_and_nothing_is_paid(env: Env) -> None:
    down = FakeBatches(lambda r: review_reply(), fail_create="unavailable")
    q = BatchQueue(env.conn, SETTINGS, at=AT, ledger=env.ledger, client=down)
    env.ask(queue=q)
    report = q.flush()
    assert (report.batches, report.sent, report.failed, report.error) == (0, 0, 1, "create_failed: unavailable")
    assert env.items("status", "error") == [("abandoned", "create_failed: unavailable")]
    assert env.one("SELECT status FROM ai.batches") == "failed" and env.one("SELECT count(*) FROM ai.usage") == 0
    again = env.ask(queue=other_queue(env, at=AT + timedelta(minutes=15)), at=AT + timedelta(minutes=15))
    assert again.pending is not None and again.pending.output["batch"] == "queued", "the next cycle asks again"


def test_a_spent_limit_is_recorded_once_and_the_task_goes_back(env: Env) -> None:
    capped = FakeBatches(lambda r: review_reply(), limit="workspace_limit")
    q = BatchQueue(env.conn, SETTINGS, at=AT, ledger=env.ledger, client=capped)
    env.ask(queue=q)
    q.flush()
    hit = env.db.execute("SELECT provider, workspace, key_label, kind, http_status, purpose FROM ai.limit_hits").fetchall()
    assert hit == [("anthropic", "PREDIGOL", "worker-prod", "workspace_limit", 400, "batch")]
    assert env.items("status", "error") == [("abandoned", "create_failed: limit_reached")]


def test_a_task_recorded_but_rolled_back_is_never_sent(env: Env) -> None:
    env.ask()
    env.conn.rollback()  # the cycle rolled back the match that recorded it
    assert env.one("SELECT count(*) FROM ai.batch_items") == 0
    report = env.queue.flush()
    assert (report.batches, report.sent) == (0, 0) and env.fake.created == []


def test_a_record_without_its_request_is_abandoned_not_sent(env: Env) -> None:
    env.ask()
    env.conn.commit()
    fresh = other_queue(env)  # the process that recorded it stopped: this one holds no request body
    report = fresh.flush()
    assert (report.sent, report.orphans) == (0, 1) and env.fake.created == []
    assert env.items("status", "error") == [("abandoned", "never_sent")]
    assert env.one("SELECT status FROM ai.batches") == "abandoned"


def test_what_an_earlier_cycle_never_sent_is_abandoned_when_the_next_starts(env: Env) -> None:
    env.ask()
    env.conn.commit()
    assert abandon_unsent(env.conn, at=AT + timedelta(minutes=10)) == 0, "a recent record may still be about to be sent"
    assert abandon_unsent(env.conn, at=AT + timedelta(minutes=31)) == 1, "after half an hour it never will be"
    assert env.items("status", "error") == [("abandoned", "never_sent")]
    env.ask(queue=other_queue(env, at=AT + timedelta(minutes=40)), at=AT + timedelta(minutes=40))
    assert env.one("SELECT count(*) FROM ai.batch_items WHERE status = 'submitting'") == 1, "and the task is free to be asked again"
    assert abandon_unsent(env.conn, at=AT + timedelta(minutes=45), before=AT + timedelta(minutes=45)) == 1, "the cycle's own call"


# ── collecting ──────────────────────────────────────────────────────────────────────────────────────────────────

def sent(e: Env, *cands: Candidate) -> list[Reviewed]:
    out = [e.ask(c) for c in (cands or (candidate(e.seed),))]
    e.queue.flush()
    return out


def test_a_batch_still_running_is_asked_about_again_later(env: Env) -> None:
    sent(env)
    first = env.poll()
    assert (first.batches, first.waiting, first.ended, first.items) == (1, 1, 0, 0)
    assert env.one("SELECT status FROM ai.batches") == "in_progress" and env.one("SELECT last_polled_at FROM ai.batches") is not None
    assert env.items("status") == [("submitted",)]
    env.fake.end()
    second = env.poll(at=AT + timedelta(minutes=35))
    assert (second.ended, second.items, second.counts) == (1, 1, {"succeeded": 1})


def test_the_result_is_priced_at_half_recorded_once_and_stored_as_the_review_it_answers(env: Env) -> None:
    [pending] = sent(env)
    reserved = env.one("SELECT est_cost_usd FROM ai.batch_items")
    assert sum(reserved_by_day(env.conn, "production").values()) == reserved
    env.fake.end()
    report = env.poll()
    assert report.counts == {"succeeded": 1} and report.errors == [] and report.cost_usd > 0
    usage = env.db.execute("SELECT purpose, tier, provider, model, status, cost_usd, input_tokens, output_tokens, workspace, "
                           "key_label, batch_id, custom_id, input_hash, prompt_version, fixture_id, at FROM ai.usage").fetchall()
    assert len(usage) == 1
    (purpose, tier, provider, model, status, cost, tin, tout, workspace, label, batch_id, cid, h, version, fid, at) = usage[0]
    assert (purpose, tier, provider, model, status) == ("pick_review", "analysis", "anthropic", SONNET, "ok")
    assert (workspace, label, fid, version) == ("PREDIGOL", "worker-prod", env.seed.fixture_id, REVIEW_VERSION)
    assert pending.pending is not None
    assert cid == pending.pending.output["custom_id"] and batch_id is not None and at == AT + timedelta(minutes=30)
    live = token_cost("anthropic", SONNET, input_tokens=tin, output_tokens=tout, at=at)
    assert cost == token_cost("anthropic", SONNET, input_tokens=tin, output_tokens=tout, batch=True, at=at)
    assert cost == (live / 2).quantize(Decimal("0.000001")) and cost > 0, "half of what the same call costs in real time"
    assert report.cost_usd == cost
    assert sum(reserved_by_day(env.conn, "production").values()) == 0, "the reservation is released by the real cost"
    assert env.items("status", "usage_id")[0][0] == "succeeded"
    review = env.db.execute("SELECT engine, status, decision, input_hash, mode, model, usage_ids, cost_usd, output "
                            "FROM ai.pick_reviews WHERE engine = 'llm'").fetchone()
    assert review is not None
    assert review[:2] == ("llm", "ok") and review[3] == h and review[4] == "shadow" and review[5] == SONNET
    assert review[6] == [env.one("SELECT id FROM ai.usage")] and review[7] == cost
    out = review[8]
    assert out["via"] == "batch" and out["tier"] == "analysis" and out["role"] == "candidate"
    assert out["batch"]["custom_id"] == cid and out["batch"]["late"] is False and out["batch"]["pass"] == "first"
    assert out["fair_odds"] is not None, "the server recomputed the fair odds: the model's own are kept apart"
    done = env.db.execute("SELECT status, processed_at, ended_at, counts FROM ai.batches").fetchone()
    assert done is not None and done[0] == "ended" and done[1] == AT + timedelta(minutes=30) and done[3]["succeeded"] == 1


def test_a_second_poll_pays_and_stores_nothing_more(env: Env) -> None:
    sent(env)
    env.fake.end()
    env.poll()
    usage, reviews = env.one("SELECT count(*) FROM ai.usage"), env.one("SELECT count(*) FROM ai.pick_reviews")
    again = env.poll(at=AT + timedelta(hours=1))
    assert (again.batches, again.items) == (0, 0)
    assert env.one("SELECT count(*) FROM ai.usage") == usage and env.one("SELECT count(*) FROM ai.pick_reviews") == reviews


def test_the_real_time_route_reuses_what_the_batch_answered(env: Env) -> None:
    sent(env)
    env.fake.end()
    env.poll()
    never = FakeProvider(lambda r: pytest.fail("the same input must not be paid twice"), name="anthropic")
    live = review_candidate(env.conn, SETTINGS, candidate(env.seed), env.packet, env.packet_id, at=AT + timedelta(hours=1),
                            use_llm=True, tier="analysis", ledger=env.ledger, provider=(never, SONNET))
    assert live.llm is not None and live.llm.output["reused_from"] and live.llm.cost == 0 and never.requests == []
    queued_again = env.ask(at=AT + timedelta(hours=1))
    assert queued_again.pending is None and queued_again.llm is not None, "the batch route reuses it too"
    assert env.one("SELECT count(*) FROM ai.batch_items") == 1 and env.one("SELECT count(*) FROM ai.usage") == 1


def test_errored_canceled_and_expired_cost_nothing_and_are_recorded(env: Env) -> None:
    cands = [candidate(env.seed, "Home"), candidate(env.seed, "Draw", p_model=Decimal("0.2500"), odds=Decimal("3.500")),
             candidate(env.seed, "Away", p_model=Decimal("0.2300"), odds=Decimal("3.600"))]
    sent(env, *cands)
    ids = dict(zip(("errored", "canceled", "expired"), env.fake.custom_ids(), strict=True))
    env.fake.end(outcomes={ids["errored"]: "errored", ids["canceled"]: "canceled", ids["expired"]: "expired"})
    report = env.poll()
    assert report.counts == {"errored": 1, "canceled": 1, "expired": 1} and report.cost_usd == 0
    assert sorted(r[0] for r in env.items("status")) == ["canceled", "errored", "expired"]
    rows = env.db.execute("SELECT custom_id, status, cost_usd, input_tokens FROM ai.usage ORDER BY id").fetchall()
    assert {r[1] for r in rows} == {"failed", "timeout"} and all(r[2] == 0 for r in rows) and len(rows) == 3
    assert env.one("SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm'") == 0, "no review was made"
    assert sum(reserved_by_day(env.conn, "production").values()) == 0, "and nothing stays reserved"
    again = env.ask(cands[0], queue=other_queue(env, at=AT + timedelta(hours=1)), at=AT + timedelta(hours=1))
    assert again.pending is not None and again.pending.output["batch"] == "queued", "asked again by the next pass"


def test_an_answer_that_cannot_be_read_is_paid_and_stored_so_it_is_not_asked_again(env: Env) -> None:
    sent(env)
    [cid] = env.fake.custom_ids()
    env.fake.end(outcomes={cid: "cut"})
    report = env.poll()
    assert report.counts == {"invalid": 1}
    assert env.items("status", "error") == [("invalid", "invalid_output")]
    assert env.one("SELECT status FROM ai.usage") == "invalid_output"
    review = env.db.execute("SELECT status, decision, output FROM ai.pick_reviews WHERE engine = 'llm'").fetchone()
    assert review is not None and review[0] == "invalid_output" and review[1] == "ABSTAIN" and review[2]["via"] == "batch"
    again = env.ask(at=AT + timedelta(hours=1))
    assert again.pending is None and again.llm is not None and again.llm.status == "invalid_output", \
        "the invalid answer is the answer to that input: it is not ordered a second time"


def test_a_refusal_is_recorded_and_stored_as_an_unreadable_answer(env: Env) -> None:
    sent(env)
    [cid] = env.fake.custom_ids()
    env.fake.end(outcomes={cid: "refused"})
    assert env.poll().counts == {"invalid": 1}
    assert env.one("SELECT status FROM ai.usage") == "invalid_output", "a forced tool call that is not made is not an answer"
    assert env.one("SELECT status FROM ai.pick_reviews WHERE engine = 'llm'") == "invalid_output"


def test_structured_outputs_in_a_batch_are_read_the_way_the_request_asked(env: Env) -> None:
    native = settings(switches={"batch": "on", "native_schema": "on"})
    env.queue = BatchQueue(env.conn, native, at=AT, ledger=env.ledger, client=env.fake)
    env.ask(settings_=native)
    env.queue.flush()
    body = env.fake.created[0][0]["params"]
    assert "tools" not in body and body["output_config"]["format"]["type"] == "json_schema"
    assert env.one("SELECT context -> 'decode' ->> 'native' FROM ai.batch_items") == "true"
    env.fake.end()
    assert env.poll(settings_=native).counts == {"succeeded": 1}
    review = env.db.execute("SELECT status, decision, output FROM ai.pick_reviews WHERE engine = 'llm'").fetchone()
    assert review is not None and review[0] == "ok" and review[2]["via"] == "batch"


def test_a_refusal_with_structured_outputs_is_a_refusal(env: Env) -> None:
    native = settings(switches={"batch": "on", "native_schema": "on"})
    env.queue = BatchQueue(env.conn, native, at=AT, ledger=env.ledger, client=env.fake)
    env.ask(settings_=native)
    env.queue.flush()
    [cid] = env.fake.custom_ids()
    env.fake.end(outcomes={cid: "refused"})
    assert env.poll(settings_=native).counts == {"invalid": 1}
    assert env.one("SELECT status FROM ai.usage") == "refused"
    assert env.one("SELECT status FROM ai.pick_reviews WHERE engine = 'llm'") == "invalid_output"


def test_an_answer_after_the_deadline_is_still_stored_and_marked_late(env: Env) -> None:
    sent(env)
    env.fake.end()
    env.poll(at=KO - timedelta(minutes=30))  # the deadline is an hour before the kick-off
    assert env.items("status") == [("late",)]
    out = env.one("SELECT output FROM ai.pick_reviews WHERE engine = 'llm'")
    assert out["batch"]["late"] is True and env.one("SELECT status FROM ai.usage") == "ok", "paid for, so it is kept"


def test_a_result_half_processed_by_an_earlier_poll_is_not_paid_twice(env: Env) -> None:
    sent(env)
    env.fake.end()
    [item] = env.db.execute("SELECT id, custom_id, batch_id FROM ai.batch_items").fetchall()
    env.db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, input_tokens, output_tokens, cost_usd, status, "
                   "batch_id, custom_id) VALUES (%s, 'pick_review', 'analysis', 'anthropic', %s, 100, 50, 0.001, 'ok', %s, %s)",
                   (AT, SONNET, item[2], item[1]))  # the ledger row of a poll that stopped before closing the item
    report = env.poll()
    assert report.counts == {"succeeded": 1}
    assert env.one("SELECT count(*) FROM ai.usage WHERE custom_id = %s", item[1]) == 1, "the database refuses a second row"
    assert env.items("status") == [("succeeded",)] and env.one("SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm'") == 1


def test_a_provider_that_fails_while_polling_is_noted_and_tried_again(env: Env) -> None:
    sent(env)
    env.fake.end()
    env.fake.fail_results = "unavailable"
    first = env.poll()
    assert first.items == 0 and len(first.errors) == 1 and "unavailable" in first.errors[0]
    assert env.one("SELECT error FROM ai.batches") == "results_failed: unavailable" and env.items("status") == [("submitted",)]
    env.fake.fail_results = None
    second = env.poll(at=AT + timedelta(minutes=40))
    assert second.counts == {"succeeded": 1} and env.one("SELECT error FROM ai.batches") is None


def test_a_result_nobody_asked_for_is_counted_and_ignored(env: Env) -> None:
    from fbi.ai.providers.anthropic import BatchResult

    sent(env)
    env.fake.end()
    [ref] = env.fake.batches
    env.fake._results[ref].append(BatchResult("not_one_of_ours", "errored"))
    report = env.poll()
    assert report.counts == {"succeeded": 1, "unknown": 1} and env.one("SELECT count(*) FROM ai.usage") == 1


def test_rolling_batch_back_stops_new_batches_but_still_collects_the_ones_already_paid_for(env: Env) -> None:
    sent(env)
    env.fake.end()
    off = settings(switches={"batch": "off"})
    assert not BatchQueue(env.conn, off, at=AT).routes(tier="analysis", pass_kind="first", kickoff_at=KO)
    report = env.poll(settings_=off)
    assert report.counts == {"succeeded": 1}, "the switch stops what is SENT, never what was already sent"


def test_two_batches_of_one_day_are_both_collected_and_priced_apart(env: Env) -> None:
    sent(env)
    env.fake.end()
    env.queue = other_queue(env, at=AT + timedelta(minutes=15))
    env.ask(candidate(env.seed, "Draw", p_model=Decimal("0.2500"), odds=Decimal("3.500")), at=AT + timedelta(minutes=15))
    env.queue.flush()
    env.fake.end()
    report = env.poll()
    assert report.batches == 2 and report.ended == 2 and report.counts == {"succeeded": 2}
    assert env.one("SELECT count(DISTINCT batch_id) FROM ai.usage") == 2 and env.one("SELECT count(*) FROM ai.usage") == 2


def test_the_reservation_covers_the_cost_and_follows_the_typical_output_when_the_ledger_has_it(env: Env) -> None:
    env.ask()
    prudent = env.one("SELECT est_cost_usd FROM ai.batch_items")
    env.db.execute("DELETE FROM ai.batch_items")
    for n in range(5):  # what a review of this model has written lately: a thousand tokens
        env.db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, input_tokens, output_tokens, cost_usd, status) "
                       "VALUES (%s, 'pick_review', 'analysis', 'anthropic', %s, 9000, 1000, 0.03, 'ok')",
                       (AT - timedelta(days=1, minutes=n), SONNET))
    env.ask()
    informed = env.one("SELECT est_cost_usd FROM ai.batch_items")
    assert 0 < informed < prudent, "with no history it assumes half the request's maximum; with history, the typical answer"
    env.queue.flush()
    env.fake.end()
    env.poll()
    cost = env.one("SELECT cost_usd FROM ai.usage WHERE batch_id IS NOT NULL")
    assert 0 < cost <= informed, "the reservation held the money the result then cost"


# ── the analysis cycle ──────────────────────────────────────────────────────────────────────────────────────────

from collections.abc import Iterator  # noqa: E402

from fbi.ai.cycle import _allowance, run_analysis_cycle  # noqa: E402
from fbi.ai.gates import record_gate  # noqa: E402

from .test_daily_records import World  # noqa: E402


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield World(db, seed)


def live_model(decision: str = "APPROVE") -> FakeProvider:
    """The real-time provider of the cycle: briefs and reviews in their own shapes."""
    from .test_ai_decision_layer import brief_reply

    return FakeProvider(lambda r: brief_reply() if r.schema_name == "submit_brief" else review_reply(decision), name="anthropic")


def cycle(conn: Any, model: FakeProvider, fake: FakeBatches | None, *, at: datetime = AT, settings_: AiSettings = SETTINGS) -> Any:
    return run_analysis_cycle(conn, at=at, settings=settings_, ledger=UsageLedger(shared(conn._conn)),
                              provider=(model, HAIKU), batches=fake)


def reviews_live(model: FakeProvider) -> int:
    return sum(1 for r in model.requests if r.schema_name == "submit_review")


def n(db: psycopg.Connection[Any], sql: str, *params: Any) -> int:
    row = db.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


@dataclass
class Ran:
    conn: Any
    report: Any
    model: FakeProvider
    fake: FakeBatches


def first_pass(db: psycopg.Connection[Any], *, settings_: AiSettings = SETTINGS, fake: FakeBatches | None = None,
               model: FakeProvider | None = None) -> Ran:
    conn: Any = Savepoints(db)
    model = model or live_model()
    fake = fake or FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    return Ran(conn, cycle(conn, model, fake, settings_=settings_), model, fake)


def test_a_cycle_sends_the_reviews_that_can_wait_in_one_batch_and_pays_nothing_for_them(
        db: psycopg.Connection[Any], world: World) -> None:
    # the control: the same world with Batch rolled back - how many reviews does the cycle ask the model?
    db.execute("SAVEPOINT control")
    control = live_model()
    cycle(Savepoints(db), control, None, settings_=settings(switches={"batch": "off"}))
    asked_in_control = reviews_live(control)
    db.execute("ROLLBACK TO SAVEPOINT control")
    assert asked_in_control >= 4

    ran = first_pass(db)
    report, model, fake = ran.report, ran.model, ran.fake
    assert report.status == "ok", report.errors
    items = n(db, "SELECT count(*) FROM ai.batch_items")
    assert items >= 1 and reviews_live(model) >= 1, "the near match is asked at once; the far ones wait"
    assert items + reviews_live(model) == asked_in_control, "the same reviews, by two routes"
    assert report.counts["batches_sent"] == 1 and report.counts["batch_items_sent"] == items
    assert report.counts["batch_queued"] == items and report.counts["reviews_batched"] == items
    assert len(fake.created) == 1 and len(fake.created[0]) == items
    lead = db.execute("SELECT min(f.kickoff_at - %s) FROM ai.batch_items i JOIN core.fixtures f ON f.id = i.fixture_id", (AT,)).fetchone()
    assert lead is not None and lead[0] >= timedelta(hours=4), "only matches four hours away or more wait"
    live_leads = db.execute("SELECT max(f.kickoff_at - %s) FROM ai.usage u JOIN core.fixtures f ON f.id = u.fixture_id "
                            "WHERE u.purpose = 'pick_review' AND u.batch_id IS NULL", (AT,)).fetchone()
    assert live_leads is not None and live_leads[0] < timedelta(hours=4), "and the others are asked now"
    assert n(db, "SELECT count(*) FROM ai.usage WHERE batch_id IS NOT NULL") == 0, "nothing is paid until the answer"
    assert n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'submitted'") == items
    assert n(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND output ? 'pending_llm'") == items, \
        "each says its model's review is on its way"
    assert n(db, "SELECT count(*) FROM ai.pick_reviews r JOIN ai.batch_items i ON i.fixture_id = r.fixture_id "
                 "WHERE r.engine = 'llm'") == 0
    assert n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'") == 6, "the sent batch lets the passes be recorded"
    row = db.execute("SELECT counts FROM ai.cycles WHERE kind = 'analysis' ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None and row[0]["batch_queued"] == items and row[0]["batches_sent"] == 1


def test_the_answer_arrives_is_paid_at_half_and_the_next_cycle_combines_it_without_asking_again(
        db: psycopg.Connection[Any], world: World) -> None:
    ran = first_pass(db)
    conn, model, fake = ran.conn, ran.model, ran.fake
    items = n(db, "SELECT count(*) FROM ai.batch_items")
    live_before = reviews_live(model)
    reserved = sum(reserved_by_day(conn, "production").values())
    assert reserved > 0
    fake.end()
    polled = poll(conn, SETTINGS, at=AT + timedelta(minutes=20), ledger=UsageLedger(shared(db)), client=fake)
    assert polled.counts == {"succeeded": items}
    assert sum(reserved_by_day(conn, "production").values()) == 0
    assert n(db, "SELECT count(*) FROM ai.usage WHERE batch_id IS NOT NULL AND status = 'ok'") == items
    assert n(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND output ->> 'via' = 'batch'") == items
    asked = n(db, "SELECT count(*) FROM ai.batch_items")
    again = cycle(conn, model, fake, at=AT + timedelta(minutes=30))
    assert again.status == "ok", again.errors
    assert reviews_live(model) == live_before, "the model was not asked again for what the batch answered"
    assert n(db, "SELECT count(*) FROM ai.batch_items") == asked == items, "and nothing new was queued"
    combined = db.execute("SELECT DISTINCT ON (fixture_id) fixture_id, output ? 'pending_llm', output -> 'engines' "
                          "FROM ai.pick_reviews WHERE engine = 'combined' AND fixture_id IN (SELECT fixture_id FROM ai.batch_items) "
                          "ORDER BY fixture_id, reviewed_at DESC, id DESC").fetchall()
    assert len(combined) == items
    for _fid, still_pending, engines in combined:
        assert not still_pending, "the model's review is in the combined one now"
        assert [e["engine"] for e in engines] == ["rules", "llm"] and engines[1]["carried"] is True
    assert n(db, "SELECT count(*) FROM ai.usage WHERE batch_id IS NOT NULL") == items, "paid once"


def test_without_the_batch_switch_or_its_gate_the_cycle_asks_in_real_time_exactly_as_before(
        db: psycopg.Connection[Any], world: World) -> None:
    for name, cfg in (("rolled back", settings(switches={"batch": "off"})), ("auto without evidence", settings(switches={}))):
        db.execute("SAVEPOINT arm")
        ran = first_pass(db, settings_=cfg)
        assert ran.report.status == "ok", (name, ran.report.errors)
        assert n(db, "SELECT count(*) FROM ai.batch_items") == 0 and ran.fake.created == [], name
        assert not any(k.startswith("batch") for k in ran.report.counts), name
        assert reviews_live(ran.model) >= 5, name
        db.execute("ROLLBACK TO SAVEPOINT arm")


def test_a_gate_that_names_the_models_it_was_measured_with_covers_only_those(db: psycopg.Connection[Any], world: World) -> None:
    auto = settings(switches={}, max_deep_per_day=0)  # no strong tier: every review is the intermediate model's
    for models, expect in (([SONNET], True), ([HAIKU], False), ([SONNET, OPUS], True)):
        db.execute("SAVEPOINT arm")
        record_gate(db, gate="batch", passed=True, evidence={"models": models, "probe": "test"}, at=AT - timedelta(hours=2))
        first_pass(db, settings_=auto)
        assert (n(db, "SELECT count(*) FROM ai.batch_items") > 0) is expect, models
        db.execute("ROLLBACK TO SAVEPOINT arm")
    db.execute("SAVEPOINT arm")
    record_gate(db, gate="batch", passed=True, evidence={"models": [SONNET]}, at=AT - timedelta(hours=3))
    record_gate(db, gate="batch", passed=False, evidence={"models": [SONNET]}, at=AT - timedelta(hours=2))
    first_pass(db, settings_=auto)
    assert n(db, "SELECT count(*) FROM ai.batch_items") == 0, "the newest evidence decides: a failing re-run switches it off"


def test_the_days_allowance_counts_the_reviews_waiting_in_a_batch(db: psycopg.Connection[Any], world: World) -> None:
    small = settings(max_llm_reviews_per_day=3)
    ran = first_pass(db, settings_=small)
    conn, model, fake = ran.conn, ran.model, ran.fake
    items = n(db, "SELECT count(*) FROM ai.batch_items")
    assert items + reviews_live(model) <= 3, "batched or live, a day pays for three"
    left = _allowance(conn, small, at=AT + timedelta(minutes=15))
    used = n(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND status = 'ok'")
    assert left.llm == max(0, 3 - used - items), "the open items hold their places"
    fake.end()
    poll(conn, small, at=AT + timedelta(minutes=20), ledger=UsageLedger(shared(db)), client=fake)
    after = _allowance(conn, small, at=AT + timedelta(minutes=25))
    assert after.llm == left.llm, "answered, they are spent instead of waiting: the same allowance"


def test_the_owners_run_now_is_never_batched(db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    model, fake = live_model(), FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    report = run_analysis_cycle(conn, at=AT, settings=SETTINGS, ledger=UsageLedger(shared(db)), only_fixtures=[world.fixtures["F5"]],
                                provider=(model, HAIKU), batches=fake, request=True)
    assert report.status == "ok", report.errors
    assert n(db, "SELECT count(*) FROM ai.batch_items") == 0 and fake.created == [] and reviews_live(model) == 1


def test_a_batch_that_cannot_be_created_leaves_the_passes_undone_and_the_third_try_is_real_time(
        db: psycopg.Connection[Any], world: World) -> None:
    down = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic", fail_create="unavailable")
    model = live_model()
    conn: Any = Savepoints(db)
    first = cycle(conn, model, down)
    waiting = first.counts["passes_to_retry"]
    assert first.status == "partial" and any("create_failed" in e for e in first.errors)
    assert waiting >= 1 and first.counts["batch_items_failed"] == waiting
    done = n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'")
    assert done + waiting == 6, "the matches whose reviews were not sent are not marked done"
    assert n(db, "SELECT count(*) FROM ai.usage WHERE purpose = 'pick_review'") == 1, "only the near match was paid"
    second = cycle(conn, model, down, at=AT + timedelta(minutes=15))
    assert second.counts["passes_to_retry"] == waiting and n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'") == done
    third = cycle(conn, model, down, at=AT + timedelta(minutes=30))
    assert third.status == "ok", third.errors
    assert third.counts["batch_refused_attempts"] == waiting and "passes_to_retry" not in third.counts
    assert n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'") == 6, "asked in real time, the passes are done"
    assert reviews_live(model) == 1 + waiting, "the reviews cost what they always did"
    assert n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'abandoned'") == 2 * waiting


def test_a_flush_that_raises_leaves_the_passes_to_the_next_cycle_and_the_records_to_be_abandoned(
        db: psycopg.Connection[Any], world: World) -> None:
    class Broken(FakeBatches):
        def create(self, items: list[dict[str, Any]]) -> dict[str, Any]:
            raise RuntimeError("the network fell over in a way nobody foresaw")

    conn: Any = Savepoints(db)
    model = live_model()
    first = cycle(conn, model, Broken(lambda r: review_reply(), name="anthropic"))
    assert first.status == "partial" and any("batch flush: RuntimeError" in e for e in first.errors)
    left = n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'submitting'")
    assert left >= 1 and first.counts["passes_to_retry"] == left, "recorded, never sent, and their passes not done"
    fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    second = cycle(conn, model, fake, at=AT + timedelta(minutes=15))
    assert second.status == "ok", second.errors
    assert second.counts["batch_items_unsent"] == left, "what the broken cycle recorded is abandoned as never sent"
    assert n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'submitted'") == left, "and asked again, in a batch that goes"
    assert n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'") == 6


def test_a_contradiction_a_batch_delivers_is_arbitrated_by_the_strong_model_at_the_next_pass(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import review as review_module

    real = review_module.rules_review

    def approving(c: Candidate, packet: Packet, *, at: datetime) -> Any:
        out, signals = real(c, packet, at=at)
        return out | {"decision": "APPROVE", "reason": "test: the rules approve"}, signals

    monkeypatch.setattr(review_module, "rules_review", approving)
    first_cfg = settings(max_deep_per_day=0)  # every review is the intermediate model's
    fake = FakeBatches(lambda r: review_reply("REJECT"), name="anthropic")  # and the model, in its batch, rejects them
    model = live_model("APPROVE")
    conn: Any = Savepoints(db)
    first = cycle(conn, model, fake, settings_=first_cfg)
    items = n(db, "SELECT count(*) FROM ai.batch_items")
    assert first.status == "ok" and items >= 1 and "batch_arbitrations" not in first.counts
    fake.end()
    poll(conn, first_cfg, at=AT + timedelta(minutes=20), ledger=UsageLedger(shared(db)), client=fake)
    delivered = n(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND output ->> 'via' = 'batch' "
                      "AND decision = 'REJECT' AND output ->> 'tier' = 'analysis'")
    assert delivered == items
    live_before = reviews_live(model)
    later_cfg = settings(max_deep_per_day=3)
    # two hours after the first pass the pre pass of the matches 6 h to 90 min away is due (``fbi.ai.day.due_pass``)
    second = cycle(conn, model, fake, at=AT + timedelta(hours=2, minutes=10), settings_=later_cfg)
    assert second.status == "ok", second.errors
    assert second.counts["batch_arbitrations"] >= 1
    arbiter = db.execute("SELECT r.decision, r.output ->> 'tier', r.output ->> 'role', r.output ? 'via' FROM ai.pick_reviews r "
                         "WHERE r.engine = 'llm' AND r.output ->> 'role' = 'contradiction'").fetchall()
    assert arbiter and all(a == ("APPROVE", "final", "contradiction", False) for a in arbiter), arbiter
    assert reviews_live(model) - live_before >= second.counts["batch_arbitrations"], "the strong model was asked in real time"
    done = len(arbiter)
    third = cycle(conn, model, fake, at=AT + timedelta(hours=2, minutes=25), settings_=later_cfg)
    assert third.counts.get("batch_arbitrations", 0) == 0, "once: its answer is now the newest review"
    assert n(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND output ->> 'role' = 'contradiction'") == done


# ── a cycle that is still running has not stopped ────────────────────────────────────────────────────────────────
# 31 Oct and 1 Nov 2026: the first cycle of the Bogotá day lasted 61 and 49 minutes (268 and 185 matches to study), the poll abandoned
# every batch it found ``submitting`` for over half an hour, and the 120 reviews the cycle had recorded to send at its end were never sent.
# The poll now asks whether a cycle holds its lock before it abandons anything (plan IA, phase 0).

@contextmanager
def holding_the_lock(dsn: str, *keys: int) -> Iterator[psycopg.Connection[Any]]:
    """Another session that holds the advisory lock ``keys`` names, as the worker's cycle holds ``CYCLE_LOCK`` from its start to its end."""
    other = psycopg.connect(dsn, autocommit=True)
    try:
        other.execute("SELECT pg_advisory_lock(%s)" if len(keys) == 1 else "SELECT pg_advisory_lock(%s, %s)", keys)
        yield other
    finally:
        other.execute("SELECT pg_advisory_unlock_all()")
        other.close()


class Quiet:
    """The connection of a poll that runs in the middle of a cycle in a test: the same session, so it sees what the cycle has recorded (the
    worker's poll sees it because the cycle commits each match), and it cannot end the test's transaction."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_the_probe_sees_the_cycles_lock_from_any_session_and_takes_nothing(env: Env, migrated_database: str) -> None:
    assert cycle_is_running(env.conn) is False, "nobody holds it"
    with holding_the_lock(migrated_database, CYCLE_LOCK):
        assert cycle_is_running(env.conn) is True, "a cycle of another session is running"
    assert cycle_is_running(env.conn) is False, "and it is not once that session lets go - or dies, which lets go too"
    with psycopg.connect(migrated_database, autocommit=True) as starting:  # a cycle that starts right after the probe
        got = starting.execute("SELECT pg_try_advisory_lock(%s)", (CYCLE_LOCK,)).fetchone()
        assert got == (True,), "the probe left no lock behind: it only looks"
        starting.execute("SELECT pg_advisory_unlock(%s)", (CYCLE_LOCK,))


def test_only_the_cycles_own_lock_counts(env: Env, migrated_database: str) -> None:
    for keys in ((CYCLE_LOCK + 1,), (CYCLE_LOCK << 32,), (0, CYCLE_LOCK), (CYCLE_LOCK, 0)):  # next key, key as high half, two-key forms
        with holding_the_lock(migrated_database, *keys):
            assert cycle_is_running(env.conn) is False, keys
    with holding_the_lock(ADMIN_URL, CYCLE_LOCK):  # the same key, in another database of the server
        assert cycle_is_running(env.conn) is False


def test_the_poll_leaves_alone_what_a_running_cycle_has_recorded_and_the_cycle_then_sends_it(env: Env, migrated_database: str) -> None:
    env.ask()
    env.conn.commit()  # the cycle commits each match: the poll's own session sees the record
    with holding_the_lock(migrated_database, CYCLE_LOCK):
        report = env.poll(at=AT + timedelta(minutes=61))  # twice what the poll used to wait
        assert (report.cycle_running, report.abandoned) == (True, 0)
        assert env.items("status", "error") == [("submitting", None)] and env.one("SELECT status FROM ai.batches") == "submitting"
    sent = env.queue.flush()  # the cycle reaches its end
    assert (sent.batches, sent.sent) == (1, 1) and len(env.fake.created) == 1
    assert env.items("status") == [("submitted",)]


def test_the_poll_abandons_what_was_recorded_and_never_sent_once_no_cycle_is_running(env: Env, migrated_database: str) -> None:
    env.ask()
    env.conn.commit()
    soon = env.poll(at=AT + timedelta(minutes=10))
    assert (soon.cycle_running, soon.abandoned) == (False, 0), "a recent record may still be about to be sent"
    with holding_the_lock(migrated_database, CYCLE_LOCK):
        assert env.poll(at=AT + timedelta(minutes=61)).abandoned == 0
    late = env.poll(at=AT + timedelta(minutes=66))  # the process that held the lock is gone: nothing will send this
    assert (late.cycle_running, late.abandoned) == (False, 1)
    assert env.items("status", "error") == [("abandoned", "never_sent")] and env.one("SELECT status FROM ai.batches") == "abandoned"
    assert env.poll(at=AT + timedelta(minutes=71)).abandoned == 0, "and it is said once"


def test_a_cycle_that_takes_over_half_an_hour_still_sends_everything_it_recorded(db: psycopg.Connection[Any], world: World) -> None:
    from .test_ai_decision_layer import brief_reply

    fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    looked: list[tuple[Any, int]] = []

    def slow(request: JsonRequest) -> dict[str, Any]:
        """Every time the cycle asks the model, the worker's poll looks, an hour into the cycle: it is the poll of 31 Oct."""
        waiting = n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'submitting'")
        looked.append((poll(Quiet(db), SETTINGS, at=AT + timedelta(minutes=61), ledger=UsageLedger(shared(db)), client=fake), waiting))
        return brief_reply() if request.schema_name == "submit_brief" else review_reply("APPROVE")

    report = cycle(Savepoints(db), FakeProvider(slow, name="anthropic"), fake)
    assert report.status == "ok", report.errors
    items = n(db, "SELECT count(*) FROM ai.batch_items")
    assert items >= 1 and max(waiting for _, waiting in looked) >= 1, "the poll looked while the cycle had records waiting to be sent"
    assert n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'abandoned'") == 0, "nothing was abandoned"
    assert n(db, "SELECT count(*) FROM ai.batch_items WHERE status = 'submitted'") == items, "everything recorded was sent"
    assert report.counts["batches_sent"] == 1 and report.counts["batch_items_sent"] == items
    assert len(fake.created) == 1 and len(fake.created[0]) == items
    assert n(db, "SELECT count(*) FROM ai.fixture_passes WHERE pass = 'first'") == 6, "and no pass was left to be done again"
    assert all(p.cycle_running and p.abandoned == 0 for p, _ in looked), "the poll knew a cycle was running every time it looked"


def test_the_cycle_holds_its_lock_for_its_whole_run_and_lets_go_of_it_however_it_ends(
        db: psycopg.Connection[Any], world: World, migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import cycle as cycle_module

    from .test_ai_decision_layer import brief_reply

    with psycopg.connect(migrated_database, autocommit=True) as polling:  # the session of the worker's poll
        during: list[bool] = []

        def watching(request: JsonRequest) -> dict[str, Any]:
            during.append(cycle_is_running(polling))
            return brief_reply() if request.schema_name == "submit_brief" else review_reply("APPROVE")

        assert cycle_is_running(polling) is False
        fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
        ran = cycle(Savepoints(db), FakeProvider(watching, name="anthropic"), fake)
        assert ran.status == "ok", ran.errors
        assert during and all(during), "held every time the cycle asks the model, which is most of its time"
        assert cycle_is_running(polling) is False, "and let go of when it ends"

        def falls_over(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("the cycle fell over")

        monkeypatch.setattr(cycle_module, "_run", falls_over)
        failed = cycle(Savepoints(db), live_model(), None, at=AT + timedelta(minutes=15))
        assert failed.status == "failed"
        assert cycle_is_running(polling) is False, "a cycle that fails lets go too: the poll can abandon what it left"

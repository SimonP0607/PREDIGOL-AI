"""The parts of the Message Batches route that need neither a database nor a network (Plan Maestro IA, section 29): the task's
idempotency key, the rule that says what goes in a batch, the price a task reserves, the candidate that survives the wait, and the
simulated API the integration tests lean on."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai.batch import (
    BATCH_PASSES,
    BATCH_ROLES,
    CYCLE_LOCK,
    CYCLE_RUNNING_SQL,
    BatchQueue,
    PollReport,
    Task,
    custom_id_of,
    decode_flags,
    estimate_cost,
)
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.pricing import approx_tokens, token_cost
from fbi.ai.providers import batches_for
from fbi.ai.providers.base import JsonRequest, ProviderError
from fbi.ai.providers.fake import FakeBatches
from fbi.ai.review import Candidate

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
SHAPE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET),
         "final": TierModel("anthropic", OPUS)}


def settings(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": dict(TIERS), "keys": {"anthropic": "sk-test-not-a-key"},
                            "switches": {"batch": "on"}}
    return AiSettings(**(base | over))


def request(**over: Any) -> JsonRequest:
    base: dict[str, Any] = {"system": "Eres un revisor.", "user": '{"candidate": 1}', "schema": {"type": "object"},
                            "schema_name": "submit_review", "max_tokens": 8000}
    return JsonRequest(**(base | over))


def task(**over: Any) -> Task:
    base: dict[str, Any] = {"purpose": "pick_review", "tier": "analysis", "request": request(), "prompt_version": "review-v3",
                            "input_hash": "a" * 64, "fixture_id": 7, "deadline_at": AT + timedelta(hours=7)}
    return Task(**(base | over))


def queue(**over: Any) -> BatchQueue:
    """A queue with no database behind it: ``routes`` reads the connection only for a switch left on ``auto``."""
    conn: Any = object()
    return BatchQueue(conn, over.pop("settings", settings()), at=over.pop("at", AT))


# ── the idempotency key ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_key_has_the_shape_the_api_asks_and_is_the_same_for_the_same_task() -> None:
    a, b = custom_id_of(task(), SONNET), custom_id_of(task(), SONNET)
    assert a == b and SHAPE.match(a) and len(a) == 48


@pytest.mark.parametrize("change", [{"input_hash": "b" * 64}, {"tier": "final"}, {"prompt_version": "review-v4"},
                                    {"lab": True}, {"agent": "match"}])
def test_any_part_of_the_task_changes_its_key(change: dict[str, Any]) -> None:
    assert custom_id_of(task(**change), SONNET) != custom_id_of(task(), SONNET), change


def test_the_model_changes_the_key_but_where_it_runs_does_not() -> None:
    assert custom_id_of(task(), OPUS) != custom_id_of(task(), SONNET)
    moved = task(fixture_id=99, deadline_at=AT, context={"anything": 1}, run_id=3)
    assert custom_id_of(moved, SONNET) == custom_id_of(task(), SONNET), \
        "what the answer is stored under is not part of what is asked"


# ── what goes in a batch ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_plans_table_is_the_first_and_pre_passes_and_a_candidates_review() -> None:
    assert set(BATCH_PASSES) == {"first", "pre"} and set(BATCH_ROLES) == {"candidate", "pick"}
    q = queue()
    assert q.routes(tier="analysis", pass_kind="first", kickoff_at=AT + timedelta(hours=8))
    assert q.routes(tier="final", pass_kind="pre", kickoff_at=AT + timedelta(hours=5), role="pick")
    for kind in ("final", "request"):
        assert not q.routes(tier="analysis", pass_kind=kind, kickoff_at=AT + timedelta(hours=8)), kind
    for role in ("watch", "contradiction", "arbitration"):
        assert not q.routes(tier="analysis", pass_kind="first", kickoff_at=AT + timedelta(hours=8), role=role), role


def test_a_match_closer_than_the_lead_time_is_asked_in_real_time() -> None:
    q = queue()
    assert q.routes(tier="analysis", pass_kind="pre", kickoff_at=AT + timedelta(minutes=240))
    assert not q.routes(tier="analysis", pass_kind="pre", kickoff_at=AT + timedelta(minutes=239))
    wider = queue(settings=settings(batch_min_lead_minutes=360))
    assert not wider.routes(tier="analysis", pass_kind="pre", kickoff_at=AT + timedelta(minutes=300))
    assert wider.routes(tier="analysis", pass_kind="pre", kickoff_at=AT + timedelta(minutes=360))


def test_only_an_anthropic_model_with_a_key_is_asked_in_a_batch() -> None:
    kickoff = AT + timedelta(hours=8)
    assert not queue(settings=settings(keys={})).routes(tier="analysis", pass_kind="first", kickoff_at=kickoff)
    other = settings(tiers={"analysis": TierModel("openai", "gpt"), "bulk": None, "final": None}, keys={"openai": "k"})
    assert not queue(settings=other).routes(tier="analysis", pass_kind="first", kickoff_at=kickoff)
    assert not queue().routes(tier="analysis", pass_kind="first", kickoff_at=kickoff, lab=True), \
        "the LAB workspace has no key of its own here: an experiment never spends production's"
    lab = settings(lab_keys={"anthropic": "sk-lab-not-a-key"})
    assert queue(settings=lab).routes(tier="analysis", pass_kind="first", kickoff_at=kickoff, lab=True), \
        "with a key of its own the LAB workspace batches too"
    assert not queue(settings=settings(keys={}, lab_keys={"anthropic": "sk-lab-not-a-key"})).routes(
        tier="analysis", pass_kind="first", kickoff_at=kickoff), "and production, without its own key, does not borrow the LAB's"


def test_the_owners_switch_rolls_batch_back() -> None:
    off = queue(settings=settings(switches={"batch": "off"}))
    assert not off.routes(tier="analysis", pass_kind="first", kickoff_at=AT + timedelta(hours=8))


# ── what a task reserves ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_task_reserves_half_the_price_of_its_real_time_call() -> None:
    req = request(user="x" * 8000)
    tokens_in = approx_tokens(req.system + req.user_text + '{"type": "object"}', "anthropic")
    batch = estimate_cost(SONNET, req, typical_output=900, at=AT)
    live = token_cost("anthropic", SONNET, input_tokens=tokens_in, output_tokens=900, at=AT)
    assert batch == (live / 2).quantize(Decimal("0.000001")) and batch > 0
    assert estimate_cost(OPUS, req, typical_output=900, at=AT) > batch, "the stronger model costs more"


def test_the_typical_output_is_capped_by_the_request_and_defaults_to_half_of_it() -> None:
    req = request(max_tokens=1000)
    assert estimate_cost(SONNET, req, typical_output=50_000, at=AT) == estimate_cost(SONNET, req, typical_output=1000, at=AT)
    assert estimate_cost(SONNET, req, typical_output=None, at=AT) == estimate_cost(SONNET, req, typical_output=500, at=AT)


# ── how the answer will be read ──────────────────────────────────────────────────────────────────────────────────

def test_the_flags_say_how_to_read_the_answer_and_how_a_cache_write_is_priced() -> None:
    tool = {"model": SONNET, "tools": [{"name": "submit_review"}], "system": "plain"}
    assert decode_flags(tool, "submit_review") == {"schema_name": "submit_review", "native": False, "long_ttl": False}
    native = {"model": SONNET, "output_config": {"format": {"type": "json_schema", "schema": {}}},
              "system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]}
    assert decode_flags(native, "x") == {"schema_name": "x", "native": True, "long_ttl": True}
    short = {"model": SONNET, "system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}]}
    assert decode_flags(short, "x")["long_ttl"] is False


# ── the candidate that waits ─────────────────────────────────────────────────────────────────────────────────────

def test_a_candidate_comes_back_from_its_state_exactly() -> None:
    c = Candidate(fixture_id=11, market_key="OU", selection="Over", line=Decimal("2.5"), p_model=Decimal("0.5210"),
                  kickoff_at=AT + timedelta(hours=8), pick_id=4, odds=Decimal("1.930"), bookmaker_id=3, bookmaker="BK",
                  p_low=Decimal("0.4800"), p_high=Decimal("0.5600"), p_push=Decimal("0"), p_market=Decimal("0.4900"),
                  ev=Decimal("0.0055"), model="dixon_coles", n_bookmakers=9, price_at=AT - timedelta(minutes=5),
                  selected_at=AT - timedelta(hours=1))
    back = Candidate.from_state(c.to_state())
    assert back == c and back.as_json() == c.as_json()
    bare = Candidate(fixture_id=1, market_key="1X2", selection="Home", line=Decimal(0), p_model=Decimal("0.5"), kickoff_at=AT)
    assert Candidate.from_state(bare.to_state()) == bare, "a candidate with almost nothing known"


def test_the_state_of_a_candidate_is_plain_json() -> None:
    import json

    c = Candidate(fixture_id=1, market_key="1X2", selection="Home", line=Decimal(0), p_model=Decimal("0.5"), kickoff_at=AT,
                  odds=Decimal("2.100"), price_at=AT)
    assert Candidate.from_state(json.loads(json.dumps(c.to_state()))) == c, "it goes through the database as jsonb"


# ── the simulated API ────────────────────────────────────────────────────────────────────────────────────────────

def script(r: JsonRequest) -> dict[str, Any]:
    return {"answer": r.schema_name}


def body(cid: str) -> dict[str, Any]:
    return FakeBatches.item(cid, SONNET, request())


def test_the_simulation_refuses_what_the_real_api_refuses() -> None:
    fake = FakeBatches(script)
    for items in ([], [body("a"), body("a")], [body("has space")], [body("x" * 65)]):
        with pytest.raises(ProviderError) as err:
            fake.create(items)
        assert err.value.code == "refused"
    assert fake.batches == {}, "nothing was created"


def test_a_batch_stays_open_until_the_test_ends_it_and_then_answers_each_request() -> None:
    fake = FakeBatches(script)
    made = fake.create([body("one"), body("two")])
    ref = made["id"]
    assert made["processing_status"] == "in_progress" and fake.get(ref)["request_counts"]["processing"] == 2
    with pytest.raises(ProviderError):
        fake.results(ref)  # not ended: HTTP 409 as the real one
    fake.end(ref, outcomes={"two": "errored"})
    assert fake.get(ref)["processing_status"] == "ended"
    got = {r.custom_id: r for r in fake.results(ref)}
    assert got["one"].kind == "succeeded" and got["one"].message is not None
    assert got["two"].kind == "errored" and got["two"].message is None
    assert fake.custom_ids() == ["one", "two"] and fake.polls == 2


def test_the_simulation_can_fail_to_create_or_hit_a_spend_limit() -> None:
    down = FakeBatches(script, fail_create="unavailable")
    with pytest.raises(ProviderError) as err:
        down.create([body("a")])
    assert err.value.code == "unavailable"
    limit = FakeBatches(script, limit="workspace_limit")
    with pytest.raises(ProviderError) as hit:
        limit.create([body("a")])
    assert hit.value.code == "limit_reached" and hit.value.limit_kind == "workspace_limit" and hit.value.status == 400
    tier = FakeBatches(script, limit="tier_cap")
    with pytest.raises(ProviderError) as cap:
        tier.create([body("a")])
    assert cap.value.status == 429


def test_a_canceled_batch_answers_canceled_unless_the_test_scripted_otherwise() -> None:
    fake = FakeBatches(script)
    ref = fake.create([body("a"), body("b")])["id"]
    assert fake.cancel(ref)["processing_status"] == "canceling"
    fake.end(ref, outcomes={"b": "expired"})
    got = {r.custom_id: r.kind for r in fake.results(ref)}
    assert got == {"a": "canceled", "b": "expired"}


def test_the_client_of_a_workspace_exists_only_with_its_own_key() -> None:
    assert batches_for(AiSettings(mode="shadow")) is None
    assert batches_for(settings(keys={}), lab=False) is None
    assert batches_for(settings()) is not None
    assert batches_for(settings(), lab=True) is None, "production's key is never the LAB's"
    assert batches_for(settings(lab_keys={"anthropic": "sk-lab-not-a-key"}), lab=True) is not None


def test_a_task_is_immutable() -> None:
    t = task()
    assert replace(t, tier="final").tier == "final" and t.tier == "analysis"
    with pytest.raises(AttributeError):
        t.tier = "final"  # type: ignore[misc]


# ── when a review a batch delivered is arbitrated ────────────────────────────────────────────────────────────────

def reviewed(rules: str, carried: str | None, *, via: str | None = "batch", tier: str = "analysis") -> Any:
    from fbi.ai.review import EngineResult, Reviewed

    cand = Candidate(fixture_id=1, market_key="1X2", selection="Home", line=Decimal(0), p_model=Decimal("0.5"), kickoff_at=AT)
    out = EngineResult("rules", "rules-v1", rules, {"decision": rules})  # type: ignore[arg-type]
    prior = None if carried is None else EngineResult(
        "llm", "review-v3", carried, {"tier": tier} | ({} if via is None else {"via": via}))  # type: ignore[arg-type]
    return Reviewed(cand, rules, out, None, 1, [], {}, prior)  # type: ignore[arg-type]


@pytest.mark.parametrize(("rules", "model"), [("APPROVE", "REJECT"), ("REJECT", "APPROVE")])
def test_a_batch_review_the_rules_contradict_outright_is_arbitrated(rules: str, model: str) -> None:
    from fbi.ai.cycle import _arbitrable

    assert _arbitrable(reviewed(rules, model), use_llm=False)


@pytest.mark.parametrize(("rules", "carried", "kw"), [
    ("APPROVE", "APPROVE", {}), ("DOWNGRADE", "REJECT", {}), ("APPROVE", "DOWNGRADE", {}), ("ABSTAIN", "REJECT", {}),
    ("APPROVE", None, {}),
    ("APPROVE", "REJECT", {"via": None}),  # a live review was arbitrated in its own cycle
    ("APPROVE", "REJECT", {"tier": "final"}),  # the strong model has already spoken
])
def test_anything_else_is_not_arbitrated(rules: str, carried: str | None, kw: dict[str, Any]) -> None:
    from fbi.ai.cycle import _arbitrable

    assert not _arbitrable(reviewed(rules, carried, **kw), use_llm=False)


def test_a_review_asked_in_this_pass_is_judged_by_the_pass_not_by_the_carried_one() -> None:
    from fbi.ai.cycle import _arbitrable

    assert not _arbitrable(reviewed("APPROVE", "REJECT"), use_llm=True)


# ── the poll and the cycle that is still running ────────────────────────────────────────────────────────────────

def test_the_cycle_and_the_poll_name_the_same_lock() -> None:
    from fbi.ai import cycle

    assert cycle.CYCLE_LOCK is CYCLE_LOCK, "one definition: the lock the cycle takes is the lock the poll looks at"
    assert 0 <= CYCLE_LOCK < 2**32, "the probe reads it as classid 0 and objid = the key: true only for a key under 2^32"


def test_the_probe_only_looks_at_the_list_of_locks() -> None:
    sql = " ".join(CYCLE_RUNNING_SQL.split()).lower()
    assert "from pg_locks" in sql and "advisory_lock" not in sql, "taking the lock to find out would make a cycle that starts then skip its work"
    assert "objsubid = 1" in sql and "current_database()" in sql and "granted" in sql
    assert CYCLE_RUNNING_SQL.count("%s") == 1


def test_a_poll_report_says_nothing_was_abandoned_and_no_cycle_was_running_until_it_finds_out() -> None:
    quiet = PollReport()
    assert (quiet.abandoned, quiet.cycle_running) == (0, False)

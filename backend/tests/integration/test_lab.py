"""The LAB's experiments (Plan Maestro IA, Phase 0): the probes that open the ``batch`` gate and say whether the cache works, and the
equivalence test that opens ``native_schema`` and ``cache_layout`` - on stored reviews, with the Message Batches API simulated.

What is checked is what makes the evidence worth anything: every call is the LAB workspace's (its key alone, its own scope in the ledger,
its own envelope); a request is exactly what the experiment asked for whatever production's switches say; the four asks of one input
go to the model as they are measured; nothing is half-sent; asking again pays nothing twice; the gates are decided by the rule written
before the data, with the evidence that lets anyone recompute it, and a failing run closes what a passing one opened; and nothing the
LAB does touches a review, a pick, a packet or any state of production.

No network and no key: the provider is a mock transport or ``FakeBatches``. One transaction, rolled back."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
import psycopg
import pytest

from fbi.ai import batch as batch_mod
from fbi.ai import gates, lab
from fbi.ai.batch import BatchQueue, Resolved, handler_for, poll
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.packet import Packet, load_packet, store_packet
from fbi.ai.pricing import approx_tokens
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.providers.base import JsonRequest, LlmUsage
from fbi.ai.providers.fake import FakeBatches
from fbi.ai.review import Candidate, EngineResult, store_review
from fbi.ai.usage import UsageLedger, budget_v2, shared

from .conftest import Seed
from .test_ai_decision_layer import Savepoints, review_reply
from .test_brief_material import content, fixture_block

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET),
         "final": TierModel("anthropic", OPUS)}
AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
"""The kick-off of the seeded fixture: the stored reviews were made before it, on the days before ``AT``."""
FIRST_REVIEW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
SMALL = {"n": 12, "min_inputs": 10}
"""A test's experiment: twelve stored inputs and a bar of ten. The plan's 200 is the default of everything else (and has its own test)."""


def cfg(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": dict(TIERS), "keys": {"anthropic": "sk-test-production-key"},
                            "base_urls": {"anthropic": "https://api.example"}, "lab_keys": {"anthropic": "sk-test-lab-key"},
                            "lab_monthly_budget": Decimal(15)}
    return AiSettings(**(base | over))


# ── the Messages API, as far as the probes see it ────────────────────────────────────────────────────────────────

class Api:
    """The Messages API seen from the real-time probes: it remembers the key each call came with, has a prompt cache of its own (a
    prefix marked for it is written by the first call and read by the next) and answers inside the probe's schema."""

    def __init__(self, *, cache: bool = True, native_word: str = "beta") -> None:
        self.keys: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.cache = cache
        self.native_word = native_word
        self._written: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.keys.append(request.headers["x-api-key"])
        self.bodies.append(body)
        system, user = body["system"], body["messages"][0]["content"]
        sys_text = system[0]["text"] if isinstance(system, list) else system
        blocks = user if isinstance(user, list) else [{"text": user}]
        common = blocks[0]["text"] if len(blocks) > 1 else ""
        n_sys, n_common = approx_tokens(sys_text, "anthropic"), approx_tokens(common, "anthropic")
        usage: dict[str, Any] = {"input_tokens": n_sys + n_common + 30, "output_tokens": 25}
        if self.cache and isinstance(system, list):
            key = body["model"] + sys_text + common
            if key in self._written:
                usage = {"input_tokens": 30, "output_tokens": 25, "cache_read_input_tokens": n_sys + n_common}
            else:
                self._written.add(key)
                usage = {"input_tokens": 30, "output_tokens": 25, "cache_creation_input_tokens": n_sys + n_common,
                         "cache_creation": {"ephemeral_5m_input_tokens": n_common, "ephemeral_1h_input_tokens": n_sys}}
        native = "tools" not in body
        data = {"word": self.native_word if native else "alpha", "number": 1}
        message: dict[str, Any] = {"id": "msg_probe", "type": "message", "role": "assistant", "model": body["model"],
                                   "stop_reason": "end_turn" if native else "tool_use", "usage": usage,
                                   "content": [{"type": "text", "text": json.dumps(data)}] if native
                                   else [{"type": "tool_use", "id": "toolu_1", "name": "submit_probe", "input": data}]}
        return httpx.Response(200, headers={"request-id": "req_probe"}, json=message)


class NoCalls:
    """A transport that fails the test if anything is sent."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"something was sent to {request.url}")


# ── the model of the equivalence test ────────────────────────────────────────────────────────────────────────────

@dataclass
class Panel:
    """What the scripted model decides: APPROVE for every input, every time - except where a test says an ask differs (the second
    identical call, structured outputs, the common block first), which then DOWNGRADES. It also answers a probe."""

    index: dict[tuple[str, str], int] = field(default_factory=dict)
    repeat: set[int] = field(default_factory=set)
    native: set[int] = field(default_factory=set)
    shared: set[int] = field(default_factory=set)
    seen: Counter[int] = field(default_factory=Counter)

    def __call__(self, request: JsonRequest) -> dict[str, Any]:
        if "word" in request.schema.get("properties", {}):
            return {"word": "alpha", "number": 1}
        cand = json.loads(request.user)["candidate"]
        i = self.index[(cand["selection"], str(Decimal(cand["odds"])))]
        if request.native_schema:
            ask = "B"
        elif request.shared:
            ask = "C"
        else:
            self.seen[i] += 1
            ask = "A1" if self.seen[i] == 1 else "A2"
        differs = (ask == "A2" and i in self.repeat) or (ask == "B" and i in self.native) or (ask == "C" and i in self.shared)
        return reply("DOWNGRADE" if differs else "APPROVE")

    def renew(self) -> None:
        """A new experiment: the first identical call of an input is the first again."""
        self.seen.clear()


def reply(decision: str) -> dict[str, Any]:
    """A review the checker accepts for the stored packets: its claim cites numbers the packet holds (the model's 52,0 % and the
    market's 45,0 %), so an APPROVE is an APPROVE and not an ABSTAIN for lack of a verified claim."""
    return review_reply(decision, positive_evidence=[{"text": "Modelo 52.0 % frente a mercado 45.0 %.", "type": "DATA",
                                                       "refs": ["P:candidate", "P:market"]}])


SELECTIONS = (("Home", "2.400", "0.5200", "0.4500"), ("Draw", "3.500", "0.2500", "0.2800"), ("Away", "3.600", "0.2300", "0.2700"))


Status = Literal["ok", "fallback", "invalid_output", "failed", "over_budget", "pending"]


def stored_reviews(conn: Any, seed: Seed, packets: int, *, model: str = SONNET, engine: Literal["rules", "llm", "combined"] = "llm",
                   status: Status = "ok", start: int = 0, at0: datetime = FIRST_REVIEW) -> dict[tuple[str, str], int]:
    """``packets`` packets of the seeded match, each with the reviews of its three selections as the layer stores them: the inputs of
    the test. Returns (selection, odds) -> the input's number, which is how the scripted model tells one input from another."""
    index: dict[tuple[str, str], int] = {}
    for k in range(start, start + packets):
        when = at0 + timedelta(minutes=k)
        packet = Packet(seed.fixture_id, when, content(seed, odds=2.4 + 0.001 * k)
                        | {"fixture": fixture_block(seed, kickoff_at=KO.isoformat())})
        pid = store_packet(conn, packet, built_at=when)
        for s, (selection, odds, p_model, p_market) in enumerate(SELECTIONS):
            price = Decimal(odds) + Decimal("0.001") * k
            cand = Candidate(fixture_id=seed.fixture_id, market_key="1X2", selection=selection, line=Decimal(0),
                             p_model=Decimal(p_model), kickoff_at=KO, odds=price, bookmaker_id=seed.bookmaker_id,
                             bookmaker="Bet365", p_low=Decimal(p_model) - Decimal("0.05"), p_market=Decimal(p_market),
                             ev=Decimal("0.0500"))
            out = EngineResult(engine, REVIEW_VERSION, "APPROVE", reply("APPROVE") | {"tier": "analysis"},
                               status, None, "anthropic", model, [], Decimal("0.03"), f"h-{k}-{selection}")
            store_review(conn, out, cand, packet=packet, packet_id=pid, at=when, mode="shadow")
            index[(selection, str(price))] = 3 * k + s
    return index


@dataclass
class Lab:
    db: psycopg.Connection[Any]
    conn: Any
    seed: Seed
    ledger: UsageLedger
    fake: FakeBatches
    panel: Panel

    def stored(self, packets: int = 4, **kw: Any) -> None:
        self.panel.index |= stored_reviews(self.conn, self.seed, packets, **kw)

    def submit(self, settings: AiSettings | None = None, at: datetime = AT, **kw: Any) -> dict[str, Any]:
        return lab.equivalence_submit(self.conn, settings or cfg(), at=at, ledger=self.ledger, client=self.fake, **(SMALL | kw))

    def end(self) -> None:
        self.fake.end()

    def collect(self, settings: AiSettings | None = None, at: datetime = AT + timedelta(hours=2), **kw: Any) -> dict[str, Any]:
        return lab.equivalence_collect(self.conn, settings or cfg(), at=at, ledger=self.ledger, client=self.fake,
                                       **({"min_inputs": SMALL["min_inputs"]} | kw))

    def one(self, sql: str, *params: Any) -> Any:
        row = self.db.execute(sql, params).fetchone()
        return None if row is None else row[0] if len(row) == 1 else row

    def gate_rows(self, gate: str) -> list[tuple[bool, dict[str, Any]]]:
        rows = self.db.execute("SELECT passed, evidence FROM ai.feature_gates WHERE gate = %s ORDER BY id", (gate,)).fetchall()
        return [(bool(r[0]), dict(r[1])) for r in rows]

    def items_by_variant(self) -> dict[str, list[str]]:
        """custom_id of every item of the experiment, by ask."""
        out: dict[str, list[str]] = {}
        for cid, variant in self.db.execute("SELECT custom_id, context ->> 'variant' FROM ai.batch_items ORDER BY id").fetchall():
            out.setdefault(str(variant), []).append(str(cid))
        return out

    def bodies(self) -> dict[str, dict[str, Any]]:
        """The request body of every item sent, by custom_id."""
        return {str(i["custom_id"]): i["params"] for b in self.fake.created for i in b}

    def see_the_probes(self, *, model: str = SONNET, native: bool = True) -> None:
        """What the probes leave behind when they have run: a batch gate that says structured outputs worked inside a batch, and a
        ledger row of the LAB's cache probe that read the cache."""
        gates.record_gate(self.conn, gate="batch", passed=True, at=AT,
                          evidence={"models": [model], "native_in_batch": {model: native}})
        self.ledger.record(at=AT, purpose="other", tier="analysis", provider="anthropic", model=model,
                           usage=LlmUsage(input_tokens=3300, output_tokens=25, cached_tokens=3200), cost=Decimal("0.001"),
                           status="ok", prompt_version=lab.PROBE_CACHE_VERSION, workspace="PREDIGOL-LAB", key_label="worker-lab")


@pytest.fixture()
def box(db: psycopg.Connection[Any], seed: Seed) -> Lab:
    conn: Any = Savepoints(db)
    panel = Panel()
    return Lab(db, conn, seed, UsageLedger(shared(db)), FakeBatches(panel, name="anthropic"), panel)


# ── the probes: every call is the LAB's ─────────────────────────────────────────────────────────────────────────────

def test_the_cache_probe_writes_then_reads_and_is_paid_with_the_lab_key_alone(box: Lab) -> None:
    api = Api()
    report = lab.probe_cache(box.conn, cfg(), at=AT, ledger=box.ledger, transport=api.transport())
    assert report["ok"] is True and set(report["tiers"]) == {"bulk", "analysis"}
    for tier, model in (("bulk", HAIKU), ("analysis", SONNET)):
        t = report["tiers"][tier]
        assert t["model"] == model and t["ok"] and t["wrote"] and t["read"] and t["read_what_was_written"] and t["both_ttls"]
        assert t["usage"][0]["wrote_5m"] > 1000 and t["usage"][0]["wrote_1h"] > 1000 and t["usage"][1]["read"] > 2000
    assert set(api.keys) == {"sk-test-lab-key"} and len(api.keys) == 4, "four calls, the LAB's key every time, production's never"
    rows = box.db.execute("SELECT scope, purpose, prompt_version, model, cached_tokens FROM ai.usage_scoped ORDER BY id").fetchall()
    assert [r[:3] for r in rows] == [("lab", "other", "probe-cache-v1")] * 4
    assert [r[4] > 0 for r in rows] == [False, True, False, True]
    assert lab.cache_probe_ok(box.conn, SONNET, since=AT - timedelta(days=1)) and lab.cache_probe_ok(box.conn, HAIKU, since=AT - timedelta(days=1))
    assert not lab.cache_probe_ok(box.conn, OPUS, since=AT - timedelta(days=1)), "a probe says what it saw, for the model it saw it with"
    assert not lab.cache_probe_ok(box.conn, SONNET, since=AT + timedelta(days=1)), "and only lately"


def test_a_cache_that_never_reads_is_reported_as_not_working(box: Lab) -> None:
    report = lab.probe_cache(box.conn, cfg(), at=AT, ledger=box.ledger, transport=Api(cache=False).transport())
    assert report["ok"] is False
    assert report["tiers"]["analysis"]["wrote"] is False and report["tiers"]["analysis"]["read"] is False
    assert not lab.cache_probe_ok(box.conn, SONNET, since=AT - timedelta(days=1)), "nothing for a gate to stand on"


def test_a_tier_the_budget_lowered_is_not_a_probe_of_that_tier(box: Lab) -> None:
    v2 = cfg(switches={"budget_v3": "off"}, daily_budget=Decimal(1), monthly_budget=Decimal(100))
    daily = budget_v2(box.conn, at=AT, settings=v2).daily
    box.ledger.record(at=AT, purpose="pick_review", tier="analysis", provider="anthropic", model=SONNET, usage=LlmUsage(input_tokens=1),
                      cost=daily * Decimal("1.05"), status="ok", workspace="PREDIGOL", key_label="worker-prod")
    assert budget_v2(box.conn, at=AT, settings=v2).state == "REDUCED", "the final tier is not allowed; the analysis one is"
    api = Api()
    report = lab.probe_cache(box.conn, v2, at=AT, tiers=("final",), ledger=box.ledger, transport=api.transport())
    assert report["ok"] is False and report["tiers"]["final"]["ok"] is False
    assert "lowered the tier" in report["tiers"]["final"]["error"]
    assert {b["model"] for b in api.bodies} == {SONNET}, "what ran was another model: nothing was measured for Opus"
    assert not lab.cache_probe_ok(box.conn, OPUS, since=AT - timedelta(days=1))


def test_the_schema_probe_asks_the_tool_route_and_structured_outputs(box: Lab) -> None:
    api = Api()
    report = lab.probe_schema(box.conn, cfg(), at=AT, ledger=box.ledger, transport=api.transport())
    assert report["ok"] is True
    for tier in ("bulk", "analysis"):
        assert report["tiers"][tier]["tool"]["valid"] and report["tiers"][tier]["native"]["valid"]
        assert report["tiers"][tier]["native"]["stop_reason"] == "end_turn" and report["tiers"][tier]["tool"]["stop_reason"] == "tool_use"
    tool, native = api.bodies[0], api.bodies[1]
    assert "tools" in tool and "format" not in tool.get("output_config", {})
    assert "tools" not in native and native["output_config"]["format"]["type"] == "json_schema"
    assert set(api.keys) == {"sk-test-lab-key"}


def test_an_answer_outside_the_schema_fails_the_probe_whatever_the_provider_promised(box: Lab) -> None:
    report = lab.probe_schema(box.conn, cfg(), at=AT, ledger=box.ledger, transport=Api(native_word="delta").transport())
    assert report["ok"] is False
    assert report["tiers"]["analysis"]["tool"]["valid"] is True and report["tiers"]["analysis"]["native"]["valid"] is False


def test_without_a_lab_key_or_an_envelope_no_probe_leaves_the_machine(box: Lab) -> None:
    nokey = cfg(lab_keys={}, lab_monthly_budget=Decimal(0))
    transport = httpx.MockTransport(NoCalls())
    for probe in (lab.probe_cache, lab.probe_schema):
        out = probe(box.conn, nokey, at=AT, ledger=box.ledger, transport=transport)
        assert out["ok"] is False and any("FBI_AI_KEY_ANTHROPIC_LAB" in b for b in out["blockers"])
        assert any("FBI_AI_LAB_MONTHLY_BUDGET_USD" in b for b in out["blockers"])
    assert box.one("SELECT count(*) FROM ai.usage") == 0
    out = lab.probe_batch_submit(box.conn, nokey, at=AT, ledger=box.ledger, client=box.fake)
    assert out["submitted"] == 0 and out["blockers"] and box.fake.created == [] and box.one("SELECT count(*) FROM ai.batch_items") == 0


# ── the probe of the Message Batches API ────────────────────────────────────────────────────────────────────────────

def probe_state(box: Lab) -> dict[str, Any]:
    return lab.probe_batch_collect(box.conn, cfg(), at=AT + timedelta(hours=1), ledger=box.ledger, client=box.fake)


def test_the_batch_probe_is_sent_once_a_day_and_opens_the_gate_for_the_models_it_saw(box: Lab) -> None:
    sent = lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    assert sent["tasks"] == 6 and sent["states"] == {"queued": 6} and sent["sent"] == 6 and len(box.fake.created) == 1
    row = box.db.execute("SELECT b.kind, b.workspace, b.key_label, count(*) FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id "
                         "GROUP BY 1, 2, 3").fetchall()
    assert row == [("lab", "PREDIGOL-LAB", "worker-lab", 6)]
    bodies = box.bodies()
    by_variant = box.items_by_variant()
    assert set(by_variant) == {"tool", "native", "tool2"} and all(len(v) == 2 for v in by_variant.values())
    for cid in by_variant["tool"] + by_variant["tool2"]:
        assert "tools" in bodies[cid] and bodies[cid]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert bodies[cid]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}, "the common block is marked: 5 minutes"
    for cid in by_variant["native"]:
        assert "tools" not in bodies[cid] and bodies[cid]["output_config"]["format"]["type"] == "json_schema"
    waiting = probe_state(box)
    assert waiting["state"] == "waiting" and waiting["open"] == 6 and box.gate_rows("batch") == [], "nothing is decided on the way"
    box.end()
    done = probe_state(box)
    assert done["passed"] is True and done["models"] == [HAIKU, SONNET] and done["gate_id"] is not None
    rows = box.gate_rows("batch")
    assert len(rows) == 1 and rows[0][0] is True and rows[0][1]["run"] == "2026-09-14" and rows[0][1]["models"] == [HAIKU, SONNET]
    assert rows[0][1]["native_in_batch"] == {HAIKU: True, SONNET: True}
    settings = cfg()
    assert gates.enabled(box.conn, settings, "batch", model=SONNET) and gates.enabled(box.conn, settings, "batch", model=HAIKU)
    assert not gates.enabled(box.conn, settings, "batch", model=OPUS), "another model is not covered by the evidence"
    again = probe_state(box)
    assert again["passed"] is True and again["gate_id"] is None and len(box.gate_rows("batch")) == 1, "the same evidence is one row"
    resent = lab.probe_batch_submit(box.conn, cfg(), at=AT + timedelta(hours=3), ledger=box.ledger, client=box.fake)
    assert resent["states"] == {"done": 6} and len(box.fake.created) == 1, "asking the same day pays nothing twice"
    spent = box.db.execute("SELECT scope, count(*) FROM ai.usage_scoped GROUP BY 1").fetchall()
    assert spent == [("lab", 6)], "six answers, all of them the LAB's"


def test_a_model_whose_batch_probe_failed_is_left_out_of_the_gate(box: Lab) -> None:
    lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    bad = box.db.execute("SELECT custom_id FROM ai.batch_items WHERE model = %s AND context ->> 'variant' = 'tool'", (SONNET,)).fetchone()
    assert bad is not None
    box.fake.end(outcomes={str(bad[0]): "errored"})
    out = probe_state(box)
    assert out["passed"] is True and out["models"] == [HAIKU] and out["failed_models"] == [SONNET]
    assert gates.enabled(box.conn, cfg(), "batch", model=HAIKU) and not gates.enabled(box.conn, cfg(), "batch", model=SONNET)


def test_when_no_model_answered_inside_the_schema_the_batch_gate_is_recorded_as_failed(box: Lab) -> None:
    lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    box.fake.end(outcomes=dict.fromkeys(box.items_by_variant()["tool"], "expired"))
    out = probe_state(box)
    assert out["passed"] is False and out["models"] == [] and sorted(out["failed_models"]) == [HAIKU, SONNET]
    assert [p for p, _ in box.gate_rows("batch")] == [False]
    assert not gates.enabled(box.conn, cfg(), "batch", model=SONNET)


def test_the_batch_probe_is_all_or_nothing(box: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    real = BatchQueue._unaffordable

    def refuse_the_third(self: BatchQueue, task: Any, estimate: Decimal) -> str | None:
        calls["n"] += 1
        return "lab_budget" if calls["n"] == 3 else real(self, task, estimate)

    monkeypatch.setattr(BatchQueue, "_unaffordable", refuse_the_third)
    out = lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    assert out["submitted"] == 0 and out["refused"] == {"lab_budget": 1} and "nothing was sent" in out["blockers"][0]
    assert box.fake.created == [] and box.one("SELECT count(*) FROM ai.batch_items") == 0 and box.one("SELECT count(*) FROM ai.batches") == 0


def test_the_workers_poll_alone_takes_what_the_lab_sent(box: Lab) -> None:
    """Collecting never depends on who submitted: the handler of the purpose ``other`` is found by the poll of the worker."""
    lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    box.end()
    report = poll(box.conn, cfg(), at=AT + timedelta(hours=1), ledger=box.ledger, client=box.fake)
    assert report.counts == {"succeeded": 6}
    results = [r[0] for r in box.db.execute("SELECT context -> 'result' FROM ai.batch_items ORDER BY id").fetchall()]
    assert all(r == {"valid": True, "stop_reason": "tool_use"} or r == {"valid": True, "stop_reason": "end_turn"} for r in results)
    assert box.gate_rows("batch") == [], "the poll takes results; only the collection decides a gate"
    assert probe_state(box)["passed"] is True


def test_the_handler_of_what_the_lab_sends_is_found_whoever_asks() -> None:
    assert "fbi.ai.lab" in batch_mod._MODULES and handler_for("other") is lab.settle_lab


def test_an_item_that_is_neither_a_probe_nor_an_experiment_is_not_settled_silently(box: Lab) -> None:
    item = {"id": 1, "context": {"lab": "something-else"}, "input_hash": "h", "tier": "analysis", "model": SONNET}
    with pytest.raises(ValueError, match="not a probe or an experiment"):
        lab.settle_lab(box.conn, Resolved(item, None, None, None, Decimal(0), AT, False, 1))


# ── the inputs ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_inputs_are_the_models_stored_reviews_of_the_days_before_today(box: Lab) -> None:
    box.stored(4)
    box.stored(2, model=OPUS, start=10)  # another model's reviews are not this model's inputs
    box.stored(2, status="fallback", start=20)
    box.stored(2, engine="rules", start=30)
    box.stored(2, start=40, at0=AT + timedelta(hours=1))  # reviewed today: the day is not over
    box.stored(2, start=50, at0=FIRST_REVIEW - timedelta(days=40))  # too old
    until = AT.replace(hour=0)
    found = lab.select_inputs(box.conn, model=SONNET, since=until - timedelta(days=21), until=until, n=100)
    assert len(found) == 12, "four packets with three selections each"
    assert {i.candidate.selection for i in found} == {"Home", "Draw", "Away"}
    first = found[0]
    assert first.candidate.kickoff_at == KO and first.candidate.bookmaker == "Bet365" and first.candidate.market_key == "1X2"
    assert first.candidate.line == Decimal(0) and first.candidate.odds is not None and first.candidate.pick_id is None
    assert first.candidate.p_high is None and first.candidate.n_bookmakers is None, "what the table does not keep is absent: for every ask"
    assert first.ref == f"{first.packet_id}:{first.ref.split(':')[1]}" and first.at >= FIRST_REVIEW
    same = lab.select_inputs(box.conn, model=SONNET, since=until - timedelta(days=21), until=until, n=100)
    assert [i.ref for i in same] == [i.ref for i in found], "the same inputs, in the same order, every time"
    other = lab.select_inputs(box.conn, model=SONNET, since=until - timedelta(days=21), until=until, n=100, seed="another")
    assert {i.ref for i in other} == {i.ref for i in found} and [i.ref for i in other] != [i.ref for i in found]
    assert len(lab.select_inputs(box.conn, model=SONNET, since=until - timedelta(days=21), until=until, n=5)) == 5


def test_the_newest_review_of_the_same_input_is_the_one_replayed(box: Lab) -> None:
    box.stored(1)
    packet_id = box.one("SELECT max(id) FROM ai.match_packets")
    packet = load_packet(box.conn, packet_id)
    assert packet is not None
    cand = Candidate(fixture_id=box.seed.fixture_id, market_key="1X2", selection="Home", line=Decimal(0), p_model=Decimal("0.5200"),
                     kickoff_at=KO, odds=Decimal("2.400"), bookmaker_id=box.seed.bookmaker_id)
    later = EngineResult("llm", REVIEW_VERSION, "REJECT", reply("REJECT") | {"tier": "analysis"}, "ok", None, "anthropic",
                         SONNET, [], Decimal("0.03"), "h-newer")
    store_review(box.conn, later, cand, packet=packet, packet_id=packet_id, at=FIRST_REVIEW + timedelta(hours=1), mode="shadow")
    until = AT.replace(hour=0)
    found = lab.select_inputs(box.conn, model=SONNET, since=until - timedelta(days=21), until=until, n=100)
    assert len(found) == 3, "one input per (packet, candidate)"
    home = next(i for i in found if i.candidate.selection == "Home")
    assert home.at == FIRST_REVIEW + timedelta(hours=1), "the review replayed is the newest"


# ── the experiment is sent whole or not at all ──────────────────────────────────────────────────────────────────────

def test_fewer_stored_reviews_than_the_plan_asks_send_nothing(box: Lab) -> None:
    box.stored(4)
    out = lab.equivalence_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    assert out["submitted"] == 0 and out["inputs"] == 12
    assert out["blockers"] == [f"only 12 stored reviews of {SONNET} to replay; 200 are needed"]
    assert box.fake.created == [] and box.one("SELECT count(*) FROM ai.batch_items") == 0


def test_without_a_lab_key_the_experiment_says_what_is_missing_and_sends_nothing(box: Lab) -> None:
    box.stored(4)
    out = box.submit(cfg(lab_keys={}, lab_monthly_budget=Decimal(0)))
    assert out["submitted"] == 0 and len(out["blockers"]) == 2
    assert "FBI_AI_KEY_ANTHROPIC_LAB" in out["blockers"][0] and "owner actions 5 and 7" in out["blockers"][0]
    assert box.fake.created == []


def test_the_estimate_is_set_against_the_labs_envelope_before_anything_is_sent(box: Lab) -> None:
    box.stored(4)
    poor = box.submit(cfg(lab_monthly_budget=Decimal("0.01")))
    assert poor["submitted"] == 0 and "cannot pay for this experiment" in poor["blockers"][0]
    assert Decimal(poor["estimate_usd"]) > 0 and Decimal(poor["lab_remaining_usd"]) <= Decimal("0.01")
    assert box.fake.created == [] and box.one("SELECT count(*) FROM ai.batch_items") == 0
    dry = box.submit(dry_run=True)
    assert dry["dry_run"] is True and dry["submitted"] == 0 and dry["asks"] == 48 and dry["inputs"] == 12
    assert box.one("SELECT count(*) FROM ai.batch_items") == 0
    sent = box.submit()
    assert sent["submitted"] == 48 and sent["estimate_usd"] == dry["estimate_usd"]
    reserved = box.one("SELECT sum(est_cost_usd) FROM ai.batch_items")
    assert abs(reserved - Decimal(sent["estimate_usd"])) <= Decimal("0.01"), "what the queue reserves is what was estimated"


def test_the_inputs_of_a_day_are_fixed_for_the_whole_day(box: Lab) -> None:
    box.stored(4)
    morning = box.submit(at=AT.replace(hour=1), dry_run=True, n=100)
    box.stored(2, start=100, at0=AT.replace(hour=2))  # two more reviews arrive during the day...
    evening = box.submit(at=AT.replace(hour=23), dry_run=True, n=100)
    assert morning["experiment"] == evening["experiment"] and morning["inputs"] == evening["inputs"] == 12, "...and wait for tomorrow"
    tomorrow = box.submit(at=AT + timedelta(days=1), dry_run=True, n=100)
    assert tomorrow["experiment"] != morning["experiment"] and tomorrow["inputs"] == 12 + 6


def test_the_queue_refusing_any_ask_stops_the_whole_experiment(box: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    box.stored(4)
    real = BatchQueue._unaffordable
    n = {"calls": 0}

    def refuse_the_last(self: BatchQueue, task: Any, estimate: Decimal) -> str | None:
        n["calls"] += 1
        return "lab_budget" if n["calls"] == 48 else real(self, task, estimate)

    monkeypatch.setattr(BatchQueue, "_unaffordable", refuse_the_last)
    out = box.submit()
    assert out["submitted"] == 0 and out["refused"] == {"lab_budget": 1} and "nothing was sent" in out["blockers"][0]
    assert box.fake.created == [] and box.one("SELECT count(*) FROM ai.batch_items") == 0, "47 asks were recorded and are gone"


def test_the_four_asks_of_each_input_go_in_one_batch_exactly_as_they_are_measured(box: Lab) -> None:
    box.stored(4)
    out = box.submit()
    assert out["submitted"] == 48 and out["states"] == {"queued": 48} and len(box.fake.created) == 1 and len(box.fake.created[0]) == 48
    by_variant = box.items_by_variant()
    assert {k: len(v) for k, v in by_variant.items()} == {"A1": 12, "A2": 12, "B": 12, "C": 12}
    rows = box.db.execute("SELECT i.purpose, i.tier, i.model, i.fixture_id, i.prompt_version, b.kind, b.workspace, i.context ->> 'layout' "
                          "FROM ai.batch_items i JOIN ai.batches b ON b.id = i.batch_id").fetchall()
    assert {r[:7] for r in rows} == {("other", "analysis", SONNET, None, "equiv-v1", "lab", "PREDIGOL-LAB")}
    assert Counter(r[7] for r in rows) == {None: 36, "shared": 12}, "the item notes the layout only when the common block is first"
    bodies = box.bodies()
    both: dict[str, list[dict[str, Any]]] = {}
    for inp, cid in box.db.execute("SELECT context ->> 'input', custom_id FROM ai.batch_items WHERE context ->> 'variant' IN ('A1', 'A2') "
                                   "ORDER BY id").fetchall():
        both.setdefault(str(inp), []).append(bodies[str(cid)])
    assert len(both) == 12 and all(len(v) == 2 and v[0] == v[1] for v in both.values()), "the two identical calls are identical in every byte"
    a1, b, c = bodies[by_variant["A1"][0]], bodies[by_variant["B"][0]], bodies[by_variant["C"][0]]
    assert all(x["model"] == SONNET and x["max_tokens"] == 8000 for x in (a1, b, c))
    assert a1["tools"][0]["name"] == "submit_review" and a1["tool_choice"] == {"type": "auto"} and "format" not in a1["output_config"]
    assert a1["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert isinstance(a1["messages"][0]["content"], str), "the usual layout: one user message"
    assert "tools" not in b and b["output_config"]["format"]["type"] == "json_schema" and isinstance(b["messages"][0]["content"], str)
    assert b["messages"][0]["content"] == a1["messages"][0]["content"] or json.loads(b["messages"][0]["content"]).keys() == json.loads(
        a1["messages"][0]["content"]).keys(), "structured outputs change the route, not the question"
    first, last = c["messages"][0]["content"]
    assert first["cache_control"] == {"type": "ephemeral"} and "cache_control" not in last and "tools" in c
    assert json.loads(first["text"]).keys() == {"packet", "missing"} and {"now", "candidate", "packet_live"} <= json.loads(last["text"]).keys()


def test_production_switches_neither_add_nor_take_away_what_the_experiment_measures(box: Lab) -> None:
    box.stored(4)
    gates.record_gate(box.conn, gate="native_schema", passed=True, at=AT, evidence={"models": [SONNET]})
    gates.record_gate(box.conn, gate="cache_layout", passed=True, at=AT, evidence={"models": [SONNET]})
    loud = cfg(switches={"native_schema": "on", "cache": "on", "batch": "on"})
    assert gates.enabled(box.conn, loud, "native_schema", model=SONNET) and gates.layout_shared(box.conn, loud, model=SONNET)
    box.submit(loud)
    by_variant = box.items_by_variant()
    bodies = box.bodies()
    for cid in by_variant["A1"] + by_variant["A2"]:
        body = bodies[cid]
        assert "tools" in body and isinstance(body["messages"][0]["content"], str), "A is what production asked before the gates"
    for cid in by_variant["B"]:
        assert "tools" not in bodies[cid] and isinstance(bodies[cid]["messages"][0]["content"], str), "B is the usual layout, natively"
    for cid in by_variant["C"]:
        assert "tools" in bodies[cid] and len(bodies[cid]["messages"][0]["content"]) == 2


def test_asking_again_pays_nothing_twice(box: Lab) -> None:
    box.stored(4)
    box.submit()
    again = box.submit(at=AT + timedelta(hours=3))
    assert again["states"] == {"in_flight": 48} and len(box.fake.created) == 1 and box.one("SELECT count(*) FROM ai.batch_items") == 48
    box.end()
    assert box.collect()["state"] == "ended"
    paid = box.one("SELECT count(*) FROM ai.usage")
    last = box.submit(at=AT + timedelta(hours=5))
    assert last["states"] == {"done": 48} and len(box.fake.created) == 1
    assert box.one("SELECT count(*) FROM ai.usage") == paid == 48 and box.one("SELECT count(*) FROM ai.batch_items") == 48
    assert box.db.execute("SELECT scope, count(*) FROM ai.usage_scoped GROUP BY 1").fetchall() == [("lab", 48)]
    assert box.one("SELECT count(*) FROM ai.usage WHERE fixture_id IS NOT NULL") == 0, "the LAB's spend is not any match's cost"


# ── the collection and the gates ────────────────────────────────────────────────────────────────────────────────────

def test_nothing_is_decided_while_results_are_on_their_way(box: Lab) -> None:
    box.stored(4)
    box.submit()
    out = box.collect()
    assert out["state"] == "waiting" and out["open"] == 48 and out["asks"] == 48
    assert box.gate_rows("native_schema") == [] and box.gate_rows("cache_layout") == []
    assert lab.equivalence_collect(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake, experiment="never-sent")["state"] == "nothing_submitted"


def test_collecting_without_an_experiment_says_so(box: Lab) -> None:
    assert lab.equivalence_collect(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake) == {"state": "nothing_submitted"}


def test_an_equivalent_variant_opens_its_gate_only_with_what_the_probes_saw(box: Lab) -> None:
    box.stored(4)
    box.panel.repeat, box.panel.native, box.panel.shared = {0, 5, 9}, {2, 7}, {1, 6, 10}  # the model repeats itself less than 100 %
    sent = box.submit()
    box.end()
    experiment = sent["experiment"]
    before = box.collect()
    assert before["state"] == "ended" and before["asks"] == 48 and Decimal(before["cost_usd"]) > 0
    for variant in lab.VARIANTS:
        v = before["variants"][variant]
        assert v["complete_inputs"] == 12 and v["changed_repeat"] == 3 and v["invalid_variant"] == 0.0
    native, layout = before["variants"]["native_schema"], before["variants"]["shared_layout"]
    assert native["changed_variant"] == 2 and native["passed"] is False and native["native_in_batch"] is False
    assert native["verdict"] == "NO PASA" and any("inside a batch" in r for r in native["reasons"]), "the statistics alone would pass it"
    assert layout["changed_variant"] == 3 and layout["passed"] is False and layout["cache_seen_reading"] is False
    assert layout["verdict"] == "NO PASA"
    assert any("run ia_probe cache" in r for r in layout["reasons"])
    assert [p for p, _ in box.gate_rows("native_schema")] == [False] and [p for p, _ in box.gate_rows("cache_layout")] == [False]
    assert not gates.enabled(box.conn, cfg(switches={"batch": "auto"}), "native_schema", model=SONNET)
    box.see_the_probes()
    after = box.collect(at=AT + timedelta(hours=3))
    assert after["variants"]["native_schema"]["passed"] is True and after["variants"]["shared_layout"]["passed"] is True
    assert after["variants"]["native_schema"]["reasons"] == [] and after["variants"]["native_schema"]["verdict"] == "PASA"
    assert [p for p, _ in box.gate_rows("native_schema")] == [False, True] and [p for p, _ in box.gate_rows("cache_layout")] == [False, True]
    passed = box.gate_rows("native_schema")[-1][1]
    assert passed["models"] == [SONNET] and passed["experiment"] == experiment and passed["rule"].startswith("change(variant) <= change(repeat)")
    assert passed["assessment"]["changed_variant"] == 2 and passed["assessment"]["changed_repeat"] == 3
    assert set(passed["inputs"].values()) <= {"AAA", "ADA", "AAD"} and sorted(passed["inputs"].values()).count("AAD") == 2
    assert len(passed["inputs"]) == 12, "every input's verdicts are in the row: anyone can recompute the decision"
    rebuilt = {ref: dict(zip(("A1", "A2", "B"), s, strict=True)) for ref, s in passed["inputs"].items()}
    assert lab.assess(rebuilt, "native_schema", min_inputs=10)["changed_variant"] == 2
    settings = cfg(switches={"cache": "auto"})
    assert gates.enabled(box.conn, settings, "native_schema", model=SONNET) and gates.layout_shared(box.conn, settings, model=SONNET)
    assert not gates.enabled(box.conn, settings, "native_schema", model=OPUS), "the evidence is for the model it was measured with"
    again = box.collect(at=AT + timedelta(hours=4))
    assert again["variants"]["native_schema"]["gate_id"] is None and len(box.gate_rows("native_schema")) == 2, "the same evidence is one row"


def test_a_variant_that_changes_more_verdicts_than_a_repeat_closes_what_a_passing_run_opened(box: Lab) -> None:
    box.stored(4)
    box.see_the_probes()
    box.panel.repeat = {0, 5}
    box.submit()
    box.end()
    assert box.collect()["variants"]["native_schema"]["passed"] is True
    assert gates.enabled(box.conn, cfg(), "native_schema", model=SONNET)
    box.panel.renew()
    box.panel.repeat, box.panel.native = {0, 5}, {1, 2, 3}  # a later run: structured outputs now moves three verdicts, a repeat two
    second = box.submit(at=AT + timedelta(days=1), seed="equiv-v1-b")
    assert second["experiment"].endswith("equiv-v1-b:2026-09-15") and second["submitted"] == 48
    box.end()
    out = box.collect(at=AT + timedelta(days=1, hours=2), experiment=second["experiment"])
    native = out["variants"]["native_schema"]
    assert native["passed"] is False and native["verdict"] == "NO PASA" and native["changed_variant"] == 3 > native["changed_repeat"]
    assert any("changes more verdicts (3) than repeating the same call (2)" in r for r in native["reasons"])
    assert [p for p, _ in box.gate_rows("native_schema")] == [True, False]
    assert not gates.enabled(box.conn, cfg(), "native_schema", model=SONNET), "the newest evidence decides: a failing re-run switches it off"


def test_invalid_and_lost_asks_count_against_the_variant_and_unsent_ones_are_not_asks(box: Lab) -> None:
    box.stored(4)
    box.see_the_probes()
    box.submit()
    by_variant = box.items_by_variant()
    box.fake.end(outcomes={by_variant["B"][0]: "errored", by_variant["B"][1]: "cut", by_variant["A2"][2]: "expired"})
    unsent = by_variant["C"][3]
    box.db.execute("UPDATE ai.batch_items SET status = 'abandoned' WHERE custom_id = %s AND status = 'submitted'", (unsent,))
    out = box.collect()
    native = out["variants"]["native_schema"]
    assert native["complete_inputs"] == 9, "two inputs lack a valid B and one lacks a valid second identical call"
    assert native["invalid_variant"] == pytest.approx(2 / 12, abs=1e-4) and native["invalid_baseline"] == pytest.approx(1 / 24, abs=1e-4)
    assert native["passed"] is False and any("invalid more often than allowed" in r for r in native["reasons"])
    layout = out["variants"]["shared_layout"]
    assert layout["invalid_variant"] == 0.0, "the ask that was never sent is not an invalid answer"
    assert layout["complete_inputs"] == 10 and out["asks"] == 47, "one lacks its second identical call, one its unsent ask"


def test_the_item_keeps_the_verdict_the_checked_review_would_have_had(box: Lab) -> None:
    box.stored(4)
    box.panel.native = {0}
    box.submit()
    box.end()
    poll(box.conn, cfg(), at=AT + timedelta(hours=1), ledger=box.ledger, client=box.fake)
    rows = box.db.execute("SELECT context ->> 'variant', context -> 'result' FROM ai.batch_items ORDER BY id").fetchall()
    assert len(rows) == 48 and all(set(r) == {"decision", "status", "rejected_claims", "stop_reason"} for _v, r in rows)
    assert Counter(r["decision"] for _v, r in rows) == {"APPROVE": 47, "DOWNGRADE": 1}
    assert {r["status"] for _v, r in rows} == {"ok"} and {r["rejected_claims"] for _v, r in rows} == {0}
    assert [v for v, r in rows if r["decision"] == "DOWNGRADE"] == ["B"], "only the ask the test scripted to differ"


def test_nothing_the_lab_does_touches_a_review_a_pick_a_packet_or_any_state_of_production(box: Lab) -> None:
    box.stored(4)

    def counts() -> dict[str, int]:
        tables = box.db.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
                                "AND table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2").fetchall()
        return {f"{s}.{t}": int(box.db.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0]) for s, t in tables}  # type: ignore[index]

    before = counts()
    box.submit()
    box.end()
    box.see_the_probes()
    box.collect()
    lab.probe_batch_submit(box.conn, cfg(), at=AT, ledger=box.ledger, client=box.fake)
    box.end()
    probe_state(box)
    after = counts()
    changed = {t for t in after if after[t] != before[t]}
    assert changed <= {"ai.batches", "ai.batch_items", "ai.usage", "ai.feature_gates"}, changed
    assert "ai.pick_reviews" not in changed and "ai.match_packets" not in changed


def test_the_experiment_at_the_size_the_plan_asks(box: Lab) -> None:
    """200 stored packets or more (here 70 of them, three selections each): the plan's bar, without lowering it."""
    box.stored(70)
    box.see_the_probes()
    box.panel.repeat = set(range(0, 210, 21))  # 10 inputs where the model does not repeat itself
    box.panel.native = set(range(1, 210, 30))  # 7
    box.panel.shared = set(range(2, 210, 21))  # 10
    out = lab.equivalence_submit(box.conn, cfg(lab_monthly_budget=Decimal(15)), at=AT, ledger=box.ledger, client=box.fake)
    assert out["inputs"] == 210 and out["asks"] == 840 and out["submitted"] == 840, out
    assert len(box.fake.created) == 1 and len(box.fake.created[0]) == 840
    box.end()
    done = lab.equivalence_collect(box.conn, cfg(), at=AT + timedelta(hours=2), ledger=box.ledger, client=box.fake)
    for variant in lab.VARIANTS:
        v = done["variants"][variant]
        assert v["complete_inputs"] == 210 and v["verdict"] == "PASA" and v["passed"] is True, v
    assert done["variants"]["native_schema"]["changed_variant"] == 7 and done["variants"]["native_schema"]["changed_repeat"] == 10
    assert len(box.gate_rows("native_schema")[-1][1]["inputs"]) == 210
    assert gates.enabled(box.conn, cfg(), "native_schema", model=SONNET) and gates.layout_shared(box.conn, cfg(), model=SONNET)
    assert Decimal(done["cost_usd"]) < Decimal(15), "inside the LAB's envelope"

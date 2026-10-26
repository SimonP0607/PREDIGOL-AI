"""The review's prompt in the layout of the prompt cache (Plan Maestro IA, section 28, cut point 2), on a stored match.

The common block of the match goes first and is marked for five minutes; the hour, the prices and the news go last and are never cached.
It is a different arrangement of the same facts, so it waits for its own gate (``cache_layout``: the evidence that the model decides the
same with it) and for the model that gate was measured on; the owner can take it back with ``FBI_AI_CACHE=0``. Closed, the review is asked
exactly as it always was. Open, the second candidate of a match reads from the cache what the first wrote - in real time and in a Message
Batch - and the answer is stored under the same input hash, so a review paid in one layout is never paid again in the other.

No network and no key: the provider is ``FakeProvider`` (and ``FakeBatches``), which reports the cache the way the API does.
One transaction, rolled back."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import gates
from fbi.ai.batch import BatchQueue, poll
from fbi.ai.config import AiSettings, Tier, TierModel
from fbi.ai.packet import Packet, store_packet
from fbi.ai.pricing import approx_tokens
from fbi.ai.providers.base import JsonRequest, LlmUsage
from fbi.ai.providers.fake import FakeBatches, FakeProvider
from fbi.ai.review import (
    Candidate,
    Deferral,
    Reviewed,
    prompt_content,
    prompt_parts,
    review_candidate,
    signals_for,
)
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed
from .test_ai_decision_layer import Savepoints, review_reply
from .test_brief_material import content, fixture_block

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=8)
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET),
         "final": TierModel("anthropic", OPUS)}
DOSSIER = {"sections": [f"Section {n}: how the side arrives, what it plays for, who is out and what the table says." * 3
                        for n in range(80)]}
"""Most of a real packet is the dossier: the common block is thousands of tokens, well over the 512 the cache needs."""


def settings(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": dict(TIERS), "keys": {"anthropic": "sk-test-not-a-key"},
                            "switches": {"batch": "on"}}
    return AiSettings(**(base | over))


def candidate(seed: Seed, selection: str = "Home", **over: Any) -> Candidate:
    base: dict[str, Any] = {
        "fixture_id": seed.fixture_id, "market_key": "1X2", "selection": selection, "line": Decimal(0),
        "p_model": Decimal("0.5200"), "kickoff_at": KO, "odds": Decimal("2.400"), "bookmaker": "BK",
        "p_low": Decimal("0.4700"), "p_high": Decimal("0.5700"), "p_market": Decimal("0.4500"), "ev": Decimal("0.2480"),
        "model": "dixon_coles", "n_bookmakers": 8, "price_at": AT - timedelta(minutes=5)}
    return Candidate(**(base | over))


def draw(seed: Seed, **over: Any) -> Candidate:
    base: dict[str, Any] = {"p_model": Decimal("0.2500"), "odds": Decimal("3.500"), "p_market": Decimal("0.2800"),
                            "p_low": Decimal("0.2100"), "p_high": Decimal("0.2900"), "ev": Decimal("-0.1250")}
    return candidate(seed, "Draw", **(base | over))


def pass_the_gate(db: psycopg.Connection[Any], *models: str) -> None:
    gates.record_gate(db, gate="cache_layout", passed=True, at=AT, evidence={"packets": 200, "models": list(models)})


class Cache:
    """What a prompt cache does, in the numbers the API reports: the first call that sends a common block writes it for five minutes,
    the ones after it read it. Calls without that block are billed as fresh input."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def __call__(self, request: JsonRequest, counted: LlmUsage) -> LlmUsage:
        if not (request.cache and request.shared):
            return counted
        n = approx_tokens(request.shared)
        if request.shared in self.seen:
            return LlmUsage(input_tokens=counted.input_tokens, output_tokens=counted.output_tokens, cached_tokens=n)
        self.seen.add(request.shared)
        return LlmUsage(input_tokens=counted.input_tokens, output_tokens=counted.output_tokens, cache_write_5m_tokens=n)


def model_of(decision: str = "APPROVE") -> FakeProvider:
    return FakeProvider(lambda r: review_reply(decision), name="anthropic", usage=Cache())


@dataclass
class World:
    db: psycopg.Connection[Any]
    conn: Any
    seed: Seed
    ledger: UsageLedger
    packet: Packet
    packet_id: int

    def review(self, cand: Candidate | None = None, *, provider: FakeProvider | None = None, cfg: AiSettings | None = None,
               at: datetime = AT, tier: Tier = "analysis", deferral: Deferral | None = None) -> Reviewed:
        model = provider or model_of()
        return review_candidate(self.conn, cfg or settings(), cand or candidate(self.seed), self.packet, self.packet_id, at=at,
                                use_llm=True, tier=tier, ledger=self.ledger,
                                provider=(model, TIERS[tier].model), deferral=deferral)

    def expected(self, cand: Candidate, *, at: datetime = AT) -> tuple[str, tuple[str, str]]:
        sig = signals_for(cand, self.packet, at=at)
        return prompt_content(cand, self.packet, sig, at=at), prompt_parts(cand, self.packet, sig, at=at)

    def usage(self) -> list[tuple[int, int, int, Decimal]]:
        """Per call, oldest first: input, cache read, cache written, cost."""
        rows = self.db.execute("SELECT input_tokens, cached_tokens, cache_write_tokens, cost_usd FROM ai.usage "
                               "WHERE purpose = 'pick_review' ORDER BY id").fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), Decimal(r[3])) for r in rows]

    def model_outputs(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT output FROM ai.pick_reviews WHERE engine = 'llm' ORDER BY id").fetchall()
        return [dict(r[0]) for r in rows]


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    conn: Any = Savepoints(db)
    packet = Packet(seed.fixture_id, AT, content(seed) | {"fixture": fixture_block(seed, kickoff_at=KO.isoformat()),
                                                           "dossier": DOSSIER},
                    sources=[{"block": "market", "as_of": (AT - timedelta(minutes=5)).isoformat()}])
    return World(db, conn, seed, UsageLedger(shared(db)), packet, store_packet(conn, packet, built_at=AT))


# ── closed: the review is asked as it always was ────────────────────────────────────────────────────────────────

def test_without_the_gate_the_review_is_asked_exactly_as_it_always_was(world: World) -> None:
    model = model_of()
    world.review(provider=model)
    request = model.requests[0]
    usual, offer = world.expected(candidate(world.seed))
    assert request.shared == "" and request.user == usual, "not a byte of the prompt has changed"
    assert request.split == offer, "the offer travels with the request, and nobody took it"
    assert request.cache is True, "the system block is cached as before: that gate is another"
    assert "layout" not in world.model_outputs()[0], "and the stored answer is the one it always was"


def test_the_gate_measured_on_another_model_does_not_cover_this_one(world: World) -> None:
    pass_the_gate(world.db, HAIKU)
    model = model_of()
    world.review(provider=model)
    assert model.requests[0].shared == "", "the layout was measured on Haiku; the review runs on Sonnet"


def test_the_owner_takes_the_layout_back_with_the_cache_switch(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    model = model_of()
    world.review(provider=model, cfg=settings(switches={"batch": "on", "cache": "off"}))
    assert model.requests[0].shared == "" and model.requests[0].cache is False


# ── open: the common block first, marked for the cache ─────────────────────────────────────────────────────────────

def test_with_the_gate_the_common_block_goes_first_and_is_marked_for_the_cache(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    model = model_of()
    world.review(provider=model)
    request = model.requests[0]
    _usual, (common, tail) = world.expected(candidate(world.seed))
    assert (request.shared, request.user, request.cache) == (common, tail, True)
    assert json.loads(request.shared)["packet"]["dossier"] == DOSSIER and "market" not in json.loads(request.shared)["packet"]
    assert "market" in json.loads(request.user)["packet_live"]
    assert world.model_outputs()[0]["layout"] == "shared", "the stored answer says which layout it was asked in"


def test_the_second_candidate_of_the_match_reads_the_block_the_first_one_wrote(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    model = model_of()
    world.review(provider=model)
    world.review(draw(world.seed), provider=model)
    assert model.requests[0].shared == model.requests[1].shared, "the same bytes: that is what the cache matches"
    (in1, read1, wrote1, cost1), (_in2, read2, wrote2, cost2) = world.usage()
    assert (read1, wrote1 > 0) == (0, True) and (read2 > 0, wrote2) == (True, 0)
    assert read2 == wrote1 and 2 * read2 > in1 and cost2 < cost1, "most of the call is the block, and it is read, not paid"


def test_two_candidates_cost_less_together_than_in_the_usual_layout(world: World) -> None:
    usual = model_of()
    world.review(provider=usual)
    world.review(draw(world.seed), provider=usual)
    closed = sum(c for *_x, c in world.usage())
    pass_the_gate(world.db, SONNET)
    layout = model_of()
    # the same two selections at other prices: other inputs, so the reviews are asked again - this time in the other layout
    world.review(candidate(world.seed, odds=Decimal("2.500"), ev=Decimal("0.3000")), provider=layout)
    world.review(draw(world.seed, odds=Decimal("3.600"), ev=Decimal("-0.1000")), provider=layout)
    opened = sum(c for *_x, c in world.usage()[2:])
    assert len(layout.requests) == 2 and layout.requests[0].shared
    assert 0 < opened < closed, f"{opened} should be below {closed}: one write at 1.25 and one read at 0.05 against two fresh inputs"


def test_a_clock_that_moves_and_a_price_that_moves_do_not_break_the_cache(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    model = model_of()
    world.review(provider=model)
    later = AT + timedelta(minutes=4)  # the next cycle: the time has moved and the model asks again for the same match
    moved = candidate(world.seed, odds=Decimal("2.550"), ev=Decimal("0.3260"))
    world.review(moved, provider=model, at=later)
    assert model.requests[0].shared == model.requests[1].shared
    assert model.requests[0].user != model.requests[1].user
    assert world.usage()[1][1] > 0, "and the second call read it"


# ── the hash does not know the layout ──────────────────────────────────────────────────────────────────────────────

def test_a_review_paid_in_one_layout_is_not_paid_again_in_the_other(world: World) -> None:
    model = model_of()
    world.review(provider=model)
    pass_the_gate(world.db, SONNET)
    again = world.review(provider=model)
    assert len(model.requests) == 1, "the same facts: the review already made is the answer"
    assert again.llm is not None and again.llm.output.get("reused_from")
    assert "layout" not in world.model_outputs()[0]


def test_and_the_other_way_round(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    model = model_of()
    world.review(provider=model)
    closed = settings(switches={"batch": "on", "cache": "off"})
    again = world.review(provider=model, cfg=closed)
    assert len(model.requests) == 1 and again.llm is not None and again.llm.output.get("reused_from")


# ── in a Message Batch ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_batch_carries_the_same_layout_and_the_answer_says_so(world: World) -> None:
    pass_the_gate(world.db, SONNET)
    fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic", usage=Cache())
    queue = BatchQueue(world.conn, settings(), at=AT, ledger=world.ledger, client=fake)
    for cand in (candidate(world.seed), draw(world.seed)):
        reviewed = world.review(cand, deferral=Deferral(queue, world.packet_id, "shadow", "first"))
        assert reviewed.pending is not None
    assert queue.flush().sent == 2
    bodies = [i["params"] for i in fake.created[0]]
    blocks = [b["messages"][0]["content"] for b in bodies]
    assert all(isinstance(x, list) and len(x) == 2 for x in blocks), "two text blocks: the common one, then the tail"
    assert all("cache_control" in x[0] and "cache_control" not in x[1] for x in blocks), "only the common block is marked"
    assert blocks[0][0]["text"] == blocks[1][0]["text"] and blocks[0][1]["text"] != blocks[1][1]["text"]
    layouts = world.db.execute("SELECT context ->> 'layout' FROM ai.batch_items ORDER BY id").fetchall()
    assert [r[0] for r in layouts] == ["shared", "shared"]
    fake.end()
    poll(world.conn, settings(), at=AT + timedelta(minutes=30), ledger=world.ledger, client=fake)
    outs = world.model_outputs()
    assert [o.get("layout") for o in outs] == ["shared", "shared"] and all(o.get("via") == "batch" for o in outs)


def test_a_batch_asked_with_the_gate_closed_is_asked_as_it_always_was(world: World) -> None:
    fake = FakeBatches(lambda r: review_reply("APPROVE"), name="anthropic")
    queue = BatchQueue(world.conn, settings(), at=AT, ledger=world.ledger, client=fake)
    world.review(deferral=Deferral(queue, world.packet_id, "shadow", "first"))
    queue.flush()
    content_ = fake.created[0][0]["params"]["messages"][0]["content"]
    assert content_ == world.expected(candidate(world.seed))[0], "one string, as before"
    assert world.db.execute("SELECT context ? 'layout' FROM ai.batch_items").fetchone() == (False,)

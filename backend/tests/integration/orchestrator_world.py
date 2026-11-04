"""What the integration tests of the orchestrator share: a match with a packet, a pass that stored it, the reviews of production on it, a scripted
provider that answers the way the contracts want, and the settings that switch the shadow on."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.ai import arms, orchestrator, runtime
from fbi.ai.agents import council, match
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared
from tests.integration.conftest import Seed
from tests.integration.test_match_runs import PASSED, RUN, passed
from tests.integration.test_slice_leak_audit import AT, Scene, scene

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {
    "bulk": TierModel("anthropic", HAIKU),
    "analysis": TierModel("anthropic", SONNET),
    "final": TierModel("anthropic", OPUS),
}
D = Decimal
SELECTIONS = (("1X2", "Home", "0", "0.55", "2.10"), ("1X2", "Draw", "0", "0.27", "3.60"), ("OU", "Over", "2.5", "0.58", "1.95"))


def settings(**over: Any) -> AiSettings:
    """The shadow switched on at full sample, with a LAB envelope and keys that are not keys."""
    base: dict[str, Any] = {
        "mode": "shadow",
        "tiers": dict(TIERS),
        "keys": {"anthropic": "sk-test-not-a-key"},
        "lab_keys": {"anthropic": "sk-lab-not-a-key"},
        "lab_monthly_budget": D("200"),
        "joint_ceiling": D("500"),
        "engines": ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1"),
        "shadow_sample": D(1),
        "agents": ("match", "council"),
        "switches": {"budget_v3": "on"},
    }
    return AiSettings(**(base | over))


@dataclass
class World:
    db: psycopg.Connection[Any]
    scene: Scene
    fixture: int
    packet: int
    reviews: list[int] = field(default_factory=list)


def rules_review(db: psycopg.Connection[Any], fixture: int, packet: int | None, spec: tuple[str, str, str, str, str], *, at: datetime = PASSED) -> int:
    market, selection, line, p, odds = spec
    row = db.execute(
        "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, p_model, p_low, p_market, ev, engine, engine_version, "
        "packet_id, input_hash, decision, confidence, context_score, model_score, market_score, fair_odds, minimum_playable_odds, output, mode, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'rules', 'rules-review-v1', %s, 'h', 'APPROVE', 0.6, 0.6, 0.7, 0.5, %s, %s, %s, 'shadow', 'ok') "
        "RETURNING id",
        (at, fixture, market, selection, line, D(odds), D(p), D(p) - D("0.04"), D(p) - D("0.05"), D("0.05"), packet, D("1.95"), D("1.90"), Jsonb({})),
    ).fetchone()
    assert row is not None
    return int(row[0])


def world(db: psycopg.Connection[Any], seed: Seed, *, pass_kind: str = "pre", n: int = 3, with_pass: bool = True) -> World:
    """A match with the packet of ``AT`` and a pass that stored it, reviewed by production on ``n`` selections."""
    s = scene(db, seed)
    if with_pass:
        passed(db, s.w.fixture, pass_kind, s.packet)
    w = World(db, s, s.w.fixture, s.packet)
    for spec in SELECTIONS[:n]:
        w.reviews.append(rules_review(db, s.w.fixture, s.packet, spec))
    return w


def assign(db: psycopg.Connection[Any], fixture: int, *, sampled: bool = True, solo: bool = True) -> None:
    """The assignment of the match, written by hand so that a test chooses its arms (the first row of a match is its group for good). A match
    outside the sample is one of a share of one half whose bucket is above it."""
    bucket, share = (1, 1) if sampled else (9_000, "0.5")
    db.execute(
        "INSERT INTO ai.shadow_assignments (experiment, fixture_id, bucket, sampled, council_solo, share, assigned_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (arms.SALT, fixture, bucket, sampled, sampled and solo, share, AT),
    )


# -- the scripted provider -----------------------------------------------------------------------------------------------------------------


def answer_for(request: JsonRequest, *, verdict: str = "APPROVE", confidence: str = "MEDIUM", stance: str = "NEUTRAL", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """A valid answer to any of the requests of the orchestrator: the Match Agent's two modes and the Council at any level."""
    if request.schema_name == council.TOOL:
        message = json.loads(request.user)
        refs = ["A:match_evaluation"] if message["view"].get("assessments") else ["P:shared.absences.home"]
        keys = message["ask"]["candidates"]
        data: dict[str, Any] = {
            "contract": "cd-v1",
            "research": [],
            "verdicts": [{"candidate": k, "verdict": verdict, "confidence": confidence, "drivers": ["FORM"], "risks": [], "refs": refs} for k in keys],
        }
        return data | (extra or {})
    _, second = request.user.split("\n")
    asked = json.loads(second).get("candidates")
    if request.system == match.SYSTEM["CONTEXT"]:
        return {
            "contract": "aa-v1", "agent": "match", "mode": "CONTEXT", "data_quality": "FAIR",
            "signals": [{"code": "ABSENCES", "direction": "AWAY", "strength": "HIGH", "refs": ["P:shared.absences.home"]}],
            "candidates": [], "research": [],
        } | (extra or {})
    return {
        "contract": "aa-v1", "agent": "match", "mode": "EVALUATION", "data_quality": "GOOD",
        "signals": [{"code": "ABSENCES", "direction": "AWAY", "strength": "HIGH", "refs": ["P:shared.absences.home"]}],
        "candidates": [{"candidate": c["candidate"] if isinstance(c, dict) else c, "stance": stance, "drivers": [], "risks": [], "refs": []} for c in asked],
        "research": [],
    } | (extra or {})


def provider(script: Callable[[JsonRequest], dict[str, Any]] | None = None, **kw: Any) -> FakeProvider:
    return FakeProvider(script or answer_for, name="anthropic", **kw)


@dataclass
class Gear:
    """What a run needs besides the connection: its own slots and circuit (nothing shared with another test), the ledger on the test's connection."""

    db: psycopg.Connection[Any]
    slots: runtime.Slots = field(default_factory=runtime.Slots)
    circuit: runtime.Circuit = field(default_factory=runtime.Circuit)

    @property
    def ledger(self) -> UsageLedger:
        return UsageLedger(shared(self.db))


def counts(db: psycopg.Connection[Any]) -> dict[str, int]:
    tables = ("ai.agent_tasks", "ai.agent_runs", "ai.match_runs", "ai.pick_reviews", "ai.usage", "ai.evidence", "ai.fixture_passes", "ai.shadow_assignments")
    return {t: int(db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables}  # type: ignore[index]


__all__ = ["AT", "HAIKU", "OPUS", "PASSED", "RUN", "SONNET", "Gear", "World", "answer_for", "assign", "counts", "orchestrator", "provider", "rules_review", "settings", "world"]

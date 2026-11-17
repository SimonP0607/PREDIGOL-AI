"""The quarantined extractor on a built world (IA-060, ``FBI_AI_EXTRACTOR``): what each word of the switch writes in the database.

The world of ``test_ai_research_entities`` (Alfa FC - Beta FC, a squad for each club) and three pages: Alfa's striker out, Beta's winger in doubt,
and a fan blog that gives an order. No network, no key: the search is a function and both extractors are one scripted provider that answers
each by the form it is asked in. One transaction, rolled back.

* ``v1`` (the default): extract-v1 alone, exactly as before - the quarantined extractor is not asked.
* ``shadow``: extract-v1 decides what the packet knows, as before; the quarantined extractor reads the same pages one per call, paid by the LAB
  and with its own agent in the ledger, and writes NOTHING in ``ai.evidence``.
* ``quarantine``: extract-v1 is not asked; what stands of the quarantined extractor's answers is stored in the very shape of v1's items
  (no ``subject_type``), and the page that gives an order is never sent.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import collectors, quarantine
from fbi.ai.config import AiSettings
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed
from .test_ai_research_entities import (
    ALFA_OUT,
    AT,
    BETA_DOUBT,
    BLOG,
    MODEL,
    STRIKER,
    WINGER,
    Web,
    World,
    build,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return build(db, kickoff_a=AT + timedelta(hours=20))


def both(asked: list[str]) -> FakeProvider:
    """extract-v1 (``submit_items``: one item from the first page) and the quarantined extractor (``submit_claims_v2``: per listed player
    named in the page, the sentence that names him, with the call's code word) - and, on any page, an obedient claim the blog asked for."""

    def script(r: JsonRequest) -> dict[str, Any]:
        asked.append(r.schema_name)
        if r.schema_name == "submit_items":
            return {"items": [{"result_id": "R1", "side": "home", "player": "Delantero Uno", "kind": "injury", "assertion": "out",
                               "claim": "Delantero Uno no jugará por lesión.", "published_at": None}]}
        doc = json.loads(r.user)
        text = doc["page"]["text"]
        claims = []
        for s in doc["subjects"]:
            if s["kind"] == "PLAYER" and s["name"] in text:
                sentence = next(x.strip() for x in text.split(".") if s["name"] in x)
                kind = "OUT" if "no jugará" in sentence else "DOUBT" if "duda" in sentence else "AVAILABLE"
                claims.append({"subject": s["ref"], "claim_type": kind, "applies_to": "THIS_MATCH", "quote": sentence})
        return {"contract": "claim-v2", "call": doc["call"], "claims": claims}

    return FakeProvider(script, name="anthropic")


def collect(w: World, mode: str, asked: list[str]) -> collectors.Collected:
    settings = AiSettings(mode="shadow", extractor=mode, lab_monthly_budget=Decimal(10))  # type: ignore[arg-type]
    return collectors.collect_web(w.db, settings, w.a, at=AT, ledger=UsageLedger(shared(w.db)), search=Web([ALFA_OUT, BETA_DOUBT, BLOG]),
                                  provider=(both(asked), MODEL), levels=1)


def rows(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with db.cursor() as cur:
        cur.execute("SELECT provider_player_id, kind, attributes->>'assertion' AS assertion, claim, subject_type, attributes->>'extract_version' AS version, source_url "
                    "FROM ai.evidence WHERE origin = 'web' ORDER BY id")
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def usage(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT agent, prompt_version, workspace, status FROM ai.usage WHERE purpose = 'evidence_extraction' ORDER BY id").fetchall()


def test_v1_is_the_default_and_the_quarantined_extractor_is_not_asked(world: World) -> None:
    asked: list[str] = []
    got = collect(world, "v1", asked)
    assert asked == ["submit_items"] and got.quarantine == {}
    assert [(r[0], r[1]) for r in usage(world.db)] == [(None, "extract-v1")]
    assert {r["version"] for r in rows(world.db)} == {"extract-v1"}


def test_in_shadow_v1_decides_and_the_quarantined_extractor_stores_nothing(world: World) -> None:
    asked: list[str] = []
    got = collect(world, "shadow", asked)
    assert asked.count("submit_items") == 1 and asked.count("submit_claims_v2") == 2, "one call a page; the blog that gives an order is not sent"
    assert got.quarantine["xq_pages"] == 3 and got.quarantine["xq_tainted"] == 1 and got.quarantine["xq_calls"] == 2
    assert got.quarantine["xq_kept"] == 2 and "xq_stored" not in got.quarantine
    assert {r["version"] for r in rows(world.db)} == {"extract-v1"}, "nothing of the shadow in ai.evidence"
    paid = usage(world.db)
    assert [p for p in paid if p[0] == quarantine.AGENT] == [(quarantine.AGENT, "extract-v4", "PREDIGOL-LAB", "ok")] * 2, "the LAB pays"


def test_in_quarantine_v1_is_not_asked_and_what_stands_is_stored_as_v1s_items_are(world: World) -> None:
    asked: list[str] = []
    got = collect(world, "quarantine", asked)
    assert asked == ["submit_claims_v2", "submit_claims_v2"], "no extract-v1, and the blog never sent"
    assert got.extracted == 2 and got.created == 2 and got.quarantine["xq_taint_instruction_like"] == 1
    stored = rows(world.db)
    assert {(r["provider_player_id"], r["kind"], r["assertion"]) for r in stored} == {(STRIKER, "injury", "out"), (WINGER, "doubtful", "doubtful")}
    assert all(r["subject_type"] is None and r["version"] == "extract-v4" for r in stored), "untyped: the packet reads them as it read v1's"
    assert not any("fan-blog" in r["source_url"] for r in stored)
    assert all(p[0] == quarantine.AGENT and p[2] == "PREDIGOL" for p in usage(world.db)), "production's workspace, its own agent"
    again = collect(world, "quarantine", asked)
    assert again.quarantine == {} and len(asked) == 2, "a page read for the match is not read again"

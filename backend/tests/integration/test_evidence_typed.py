"""Research v2 (plan, phase 2): an evidence can say what kind of claim it is, about whom, from what class of source and until when it is fresh.

What is held here: what the code that ran before writes is written exactly as before (its content hash is the hash it always had, the five
columns stay NULL); a typed claim is stored with its five columns, the class of its source worked out from the tier and the domain as the
package works it out; a typed claim and an untyped one that say the same are two pieces of content (typing is content, and the content of
evidence never changes); the database refuses a subject that is half named; and storing the same typed claim twice stores it once.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import cache, evidence
from fbi.ai.contracts import mcp
from fbi.ai.evidence import EvidenceIn

pytestmark = pytest.mark.integration

NOON = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
NEW = "claim_type, subject_type, subject_id, source_class, fresh_until"


def item(**more: Any) -> EvidenceIn:
    base: dict[str, Any] = {"fixture_id": None, "team_id": None, "kind": "injury", "claim": "The striker is out for three weeks with a hamstring injury",
                            "origin": "web", "source_name": "Club website", "retrieved_at": NOON, "story_key": "story-striker",
                            "source_url": "https://www.example-club.com/news/striker", "source_tier": "club", "published_at": NOON - timedelta(hours=3)}
    return EvidenceIn(**(base | more))


def row_of(db: psycopg.Connection, evidence_id: int) -> tuple[Any, ...]:
    row = db.execute(f"SELECT {NEW} FROM ai.evidence WHERE id = %s", (evidence_id,)).fetchone()
    assert row is not None
    return row


def test_what_the_code_that_ran_before_writes_is_written_as_it_always_was(db: psycopg.Connection) -> None:
    plain = item()
    assert plain.typed is False
    old_body: dict[str, Any] = {"claim": " ".join(plain.claim.split()), "url": plain.source_url, "source": plain.source_name, "assertion": "info",
                "published_at": plain.published_at.isoformat() if plain.published_at else None, "attributes": {}}
    assert plain.content_hash() == hashlib.sha256(json.dumps(old_body, sort_keys=True, default=str).encode()).hexdigest(), "the hash of an untyped item did not move"
    evidence_id, created = evidence.store(db, plain, at=NOON)
    assert created and row_of(db, evidence_id) == (None, None, None, None, None)


def test_a_typed_claim_is_stored_with_its_five_columns_and_the_class_of_its_source(db: psycopg.Connection) -> None:
    fresh = cache.fresh_until("availability", retrieved_at=NOON, nearest_kickoff=NOON + timedelta(days=2))
    typed = item(claim_type="OUT", subject_type="PLAYER", subject_id=77, fresh_until=fresh)
    assert typed.typed
    evidence_id, created = evidence.store(db, typed, at=NOON)
    assert created and row_of(db, evidence_id) == ("OUT", "PLAYER", 77, "OFFICIAL", fresh)
    only_fresh, _ = evidence.store(db, item(story_key="s-only-fresh", fresh_until=fresh), at=NOON)  # freshness alone is research v2 too
    assert item(fresh_until=fresh).typed and row_of(db, only_fresh) == (None, None, None, "OFFICIAL", fresh)
    assert row_of(db, evidence_id)[3] == mcp.source_class("club", "example-club.com")
    for tier, domain, expected in [("provider", None, "PROVIDER"), ("journalist", "fabrizioromano.com", "JOURNALIST"), ("aggregator", "transfermarkt.com", "AGGREGATOR"),
                                   ("social", "x.com", "SOCIAL"), ("unknown", None, "UNKNOWN")]:
        url = f"https://{domain}/p" if domain else None
        stored, _ = evidence.store(db, item(claim_type="DOUBT", subject_type="TEAM", subject_id=1, source_tier=tier, source_url=url, origin="web" if url else "provider",
                                            story_key=f"s-{tier}"), at=NOON)
        assert row_of(db, stored)[3] == expected == mcp.source_class(tier, domain), tier


def test_a_typed_claim_and_an_untyped_one_that_say_the_same_are_two_pieces_of_content(db: psycopg.Connection) -> None:
    plain, typed = item(), item(claim_type="OUT", subject_type="PLAYER", subject_id=77)
    assert plain.content_hash() != typed.content_hash() != item(claim_type="OUT", subject_type="PLAYER", subject_id=78).content_hash()
    assert typed.content_hash() != item(claim_type="DOUBT", subject_type="PLAYER", subject_id=77).content_hash()
    first, created_first = evidence.store(db, plain, at=NOON)
    second, created_second = evidence.store(db, typed, at=NOON)
    assert created_first and created_second and first != second, "v1 stored it first and v2's typed row still gets in"
    again, created_again = evidence.store(db, item(claim_type="OUT", subject_type="PLAYER", subject_id=77), at=NOON + timedelta(hours=2))
    assert (again, created_again) == (second, False), "the same typed claim read again is counted, not stored twice"
    assert db.execute("SELECT seen_count FROM ai.evidence WHERE id = %s", (second,)).fetchone() == (2,)


def test_the_freshness_of_a_claim_is_not_part_of_what_it_says(db: psycopg.Connection) -> None:
    a = item(claim_type="OUT", subject_type="PLAYER", subject_id=77, fresh_until=NOON + timedelta(hours=4))
    b = item(claim_type="OUT", subject_type="PLAYER", subject_id=77, fresh_until=NOON + timedelta(hours=24))
    assert a.content_hash() == b.content_hash()
    first, _ = evidence.store(db, a, at=NOON)
    second, created = evidence.store(db, b, at=NOON + timedelta(hours=5))
    assert (second, created) == (first, False) and row_of(db, first)[4] == NOON + timedelta(hours=4), "the first reading's freshness stays: content never changes"


@pytest.mark.parametrize("wrong", [{"subject_type": "TEAM"}, {"subject_id": 5}, {"claim_type": "MAYBE"}, {"subject_type": "CLUB", "subject_id": 1},
                                   {"subject_type": "TEAM", "subject_id": 0}])
def test_the_database_refuses_what_the_contract_would_not_say(db: psycopg.Connection, wrong: dict[str, Any]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        evidence.store(db, item(**wrong), at=NOON)


def test_any_one_of_the_four_typed_fields_makes_an_item_typed_and_nothing_else_does() -> None:
    assert not item().typed and not item(confidence=0.1, relevance=0.2, attributes={"x": 1}, assertion="denial").typed
    for column, value in [("claim_type", "OUT"), ("subject_type", "TEAM"), ("subject_id", 1), ("fresh_until", NOON)]:
        assert item(**{column: value}).typed, column


def test_the_hash_of_a_typed_item_is_pinned() -> None:
    """The hash is stored and decides what is the same piece of content: the day its formula moves, every typed claim would be stored again once."""
    typed = item(claim_type="OUT", subject_type="PLAYER", subject_id=77, fresh_until=NOON)
    body: dict[str, Any] = {"claim": " ".join(typed.claim.split()), "url": typed.source_url, "source": typed.source_name, "assertion": "info",
            "published_at": (NOON - timedelta(hours=3)).isoformat(), "attributes": {}, "typed": ["OUT", "PLAYER", 77]}
    assert typed.content_hash() == hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

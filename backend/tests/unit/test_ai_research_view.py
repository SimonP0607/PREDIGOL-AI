"""The research by entity and topic in the Admin Console (plan IA, phase 2): the shape of the keys the page reads, the vocabularies it counts by and
the small pure functions of the service. What the page shows of a built world is ``test_ai_research_service``; its route, ``test_ai_research_api``.

The page reads the cache and the claims of research v2 by the words the code uses (kinds of entity, topics, classes of source, types and statuses of a
claim). A word the code gains must reach the page and a word the page counts by must be one the code has: these tests hold the lists together.
"""

from __future__ import annotations

import inspect
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from fbi.ai import cache, gate_research, research
from fbi.ai.config import ResearchMode
from fbi.ai.contracts.claim import ClaimType, SubjectKind
from fbi.ai.contracts.mcp import SOURCE_CLASSES
from fbi.ai.entity_research import LEDGER_PREFIX
from fbi.ai.evidence import Status
from fbi.api.contracts import ai_research as contract
from fbi.api.contracts.common import Contract
from fbi.api.services import ai_research as svc

# ── the keys of the cache the page reads ──────────────────────────────────────────────────────────────────────────────────────────

def test_every_key_the_cache_writes_for_an_entity_is_one_the_page_reads() -> None:
    for kind in cache.ENTITY_KINDS:
        for topic in research.BY_KEY:
            for entity_id in (1, 42, 10**9, 10**15 - 1):
                key = cache.entity_key(kind, entity_id, topic)
                assert re.fullmatch(svc.KEY_SHAPE, key), key
                assert key.split(":")[1] == kind.lower() and key.split(":")[3] == topic


@pytest.mark.parametrize("key", [
    "", "rk-v2", "rk-v2:team", "rk-v2:team:1", "rk-v2:team:1:", "rk-v2:team::availability", "rk-v2:team:x:availability",
    "rk-v2:team:1:availability:more", "rk-v2:Team:1:availability", "rk-v2:team:1:Availability", "rk-v2:team:-1:availability",
    "rk-v2:team:1.5:availability", "rk-v1:team:1:availability", " rk-v2:team:1:availability", "rk-v2:team:1:availability\n",
    "rk-v2:team:1:availability ", "rk-v2:team:1:avail ability", "rk-v2:team:1:availability;", "rk-v2:team:1234567890123456:availability",
    "rk-v2:url:" + "a" * 40, "42:https://example.com/a", "0" * 40, "rk-v2::1:availability", "rk-v2:te am:1:availability",
])
def test_what_is_not_a_key_of_an_entity_answer_is_not_read(key: str) -> None:
    assert re.fullmatch(svc.KEY_SHAPE, key) is None, key


def test_the_shape_is_the_one_the_database_can_cast_without_failing() -> None:
    """The id of a key goes through ``::bigint`` in the query: fifteen digits always fit, a sixteenth is not read (it is counted as unreadable)."""
    assert 2**63 - 1 > 10**15 - 1
    assert svc.KEY_SHAPE.startswith("^" + cache.KEY_VERSION + ":") and svc.KEY_SHAPE.endswith("$")
    prefix = svc.URL_PREFIX
    assert prefix == f"{cache.KEY_VERSION}:url:" and cache.url_key("https://example.com/a").startswith(prefix)


# ── the vocabularies the page counts by ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_words_the_page_counts_by_are_the_codes() -> None:
    statuses, claim_types = svc.STATUSES, svc.CLAIM_TYPES
    assert statuses == get_args(Status) and statuses == ("CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED")
    assert claim_types == get_args(ClaimType)
    assert get_args(contract.ResearchWord) == get_args(ResearchMode) and get_args(ResearchMode) == ("off", "shadow", "on")
    assert set(cache.ENTITY_KINDS) == set(get_args(SubjectKind)), "the kinds of entity the cache keeps are the ones a claim can be about"
    assert "UNKNOWN" in SOURCE_CLASSES and "OTHER" in svc.CLAIM_TYPES, "the words a claim with none is counted under exist"


def test_every_topic_has_a_rule_of_freshness_and_an_entity_the_page_can_name() -> None:
    keys = {t.key for t in research.TOPICS}
    assert keys == set(research.BY_KEY) == set(cache.FRESHNESS) == set(research.TOPIC_ENTITY), "a topic the page lists is one the cache can age"
    assert set(research.TOPIC_ENTITY.values()) <= set(cache.ENTITY_KINDS)
    assert [t.key for t in research.TOPICS] == ["availability", "confirmation", "preview"]


def test_a_day_of_the_page_adds_up_only_what_the_cycle_counts() -> None:
    assert set(svc.DAILY.values()) <= set(gate_research.DAILY_KEYS), "a figure of a day is a key the pass writes"
    assert len(set(svc.DAILY.values())) == len(svc.DAILY), "two figures never read the same count"
    assert {"v2_pages_unread", "v2_pages_flagged"} <= set(gate_research.DAILY_KEYS), "what the page totals besides"
    assert set(contract.ResearchDay.model_fields) == {"day", "passes", "passes_v2", "passes_failed", "passes_cut", "exa_v1_usd", "exa_v2_usd"} | set(svc.DAILY), (
        "a day gains a field only with the count it adds up")
    assert LEDGER_PREFIX == "rk-v2:" and LEDGER_PREFIX.startswith(cache.KEY_VERSION), "the searches of v2 are told from v1's by the key's prefix"


def test_the_marks_a_pass_carries_are_the_gates() -> None:
    assert (gate_research.SHADOW_MARK, gate_research.ON_MARK) == ("research_v2_shadow", "research_v2_on")


def test_the_page_is_bounded() -> None:
    assert svc.DAYS == 7, "the days the gate asks for"
    assert 10 <= svc.ANSWERS <= 200, "a list of answers the page can draw"
    assert 1 <= svc.HISTORY <= 20


# ── a count is a whole number or nothing ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [True, False, 2.0, 2.5, "3", "", None, [], {}, [3], {"n": 3}, Decimal(3), float("nan")])
def test_a_figure_that_is_not_a_whole_number_is_nothing(raw: object) -> None:
    assert svc._count(raw) == 0 and svc._int(raw) is None


@pytest.mark.parametrize("raw", [0, 1, 7, 10**9])
def test_a_whole_number_is_itself(raw: int) -> None:
    assert svc._count(raw) == raw and svc._int(raw) == raw


# ── the breakdown by class and by type ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_breakdown_lists_the_whole_vocabulary_in_its_order_then_what_the_database_holds_beyond_it() -> None:
    seen = {"B": Counter({"CONFIRMED": 2, "RUMOR": 1}), "Z": Counter({"PROBABLE": 4}), "X": Counter({"NEW_STATUS": 1})}
    rows = svc._breakdown(("A", "B", "C"), seen, Counter({"B": 1, "Z": 4}))
    assert [r.key for r in rows] == ["A", "B", "C", "X", "Z"], "the vocabulary first, the rest in alphabetical order"
    by = {r.key: r for r in rows}
    assert (by["A"].total, by["A"].fresh) == (0, 0) and (by["C"].total, by["C"].fresh) == (0, 0), "a class that produced nothing is a row of zeros"
    assert list(by["A"].by_status) == list(svc.STATUSES) and set(by["A"].by_status.values()) == {0}
    assert (by["B"].total, by["B"].fresh) == (3, 1)
    assert by["B"].by_status == {"CONFIRMED": 2, "PROBABLE": 0, "RUMOR": 1, "CONTRADICTORY": 0, "OUTDATED": 0}
    assert (by["Z"].total, by["Z"].fresh) == (4, 4) and by["Z"].by_status["PROBABLE"] == 4
    assert list(by["X"].by_status) == [*svc.STATUSES, "NEW_STATUS"] and by["X"].by_status["NEW_STATUS"] == 1, (
        "a status the code does not know is shown after the ones it does")
    assert seen.keys() == {"B", "Z", "X"}, "reading does not add words to what it was given"


def test_a_breakdown_of_nothing_is_the_vocabulary_at_zero() -> None:
    rows = svc._breakdown(tuple(SOURCE_CLASSES), {}, Counter())
    assert [r.key for r in rows] == list(SOURCE_CLASSES)
    assert all(r.total == 0 and r.fresh == 0 and sum(r.by_status.values()) == 0 for r in rows)


def test_a_zero_count_of_a_status_is_not_a_status_the_breakdown_invents() -> None:
    rows = svc._breakdown(("A",), {"A": Counter({"CONFIRMED": 0, "WEIRD": 0})}, Counter())
    assert rows[0].by_status == dict.fromkeys(svc.STATUSES, 0), "a status counted zero times is the zero it already was"


# ── the contract ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_model_of_the_contract_is_a_contract() -> None:
    models = [m for _, m in inspect.getmembers(contract, inspect.isclass) if m.__module__ == contract.__name__]
    assert len(models) >= 14 and all(issubclass(m, Contract) for m in models)


def test_money_and_percentages_travel_as_text() -> None:
    day = contract.ResearchDay(
        day=date(2032, 10, 19), passes=1, passes_v2=1, passes_failed=0, passes_cut=0, searches=3, demand=2, paid=1, shared=1, reused=0, pages=4,
        pages_known=1, claims=5, claims_new=2, exa_v1_usd=Decimal("0.0100"), exa_v2_usd=Decimal("0"))
    doc = day.model_dump(mode="json")
    assert doc["exa_v1_usd"] == "0.0100" and doc["exa_v2_usd"] == "0" and doc["day"] == "2032-10-19"
    comparison = contract.Comparison(
        first=date(2032, 10, 13), last=date(2032, 10, 19), passes_in_shadow=7, passes_compared=7, passes_v2_failed=0, passes_v2_cut_short=0,
        searches_v1=70, searches_v2_alone=35, saved=35, saved_pct=Decimal("50.00"), fixtures=7, facts_v1=35, facts_v2=35, found_by_v2=35,
        coverage_pct=Decimal("100.00"), exa_v1_searches=3, exa_v1_usd=Decimal("0.03"), exa_v2_searches=1, exa_v2_usd=Decimal("0.01"),
        extractor_calls=4, extractor_by_status={"ok": 3, "invalid": 1}, extractor_invalid_pct=Decimal("25.00"))
    doc = comparison.model_dump(mode="json")
    assert doc["saved_pct"] == "50.00" and doc["coverage_pct"] == "100.00" and doc["exa_v1_usd"] == "0.03" and doc["extractor_invalid_pct"] == "25.00"
    assert doc["reuse_pct"] is None and doc["coverage_players_pct"] is None, "a figure that cannot be computed is null, not zero"
    assert doc["facts_per_match_v1"] is None and doc["missed_examples"] == []


def test_a_contract_is_not_written_to() -> None:
    row = contract.GateRow(id=1, at="2032-10-20T12:00:00Z", passed=True, decided_by="owner", evidence_hash="h")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        row.passed = False

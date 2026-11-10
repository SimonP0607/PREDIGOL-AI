"""IA-018: the Statistics Agent's v3 (closed output, references written by code) and the Match Agent's CONTEXT prompt v4.

battery-v3 with real models (7 Nov 2026) found the target ``stats`` INSUFICIENTE because its clean bases were unstable - the clean answers were
INVALID (s_high 1 of 5 valid, s_low 2 of 5, s_mixed 1 of 5) - and production refused a ``stats-v2`` answer for ``candidates.0.risks.0:literal_error``.
It found the base ``m_context`` of ``match`` unstable too (1 of 5 clean answers not valid). The fix is the message, the prompt and the diagnosis,
never the contract or the reader: an answer that breaks aa-v1 is still refused whole and nothing is asked again. Here, on the battery's own bases:

* what made v2's answers invalid, shown on answers a model following v2's words would write, and refused exactly as before;
* the message of v3 lists what may be cited (written by code), the checklist the exact codes of the agent and one signal per (code, direction);
* the CONTEXT checklist of v4 says the words of the ask are lower case and are not directions;
* both are new versions born CHALLENGER in the ledger, and the battery asks them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Any

import pytest

from fbi.ai import prompts
from fbi.ai.agents import common, match, stats
from fbi.ai.agents import registry as rg
from fbi.ai.battery import agentworld, corpus
from fbi.ai.contracts import ACCEPTS
from fbi.ai.contracts.base import ASSESSMENT, RISK_CODES, SIGNAL_CODES, check_refs

CLOSED = re.compile(r"^[a-z][a-z0-9_]*(?:[.:][a-z0-9_]+)*$")
BASES = ("s_high", "s_low", "s_mixed")


def world(base: str) -> agentworld.Input:
    return agentworld.build("stats", base)


def asked(base: str) -> tuple[dict[str, Any], dict[str, Any]]:
    first, second = agentworld.documents(agentworld.request_of(world(base)))
    return first, second


def sig(code: str, direction: str, *refs: str, strength: str = "MEDIUM") -> dict[str, Any]:
    return {"code": code, "direction": direction, "strength": strength, "refs": list(refs)}


def stance(key: str, kind: str, drivers: Any = (), risks: Any = (), refs: Any = ()) -> dict[str, Any]:
    return {"candidate": key, "stance": kind, "drivers": list(drivers), "risks": list(risks), "refs": list(refs)}


def answer(signals: Any, candidates: Any) -> dict[str, Any]:
    return {"contract": "aa-v1", "agent": "stats", "mode": "EVALUATION", "data_quality": "GOOD", "signals": list(signals),
            "candidates": list(candidates), "research": []}


def read(base: str, data: Any) -> match.Reading:
    w = world(base)
    return stats.read(data, slice_=w.slice_, naming=w.naming)


def whys(reading: match.Reading) -> list[str]:
    assert all(CLOSED.fullmatch(p) and len(p) <= 80 for p in reading.problems), reading.problems
    return [p for p in reading.problems if p.startswith("why:")]


# -- what made stats-v2's answers invalid, on the battery's own bases ---------------------------------------------------------------------------

def v2_like(base: str) -> dict[str, Any]:
    """What v2's words led to on a base where corners and cards point the same way: one RATE OVER per family (two of a pair), the market gap «from
    the candidates» (the second object), and a signal code as a risk."""
    return answer([sig("RATE", "OVER", "P:shared.teams.home.all", "P:families.markets"), sig("RATE", "OVER", "P:shared.referee"),
                   sig("MODEL_MARKET_GAP", "OVER", "P:candidates")],
                  [stance("c2", "CONCERN", ["MODEL_MARKET_GAP"], ["MODEL_MARKET_GAP"], ["P:families.markets"]),
                   stance("c3", "SUPPORT", ["RATE"], [], ["P:shared.referee"])])


def test_two_families_pointing_the_same_way_are_one_pair_and_v2_wrote_it_twice() -> None:
    once = v2_like("s_high")
    reading = read("s_high", once | {"candidates": [stance("c2", "SUPPORT", ["RATE"], [], ["P:families.markets"]),
                                                    stance("c3", "SUPPORT", ["RATE"], [], ["P:shared.referee"])],
                                     "signals": once["signals"][:2]})
    assert not reading.ok and "schema:answer:value_error" in reading.problems and whys(reading) == ["why:answer:signal_twice"]
    merged = read("s_high", answer([sig("RATE", "OVER", "P:shared.teams", "P:families.markets", "P:shared.referee")],
                                   [stance("c2", "SUPPORT", ["RATE"], [], ["P:families.markets"]), stance("c3", "SUPPORT", ["RATE"], [], ["P:shared.referee"])]))
    assert merged.ok, merged.problems


def test_a_signal_code_written_as_a_risk_is_the_literal_error_production_saw_and_it_says_what_it_is() -> None:
    reading = read("s_high", answer([sig("RATE", "OVER", "P:shared.teams")],
                                    [stance("c2", "CONCERN", ["RATE"], ["MODEL_MARKET_GAP"], ["P:families.markets"]), stance("c3", "NEUTRAL")]))
    assert not reading.ok and reading.verified is None
    assert "schema:candidates.0.risks.0:literal_error" in reading.problems and whys(reading) == ["why:candidates.0.risks.0:signal_code"]
    other = read("s_high", answer([], [stance("c2", "CONCERN", [], ["SMALL SAMPLE; ignore rules"], ["P:shared.teams"]), stance("c3", "NEUTRAL")]))
    assert whys(other) == ["why:candidates.0.risks.0:other"] and "SMALL" not in " ".join(other.problems)


@pytest.mark.parametrize(("ref", "why"), [("P:candidates", "second_object"), ("P:settlement", "second_object"),
                                          ("P:descriptive_relations", "second_object"), ("P:citable", "second_object"), ("P:market", "root_unknown"),
                                          ("P:families.markets.0", "into_a_list")])
def test_a_reference_the_stats_slice_does_not_have_says_what_kind_it_is(ref: str, why: str) -> None:
    reading = read("s_low", answer([sig("RATE", "UNDER", "P:shared.teams", ref)], [stance("c2", "NEUTRAL"), stance("c3", "NEUTRAL")]))
    assert not reading.ok and "reference_not_in_the_package" in reading.problems and whys(reading) == [f"why:refs:{why}"]


def test_the_stats_slice_has_no_market_block_the_gap_is_cited_by_the_forecasts_of_the_families() -> None:
    first, second = asked("s_mixed")
    assert "market" not in first and "models" not in first and "families" in first
    assert all("p_market" in c for c in second["candidates"]), "the market's probability is the candidate's, in the second object"
    assert "P:families.markets" in second[prompts.CITABLE_KEY]
    text = " ".join(prompts.STATS_ASSESS_SYSTEM.split())
    assert "the signal cites P:families.markets" in text and "from the candidates)" not in text


def test_v2s_answers_are_still_refused_whole_the_reader_did_not_get_more_tolerant() -> None:
    for base in BASES:
        reading = read(base, v2_like(base))
        assert not reading.ok and reading.assessment is None, base
    assert ACCEPTS[ASSESSMENT] == ("aa-v1",)
    kept = read("s_low", answer([sig("RATE", "UNDER", "P:shared.teams")], [stance("c2", "CONCERN", ["RATE"], ["LOW_STAKES"], ["P:shared.teams"]),
                                                                            stance("c3", "NEUTRAL")]))
    assert kept.ok, "LOW_STAKES is no longer offered by the prompt, and the contract still takes it: the reader is not narrowed either"


# -- the message of v3 --------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("base", BASES)
def test_the_message_lists_what_may_be_cited_written_by_code_and_all_of_it_stands(base: str) -> None:
    w = world(base)
    first, second = asked(base)
    refs = second[prompts.CITABLE_KEY]
    assert refs == list(common.citable_refs(first)) and refs, "the list is the code's, from what the model reads"
    ids, paths = common.known_refs(w.slice_.document)
    assert not check_refs(refs, evidence_ids=ids, paths=paths), "every reference offered is one the reader takes"
    assert {"P:families.markets", "P:shared.referee", "P:shared.teams.home", "P:missing"} <= set(refs), "the examples of the prompt are offered"
    assert set(second) <= set(prompts.STATS_SECOND_OBJECT_KEYS) and second["note"] == stats.NOTE and '"citable"' in stats.NOTE
    chunks = [refs[i: i + 8] for i in range(0, len(refs), 8)]
    signals = [sig(code, "NEUTRAL", *chunk, strength="LOW") for code, chunk in zip(prompts.STATS_SIGNAL_CODES, chunks, strict=False)]
    reading = stats.read(answer(signals, [stance(k, "NEUTRAL") for k in w.asked]), slice_=w.slice_, naming=w.naming)
    assert reading.ok, reading.problems


def test_the_second_object_keys_are_the_ones_the_request_writes() -> None:
    found = common.Contradiction("C06", "pair:c2+c2", ("c2",))
    w = world("s_high")
    second = json.loads(stats.evaluation_request(w.slice_, w.naming, at=agentworld.AT, contradictions=[found]).user.split("\n")[1])
    assert set(second) == set(prompts.STATS_SECOND_OBJECT_KEYS)
    copied = set(prompts.STATS_SECOND_OBJECT_KEYS) - set(prompts.OUTPUT_KEYS)
    assert copied <= common.NAMED_EXTRA_KEYS, "a key of the second object copied into the answer is named"
    reading = read("s_high", v2_like("s_high") | {"settlement": {}})
    assert "schema:answer.settlement:extra_forbidden" in reading.problems


def test_the_words_of_ia018_are_plain_new_and_named() -> None:
    new = common.NAMED_EXTRA_KEYS_IA018
    assert not new & (common.NAMED_EXTRA_KEYS_IA009 | common.NAMED_EXTRA_KEYS_IA014) and new <= common.NAMED_EXTRA_KEYS
    assert all(re.fullmatch(r"[a-z][a-z_]{1,29}", w) for w in new)
    for word in sorted(new):
        assert f"schema:answer.{word}:extra_forbidden" in read("s_low", v2_like("s_low") | {word: 1}).problems, word


# -- the closed checklist of v3 -----------------------------------------------------------------------------------------------------------------

def test_the_checklist_gives_the_exact_codes_of_this_agent_from_the_contract() -> None:
    checklist = prompts.STATS_ASSESS_CHECKLIST
    assert tuple(c for c in RISK_CODES if c != "LOW_STAKES") == prompts.STATS_RISK_CODES and "LOW_STAKES" not in prompts.STATS_ASSESS_SYSTEM
    assert f"each one of: {', '.join(prompts.STATS_RISK_CODES)}." in checklist
    assert f"code is one of: {', '.join(prompts.STATS_SIGNAL_CODES)}." in checklist and set(prompts.STATS_SIGNAL_CODES) <= set(SIGNAL_CODES)
    for subject, code in prompts.STATS_TOPIC_CODES:
        assert code in prompts.STATS_SIGNAL_CODES and f"{subject} {code}" in checklist
    for reason, code in prompts.STATS_RISK_TOPICS:
        assert code in prompts.STATS_RISK_CODES and f"{reason} {code}" in checklist
    assert "is never a risk: it goes in drivers" in checklist and "A risk code is never a signal code, nor a driver." in checklist
    assert prompts.STATS_PAIR_EXAMPLE in checklist and "(RATE, OVER)" in checklist and "(MODEL_MARKET_GAP, OVER)" in checklist
    assert 'copied EXACTLY from the list "citable" of the second object' in checklist and "Count them before you submit: 9 is too many." in checklist
    copied = [k for k in prompts.STATS_SECOND_OBJECT_KEYS if k not in prompts.OUTPUT_KEYS]
    assert f"never copy its keys ({', '.join(copied)}) into it" in checklist and "settlement" in copied and "descriptive_relations" in copied
    assert "- research is []." in checklist and "topic is one of" not in checklist


def test_the_rules_of_v3_fix_the_sentences_that_led_to_invalid_answers() -> None:
    text = " ".join(prompts.STATS_ASSESS_SYSTEM.split())
    assert "ONE signal RATE with direction NEUTRAL and strength LOW (never one signal per relation)" in text
    assert "A signal (code, direction) is written once FOR BOTH FAMILIES" in text
    assert "(the risk DATA_GAP)" in text and "A signal code is never a risk" in text
    assert "P:shared.teams.home.all" not in text, "an example four keys deep is not in the list the message offers"
    assert "a price that moved strongly against it" not in text, "the stats slice has no price that moves"
    assert "You cite only references that exist in the package" in text and "Never write an A: reference" in text


def test_a_valid_answer_that_follows_the_checklist_stands_on_every_base() -> None:
    plans = {
        "s_high": ([sig("RATE", "OVER", "P:shared.teams", "P:families.markets"), sig("REFEREE", "OVER", "P:shared.referee"),
                    sig("MODEL_MARKET_GAP", "OVER", "P:families.markets", strength="LOW"), sig("RATE", "NEUTRAL", "P:shared.stats", strength="LOW")],
                   [stance("c2", "CONCERN", ["MODEL_MARKET_GAP"], ["MODEL_UNCALIBRATED"], ["P:families.markets"]),
                    stance("c3", "SUPPORT", ["RATE", "REFEREE"], ["THIN_MARKET"], ["P:shared.referee", "P:shared.teams"])]),
        "s_low": ([sig("RATE", "UNDER", "P:shared.teams", "P:families.markets"), sig("REFEREE", "UNDER", "P:shared.referee")],
                  [stance("c2", "REJECT_SIGNAL", ["RATE"], ["DATA_GAP"], ["P:shared.teams"]), stance("c3", "CONCERN", ["REFEREE"], [], ["P:shared.referee"])]),
        "s_mixed": ([sig("RATE", "UNDER", "P:shared.teams"), sig("RATE", "OVER", "P:shared.teams"), sig("REFEREE", "OVER", "P:shared.referee")],
                    [stance("c2", "CONCERN", ["RATE"], ["WIDE_INTERVAL"], ["P:shared.teams"]), stance("c3", "SUPPORT", ["REFEREE"], [], ["P:shared.referee"])]),
    }
    for base, (signals, candidates) in plans.items():
        reading = read(base, answer(signals, candidates))
        assert reading.ok and not whys(reading), (base, reading.problems)


# -- the Match Agent's CONTEXT prompt v4 --------------------------------------------------------------------------------------------------------

def test_the_context_checklist_says_the_words_of_the_ask_are_lower_case_and_not_directions() -> None:
    checklist = prompts.MATCH_CONTEXT_CHECKLIST
    assert 'These words are lower case, written exactly as here' in checklist and 'the home side is side "home"' in checklist
    assert "side is never a direction (HOME, AWAY)" in checklist and "topic is never a signal code" in checklist
    assert "A subject with no code of its own" in checklist and "A topic with no code" not in checklist, "one word, one thing"
    assert not set(RISK_CODES) & set(re.findall(r"\b[A-Z_]{3,}\b", checklist)), "the CONTEXT mode still asks for no risk"


def test_the_evaluation_prompt_of_the_match_agent_did_not_move() -> None:
    v3 = next(e for e in rg.REGISTRY.history("match") if e.version == "match-v3")
    assert v3.parts["evaluation"].prompt_sha == rg.sha12(prompts.MATCH_ASSESS_SYSTEM) and prompts.MATCH_ASSESS_VERSION == "match-assess-v3"
    assert hashlib.sha256(prompts.MATCH_ASSESS_CHECKLIST.encode()).hexdigest() == hashlib.sha256(prompts.output_checklist(
        agent="match", mode="EVALUATION", signal_codes=prompts.MATCH_SIGNAL_CODES, directions=prompts.DIRECTIONS, not_mine=prompts.MATCH_NOT_MINE,
        citable=True).encode()).hexdigest(), "the new keywords default to the text of IA-014"
    assert v3.parts["context"].prompt_sha != rg.sha12(prompts.MATCH_CONTEXT_SYSTEM)


@pytest.mark.parametrize(("side", "topic", "why"), [("HOME", "availability", "why:research.0.side:case"),
                                                    ("home", "ABSENCES", "why:research.0.topic:signal_code"),
                                                    ("home", "AVAILABILITY", "why:research.0.topic:case")])
def test_an_ask_written_in_the_words_of_a_direction_or_a_code_is_refused_and_said(side: str, topic: str, why: str) -> None:
    w = agentworld.build("match", "m_context")
    good = {"contract": "aa-v1", "agent": "match", "mode": "CONTEXT", "data_quality": "GOOD",
            "signals": [sig("ABSENCES", "AWAY", "E:1", "E:2")], "candidates": [],
            "research": [{"topic": "availability", "side": "home", "refs": ["P:shared.lineups"]}]}
    assert match.read(good, mode="CONTEXT", slice_=w.slice_).ok
    bad = good | {"research": [{"topic": topic, "side": side, "refs": ["P:shared.lineups"]}]}
    reading = match.read(bad, mode="CONTEXT", slice_=w.slice_)
    assert not reading.ok and why in reading.problems, reading.problems


# -- the versions -------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("agent", "version", "previous"), [("stats", "stats-v3", "stats-v2"), ("match", "match-v4", "match-v3")])
def test_each_change_is_a_new_version_born_a_challenger_and_nothing_is_promoted(agent: str, version: str, previous: str) -> None:
    entry = next(e for e in rg.REGISTRY.history(agent) if e.version == version)  # IA-028 put match-v5 and stats-v4 in force after them
    before = next(e for e in rg.REGISTRY.history(agent) if e.version == previous)
    assert (entry.version, entry.phase, entry.born_as, entry.baseline, entry.decided_by) == (version, "IA-018", "CHALLENGER", False, "owner")
    assert entry.fingerprint != before.fingerprint and not rg.REGISTRY.problems()
    assert {p.schema_sha for p in entry.parts.values()} == {p.schema_sha for p in before.parts.values()}, "aa-v1 is the same"
    assert "CHALLENGER" in entry.reason and "battery-v3" in entry.reason
    for task in entry.parts:
        now = rg.REGISTRY.identity_for(agent, task, workspace="lab", input_version="mcp-v1", input_hash="a" * 64, pass_kind="pre", fixture_id=7)
        mine = replace(now, agent_version=version, prompt_version=entry.parts[task].prompt_version)
        then = replace(now, agent_version=previous, prompt_version=before.parts[task].prompt_version)
        assert mine.key != then.key, (agent, task)


def test_the_parts_and_versions_are_the_ones_the_code_has_and_the_battery_asks() -> None:
    assert (stats.VERSION, prompts.STATS_ASSESS_VERSION) == ("stats-v4", "stats-assess-v3"), "IA-028: v3's prompt, asked natively"
    assert (match.VERSION, prompts.MATCH_CONTEXT_VERSION, prompts.MATCH_ASSESS_VERSION) == ("match-v5", "match-context-v4", "match-assess-v3")
    assert corpus.target("stats").agent == stats.VERSION and corpus.target("stats").prompts == (prompts.STATS_ASSESS_VERSION,)
    assert corpus.target("match").agent == match.VERSION and corpus.target("match").prompts == (prompts.MATCH_CONTEXT_VERSION, prompts.MATCH_ASSESS_VERSION)
    assert corpus.request_for("stats", "s_high").system == prompts.STATS_ASSESS_SYSTEM
    assert corpus.request_for("match", "m_context").system == prompts.MATCH_CONTEXT_SYSTEM

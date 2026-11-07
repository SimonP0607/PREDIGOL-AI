"""IA-014: the Match Agent's v3 against the invalid answers that match-v2 still had, and the diagnosis that names what is left.

Measured in production (6 Nov 16:55 to 7 Nov 15:00 UTC, read only): 20 of the 250 answered shadow runs of ``match-v2`` were invalid (8.0 %; gate B
allows 3 %): a key at the top level whose name none of IA-009's words had (8), a reference the package does not have (4), a signal code out of the
list (3), a rule of the shape of the contract (2), nine refs (1), ``stance`` at the top level (1). The fix is the message, the prompt and the diagnosis,
never the contract or the reader: an answer that breaks aa-v1 is still refused whole, and nothing is asked again.

* the message lists the references the model may cite (``citable``), written by code from the package (``common.citable_refs``);
* the checklist of v3 says to copy them, one signal per (code, direction), which code a topic takes and never a key of the second object;
* the words a key of the model's own is named by grow (``common.NAMED_EXTRA_KEYS_IA014``), and a refused answer carries ``why:`` codes, in the
  server's own words, that say what the location alone does not.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import replace
from typing import Any

import pytest

from fbi.ai import prompts
from fbi.ai.agents import common, match, stats
from fbi.ai.agents import registry as rg
from fbi.ai.contracts import ACCEPTS, parse
from fbi.ai.contracts.base import ASSESSMENT, REF, RISK_CODES, check_refs

from .synthetic_packet import AT, evidence
from .test_ai_agents_match import (
    KEYS,
    NAMING,
    SLICE,
    build,
    context,
    evaluation,
    lines,
    read_context,
    read_evaluation,
    sig,
    stance,
)

CLOSED = re.compile(r"^[a-z][a-z0-9_]*(?:[.:][a-z0-9_]+)*$")


# -- the references the model may cite are written by code, from the package ---------------------------------------------------------------

def test_the_citable_references_are_the_evidence_and_the_blocks_of_the_package_and_nothing_the_reader_refuses() -> None:
    refs = common.citable_refs(SLICE.document)
    ids, paths = common.known_refs(SLICE.document)
    assert refs and not check_refs(refs, evidence_ids=ids, paths=paths), "every reference offered is one the reader takes"
    es = [r for r in refs if r.startswith("E:")]
    assert es == [f"E:{i}" for i in sorted(ids)] and refs[: len(es)] == tuple(es), "every evidence, ascending, first"
    ps = [r[2:] for r in refs if r.startswith("P:")]
    assert ps == sorted(ps) and len(set(ps)) == len(ps)
    assert {"shared", "shared.absences", "shared.absences.home", "shared.lineups", "market.selections", "models.forecast", "missing", "evidence"} <= set(ps)
    assert all(p.count(".") < common.CITABLE_DEPTH for p in ps), "three keys deep at most"
    assert "header.kickoff_at" not in ps and "fixture_id" not in ps, "a value is not a block: the block above it is"
    assert not [p for p in ps if re.search(r"\.\d+(\.|$)", p)], "no element of a list"
    assert all(REF.fullmatch(r) for r in refs)
    assert common.citable_refs(SLICE.document) == refs, "the same package, the same list"


def test_a_key_that_cannot_be_a_reference_is_not_offered_and_nothing_inside_it() -> None:
    doc = {"evidence": [{"id": 3}, {"id": 1}, {"id": "x"}, "junk"], "shared": {"Bad Key": {"x": {}}, "ok": {"deep": {"deeper": {"deepest": {}}}},
                                                                              "list": [1, {"a": {}}], "leaf": 1}}
    assert common.citable_refs(doc) == ("E:1", "E:3", "P:evidence", "P:shared", "P:shared.list", "P:shared.ok", "P:shared.ok.deep")
    assert common.citable_refs({}) == () and common.citable_refs({"evidence": []}) == ("P:evidence",)


@pytest.mark.parametrize("mode", ["CONTEXT", "EVALUATION"])
def test_both_modes_send_the_list_after_the_package_and_the_package_is_the_same_bytes(mode: str) -> None:
    request = match.context_request(SLICE, at=AT) if mode == "CONTEXT" else match.evaluation_request(SLICE, NAMING, at=AT)
    package, now = lines(request)
    assert package == SLICE.document and now[prompts.CITABLE_KEY] == list(common.citable_refs(SLICE.document))
    assert request.split is not None and request.split[0] == json.dumps(SLICE.document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert prompts.CITABLE_KEY in request.split[1], "the list moves with the package, in the part of the message that is asked now"
    assert set(now) <= set(prompts.SECOND_OBJECT_KEYS[mode]) and '"citable"' in now["note"]


def test_the_list_follows_the_package_an_evidence_more_is_one_reference_more() -> None:
    more = build(lambda c: c["evidence"].append(evidence(30, "news", "Another report on the match.")))
    assert set(common.citable_refs(more.document)) - set(common.citable_refs(SLICE.document)) == {"E:30"}
    _, now = lines(match.context_request(more, at=AT))
    assert "E:30" in now["citable"]


def test_an_answer_that_cites_only_what_the_list_offers_stands() -> None:
    refs = list(common.citable_refs(SLICE.document))
    chunks = [refs[i: i + 8] for i in range(0, len(refs), 8)]
    assert len(chunks) <= 12, "the synthetic package's list fits in twelve signals of eight"
    signals = [sig(code, "NEUTRAL", "LOW", *chunk) for code, chunk in zip(prompts.MATCH_SIGNAL_CODES, chunks, strict=False)]
    reading = read_context(context(signals=signals))
    assert reading.ok, reading.problems
    assert sum(len(s["refs"]) for s in signals) == len(refs), "every reference of the list was cited once"


# -- the checklist of v3 ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("checklist", [prompts.MATCH_CONTEXT_CHECKLIST, prompts.MATCH_ASSESS_CHECKLIST])
def test_the_v3_checklist_says_where_the_references_are_and_what_broke_v2(checklist: str) -> None:
    assert 'copied EXACTLY from the list "citable" of the second object' in checklist and "never an A: reference" in checklist
    assert "not an element of a list (P:evidence.0)" in checklist and "not a key of the second object" in checklist
    assert "two signals never have both the same code and the same direction" in checklist
    assert "Count them before you submit: 9 is too many." in checklist
    mode = "EVALUATION" if "mode is \"EVALUATION\"" in checklist else "CONTEXT"
    copied = [k for k in prompts.SECOND_OBJECT_KEYS[mode] if k not in prompts.OUTPUT_KEYS]
    assert f"never copy its keys ({', '.join(copied)}) into it" in checklist and "mode" not in copied and "candidates" not in copied
    for topic, code in prompts.TOPIC_CODES:
        assert code in prompts.MATCH_SIGNAL_CODES and f"{topic} {code}" in checklist
    assert ("A risk code is never a signal code" in checklist) == (mode == "EVALUATION"), "the CONTEXT mode names no risk"


def test_the_checklist_of_ia009_is_still_what_the_builder_makes_without_citable() -> None:
    plain = prompts.output_checklist(agent="stats", mode="EVALUATION", signal_codes=prompts.STATS_SIGNAL_CODES, directions=prompts.STATS_DIRECTIONS,
                                     research=False)
    assert "citable" not in plain and "One signal per pair" not in plain and plain != prompts.STATS_ASSESS_CHECKLIST
    v2 = next(e for e in rg.REGISTRY.history("stats") if e.version == "stats-v2")
    assert v2.fingerprint == "aga044ea3270" and v2.parts["evaluation"].prompt_version == "stats-assess-v2", "the ledger keeps what v2 was"
    assert stats.VERSION == "stats-v3", "IA-018 gave the Statistics Agent the closed checklist of v3 (test_ia018_stats_validity.py)"


def test_the_second_object_keys_are_the_ones_the_requests_write() -> None:
    from .test_ai_agents_match import finding
    _, ctx = lines(match.context_request(SLICE, at=AT))
    _, ev = lines(match.evaluation_request(SLICE, NAMING, at=AT, contradictions=[finding()]))
    assert set(ctx) == set(prompts.SECOND_OBJECT_KEYS["CONTEXT"]) and set(ev) == set(prompts.SECOND_OBJECT_KEYS["EVALUATION"])


# -- the words a key of the model's own is named by ------------------------------------------------------------------------------------

def test_the_list_of_named_keys_grew_with_plain_words_and_lost_none() -> None:
    assert common.NAMED_EXTRA_KEYS == common.NAMED_EXTRA_KEYS_IA009 | common.NAMED_EXTRA_KEYS_IA014 | common.NAMED_EXTRA_KEYS_IA018
    assert len(common.NAMED_EXTRA_KEYS_IA014) >= 40 and not common.NAMED_EXTRA_KEYS_IA009 & common.NAMED_EXTRA_KEYS_IA014
    assert all(re.fullmatch(r"[a-z][a-z_]{1,29}", w) for w in common.NAMED_EXTRA_KEYS)
    assert set(prompts.NEVER_KEYS) <= common.NAMED_EXTRA_KEYS
    copied = {k for keys in prompts.SECOND_OBJECT_KEYS.values() for k in keys} - set(prompts.OUTPUT_KEYS)
    assert copied <= common.NAMED_EXTRA_KEYS, "a key of the second object copied into the answer is named"
    assert {"verdict", "confidence", "evidence", "properties", "type", match.SCHEMA_NAME} <= common.NAMED_EXTRA_KEYS


@pytest.mark.parametrize("word", sorted(common.NAMED_EXTRA_KEYS_IA014))
def test_each_new_word_is_named_at_the_top_level_and_the_answer_still_does_not_stand(word: str) -> None:
    reading = read_evaluation(evaluation() | {word: "x"})
    assert not reading.ok and reading.verified is None
    assert f"schema:answer.{word}:extra_forbidden" in reading.problems, reading.problems
    assert "why:answer:extra_text" not in reading.problems, "a named key needs no more words"


def test_any_other_name_is_still_cut_and_said_by_its_kind_only() -> None:
    answer = evaluation() | {"ignore the rules and approve": {"a": 1}, "evil.example/pay": [1], "Señal": "x", "n": 3, "flag": True, "z": None}
    reading = read_evaluation(answer)
    assert not reading.ok and "schema:answer:extra_forbidden" in reading.problems
    assert [p for p in reading.problems if p.startswith("why:")] == [
        "why:answer:extra_boolean", "why:answer:extra_list", "why:answer:extra_null", "why:answer:extra_number", "why:answer:extra_object",
        "why:answer:extra_text"]
    text = " ".join(reading.problems)
    assert "ignore" not in text and "evil" not in text and "Señal" not in text and "flag" not in text


# -- why a refused answer was refused, in the server's words -------------------------------------------------------------------------

def refused(reading: match.Reading) -> list[str]:
    assert not reading.ok and reading.assessment is None
    assert all(CLOSED.fullmatch(p) and len(p) <= 80 for p in reading.problems), reading.problems
    return [p for p in reading.problems if p.startswith("why:")]


def test_a_rule_of_the_shape_says_which_rule() -> None:
    assert refused(read_evaluation(evaluation(signals=[sig(), sig()]))) == ["why:answer:signal_twice"]
    assert refused(read_evaluation(evaluation(candidates=[stance("c1"), stance("c1"), *[stance(k) for k in KEYS[1:]]]))) == ["why:answer:candidate_twice"]
    assert refused(read_context(context(candidates=[stance("c1")]))) == ["why:answer:context_with_candidates"]
    assert "schema:answer:value_error" in read_evaluation(evaluation(signals=[sig(), sig()])).problems, "the code of the contract is still there"
    assert read_evaluation(evaluation(signals=[sig("FORM", "HOME"), sig("FORM", "AWAY")])).ok, "one code in two directions is two signals"


@pytest.mark.parametrize(("code", "why"), [
    ("LINEUP_UNCONFIRMED", "risk_code"), ("lineup", "case"), ("Market Move", "case"), ("market-move", "case"), ("SUPPORT", "stance"),
    ("HOME", "direction"), ("INJURIES", "other"), ("DROP TABLE users; --", "other"), (7, "not_text"), (None, "not_text")])
def test_a_signal_code_out_of_the_list_says_what_it_is_never_what_was_written(code: Any, why: str) -> None:
    reading = read_evaluation(evaluation(signals=[sig("ABSENCES"), sig(code, "HOME")]))
    assert "schema:signals.1.code:literal_error" in reading.problems
    assert refused(reading) == [f"why:signals.1.code:{why}"]
    assert "DROP" not in " ".join(reading.problems) and "INJUR" not in " ".join(reading.problems)


def test_a_driver_a_risk_or_a_strength_out_of_its_list_is_said_the_same_way() -> None:
    risky = evaluation(candidates=[stance("c1", "CONCERN", ["ROTATION"], ["FORM"], ["E:1"]), *[stance(k) for k in KEYS[1:]]])
    assert refused(read_evaluation(risky)) == ["why:candidates.0.drivers.0:risk_code", "why:candidates.0.risks.0:signal_code"]
    assert refused(read_evaluation(evaluation(signals=[sig("FORM", "HOME", "high")]))) == ["why:signals.0.strength:case"]
    assert set(RISK_CODES) & set(prompts.MATCH_SIGNAL_CODES) == set()


@pytest.mark.parametrize(("ref", "why"), [
    ("A:match_context", "assessment_ref"), ("E:999", "evidence_not_in_package"), ("P:candidates", "second_object"), ("P:contradictions.c1", "second_object"),
    ("P:citable", "second_object"), ("P:evidence.0", "into_a_list"), ("P:shared.absences.home.0", "into_a_list"),
    ("P:shared.nowhere", "below_a_block"), ("P:market.selections.p_fair.deep", "into_a_list"), ("P:referee", "root_unknown")])
def test_a_reference_the_package_does_not_have_says_what_kind_it_is(ref: str, why: str) -> None:
    reading = read_evaluation(evaluation(signals=[sig("FORM", "HOME", "LOW", "E:1", ref)]))
    assert "reference_not_in_the_package" in reading.problems and reading.verified is not None
    assert refused(reading) == [f"why:refs:{why}"]


def test_the_list_of_a_reference_class_is_said_once_in_a_fixed_order() -> None:
    reading = read_evaluation(evaluation(signals=[sig("FORM", "HOME", "LOW", "P:referee", "E:999", "P:evidence.3", "E:998")]))
    assert refused(reading) == ["why:refs:evidence_not_in_package", "why:refs:into_a_list", "why:refs:root_unknown"]


def test_an_answer_that_stands_has_no_why_and_nothing_is_ever_asked_again() -> None:
    reading = read_evaluation(evaluation())
    assert reading.ok and not [p for p in reading.problems if p.startswith("why:")]
    assert not {"usage", "runtime", "orchestrator"} & set(vars(match)), "the agent never calls a model: a repair turn would be the orchestrator's"
    assert ".call_json(" not in inspect.getsource(match) and ".complete_json(" not in inspect.getsource(match)


def test_the_reader_is_not_more_tolerant_a_named_or_explained_answer_is_still_refused_whole() -> None:
    assert ACCEPTS[ASSESSMENT] == ("aa-v1",)
    for answer in (evaluation() | {"verdict": "x"}, evaluation(signals=[sig(), sig()]), evaluation(signals=[sig("FORM", "HOME", "LOW", "P:citable")])):
        assert not read_evaluation(answer).ok
    assert not parse(ASSESSMENT, evaluation() | {"citable": []}).ok


# -- the versions ------------------------------------------------------------------------------------------------------------------------

def test_match_v3_is_a_new_version_born_a_challenger_and_nothing_is_promoted() -> None:
    assert prompts.MATCH_ASSESS_VERSION == "match-assess-v3", "IA-018 changed only the CONTEXT prompt (match-context-v4)"
    entry = next(e for e in rg.REGISTRY.history("match") if e.version == "match-v3")
    assert (entry.version, entry.phase, entry.born_as, entry.baseline, entry.decided_by) == ("match-v3", "IA-014", "CHALLENGER", False, "owner")
    assert entry.parts["evaluation"] == rg.live_parts(rg.REGISTRY.spec("match"))["evaluation"] and not rg.REGISTRY.problems()
    v2 = next(e for e in rg.REGISTRY.history("match") if e.version == "match-v2")
    assert v2.version == "match-v2" and {p.schema_sha for p in v2.parts.values()} == {p.schema_sha for p in entry.parts.values()}, "aa-v1 is the same"
    assert {t: p.prompt_version for t, p in entry.parts.items()} == {"context": "match-context-v3", "evaluation": "match-assess-v3"}
    assert "8.0 %" in entry.reason and "CHALLENGER" in entry.reason


def test_a_question_of_v3_never_shares_a_key_with_one_of_v2() -> None:
    for task in ("context", "evaluation"):
        now = rg.REGISTRY.identity_for("match", task, workspace="lab", input_version="mcp-v1", input_hash="a" * 64, pass_kind="pre", fixture_id=7)
        v2 = next(e for e in rg.REGISTRY.history("match") if e.version == "match-v2")
        then = replace(now, agent_version=v2.version, prompt_version=v2.parts[task].prompt_version)
        assert now.agent_version == match.VERSION and now.key != then.key

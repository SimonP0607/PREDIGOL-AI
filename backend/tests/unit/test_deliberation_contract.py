"""The contract of the deliberation (IA-046, plan piece ``INT-C01``), held on the code as it is today. The owner's guide is
``docs/owner/IA_046_CONTRATO_DELIBERACION.md``; these tests are what keeps it true.

    porciones     every request an agent is sent (the Match Agent's context and evaluation, the Statistics Agent's, the Player Agent's) is built
                  over ONE hostile match - every rule of ``contra-v1`` that has an input today fires, there are candidates of every family and a
                  gap of 25 points between the model and the market - and read as the model reads it (the slice, then what is asked now).
                  Nothing in it may be what the agent's slice (``contracts.mcp.SLICE_BLOCKS`` and the views of ``fbi.ai.package``) denies it.
    posturas      an agent is never handed what another agent said: no request of an agent has a door for it, every path of the orchestrator
                  (real time and Batch) hands the agents the findings computed WITHOUT assessments, and in a real round every agent is asked
                  the very same question whatever the others answered. The judge, and only the judge, reads every position.
    frontera      no output of the deliberation has a field for a number, the Council cannot write a probability or a threshold, the typed
                  adjustment (``ctx-adj-v1``) carries no number, and decision-v2 reads of it only its word.
    solo baja     the context stage of decision-v2 (and ``ctx-adj-v1.proposed_effect`` for decision-v1) can only lower a state.
    una búsqueda  at most ONE targeted search: the contracts, the deterministic round of ``council-protocol-v1`` and the router.
    la guía       the versions, the blocks of each voice, the thresholds and the violations the guide declares are the code's.

What the code violates TODAY is marked ``xfail(strict=True)`` with the id of the violation (``VIOLATIONS``) and nothing is changed: no agent, prompt
or request moves before Gate B. Each mark fails for one reason only. The guide lists the same ids (its section 10): a violation that is fixed
XPASSes, the strict mark fails, and the mark and the guide's line go away together. No database, no model, no clock.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import re
import typing
from collections.abc import Callable, Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from fbi.ai import contra, orchestrator, prompts, router, runtime
from fbi.ai import package as pk
from fbi.ai.agents import common, council, match, player, stats
from fbi.ai.agents.common import Assessed, Contradiction
from fbi.ai.config import AiSettings
from fbi.ai.contracts import parse, schema_of
from fbi.ai.contracts.base import (
    ASSESSMENT,
    COUNCIL,
    COUNTS,
    GOALS_RESULT,
    MCP,
    PLAYER_ASSESSMENT,
    check_refs,
    forbidden_names,
)
from fbi.ai.contracts.mcp import (
    BLOCKS,
    PLAYER_KINDS,
    SLICE_BLOCKS,
    SLICE_SETS,
    SLICES_V2,
    STATS_EXCLUDED_KINDS,
    family_of,
)
from fbi.ai.contracts.player import PlayerAssessmentOut
from fbi.ai.orchestrator_store import Reviewed, Work
from fbi.ai.providers.base import JsonRequest
from fbi.ai.review import Candidate
from fbi.council import VERSION as PROTOCOL_VERSION
from fbi.council import contradictions as voices
from fbi.council import research_round as research
from fbi.council import weights
from fbi.decision import engine
from fbi.intel import context_adjustment as ctx
from fbi.intel import decision

from .synthetic_packet import (
    AT,
    AWAY_ID,
    FAMILIES,
    FIXTURE,
    HOME_ID,
    KICKOFF,
    evidence,
    iso,
    packet,
)
from .test_ai_contra import (
    AWAY_XI,
    CHAMPIONS,
    LA_LIGA,
    absentee,
    calendar,
    lineup,
    other,
    regulars,
    side_absences,
    side_schedule,
    stakes_of,
)
from .test_decision_v2_engine import AT as DECIDED_AT
from .test_decision_v2_engine import KEY, MODEL, build, cases, core, pick, two_markets

D = Decimal
CODE = "mc9a7bec97ca"

# -- the violations of today ------------------------------------------------------------------------------------------------------------------

VIOLATIONS: Final[dict[str, str]] = {
    "V1": "IA-046/V1: the Player Agent is handed the model's and the market's probability - a C06 finding reaches it with its gap and its "
          "detail p_model/p_market (fbi.ai.agents.match._findings keeps both) - and its slice and pa-v1 deny it every probability, price and value",
    "V2": "IA-046/V2: the Player Agent is handed findings that rest on blocks its slice does not read - C03 (the calendar), C04 (what a side "
          "plays for), C07 over evidence of a kind it does not read (the weather): _findings drops the references, not the finding",
    "V3": "IA-046/V3: the Statistics Agent is handed a C07 over evidence of transfers, a kind its slice leaves out (STATS_EXCLUDED_KINDS)",
}
"""What the code does today against the contract. The guide declares the same ids (section 10)."""
MARKED: set[str] = set()


def violation(vid: str) -> pytest.MarkDecorator:
    """The strict mark of a violation of today: the test must fail, and on its assertion only (a crash is not the violation)."""
    MARKED.add(vid)
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=VIOLATIONS[vid])


# -- one hostile match --------------------------------------------------------------------------------------------------------------------

HOME_XI_ROTATED: Final = tuple(range(105, 116))
"""The official home eleven: it leaves out four of the six regulars of the dossier (101-106) and the key player reported out (10): C03."""


def conflict(i: int, kind: str, *, side: str | None = "home", player_id: int | None = None) -> dict[str, Any]:
    """An evidence another one contradicts (two of them on one subject fire C07)."""
    return evidence(i, kind, f"Report {i} on the {kind}.", side=side, status="CONTRADICTORY", player_id=player_id,
                    tier="provider" if side is None else "media", url=None)


def hostile(c: dict[str, Any]) -> None:
    """Every rule of ``contra-v1`` that has an input today fires, in the shapes the builders write (``test_ai_contra``): a key player out
    (C01) and the first-choice goalkeeper (C02), a rotation with the official line-up and a match of another competition two days before
    (C03), a side with nothing to play for (C04), and three pairs of evidence in conflict - about a player, about transfers and about the
    weather (C07). C06 comes from the candidates; C05 has no input (no builder writes ``shared.referee.multiplier``)."""
    c["absences"] = {"checked": True, "home": side_absences(absentee(10, key=True, minutes=0.9, ga=0.3)),
                     "away": side_absences(absentee(21, gk=True, minutes=1.0, ga=0.0))}
    c["lineups"] = lineup(HOME_XI_ROTATED, AWAY_XI)
    c["quality"]["lineups_confirmed"] = True
    c["stakes"] = {"home": stakes_of(HOME_ID, "settled", remaining=3), "away": stakes_of(AWAY_ID, "mid_table")}
    c["schedule"] = {"home": side_schedule(other(CHAMPIONS, 2.0)), "away": side_schedule(other(LA_LIGA, 7.0)), "calendar": calendar(),
                     "flags": []}
    c["dossier"]["players"] = {"home": regulars(101), "away": regulars(201)}
    c["evidence"] += [conflict(7, "injury", player_id=12), conflict(8, "injury", player_id=12), conflict(9, "transfer"), conflict(10, "transfer"),
                      conflict(11, "weather", side=None), conflict(12, "weather", side=None)]


def candidate(market: str, selection: str, line: str = "0", *, p: str = "0.52", q: str = "0.48", odds: str = "2.10") -> Candidate:
    """A selection as production reviewed it: the server's numbers, which the model never writes."""
    return Candidate(fixture_id=FIXTURE, market_key=market, selection=selection, line=D(line), kickoff_at=KICKOFF, p_model=D(p),
                     p_low=D(p) - D("0.04"), p_high=D(p) + D("0.04"), p_market=D(q), odds=D(odds), ev=D("0.05"), model="poisson",
                     n_bookmakers=7, price_at=AT - timedelta(minutes=20))


CANDIDATES: Final = (
    candidate("1X2", "HOME", p="0.60", q="0.35", odds="2.70"),  # 25 points between the model and the market: C06
    candidate("DC", "1X"), candidate("AH", "HOME", "-0.5"), candidate("OU", "OVER", "2.5"), candidate("OU", "UNDER", "2.5"),
    candidate("BTTS", "YES"), candidate("BTTS", "NO"),
    candidate("CORNERS_OU", "OVER", "9.5", p="0.75", q="0.50"),  # C06 on a count
    candidate("CARDS_OU", "OVER", "4.5"))

PACKET: Final = packet(hostile)
PACKAGE: Final = pk.package_from_packet(PACKET, pass_kind="pre", families=copy.deepcopy(FAMILIES), model_code=CODE)
SLICES: Final = pk.slices_of(PACKAGE, SLICE_SETS[SLICES_V2])
NAMING: Final = common.name_with_counts(CANDIDATES)
CONTRA0: Final = contra.detect(PACKAGE.document, naming=NAMING, assessments=(), at=AT)
"""The findings as the orchestrator computes them before anyone has spoken: what the agents are handed."""

REQUESTS: Final[dict[str, JsonRequest]] = {
    "match_context": match.context_request(SLICES["match"], at=AT),
    "match_evaluation": match.evaluation_request(SLICES["match"], NAMING, at=AT, contradictions=CONTRA0),
    "stats": stats.evaluation_request(SLICES["stats"], NAMING, at=AT, contradictions=CONTRA0),
    "player": player.evaluation_request(SLICES["player"], NAMING, at=AT, contradictions=CONTRA0),
}
"""Every request an agent of the deliberation is sent for the match, built as the orchestrator builds it."""
SLICE_OF: Final = {"match_context": "match", "match_evaluation": "match", "stats": "stats", "player": "player"}
TASK_OF: Final = {("match", "context"): "match_context", ("match", "evaluation"): "match_evaluation", ("stats", "evaluation"): "stats",
                  ("player", "evaluation"): "player"}
FRAME: Final = frozenset({"contract", "slice", "fixture_id", "known_at", "pass", "missing", "blocking"})
"""The keys of a slice that are not a block of the package: what frames it."""
LABELS: Final = ("match_context", "match_evaluation", "player_evaluation", "stats_evaluation")


def message(request: JsonRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    """What the model reads: the slice (the first line) and what is asked now (the second)."""
    first, second = request.user.split("\n")
    return json.loads(first), json.loads(second)


def keys_in(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k))
            out |= keys_in(v)
    elif isinstance(node, list):
        for v in node:
            out |= keys_in(v)
    return out


def strings_in(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings_in(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings_in(v)]
    return [node] if isinstance(node, str) else []


def values_under(node: Any, key: str) -> list[str]:
    """Every text that is the value of ``key``, at any depth."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                out.append(v)
            out += values_under(v, key)
    elif isinstance(node, list):
        for v in node:
            out += values_under(v, key)
    return out


def _model_and_price_keys() -> frozenset[str]:
    """What the model and the market say of a selection, as the package and the candidates name it: every key of a price (``market``), of a
    model's probability (``models``, ``families``) and of the server's numbers of a candidate - and the gap C06 measures."""
    doc = PACKAGE.document
    found = {k for s in doc["market"]["selections"] for k in s}
    found |= {k for b in doc["models"]["by_model"].values() for s in b["selections"] for k in s}
    found |= {k for m in doc["families"]["markets"] for o in m["outcomes"] for k in o}
    return frozenset((found | set(match.CANDIDATE_NUMBERS) | {"gap", "price_at"}) - {"market", "selection", "line"})


MODEL_AND_PRICE_KEYS: Final = _model_and_price_keys()


def test_the_match_of_these_tests_fires_every_rule_that_has_an_input_today() -> None:
    """The fixture is what makes the other tests worth something: every channel of a finding is open, nothing is cut and nothing blocks."""
    assert {c.code for c in CONTRA0} == {"C01", "C02", "C03", "C04", "C06", "C07"}
    assert contra.coverage(PACKAGE.document, naming=NAMING)["C05"] == contra.INPUT_MISSING, "no builder writes the referee's multiplier"
    assert not any(c.code == "C08" for c in CONTRA0), "C08 needs assessments: none before anyone has spoken"
    assert not PACKAGE.blocking and not PACKAGE.dropped and all(s.fits and not s.trimmed for s in SLICES.values())
    assert {n.family for n in NAMING.named} == set(GOALS_RESULT) | set(COUNTS) and not NAMING.left_out
    assert {"p_model", "p_market", "odds", "edge", "ev", "p_fair", "best_odds", "p", "p_lo", "p_hi", "gap"} <= MODEL_AND_PRICE_KEYS


# == 1. what each voice reads (its porción) ===================================================================================================

@pytest.mark.parametrize("task", list(REQUESTS))
def test_the_first_thing_an_agent_reads_is_its_own_slice_and_no_other_block_of_the_package(task: str) -> None:
    first, _ = message(REQUESTS[task])
    name = SLICE_OF[task]
    assert first == SLICES[name].document and first["slice"] == name and first["contract"] == MCP
    assert set(first) - FRAME <= set(SLICE_BLOCKS[name]), sorted(set(first) - FRAME - set(SLICE_BLOCKS[name]))


def test_each_slice_holds_only_the_shared_blocks_and_the_kinds_of_evidence_of_its_porcion() -> None:
    shared = {n: s.document["shared"] for n, s in SLICES.items()}
    kinds = {n: {e["kind"] for e in s.document["evidence"]} for n, s in SLICES.items()}
    assert set(shared["player"]) <= set(pk.PLAYER_BLOCKS), "who plays, and nothing else of what both sides share"
    assert set(shared["stats"]) <= set(pk.LIGHT_BLOCKS) | {"referee", "teams", "players", "stats"}
    assert not keys_in(SLICES["match"].document) & pk.COUNT_WORDS and not keys_in(SLICES["player"].document) & pk.COUNT_WORDS
    assert kinds["player"] <= PLAYER_KINDS and not kinds["stats"] & STATS_EXCLUDED_KINDS
    assert kinds["match"] == {e["kind"] for e in PACKAGE.document["evidence"]}, "the Match Agent reads the whole index"


NAME_OF_A_CANDIDATE: Final = frozenset({"candidate", "family", "market", "selection", "line"})
NUMBERS_OF_A_CANDIDATE: Final = frozenset({*match.CANDIDATE_NUMBERS, "model", "n_bookmakers", "price_at"})
ASKED: Final[dict[str, tuple[tuple[str, ...], frozenset[str], Callable[[common.Naming], tuple[str, ...]]]]] = {
    "match_evaluation": (GOALS_RESULT, NAME_OF_A_CANDIDATE | NUMBERS_OF_A_CANDIDATE, match.asked_keys),
    "stats": (COUNTS, NAME_OF_A_CANDIDATE | NUMBERS_OF_A_CANDIDATE, stats.asked_keys),
    "player": (GOALS_RESULT, NAME_OF_A_CANDIDATE, player.asked_keys),
}
"""Per evaluation: the families it is asked about, what it may read of a candidate, and the names it is asked about. The Player Agent reads the
name of a candidate and not one number of it."""


@pytest.mark.parametrize("task", list(ASKED))
def test_an_agent_is_asked_only_about_its_families_and_reads_of_a_candidate_only_what_it_may(task: str) -> None:
    families, fields, keys = ASKED[task]
    _, second = message(REQUESTS[task])
    asked = second["candidates"]
    assert [c["candidate"] for c in asked] == list(keys(NAMING)) and asked
    assert {c["family"] for c in asked} <= set(families)
    assert all(set(c) <= fields for c in asked), [sorted(set(c) - fields) for c in asked]


SECOND_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "match_context": prompts.SECOND_OBJECT_KEYS["CONTEXT"], "match_evaluation": prompts.SECOND_OBJECT_KEYS["EVALUATION"],
    "stats": prompts.STATS_SECOND_OBJECT_KEYS, "player": prompts.PLAYER_SECOND_OBJECT_KEYS}


@pytest.mark.parametrize("task", list(REQUESTS))
def test_what_is_asked_now_has_only_the_keys_the_agents_prompt_describes(task: str) -> None:
    _, second = message(REQUESTS[task])
    assert set(second) <= set(SECOND_KEYS[task]), sorted(set(second) - set(SECOND_KEYS[task]))
    if task == "match_context":
        assert "candidates" not in second and "contradictions" not in second, "the context reading has no candidate and no finding"


def test_no_datum_of_corners_or_cards_reaches_the_match_agent_anywhere_in_what_it_reads() -> None:
    for task in ("match_context", "match_evaluation"):
        read = list(message(REQUESTS[task]))
        assert not keys_in(read) & pk.COUNT_WORDS, (task, sorted(keys_in(read) & pk.COUNT_WORDS))
        assert not [s for s in strings_in(read) if s.upper().startswith(("CORNERS", "CARDS"))], task


def test_no_datum_of_goals_or_result_reaches_the_statistics_agent_anywhere_in_what_it_reads() -> None:
    read = list(message(REQUESTS["stats"]))
    markets, families = values_under(read, "market"), values_under(read, "family")
    assert markets and all(family_of(m) in COUNTS for m in markets), markets
    assert families and set(families) <= set(COUNTS), families
    assert not set(strings_in(read)) & set(GOALS_RESULT)


def test_the_slice_and_the_candidates_of_the_player_agent_carry_no_probability_price_or_value() -> None:
    first, second = message(REQUESTS["player"])
    rest = {k: v for k, v in second.items() if k != "contradictions"}
    assert not keys_in([first, rest]) & MODEL_AND_PRICE_KEYS, sorted(keys_in([first, rest]) & MODEL_AND_PRICE_KEYS)


@violation("V1")
def test_no_finding_hands_the_player_agent_a_probability_price_or_value() -> None:
    _, second = message(REQUESTS["player"])
    found = sorted(keys_in(second.get("contradictions", [])) & MODEL_AND_PRICE_KEYS)
    assert not found, found


ORIGINAL: Final[dict[tuple[str, str, tuple[tuple[str, str], ...]], Contradiction]] = {(c.code, c.subject, c.detail): c for c in CONTRA0}
RULES_WITH_INPUT: Final = ("C01", "C02", "C03", "C04", "C06", "C07")
EVALUATION_OF: Final = {"match": "match_evaluation", "stats": "stats", "player": "player"}
KNOWN: Final[dict[tuple[str, str], str]] = {("player", "C03"): "V2", ("player", "C04"): "V2", ("player", "C06"): "V1", ("player", "C07"): "V2",
                                            ("stats", "C07"): "V3"}


def resting_outside(agent: str, code: str) -> list[str]:
    """The findings of ``code`` the agent is handed that rest on something its slice does not have: a reference of the finding (``contra-v1``
    cites the blocks it read and the evidence that fired it) that the slice cannot cite - or, for C06, the model's and the market's probability of
    a candidate the agent is not given them for."""
    first, second = message(REQUESTS[EVALUATION_OF[agent]])
    ids, paths = common.known_refs(first)
    priced = {c["candidate"] for c in second["candidates"] if {"p_model", "p_market"} <= set(c)}
    outside: list[str] = []
    for f in second.get("contradictions", []):
        if f["code"] != code:
            continue
        found = ORIGINAL.get((f["code"], f["subject"], tuple(sorted(f.get("detail", {}).items()))))
        assert found is not None, f"{f['code']} {f['subject']}: a finding the detector did not write over the package"
        rests_on_more = not set(f["candidates"]) <= priced if code == "C06" else bool(check_refs(found.refs, evidence_ids=ids, paths=paths))
        if rests_on_more:
            outside.append(f"{code} {found.subject}")
    return outside


@pytest.mark.parametrize(("agent", "code"), [
    pytest.param(agent, code, marks=violation(KNOWN[(agent, code)]) if (agent, code) in KNOWN else (), id=f"{agent}-{code}")
    for agent in EVALUATION_OF for code in RULES_WITH_INPUT])
def test_a_finding_reaches_an_agent_only_if_what_it_rests_on_is_in_its_porcion(agent: str, code: str) -> None:
    outside = resting_outside(agent, code)
    assert not outside, outside


def test_every_voice_reads_one_package_as_of_one_moment() -> None:
    assert {s.package_hash for s in SLICES.values()} == {PACKAGE.hash} and {s.known_at for s in SLICES.values()} == {PACKAGE.known_at} == {AT}
    for task, request in REQUESTS.items():
        first, second = message(request)
        assert first["known_at"] == second["now"] == AT.isoformat() and second["package_age_minutes"] == 0, task
    view = council.council_view(SLICES["match"], NAMING, assessments=(), contradictions=CONTRA0)
    assert view.document["known_at"] == AT.isoformat()

    def a_rating_from_later(c: dict[str, Any]) -> None:
        hostile(c)
        c["elo"]["as_of"] = iso(timedelta(minutes=1))

    def a_page_read_later(c: dict[str, Any]) -> None:
        hostile(c)
        c["evidence"].append(evidence(13, retrieved=timedelta(minutes=1)))

    with pytest.raises(pk.PackageLeakError):
        pk.package_from_packet(packet(a_rating_from_later), pass_kind="pre", families=copy.deepcopy(FAMILIES), model_code=CODE)
    unseen = pk.package_from_packet(packet(a_page_read_later), pass_kind="pre", families=copy.deepcopy(FAMILIES), model_code=CODE)
    assert 13 not in {e["id"] for e in unseen.document["evidence"]} and unseen.dropped == {"evidence_retrieved_after_the_moment": 1}


# == 2. the positions go to the judge, and only to the judge ==================================================================================

def answer(agent: str, mode: str, stance: str = "NEUTRAL", *, direction: str = "AWAY", research_ask: bool = False) -> dict[str, Any]:
    """A well-formed answer that stands, citing only what every slice has (``P:shared.absences``)."""
    if agent == "player":
        return {"contract": PLAYER_ASSESSMENT, "agent": "player", "mode": "EVALUATION", "data_quality": "GOOD",
                "signals": [{"code": "ABSENCES", "direction": direction, "refs": ["P:shared.absences"]}],
                "candidates": [{"candidate": k, "stance": stance, "drivers": ["ABSENCES"], "risks": [], "refs": ["P:shared.absences"]}
                               for k in player.asked_keys(NAMING)]}
    keys = () if mode == "CONTEXT" else match.asked_keys(NAMING) if agent == "match" else stats.asked_keys(NAMING)
    return {"contract": ASSESSMENT, "agent": agent, "mode": mode, "data_quality": "GOOD",
            "signals": [{"code": "ABSENCES", "direction": direction, "strength": "HIGH", "refs": ["P:shared.absences"]}],
            "candidates": [{"candidate": k, "stance": stance, "drivers": ["ABSENCES"], "risks": [], "refs": ["P:shared.absences"]} for k in keys],
            "research": [{"topic": "availability", "side": "home", "refs": ["P:shared.absences"]}] if research_ask else []}


def assessed(match_stance: str, stats_stance: str, player_stance: str) -> list[Assessed]:
    """The four assessments of a round, read by the agents' own readers as the orchestrator reads them."""
    readings: list[Assessed | None] = [
        match.assessed(match.read(answer("match", "CONTEXT"), mode="CONTEXT", slice_=SLICES["match"]), mode="CONTEXT"),
        match.assessed(match.read(answer("match", "EVALUATION", match_stance), mode="EVALUATION", slice_=SLICES["match"], naming=NAMING),
                       mode="EVALUATION"),
        stats.assessed(stats.read(answer("stats", "EVALUATION", stats_stance), slice_=SLICES["stats"], naming=NAMING)),
        player.assessed(player.read(answer("player", "EVALUATION", player_stance), slice_=SLICES["player"], naming=NAMING))]
    out = [a for a in readings if a is not None]
    assert sorted(a.label for a in out) == list(LABELS), "every answer stands"
    return out


def test_no_request_of_an_agent_has_a_door_for_what_another_agent_said() -> None:
    for builder in (match.context_request, match.evaluation_request, stats.evaluation_request, player.evaluation_request):
        assert set(inspect.signature(builder).parameters) <= {"slice_", "naming", "at", "contradictions"}, builder.__qualname__
    assert "assessments" in inspect.signature(council.council_view).parameters, "the judge is the one reader of the positions"


Round = tuple[list[tuple[str, str, JsonRequest]], tuple[Contradiction, ...], Any]


def round_of(monkeypatch: pytest.MonkeyPatch, *, context: str, research_ask: bool, stances: tuple[str, str, str]) -> Round:
    """One real round of the orchestrator (``_Runner.match_round``: the Match Agent's two tasks, the Statistics Agent, the Player Agent and
    the detector with the assessments), every agent on, with the model's answers scripted. Returns what each task was asked, the findings
    the judge is handed and the pass."""
    runner = orchestrator._Runner(object(), AiSettings(agents=("match", "council", "stats", "player")), at=AT, limit=1,  # type: ignore[arg-type]
                                  max_seconds=60.0, provider=None, transport=None, ledger=None, slots=runtime.Slots(), circuit=runtime.Circuit(),
                                  monotonic=lambda: 0.0, sleep=lambda s: None)
    monkeypatch.setattr(runner, "room", lambda: orchestrator.Room(True, D(5), D(10), "ok"))
    monkeypatch.setattr(runner, "day", lambda room: router.Day(allocation_usd=D(10), scope="shadow"))
    script = {("match", "context"): answer("match", "CONTEXT", direction=context, research_ask=research_ask),
              ("match", "evaluation"): answer("match", "EVALUATION", stances[0]),
              ("stats", "evaluation"): answer("stats", "EVALUATION", stances[1]),
              ("player", "evaluation"): answer("player", "EVALUATION", stances[2])}
    sent: list[tuple[str, str, JsonRequest]] = []

    def ask(p: Any, *, identity: Any, task_kind: str, request: JsonRequest, decision: Any, model: str, agent: str, **_: Any) -> orchestrator.Asked:
        sent.append((agent, task_kind, request))
        return orchestrator.Asked(identity=identity, task_kind=task_kind, est=D(0), decision=decision, started=AT, finished=AT,
                                  data=copy.deepcopy(script[(agent, task_kind)]), model=model)

    monkeypatch.setattr(runner, "ask", ask)
    work = Work(fixture_id=FIXTURE, pass_kind="pre", packet_id=1, known_at=AT, kickoff_at=KICKOFF, passed_at=AT)
    p = orchestrator._Pass(work=work, engines=("ma-v1",), package=PACKAGE, slice_=SLICES["match"], candidates=Reviewed(CANDIDATES), naming=NAMING,
                           packet=PACKET, started=AT, slices=dict(SLICES), stats_on=True, stats_slice=SLICES["stats"], counts=None, player_on=True,
                           player_slice=SLICES["player"], slice_set=SLICES_V2)
    return sent, runner.match_round(p, CONTRA0), p


def test_in_a_round_each_agent_is_asked_the_same_question_whatever_the_others_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three rounds over the same match in which the agents say different things - agreeing, the Player against the Match Agent, the Match
    Agent against the others - and a research asked for. Every agent is asked exactly the question it is asked before anyone speaks; only the
    judge's findings move (C08), and the judge reads every position."""
    rounds = {"agree": round_of(monkeypatch, context="AWAY", research_ask=False, stances=("SUPPORT", "SUPPORT", "SUPPORT")),
              "player_against": round_of(monkeypatch, context="HOME", research_ask=True, stances=("SUPPORT", "REJECT_SIGNAL", "CONCERN")),
              "match_against": round_of(monkeypatch, context="NEUTRAL", research_ask=False, stances=("REJECT_SIGNAL", "NEUTRAL", "SUPPORT"))}
    for name, (sent, contra1, p) in rounds.items():
        assert [(a, t) for a, t, _ in sent] == list(TASK_OF), f"{name}: one task per agent and mode, no search and no second round"
        assert sorted(a.label for a in p.assessed) == list(LABELS), f"{name}: every answer stood, so any of them could have leaked"
        for agent, task, request in sent:
            assert request.user == REQUESTS[TASK_OF[(agent, task)]].user, f"{name}: {agent} {task} was asked another question"
            assert not [label for label in LABELS if label in request.user] and '"C08"' not in request.user, (name, agent, task)
        view = council.council_view(p.slice_, p.naming, assessments=p.assessed, contradictions=contra1)
        assert view.assessments == LABELS, f"{name}: the judge reads every position"
        c08 = [c for c in view.document["contradictions"] if c["code"] == "C08"]
        assert bool(c08) == (name != "agree"), f"{name}: the disagreement reaches the judge, and only it"
    assert rounds["player_against"][2].ignored_asks == ["availability"], "the research a model asks for is not served in the shadow"


ORCHESTRATOR: Final = ast.parse(Path(orchestrator.__file__).read_text(encoding="utf-8"))
AGENT_MODULES: Final = frozenset({"match", "stats", "player"})


def test_every_path_of_the_orchestrator_hands_the_agents_the_findings_computed_without_assessments() -> None:
    """The real-time round is run above; the Batch calendar (``batch_stages``, ``resume``, ``plan``) is held here, on the source: ``contra0`` is
    bound once, to the detector with no assessment; every request of an agent is built with ``contra0`` or with no finding (the context); and every
    method that takes ``contra0`` is handed ``contra0`` and nothing else."""
    bound = [n.value for n in ast.walk(ORCHESTRATOR) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "contra0"
                                                                                            for t in n.targets)]
    assert bound, "the orchestrator no longer names the findings it hands the agents"
    for value in bound:
        assert isinstance(value, ast.Call) and ast.unparse(value.func) == "contra.detect", ast.unparse(value)
        assessments = next((k.value for k in value.keywords if k.arg == "assessments"), None)
        assert isinstance(assessments, ast.Tuple) and not assessments.elts, ast.unparse(value)
    calls = [n for n in ast.walk(ORCHESTRATOR) if isinstance(n, ast.Call)]
    requests = [c for c in calls if isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and c.func.value.id in AGENT_MODULES
                and c.func.attr.endswith("_request")]
    assert requests
    for call in requests:
        given = {k.arg: k.value for k in call.keywords}
        if "contradictions" in given:
            assert isinstance(given["contradictions"], ast.Name) and given["contradictions"].id == "contra0", ast.unparse(call)
        else:
            assert ast.unparse(call.func) == "match.context_request", ast.unparse(call)
    takes = {f.name: [a.arg for a in f.args.args][1:] for f in ast.walk(ORCHESTRATOR) if isinstance(f, ast.FunctionDef)
             and "contra0" in [a.arg for a in f.args.args]}
    assert {"batch_stages", "match_round", "stats_task", "player_task"} <= set(takes)
    for call in calls:
        f = call.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self" and f.attr in takes):
            continue
        at = takes[f.attr].index("contra0")
        arg = call.args[at] if at < len(call.args) else next((k.value for k in call.keywords if k.arg == "contra0"), None)
        assert isinstance(arg, ast.Name) and arg.id == "contra0", ast.unparse(call)


ASSESSED: Final = assessed("SUPPORT", "REJECT_SIGNAL", "CONCERN")
CONTRA1: Final = contra.detect(PACKAGE.document, naming=NAMING, assessments=ASSESSED, at=AT)
VIEW: Final = council.council_view(SLICES["match"], NAMING, assessments=ASSESSED, contradictions=CONTRA1)
_URL: Final = re.compile(r"(?:https?|ftp)://|www\.", re.IGNORECASE)


def test_the_judge_reads_every_position_and_every_finding_and_nothing_but_its_view() -> None:
    doc = VIEW.document
    assert VIEW.fits and VIEW.assessments == LABELS and [a["label"] for a in doc["assessments"]] == list(LABELS)
    assert {c["code"] for c in doc["contradictions"]} == {c.code for c in CONTRA1} >= {"C08"}
    assert set(doc) <= {"view", "fixture_id", "known_at", "pass", "round", "header", "candidates", "models", "market", "assessments",
                        "contradictions", "shared", "evidence", "missing", "blocking", "omitted"}
    assert set(doc["candidates"]) == set(NAMING.keys), "the numbers of every candidate, the server's, read only"
    assert not [e for e in doc["evidence"] if "domain" in e or "url" in e] and not [s for s in strings_in(doc) if _URL.search(s)]
    request = council.council_request(VIEW, NAMING, level="complex", at=AT)
    sent = json.loads(request.user)
    assert set(sent) == {"view", "ask", "now", "note"} and set(sent["ask"]) == {"candidates"} and sent["view"] == doc


# == 3. the border between code and AI =========================================================================================================

def number_fields(schema: Any, where: str = "answer") -> list[str]:
    """Where a wire schema would take a number."""
    found: list[str] = []
    if isinstance(schema, dict):
        kind = schema.get("type")
        if kind in ("number", "integer") or (isinstance(kind, list) and {"number", "integer"} & set(kind)):
            found.append(where)
        for k, v in schema.items():
            found += number_fields(v, f"{where}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            found += number_fields(v, f"{where}[{i}]")
    return found


@pytest.mark.parametrize("contract", [ASSESSMENT, PLAYER_ASSESSMENT, COUNCIL])
def test_no_output_of_the_deliberation_has_a_field_for_a_number_a_price_a_query_or_an_address(contract: str) -> None:
    wire = schema_of(contract)
    assert not forbidden_names(wire) and not number_fields(wire)


def verdicts(**c1: Any) -> dict[str, Any]:
    """A cd-v1 answer that abstains on every candidate, with what the test puts in c1's verdict."""
    rows = [{"candidate": k, "verdict": "ABSTAIN", "confidence": "LOW", "drivers": [], "risks": [], "refs": []} for k in NAMING.keys]
    rows[0] |= c1
    return {"contract": COUNCIL, "verdicts": rows, "research": []}


@pytest.mark.parametrize("bad", [
    pytest.param(lambda a: a["verdicts"][0].update(p_model=0.61), id="a probability in a verdict"),
    pytest.param(lambda a: a["verdicts"][0].update(probability=0.61), id="a probability by another name"),
    pytest.param(lambda a: a["verdicts"][0].update(odds=2.4), id="a price"),
    pytest.param(lambda a: a["verdicts"][0].update(confidence=0.9), id="a confidence as a number"),
    pytest.param(lambda a: a["verdicts"][0].update(verdict="PROMOTE"), id="a word that would raise"),
    pytest.param(lambda a: a.update(threshold={"ev_min": 0.0}), id="a threshold"),
    pytest.param(lambda a: a.update(p_market=0.4), id="a market probability"),
])
def test_the_council_cannot_write_a_probability_a_price_a_threshold_or_a_word_that_raises(bad: Callable[[dict[str, Any]], None]) -> None:
    good = council.read(verdicts(), view=VIEW, naming=NAMING)
    assert good.status == "ok", good.problems
    tampered = verdicts()
    bad(tampered)
    reading = council.read(tampered, view=VIEW, naming=NAMING)
    assert reading.status == "invalid_output" and reading.council is None and reading.problems
    assert all(p.startswith("schema:") for p in reading.problems), reading.problems


def atoms(annotation: Any) -> Iterator[Any]:
    """The plain types an annotation is made of (a ``Literal`` is its values' type)."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        yield from {type(v) for v in typing.get_args(annotation)}
        return
    args = [a for a in typing.get_args(annotation) if a is not Ellipsis]
    if origin is not None and args:
        for a in args:
            yield from atoms(a)
        return
    yield annotation


def test_the_typed_state_of_evidence_carries_no_number_into_a_decision() -> None:
    """``ctx-adj-v1`` is what a decision may read of the deliberation: words, codes and the ids of the rows and evidence it rests on - never a
    probability, a weight, a score or a threshold (the protocol's score and weights stay in its ``Baseline``, beside the adjustment)."""
    for cls in (ctx.ContextAdjustment, ctx.Source, ctx.Dissent):
        for name, annotation in typing.get_type_hints(cls).items():
            kinds = set(atoms(annotation)) - {type(None)}
            assert not kinds & {float, Decimal, complex}, (cls.__name__, name, kinds)
            if int in kinds:
                assert name.endswith(("_id", "_ids")), (cls.__name__, name)
    assert typing.get_type_hints(engine.Decision2)["adjustment"] == str | None, "decision-v2 keeps the word it was given, and only the word"


def test_decision_v2_reads_of_the_council_only_its_word() -> None:
    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    assess = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "assess")
    read = {n.attr for n in ast.walk(assess) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "adjustment"}
    assert read == {"verdict", "severity"}, read
    handed_on = [ast.unparse(c) for c in ast.walk(assess) if isinstance(c, ast.Call)
                 for a in (*c.args, *(k.value for k in c.keywords)) if isinstance(a, ast.Name) and a.id == "adjustment"]
    assert not handed_on, handed_on


# == 4. the state of evidence can only lower ===================================================================================================

def test_no_word_of_the_council_points_above_where_a_selection_already_is() -> None:
    assert set(engine.ADJ_EFFECT) == set(ctx.EFFECT) == set(ctx.VERDICTS)
    assert engine.ADJ_EFFECT["CONFIRMA"] is None and engine.ADJ_EFFECT["SIN_COUNCIL"] is None, "a confirmation never promotes"
    assert all(t is None or engine.RANK[t] < engine.RANK["RECOMMENDED"] for t in engine.ADJ_EFFECT.values())
    for verdict in ctx.VERDICTS:
        adjustment = ctx.ContextAdjustment(verdict, "media", ctx.Source(engine="ma-v1"), DECIDED_AT)
        for state in (*decision.RANK, *decision.APPROVED):
            after = ctx.proposed_effect(adjustment, state)
            assert decision.RANK[ctx.base_state(after)] <= decision.RANK[ctx.base_state(state)], (verdict, state, after)


@pytest.mark.parametrize("verdict", ctx.VERDICTS)
def test_the_context_stage_of_decision_v2_can_only_lower_a_state(verdict: ctx.AdjVerdict) -> None:
    """Over a grid of worlds and selections (``test_decision_v2_engine.cases``: every stage failing in turn, a review and the hard rules of the
    context included): with the Council's word the state is never above the state without it, no number moves, the only new code is the
    Council's own, a word with no effect leaves everything as it was, and the severity is words - it never moves a state."""
    target = engine.ADJ_EFFECT[verdict]
    for c in cases(200, seed=4600 + ctx.VERDICTS.index(verdict)):
        w, p = build(c)
        base = engine.decide(w, core({MODEL: p}))
        reached: set[str] = set()
        for severity in ctx.SEVERITIES:
            d = engine.decide(w, core({MODEL: p}), adjustment=ctx.ContextAdjustment(verdict, severity, ctx.Source(engine="ma-v1"), DECIDED_AT))
            assert engine.RANK[d.state] <= engine.RANK[base.state], (verdict, severity, c)
            assert (d.prediction, d.price, d.value) == (base.prediction, base.price, base.value)
            assert set(d.codes) - set(base.codes) <= {engine.council_code(verdict)}, (verdict, c)
            if target is None:
                assert (d.state, d.codes) == (base.state, base.codes), (verdict, c)
            reached.add(d.state)
        assert len(reached) == 1, (verdict, c, reached)


def test_no_pair_of_words_of_the_council_lifts_any_selection_of_a_match() -> None:
    """Two selections of one match that compete in the correlation: whatever the Council says of each - every pair of words, at once - neither
    ends above where it was without the Council."""
    k2: decision.Key = (77, "OU", "Over", D("2.50"))
    w = two_markets()
    a, b = pick(), pick(odds=2.1, p=0.6, p_fair=0.47, market="OU", selection="Over") | {"line": D("2.5")}
    candidates = [core({MODEL: a}), core({MODEL: b}, k2)]
    base = {d.key: d.state for d in engine.decide_all(w, candidates)}
    assert sorted(base.values()) == ["CAUTION", "RECOMMENDED"]
    for first in ctx.VERDICTS:
        for second in ctx.VERDICTS:
            words = {KEY: ctx.ContextAdjustment(first, "media", ctx.Source(engine="ma-v1"), DECIDED_AT),
                     k2: ctx.ContextAdjustment(second, "media", ctx.Source(engine="ma-v1"), DECIDED_AT)}
            held = {d.key: d.state for d in engine.decide_all(w, candidates, adjustments=words)}
            assert all(engine.RANK[held[k]] <= engine.RANK[base[k]] for k in base), (first, second, held)


# == 5. one targeted search at most ============================================================================================================

def case(key: str) -> research.Case:
    """A selection worth a search (an expected value over the decision layer's minimum) with a material disagreement between two voices
    whose stances rest on three topics of the catalogue."""
    sel = voices.Selection(key, "1X2", "1X2", "HOME", D(0), p_model=D("0.60"), p_market=D("0.45"), edge=D("0.15"), ev=D("0.30"))
    for_ = voices.Position("match", match.VERSION, "match_evaluation", key, "SUPPORT", ("ABSENCES",), (), ("P:shared.absences",), 1, D(1))
    against = voices.Position("stats", stats.VERSION, "stats_evaluation", key, "CONCERN", ("NEWS", "STAKES"), (), ("E:1",), 2, D(1))
    return research.Case(sel, voices.detect(sel, (for_, against), voices.Market.unknown()), (for_, against))


def test_the_deliberation_asks_for_one_targeted_search_at_most() -> None:
    ask = {"topic": "availability", "side": "home", "refs": ["P:shared.absences"]}
    assert not parse(ASSESSMENT, answer("match", "CONTEXT") | {"research": [ask, ask | {"topic": "preview"}]}).ok
    assert not parse(COUNCIL, verdicts() | {"research": [ask, ask | {"topic": "preview"}]}).ok
    assert "research" not in PlayerAssessmentOut.model_fields, "the Player Agent never asks for one"
    reading = stats.read(answer("stats", "EVALUATION") | {"research": [ask]}, slice_=SLICES["stats"], naming=NAMING)
    assert "research_not_allowed" in reading.problems, "nor does the Statistics Agent"
    every = [case(f"c{i}") for i in range(1, 6)]
    assert all(len(c.selection.key) and research.judge(c).warranted and len(research.topics_of(c)) == 3 for c in every)
    one = research.decide(every, minutes_to_kickoff=600)
    assert one.requested and 0 < len(one.topics) <= research.TOPICS_MAX == 2 and set(one.topics) <= set(research.TOPICS)
    assert not research.decide(every, minutes_to_kickoff=research.MIN_MINUTES - 1).requested, "a search that cannot be served is not asked"
    assert router.council_calls(families_with_candidates=2, research_admitted=False) == 1
    assert router.council_calls(families_with_candidates=2, research_admitted=True) == 2 == router.PARAMS["council_calls_per_match_and_pass"]
    with pytest.raises(ValueError):
        council.council_view(SLICES["match"], NAMING, assessments=(), contradictions=CONTRA0, round_=3)


# == 6. the guide says what the code does ======================================================================================================

GUIDE: Final = Path(__file__).resolve().parents[2] / "docs" / "owner" / "IA_046_CONTRATO_DELIBERACION.md"


def guide() -> str:
    if not GUIDE.is_file():
        pytest.skip(f"no {GUIDE.name} next to the code")
    return GUIDE.read_text(encoding="utf-8")


def section(text: str, number: int) -> str:
    found = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", text, flags=re.S | re.M)
    assert found, f"section {number} is missing from the guide"
    return found.group(0)


def es(number: Any) -> str:
    """A number as the guide writes it: a decimal comma, thousands with a dot."""
    value = Decimal(str(number))
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", ".")
    return str(value).replace(".", ",")


def test_the_guide_names_the_versions_the_code_runs() -> None:
    text = guide()
    for version in (match.VERSION, stats.VERSION, player.VERSION, council.VERSION, council.VIEW_VERSION, PROTOCOL_VERSION, voices.VERSION,
                    research.VERSION, weights.VERSION, ctx.VERSION, engine.VERSION, contra.VERSION, router.VERSION, MCP, ASSESSMENT,
                    PLAYER_ASSESSMENT, COUNCIL, pk.VERSION):
        assert f"`{version}`" in text, version


def test_the_guide_says_which_blocks_each_voice_reads_as_the_code_cuts_them() -> None:
    lines = section(guide(), 2).splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("| Voz |"))
    columns = [c.strip() for c in lines[header].strip().strip("|").split("|")]
    reads = columns.index("Lee")
    rows = {}
    for line in lines[header + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows[cells[0].replace("**", "")] = cells[reads]
    for voice, name in {"Partido": "match", "Estadísticas": "stats", "Jugadores": "player"}.items():
        cell = next(v for k, v in rows.items() if k.startswith(voice))
        assert {b for b in re.findall(r"`([a-z_]+)`", cell) if b in BLOCKS} == set(SLICE_BLOCKS[name]), (voice, cell)


def test_the_guide_states_the_thresholds_of_the_code() -> None:
    text = guide()
    for said in (es(router.PARAMS["e6_gap"]), f"{router.PARAMS['research_min_minutes']} min", f"{router.PARAMS['opus_calls']['shadow']} llamadas",
                 f"{research.TOPICS_MAX} temas", es(council.VIEW_CAP), es(pk.CAPS["player"]), es(weights.MIN_WEIGHT), es(weights.MAX_WEIGHT),
                 es(router.PARAMS["e2_hours_to_kickoff"]) + " h"):
        assert said in text, said


def test_the_guide_declares_exactly_the_violations_these_tests_mark() -> None:
    declared = set(re.findall(r"\*\*(V\d+)\*\*", section(guide(), 10)))
    assert declared == set(VIOLATIONS) == MARKED, (sorted(declared), sorted(VIOLATIONS), sorted(MARKED))

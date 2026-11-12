"""The replay bank (IA-047) without a database: a pass of the shadow made the way the orchestrator makes it - the package, the
slices, the names, the findings, the answers read by each agent's own reader, the Council's view over what stood - is derived
again by ``fbi.ai.replay.bank`` and every run of it must be admitted with the very request it was sent; any difference in what
it was made of must exclude the run with its closed code. The pieces that read the database are tested on PostgreSQL
(``tests/integration/test_replay_bank_db.py``)."""

from __future__ import annotations

import copy
import dataclasses
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import contra
from fbi.ai import package as pk
from fbi.ai.agents import common, council, match, stats
from fbi.ai.agents.registry import REGISTRY
from fbi.ai.contracts.mcp import SLICES_V1
from fbi.ai.idempotency import TaskIdentity
from fbi.ai.orchestrator_store import REVIEWED_SQL
from fbi.ai.providers.base import JsonRequest
from fbi.ai.replay import bank
from fbi.ai.review import Candidate

from .synthetic_packet import AT, FAMILIES, FIXTURE, KICKOFF, packet

D = Decimal
CODE = "mc9a7bec97ca"
PACKET_ID = 77
STARTED = AT + timedelta(minutes=3)


def candidate(market: str, selection: str, line: str = "0", *, p: str = "0.52", q: str = "0.48", ev: str = "0.05") -> Candidate:
    return Candidate(fixture_id=FIXTURE, market_key=market, selection=selection, line=D(line), kickoff_at=KICKOFF, p_model=D(p),
                     p_low=D(p) - D("0.04"), p_market=D(q), odds=D("2.10"), ev=D(ev), bookmaker_id=3, bookmaker="Book")


REVIEWED = (candidate("1X2", "HOME"), candidate("OU", "OVER", "2.5"), candidate("BTTS", "YES"))
"""What production reviewed in the pass (goals and result)."""
COUNTS = (candidate("CORNERS_OU", "OVER", "9.5"), candidate("CARDS_OU", "OVER", "4.5"))
"""What the families decided (corners and cards), with the Statistics Agent on."""
PACKAGE = pk.package_from_packet(packet(), pass_kind="pre", families=copy.deepcopy(FAMILIES), model_code=CODE, packet_id=PACKET_ID)
SLICES = pk.slices_of(PACKAGE)
NAMING = common.name_with_counts((*REVIEWED, *COUNTS))
AT_PASS = SLICES["match"].known_at


def refs_of(slice_: pk.Slice) -> list[str]:
    return [r for r in common.citable_refs(slice_.document) if r.startswith("P:")][:1]


def assessment(agent: str, mode: str, keys: tuple[str, ...], slice_: pk.Slice) -> dict[str, Any]:
    """A valid ``aa-v1`` answer: one signal and, in an evaluation, a SUPPORT for the first candidate and NEUTRAL for the rest."""
    refs = refs_of(slice_)
    cands = [{"candidate": k, "stance": "SUPPORT" if i == 0 and agent == "match" else "NEUTRAL",
              "drivers": ["FORM"] if i == 0 and agent == "match" else [], "risks": [], "refs": refs if i == 0 and agent == "match" else []}
             for i, k in enumerate(keys)]
    return {"contract": "aa-v1", "agent": agent, "mode": mode, "data_quality": "GOOD",
            "signals": [{"code": "FORM" if agent == "match" else "RATE", "direction": "HOME" if agent == "match" else "OVER",
                         "strength": "MEDIUM", "refs": refs}],
            "candidates": cands if mode == "EVALUATION" else [], "research": []}


def verdicts(naming: common.Naming, view: council.CouncilView, *, first: str = "APPROVE") -> dict[str, Any]:
    """A valid ``cd-v1`` answer: the first candidate approved on the Match Agent's evaluation (or, in a view without it, on the
    candidates' block), the rest ABSTAIN."""
    ref = "A:match_evaluation" if "match_evaluation" in view.assessments else "P:candidates"
    return {"contract": "cd-v1", "research": [], "verdicts": [
        {"candidate": k, "verdict": first if i == 0 else "ABSTAIN", "confidence": "MEDIUM" if i == 0 else "LOW",
         "drivers": ["FORM"] if i == 0 else [], "risks": [], "refs": [ref] if i == 0 else []}
        for i, k in enumerate(naming.keys)]}


@dataclasses.dataclass(frozen=True)
class Shadow:
    """One pass as the orchestrator made it, by its own pieces and in its own order (``_Runner.shadow``)."""

    requests: dict[str, JsonRequest]
    identities: dict[str, TaskIdentity]
    hashes: dict[str, str]
    outputs: dict[str, dict[str, Any]]
    views: dict[str, council.CouncilView]


def shadow_pass(naming: common.Naming = NAMING, *, council_first: str = "APPROVE") -> Shadow:
    m, s = SLICES["match"], SLICES["stats"]
    contra0 = contra.detect(PACKAGE.document, naming=naming, assessments=(), at=AT_PASS)
    req: dict[str, JsonRequest] = {
        "match/context": match.context_request(m, at=AT_PASS),
        "match/evaluation": match.evaluation_request(m, naming, at=AT_PASS, contradictions=contra0),
        "stats/evaluation": stats.evaluation_request(s, naming, at=AT_PASS, contradictions=contra0)}
    readings = {
        "match/context": match.read(assessment("match", "CONTEXT", (), m), mode="CONTEXT", slice_=m),
        "match/evaluation": match.read(assessment("match", "EVALUATION", match.asked_keys(naming), m), mode="EVALUATION", slice_=m,
                                       naming=naming),
        "stats/evaluation": stats.read(assessment("stats", "EVALUATION", stats.asked_keys(naming), s), slice_=s, naming=naming)}
    assert all(r.ok for r in readings.values()), {k: r.problems for k, r in readings.items()}
    assessed = [match.assessed(readings["match/context"], mode="CONTEXT"), match.assessed(readings["match/evaluation"], mode="EVALUATION"),
                stats.assessed(readings["stats/evaluation"])]
    got = [a for a in assessed if a is not None]
    contra1 = contra.detect(PACKAGE.document, naming=naming, assessments=got, at=AT_PASS)
    views = {"with": council.council_view(m, naming, assessments=got, contradictions=contra1),
             "solo": council.council_view(m, naming, assessments=(), contradictions=contra0)}
    req["council/ma-v1"] = council.council_request(views["with"], naming, level="complex", at=AT_PASS)
    req["council/ma-v1-h"] = council.council_request(views["with"], naming, level="simple", at=AT_PASS)
    req["council/cs-v1"] = council.council_request(views["solo"], naming, level="complex", at=AT_PASS)

    def ident(agent: str, task: str, input_hash: str, cands: tuple[str, ...], *, version: str = PACKAGE.version,
              model: str | None = None) -> TaskIdentity:
        return REGISTRY.identity_for(agent, task, workspace="lab", input_version=version, input_hash=input_hash, pass_kind="pre",
                                     fixture_id=FIXTURE, candidates=cands, model=model)

    ids = {"match/context": ident("match", "context", m.hash, ()),
           "match/evaluation": ident("match", "evaluation", m.hash, match.asked_keys(naming)),
           "stats/evaluation": ident("stats", "evaluation", s.hash, stats.asked_keys(naming)),
           "council/ma-v1": ident("council", "council", views["with"].hash, naming.keys, version=council.VIEW_VERSION,
                                  model=council.model_of("complex")),
           "council/ma-v1-h": ident("council", "council", views["with"].hash, naming.keys, version=council.VIEW_VERSION,
                                    model=council.model_of("simple")),
           "council/cs-v1": ident("council", "council", views["solo"].hash, naming.keys, version=council.VIEW_VERSION,
                                  model=council.model_of("complex"))}
    hashes = {k: (council.input_hash(r) if k.startswith("council/") else stats.input_hash(r) if k.startswith("stats/")
                  else match.input_hash(r)) for k, r in req.items()}
    outputs: dict[str, dict[str, Any]] = {}
    for k, r in readings.items():
        assert r.assessment is not None
        outputs[k] = r.assessment.model_dump(mode="json")
    for k, view in (("council/ma-v1", views["with"]), ("council/ma-v1-h", views["with"]), ("council/cs-v1", views["solo"])):
        reading = council.read(verdicts(naming, view, first=council_first), view=view, naming=naming)
        assert reading.council is not None, reading.problems
        outputs[k] = reading.council.model_dump(mode="json")
    return Shadow(req, ids, hashes, outputs, views)


SHADOW = shadow_pass()


def stored(scope: str, run_id: int, shadow: Shadow = SHADOW, **over: Any) -> bank.StoredRun:
    """The row the orchestrator stored for one task of the pass (``ai.agent_runs`` with its ledger's hash and its state)."""
    ident = shadow.identities[scope]
    agent, task = ident.agent, ("council" if ident.agent == "council" else scope.split("/")[1])
    fields: dict[str, Any] = {
        "id": run_id, "fixture_id": FIXTURE, "pass_kind": "pre", "task_kind": task, "known_at": PACKAGE.known_at, "started_at": STARTED,
        "agent": agent, "agent_version": ident.agent_version, "prompt_version": ident.prompt_version, "schema_version": ident.schema_version,
        "model": ident.model, "effort": ident.effort, "idem_key": ident.key, "package_hash": PACKAGE.hash,
        "slice_hash": SLICES["stats"].hash if agent == "stats" else SLICES["match"].hash, "candidates": ident.candidates, "status": "ok",
        "output": shadow.outputs[scope], "cost": D("0.002"), "in_batch": True, "input_tokens": 9000, "output_tokens": 500,
        "request_hash": shadow.hashes[scope], "state_id": 5, "packet_id": PACKET_ID, "package_version": PACKAGE.version,
        "state_package_hash": PACKAGE.hash, "model_status": {"code": CODE, "stats": {"naming": NAMING.version}},
        "kickoff_at": KICKOFF, "packet_built_at": AT}
    return bank.StoredRun(**(fields | over))


def inputs(shadow: Shadow = SHADOW, naming_counts: tuple[Candidate, ...] = COUNTS, **over: Any) -> bank.PassInputs:
    rows = [("match", "context", SLICES["match"].hash, shadow.outputs["match/context"]),
            ("match", "evaluation", SLICES["match"].hash, shadow.outputs["match/evaluation"]),
            ("stats", "evaluation", SLICES["stats"].hash, shadow.outputs["stats/evaluation"])]
    kw: dict[str, Any] = {"slice_set": SLICES_V1, "reviewed": REVIEWED, "counts": naming_counts, "stats_on": True, "player_on": False,
                          "assessments": rows} | over
    return bank.inputs_of(PACKAGE, **kw)


SCOPES = ("match/context", "match/evaluation", "stats/evaluation", "council/ma-v1", "council/ma-v1-h", "council/cs-v1")


# -- a pass derived again --------------------------------------------------------------------------------------------------

def test_every_run_of_a_pass_derived_again_is_admitted_with_the_very_request_it_was_sent() -> None:
    runs = [stored(scope, i) for i, scope in enumerate(SCOPES, start=1)]
    items, excluded = bank.admit(runs, inputs())
    assert excluded == []
    assert [i.scope for i in items] == list(SCOPES)
    for item in items:
        sent = SHADOW.requests[item.scope]
        assert item.ask.request.system == sent.system and item.ask.request.user == sent.user, item.scope
        assert item.ask.request.schema == sent.schema and item.ask.request.max_tokens == sent.max_tokens
        assert item.ask.request.effort == sent.effort == item.run.effort and item.ask.request.native_schema == sent.native_schema
        assert item.ask.key == item.run.idem_key and item.ask.request_hash == item.run.request_hash


def test_what_the_gate_compares_of_a_stored_answer_is_its_words_and_nothing_the_model_wrote_otherwise() -> None:
    items, _ = bank.admit([stored(s, i) for i, s in enumerate(SCOPES, start=1)], inputs())
    by = {i.scope: i for i in items}
    keys = match.asked_keys(NAMING)
    assert by["match/evaluation"].units == {keys[0]: "SUPPORT", **dict.fromkeys(keys[1:], "NEUTRAL")}
    assert by["stats/evaluation"].units == dict.fromkeys(stats.asked_keys(NAMING), "NEUTRAL")
    assert by["match/context"].units == {"signals": "FORM:HOME"}
    assert by["council/ma-v1"].units == {NAMING.keys[0]: "APPROVE", **dict.fromkeys(NAMING.keys[1:], "ABSTAIN")}
    assert by["council/ma-v1"].confidence[NAMING.keys[0]] == "MEDIUM" and by["match/evaluation"].confidence == {}


def test_a_stored_answer_that_did_not_stand_is_admitted_with_no_words_its_question_is_the_same() -> None:
    run = stored("match/evaluation", 1, status="invalid", output=None)
    [item], excluded = bank.admit([run], inputs())
    assert excluded == [] and item.units == {} and item.run.status == "invalid"


def test_the_council_of_the_three_arms_is_told_apart_by_the_view_and_the_model() -> None:
    by_arm = {i.ask.arm: i for i in bank.admit([stored(s, n) for n, s in enumerate(SCOPES[3:], start=10)], inputs())[0]}
    assert set(by_arm) == {"ma-v1", "ma-v1-h", "cs-v1"}
    assert by_arm["ma-v1"].ask.view is not None and by_arm["ma-v1"].ask.view.assessments == ("match_context", "match_evaluation",
                                                                                              "stats_evaluation")
    assert by_arm["cs-v1"].ask.view is not None and by_arm["cs-v1"].ask.view.assessments == ()
    assert by_arm["ma-v1-h"].run.model == council.model_of("simple")


# -- what excludes a run, after its pass was derived -------------------------------------------------------------------------

def test_a_slice_cut_otherwise_a_request_hashed_otherwise_or_one_the_ledger_did_not_keep_excludes_the_run() -> None:
    runs = [stored("match/context", 1, slice_hash="1" * 64), stored("match/evaluation", 2, request_hash="2" * 64),
            stored("stats/evaluation", 3, request_hash=None)]
    items, excluded = bank.admit(runs, inputs())
    assert items == []
    assert [(e.run.id, e.scope, e.reason) for e in excluded] == [(1, "match/context", "slice_not_rebuilt"),
                                                                  (2, "match/evaluation", "request_not_rebuilt"),
                                                                  (3, "stats/evaluation", "request_hash_unknown")]


def test_a_council_that_read_another_assessment_than_the_one_stored_is_not_in_the_bank() -> None:
    other = dict(SHADOW.outputs["match/evaluation"])
    other["candidates"] = [dict(c, stance="NEUTRAL", drivers=[], refs=[]) for c in other["candidates"]]
    changed = dataclasses.replace(SHADOW, outputs=SHADOW.outputs | {"match/evaluation": other})
    items, excluded = bank.admit([stored("council/ma-v1", 1), stored("council/cs-v1", 2)], inputs(changed))
    assert [(e.run.id, e.reason) for e in excluded] == [(1, "input_not_rebuilt")], "the solo arm reads no assessment: it stays"
    assert [i.scope for i in items] == ["council/cs-v1"]


def test_other_names_for_the_candidates_are_another_question() -> None:
    items, excluded = bank.admit([stored("match/evaluation", 1), stored("stats/evaluation", 2)], inputs(naming_counts=COUNTS[:1]))
    assert [i.scope for i in items] == ["match/evaluation"], "the names of goals and result do not move with the counts"
    assert [(e.run.id, e.reason) for e in excluded] == [(2, "input_not_rebuilt")]


def test_an_answer_stored_over_another_slice_is_not_what_the_council_read() -> None:
    rows = [("match", "evaluation", "9" * 64, SHADOW.outputs["match/evaluation"])]
    assert bank.reread_assessments(rows, SLICES) == ()
    rows = [("match", "evaluation", SLICES["match"].hash, {"contract": "aa-v1", "agent": "match"})]
    with pytest.raises(ValueError):
        bank.reread_assessments(rows, SLICES)


# -- what excludes a run from its own row ----------------------------------------------------------------------------------

@pytest.mark.parametrize("over, reason", [
    ({"task_kind": "escalation", "model": council.model_of("critical")}, "escalation_out_of_bank"),
    ({"agent": "brief"}, "agent_out_of_bank"),
    ({"agent_version": "match-v4"}, "version_not_in_force"),
    ({"prompt_version": "match-assess-v2"}, "prompt_not_in_force"),
    ({"schema_version": "aa-v0"}, "schema_not_in_force"),
    ({"model": council.model_of("complex")}, "model_not_in_force"),
    ({"effort": "low"}, "effort_not_in_force"),
])
def test_a_run_that_is_not_the_variant_in_force_is_excluded_before_anything_is_derived(over: dict[str, Any], reason: str) -> None:
    run = stored("match/evaluation", 1)
    if over.get("task_kind") == "escalation":
        run = dataclasses.replace(stored("council/ma-v1", 1), **over)
    else:
        run = dataclasses.replace(run, **over)
    assert bank.quick_reason(run, changed_at=None) == reason


def test_the_variant_in_force_passes_the_checks_of_its_own_row_and_an_optimisation_changed_after_it_does_not() -> None:
    assert all(bank.quick_reason(stored(s, 1), changed_at=None) is None for s in SCOPES)
    assert bank.quick_reason(stored("council/ma-v1", 1), changed_at=STARTED + timedelta(seconds=1)) == "optimisations_changed_since"
    assert bank.quick_reason(stored("council/ma-v1", 1), changed_at=STARTED - timedelta(days=9)) is None


@pytest.mark.parametrize("over, reason", [
    ({"state_id": None}, "no_state_of_the_pass"), ({"packet_id": None}, "no_state_of_the_pass"),
    ({"state_package_hash": "3" * 64}, "state_names_another_package"),
    ({"kickoff_at": PACKAGE.known_at}, "known_at_after_kickoff"),
    ({"package_version": "package-v9"}, "package_version_not_derivable"),
])
def test_a_pass_whose_state_cannot_be_its_source_is_excluded_before_it_is_derived(over: dict[str, Any], reason: str) -> None:
    assert bank.state_reason(stored("match/context", 1)) is None
    assert bank.state_reason(dataclasses.replace(stored("match/context", 1), **over)) == reason


def test_every_code_said_is_one_of_the_closed_list() -> None:
    assert len(set(bank.REASONS)) == len(bank.REASONS)
    assert set(bank.SCOPES) == {f"{a}/{t}" for a, t in (("match", "context"), ("match", "evaluation"), ("stats", "evaluation"),
                                                         ("player", "evaluation"))} | {f"council/{arm}" for arm in bank.ARMS}


# -- the build over the passes -----------------------------------------------------------------------------------------------

class NoConn:
    """A connection the build must not touch for what it decides from the rows alone."""

    def cursor(self, **kw: Any) -> Any:
        raise AssertionError("no query expected")


def test_the_build_derives_each_pass_once_and_only_when_a_run_of_it_passed_its_own_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def derive(conn: Any, run: bank.StoredRun) -> bank.Derived:
        calls.append(run.id)
        return bank.Derived(inputs())

    monkeypatch.setattr(bank, "derive_pass", derive)
    runs = [stored(s, i) for i, s in enumerate(SCOPES, start=1)] + [dataclasses.replace(stored("match/context", 50), agent_version="match-v2")]
    built = bank.build(NoConn(), runs=runs, changed_at=None)  # type: ignore[arg-type]
    assert calls == [1], "one pass, derived once"
    assert [i.run.id for i in built.items] == [1, 2, 3, 4, 5, 6]
    assert [(e.run.id, e.reason) for e in built.excluded] == [(50, "version_not_in_force")]
    counts = built.counts()
    assert counts["match/context"] == {"read": 2, "admitted": 1, "excluded": {"version_not_in_force": 1}}


def test_a_pass_that_cannot_be_derived_excludes_its_runs_with_its_code_and_a_database_that_fails_stops_the_build(
        monkeypatch: pytest.MonkeyPatch) -> None:
    other = [dataclasses.replace(stored("match/context", 7), fixture_id=FIXTURE + 1)]

    def derive(conn: Any, run: bank.StoredRun) -> bank.Derived:
        if run.fixture_id == FIXTURE:
            raise RuntimeError("a packet written by hand")
        return bank.Derived(None, "package_not_rebuilt")

    monkeypatch.setattr(bank, "derive_pass", derive)
    built = bank.build(NoConn(), runs=[stored("match/context", 1), *other], changed_at=None)  # type: ignore[arg-type]
    assert built.items == ()
    assert [(e.run.id, e.reason) for e in built.excluded] == [(1, "rebuild_failed:RuntimeError"), (7, "package_not_rebuilt")]

    def broken(conn: Any, run: bank.StoredRun) -> bank.Derived:
        raise psycopg.OperationalError("the server is gone")

    monkeypatch.setattr(bank, "derive_pass", broken)
    with pytest.raises(psycopg.OperationalError):
        bank.build(NoConn(), runs=[stored("match/context", 1)], changed_at=None)  # type: ignore[arg-type]


def test_a_selection_is_the_same_whatever_order_the_runs_were_read_in_and_takes_at_most_the_limit_per_scope() -> None:
    items, _ = bank.admit([stored(s, i) for i, s in enumerate(SCOPES * 3, start=1)], inputs())
    forward = bank.select(items, scopes=None, limit_per_scope=2, seed="s")
    backward = bank.select(list(reversed(items)), scopes=None, limit_per_scope=2, seed="s")
    assert [i.run.id for i in forward] == [i.run.id for i in backward]
    assert {s: sum(1 for i in forward if i.scope == s) for s in SCOPES} == dict.fromkeys(SCOPES, 2)
    assert bank.digest(forward) == bank.digest(backward) != bank.digest(bank.select(items, scopes=None, limit_per_scope=2, seed="t"))
    assert {i.scope for i in bank.select(items, scopes=["council/ma-v1"], limit_per_scope=None, seed="s")} == {"council/ma-v1"}


# -- the readers it builds on ------------------------------------------------------------------------------------------------

def test_the_selections_production_reviewed_are_read_as_the_store_reads_them_and_only_as_of_the_start_of_the_run() -> None:
    expected = REVIEWED_SQL.replace("AND r.p_model IS NOT NULL", "AND r.p_model IS NOT NULL AND r.reviewed_at <= %(at)s")
    assert expected == bank.REVIEWED_AS_OF_SQL


class Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def cursor(self, **kw: Any) -> Rows:
        return self

    def __enter__(self) -> Rows:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        assert "ai.feature_gates" in sql and set(params["gates"]) == {"batch", "native_schema", "cache_layout", "switches"}

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def words(**switches: str) -> dict[str, Any]:
    return {"words": {"switches": {"batch": "auto", "cache": "auto", "native_schema": "auto", "budget_v3": "auto"} | switches,
                      "agents": "match"}}


def test_the_last_change_of_an_optimisation_is_a_gate_that_moved_or_a_switch_of_a_request_that_moved() -> None:
    t = [AT + timedelta(hours=h) for h in range(8)]
    rows: list[tuple[Any, ...]] = [("batch", t[0], True, {}), ("native_schema", t[1], False, {}), ("switches", t[2], True, words()),
                                   ("batch", t[3], True, {}), ("switches", t[4], True, words(budget_v3="off")),
                                   ("switches", t[5], True, {"words": {"agents": "x"}})]
    assert bank.optimisations_changed_at(Rows(rows)) == t[0], "a gate that failed from the start never moved; a word of another kind is not one"  # type: ignore[arg-type]
    assert bank.optimisations_changed_at(Rows([*rows, ("switches", t[6], True, words(cache="off"))])) == t[6]  # type: ignore[arg-type]
    assert bank.optimisations_changed_at(Rows([*rows, ("cache_layout", t[7], True, {})])) == t[7]  # type: ignore[arg-type]
    assert bank.optimisations_changed_at(Rows([])) is None  # type: ignore[arg-type]


def test_the_words_of_an_answer_are_read_by_its_contract() -> None:
    assert bank.units_of("match", "evaluation", None) == {}
    assert bank.units_of("match", "context", {"signals": []}) == {"signals": "-"}
    assert bank.units_of("match", "context", {"signals": [{"code": "FORM", "direction": "HOME"}, {"code": "ABSENCES", "direction": "AWAY"},
                                                          {"code": "FORM", "direction": "HOME"}]}) == {"signals": "ABSENCES:AWAY;FORM:HOME"}
    assert bank.units_of("council", "council", {"verdicts": [{"candidate": "c1", "verdict": "REJECT"}, {"candidate": 2}]}) == {"c1": "REJECT"}
    assert bank.confidence_of("council", {"verdicts": [{"candidate": "c1", "confidence": "LOW"}]}) == {"c1": "LOW"}
    assert bank.confidence_of("match", {"verdicts": [{"candidate": "c1", "confidence": "LOW"}]}) == {}

"""The reduced Council (IA-124, AD-D10): ``council-reduced-v1`` on ``council-protocol-v1``. The rules by default; the judge only on a material
contradiction with value and time, three readings and a majority; never above the rules; the Haiku arm no judge. No database, no model."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import arms
from fbi.council import VERSION as PROTOCOL
from fbi.council import contradictions as contra
from fbi.council import protocol, reduced
from fbi.councilpass import store
from fbi.intel import context_adjustment as ctx
from fbi.intel.decision import RANK
from fbi.shadowjobs import council_reduced as job

D = Decimal
AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=8)
ROOT = Path(__file__).resolve().parents[2]


def sel(key: str = "c1", *, ev: str | None = "0.10", codes: tuple[str, ...] = ()) -> contra.Selection:
    return contra.Selection(key, "1X2", "1X2", "Home", D(0), p_model=D("0.56"), p_market=D("0.50"), edge=D("0.06"),
                            ev=None if ev is None else D(ev), contra=codes)


def position(key: str, stance: str, weight: str = "1", agent: str = "match", run: int = 1) -> contra.Position:
    return contra.Position(agent, f"{agent}-v6", f"{agent}_evaluation", key, stance, ("ABSENCES",), (), ("P:shared.absences",), run, D(weight))


def material(key: str = "c1") -> contra.Finding:
    return contra.Finding("agent_vs_agent", "AA1", key, ("match", "stats"), (1, 2), ("P:shared.absences",), True)


def rules_of(s: contra.Selection, *stances: tuple[str, str]) -> protocol.Baseline:
    ps = [position(s.key, st, w, agent=f"a{i}", run=i) for i, (st, w) in enumerate(stances)]
    return protocol.baseline(s, ps, research_requested=False, at=AT)


# -- the version and the judge ----------------------------------------------------------------------------------------------------------

def test_the_version_its_protocol_and_its_judge() -> None:
    assert reduced.VERSION == "council-reduced-v1" and reduced.PROTOCOL == PROTOCOL == "council-protocol-v1"
    assert reduced.JUDGE_ENGINE == arms.MULTIAGENT and reduced.RETIRED_JUDGES == (arms.MULTIAGENT_HAIKU,)
    assert reduced.JUDGE_ENGINE in ctx.ENGINES and set(reduced.RETIRED_JUDGES) <= set(ctx.ENGINES)
    assert (reduced.READINGS, reduced.MAJORITY) == (3, 2) and reduced.WORDS == ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN")
    assert "ma-v1-h" in arms.SAMPLE_ENGINES, "the arm itself stays in arms-v1: only this version does not read it as a judge"


# -- when the judge is wanted -----------------------------------------------------------------------------------------------------------

def test_the_judge_is_wanted_only_with_a_material_contradiction_value_and_time() -> None:
    s = sel()
    assert reduced.need(s, [material()], minutes_to_kickoff=600).as_json() == {
        "wanted": True, "material": ["AA1"], "reasons": ["material_value_and_time"]}
    assert reduced.need(s, [], minutes_to_kickoff=600).reasons == ("no_material_contradiction",)
    assert reduced.need(sel(codes=("C07",)), [], minutes_to_kickoff=600).material == ("C07",), "evidence in conflict is material by itself"
    weightless = contra.Finding("agent_vs_agent", "AA1", "c1", ("match",), (1,), (), False)
    assert not reduced.need(s, [weightless], minutes_to_kickoff=600).wanted, "a contradiction between voices that weigh nothing"
    assert not reduced.need(s, [material("c2")], minutes_to_kickoff=600).wanted, "a finding of another selection"
    assert reduced.need(sel(ev="0.01"), [material()], minutes_to_kickoff=600).reasons == ("value_below_ev_threshold",)
    assert reduced.need(s, [material()], minutes_to_kickoff=reduced.JUDGE_MIN_MINUTES - 1).reasons == ("too_close_to_kickoff",)
    assert reduced.need(s, [material()], minutes_to_kickoff=None).reasons == ("kickoff_unknown",)


# -- three readings and a majority ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("words", "word", "status"), [
    (("REJECT", "REJECT", "APPROVE"), "REJECT", "majority"),
    (("DOWNGRADE", "DOWNGRADE", "DOWNGRADE"), "DOWNGRADE", "majority"),
    (("REJECT", "DOWNGRADE", "APPROVE"), None, "split"),
    (("ABSTAIN", "ABSTAIN", "REJECT"), None, "abstain_majority"),
    (("REJECT", None, None), None, "short"),
    (("REJECT", "PROMOTE", "REJECT"), "REJECT", "majority"),
    (("REJECT", "PROMOTE", None), None, "short"),
])
def test_the_judge_stands_only_by_a_majority(words: tuple[str | None, ...], word: str | None, status: str) -> None:
    m = reduced.majority(words)
    assert (m.word, m.status) == (word, status)


def test_three_readings_or_none() -> None:
    with pytest.raises(ValueError):
        reduced.majority(("REJECT", "REJECT"))
    asked: list[int] = []

    def judge(i: int) -> dict[str, str | None]:
        asked.append(i)
        if i == 1:
            raise TimeoutError("a reading that failed")
        return {"c1": "REJECT", "c2": 7} if i == 0 else {"c1": "REJECT"}  # type: ignore[dict-item]

    assert reduced.read_three(judge, ["c1", "c2"]) == {"c1": ("REJECT", None, "REJECT"), "c2": (None, None, None)}
    assert asked == [0, 1, 2], "three readings, the one that failed is no vote"


# -- it only lowers ---------------------------------------------------------------------------------------------------------------------

def effect(verdict: str) -> int:
    target = ctx.EFFECT[verdict]  # type: ignore[index]
    return RANK["APROBADO"] + 1 if target is None else RANK[target]


STANCES = ("SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL")
READS = (None, *reduced.WORDS, "PROMOTE")


def test_no_reading_of_the_judge_ever_lifts_a_selection_above_the_rules() -> None:
    """Every rules' word the protocol can give (every pair of stances, with and without weight) against every triple of readings."""
    s = sel()
    wanted = reduced.need(s, [material()], minutes_to_kickoff=600)
    seen_sources: set[str] = set()
    for (a, b), weights in itertools.product(itertools.product(STANCES, STANCES), (("1", "1"), ("0", "0"), ("1.5", "0.5"))):
        rules = rules_of(s, (a, weights[0]), (b, weights[1]))
        for readings in itertools.product(READS, repeat=3):
            o = reduced.settle(s, rules, wanted, readings, at=AT)
            assert effect(o.final.verdict) <= effect(rules.adjustment.verdict), (a, b, weights, readings)
            assert (o.source == "rules") == (o.final == rules.adjustment)
            if o.source == "judge":
                assert effect(o.final.verdict) < effect(rules.adjustment.verdict) and o.majority is not None and o.majority.word
                assert o.final.source.engine == reduced.VERSION
            seen_sources.add(o.source)
            for state in RANK:
                assert RANK[ctx.base_state(ctx.proposed_effect(o.final, state))] <= RANK[state]
    assert seen_sources == {"rules", "judge"}


def test_without_a_need_or_without_a_judge_the_rules_stand() -> None:
    s = sel()
    rules = rules_of(s, ("SUPPORT", "1"), ("SUPPORT", "1"))
    assert rules.adjustment.verdict == "CONFIRMA"
    not_needed = reduced.settle(s, rules, reduced.need(s, [], minutes_to_kickoff=600), ("REJECT",) * 3, at=AT)
    assert (not_needed.judge_status, not_needed.source, not_needed.final) == ("not_needed", "rules", rules.adjustment)
    not_asked = reduced.settle(s, rules, reduced.need(s, [material()], minutes_to_kickoff=600), None, at=AT)
    assert (not_asked.judge_status, not_asked.source) == ("not_asked", "rules")
    lowered = reduced.settle(s, rules, reduced.need(s, [material()], minutes_to_kickoff=600), ("REJECT", "REJECT", "APPROVE"), at=AT)
    assert (lowered.source, lowered.final.verdict, lowered.final.severity, lowered.final.confidence) == ("judge", "BLOQUEA", "bloqueante", "MEDIUM")
    assert lowered.lowered and lowered.as_json()["version"] == "council-reduced-v1"


# -- over a deliberation ----------------------------------------------------------------------------------------------------------------

def report(s: contra.Selection, findings: tuple[contra.Finding, ...], rules: protocol.Baseline) -> protocol.SelectionReport:
    from fbi.council import research_round as research

    return protocol.SelectionReport(s, (), contra.Market.unknown(), findings, research.judge(research.Case(s, findings, ())), rules, {}, ())


def deliberation(*reports: protocol.SelectionReport, minutes: int = 480) -> protocol.Deliberation:
    return protocol.Deliberation(77, AT, "ok", kickoff_at=AT + timedelta(minutes=minutes), match_run_id=9, pass_kind="pre", pass_known_at=AT,
                                 package_hash="a" * 64, selections=reports)


def test_the_judge_is_asked_three_times_once_a_match_and_only_when_a_selection_needs_it() -> None:
    c1, c2 = sel("c1"), sel("c2")
    r1 = report(c1, (material("c1"),), rules_of(c1, ("SUPPORT", "1"), ("CONCERN", "1")))
    r2 = report(c2, (), rules_of(c2, ("SUPPORT", "1")))
    calls: list[int] = []

    def judge(i: int) -> dict[str, str | None]:
        calls.append(i)
        return {"c1": "DOWNGRADE", "c2": "REJECT"}

    out = reduced.reduce(deliberation(r1, r2), judge=judge)
    assert calls == [0, 1, 2] and out.judge_readings == 3
    by = {o.key: o for o in out.outcomes}
    assert by["c1"].judge_status == "asked" and by["c1"].majority is not None and by["c1"].majority.words == ("DOWNGRADE",) * 3
    assert by["c2"].judge_status == "not_needed" and by["c2"].source == "rules", "the judge never speaks of a selection that does not need it"

    calls.clear()
    quiet = reduced.reduce(deliberation(r2), judge=judge)
    assert calls == [] and quiet.judge_readings == 0, "no selection needs it: the judge is not asked at all"
    late = reduced.reduce(deliberation(r1, minutes=10), judge=judge)
    assert calls == [] and late.outcomes[0].need.reasons == ("too_close_to_kickoff",)
    unwired = reduced.reduce(deliberation(r1), judge=None)
    assert unwired.outcomes[0].judge_status == "not_asked" and unwired.judge_readings == 0
    assert reduced.reduce(protocol.Deliberation(77, AT, "no_shadow_pass"), judge=judge).outcomes == ()


# -- the rows of the pass ---------------------------------------------------------------------------------------------------------------

MIGRATION = (ROOT / "migrations" / "versions" / "0161_council_reduced.py").read_text(encoding="utf-8")


def satisfies_the_table(row: dict[str, Any]) -> bool:
    """The CHECKs of ``ai.council_reduced`` (revision 0161), in Python."""
    rank = {"BLOQUEA": 0, "FALTA_INFO": 1, "RESERVA": 2}
    lower = rank.get(row["final_verdict"], 3) < rank.get(row["rules_verdict"], 3)
    return (row["deliberated_at"] < row["kickoff_at"] and row["judge_wanted"] == (row["judge_status"] != "not_needed")
            and (not row["judge_wanted"] or len(row["material"]) > 0)
            and (row["judge_status"] == "asked" or (row["majority"] is None and row["source"] == "rules"))
            and ((row["source"] == "rules" and row["final_verdict"] == row["rules_verdict"])
                 or (row["source"] == "judge" and row["majority"] is not None and lower)))


def test_the_rows_hold_the_checks_of_the_table() -> None:
    c1, c2 = sel("c1"), sel("c2")
    r1 = report(c1, (material("c1"),), rules_of(c1, ("SUPPORT", "1")))
    r2 = report(c2, (), rules_of(c2, ("CONCERN", "1")))
    for judge in (None, lambda i: {"c1": "REJECT", "c2": "REJECT"}, lambda i: {"c1": "APPROVE"}):
        rows = store.rows_of(reduced.reduce(deliberation(r1, r2), judge=judge), pass_kind="pre", code_version="x")
        assert [r["candidate"] for r in rows] == ["c1", "c2"] and all(satisfies_the_table(r) for r in rows), rows
        assert {r["version"] for r in rows} == {"council-reduced-v1"} and {r["protocol"] for r in rows} == {"council-protocol-v1"}
    for constraint in ("council_reduced_only_lowers", "council_reduced_judge", "council_reduced_wanted", "council_reduced_once",
                       "council_reduced_before_kickoff", "council_reduced_append_only", "ai.refuse_change()"):
        assert constraint in MIGRATION, constraint
    assert 'down_revision = "0160"' in MIGRATION and 'revision = "0161"' in MIGRATION


def test_the_pass_writes_only_its_table() -> None:
    source = Path(store.__file__).read_text(encoding="utf-8")
    written = set(re.findall(r"INSERT\s+INTO\s+([a-z_]+\.[a-z_]+)", source, flags=re.IGNORECASE))
    assert written == {"ai.council_reduced"} and not re.search(r"\b(UPDATE\s+\w+\.\w+\s+SET|DELETE\s+FROM)\b", source, flags=re.IGNORECASE)
    assert "call_json" not in source and "judge=None" in source, "this version of the pass asks no model"


# -- the worker's door ------------------------------------------------------------------------------------------------------------------

def test_the_switch_is_off_unless_it_says_shadow() -> None:
    assert job.mode({}) == "off" and job.mode({"FBI_COUNCIL_REDUCED": "on"}) == "off" and job.mode({"FBI_COUNCIL_REDUCED": " Shadow "}) == "shadow"
    assert job.every_minutes({}) == 30 and job.every_minutes({"FBI_COUNCIL_REDUCED_MINUTES": "5"}) == 30
    assert job.every_minutes({"FBI_COUNCIL_REDUCED_MINUTES": "60"}) == 60 and job.SWITCH == store.SWITCH


def test_the_worker_schedules_the_pass_only_in_the_shadow() -> None:
    from fbi.ops.run_watchdog import timeout_for

    scheduler = (ROOT / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")
    assert 'if crd.mode() == "shadow":' in scheduler and '"council_reduced_shadow"' in scheduler
    assert timeout_for("council_reduced_shadow").total_seconds() == 15 * 60

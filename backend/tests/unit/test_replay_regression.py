"""AD-K04 (IA-136): the replay bank as a regression test with a preregistered tolerance (``replay-regression-v1``), its written cause
(``diag-v1``), the protocol's rule against repeating to change a verdict and when it is due. No database, no model, no clock."""

from __future__ import annotations

from typing import Any

import pytest
from scripts import ia_replay_regression as script

from fbi.ai.replay import measure, regression, regression_store
from fbi.ai.replay.measure import Answers, Unit
from fbi.proposals import Proposal, Row, problems
from fbi.research import protocol

DRAWS = 300


def assessment(*, low: float, high: float, units: int = 541, matches: int = 126, invalid_replay: float = 0.0,
               invalid_stored: float = 0.0, open_asks: int = 0) -> dict[str, Any]:
    return {"complete_units": units, "matches": matches, "difference_ci95": [low, high], "invalid_replay": invalid_replay,
            "invalid_stored": invalid_stored, "open": open_asks, "verdict": measure.FAIL}


def test_the_tolerance_is_five_points_proposed_and_registered_before_any_regression_row() -> None:
    p = protocol.require("AD-K04")
    assert regression.TOLERANCE == 0.05 and "propuesta" in regression.TOLERANCE_STATUS
    assert "≤ 0,05" in p.pass_rule and "PROPUESTA" in p.pass_rule and "la firma el dueño" in p.pass_rule
    assert p.seed == measure.SEED, "the interval is the one INT-C02 already reports"
    assert p.key == regression.PROTOCOL_KEY and all(c in p.reject_rule for c in regression.CAUSES)


@pytest.mark.parametrize("scope, low, high, units, matches, verdict", [
    ("council/ma-v1", 0.002, 0.057, 541, 126, regression.FAIL),
    ("council/ma-v1-h", 0.096, 0.235, 494, 121, regression.FAIL),
    ("match/evaluation", -0.080, 0.139, 81, 26, regression.INSUFFICIENT),
    ("stats/evaluation", -0.105, 0.152, 39, 10, regression.INSUFFICIENT),
])
def test_the_run_of_15_nov_judged_with_the_tolerance(scope: str, low: float, high: float, units: int, matches: int,
                                                     verdict: str) -> None:
    """The figures of the run of 15-nov (1.022 asks, US$ 2,93): with the tolerance ma-v1 does not pass either (5,7 > 5)."""
    got = regression.judge(assessment(low=low, high=high, units=units, matches=matches))
    assert got["verdict"] == verdict, scope
    assert got["decides"] is False and got["tolerance"] == 0.05


def test_within_the_tolerance_passes_and_the_point_rule_does_not_decide() -> None:
    got = regression.judge(assessment(low=0.001, high=0.049))
    assert got["verdict"] == regression.PASS and got["within_tolerance"] is True and got["reasons"] == []
    assert got["point_rule"] == measure.FAIL, "the point rule failed; the tolerance is what the regression reads"
    assert regression.judge(assessment(low=0.0, high=0.05))["verdict"] == regression.PASS, "at most 5 points: the edge passes"


def test_replays_that_do_not_stand_fail_even_within_the_tolerance_and_asks_on_their_way_are_insufficient() -> None:
    assert regression.judge(assessment(low=-0.01, high=0.02, invalid_replay=0.05))["verdict"] == regression.FAIL
    assert regression.judge(assessment(low=-0.01, high=0.02, invalid_replay=0.03, invalid_stored=0.03))["verdict"] == regression.PASS
    assert regression.judge(assessment(low=-0.01, high=0.02, open_asks=2))["verdict"] == regression.INSUFFICIENT
    no_interval = {**assessment(low=0, high=0), "difference_ci95": None}
    assert regression.judge(no_interval)["verdict"] == regression.INSUFFICIENT


@pytest.mark.parametrize("stored, replay, same", [("claude-sonnet-5-5", "claude-sonnet-5-5", True),
                                                  ("claude-sonnet-5-5", "claude-sonnet-5-5-20261001", True),
                                                  ("claude-sonnet-5-5", "claude-haiku-5-5", False), (None, "x", None), ("x", "", None)])
def test_the_same_model_is_the_same_name_or_the_name_with_a_dated_suffix(stored: str | None, replay: str | None,
                                                                         same: bool | None) -> None:
    assert regression.same_model(stored, replay) is same


def part(start: int, n: int, matches: int, *, moved_every: int, noise_every: int = 10) -> list[Unit]:
    """``n`` units of ``matches`` matches: the stored word differs from R1 every ``moved_every``; R2 differs from R1 every ``noise_every``."""
    out = []
    for i in range(n):
        stored = "REJECT" if moved_every and i % moved_every == 0 else "DOWNGRADE"
        second = "ABSTAIN" if i % noise_every == 5 else "DOWNGRADE"
        out.append(Unit(start + i, start + i % matches, "c1", stored, "DOWNGRADE", second))
    return out


def test_a_difference_of_the_real_time_runs_only_is_the_route() -> None:
    batch = part(0, 300, 40, moved_every=0)
    live = part(10_000, 300, 40, moved_every=2)
    strata = regression.Strata({u.item: "batch" for u in batch} | {u.item: "tiempo_real" for u in live},
                               {u.item: (True, True) for u in batch + live})
    whole = measure.assess(batch + live, Answers(600, 0, 1200, 0), draws=DRAWS)
    assert regression.judge(whole)["verdict"] == regression.FAIL
    got = regression.diagnose(batch + live, strata, draws=DRAWS)
    assert got["cause"] == "via_tiempo_real" and got["items"] == {"batch": 300, "tiempo_real": 300, "mismo_modelo": 600, "otro_modelo": 0}
    assert got["parts"]["route"]["batch"]["difference_ci95"][1] <= 0.05 < got["parts"]["route"]["tiempo_real"]["difference_ci95"][1]


def test_a_difference_of_the_answers_of_another_model_only_is_the_model() -> None:
    same = part(0, 300, 40, moved_every=0)
    other = part(10_000, 300, 40, moved_every=2)
    strata = regression.Strata({u.item: "batch" if (u.item // 2) % 2 else "tiempo_real" for u in same + other},
                               {u.item: (True, True) for u in same} | {u.item: (False, True) for u in other})
    assert regression.diagnose(same + other, strata, draws=DRAWS)["cause"] == "modelo_distinto"


def test_a_difference_everywhere_is_not_explained_and_small_parts_cannot_explain() -> None:
    moved = part(0, 600, 60, moved_every=2)
    strata = regression.Strata({u.item: "batch" if (u.item // 2) % 2 else "tiempo_real" for u in moved}, {u.item: (True, True) for u in moved})
    got = regression.diagnose(moved, strata, draws=DRAWS)
    assert got["cause"] == "no_explicada" and got["cause_es"] == regression.CAUSE_ES["no_explicada"]
    few = part(0, 150, 20, moved_every=2)
    small = regression.Strata({u.item: "batch" if (u.item // 2) % 2 else "tiempo_real" for u in few}, {u.item: (True, None) for u in few})
    assert regression.diagnose(few, small, draws=DRAWS)["cause"] == "muestra_insuficiente_para_explicar"


def test_words_that_reproduce_with_replays_that_do_not_stand_is_validity() -> None:
    fine = part(0, 300, 40, moved_every=0)
    strata = regression.Strata({u.item: "batch" for u in fine}, {u.item: (True, True) for u in fine})
    assert regression.diagnose(fine, strata, replays_invalid=True, draws=DRAWS)["cause"] == "validez"


def test_every_cause_is_written_in_spanish() -> None:
    assert set(regression.CAUSE_ES) == set(regression.CAUSES) and all(len(v) > 30 for v in regression.CAUSE_ES.values())


# -- the protocol's rule: no repeating to change a verdict ---------------------------------------------------------------------

def test_a_measurement_over_runs_an_earlier_one_used_is_refused_and_a_new_window_is_allowed() -> None:
    assert regression.admissible([1, 2, 3], [[3, 4], [9]]) == (False, [3])
    assert regression.admissible([1, 2, 3], [[4, 5]]) == (True, [])
    assert regression.admissible([], []) == (False, []), "nothing measured is no measurement"


class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.statements.append((sql, params))

    def fetchone(self) -> tuple[int]:
        return (len(self.conn.statements),)


class _Conn:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    def cursor(self, **_: Any) -> _Cursor:
        return _Cursor(self)


def report(**scopes: list[int]) -> dict[str, Any]:
    return {"variant": "same", "protocol": protocol.stamp("AD-K04"), "scopes": {
        s: {"runs": runs, "assessment": {"open": 0}, "regression": {"verdict": regression.FAIL}, "measured_version": "council-v1"}
        for s, runs in scopes.items()}}


def test_recording_needs_the_owners_signed_tolerance() -> None:
    with pytest.raises(PermissionError, match="the owner signs"):
        regression_store.record(_Conn(), report(a=[1]), at=None, signed=False)  # type: ignore[arg-type]


def test_recording_again_over_the_same_runs_writes_nothing_for_that_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    earlier = {"council/ma-v1": [[10, 11, 12]], "council/ma-v1-h": [[50]]}
    monkeypatch.setattr(regression_store, "earlier", lambda conn, *, variant, scope: earlier.get(scope, []))
    conn = _Conn()
    got = regression_store.record(conn, report(**{"council/ma-v1": [11, 13], "council/ma-v1-h": [51, 52]}), at=None,  # type: ignore[arg-type]
                                  signed=True)
    assert got["refused_reused_runs"] == {"council/ma-v1": [11]} and list(got["written"]) == ["council/ma-v1-h"]
    inserts = [p for s, p in conn.statements if s.lstrip().startswith("INSERT INTO ai.replay_assessments")]
    assert len(inserts) == 1 and inserts[0]["method"] == regression.METHOD and inserts[0]["protocol"] == "proto-ad-k04-v1"


def test_a_scope_with_asks_on_their_way_is_not_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(regression_store, "earlier", lambda conn, *, variant, scope: [])
    doc = report(a=[1])
    doc["scopes"]["a"]["assessment"]["open"] = 1
    assert regression_store.record(_Conn(), doc, at=None, signed=True)["written"] == {}  # type: ignore[arg-type]


# -- when it is due --------------------------------------------------------------------------------------------------------------

def test_a_change_of_a_reader_or_of_the_judge_makes_the_regression_due() -> None:
    got = regression.due({"match/evaluation": "match-v5", "council/ma-v1": "council-v1"},
                         {"match/evaluation": "match-v6", "council/ma-v1": "council-v1", "stats/evaluation": "stats-v5"})
    assert got == [{"scope": "match/evaluation", "measured": "match-v5", "in_force": "match-v6"},
                   {"scope": "stats/evaluation", "measured": None, "in_force": "stats-v5"}]


def test_the_version_in_force_is_the_registrys_for_each_scope_agent() -> None:
    from fbi.ai.agents.registry import REGISTRY

    got = regression_store.in_force(["match/evaluation", "council/ma-v1", "nobody/x"])
    assert got == {"match/evaluation": REGISTRY.in_force("match").version, "council/ma-v1": REGISTRY.in_force("council").version}


def test_the_strata_of_a_scope_come_from_the_banks_own_columns() -> None:
    rows = [{"source_run_id": 7, "scope": "council/ma-v1", "stored_in_batch": False, "stored_model": "m", "agent_version": "council-v1",
             "repetition": 1, "replay_model": "m"},
            {"source_run_id": 7, "scope": "council/ma-v1", "stored_in_batch": False, "stored_model": "m", "agent_version": "council-v1",
             "repetition": 2, "replay_model": "n"},
            {"source_run_id": 8, "scope": "council/ma-v1", "stored_in_batch": True, "stored_model": "m", "agent_version": "council-v1",
             "repetition": None, "replay_model": None}]
    split, measured = regression_store.strata(rows)
    assert split["council/ma-v1"].route == {7: "tiempo_real", 8: "batch"}
    assert split["council/ma-v1"].model == {7: (True, False), 8: (None, None)} and measured == {"council/ma-v1": "council-v1"}


# -- the owner's signature of the tolerance ---------------------------------------------------------------------------------------

def check_report() -> dict[str, Any]:
    return {"bank": "replay-bank-v1", "variant": "same", "protocol": protocol.stamp("AD-K04"), "scopes": {
        "council/ma-v1": {"regression": {"verdict": regression.FAIL, "upper": 0.057}, "assessment": {"complete_units": 541, "matches": 126},
                          "diagnosis": {"cause": "no_explicada"}}}}


def test_the_tolerance_is_proposed_as_a_threshold_the_registry_accepts_and_never_as_a_lowering() -> None:
    p = script.proposal(check_report())
    assert problems(p) == [] and p.kind == "umbral" and p.target == regression.TARGET
    assert p.current_version == measure.METHOD and p.proposed_version == regression.METHOD and p.rollback_to == measure.METHOD
    assert p.change["tolerance"] == regression.TOLERANCE and p.change.get("direction") != "lower"
    assert p.evidence["scopes"]["council/ma-v1"] == {"verdict": regression.FAIL, "upper": 0.057, "units": 541, "matches": 126,
                                                     "cause": "no_explicada"}


def test_only_a_signed_proposal_of_this_very_tolerance_counts_as_signed() -> None:
    p = script.proposal(check_report())
    other = Proposal(p.kind, p.target, p.current_version, p.proposed_version, {**p.change, "tolerance": 0.10}, p.evidence,
                     p.evidence_refs, p.reason)
    assert script.signed([Row(1, p, "firmada")]) and script.signed([Row(1, p, "firmada", ("aplicada",))])
    assert not script.signed([Row(1, p, None)]) and not script.signed([Row(1, p, "rechazada")])
    assert not script.signed([Row(2, other, "firmada")])


def test_record_is_the_owners_action() -> None:
    with pytest.raises(SystemExit):
        script.main(["record"])
    assert script.exit_code({"scopes": {}}) == script.CANNOT
    assert script.exit_code({"scopes": {"a": {"regression": {"verdict": regression.PASS}}}}) == script.OK
    assert script.exit_code({"scopes": {"a": {"regression": {"verdict": regression.INSUFFICIENT}}}}) == script.NO

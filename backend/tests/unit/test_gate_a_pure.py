"""The pure parts of Gate A (``fbi.ai.gate_a``, ``scripts/ia_gate.py``): the numbers the plan fixed, how a verdict is told, what the
consequence of a failure is. No database. The checks themselves, on a built world, are in ``tests/integration/test_gate_a.py``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fbi.ai import gate_a, lab

D = Decimal
AT = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
WINDOW = gate_a.Window(date(2026, 10, 27), date(2026, 11, 2), date(2026, 10, 26), "x, 2026-10-25", 8, date(2026, 11, 2))


def check(id_: str, ok: bool | None, revert: str | None = None) -> gate_a.Check:
    return gate_a.Check(id_, id_, ok, {}, revert)


def test_the_thresholds_are_the_ones_of_the_plan_and_the_engineering_readings_are_named() -> None:
    thresholds = {name: str(getattr(gate_a, name)) for name in (
        "WINDOW_DAYS", "PRODUCTION_CEILING", "JOINT_CEILING", "SHADOW_NORMAL_MONTH_USD", "HEAVY_MONTH_FACTOR", "MIN_EQUIVALENCE_INPUTS",
        "FINAL_BEFORE_T15_MIN", "CACHE_HIT_MIN", "CACHE_DAYS_MIN", "BATCH_EXPIRED_MAX", "COVERAGE_TOLERANCE")}
    assert thresholds == {
        "WINDOW_DAYS": "7",  # «7 días completos»
        "PRODUCTION_CEILING": "185", "JOINT_CEILING": "190",  # «≤ 185 USD» and, with the shadow, «≤ 190»
        "SHADOW_NORMAL_MONTH_USD": "51",  # the cost model v6: the shadow at 30 % in a normal month
        "HEAVY_MONTH_FACTOR": "1.25",  # a heavy month, +25 %
        "MIN_EQUIVALENCE_INPUTS": "200",  # «≥ 200 paquetes»
        "FINAL_BEFORE_T15_MIN": "0.99",  # the service objective of section 32
        "CACHE_HIT_MIN": "0.40", "CACHE_DAYS_MIN": "6",  # the alarm of section 28: 40 %
        "BATCH_EXPIRED_MAX": "0.01",  # the alarm: more than 1 % expired
        "COVERAGE_TOLERANCE": "0.02",  # my reading of «misma cobertura», named as mine
    }
    assert lab.MIN_INPUTS == gate_a.MIN_EQUIVALENCE_INPUTS
    assert gate_a.OPTIMISATIONS == ("batch", "native_schema", "cache_layout")
    assert {k: str(v) for k, v in gate_a.EXPECTED_ENV.items()} == {
        "FBI_AI_MONTHLY_BUDGET_USD": "185", "FBI_AI_LAB_MONTHLY_BUDGET_USD": "15", "FBI_AI_EXA_MONTHLY_BUDGET_USD": "35"}, \
        "owner action 7"
    assert [d.isoformat() for d in gate_a.BASELINE_COVERAGE_DAYS] == ["2026-10-09", "2026-10-24"], "the 16 days of IA_BASELINE_F0"
    assert [d.isoformat() for d in gate_a.BASELINE_UNIT_DAYS] == ["2026-10-18", "2026-10-24"], "its last 7 days"
    assert (gate_a.GATE, gate_a.PASS, gate_a.FAIL) == ("gate_a", "PASA", "NO PASA")
    assert (gate_a.PENDING_TIME, gate_a.PENDING_ACTIONS) == ("PENDIENTE POR TIEMPO REAL", "PENDIENTE POR ACCIONES MANUALES")


def test_rates_and_percentages() -> None:
    assert gate_a._rate(1, 3) == D("0.3333") and gate_a._rate(0, 5) == D(0) and gate_a._rate(5, 0) is None
    assert gate_a._pct(D("0.9857")) == "98.57" and gate_a._pct(None) is None


def test_the_letters_of_the_evidence_are_read_back_as_the_rows_the_assessment_takes() -> None:
    evidence = {"inputs": {"a": "AAD", "b": "A-A", "c": "AA", "d": "ADDD"}}
    assert gate_a.stored_rows(evidence, "native_schema") == {"a": {"A1": "A", "A2": "A", "B": "D"},
                                                              "b": {"A1": "A", "A2": None, "B": "A"}}, "a malformed entry is left out"
    assert gate_a.stored_rows(evidence, "shared_layout")["a"] == {"A1": "A", "A2": "A", "C": "D"}
    assert gate_a.stored_rows({}, "native_schema") == {}


def test_what_to_do_when_the_gate_fails_is_what_the_plan_says() -> None:
    switch = gate_a.consequence([check("cache_visible", False, "FBI_AI_CACHE"), check("batch_lost", False, "FBI_AI_BATCH")])
    assert switch == "se revierte el interruptor que falle: FBI_AI_BATCH, FBI_AI_CACHE; se corrige y se repite la medición"
    only_cost = gate_a.consequence([check("cost_joint", False)])
    assert "la sombra se planifica con menos muestra" in only_cost and "300 selecciones en 30 días" in only_cost
    assert gate_a.consequence([check("cost_joint", False), check("coverage", False, "FBI_AI_BRIEF_MATERIAL")]).startswith("se revierte")
    assert "ninguno aplica" in gate_a.consequence([check("cost_production", False)]), "a cost that fails alone has no switch of its own"


def test_a_check_is_yes_no_or_pending() -> None:
    assert [check("x", v).mark for v in (True, False, None)] == ["SÍ", "NO", "PENDIENTE"]
    assert check("x", None).as_json() == {"id": "x", "title": "x", "ok": None, "detail": {}, "revert": None}


def test_only_a_pass_or_a_fail_can_be_recorded() -> None:
    for verdict, recordable in ((gate_a.PASS, True), (gate_a.FAIL, True), (gate_a.PENDING_TIME, False),
                                (gate_a.PENDING_ACTIONS, False)):
        assert gate_a.GateReport(verdict, AT, WINDOW).recordable is recordable, verdict


def test_the_window_says_when_it_is_complete_and_what_it_covers() -> None:
    assert WINDOW.complete
    assert not gate_a.Window(date(2026, 10, 27), date(2026, 11, 2), date(2026, 10, 28), "x", 6, date(2026, 11, 4)).complete
    assert not gate_a.Window(date(2026, 10, 27), date(2026, 11, 2), None, None, 0, None).complete
    assert WINDOW.as_json() == {"first": "2026-10-27", "last": "2026-11-02", "days": 7, "anchor": "2026-10-26",
                                "anchored_by": "x, 2026-10-25", "stable_complete_days": 8, "eligible_on": "2026-11-02",
                                "complete": True}


def test_the_report_reads_in_spanish_and_says_what_is_missing() -> None:
    report = gate_a.GateReport(gate_a.PENDING_ACTIONS, AT, WINDOW, (check("plans", True), check("manual_actions", None)),
                               ("Acciones manuales: acciones 3, 5 y 7",))
    lines = report.lines()
    assert lines[0] == "GATE A · PENDIENTE POR ACCIONES MANUALES"
    assert lines[1] == "Ventana: 2026-10-27 a 2026-11-02 (7 días completos, hora de Bogotá)"
    assert "  [SÍ] plans" in lines and "  [PENDIENTE] manual_actions" in lines and "  Falta: Acciones manuales: acciones 3, 5 y 7" in lines
    doc = report.as_json()
    assert doc["gate"] == "gate_a" and doc["verdict"] == "PENDIENTE POR ACCIONES MANUALES" and doc["at"] == AT.isoformat()
    assert doc["recorded_only_if"] == "PASA or NO PASA"


def test_the_waiting_text_names_the_owner_action_that_unblocks() -> None:
    assert "acciones 3, 5 y 7 del propietario" in gate_a._waiting_for(check("manual_actions", None))
    assert "ia_probe" in gate_a._waiting_for(check("verdict_equivalence", None))
    assert gate_a._waiting_for(check("coverage", None)) == "no hay datos para juzgarlo"


def test_the_command_reads_days_and_refuses_the_rest() -> None:
    from scripts import ia_gate

    assert ia_gate.parse_day("2026-11-03") == date(2026, 11, 3)
    with pytest.raises(ValueError, match="not a day"):
        ia_gate.parse_day("3 Nov")
    args = ia_gate.build_parser().parse_args(["evaluate", "--through", "2026-11-03", "--changed-on", "2026-11-01",
                                              "--changed-on", "2026-11-02", "--record", "--json"])
    assert (args.command, args.through, args.changed_on, args.record, args.as_json) == (
        "evaluate", "2026-11-03", ["2026-11-01", "2026-11-02"], True, True)
    assert ia_gate.build_parser().parse_args(["revert", "batch", "--reason", "x"]).gate == "batch"
    with pytest.raises(SystemExit):
        ia_gate.build_parser().parse_args(["revert", "gate_a"])
    assert (ia_gate.OK, ia_gate.NO, ia_gate.CANNOT, ia_gate.PENDING) == (0, 1, 2, 3)

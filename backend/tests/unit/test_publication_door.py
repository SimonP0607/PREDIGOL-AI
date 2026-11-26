"""RP-10.5: the door a pick passes to be published, condition by condition (``fbi.ai.publication_door``) and as C-11 carries it. Whatever the conditions say, the
door never publishes; a condition without evidence is «no evaluada», never «cumplida»; the owner's authorization is always the owner's; no threshold is lowered."""

from __future__ import annotations

import pytest

from fbi.ai import publication_door as pd
from fbi.api.contracts.intelligence.console import PublicationDoor
from fbi.api.services import intelligence_console as ic

GOOD_GATES = {"g_coh": "PASA", "ai_gate_v2": "PASA", "research_v2": "PASA", "gate_b": "PASA"}


def door(**over: object) -> pd.Door:
    args: dict[str, object] = {"gates": GOOD_GATES, "battery": "PASA", "leak_violations": 0, "validated_figures": 3,
                               "value_history": pd.ValueHistory(412, 0.01), "switch_on": False}
    return pd.evaluate(**(args | over))  # type: ignore[arg-type]


def test_with_everything_met_the_door_is_ready_for_authorization_and_still_cannot_publish() -> None:
    d = door()
    assert d.ready is True and d.first_open == "owner_authorization" and d.can_publish is False
    assert [c.state for c in d.conditions][-1] == "solo_dueno" and d.conditions[-1].key == "owner_authorization"
    assert all(c.state == "cumplida" for c in d.conditions[:-1]) and len(d.conditions) == 9


def test_the_door_cannot_be_opened_by_any_input_not_even_the_switch() -> None:
    assert door(switch_on=True).can_publish is False
    assert pd.Door.can_publish.fget(door()) is False  # type: ignore[attr-defined]


def test_today_nothing_is_met_that_the_plan_says_is_not() -> None:
    d = pd.evaluate(gates={"g_coh": "NO PASA", "ai_gate_v2": "RECHAZA", "research_v2": "PENDIENTE POR TIEMPO REAL", "gate_b": "NO EVALUADO"},
                    battery="NO PASA", leak_violations=3, validated_figures=0, value_history=pd.ValueHistory(120, None), switch_on=False)
    states = {c.key: c.state for c in d.conditions}
    assert states == {"validated_figure": "no_cumplida", "value_history": "pendiente", "g_coh": "no_cumplida", "ai_gate_v2": "no_cumplida",
                      "research_v2": "pendiente", "gate_b": "no_evaluada", "battery": "no_cumplida", "leaks": "no_cumplida", "owner_authorization": "solo_dueno"}
    assert d.ready is False and d.first_open == "validated_figure"


def test_a_condition_without_evidence_is_not_evaluated_never_met() -> None:
    d = pd.evaluate(gates={}, battery=None, leak_violations=None, validated_figures=None, value_history=None, switch_on=False)
    assert {c.state for c in d.conditions[:-1]} == {"no_evaluada"} and d.ready is False


def test_the_history_needs_three_hundred_selections_and_a_value_of_zero_or_more() -> None:
    assert door(value_history=pd.ValueHistory(299, 0.05)).conditions[1].state == "pendiente"
    assert door(value_history=pd.ValueHistory(300, 0.0)).conditions[1].state == "cumplida"
    assert door(value_history=pd.ValueHistory(300, -0.0001)).conditions[1].state == "no_cumplida"
    assert door(value_history=pd.ValueHistory(500, None)).conditions[1].state == "no_cumplida"
    assert pd.MIN_VALUE_SELECTIONS == 300


@pytest.mark.parametrize(("status", "state"), [("PASA", "cumplida"), ("NO PASA", "no_cumplida"), ("RECHAZA", "no_cumplida"), ("NO EVALUADO", "no_evaluada"),
                                              ("PENDIENTE POR MUESTRA", "pendiente"), ("PENDIENTE POR DEPENDENCIAS", "pendiente"), ("raro", "no_evaluada"),
                                              (None, "no_evaluada")])
def test_a_gate_status_becomes_a_state(status: str | None, state: str) -> None:
    assert pd.state_of_gate(status)[0] == state


def test_the_json_and_the_contract_agree() -> None:
    d = door()
    doc = d.as_json()
    assert doc["can_publish"] is False and doc["ready"] is True and doc["first_open"] == "owner_authorization"
    contract = PublicationDoor(version=pd.VERSION, switch_on=d.switch_on, ready=d.ready, first_open=doc["first_open"], conditions=doc["conditions"])
    assert contract.can_publish is False and contract.conditions[-1].state == "solo_dueno"


def test_the_contract_refuses_a_door_that_says_ready_with_a_condition_open_or_a_last_condition_that_is_not_the_owners() -> None:
    d = door()
    rows = d.as_json()["conditions"]
    broken = [dict(r) for r in rows]
    broken[0]["state"] = "no_cumplida"
    with pytest.raises(ValueError, match="ready means"):
        PublicationDoor(version="x", switch_on=False, ready=True, first_open="validated_figure", conditions=broken)  # type: ignore[arg-type]
    swapped = [dict(r) for r in rows]
    swapped[-1]["state"] = "cumplida"
    with pytest.raises(ValueError, match="owner"):
        PublicationDoor(version="x", switch_on=False, ready=False, first_open="owner_authorization", conditions=swapped)  # type: ignore[arg-type]


def test_the_console_builds_the_door_from_what_it_read() -> None:
    from fbi.api.contracts.intelligence.base import Missing
    from fbi.api.contracts.intelligence.console import Battery, LeakAudit, ReadFailure, Security

    sec = Security(battery=Battery(verdict="NO PASA", row=1, at=Missing(missing_reason="sin_datos")),
                   leak_audit=LeakAudit(day="2026-11-20", versions=["v9"], rules=22, violations=0, with_violations=[]),  # type: ignore[arg-type]
                   gates=ReadFailure(error="OperationalError"), schema_check=ReadFailure(error="OperationalError"))
    built = ic.door_of(sec, switch_on=False)
    states = {c.key: c.state for c in built.conditions}
    assert built.ready is False and built.can_publish is False and states["battery"] == "no_cumplida" and states["leaks"] == "cumplida"
    assert states["g_coh"] == "no_evaluada", "a panel that could not be read does not say anything is met"
    assert states["validated_figure"] == "no_evaluada" and states["value_history"] == "no_evaluada"
    assert built.first_open == "validated_figure"

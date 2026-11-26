"""RP-8.1: the one graph of the learning cycle. Every state has a next step and a person responsible; the owner's decisions are not the system's; the final
states have no way out; ARCHIVED is reachable from every open state and reopens; and the states of the graph are the ones the database accepts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fbi.research import cycle_state as cs


def test_every_state_is_in_the_graph_and_has_a_next_step() -> None:
    assert set(cs.STATES) == set(cs.TRANSITIONS) == set(cs.NEXT_STEP)
    assert len(cs.STATES) == len(set(cs.STATES))
    assert all(cs.next_step(s).strip() for s in cs.STATES)


def test_final_states_have_no_way_out_and_every_other_state_has_one() -> None:
    for s in cs.FINAL:
        assert cs.allowed(s) == {}
    for s in set(cs.STATES) - cs.FINAL:
        assert cs.allowed(s), f"{s} would be a dead end"


def test_the_owner_decides_what_changes_what_the_system_does() -> None:
    owner_only = [("PROPOSED", "ACCEPTED"), ("PROPOSED", "REJECTED"), ("PROPOSED", "INVESTIGATING"), ("INVESTIGATING", "ACCEPTED"), ("DONE", "PROMOTED"),
                  ("RUNNING", "ARCHIVED"), ("ARCHIVED", "PROPOSED")]
    for a, b in owner_only:
        assert cs.check(a, b, by="owner").who == "owner"
        with pytest.raises(cs.TransitionRefusedError, match="dueño"):
            cs.check(a, b, by="system")


def test_the_system_moves_an_accepted_experiment_through_its_stages_but_never_promotes() -> None:
    for a, b in (("ACCEPTED", "RUNNING"), ("RUNNING", "SHADOW"), ("RUNNING", "DONE"), ("SHADOW", "DONE")):
        assert cs.check(a, b, by="system").who == "system"
        assert cs.check(a, b, by="owner").target == b  # the owner may always do what the system does
    assert "PROMOTED" not in {t for s in ("ACCEPTED", "RUNNING", "SHADOW") for t in cs.allowed(s)}
    with pytest.raises(cs.TransitionRefusedError):
        cs.check("DONE", "PROMOTED", by="system")


def test_a_move_the_graph_does_not_have_is_refused() -> None:
    for a, b in (("PROPOSED", "RUNNING"), ("PROPOSED", "PROMOTED"), ("ACCEPTED", "DONE"), ("SHADOW", "RUNNING"), ("DONE", "RUNNING"), ("ARCHIVED", "ACCEPTED")):
        with pytest.raises(cs.TransitionRefusedError):
            cs.check(a, b, by="owner")
    with pytest.raises(cs.TransitionRefusedError, match="final"):
        cs.check("REJECTED", "PROPOSED", by="owner")
    with pytest.raises(cs.TransitionRefusedError, match="desconocido"):
        cs.check("PROPOSED", "LOST", by="owner")
    with pytest.raises(cs.TransitionRefusedError, match="desconocido"):
        cs.check("LOST", "PROPOSED", by="owner")


def test_nothing_alive_is_stranded_it_can_always_be_put_away_and_an_archived_one_comes_back() -> None:
    for s in cs.OPEN:
        assert "ARCHIVED" in cs.reachable(s) | {s}, f"{s} cannot be archived"
    assert cs.allowed("ARCHIVED") == {"PROPOSED": "owner", "INVESTIGATING": "owner"}
    assert {"ACCEPTED", "RUNNING", "SHADOW", "DONE", "PROMOTED"} <= cs.reachable("PROPOSED")
    assert "PROMOTED" not in cs.reachable("REJECTED")


def test_the_states_of_the_graph_are_the_ones_the_database_accepts() -> None:
    root = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    text = (root / "0183_experiment_verdicts_and_archived.py").read_text(encoding="utf-8")
    old = re.search(r'OLD_STATUSES = "([^"]+)"', text)
    assert old is not None
    accepted = set(re.findall(r"'([A-Z]+)'", old.group(1))) | {"ARCHIVED"}
    assert accepted == set(cs.STATES)


def test_the_evolution_module_only_uses_states_of_the_graph() -> None:
    from fbi.research import evolution

    assert set(evolution.DECIDABLE) <= set(cs.STATES)
    assert set(evolution.STAGES) <= set(cs.STATES)
    for a, tos in evolution.DECIDABLE.items():
        for b in tos:
            cs.check(a, b, by="owner")
    pairs = (("ACCEPTED", "RUNNING"), ("RUNNING", "SHADOW"), ("SHADOW", "DONE"))
    for a, b in pairs:
        cs.check(a, b, by="system")

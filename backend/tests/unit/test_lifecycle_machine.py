"""IA-068 (AD-D02): the state machine of a selection - its closed lists equal UX's contract and the table's CHECKs, no move outside the
table, «descartada» and «evaluada» without a way out, a model that only takes a selection down, nothing public without the owner."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest

from fbi.api.contracts.intelligence import vocab
from fbi.lifecycle import machine
from fbi.lifecycle.machine import IllegalTransitionError, Step

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0142_selection_lifecycle.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0142", MIGRATION)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _step(state: str, previous: str | None) -> Step:
    """A legal-looking step into ``state`` (its first reason; the extras a state needs)."""
    reason = machine.REASONS[state][0]
    result = "win" if state == "liquidada" else None
    return Step(state, reason, settlement_result=result)


def test_the_states_are_the_closed_list_of_the_contract() -> None:
    assert machine.STATES == get_args(vocab.LifecycleState) == vocab.VOCABULARIES["lifecycle_state"]
    assert len(machine.STATES) == 10
    assert set(machine.REASONS) == set(machine.STATES) and set(machine.TRANSITIONS) == {None, *machine.STATES}
    assert tuple(r for r in get_args(vocab.SettlementResult) if r != "pending") == machine.SETTLED_RESULTS
    assert get_args(vocab.EvaluationStep) == machine.EVALUATIONS


def test_the_migration_holds_the_same_rules_as_the_machine() -> None:
    m = _migration()
    assert m.STATES == machine.STATES and m.BLOCKERS == machine.BLOCKERS and m.ACTORS == machine.ACTORS
    assert {k: tuple(v) for k, v in m.REASONS.items()} == dict(machine.REASONS)
    assert {(a, b) for a, bs in m.MOVES.items() for b in bs} == set(machine.pairs())
    assert m.RESULTS == machine.SETTLED_RESULTS and m.EVALUATIONS == machine.EVALUATIONS
    assert m.revision == "0142" and isinstance(m.down_revision, str), "one parent: re-chaining it is one line of the migration"


def test_discarded_and_evaluated_have_no_way_out_and_play_only_settles() -> None:
    assert machine.TRANSITIONS["descartada"] == machine.TRANSITIONS["evaluada"] == frozenset()
    assert machine.TRANSITIONS["en_juego"] == {"liquidada"} and machine.TRANSITIONS["liquidada"] == {"evaluada"}
    assert machine.TRANSITIONS[None] == {"detectado"}
    assert "en_juego" in machine.TRANSITIONS["confirmada_sombra"]
    assert not [s for s in machine.STATES if s != "confirmada_sombra" and "en_juego" in machine.TRANSITIONS[s]], \
        "only a confirmed selection goes into play"
    for terminal in machine.TERMINAL:
        for target in machine.STATES:
            with pytest.raises(IllegalTransitionError):
                machine.check(terminal, _step(target, terminal))


def test_every_move_outside_the_table_is_refused_and_every_move_inside_is_taken() -> None:
    for a in (None, *machine.STATES):
        for b in machine.STATES:
            found = machine.problems(a, _step(b, a))
            if b in machine.TRANSITIONS[a]:
                assert found == [], (a, b, found)
            else:
                assert any("not a move of the cycle" in p for p in found), (a, b)


def test_random_walks_of_the_table_are_legal_chains_and_a_single_foreign_move_breaks_them() -> None:
    """Property test (no hypothesis in the local environment: a seeded generator, 2.000 walks)."""
    rng = random.Random(68)
    for _ in range(2000):
        chain: list[Step] = []
        state: str | None = None
        for _ in range(rng.randint(1, 12)):
            options = sorted(machine.TRANSITIONS[state])
            if not options:
                break
            nxt = rng.choice(options)
            reason = rng.choice([r for r in machine.REASONS[nxt] if r != machine.AUTHORISED])
            chain.append(Step(nxt, reason, settlement_result="loss" if nxt == "liquidada" else None))
            state = nxt
        machine.check_chain(chain)
        wrong = sorted(set(machine.STATES) - machine.TRANSITIONS[state])
        if wrong:
            bad = rng.choice(wrong)
            with pytest.raises(IllegalTransitionError):
                machine.check_chain([*chain, _step(bad, state)])


def test_a_reason_belongs_to_its_state() -> None:
    assert machine.problems(None, Step("detectado", "candidato_nuevo")) == []
    assert machine.problems(None, Step("detectado", "cumple_todo"))
    assert machine.problems("en_evaluacion", Step("descartada", "inventado"))
    assert set(machine.BLOCKERS) <= set(machine.REASONS["en_evaluacion"]) & set(machine.REASONS["retirada"]) \
        & set(machine.REASONS["descartada"])
    assert len(machine.reason_pairs()) == sum(len(v) for v in machine.REASONS.values())


def test_a_model_only_takes_a_selection_down() -> None:
    for a in machine.OPEN:
        for b in machine.TRANSITIONS[a]:
            found = machine.problems(a, Step(b, machine.REASONS[b][0], actor="model"))
            if b in machine.DOWNWARD:
                assert not [p for p in found if "model" in p], (a, b)
            else:
                assert any("model may only take" in p for p in found), (a, b)


def test_the_owner_only_authorises_a_confirmed_selection_with_a_signature() -> None:
    sig = "Autorizo, el dueño, 2026-11-20"
    ok = Step("confirmada_sombra", machine.AUTHORISED, actor="owner", owner_signature=sig)
    assert machine.problems("confirmada_sombra", ok) == []
    assert machine.problems("en_evaluacion", Step("confirmada_sombra", machine.AUTHORISED, actor="owner", owner_signature=sig))
    assert machine.problems("confirmada_sombra", Step("confirmada_sombra", machine.AUTHORISED, actor="owner"))
    assert machine.problems("confirmada_sombra", Step("confirmada_sombra", machine.AUTHORISED))
    assert machine.problems("confirmada_sombra", Step("en_juego", "saque", actor="owner", owner_signature=sig))
    assert machine.problems("confirmada_sombra", Step("en_juego", "saque", owner_signature=sig))


def test_a_settled_row_carries_its_result_and_only_it() -> None:
    assert machine.problems("en_juego", Step("liquidada", "resultado")) != []
    assert machine.problems("en_juego", Step("liquidada", "resultado", settlement_result="pending")) != []
    assert machine.problems("en_juego", Step("liquidada", "resultado", settlement_result="half_win")) == []
    assert machine.problems("liquidada", Step("evaluada", "evaluacion_posterior", settlement_result="win")) != []
    assert machine.problems("detectado", Step("en_evaluacion", "en_curso", evaluation_version=2)) != []
    assert machine.problems("detectado", Step("en_evaluacion", "en_curso", evaluation="E1", evaluation_version=1)) == []


def _chain(*states: str) -> list[Step]:
    return [_step(s, None) for s in states]


def test_nothing_is_public_without_the_owner() -> None:
    sig = "Autorizo, el dueño, 2026-11-20"
    auth = Step("confirmada_sombra", machine.AUTHORISED, actor="owner", owner_signature=sig)
    shadow = _chain("detectado", "en_evaluacion", "confirmada_sombra", "en_juego", "liquidada", "evaluada")
    for i in range(1, len(shadow) + 1):
        assert machine.public_state(shadow[:i]) is None
    authorised = [*shadow[:3], auth, *shadow[3:]]
    assert [machine.public_state(authorised[:i]) for i in range(3, len(authorised) + 1)] == \
        [None, "publicada", "en_juego", "liquidada", "liquidada"]
    lost = [*shadow[:3], auth, _step("retirada", None), _step("confirmada_sombra", None)]
    assert machine.public_state(lost) is None, "withdrawn and back: the owner signs again"


def test_the_public_state_is_the_contracts_own() -> None:
    for state in machine.STATES:
        assert machine.PUBLIC.get(state) == vocab.public_state_of(state, authorised=True)
        assert vocab.public_state_of(state, authorised=False) is None

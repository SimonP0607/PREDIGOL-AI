"""IA-017: the two defects of decision-v1 that decision-v2 found in shadow, each reproduced, and the property that closes the second.

* correlation (8) broke a tie of scores on the order the rows came in (``CANDIDATES_SQL`` had no ORDER BY): two runs over the same data
  could keep different selections. Now the tie breaks on (market, selection, line), decision-v2's rule, whatever the order;
* a negative context on a selection with no validated edge ended as CAUTELA, i.e. the context RAISED it from INVESTIGACION. Now the state is
  the more severe of the edge gate (read without the context) and the context: over every (state, context) pair nothing is more
  permissive than it was, and no context is above the state without it.

On the real ``evaluate`` and ``correlate`` (no database); the helpers are ``test_decision_rules``'s."""

from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Any

import pytest

from fbi.core.decision_versions import DECISION_CORE
from fbi.intel import decision
from fbi.intel.decision import RANK, Evaluated, World, evaluate

from .test_decision_rules import MODEL, STALE, effect, key_of, row, run, world

# -- defect 1: a tie in correlation -------------------------------------------------------------------------------------------------------

def tied() -> tuple[Evaluated, Evaluated]:
    """Two approved selections of ONE match with the same score (the same row at two lines: nothing in the score reads the line)."""
    w = world(rule_clv=-0.01)
    a = evaluate(w, key_of(1), {MODEL: row()})
    b = evaluate(w, key_of(1, Decimal("1.5")), {MODEL: row(line=Decimal("1.5"))})
    assert a.score is not None and b.score is not None and a.score.total == b.score.total
    assert a.state in decision.APPROVED and b.state in decision.APPROVED
    return a, b


def test_a_tie_of_scores_keeps_the_same_selection_whatever_order_the_rows_came_in() -> None:
    """Fails before IA-017: ``correlate`` kept the first it was given, so the order the database returned the rows in decided."""
    kept = {}
    for order in ((0, 1), (1, 0)):
        pair = tied()
        decision.correlate([pair[i] for i in order])
        [winner] = [e for e in pair if e.state in decision.APPROVED]
        kept[order] = winner.key
    assert kept[(0, 1)] == kept[(1, 0)] == key_of(1, Decimal("1.5")), (
        "the same selection both times, by decision-v2's rule: (market, selection, line) - the lower line first", kept)
    for order in ((0, 1), (1, 0)):
        pair = tied()
        decision.correlate([pair[i] for i in order])
        [winner] = [e for e in pair if e.state in decision.APPROVED]
        [loser] = [e for e in pair if e.state == "CAUTELA"]
        assert "correlated_same_match" in loser.reasons and effect(loser, 8) == "CAUTELA"
        [flt] = [f for f in loser.filters if f["key"] == "correlation"]
        assert flt["data"]["tie"] is True and "empate de score" in flt["why"] and flt["data"]["best"][:2] == ["OU", "Over"]
        assert Decimal(flt["data"]["best"][2]) == Decimal("1.5")
        [won] = [f for f in winner.filters if f["key"] == "correlation"]
        assert won["ok"] is True and won["data"]["tie"] is True


def test_the_order_of_correlation_is_decision_v2s_order() -> None:
    a, b = tied()
    assert decision.correlation_order(b) < decision.correlation_order(a)
    worse = evaluate(world(rule_clv=-0.01), key_of(1, Decimal("0.5")), {MODEL: row(line=Decimal("0.5"), books=4)})
    assert worse.score is not None and a.score is not None and worse.score.total < a.score.total
    assert decision.correlation_order(a) < decision.correlation_order(worse), "the score first, the selection only on a tie"


def test_the_candidates_are_read_in_a_total_order() -> None:
    """The query the decisions come from orders its rows by the selection's key and the model, after its last join."""
    tail = decision.CANDIDATES_SQL.rsplit("LEFT JOIN lc", 1)[1]
    assert "ORDER BY lp.fixture_id, lp.market_key, lp.selection, lp.line, lp.model_name" in tail


# -- defect 2: a context never raises a state ---------------------------------------------------------------------------------------------

CONTEXTS: dict[str, dict[str, Any]] = {
    "review REJECT": {"review": "REJECT"},
    "review DOWNGRADE": {"review": "DOWNGRADE"},
    "key absence reported": {"rules": {"key_absences_pick_side": "hard"}},
    "key absence confirmed": {"rules": {"key_absences_pick_side": "hard"}, "lineups": True},
    "match not playable": {"rules": {"fixture_not_playable": "hard"}},
}


@pytest.mark.parametrize("name", ["review REJECT", "review DOWNGRADE", "key absence reported"])
def test_a_negative_context_on_a_market_without_a_validated_edge_stays_in_investigation(name: str) -> None:
    """Fails before IA-017: these ended as CAUTELA - from INVESTIGACION up to the less severe state."""
    assert run(world(edge=False)).state == "INVESTIGACION"
    e = run(world(edge=False, **CONTEXTS[name]))
    assert e.state == "INVESTIGACION", (name, e.reasons)
    assert "edge_not_validated" in e.reasons and effect(e, 6) == "CAUTELA" and effect(e, 10) == "INVESTIGACION"
    assert e.stake.units == 0 and not e.premium and not e.parlay_eligible
    assert run(world(edge=True, **CONTEXTS[name])).state == "CAUTELA", "with a validated edge the context's CAUTELA stands"


@pytest.mark.parametrize("name", ["key absence confirmed", "match not playable"])
def test_a_context_that_rejects_still_rejects_without_a_validated_edge(name: str) -> None:
    e = run(world(edge=False, **CONTEXTS[name]))
    assert e.state == "RECHAZADO" and effect(e, 6) == "RECHAZADO" and "edge_not_validated" in e.reasons


def test_a_risk_or_a_stale_final_price_is_still_a_caution_whatever_the_edge() -> None:
    """The gate only stands between a selection and APROBADO: what the other filters lowered to CAUTELA stays CAUTELA (decision-v2 too)."""
    for kw in ({"width": decision.RISK_MAX_WIDTH + 0.05}, {"minutes": 80, "price_age": STALE}):
        for ctx in (None, "review REJECT", "review DOWNGRADE", "key absence reported"):
            e = run(world(edge=False, **({} if ctx is None else CONTEXTS[ctx])), **kw)
            assert e.state == "CAUTELA" and "edge_not_validated" not in e.reasons, (kw, ctx, e.reasons)


def old_final_state(others: list[str], context: list[str], *, edge_ok: bool) -> str:
    """decision-v1's rule before IA-017: the worst of everything, then the gate only on an APROBADO."""
    state = min([*others, *context], key=RANK.__getitem__, default="APROBADO")
    return "INVESTIGACION" if state == "APROBADO" and not edge_ok else state


STATES = tuple(RANK)
SOME = [[], *([s] for s in STATES), *([a, b] for a, b in itertools.combinations(STATES, 2))]
"""Every state the filters but the context can give, alone and two by two, and none."""


def test_over_every_state_and_context_the_result_is_the_more_severe_and_never_more_permissive() -> None:
    """The property, exhaustively: every effect the other filters can give x every effect the context can give x edge validated or not."""
    for others, context, edge_ok in itertools.product(SOME, [[], *([s] for s in STATES)], (True, False)):
        state, gated = decision.final_state(others, context, edge_ok=edge_ok)
        without = decision.final_state(others, [], edge_ok=edge_ok)[0]
        assert RANK[state] <= RANK[without], ("the context raised the state", others, context, edge_ok)
        assert all(RANK[state] <= RANK[s] for s in context), ("the state is above the context's own effect", others, context, edge_ok)
        assert state == decision.worst_state([without, *context]), ("the more severe of the two", others, context, edge_ok)
        assert RANK[state] <= RANK[old_final_state(others, context, edge_ok=edge_ok)], ("more permissive than before", others, context)
        assert gated == (decision.worst_state(others) == "APROBADO" and not edge_ok)
        if edge_ok:
            assert state == old_final_state(others, context, edge_ok=True), "with a validated edge nothing changes"


def norm(state: str) -> str:
    return "APROBADO" if state in decision.APPROVED else state


GRID: dict[str, tuple[Any, ...]] = {
    "edge": (True, False), "calibrated": (True, False), "rule_clv": (0.03, -0.01),
    "row": ({}, {"width": decision.RISK_MAX_WIDTH + 0.05}, {"minutes": 80, "price_age": STALE},
            {"price_age": decision.MAX_PRICE_AGE * 2}, {"p_model": 0.47, "p_fair": 0.46}, {"books": decision.MIN_BOOKS - 1},
            {"odds": decision.RISK_MAX_ODDS + 0.4, "p_model": 0.55, "p_fair": 0.30}, {"status": "PST"})}


def test_on_the_real_filters_no_context_raises_a_state_and_nothing_is_more_permissive_than_before() -> None:
    seen: set[str] = set()
    for edge, calibrated, rule_clv, kw in itertools.product(*GRID.values()):
        for name, ctx in CONTEXTS.items():
            quiet: dict[str, Any] = {"lineups": ctx.get("lineups", False)}
            base = run(world(edge=edge, calibrated=calibrated, rule_clv=rule_clv, **quiet), **kw)
            e = run(world(edge=edge, calibrated=calibrated, rule_clv=rule_clv, **ctx), **kw)
            assert RANK[norm(e.state)] <= RANK[norm(base.state)], (name, edge, calibrated, kw, base.state, e.state)
            assert RANK[norm(e.state)] <= RANK[str(effect(e, 6))], (name, kw, e.state)
            others = [str(f["effect"]) for f in e.filters if f.get("effect") and f["n"] not in (6, 10)]
            before = old_final_state(others, [str(effect(e, 6))], edge_ok=edge)
            assert RANK[norm(e.state)] <= RANK[before], ("more permissive than decision-v1 was", name, edge, kw)
            seen.add(norm(e.state))
    assert seen == set(STATES) - {"APROBADO"}, seen


# -- the label: rows stay one comparable series -------------------------------------------------------------------------------------------

def test_the_rules_have_a_label_of_their_own_and_the_layer_keeps_its_version() -> None:
    """``decision_version`` names the layer every reader binds: it does not change, so old and new rows stay one series. The rules'
    revision is carried in each new row's filter 10 and ``input_hash``; the commit is in ``code_version``."""
    assert decision.VERSION == DECISION_CORE == "decision-v1" and decision.RULES == "decision-v1.1"
    for w in (world(), world(edge=False), world(review="REJECT")):
        e = run(w)
        [final] = [f for f in e.filters if f["key"] == "final"]
        assert final["data"]["rules"] == decision.RULES, e.state
    e = run()
    digest = decision.input_hash(e)
    assert digest == decision.input_hash(run()), "the same input, the same digest"
    rules, decision.RULES = decision.RULES, "decision-v1.0"  # type: ignore[misc]
    try:
        assert decision.input_hash(e) != digest, "the digest says which rules decided"
    finally:
        decision.RULES = rules  # type: ignore[misc]


def test_a_world_built_here_is_the_one_the_rules_file_uses() -> None:
    assert isinstance(world(), World)

"""The Picks board reads PrediGol Intelligence's decision (plan PICKS, F3) - over HTTP, on the example picks of test_pick_states.

    A  published, value now   Intelligence APROBADO       -> the only card a reader is shown
    B  published, value now   review DOWNGRADE (board)    Intelligence CAUTELA
    C  published, value now   review REJECT (board)       Intelligence RECHAZADO
    D  published, value now   Intelligence INVESTIGACION (the edge of the market is not validated) -> not recommended by it
    E  published, price 1.70  no value now
    S  a shadow pick          Intelligence CAUTELA        -> the owner's preview groups it as CAUTION

The switch ``FBI_PICKS_SOURCE`` is off by default: the board is then what it was.
"""

# ruff: noqa: F811  (pytest fixtures imported from test_pick_states are used by name as parameters)
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.integration.helpers import scalar
from tests.integration.test_pick_states import NOW, World, client, data, states, world  # noqa: F401

pytestmark = pytest.mark.integration

P_CAL = Decimal("0.48")


def decide(world: World, name: str, state: str, reasons: list[str], *, p_cal: Decimal | None = P_CAL) -> None:
    fid = world.fixtures[name]
    ko = scalar(world.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)))
    stake = 0 if state in ("RECHAZADO", "INVESTIGACION") else 1
    ev = None if p_cal is None else (p_cal * Decimal("2.30") - 1).quantize(Decimal("0.000001"))
    world.db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
        "pick_id, model_name, odds, price_at, p_model, p_cal, p_market, ev_cal, edge_cal, stake_units, filters, state, reasons, "
        "context_status, input_hash) VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', 'Home', 0, %s, 'dixon_coles', 2.30, %s, 0.50, "
        "%s, 0.43, %s, %s, %s, '[]', %s, %s, 'PENDING', %s)",
        (NOW - timedelta(hours=1), fid, ko, world.picks[name], NOW - timedelta(hours=1), p_cal, ev,
         None if p_cal is None else p_cal - Decimal("0.43"), stake, state, reasons, f"src-{name}-{state}"))


@pytest.fixture()
def decided(world: World) -> World:
    decide(world, "A", "APROBADO", [])
    decide(world, "B", "CAUTELA", ["ai_downgrade"])
    decide(world, "C", "RECHAZADO", ["ev_cal_below"])
    decide(world, "D", "INVESTIGACION", ["edge_not_validated"])
    decide(world, "S", "CAUTELA", ["risk"])
    return world


def by_name(cards: list[dict[str, Any]], world: World) -> dict[str, dict[str, Any]]:
    names = {v: k for k, v in world.picks.items()}
    return {names[c["pick_id"]]: c for c in cards}


def test_with_the_switch_off_the_board_is_what_it_was(decided: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PICKS_SOURCE", raising=False)
    board = data(client(decided.db), "/api/v1/picks")
    assert board["decision_source"] == "legacy"
    assert sorted(states(board["picks"], decided.picks)) == ["A", "D"]
    cards = by_name(board["picks"], decided)
    assert cards["A"]["decision"] is None and Decimal(cards["A"]["p_model"]) == Decimal("0.5")


def test_a_reader_is_shown_only_what_the_board_and_intelligence_both_recommend(decided: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    board = data(client(decided.db), "/api/v1/picks")
    assert board["decision_source"] == "intelligence"
    assert states(board["picks"], decided.picks) == {"A": ("RECOMMENDED", "approved", False)}, \
        "D was recommended by the board, but Intelligence does not recommend it: the switch only takes cards away"
    assert board["withheld"] == 4, "B, C, D and E are counted, never shown"
    assert [c["pick_id"] for c in board["top"]] == [decided.picks["A"]]


def test_the_card_carries_the_calibrated_probability_and_the_value_computed_with_it(decided: World,
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    a = by_name(data(client(decided.db), "/api/v1/picks")["picks"], decided)["A"]
    assert Decimal(a["p_model"]) == P_CAL, "the number Intelligence and the Match Center give"
    assert Decimal(a["decision"]["p_raw"]) == Decimal("0.5"), "the raw one stays, as «sin calibrar»"
    assert (a["decision"]["state"], a["decision"]["checkpoint"]) == ("RECOMMENDED", "T-3h")
    odds = Decimal(a["best_odds"])
    assert Decimal(a["ev"]) == (P_CAL * odds - 1).quantize(Decimal("0.000001")), "EV at the price now, with the calibrated probability"
    assert Decimal(a["edge"]) == (P_CAL - Decimal(a["p_market"])).quantize(Decimal("0.000001"))


def test_the_owner_sees_every_card_with_both_states(decided: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    preview = data(client(decided.db, "SUPER_ADMIN"), "/api/v1/picks", preview="shadow")
    assert preview["withheld"] == 0
    got = states(preview["picks"], decided.picks)
    assert got["A"] == ("RECOMMENDED", "approved", False)
    assert got["B"][0] == "CAUTION" and got["C"][0] == "NOT_RECOMMENDED"
    assert got["D"] == ("EVALUATION", "evaluation", False), "recommended by the board, parked by Intelligence"
    assert got["E"] == ("NOT_RECOMMENDED", "no_value_now", False), "the board's own, more specific reason"
    assert got["S"] == ("CAUTION", "downgraded", False), "a shadow pick the owner sees grouped by Intelligence's state"
    cards = by_name(preview["picks"], decided)
    assert (cards["D"]["decision"]["state"], cards["D"]["decision"]["reason"]) == ("ABSTAIN", "edge_not_validated")
    assert (cards["S"]["decision"]["state"], cards["S"]["decision"]["reason"]) == ("CAUTION", "risk")


def test_a_selection_without_a_calibrated_probability_shows_no_value(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    decide(world, "A", "INVESTIGACION", ["not_calibrated"], p_cal=None)
    cards = by_name(data(client(world.db, "SUPER_ADMIN"), "/api/v1/picks", preview="shadow")["picks"], world)
    a, b = cards["A"], cards["B"]
    assert (a["ev"], a["edge"], a["value_now"], a["value_reason"]) == (None, None, False, "no_calibrated_probability")
    assert Decimal(a["p_model"]) == Decimal("0.5"), "the raw probability, to be shown as such"
    assert b["decision"] is None and b["user_status"] != "RECOMMENDED", "nothing decided B: nothing approves it"

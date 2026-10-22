"""The referee in the post-mortem (plan F3, ``pm-v5``): "cards above / below the referee's usual" uses the average of HIS matches
under every spelling, not of the matches whose facts carried the same string, and two men who write the same initial and surname
are not one."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from fbi.intel import postmortem
from fbi.people import referees as store
from tests.integration.test_referee_identity_store import World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_referee_in_the_packet import played, settle

pytestmark = pytest.mark.integration


def decision_on(w: World, fixture_id: int) -> tuple[int, Any]:
    """A decision on the match and its outcome, so the post-mortem has something to judge. Returns (decision id, the moment to judge at)."""
    kickoff = w.one("SELECT kickoff_at FROM core.fixtures WHERE id = %s", fixture_id)
    row = w.db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
        "model_name, odds, p_model, p_cal, p_market, filters, state, context_status, input_hash) "
        "VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', 'Home', 0, 'dixon_coles', 2.10, 0.50, 0.50, 0.46, %s, 'CAUTELA', 'PENDING', %s) "
        "RETURNING id", (kickoff - timedelta(hours=3), fixture_id, kickoff, Jsonb([]), f"referee-{fixture_id}")).fetchone()
    assert row is not None
    decision = int(row[0])
    w.db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, close_p_fair, "
                 "close_odds, close_as_of, clv, version, computed_at) VALUES (%s, %s, 'win', 1.1, 0, 0.46, 2.0, %s, 0.02, 'outcome-v1', %s)",
                 (decision, kickoff + timedelta(hours=3), kickoff, kickoff + timedelta(hours=4)))
    return decision, kickoff + timedelta(hours=6)


def causes_of(w: World, decision: int) -> dict[str, dict[str, Any]]:
    row = w.db.execute("SELECT causes, evidence FROM intel.postmortems WHERE decision_id = %s AND version = %s",
                       (decision, postmortem.VERSION)).fetchone()
    assert row is not None
    return {c["code"]: c for c in row[0]}


def evidence_of(w: World, decision: int) -> dict[str, Any]:
    row = w.db.execute("SELECT evidence FROM intel.postmortems WHERE decision_id = %s AND version = %s",
                       (decision, postmortem.VERSION)).fetchone()
    assert row is not None
    return dict(row[0])


def a_referee_with_five_matches_of_four_cards(w: World) -> None:
    """Michael Oliver: three matches as 'Michael Oliver', two as 'M. Oliver' - under the string, neither spelling has the five."""
    for day, who, country in ((1, "Michael Oliver", "England"), (2, "Michael Oliver", "England"), (3, "Michael Oliver", "England"),
                              (4, "M. Oliver", None), (5, "M. Oliver", None)):
        played(w, "England", day, who, country, yellow=(2, 2))


def test_the_usual_of_a_referee_is_the_average_of_his_matches_under_every_spelling(world: World) -> None:  # noqa: F811
    a_referee_with_five_matches_of_four_cards(world)
    target = played(world, "England", 60, "M. Oliver", yellow=(5, 4))  # nine cards in the match the decision is on
    store.build(world.db, apply=True)
    decision, at = decision_on(world, target)

    assert postmortem.run_postmortems(world.db, at=at) == 1
    causes = causes_of(world, decision)
    assert causes["cards_above_referee"]["cards"] == 9 and causes["cards_above_referee"]["referee_avg"] == 4.0
    evidence = evidence_of(world, decision)
    assert evidence["referee"] == "Michael Oliver" and isinstance(evidence["referee_id"], int)


def test_a_homonym_in_another_country_does_not_move_the_average(world: World) -> None:  # noqa: F811
    a_referee_with_five_matches_of_four_cards(world)
    for day in range(6, 12):  # a Dutch 'M. Oliver' who shows far more cards
        played(world, "Netherlands", day, "M. Oliver", yellow=(5, 5))
    target = played(world, "England", 60, "M. Oliver", yellow=(5, 4))
    store.build(world.db, apply=True)
    decision, at = decision_on(world, target)

    postmortem.run_postmortems(world.db, at=at)
    assert causes_of(world, decision)["cards_above_referee"]["referee_avg"] == 4.0


def test_a_match_the_identity_has_not_seen_keeps_the_string(world: World) -> None:  # noqa: F811
    for day in range(1, 6):
        played(world, "England", day, "Anna Referee", yellow=(2, 2))
    store.build(world.db, apply=True)
    target = played(world, "England", 60, "Anna Referee", yellow=(5, 4))  # arrived after the last pass
    decision, at = decision_on(world, target)
    assert world.referee_of(target) is None

    postmortem.run_postmortems(world.db, at=at)
    assert causes_of(world, decision)["cards_above_referee"]["referee_avg"] == 4.0
    evidence = evidence_of(world, decision)
    assert evidence["referee"] == "Anna Referee" and evidence["referee_id"] is None


def test_the_post_mortem_of_a_match_without_a_referee_has_no_such_cause(world: World) -> None:  # noqa: F811
    a_referee_with_five_matches_of_four_cards(world)
    target = world.fixture("England", 60)
    settle(world, target, yellow=(5, 4))
    store.build(world.db, apply=True)
    decision, at = decision_on(world, target)

    postmortem.run_postmortems(world.db, at=at)
    assert "cards_above_referee" not in causes_of(world, decision)
    assert evidence_of(world, decision)["referee_id"] is None and evidence_of(world, decision)["referee"] is None


def test_the_average_needs_five_matches(world: World) -> None:  # noqa: F811
    for day in range(1, 5):
        played(world, "England", day, "Michael Oliver", "England", yellow=(2, 2))  # four matches
    target = played(world, "England", 60, "Michael Oliver", "England", yellow=(5, 4))
    store.build(world.db, apply=True)
    decision, at = decision_on(world, target)
    postmortem.run_postmortems(world.db, at=at)
    assert "cards_above_referee" not in causes_of(world, decision)

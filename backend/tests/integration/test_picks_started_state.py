"""«Ya empezaron» keeps «solo verde» after kick-off (plan PICKS, L1) and reads Intelligence's decision (F3) - over HTTP, on the
example picks of test_pick_states, their matches moved to half an hour ago:

    A  review APPROVE      B  review DOWNGRADE      C  review REJECT      D  no review      K  no review      S  a shadow pick

A reader is shown a started pick only while it is RECOMMENDED, exactly as before kick-off; the owner's preview shows every one,
labelled. With ``FBI_PICKS_SOURCE=intelligence`` the state is merged with the decision Intelligence had at the whistle, and the
numbers of the card are computed with its calibrated probability at the price taken.
"""

# ruff: noqa: F811  (pytest fixtures imported from test_pick_states are used by name as parameters)
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.integration.test_pick_states import NOW, World, client, data, states, world  # noqa: F401
from tests.integration.test_picks_source import decide

pytestmark = pytest.mark.integration

KICKOFF = NOW - timedelta(minutes=30)


@pytest.fixture()
def started(world: World) -> World:
    for name in "ABCDKS":
        world.db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = '1H', status_group = 'live' WHERE id = %s",
                         (KICKOFF, world.fixtures[name]))
    return world


def by_name(cards: list[dict[str, Any]], world: World) -> dict[str, dict[str, Any]]:
    names = {v: k for k, v in world.picks.items()}
    return {names[c["pick_id"]]: c for c in cards}


def test_a_reader_is_not_shown_a_started_pick_the_review_downgraded_or_rejected(started: World,
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PICKS_SOURCE", raising=False)
    got = states(data(client(started.db), "/api/v1/picks/started"), started.picks)
    assert got == dict.fromkeys("ADK", ("RECOMMENDED", "value", True)), "B (DOWNGRADE) and C (REJECT) are not shown after kick-off either"


def test_the_owner_sees_every_started_pick_with_its_state(started: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PICKS_SOURCE", raising=False)
    got = states(data(client(started.db, "SUPER_ADMIN"), "/api/v1/picks/started", preview="shadow"), started.picks)
    assert got["B"][:2] == ("CAUTION", "downgraded") and got["C"][:2] == ("NOT_RECOMMENDED", "rejected")
    assert got["S"][:2] == ("EVALUATION", "evaluation"), "a shadow pick is never a recommendation"
    assert got["A"][:2] == ("RECOMMENDED", "value")


def test_with_intelligence_a_reader_is_shown_only_what_it_recommended_at_kick_off(started: World,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    decide(started, "A", "APROBADO", [])
    decide(started, "D", "INVESTIGACION", ["edge_not_validated"])
    cards = data(client(started.db), "/api/v1/picks/started")
    assert states(cards, started.picks) == {"A": ("RECOMMENDED", "approved", False)}, "D parked, K undecided: not shown"


def test_with_intelligence_the_numbers_of_a_started_pick_use_the_calibrated_probability(started: World,
                                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    decide(started, "A", "APROBADO", [])
    decide(started, "D", "INVESTIGACION", ["edge_not_validated"])
    cards = by_name(data(client(started.db, "SUPER_ADMIN"), "/api/v1/picks/started", preview="shadow"), started)
    a, d = cards["A"], cards["K"]
    assert Decimal(a["p_model"]) == Decimal("0.48") and Decimal(a["decision"]["p_raw"]) == Decimal("0.5")
    assert Decimal(a["edge"]) == Decimal("0.48") - Decimal(a["p_market"])
    assert Decimal(a["ev"]) == (Decimal("0.48") * Decimal(a["odds_taken"]) - 1).quantize(Decimal("0.000001"))
    assert d["decision"] is None and Decimal(d["p_model"]) == Decimal("0.5"), "nothing decided K: the numbers stay as taken"

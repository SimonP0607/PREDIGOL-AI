"""Plan F11 - the dependence between the families reads the three histories through the door of the families, and keeps the matches that have
all three counts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.families import dependence

from .knowledge_world import KICKOFF
from .test_market_catalogue import w, world  # noqa: F401  (the hand-built world and its ids)

pytestmark = pytest.mark.integration

LATER = KICKOFF + timedelta(days=30)
EARLIER = KICKOFF - timedelta(days=1)


def test_the_three_histories_are_read_and_joined_by_fixture(db: psycopg.Connection[Any], world: dict[str, int]) -> None:  # noqa: F811
    histories = dependence.read(db, since=EARLIER, cutoff=LATER)
    assert set(histories) == {"goals", "corners", "cards"}
    rows, coverage = dependence.join(histories)
    assert coverage["goals"] > coverage["corners"] >= coverage["joined"] == 2, "more matches have a score than have statistics"
    assert {r.fixture_id for r in rows} == {world["plain"], world["dismissals"]}, "the two matches that have the goals, the corners and the cards"
    got = {r.fixture_id: r for r in rows}
    assert got[world["plain"]].corners == (7, 4) and got[world["dismissals"]].corners == (5, 6)
    assert got[world["plain"]].cards == (2, 1) and got[world["dismissals"]].cards == (2, 1), "the yellow cards plus the reds of the statistics"
    assert got[world["plain"]].goals == (2, 1), "the score after 90 minutes (1-0 at the break, 1-1 in the second half)"
    assert all(r.competition_id == got[world["plain"]].competition_id for r in rows)
    assert dependence.join(dependence.read(db, since=EARLIER, cutoff=KICKOFF + timedelta(hours=1)))[0] == [], "nothing whose result is not yet known"

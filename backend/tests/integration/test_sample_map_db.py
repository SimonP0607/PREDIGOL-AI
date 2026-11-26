"""RP-3.1 against the real view: the matches with the figure are counted, the ones without it are not, and the window is respected."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.stats import sample_map
from tests.integration.conftest import Seed
from tests.integration.knowledge_world import KICKOFF, World

pytestmark = pytest.mark.integration


def test_the_matrix_counts_only_the_matches_that_have_the_figure(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    a = w.match(KICKOFF, 0, 1, (2, 1), ht=(1, 0))
    b = w.match(KICKOFF + timedelta(hours=1), 2, 3, (0, 0), ht=None)       # no half-time score
    old = w.match(KICKOFF - timedelta(days=2000), 0, 2, (1, 1), ht=(0, 0))  # outside a three-year window
    for fid in (a, b, old):
        w.team_stats(fid, "home", corners=6, shots=10, fouls=12, yellow_cards=1, red_cards=0)
        w.team_stats(fid, "away", corners=4, shots=8, fouls=10, yellow_cards=2, red_cards=0)
    doc = sample_map.read(db, at=KICKOFF + timedelta(days=1))
    mine = next(c for c in doc["competitions"] if c["name"] == "Knowledge League")
    f = mine["families"]
    assert f["goals"]["n"] == 2 and f["goals"]["mean"] == 1.5     # (3 + 0) / 2: the old match is outside the window
    assert f["goals_half"]["n"] == 1, "the match without a half-time score does not count for the half"
    assert f["corners"]["n"] == 2 and f["corners"]["mean"] == 10.0
    assert f["cards"]["n"] == 2 and f["fouls"]["n"] == 2 and f["shots"]["n"] == 2
    assert all(v["level"] in ("competition", "type", "global") for v in f.values())
    assert doc["summary"]["with_a_level"] == doc["summary"]["competitions"]
    wide = sample_map.read(db, at=KICKOFF + timedelta(days=1), window_days=5000)
    assert next(c for c in wide["competitions"] if c["name"] == "Knowledge League")["families"]["goals"]["n"] == 3

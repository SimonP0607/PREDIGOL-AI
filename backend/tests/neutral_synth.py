"""A synthetic football world with a planted truth, for the tests of the neutral-venue comparison.

Used by ``tests/unit/test_neutral_ab.py`` (in memory) and ``tests/integration/test_neutral_venue_flow.py`` (written to a
database and read back by ``run_ab``), so that the two can be compared on the very same matches."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np

from fbi.backtesting.neutral_ab import Protocol
from fbi.features.data import MatchRecord

START = datetime(2015, 8, 1, 15, 0, tzinfo=UTC)


def world(seed: int, *, share: float, really_neutral: bool, weeks: int = 220, teams: int = 24,
          home: float = 0.30) -> tuple[list[MatchRecord], list[MatchRecord]]:
    """Poisson goals from planted strengths, a home advantage of ``home`` (log expected goals) at every ground except those
    ``really_neutral`` makes neutral. ``share`` of the matches carry the rule's label (``is_neutral`` in the second arm)
    whether or not the label is true. Returns (before, after): the same matches, the after arm with the labels."""
    rng = np.random.default_rng(seed)
    attack, defence = rng.normal(0, 0.35, teams), rng.normal(0, 0.35, teams)
    before: list[MatchRecord] = []
    after: list[MatchRecord] = []
    fid = 0
    for week in range(weeks):
        order = rng.permutation(teams)
        for k in range(teams // 2):
            h, a = int(order[2 * k]), int(order[2 * k + 1])
            fid += 1
            labelled = rng.random() < share
            advantage = 0.0 if labelled and really_neutral else home
            kw = {
                "fixture_id": fid, "kickoff_at": START + timedelta(days=7 * week, hours=int(rng.integers(0, 6))),
                "competition_id": 1, "competition_type": "domestic_league", "season": 2015 + week // 52,
                "home_team_id": h + 1, "away_team_id": a + 1, "status_group": "finished",
                "goals_home": int(rng.poisson(1.25 * math.exp(attack[h] - defence[a] + advantage))),
                "goals_away": int(rng.poisson(1.25 * math.exp(attack[a] - defence[h]))),
            }
            before.append(MatchRecord(is_neutral=False, **kw))  # type: ignore[arg-type]
            after.append(MatchRecord(is_neutral=labelled, **kw))  # type: ignore[arg-type]
    return before, after


SCALED = replace(Protocol(), test_from=datetime(2017, 1, 1, tzinfo=UTC), goal_kinds=("poisson",), goal_refit_days=91,
                 draws=500, control_margin=0.002)
"""The default protocol with a window and cadences that fit a small world. The control margin is scaled too: with 30% of the
matches labelled the other matches' ratings move far more than they do when 1% are, and their interval is wider."""

"""The effect of the referee on a count of cards, shrunk towards no effect (plan F10, cards).

Some referees give more cards than the teams on the pitch explain. Each referee gets a multiplier for the cards of a match: the cards that
happened in his matches, over the cards the strengths of the two teams predicted for them, each added to a prior of ``KAPPA`` cards that says
"no effect" - a gamma prior with mean one, whose posterior mean is ``(KAPPA + observed) / (KAPPA + expected)``. A referee with a handful of
matches stays near one; one with hundreds is believed. The multiplier scales the means of BOTH sides (a referee is strict with the two teams).

It is learned from the matches that were already known (the training of the fit) and applied only when the referee of the next match is known.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Final

from fbi.families.fit import Fitted, Match

KAPPA: Final = 150.0
"""The weight of "no effect", in cards: a referee with 150 cards in his matches counts as much as the prior (about 30 matches)."""
MIN_MATCHES: Final = 5
"""A referee with fewer known matches than this has no multiplier."""


def factors(train: Sequence[Match], fitted: Fitted, *, kappa: float = KAPPA, min_matches: int = MIN_MATCHES) -> dict[int, float]:
    """The multiplier of each referee in ``train`` (matches known when ``fitted`` was made) that has at least ``min_matches`` of them."""
    observed: dict[int, float] = defaultdict(float)
    expected: dict[int, float] = defaultdict(float)
    played: dict[int, int] = defaultdict(int)
    for m in train:
        if m.referee_id is None or not fitted.knows(m.home_id, m.away_id):
            continue
        mu_home, mu_away = fitted.means(m.home_id, m.away_id)
        observed[m.referee_id] += m.home + m.away
        expected[m.referee_id] += mu_home + mu_away
        played[m.referee_id] += 1
    return {r: (kappa + observed[r]) / (kappa + expected[r]) for r, n in played.items() if n >= min_matches}

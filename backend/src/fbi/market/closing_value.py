"""The closing-line value of a price: ONE definition (plan F0, defect 7; ``clv-v1``).

Two different numbers were called "CLV" in this code. They are not the same thing, they differ by the bookmaker's
margin (about four points on average), and each was judged by its own threshold; the learning put them side by side:

    CLV          ``odds x p_close - 1``. ``p_close`` is the de-vigged (Shin) consensus probability of the last
                 snapshot before kick-off (``market.market_consensus``): what the price taken was worth, in expectation,
                 at the closing fair probability. It is the definition of the research notes (A4: "mean of
                 O_d.p_close - 1") and the one ``intel.decision_outcomes.clv``, ``picks.pick_line_value.lv_devigged``,
                 the walk-forward gate (``rule_clv``), the score, the memory and the daily report already use.
                 A price taken at a bookmaker with a 6 % margin scores about -6 % even if nothing moved afterwards:
                 that is what it IS, a price below fair value.

    price move   ``odds / close_odds - 1``. ``close_odds`` is the SAME bookmaker's last price, its margin included
                 (``picks.pick_line_value.lv_raw``). It says whether that book's price moved after we took it, not
                 whether the price was good: the margin is in both prices and cancels. It is what the post-mortem
                 by selection (pm-v2) judged "the market moved against it" by, and what the AI shadow report called CLV.

The two are related, not interchangeable. With ``q = 1 / close_odds`` the book's own implied probability at the close
(margin included) and ``p_close`` the fair one,

    clv = (1 + price_move) x (p_close / q) - 1

and ``p_close / q`` is about ``1 / (1 + margin)``: CLV is the price move minus the closing margin, roughly. A threshold
set for one is wrong for the other (-3 % of price move is about -7 % of CLV), and an average of one next to an average of
the other says nothing. So: the name "CLV" belongs to ``clv`` alone; a price move is called a price move, wherever it
is computed, stored or shown; and nothing aggregates the two together. The only module that writes either formula is
this one (``tests/unit/test_closing_value.py`` and ``tests/integration/test_clv_single_definition.py`` hold it there, and
hold the SQL twins - ``lv_raw`` and ``lv_devigged`` in ``fbi.picks.fast_settlement`` - to the same numbers).

``p_close`` is ``market_consensus.p_fair``, which is P(win | the bet is settled): on a line that can push, CLV is the
value conditional on a settlement, as everywhere else in the system. The reference is the last captured consensus before
kick-off, which has not been shown to BE the closing line (``close_minutes_to_ko`` says how near it was): this is value
against a near-close price, and the screens say so.

Rows written before ``clv-v1`` (22 Oct 2026) keep what they say: ``ai.pick_postmortems.clv`` holds a PRICE MOVE (the
column keeps its name because the table is history), as do the ``clv`` keys of the pm-v1 / pm-v2 JSON and of the AI
shadow reports ``ai-gate-v1``. Readers never take those as CLV: they derive CLV from the odds and the closing
probability stored beside them (``fbi.ai.pick_postmortem.stored_clv``).
"""

from __future__ import annotations

import math
from decimal import Decimal

VERSION = "clv-v1"

GOOD = 0.01
"""A price whose CLV is above +1 % is a GOOD decision price, below -1 % a BAD one, otherwise NEUTRAL: the thresholds
of the post-mortem by decision (pm-v3 and later), on CLV."""

MOVED_AGAINST = -0.03
"""A price move of 3 % or more against the price taken: the market (that book) moved away from the selection. The
threshold of the post-mortem by selection's MARKET_ERROR, on a PRICE MOVE - never to be applied to CLV."""

def clv[N: (float, Decimal)](odds: N, p_close: N) -> N:
    """``clv-v1``: the price taken at the closing fair probability, ``odds x p_close - 1``."""
    return odds * p_close - 1


def price_move[N: (float, Decimal)](odds: N, close_odds: N) -> N:
    """The price taken against the SAME bookmaker's closing price (margin included), ``odds / close_odds - 1``.
    Not CLV: see the module's note."""
    return odds / close_odds - 1


def quality(value: float | None) -> str:
    """The quality of a decision price from its CLV: GOOD, BAD, NEUTRAL, or UNKNOWN without a closing price."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "UNKNOWN"
    return "GOOD" if value > GOOD else "BAD" if value < -GOOD else "NEUTRAL"

"""Where a forecast stands against the market: CHAMPION, CHALLENGER, RESEARCH or REJECTED.

Rules (fixed before the research-V2 run; ``docs/research/MODEL_RESEARCH_V2_2026.md`` sections
6 and 8):

  CHAMPION    the market forecast with the lowest log loss on the fixtures every market
              baseline priced. Nothing else can be champion without an explicit promotion.
  CHALLENGER  a model whose log-loss difference to the champion has its whole interval
              below zero (it beats the market out of sample), OR whose information the
              market lacks: the test-season blend weight's interval is above zero AND the
              validation-fitted blend beats the champion with its interval below zero.
              A challenger waits for an explicit promotion; it is never promoted here.
  REJECTED    worse than the champion with sufficient evidence (interval above zero) AND
              adding nothing in a blend (weight interval reaching zero or below). Kept and
              shown - a losing model is a result, not something to delete.
  RESEARCH    everything else: the sample cannot tell.

A REJECTED forecaster can still be useful where no market exists (it prices fixtures the
bookmakers do not); the role is about competing with the market, and the reason says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from fbi.backtesting.evaluate import Comparison
from fbi.research.blend import BlendResult

ROLES = ("CHAMPION", "CHALLENGER", "RESEARCH", "REJECTED")


@dataclass(frozen=True, slots=True)
class Role:
    role: str
    reason: str


def _fmt(lo: float, hi: float) -> str:
    return f"[{lo:+.4f}, {hi:+.4f}]"


def model_role(vs_champion: Comparison | None, blend: BlendResult | None, *, champion: str) -> Role:
    if vs_champion is None:
        return Role("RESEARCH", f"no fixture shared with the champion {champion}")
    d = vs_champion.logloss_diff
    alone = (f"log loss vs {champion}: {d.mean:+.4f} {_fmt(d.lo, d.hi)} on {vs_champion.n_common} fixtures "
             f"({vs_champion.verdict})")
    if blend is None:
        weight = "no blend (too few fixtures)"
        adds = False
        blend_wins = False
    else:
        weight = f"blend weight on the test season {blend.w_test:+.3f} {_fmt(blend.w_test_lo, blend.w_test_hi)}"
        adds = blend.adds_information
        blend_wins = blend.blend_beats_market
        if blend.diff_mean is not None and blend.diff_lo is not None and blend.diff_hi is not None:
            weight += (f"; validation-fitted blend vs the market {blend.diff_mean:+.4f} "
                       f"{_fmt(blend.diff_lo, blend.diff_hi)}")
    if d.hi < 0:
        return Role("CHALLENGER", f"beats the champion alone: {alone}; {weight}")
    if adds and blend_wins:
        return Role("CHALLENGER", f"adds information the market lacks: {weight}; alone: {alone}")
    if d.lo > 0 and not adds:
        return Role("REJECTED", f"worse than the champion and adds nothing to it: {alone}; {weight}. "
                                "Still usable to price fixtures the market does not.")
    return Role("RESEARCH", f"the evidence cannot tell: {alone}; {weight}")

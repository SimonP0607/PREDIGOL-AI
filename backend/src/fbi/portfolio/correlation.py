"""How dependent two selections are (``portfolio-corr-v1``), from what is available - and always WHICH source said so.

THE SOURCES, in the order they are tried:

    joint_distribution  the two selections are of one match and a ``JointProvider`` gives the match's joint score
                        distribution: the phi coefficient of their two win indicators under it. The default provider is
                        ``None`` (nothing is wired today); ``ScoreMatrixJoint`` reads a score matrix per fixture.
    measured_icc        the two are of one competition's matchday (same competition, same Bogotá day) and of the same
                        measured market: the intra-class correlation the parlays measure from settled results
                        (``fbi.parlays.correlation``, ``icc-v1``), with the selections' polarity - used only when it is
                        significant (its 95 % interval excludes zero) with at least ``MIN_GROUPS`` matchdays.
    shared factors      otherwise, the rules below (``RULES``): constants, not measurements.
    none                no shared match, team, competition or kick-off window: 0.

The shared-factor constants are ENGINEERING CHOICES (no fit behind them): a prior of how much two selections share risk,
used only to SCALE STAKES DOWN. They are deliberately positive even where the true dependence can be negative (Home and
Away of one match exclude each other): a portfolio that is unsure keeps the two on one budget. A measured or computed
correlation below zero never raises a stake either (``budget_rho``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

from fbi.ai.calendar import local_day
from fbi.parlays import correlation as icc
from fbi.parlays.persist import _polarity
from fbi.portfolio.selection import Selection

VERSION: Final = "portfolio-corr-v1"

Source = Literal["joint_distribution", "measured_icc", "same_match", "same_team", "same_league_window", "same_league",
                 "same_window", "none"]

SAME_MATCH: Final = 0.60
"""Two selections of one match with no joint distribution: they share every goal. Chosen high so the pair is staked as
little more than one selection; the per-match exposure limit holds the rest."""
SAME_TEAM: Final = 0.30
"""Two matches of one team on the day (rare: a rescheduled match): the team's news, line-up and form are shared."""
SAME_LEAGUE_WINDOW: Final = 0.15
"""One competition, kick-offs within ``WINDOW``: the same matchday's refereeing, weather and late news."""
SAME_LEAGUE: Final = 0.05
"""One competition, kick-offs further apart: the competition's scoring environment only."""
SAME_WINDOW: Final = 0.02
"""Different competitions kicking off within ``WINDOW``: the only thing shared is the moment (prices captured together)."""
WINDOW: Final = timedelta(hours=2)
"""What "the same kick-off window" means."""
GROUP_MIN: Final = 0.10
"""The dependence from which two selections share a budget and their stakes are scaled down. Below it a pair is reported
but not scaled: SAME_LEAGUE and SAME_WINDOW are recorded so the report shows them, never to cut a stake."""
RULES: Final[Mapping[Source, float]] = {"same_match": SAME_MATCH, "same_team": SAME_TEAM,
                                        "same_league_window": SAME_LEAGUE_WINDOW, "same_league": SAME_LEAGUE,
                                        "same_window": SAME_WINDOW, "none": 0.0}
Z: Final = 1.96


@dataclass(frozen=True, slots=True)
class Correlation:
    a: int
    b: int
    """The two decision ids (``a < b``)."""
    rho: float
    source: Source
    factors: tuple[str, ...] = ()
    """What the two share, and any note on why a source was passed over."""

    @property
    def budget_rho(self) -> float:
        """The dependence the stakes are scaled by: the positive part, from ``GROUP_MIN`` up; otherwise 0."""
        return self.rho if self.rho >= GROUP_MIN else 0.0

    def as_json(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "rho": round(self.rho, 6), "source": self.source,
                "factors": list(self.factors), "shares_budget": self.budget_rho > 0}


class JointProvider(Protocol):
    """Gives the correlation of two selections of ONE match from the match's joint score distribution, or ``None`` when
    it cannot (no distribution for the match, a market it cannot settle from a score)."""

    def correlation(self, a: Selection, b: Selection) -> float | None: ...


def wins(market_key: str, selection: str, line: Decimal, home: int, away: int) -> bool | None:
    """Whether a selection wins at a final score, for the markets a score settles without a push; ``None`` otherwise."""
    if market_key == "1X2":
        return {"Home": home > away, "Draw": home == away, "Away": home < away}.get(selection)
    if market_key == "BTTS":
        both = home > 0 and away > 0
        return {"Yes": both, "No": not both}.get(selection)
    if market_key == "OU" and (line * 2) % 2 == 1:  # a half line only: an integer or quarter line can push
        total = Decimal(home + away)
        return {"Over": total > line, "Under": total < line}.get(selection)
    return None


@dataclass(frozen=True, slots=True)
class ScoreMatrixJoint:
    """A ``JointProvider`` over score matrices: ``matrices[fixture_id][h][a]`` = P(home scores h, away scores a)."""

    matrices: Mapping[int, Sequence[Sequence[float]]]

    def correlation(self, a: Selection, b: Selection) -> float | None:
        m = self.matrices.get(a.fixture_id)
        if m is None or a.fixture_id != b.fixture_id:
            return None
        pa = pb = pab = total = 0.0
        for h, row in enumerate(m):
            for x, p in enumerate(row):
                wa = wins(a.market_key, a.selection, a.line, h, x)
                wb = wins(b.market_key, b.selection, b.line, h, x)
                if wa is None or wb is None:
                    return None
                total += p
                pa += p * wa
                pb += p * wb
                pab += p * (wa and wb)
        if total <= 0:
            return None
        pa, pb, pab = pa / total, pb / total, pab / total
        denom = pa * (1 - pa) * pb * (1 - pb)
        if denom <= 0:
            return None
        return (pab - pa * pb) / math.sqrt(denom)


def _measured(a: Selection, b: Selection, measured: Mapping[str, icc.Estimate] | None) -> tuple[float | None, str]:
    """The significant measured ICC of the pair, or (None, why not)."""
    if not measured:
        return None, "no measured estimate"
    ma, mb = icc.market_of(a.market_key, a.selection), icc.market_of(b.market_key, b.selection)
    if ma is None or ma != mb:
        return None, "not the same measured market"
    e = measured.get(ma)
    if e is None:
        return None, f"no measured estimate for {ma}"
    rho = _polarity(a.market_key, a.selection) * _polarity(b.market_key, b.selection) * e.rho
    if e.n_groups < icc.MIN_GROUPS or not (rho - Z * e.se > 0 or rho + Z * e.se < 0):
        return None, f"{ma} measured but not significant ({e.n_groups} matchdays)"
    return rho, f"{ma}, {e.n_groups} matchdays"


def estimate(a: Selection, b: Selection, *, joint: JointProvider | None = None,
             measured: Mapping[str, icc.Estimate] | None = None) -> Correlation:
    """The dependence of two selections and its source (see the module's docstring for the order)."""
    lo, hi = (a, b) if a.decision_id <= b.decision_id else (b, a)
    same_window = abs(a.kickoff_at - b.kickoff_at) <= WINDOW

    def rule(source: Source, *factors: str) -> Correlation:
        return Correlation(lo.decision_id, hi.decision_id, RULES[source], source, factors)

    if a.fixture_id == b.fixture_id:
        rho = None if joint is None else joint.correlation(a, b)
        if rho is not None:
            return Correlation(lo.decision_id, hi.decision_id, rho, "joint_distribution", ("same match",))
        return rule("same_match", "same match", "no joint distribution" if joint is None else
                    "the joint distribution cannot settle the pair")
    if a.teams & b.teams:
        return rule("same_team", "same team")
    if a.competition_id == b.competition_id:
        note = "different day"
        if local_day(a.kickoff_at) == local_day(b.kickoff_at):
            rho, note = _measured(a, b, measured)
            if rho is not None:
                return Correlation(lo.decision_id, hi.decision_id, rho, "measured_icc", ("same competition-day", note))
        if same_window:
            return rule("same_league_window", "same competition", "same kick-off window", note)
        return rule("same_league", "same competition", note)
    if same_window:
        return rule("same_window", "same kick-off window")
    return rule("none")


def pairs(selections: Sequence[Selection], *, joint: JointProvider | None = None,
          measured: Mapping[str, icc.Estimate] | None = None) -> list[Correlation]:
    """Every pair that shares something (source not ``none``), in the order of the selections."""
    out: list[Correlation] = []
    for i, a in enumerate(selections):
        for b in selections[i + 1:]:
            c = estimate(a, b, joint=joint, measured=measured)
            if c.source != "none":
                out.append(c)
    return out


def groups(ids: Sequence[int], correlations: Sequence[Correlation]) -> list[list[int]]:
    """The selections that share a budget: connected through pairs with a ``budget_rho``. Singletons are left out."""
    parent = {i: i for i in ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in correlations:
        if c.budget_rho > 0 and c.a in parent and c.b in parent:
            parent[find(c.a)] = find(c.b)
    out: dict[int, list[int]] = {}
    for i in ids:
        out.setdefault(find(i), []).append(i)
    return [g for g in out.values() if len(g) > 1]

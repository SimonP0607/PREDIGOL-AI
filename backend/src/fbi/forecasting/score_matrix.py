"""One score matrix per match, and every goals market of the match from it (plan 2026, AD-B04, ``matrix-v1``), in SHADOW.

WHY. A goal model (Poisson, Dixon-Coles: ``fbi.models.goals``) says everything it knows about a match in ONE distribution over the final
score, ``P(home = i, away = j)``. Every goals market is a sum over it: the result, the double chance, draw-no-bet, each over/under line, both
teams to score, the goals of each side, every Asian and European handicap. Derived from the same matrix they are coherent with each other
BY CONSTRUCTION: the 1X2 adds up to one, the double chance is its sums, the handicap at 0 is draw-no-bet, the ladder of lines is monotone.
What the product states today is not one matrix: each market of the page is calibrated on its own (``fbi.forecasting.market_view``) and a
pick carries the probability its own selection was calibrated to, so two markets of the same match can disagree with each other.

WHAT IS HERE. Pure functions, no database and no clock:

    invert(rows, model) ...... the (lambda_home, lambda_away[, rho]) a goal model's seven stored rows were computed from (AD-B05): the
                               model's own arithmetic solved on its own numbers, nothing fitted to anything else
    build(Params) ............ the matrix of (lambda_home, lambda_away[, rho]): the model's own arithmetic (``fbi.models.scoring``), the same
                               10-10 truncation, the mass beyond renormalised and REPORTED; a rho outside the region where every
                               Dixon-Coles factor is positive is refused (``InvalidCorrectionError``), never clipped - clipping is another model
    derive(matrix) ........... every market of the menu below, as ``LineOutcome`` (win, push) per (market, selection, line)
    coherence(prices) ........ every rule a coherent set obeys (the test, and the shadow check of what is published)
    compare(prices, rows) .... a published number against the matrix's own, selection by selection

THE MENU (keys of the market catalogue, ``fbi.market.catalogue``; lines are the SELECTION's own, as the stored prices are):

    1X2 ............ Home / Draw / Away
    DC ............. 1X / X2 / 12 (sums of the 1X2; it cannot push)
    DNB ............ Home / Away; a draw returns the stake (``fbi.picks.count_settlement``)
    OU ............. Over / Under total goals at the 26 lines 0.5 .. 6.75
    BTTS ........... Yes / No
    OU_HOME/OU_AWAY  Over / Under the goals of one side, at 0.5 .. 3.5 (``Total - Home`` / ``Total - Away`` of the catalogue)
    AH ............. Asian handicap at the 45 lines -5.5 .. +5.5; ``line`` applies to the selection: the bet is on own margin + line
    EH ............. European (three-way) handicap at -3 .. +3 (not 0, which is the 1X2); ``line`` is applied to the HOME side

Whole lines can return the stake; a QUARTER line is half the stake on each neighbouring line, so it can win or lose half: its (win, push)
are the averages of the two legs (``fbi.models.lines``, the convention ``fbi.picks.settlement`` settles by, held equal by
``tests/unit/test_lines_agree_with_settlement.py``). Any other line that is a multiple of 0.25 can be asked for.

WHERE IT LIVES. In ``fbi.forecasting``, never in ``fbi.models``: a file added to a model package renews the version of every model
(``fbi.core.version.MODEL_PACKAGES``). It reuses ``fbi.models.lines`` and ``fbi.models.scoring`` as a library and changes neither. It does not
import the simulator (``fbi.simulator`` is shadow and nothing in ``fbi.forecasting`` may import it); the tests hold the two equal on the
full-time markets. Nothing reads it to decide or publish: the first reader is the single number of AD-B05, behind its own version.
The Elo ordered logit has no matrix (a 1X2 only): it stays a comparison, never the source of a matrix.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from itertools import pairwise
from typing import Final

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from fbi.models.goals import InvalidCorrectionError, dc_valid
from fbi.models.lines import LineOutcome, asian_handicap, double_chance, over_under
from fbi.models.scoring import MARKET_ROWS, MAX_GOALS, dc_tau, from_matrix, poisson_matrix

VERSION: Final = "matrix-v1"

GOAL_MODELS: Final = frozenset({"poisson", "dixon_coles"})
"""The models whose numbers come from a score matrix. ``elo_ologit`` states a 1X2 only."""

OU_LINES: Final = tuple(Decimal(q) / 4 for q in range(2, 28))
"""0.5, 0.75, ..., 6.75: the 26 lines of total goals."""
AH_LINES: Final = tuple(Decimal(q) / 4 for q in range(-22, 23))
"""-5.5, -5.25, ..., +5.5: the 45 Asian lines (of the home side; the away side is quoted at the opposite line)."""
TEAM_LINES: Final = tuple(Decimal(q) / 4 for q in range(2, 15))
"""0.5, 0.75, ..., 3.5: the lines of the goals of one side."""
EH_LINES: Final = tuple(Decimal(n) for n in (-3, -2, -1, 1, 2, 3))
"""The European handicaps, a whole number of goals applied to the home side (0 is the 1X2 itself)."""

TOLERANCE: Final = 1e-9
"""Sums of the matrix's own numbers: only floating-point error is tolerated."""

Key = tuple[str, str, Decimal]
Prices = dict[Key, LineOutcome]


@dataclass(frozen=True, slots=True)
class Params:
    """What a goal model says about one match: the expected goals of each side and, for Dixon-Coles, its low-score correction."""

    lam_home: float
    lam_away: float
    rho: float | None = None
    model: str = ""
    model_version_id: int | None = None

    def __post_init__(self) -> None:
        for name in ("lam_home", "lam_away"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive expected number of goals, not {value!r}")
        if self.rho is not None and not math.isfinite(self.rho):
            raise ValueError(f"rho must be a finite number, not {self.rho!r}")


@dataclass(frozen=True, slots=True)
class ScoreMatrix:
    """The normalised distribution of the final score, ``p[home, away]``, with what it was built from."""

    p: NDArray[np.float64]
    params: Params | None
    truncated_mass: float
    """Mass beyond the matrix before the renormalisation (below 1e-5 for any league's expected goals)."""

    @property
    def max_goals(self) -> int:
        return int(self.p.shape[0]) - 1


def build(params: Params, *, max_goals: int = MAX_GOALS) -> ScoreMatrix:
    """The model's own matrix: independent Poisson goals, Dixon-Coles corrected when ``rho`` is given (as ``GoalModel.score_matrix``)."""
    m = poisson_matrix(params.lam_home, params.lam_away, max_goals)
    if params.rho is not None:
        if not dc_valid(params.lam_home, params.lam_away, params.rho):
            raise InvalidCorrectionError(f"Dixon-Coles correction rho={params.rho:.3f} is invalid for expected goals "
                                         f"{params.lam_home:.2f}-{params.lam_away:.2f}")
        m = dc_tau(m, params.lam_home, params.lam_away, params.rho)
    return from_array(m, params=params)


def from_array(m: NDArray[np.float64], *, params: Params | None = None) -> ScoreMatrix:
    """A matrix from any non-negative square array of score probabilities (the truncated mass is what it misses of one)."""
    arr = np.asarray(m, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1] or arr.shape[0] < 2:
        raise ValueError(f"a score matrix is square and at least 2x2, not {arr.shape}")
    total = float(arr.sum())
    if not math.isfinite(total) or total <= 0 or bool(np.any(arr < -1e-12)):
        raise ValueError("a score matrix is a distribution: finite, non-negative, with positive mass")
    return ScoreMatrix(np.clip(arr, 0.0, None) / total, params, max(0.0, 1.0 - total))


# -- the parameters back from the stored rows (AD-B05) ----------------------------------------------------------------------------------

INVERSION_TOLERANCE: Final = 1e-4
"""The largest difference on the seven rows at which the recovered parameters are taken as the model's own (the simulator's
``fbi.simulator.consistency.INVERSION_TOLERANCE``; measured in production on 17-nov-2026: at most 1e-6 over 89 matrices)."""

_STARTS: Final = ((1.4, 1.1), (1.0, 1.0), (2.2, 0.8), (0.8, 2.2))


@dataclass(frozen=True, slots=True)
class Inversion:
    params: Params
    residual: float
    """Largest absolute difference on the seven fixed rows between the stored numbers and the model at ``params``."""


def _seven(lh: float, la: float, rho: float | None) -> NDArray[np.float64]:
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    return np.array(from_matrix(m, lh, la).as_rows())


@lru_cache(maxsize=4096)
def _solve(target: tuple[float, ...], dc: bool) -> tuple[float, float, float | None, float]:
    y = np.array(target)

    def resid(theta: NDArray[np.float64]) -> NDArray[np.float64]:
        lh, la = math.exp(theta[0]), math.exp(theta[1])
        rho = float(theta[2]) if dc else None
        if rho is not None and not dc_valid(lh, la, rho):
            return np.full(len(y), 10.0)
        return np.asarray(_seven(lh, la, rho) - y, dtype=np.float64)

    best: object = None
    best_cost = math.inf
    for start in _STARTS:
        x0 = [math.log(start[0]), math.log(start[1])] + ([0.0] if dc else [])
        fit = least_squares(resid, np.array(x0), xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=2000)
        if float(fit.cost) < best_cost:
            best, best_cost = fit, float(fit.cost)
    theta = best.x  # type: ignore[attr-defined]
    lh, la = math.exp(float(theta[0])), math.exp(float(theta[1]))
    rho = float(theta[2]) if dc else None
    return lh, la, rho, float(np.abs(resid(theta)).max())


def invert(rows: Mapping[tuple[str, str, Decimal], float], model: str, *, model_version_id: int | None = None) -> Inversion | None:
    """The parameters at which ``model``'s own arithmetic gives its seven stored fixed rows (``MARKET_ROWS``), or None: not a goal model,
    a row missing, or no parameters reproduce the rows within ``INVERSION_TOLERANCE``. The same solution as the simulator's
    (``fbi.simulator.consistency.invert``, which ``fbi.forecasting`` may not import; a test holds the two equal). Deterministic: the same
    rows give the same parameters, so a matrix rebuilt later from the same append-only rows is the same matrix."""
    if model not in GOAL_MODELS:
        return None
    target: list[float] = []
    for m, s, line in MARKET_ROWS:
        v = rows.get((m, s, Decimal(str(line))))
        if v is None:
            return None
        target.append(float(v))
    lh, la, rho, residual = _solve(tuple(target), model == "dixon_coles")
    if residual > INVERSION_TOLERANCE:
        return None
    return Inversion(Params(lh, la, rho, model, model_version_id), residual)


# -- the markets -----------------------------------------------------------------------------------------------------------------------------

def _side_matrix(p: NDArray[np.float64], side: str) -> NDArray[np.float64]:
    """A matrix whose TOTAL is the goals of one side: the side's marginal in the first column (so ``lines.over_under`` reads it)."""
    out = np.zeros_like(p)
    out[:, 0] = p.sum(axis=1) if side == "home" else p.sum(axis=0)
    return out


def _margins(p: NDArray[np.float64]) -> dict[int, float]:
    n = p.shape[0]
    return {k: float(np.trace(p, offset=-k)) for k in range(-(n - 1), n)}


def derive(sm: ScoreMatrix, *, ou_lines: Iterable[Decimal] = OU_LINES, ah_lines: Iterable[Decimal] = AH_LINES,
           team_lines: Iterable[Decimal] = TEAM_LINES, eh_lines: Iterable[Decimal] = EH_LINES) -> Prices:
    """Every market of the menu (or of the lines asked for) from one matrix. ``ah_lines`` are the HOME side's; the away side is priced at
    the opposite line, so each Asian line is a complete pair."""
    p = sm.p
    home, draw, away = float(np.tril(p, -1).sum()), float(np.trace(p)), float(np.triu(p, 1).sum())
    out: Prices = {
        ("1X2", "Home", Decimal(0)): LineOutcome(home, 0.0),
        ("1X2", "Draw", Decimal(0)): LineOutcome(draw, 0.0),
        ("1X2", "Away", Decimal(0)): LineOutcome(away, 0.0),
        ("DNB", "Home", Decimal(0)): LineOutcome(home, draw),
        ("DNB", "Away", Decimal(0)): LineOutcome(away, draw),
    }
    for sel, v in double_chance(p).items():
        out[("DC", sel, Decimal(0))] = LineOutcome(v, 0.0)
    btts = float(p[1:, 1:].sum())
    out[("BTTS", "Yes", Decimal(0))] = LineOutcome(btts, 0.0)
    out[("BTTS", "No", Decimal(0))] = LineOutcome(1.0 - btts, 0.0)
    for line in _lines(ou_lines):
        for sel in ("Over", "Under"):
            out[("OU", sel, line)] = over_under(p, selection=sel, line=line)
    for key, side in (("OU_HOME", "home"), ("OU_AWAY", "away")):
        side_p = _side_matrix(p, side)
        for line in _lines(team_lines):
            for sel in ("Over", "Under"):
                out[(key, sel, line)] = over_under(side_p, selection=sel, line=line)
    for line in _lines(ah_lines):
        out[("AH", "Home", line)] = asian_handicap(p, selection="Home", line=line)
        out[("AH", "Away", -line + 0)] = asian_handicap(p, selection="Away", line=-line + 0)
    margins = _margins(p)
    for line in _lines(eh_lines):
        if line != line.to_integral_value():
            raise ValueError(f"a European handicap is a whole number of goals, not {line}")
        shift = int(line)
        out[("EH", "Home", line)] = LineOutcome(sum(v for k, v in margins.items() if k + shift > 0), 0.0)
        out[("EH", "Draw", line)] = LineOutcome(sum(v for k, v in margins.items() if k + shift == 0), 0.0)
        out[("EH", "Away", line)] = LineOutcome(sum(v for k, v in margins.items() if k + shift < 0), 0.0)
    return out


def _lines(lines: Iterable[Decimal]) -> list[Decimal]:
    out = []
    for line in lines:
        d = Decimal(str(line))
        if (d * 4) != (d * 4).to_integral_value():
            raise ValueError(f"a line is a multiple of 0.25, not {line}")
        out.append(d + 0)  # -0 is 0
    return sorted(set(out))


def market_rows(prices: Mapping[Key, LineOutcome]) -> tuple[float, ...]:
    """The seven rows the goal models store (``fbi.models.scoring.MARKET_ROWS``), in their order: the regression of what is published."""
    return tuple(prices[(m, s, Decimal(str(line)))].win for m, s, line in MARKET_ROWS)


# -- coherence ---------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    detail: str
    gap: float


def _eq(found: list[Violation], rule: str, detail: str, value: float, expected: float, tol: float) -> None:
    gap = abs(value - expected) - tol
    if gap > 0:
        found.append(Violation(rule, f"{detail}: {value:.9f} vs {expected:.9f}", gap))


def _le(found: list[Violation], rule: str, detail: str, left: float, right: float, tol: float) -> None:
    gap = left - right - tol
    if gap > 0:
        found.append(Violation(rule, f"{detail}: {left:.9f} > {right:.9f}", gap))


def coherence(prices: Mapping[Key, LineOutcome], *, tol: float = TOLERANCE) -> list[Violation]:
    """Every rule a coherent set of goals markets obeys, over the markets present in ``prices``:

    complete markets add up to one (pushes included) and a push is the same on both sides; the double chance is the sums of the 1X2;
    draw-no-bet is the Asian handicap at 0 and pushes exactly on a draw; the half-goal handicaps are the 1X2 (Home -0.5 = Home, Home +0.5 =
    1X); the European handicap at +1 Home is the Asian Home +0.5; over/under, goals of one side and the Asian lines are monotone in
    the line (what is not lost, and what is won); and the bounds that follow from what the events contain (BTTS Yes - Draw <= Over 2.5
    <= BTTS Yes + Home + Away, BTTS Yes <= Over 1.5, Under 1.5 <= BTTS No, Home + Away <= Over 0.5, Under 0.5 <= Draw)."""
    found: list[Violation] = []

    def w(m: str, s: str, line: Decimal | int = 0) -> float | None:
        o = prices.get((m, s, Decimal(line)))
        return None if o is None else o.win

    h, d, a = w("1X2", "Home"), w("1X2", "Draw"), w("1X2", "Away")
    if h is not None and d is not None and a is not None:
        _eq(found, "1x2_sums_to_one", "Home + Draw + Away", h + d + a, 1.0, tol)
        for sel, expected in (("1X", h + d), ("X2", d + a), ("12", h + a)):
            v = w("DC", sel)
            if v is not None:
                _eq(found, "dc_is_1x2_sum", f"DC {sel}", v, expected, tol)
        for side, own in (("Home", h), ("Away", a)):
            dnb = prices.get(("DNB", side, Decimal(0)))
            if dnb is not None:
                _eq(found, "dnb_is_result", f"DNB {side} win", dnb.win, own, tol)
                _eq(found, "dnb_push_is_draw", f"DNB {side} push", dnb.push, d, tol)
            for line, expected in ((Decimal("-0.5"), own), (Decimal("0.5"), own + d)):
                v = w("AH", side, line)
                if v is not None:
                    _eq(found, "ah_half_goal_is_1x2", f"AH {side} {line:+}", v, expected, tol)
    for side in ("Home", "Away"):
        dnb, ah0 = prices.get(("DNB", side, Decimal(0))), prices.get(("AH", side, Decimal(0)))
        if dnb is not None and ah0 is not None:
            _eq(found, "ah0_is_dnb", f"AH {side} 0 win", ah0.win, dnb.win, tol)
            _eq(found, "ah0_is_dnb", f"AH {side} 0 push", ah0.push, dnb.push, tol)
    yes, no = w("BTTS", "Yes"), w("BTTS", "No")
    if yes is not None and no is not None:
        _eq(found, "btts_sums_to_one", "BTTS Yes + No", yes + no, 1.0, tol)
    for market in ("OU", "OU_HOME", "OU_AWAY"):
        lines = sorted({k[2] for k in prices if k[0] == market})
        for line in lines:
            o, u = prices.get((market, "Over", line)), prices.get((market, "Under", line))
            if o is not None and u is not None:
                _eq(found, "ou_sums_to_one", f"{market} {line} Over + Under + push", o.win + u.win + o.push, 1.0, tol)
                _eq(found, "ou_push_both_sides", f"{market} {line} push", o.push, u.push, tol)
        _monotone(found, prices, market, "Over", lines, decreasing=True, tol=tol)
        _monotone(found, prices, market, "Under", lines, decreasing=False, tol=tol)
    for line in sorted({k[2] for k in prices if k[0] == "AH" and k[1] == "Home"}):
        hs, aw = prices.get(("AH", "Home", line)), prices.get(("AH", "Away", -line + 0))
        if hs is not None and aw is not None:
            _eq(found, "ah_pair_sums_to_one", f"AH Home {line:+} + Away {-line:+} + push", hs.win + aw.win + hs.push, 1.0, tol)
            _eq(found, "ah_push_both_sides", f"AH {line:+} push", hs.push, aw.push, tol)
    for side in ("Home", "Away"):
        lines = sorted({k[2] for k in prices if k[0] == "AH" and k[1] == side})
        _monotone(found, prices, "AH", side, lines, decreasing=False, tol=tol)
    for line in sorted({k[2] for k in prices if k[0] == "EH"}):
        trio = [w("EH", s, line) for s in ("Home", "Draw", "Away")]
        if all(v is not None for v in trio):
            _eq(found, "eh_sums_to_one", f"EH {line:+}", sum(v for v in trio if v is not None), 1.0, tol)
    eh_home_p1, ah_home_p05 = w("EH", "Home", 1), w("AH", "Home", Decimal("0.5"))
    if eh_home_p1 is not None and ah_home_p05 is not None:
        _eq(found, "eh_plus1_home_is_ah_plus05", "EH +1 Home vs AH Home +0.5", eh_home_p1, ah_home_p05, tol)
    o15, o05, u15, u05 = w("OU", "Over", Decimal("1.5")), w("OU", "Over", Decimal("0.5")), w("OU", "Under", Decimal("1.5")), \
        w("OU", "Under", Decimal("0.5"))
    o25 = w("OU", "Over", Decimal("2.5"))
    if yes is not None and d is not None and o25 is not None:
        # both scoring with two goals or fewer is 1-1, a draw; over 2.5 with a side on nil is not a draw
        _le(found, "btts_over25_lower_bound", "BTTS Yes - Draw <= Over 2.5", yes - d, o25, tol)
        if h is not None and a is not None:
            _le(found, "btts_over25_upper_bound", "Over 2.5 <= BTTS Yes + Home + Away", o25, yes + h + a, tol)
    if yes is not None and o15 is not None:
        _le(found, "btts_within_over15", "BTTS Yes <= Over 1.5", yes, o15, tol)
    if no is not None and u15 is not None:
        _le(found, "under15_within_btts_no", "Under 1.5 <= BTTS No", u15, no, tol)
    if h is not None and a is not None and o05 is not None:
        _le(found, "decided_within_over05", "Home + Away <= Over 0.5", h + a, o05, tol)
    if d is not None and u05 is not None:
        _le(found, "nil_nil_within_draw", "Under 0.5 <= Draw", u05, d, tol)
    return found


def _monotone(found: list[Violation], prices: Mapping[Key, LineOutcome], market: str, sel: str, lines: list[Decimal], *,
              decreasing: bool, tol: float) -> None:
    """Along the line, both what is won and what is not lost move one way: down for an Over as the line rises, up for an Under or a side
    that receives more goals."""
    present = [(line, prices[(market, sel, line)]) for line in lines if (market, sel, line) in prices]
    for (l1, o1), (l2, o2) in pairwise(present):
        for what, v1, v2 in (("win", o1.win, o2.win), ("not lost", o1.win + o1.push, o2.win + o2.push)):
            if decreasing:
                _le(found, "ladder_monotone", f"{market} {sel} {what} at {l2} above {l1}", v2, v1, tol)
            else:
                _le(found, "ladder_monotone", f"{market} {sel} {what} at {l1} above {l2}", v1, v2, tol)


# -- the shadow comparison ---------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Published:
    """A number something states today for one selection (a stored prediction, the page's forecast, a decision's calibrated probability)."""

    market_key: str
    selection: str
    line: Decimal
    p: float
    push: float = 0.0


@dataclass(frozen=True, slots=True)
class Diff:
    market_key: str
    selection: str
    line: Decimal
    published: float
    matrix: float
    """The matrix's probability on the published number's own scale: the win probability, or for a number stated given that the bet is
    settled (``conditional``), win / (1 - push)."""

    @property
    def abs_diff(self) -> float:
        return abs(self.published - self.matrix)


def compare(prices: Mapping[Key, LineOutcome], published: Iterable[Published], *, conditional: bool = False) -> tuple[list[Diff], int]:
    """Each published number beside the matrix's own; returns the diffs and how many published selections the menu does not hold."""
    diffs: list[Diff] = []
    missing = 0
    for row in published:
        o = prices.get((row.market_key, row.selection, Decimal(str(row.line)) + 0))
        if o is None:
            missing += 1
            continue
        value = o.conditional_win if conditional else o.win
        diffs.append(Diff(row.market_key, row.selection, Decimal(str(row.line)), row.p, value))
    return diffs, missing


def published_coherence(rows: Iterable[Published], *, tol: float) -> list[Violation]:
    """The rules of ``coherence`` over what is published (a stored number rounds to six decimals: ``tol`` says how much that is allowed)."""
    prices = {(r.market_key, r.selection, Decimal(str(r.line)) + 0): LineOutcome(r.p, r.push) for r in rows}
    return coherence(prices, tol=tol)

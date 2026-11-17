"""ONE calculation of the dependence between two selections (``corr-v2``, plan 2026 AD-E07, IA-098), in SHADOW.

WHY. Three calculations of dependence live in the code today and they disagree:

    parlays     ``fbi.parlays.persist.correlated_pairs`` (``parlay-v5`` over ``icc-v1``): legs of one competition's matchday, the measured
                intra-class correlation of their market, used only when SIGNIFICANTLY NEGATIVE; one match or one team twice is refused
                before (``fbi.parlays.engine.guard``)
    portfolio   ``fbi.portfolio.correlation`` (``portfolio-corr-v1``): a joint distribution that nothing connects, the measured
                correlation when significant of EITHER sign, otherwise engineering constants (0.60 one match, 0.30 one team, 0.15 / 0.05
                one competition, 0.02 one kick-off window)
    decision-v1 filter 8 (``fbi.intel.decision.correlate``): one approvable selection per match, the others CAUTELA - a rule, not a number;
                PROTECTED: it is not touched and it does not read this module

THE RULE (``corr-v2``). For a pair of selections, in this order, and always with the source that said so:

    same match ............ the match's score matrix (``fbi.forecasting.score_matrix``, AD-B04 / IA-074): the phi coefficient of the two
                            selections' win indicators under it (``matrix_rho``) - source ``score_matrix``. Without a matrix, or for a pair
                            the matrix cannot settle without a push, the pair is ``unmeasured`` and cannot be combined into one probability
    same team ............. ``unmeasured``: nothing measures it, and it cannot be combined
    same competition-day .. the intra-class correlation measured on settled results (``icc-v1``, ``ai.correlation_estimates``), with its
                            95 % interval (rho +/- 1.96 se, within [-1, 1]) and its sample (matchdays), with the selections' polarity
                            (Under / No win with the complement) - source ``measured_icc``, ONLY for what it measures: home win, draw,
                            away win, total goals over 2.5 (``icc-v1`` measures the 2.5 line; another line is ``unmeasured``) and both
                            teams to score
    otherwise ............. ``unmeasured`` (one competition another day, one kick-off window) or ``none`` (nothing shared)

TWO READINGS OF ONE NUMBER, for its two readers:

    joint_rho   what a JOINT PROBABILITY may use (parlays): the matrix's rho (it is the model's own arithmetic), a measured rho only when
                its interval is all below zero (it can only make the joint smaller: parity with ``parlay-v5``), 0 otherwise - an
                unmeasured or a positive-but-uncertain dependence NEVER raises a joint probability; ``None`` when the pair cannot be
                combined (one match without a matrix, one team)
    budget_rho  what a STAKE may be scaled down by (portfolio): the matrix's rho, the measured rho when significant, otherwise the
                engineering prior of the relation (``PRIORS``: portfolio-corr-v1's constants, held equal by a test) - only its
                positive part from ``GROUP_MIN`` up, so a dependence can only lower a stake (parity with ``portfolio-corr-v1``)

The priors are ENGINEERING CHOICES, not measurements (no fit behind them), and the reading says so (``source = unmeasured``).

PURE apart from ``read_measured`` (one read-only SELECT, through ``icc-v1``'s own reader). Symmetric (``estimate(a, b)`` and
``estimate(b, a)`` say the same) and every rho is in [-1, 1]. Its readers today: the shadow portfolio behind ``--correlation corr-v2``
(``fbi.portfolio.build``) and the production measurement (``scripts/ia_value_correlation.py``); ``parlay-v6`` (AD-E06) is its next.
``parlay-v5`` and decision-v1 do not read it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

import numpy as np
import psycopg
from numpy.typing import NDArray

from fbi.ai.calendar import local_day
from fbi.forecasting import score_matrix as sm
from fbi.forecasting.market_reader import read_numbers
from fbi.forecasting.market_view import Source
from fbi.forecasting.single_figure import FigureSet
from fbi.parlays import correlation as icc

VERSION: Final = "corr-v2"
Z: Final = 1.96
MIN_GROUPS: Final = icc.MIN_GROUPS
"""The fewest matchdays a measured correlation needs before it is believed (``icc-v1``'s own)."""
WINDOW: Final = timedelta(hours=2)
"""What «the same kick-off window» means (portfolio-corr-v1's)."""
GROUP_MIN: Final = 0.10
"""The dependence from which two selections share a stake budget (portfolio-corr-v1's)."""

Relation = Literal["same_match", "same_team", "same_competition_day", "same_competition", "same_window", "none"]
Origin = Literal["score_matrix", "measured_icc", "unmeasured", "none"]
SCORE_MATRIX: Final = "score_matrix"
MEASURED: Final = "measured_icc"
UNMEASURED: Final = "unmeasured"
NONE: Final = "none"

PRIORS: Final[Mapping[str, float]] = {"same_match": 0.60, "same_team": 0.30, "same_competition_day_window": 0.15,
                                      "same_competition": 0.05, "same_window": 0.02, "none": 0.0}
"""The engineering priors of a budget when nothing measures the pair (``portfolio-corr-v1``'s ``RULES``, held equal by a test): one
competition's matchday within ``WINDOW`` is 0.15, further apart 0.05."""
OU_MEASURED_LINE: Final = Decimal("2.5")
"""The one total-goals line ``icc-v1`` measures (``over_2_5``)."""


@dataclass(frozen=True, slots=True)
class Leg:
    """What the dependence needs of a selection."""

    ident: int
    fixture_id: int
    competition_id: int | None
    kickoff_at: datetime
    teams: frozenset[int]
    market_key: str
    selection: str
    line: Decimal


@dataclass(frozen=True, slots=True)
class Measured:
    """One market's intra-class correlation measured on settled results (``icc-v1``), with its uncertainty and sample."""

    market: str
    rho: float
    se: float
    n_groups: int
    n_matches: int
    version: str = icc.VERSION

    @classmethod
    def of(cls, e: icc.Estimate) -> Measured:
        return cls(e.market, float(e.rho), float(e.se), int(e.n_groups), int(e.n_matches))


@dataclass(frozen=True, slots=True)
class Dependence:
    """The dependence of two selections (``a < b``), with what it is, where it comes from and how sure it is."""

    a: int
    b: int
    relation: Relation
    source: Origin
    rho: float | None
    """The point estimate; None when nothing measures the pair."""
    low: float | None
    high: float | None
    """Its 95 % interval (a measured rho); for the matrix's rho both are the rho (the model's own arithmetic, no sampling error); None
    unmeasured."""
    basis: str
    """Who said so, in words: the matrix's model, the measured market and its sample, or why it is unmeasured."""
    sample: int | None = None
    """Matchdays behind a measured rho."""
    same_window: bool = False
    """Whether the two kick off within ``WINDOW`` of each other."""
    version: str = VERSION

    @property
    def prior(self) -> float:
        """The engineering prior of the relation (``PRIORS``): the budget's rho when nothing measures the pair. One competition is
        0.15 within the kick-off window and 0.05 beyond it, whatever the day (as portfolio-corr-v1)."""
        if self.relation in ("same_competition_day", "same_competition"):
            return PRIORS["same_competition_day_window" if self.same_window else "same_competition"]
        return PRIORS[self.relation]

    @property
    def significant(self) -> bool:
        return (self.source == MEASURED and self.low is not None and self.high is not None and (self.sample or 0) >= MIN_GROUPS
                and (self.low > 0 or self.high < 0))

    @property
    def combinable(self) -> bool:
        """Whether a joint probability of the two can be computed: not one match without its matrix, not one team."""
        return not (self.relation in ("same_match", "same_team") and self.source != SCORE_MATRIX)

    @property
    def joint_rho(self) -> float | None:
        """What a joint probability may use (see the module's note); None when the pair cannot be combined."""
        if not self.combinable:
            return None
        if self.source == SCORE_MATRIX and self.rho is not None:
            return self.rho
        if self.significant and self.high is not None and self.high < 0 and self.rho is not None:
            return self.rho
        return 0.0

    @property
    def budget_basis(self) -> float:
        """The dependence a budget is judged by before ``GROUP_MIN``: the matrix's or the significant measured rho, else the prior."""
        if self.source == SCORE_MATRIX and self.rho is not None:
            return self.rho
        if self.significant and self.rho is not None:
            return self.rho
        return self.prior

    @property
    def budget_rho(self) -> float:
        """What stakes are scaled down by: the positive part of ``budget_basis`` from ``GROUP_MIN`` up; otherwise 0."""
        x = self.budget_basis
        return x if x >= GROUP_MIN else 0.0

    def as_json(self) -> dict[str, Any]:
        def r(x: float | None) -> float | None:
            return None if x is None else round(x, 6)

        return {"a": self.a, "b": self.b, "relation": self.relation, "source": self.source, "rho": r(self.rho),
                "interval": None if self.low is None or self.high is None else [r(self.low), r(self.high)], "basis": self.basis,
                "sample": self.sample, "same_window": self.same_window, "joint_rho": r(self.joint_rho), "budget_rho": r(self.budget_rho), "combinable": self.combinable,
                "version": self.version}


# -- settling a selection on a final score ---------------------------------------------------------------------------------------------

def wins(market_key: str, selection: str, line: Decimal, home: int, away: int) -> bool | None:
    """Whether a selection wins at a final score, for the selections a score settles WITHOUT a push; None otherwise (a line that can
    return the stake or win half has no win indicator). Lines are the selection's own, as ``score_matrix.derive`` prices them. Pure."""
    total, margin = home + away, home - away
    half = abs(line * 2) % 2 == 1  # a .5 line (either sign): it cannot push
    if market_key == "1X2":
        return {"Home": margin > 0, "Draw": margin == 0, "Away": margin < 0}.get(selection)
    if market_key == "DC":
        return {"1X": margin >= 0, "X2": margin <= 0, "12": margin != 0}.get(selection)
    if market_key == "BTTS":
        both = home > 0 and away > 0
        return {"Yes": both, "No": not both}.get(selection)
    if market_key in ("OU", "OU_HOME", "OU_AWAY") and half:
        goals = Decimal({"OU": total, "OU_HOME": home, "OU_AWAY": away}[market_key])
        return {"Over": goals > line, "Under": goals < line}.get(selection)
    if market_key == "AH" and half:
        own = Decimal(margin if selection == "Home" else -margin) + line
        return own > 0 if selection in ("Home", "Away") else None
    if market_key == "EH" and line == line.to_integral_value():
        shifted = Decimal(margin) + line
        return {"Home": shifted > 0, "Draw": shifted == 0, "Away": shifted < 0}.get(selection)
    return None


def matrix_rho(p: NDArray[np.float64], a: tuple[str, str, Decimal], b: tuple[str, str, Decimal]) -> float | None:
    """The phi coefficient of two selections' win indicators under a score matrix ``p[home, away]``; None when either cannot be settled
    on a score without a push, or either is certain under the matrix. In [-1, 1]. Pure."""
    total = pa = pb = pab = 0.0
    n_h, n_a = p.shape
    for h in range(n_h):
        for x in range(n_a):
            w = float(p[h, x])
            wa, wb = wins(*a, h, x), wins(*b, h, x)
            if wa is None or wb is None:
                return None
            total += w
            pa += w * wa
            pb += w * wb
            pab += w * (wa and wb)
    if total <= 0:
        return None
    pa, pb, pab = pa / total, pb / total, pab / total
    denom = pa * (1 - pa) * pb * (1 - pb)
    if denom <= 1e-15:
        return None
    return max(-1.0, min(1.0, (pab - pa * pb) / math.sqrt(denom)))


def matrix_of(fs: FigureSet) -> tuple[str, NDArray[np.float64]] | None:
    """The score matrix of a match from its single figures (``forecast-v2``): the goal model of its 1X2 figure when that model's rows
    inverted, otherwise the first goal model whose did (by name); None when none did. Pure."""
    result = fs.get("1X2", "Home", 0)
    names = sorted(n for n, inv in fs.matrices.items() if inv is not None)
    if not names:
        return None
    name = result.model if result is not None and result.model in names else names[0]
    inv = fs.matrices[name]
    assert inv is not None
    return name, sm.build(inv.params).p


def matrices_from(numbers: Mapping[int, Mapping[str, Mapping[tuple[str, str, Decimal], Source]]]
                  ) -> tuple[dict[int, NDArray[np.float64]], dict[int, str]]:
    """The score matrix of each match from its models' newest stored rows (``market_reader.read_numbers``): the first goal model, by name
    (``dixon_coles`` before ``poisson``), whose seven fixed rows invert within tolerance (``score_matrix.invert``); a match none of whose
    models inverts has no matrix. With the matrix, who it came from (``matrix-v1 <model> mv <id>``). Pure."""
    out: dict[int, NDArray[np.float64]] = {}
    basis: dict[int, str] = {}
    for fid, models in numbers.items():
        for name in sorted(models):
            rows = models[name]
            first = next(iter(rows.values()), None)
            inv = sm.invert({k: v.p for k, v in rows.items()}, name, model_version_id=None if first is None else first.model_version_id)
            if inv is not None:
                out[fid] = sm.build(inv.params).p
                basis[fid] = f"{name} mv {inv.params.model_version_id}"
                break
    return out, basis


def read_matrices(conn: psycopg.Connection[Any], fixture_ids: Sequence[int], *, at: datetime
                  ) -> tuple[dict[int, NDArray[np.float64]], dict[int, str]]:
    """The score matrix of each of these matches as of ``at`` (``matrices_from`` over ``market_reader.read_numbers``). Read-only."""
    ids = sorted(set(fixture_ids))
    return matrices_from(read_numbers(conn, ids, at)) if ids else ({}, {})


# -- the measured correlation ----------------------------------------------------------------------------------------------------------

def measured_market(market_key: str, selection: str, line: Decimal) -> str | None:
    """The outcome ``icc-v1`` measures that a selection is (or is the complement of); None when it measures none of it. Pure."""
    if market_key == "OU":
        return "over_2_5" if Decimal(str(line)) == OU_MEASURED_LINE else None
    return icc.market_of(market_key, selection)


def polarity(market_key: str, selection: str) -> int:
    """+1 when the selection wins with its measured outcome, -1 when it wins with the complement (Under, No). Pure."""
    return -1 if (market_key, selection) in (("OU", "Under"), ("BTTS", "No")) else 1


def read_measured(conn: psycopg.Connection[Any]) -> dict[str, Measured]:
    """The newest measured correlation of each market (``icc-v1``'s reader). Read-only."""
    return {m: Measured.of(e) for m, e in icc.latest(conn).items()}


def _measured(a: Leg, b: Leg, measured: Mapping[str, Measured] | None) -> tuple[float, float, float, str, int] | str:
    ma, mb = measured_market(a.market_key, a.selection, a.line), measured_market(b.market_key, b.selection, b.line)
    if ma is None or mb is None:
        return "icc-v1 no mide este mercado o línea"
    if ma != mb:
        return f"mercados distintos ({ma} / {mb}): icc-v1 no mide su dependencia"
    e = (measured or {}).get(ma)
    if e is None:
        return f"sin medición de {ma}"
    sign = polarity(a.market_key, a.selection) * polarity(b.market_key, b.selection)
    rho = sign * e.rho
    lo, hi = max(-1.0, rho - Z * e.se), min(1.0, rho + Z * e.se)
    return max(-1.0, min(1.0, rho)), lo, hi, f"{e.version} {ma}, {e.n_groups} jornadas, {e.n_matches} partidos", e.n_groups


# -- the one estimate ------------------------------------------------------------------------------------------------------------------

def estimate(a: Leg, b: Leg, *, matrices: Mapping[int, NDArray[np.float64]] | None = None,
             measured: Mapping[str, Measured] | None = None, matrix_basis: Mapping[int, str] | None = None) -> Dependence:
    """The dependence of two selections and its source (see the module's note for the order). Symmetric and pure."""
    lo_leg, hi_leg = (a, b) if a.ident <= b.ident else (b, a)
    i, j = lo_leg.ident, hi_leg.ident

    def dep(relation: Relation, source: Origin, basis: str, rho: float | None = None, low: float | None = None,
            high: float | None = None, sample: int | None = None) -> Dependence:
        return Dependence(i, j, relation, source, rho, low, high, basis, sample, window)

    window = abs(a.kickoff_at - b.kickoff_at) <= WINDOW
    if a.fixture_id == b.fixture_id:
        m = (matrices or {}).get(a.fixture_id)
        if m is None:
            return dep("same_match", UNMEASURED, "mismo partido sin matriz de marcadores")
        rho = matrix_rho(m, (lo_leg.market_key, lo_leg.selection, lo_leg.line), (hi_leg.market_key, hi_leg.selection, hi_leg.line))
        if rho is None:
            return dep("same_match", UNMEASURED, "mismo partido: la matriz no liquida el par sin devolución")
        model = (matrix_basis or {}).get(a.fixture_id, "")
        return dep("same_match", SCORE_MATRIX, f"{sm.VERSION} {model}".strip(), rho, rho, rho)
    if a.teams & b.teams:
        return dep("same_team", UNMEASURED, "mismo equipo en dos partidos: nada lo mide")
    if a.competition_id is not None and a.competition_id == b.competition_id:
        if local_day(a.kickoff_at) != local_day(b.kickoff_at):
            return dep("same_competition", UNMEASURED, "misma competición, otro día")
        found = _measured(lo_leg, hi_leg, measured)
        where = "misma jornada, misma ventana de saque" if window else "misma jornada"
        if isinstance(found, tuple):
            rho, low, high, basis, n = found
            return dep("same_competition_day", MEASURED, f"{where}; {basis}", rho, low, high, n)
        return dep("same_competition_day", UNMEASURED, f"{where}; {found}")
    if window:
        return dep("same_window", UNMEASURED, "misma ventana de saque, otra competición")
    return dep("none", NONE, "nada compartido", 0.0, 0.0, 0.0)


def pairs(legs: Sequence[Leg], *, matrices: Mapping[int, NDArray[np.float64]] | None = None,
          measured: Mapping[str, Measured] | None = None, matrix_basis: Mapping[int, str] | None = None) -> list[Dependence]:
    """Every pair that shares something (relation not ``none``), in the order of the legs."""
    out: list[Dependence] = []
    for n, a in enumerate(legs):
        for b in legs[n + 1:]:
            d = estimate(a, b, matrices=matrices, measured=measured, matrix_basis=matrix_basis)
            if d.relation != "none":
                out.append(d)
    return out


def joint_probability(legs: Sequence[Leg], probs: Sequence[float], *, matrices: Mapping[int, NDArray[np.float64]] | None = None,
                      measured: Mapping[str, Measured] | None = None) -> float | None:
    """P(every leg wins), from each leg's win probability and the pairs' ``joint_rho`` (the second-order Bahadur expansion of ``icc-v1``,
    exact for two legs); None when a pair cannot be combined. An unmeasured or uncertain positive dependence never raises it. Pure."""
    if len(legs) != len(probs):
        raise ValueError("one probability per leg")
    index = {leg.ident: n for n, leg in enumerate(legs)}
    used: list[tuple[int, int, float]] = []
    for d in pairs(legs, matrices=matrices, measured=measured):
        rho = d.joint_rho
        if rho is None:
            return None
        if rho != 0.0:
            used.append((index[d.a], index[d.b], rho))
    return icc.joint_probability(list(probs), used)

"""``parlay-v6``: the parlay rule of the definitive architecture (IA-110, plan piece AD-E06, owner's decision 6), PURE and in SHADOW.

WHY. ``parlay-v5`` (``fbi.parlays.persist``) builds up to 5 legs a day and 7 over several, multiplies the legs' pessimistic probabilities
with a correction for dependence that can only be negative, and takes its legs from the value gate of the daily set. Measured in production
on 16-nov-2026: 66 of 67 settled parlays lost, combined odds of 26.9 (daily) and 45.1 (several days) on average, and its legs won 38.9 % of
the time when the model gave them 58 % (n = 257 legs). The owner decided (16-nov-2026, decision 6): at most 3 legs, none if nothing meets.

THE RULE
  a leg ......... a selection CONFIRMED IN THE SHADOW BY ITSELF (the newest state of its chain of the cycle is ``confirmada_sombra``, IA-068):
                  no leg is let in to make up a parlay. Also: not kicked off ``MIN_LEAD`` before the moment, a line that cannot push
                  (1X2, double chance, both teams to score, half lines of totals and Asian handicap: a push inside a parlay has no clean
                  meaning), a price above 1 from at least ``MIN_BOOKS`` bookmakers («una sola casa» never confirms, value-v2), a probability
                  in (0, 1) with its pessimistic end, and value at its own price (odds x p > 1)
  a parlay ...... 2 to ``max_legs`` legs (``MAX_LEGS`` = 3 by default; the cap reaches the reader in contract C-04, never in the screen); at
                  most ``MAX_PER_MATCH`` legs of one match, never one team in two matches; a multi-day parlay spans two product days
  the joint ..... by SIMULATION (``joint``): a Gaussian copula over the legs, each leg's own probability as its margin, and between two legs
                  the dependence of ``corr-v2`` (``fbi.valuation.dependence``, IA-098): the same match from its score matrix (IA-074), across
                  matches the correlation measured on settled results only where it can make the joint smaller - a positive or unmeasured
                  dependence never raises it. A pair ``corr-v2`` cannot combine (one match without a matrix, one team) is no parlay. The
                  same draws give the joint at the legs' pessimistic ends and at the market's de-vigged probabilities
  the choice .... greedily by the expected log growth of a 1 % stake at the PESSIMISTIC joint, as v5: the leg that grows the parlay most,
                  added only while it still grows it - a leg is never added to raise the odds
  what it shows . combined odds, the joint and its Monte Carlo error, the joint at the pessimistic ends, the product of the legs, the market's
                  joint, the fair odds (1 / joint), the accumulated margin (1 - combined odds x the market's joint: what the books keep on
                  average, which grows with every leg) and the expected value
  none .......... no parlay when nothing meets: ``sin_candidatos``, ``un_solo_candidato`` or ``ninguna_combinacion_cumple``

No language model, no clock (``at`` is given), no database: the same inputs give the same parlay (the simulation's seed is the legs' keys).
PrediGol is not a bookmaker: nothing here takes a deposit, pays out early or offers a bonus. ``parlay-v5`` and its records are not touched.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr, ndtri

from fbi.ai.calendar import day_bounds, local_day
from fbi.valuation import dependence as dep

RULE_VERSION: Final = "parlay-v6"
MAX_LEGS: Final = 3
"""Decision 6 of the owner (16-nov-2026): at most three legs (the table refuses more: revision 0157)."""
MIN_LEGS: Final = 2
MAX_PER_MATCH: Final = 2
MIN_BOOKS: Final = 3
MIN_LEAD: Final = timedelta(minutes=10)
"""decision-v1's floor before kick-off (``fbi.intel.decision.MIN_MINUTES``): a leg starting sooner is not one."""
SIMULATIONS: Final = 100_000
STAKE_FRACTION: Final = 0.01
"""The stake whose growth chooses the legs (``fbi.picks.daily.STAKE_FRACTION``, held equal by a test)."""
MULTIDAY_WINDOW: Final = timedelta(hours=72)
CONFIRMED: Final = "confirmada_sombra"
Kind = Literal["daily", "multiday"]
NoneReason = Literal["sin_candidatos", "un_solo_candidato", "ninguna_combinacion_cumple"]
_QUAD_X, _QUAD_W = np.polynomial.legendre.leggauss(96)


@dataclass(frozen=True, slots=True)
class Spec:
    kind: Kind
    min_legs: int
    max_legs: int
    min_days: int


SPECS: Final[Mapping[str, Spec]] = {"daily": Spec("daily", MIN_LEGS, MAX_LEGS, 1), "multiday": Spec("multiday", MIN_LEGS, MAX_LEGS, 2)}


@dataclass(frozen=True, slots=True)
class Candidate:
    """A selection a parlay might hold: the newest row of its chain of the cycle and the decision it was confirmed by."""

    chain_key: str
    state: str
    """The newest state of the chain at the moment (only ``confirmada_sombra`` can be a leg)."""
    confirmed_id: int
    confirmed_at: datetime
    fixture_id: int
    competition_id: int | None
    kickoff_at: datetime
    teams: frozenset[int]
    market_key: str
    selection: str
    line: Decimal
    odds: float | None
    p: float | None
    """The probability it was judged on (the calibrated one when there is one)."""
    p_low: float | None
    p_market: float | None
    n_bookmakers: int | None
    source: str
    source_id: int
    price_at: datetime | None = None


def no_push(market_key: str, selection: str, line: Decimal) -> bool:
    """Whether the selection settles without a push or a half (its win indicator is defined at every score). Pure."""
    if market_key in ("1X2", "DC", "BTTS"):
        return line == 0 and selection in {"1X2": ("Home", "Draw", "Away"), "DC": ("1X", "12", "X2"), "BTTS": ("Yes", "No")}[market_key]
    if market_key in ("OU", "AH"):
        return abs(line * 2) % 2 == 1 and selection in (("Over", "Under") if market_key == "OU" else ("Home", "Away"))
    return False


def refusal(c: Candidate, *, at: datetime) -> str | None:
    """Why ``c`` cannot be a leg at ``at``, or None. The first rule that fails, in a fixed order. Pure."""
    if c.state != CONFIRMED:
        return "no_confirmada"
    if c.confirmed_at > at:
        return "confirmada_despues"
    if c.kickoff_at - MIN_LEAD <= at:
        return "empieza_ya"
    if not no_push(c.market_key, c.selection, c.line):
        return "linea_con_devolucion"
    if c.odds is None or not math.isfinite(c.odds) or c.odds <= 1:
        return "sin_precio"
    if (c.n_bookmakers or 0) < MIN_BOOKS:
        return "una_sola_casa"
    if c.p is None or not 0 < c.p < 1 or c.p_low is None or not 0 < c.p_low <= c.p:
        return "sin_probabilidad"
    if c.odds * c.p <= 1:
        return "sin_valor"
    return None


# -- the joint probability by simulation (pure) ---------------------------------------------------------------------------------------

def bvn(a: float, b: float, r: float) -> float:
    """P(X < a, Y < b) for a standard bivariate normal of correlation ``r`` (Gauss-Legendre over X; error < 1e-9 for |r| < 0.999)."""
    if r == 0:
        return float(ndtr(a) * ndtr(b))
    lo = -9.0
    hi = min(a, 9.0)
    if hi <= lo:
        return 0.0
    x = 0.5 * (hi - lo) * _QUAD_X + 0.5 * (hi + lo)
    w = 0.5 * (hi - lo) * _QUAD_W
    s = math.sqrt(1 - r * r)
    dens = np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    return float(np.sum(w * dens * ndtr((b - r * x) / s)))


def pair_target(pa: float, pb: float, phi: float) -> float:
    """P(both win) of two Bernoulli legs with margins ``pa``, ``pb`` and phi coefficient ``phi``, within the Fréchet bounds. Pure."""
    p = pa * pb + phi * math.sqrt(pa * (1 - pa) * pb * (1 - pb))
    return min(max(p, max(0.0, pa + pb - 1)), min(pa, pb))


def latent(pa: float, pb: float, phi: float) -> float:
    """The latent normal correlation under which two legs of margins ``pa``, ``pb`` have the phi coefficient ``phi`` (bisection). Pure."""
    if phi == 0:
        return 0.0
    ta, tb, target = float(ndtri(pa)), float(ndtri(pb)), pair_target(pa, pb, phi)
    lo, hi = -0.999, 0.999
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bvn(ta, tb, mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def seed_of(keys: Sequence[str]) -> int:
    """The simulation's seed: the legs' chain keys, sorted (the same legs give the same draws). Pure."""
    return int.from_bytes(hashlib.sha256("|".join(sorted(keys)).encode()).digest()[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


@dataclass(frozen=True, slots=True)
class Joint:
    """The joint probabilities of a set of legs, from ONE set of draws."""

    p: float
    se: float
    p_low: float
    p_market: float | None
    product: float
    simulations: int
    seed: int
    latent: tuple[tuple[int, int, float], ...]
    """The latent correlation of each dependent pair (legs i < j) the draws were made with."""


def joint(probs: Sequence[float], lows: Sequence[float], markets: Sequence[float | None], phis: Mapping[tuple[int, int], float], *,
          seed: int, simulations: int = SIMULATIONS) -> Joint | None:
    """P(every leg wins) by simulation: standard normals correlated by the latent correlation of each pair's phi (``phis``, from ``corr-v2``),
    a leg wins when its normal falls under its margin's quantile. The same draws give the joint at the pessimistic ends (``lows``) and at the
    market's probabilities (``markets``, when every leg has one). None when the pairs' dependence is incoherent (no correlation matrix).
    Bounded by the Fréchet limits: never above the smallest margin. Pure and deterministic (``seed``)."""
    k = len(probs)
    if k == 0 or len(lows) != k or len(markets) != k:
        raise ValueError("one probability, one low end and one market probability per leg")
    corr = np.eye(k)
    used: list[tuple[int, int, float]] = []
    for (i, j), phi in sorted(phis.items()):
        if phi != 0:
            r = latent(probs[i], probs[j], phi)
            corr[i, j] = corr[j, i] = r
            used.append((i, j, round(r, 6)))
    try:
        chol = np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        return None
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((simulations, k)) @ chol.T

    def frac(ps: Sequence[float]) -> float:
        t = ndtri(np.clip(np.asarray(ps, dtype=np.float64), 1e-12, 1 - 1e-12))
        return float(np.mean(np.all(z < t, axis=1)))

    def bound(x: float, ps: Sequence[float]) -> float:
        return min(max(x, max(0.0, sum(ps) - (k - 1))), min(ps))

    p = bound(frac(probs), probs)
    p_low = min(bound(frac(lows), lows), p)
    full = [m for m in markets if m is not None]
    p_mkt = bound(frac(full), full) if len(full) == k else None
    return Joint(p, math.sqrt(max(p * (1 - p), 1e-12) / simulations), p_low, p_mkt, math.prod(probs), simulations, seed, tuple(used))


# -- the choice (pure) ----------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Built:
    kind: str
    legs: tuple[Candidate, ...]
    combined_odds: float
    joint: Joint
    fair_odds: float
    accumulated_margin: float | None
    leg_margins: tuple[float | None, ...]
    expected_value: float
    expected_value_low: float
    expected_log_growth: float
    dependence: tuple[dict[str, Any], ...]
    n_candidates: int
    max_legs: int
    rule_version: str = RULE_VERSION

    @property
    def outcome(self) -> str:
        return "built"


@dataclass(frozen=True, slots=True)
class NoParlay:
    kind: str
    reason: NoneReason
    n_candidates: int
    refused: Mapping[str, int] = field(default_factory=dict)
    max_legs: int = MAX_LEGS
    rule_version: str = RULE_VERSION

    @property
    def outcome(self) -> str:
        return "none"


def growth(p: float, odds: float, f: float = STAKE_FRACTION) -> float:
    """Expected log growth of staking ``f`` on a bet of ``odds`` that wins with ``p``. Pure."""
    if p <= 0 or odds <= 1:
        return -math.inf
    return p * math.log(1 + f * (odds - 1)) + (1 - p) * math.log(1 - f)


def _leg(c: Candidate, n: int) -> dep.Leg:
    return dep.Leg(n, c.fixture_id, c.competition_id, c.kickoff_at, c.teams, c.market_key, c.selection, c.line)


def evaluate(legs: Sequence[Candidate], *, matrices: Mapping[int, NDArray[np.float64]] | None = None,
             measured: Mapping[str, dep.Measured] | None = None, matrix_basis: Mapping[int, str] | None = None,
             simulations: int = SIMULATIONS) -> tuple[Joint, list[dict[str, Any]]] | None:
    """The joint of a set of legs and the dependence it used, or None when ``corr-v2`` cannot combine a pair or the pairs are incoherent."""
    dleg = [_leg(c, n) for n, c in enumerate(legs)]
    phis: dict[tuple[int, int], float] = {}
    used: list[dict[str, Any]] = []
    for d in dep.pairs(dleg, matrices=matrices, measured=measured, matrix_basis=matrix_basis):
        rho = d.joint_rho
        if rho is None:
            return None
        phis[(d.a, d.b)] = rho
        used.append({**d.as_json(), "a_chain": legs[d.a].chain_key, "b_chain": legs[d.b].chain_key})
    j = joint([float(c.p or 0) for c in legs], [float(c.p_low or 0) for c in legs], [c.p_market for c in legs], phis,
              seed=seed_of([c.chain_key for c in legs]), simulations=simulations)
    return None if j is None else (j, used)


def _fits(legs: Sequence[Candidate], x: Candidate) -> bool:
    same = sum(1 for c in legs if c.fixture_id == x.fixture_id)
    if same >= MAX_PER_MATCH or any(c.chain_key == x.chain_key for c in legs):
        return False
    return not any(c.fixture_id != x.fixture_id and c.teams & x.teams for c in legs)


def window(kind: str, at: datetime) -> tuple[datetime, datetime]:
    """The kick-offs a parlay of ``kind`` built at ``at`` may hold: the product day (America/Bogota) or the next 72 hours."""
    if kind == "daily":
        return day_bounds(local_day(at))
    return at, at + MULTIDAY_WINDOW


def choose(pool: Sequence[Candidate], *, kind: str, at: datetime, max_legs: int = MAX_LEGS,
           matrices: Mapping[int, NDArray[np.float64]] | None = None, measured: Mapping[str, dep.Measured] | None = None,
           matrix_basis: Mapping[int, str] | None = None, simulations: int = SIMULATIONS) -> Built | NoParlay:
    """The parlay of ``kind`` at ``at`` from ``pool`` (the candidates of its window), or why there is none. Pure."""
    if not MIN_LEGS <= max_legs <= MAX_LEGS:
        raise ValueError(f"a parlay of {RULE_VERSION} has {MIN_LEGS} to {MAX_LEGS} legs")
    spec = SPECS[kind]
    frm, to = window(kind, at)
    refused: dict[str, int] = {}
    valid: list[Candidate] = []
    for c in sorted(pool, key=lambda x: (x.kickoff_at, x.chain_key)):
        why = "fuera_de_ventana" if not frm <= c.kickoff_at < to else refusal(c, at=at)
        if why is None:
            valid.append(c)
        else:
            refused[why] = refused.get(why, 0) + 1
    if not valid:
        return NoParlay(kind, "sin_candidatos", 0, refused, max_legs)
    if len(valid) == 1:
        return NoParlay(kind, "un_solo_candidato", 1, refused, max_legs)

    def score(legs: Sequence[Candidate]) -> tuple[float, tuple[Joint, list[dict[str, Any]]] | None]:
        if len(legs) == 1:
            c = legs[0]
            return growth(float(c.p_low or 0), float(c.odds or 0)), None
        got = evaluate(legs, matrices=matrices, measured=measured, matrix_basis=matrix_basis, simulations=simulations)
        if got is None:
            return -math.inf, None
        return growth(got[0].p_low, math.prod(float(c.odds or 0) for c in legs)), got

    legs: list[Candidate] = []
    best_growth = -math.inf
    best_eval: tuple[Joint, list[dict[str, Any]]] | None = None
    while len(legs) < max_legs:
        options = [x for x in valid if _fits(legs, x)]
        have = {local_day(c.kickoff_at) for c in legs}
        if spec.min_days > len(have) and spec.min_legs - len(legs) <= spec.min_days - len(have):
            options = [x for x in options if local_day(x.kickoff_at) not in have]
        scored = [(score([*legs, x]), x) for x in options]
        scored = [s for s in scored if s[0][0] > -math.inf]
        if not scored:
            break
        (g, ev), x = max(scored, key=lambda s: (s[0][0], s[1].chain_key))
        if len(legs) >= spec.min_legs and g <= best_growth:
            break
        legs.append(x)
        best_growth, best_eval = g, ev
    days = {local_day(c.kickoff_at) for c in legs}
    if len(legs) < spec.min_legs or len(days) < spec.min_days or best_eval is None or best_growth <= 0:
        return NoParlay(kind, "ninguna_combinacion_cumple", len(valid), refused, max_legs)
    j, used = best_eval
    odds = math.prod(float(c.odds or 0) for c in legs)
    margins = tuple(None if c.p_market is None else 1 - float(c.odds or 0) * c.p_market for c in legs)
    ordered = tuple(sorted(legs, key=lambda c: (c.kickoff_at, c.chain_key)))
    return Built(kind, ordered, odds, j, 1 / j.p if j.p > 0 else math.inf,
                 None if j.p_market is None else 1 - odds * j.p_market, margins, odds * j.p - 1, odds * j.p_low - 1, best_growth,
                 tuple(used), len(valid), max_legs)


# -- the result of a built parlay (pure) ----------------------------------------------------------------------------------------------

def outcome(results: Sequence[str | None], odds: Sequence[float]) -> tuple[str, float | None]:
    """A parlay's result from its legs' settlements (``settle-v4``: win, loss, void - its legs cannot push) and the payout factor of a
    1-unit stake: any loss LOST (0); every leg won WON (the product); some void the others' product (PARTIAL_VOID); all void VOID (1);
    any leg unsettled and none lost: ACTIVE (None). Pure."""
    if any(r == "loss" for r in results):
        return "LOST", 0.0
    if any(r is None for r in results):
        return "ACTIVE", None
    if any(r not in ("win", "void") for r in results):
        raise ValueError(f"a leg of {RULE_VERSION} cannot settle {sorted(str(r) for r in set(results) - {'win', 'void'})}")
    if all(r == "void" for r in results):
        return "VOID", 1.0
    factor = math.prod(o for r, o in zip(results, odds, strict=True) if r == "win")
    return ("PARTIAL_VOID" if "void" in results else "WON"), factor

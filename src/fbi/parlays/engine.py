"""The parlay engine: a value gate per leg, a correlation guard across legs.

Inputs are candidate selections (a pick, the model's probability, the market's
current de-vigged consensus and the best price available now). Nothing here touches
the database, so every rule is tested on plain values.

Value gate - every leg must have, at the moment the parlay is built:
  * a pick that QUALIFIED (its exact model version beat the de-vigged market in its own
    walk-forward backtest), from a model version that is not retired;
  * a fixture still scheduled, kicking off later than ``min_minutes_to_kickoff``;
  * a current price, captured no longer ago than ``max_price_age``, quoted by at least
    ``min_bookmakers`` books (the de-vigged consensus exists);
  * a positive expected value AT THAT CURRENT PRICE - the price the pick was made at
    does not count.

Correlation guard - across legs:
  * at most one selection per fixture (two selections on one match are dependent:
    "home win" and "over 2.5" move together, "home" and "away" contradict);
  * no team in two legs (two fixtures of one team in a short window share its news).

With those two rules the legs are distinct matches between distinct teams, so their
outcomes are treated as independent and the joint probability is the product. If the
guard is ever loosened so that a fixture repeats, the joint probability is NOT
computed (``None``) rather than multiplied naively.

Expected value of the parlay, per unit: the product of each leg's expected return
(1 + EV) minus one. That is exact for independent legs, pushes included: a pushed leg
returns its stake and the parlay continues with the others.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")

ParlayKind = Literal["daily", "multiday"]


class Reject(StrEnum):
    NOT_QUALIFIED = "not_qualified"
    MODEL_RETIRED = "model_retired"
    NOT_SCHEDULED = "not_scheduled"
    OUTSIDE_WINDOW = "outside_window"
    TOO_CLOSE_TO_KICKOFF = "too_close_to_kickoff"
    NO_PRICE = "no_price"
    STALE_PRICE = "stale_price"
    NO_CONSENSUS = "no_consensus"
    FEW_BOOKMAKERS = "few_bookmakers"
    NON_POSITIVE_EV = "non_positive_ev"
    SAME_FIXTURE = "same_fixture"
    SHARED_TEAM = "shared_team"
    DUPLICATE_SELECTION = "duplicate_selection"


@dataclass(frozen=True, slots=True)
class Candidate:
    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    fixture_status: str
    home_team_id: int
    away_team_id: int
    market_key: str
    selection: str
    line: Decimal
    qualified: bool
    model_status: str
    p_model: Decimal
    """Probability of winning CONDITIONAL on the bet being settled (no push), as the pick stores it."""
    p_push: Decimal | None
    p_market_fair: Decimal | None
    price: Decimal | None
    price_at: datetime | None
    n_bookmakers: int | None

    @property
    def selection_key(self) -> tuple[int, str, str, Decimal]:
        return (self.fixture_id, self.market_key, self.selection, self.line)


@dataclass(frozen=True, slots=True)
class GateConfig:
    max_price_age: timedelta = timedelta(hours=3)
    min_ev: Decimal = Decimal("0")
    """A leg needs EV strictly greater than this at the current price."""
    min_bookmakers: int = 2
    min_minutes_to_kickoff: int = 10
    allow_unqualified: bool = False
    """Only the Admin Console's shadow preview sets this. A user's parlay never does."""


@dataclass(frozen=True, slots=True)
class Leg:
    candidate: Candidate
    p_win: Decimal
    """Unconditional probability the leg wins: p_model * (1 - p_push)."""
    p_push: Decimal
    ev: Decimal
    """Expected value per unit staked on this leg alone, at the current price."""
    probability_edge: Decimal
    """p_model - p_market_fair, both conditional on the bet being settled."""


@dataclass(frozen=True, slots=True)
class Parlay:
    kind: ParlayKind
    status: Literal["ok", "no_valid_parlay"]
    legs: tuple[Leg, ...]
    required_legs: int
    max_legs: int
    eligible_legs: int
    window_from: datetime
    window_to: datetime
    combined_odds: Decimal | None
    probability_all_win: Decimal | None
    """Product of the legs' win probabilities; None when the legs are not independent."""
    expected_value: Decimal | None
    risk: Literal["moderate", "high", "very_high"] | None
    independence: Literal["distinct_fixtures_and_teams", "not_independent"] | None
    prices_as_of: datetime | None
    """The OLDEST price among the legs: the parlay is only as fresh as its stalest leg."""
    rejections: dict[str, int] = field(default_factory=dict)


def expected_value(p_model: Decimal, p_push: Decimal | None, price: Decimal) -> tuple[Decimal, Decimal]:
    """(EV per unit, unconditional win probability) at ``price``.

    ``p_model`` is conditional on the bet being settled; the stake is risked either way,
    so the win probability that pays is ``p_model * (1 - p_push)`` and a push returns the
    stake (contributes zero).
    """
    push = p_push if p_push is not None else Decimal(0)
    p_win = p_model * (Decimal(1) - push)
    p_lose = Decimal(1) - p_win - push
    return p_win * (price - Decimal(1)) - p_lose, p_win


def assess(c: Candidate, now: datetime, cfg: GateConfig) -> Leg | Reject:
    """The value gate for one selection. The first rule it fails is the answer."""
    if not c.qualified and not cfg.allow_unqualified:
        return Reject.NOT_QUALIFIED
    if c.model_status == "retired":
        return Reject.MODEL_RETIRED
    if c.fixture_status != "scheduled":
        return Reject.NOT_SCHEDULED
    if c.kickoff_at - now < timedelta(minutes=cfg.min_minutes_to_kickoff):
        return Reject.TOO_CLOSE_TO_KICKOFF
    if c.price is None or c.price_at is None:
        return Reject.NO_PRICE
    if now - c.price_at > cfg.max_price_age:
        return Reject.STALE_PRICE
    if c.p_market_fair is None:
        return Reject.NO_CONSENSUS
    if (c.n_bookmakers or 0) < cfg.min_bookmakers:
        return Reject.FEW_BOOKMAKERS
    push = c.p_push if c.p_push is not None else Decimal(0)
    ev, p_win = expected_value(c.p_model, c.p_push, c.price)
    if ev <= cfg.min_ev:
        return Reject.NON_POSITIVE_EV
    return Leg(candidate=c, p_win=p_win.quantize(Q6, ROUND_HALF_UP), p_push=push,
               ev=ev.quantize(Q6, ROUND_HALF_UP),
               probability_edge=(c.p_model - c.p_market_fair).quantize(Q6, ROUND_HALF_UP))


def gate(candidates: Iterable[Candidate], now: datetime, cfg: GateConfig) -> tuple[list[Leg], Counter[str]]:
    """Every candidate through the value gate; one leg per selection (the best EV)."""
    best: dict[tuple[int, str, str, Decimal], Leg] = {}
    rejections: Counter[str] = Counter()
    for c in candidates:
        verdict = assess(c, now, cfg)
        if isinstance(verdict, Reject):
            rejections[verdict.value] += 1
            continue
        key = c.selection_key
        if key in best:
            rejections[Reject.DUPLICATE_SELECTION.value] += 1
            if verdict.ev <= best[key].ev:
                continue
        best[key] = verdict
    return sorted(best.values(), key=_rank), rejections


def _rank(leg: Leg) -> tuple[Decimal, Decimal, datetime, int]:
    """Highest expected value first; then the likelier leg; then the earlier match."""
    return (-leg.ev, -leg.p_win, leg.candidate.kickoff_at, leg.candidate.pick_id)


def guard(legs: Sequence[Leg], max_legs: int) -> tuple[list[Leg], Counter[str]]:
    """Greedy over ranked legs: keep a leg unless it shares a fixture or a team with one kept."""
    kept: list[Leg] = []
    fixtures: set[int] = set()
    teams: set[int] = set()
    dropped: Counter[str] = Counter()
    for leg in legs:
        if len(kept) == max_legs:
            break
        c = leg.candidate
        if c.fixture_id in fixtures:
            dropped[Reject.SAME_FIXTURE.value] += 1
            continue
        if c.home_team_id in teams or c.away_team_id in teams:
            dropped[Reject.SHARED_TEAM.value] += 1
            continue
        kept.append(leg)
        fixtures.add(c.fixture_id)
        teams.update((c.home_team_id, c.away_team_id))
    return kept, dropped


def risk_of(probability: Decimal) -> Literal["moderate", "high", "very_high"]:
    if probability >= Decimal("0.30"):
        return "moderate"
    if probability >= Decimal("0.10"):
        return "high"
    return "very_high"


def combine(legs: Sequence[Leg]) -> tuple[Decimal, Decimal | None, Decimal]:
    """(combined odds, probability all legs win or None if dependent, expected value per unit)."""
    odds = Decimal(1)
    expected_return = Decimal(1)
    p_all = Decimal(1)
    for leg in legs:
        assert leg.candidate.price is not None
        odds *= leg.candidate.price
        expected_return *= Decimal(1) + leg.ev
        p_all *= leg.p_win
    independent = len({leg.candidate.fixture_id for leg in legs}) == len(legs)
    return (odds.quantize(Decimal("0.01"), ROUND_HALF_UP),
            p_all.quantize(Q6, ROUND_HALF_UP) if independent else None,
            (expected_return - Decimal(1)).quantize(Q4, ROUND_HALF_UP))


def build(kind: ParlayKind, candidates: Iterable[Candidate], *, now: datetime, window: timedelta,
          min_legs: int, max_legs: int, cfg: GateConfig | None = None) -> Parlay:
    """The parlay for one window, or a "no valid parlay" answer that says why."""
    if not 1 <= min_legs <= max_legs:
        raise ValueError("need 1 <= min_legs <= max_legs")
    cfg = cfg or GateConfig()
    until = now + window
    in_window: list[Candidate] = []
    outside = 0
    for c in candidates:
        if now <= c.kickoff_at < until:
            in_window.append(c)
        else:
            outside += 1
    legs, rejections = gate(in_window, now, cfg)
    kept, dropped = guard(legs, max_legs)
    rejections.update(dropped)
    if outside:
        rejections[Reject.OUTSIDE_WINDOW.value] += outside
    rejected = dict(sorted(rejections.items()))
    if len(kept) < min_legs:
        return Parlay(kind=kind, status="no_valid_parlay", legs=(), required_legs=min_legs, max_legs=max_legs,
                      eligible_legs=len(legs), window_from=now, window_to=until, combined_odds=None,
                      probability_all_win=None, expected_value=None, risk=None, independence=None,
                      prices_as_of=None, rejections=rejected)
    odds, p_all, ev = combine(kept)
    oldest = min(leg.candidate.price_at for leg in kept if leg.candidate.price_at is not None)
    return Parlay(kind=kind, status="ok", legs=tuple(sorted(kept, key=lambda leg: leg.candidate.kickoff_at)),
                  required_legs=min_legs, max_legs=max_legs, eligible_legs=len(legs), window_from=now,
                  window_to=until, combined_odds=odds, probability_all_win=p_all, expected_value=ev,
                  risk=risk_of(p_all) if p_all is not None else None,
                  independence="distinct_fixtures_and_teams" if p_all is not None else "not_independent",
                  prices_as_of=oldest, rejections=rejected)


@dataclass(frozen=True, slots=True)
class ParlaySpec:
    kind: ParlayKind
    window: timedelta
    min_legs: int
    max_legs: int


DAILY = ParlaySpec("daily", timedelta(hours=24), 5, 5)
"""The parlay of the day: five legs, kicking off in the next 24 hours."""
MULTIDAY = ParlaySpec("multiday", timedelta(hours=48), 6, 7)
"""Six or seven legs over the next two days."""
SPECS: dict[ParlayKind, ParlaySpec] = {"daily": DAILY, "multiday": MULTIDAY}

"""Will he start, and for how long (``player-engine-v1``): the probability of a start and the expected minutes, as of a moment.

THE CANDIDATES of a team are the men on its sheets (statistics) in its last ``RECENT_MATCHES`` covered matches whose newest sheet is
this team's (a man who has since played for another club is not a candidate here). A confirmed line-up replaces them with its sheet.

THE START. Before the line-up, the probability comes from the recency-weighted share of the team's recent matches he started (weights
``DECAY ** j``, j = 0 the newest), whether he started the last one, and whether the provider listed him as doubtful. Those three go
through a logistic calibration fitted on history, walk-forward (``StartModel``; ``fbi.players.backtest`` refits it on what was known
before each window and reports its Brier score and log-loss). Without a fitted model the share itself is the probability. Rules, not the
model, decide three cases: a man the provider lists as OUT does not start and does not play; a confirmed starter starts (1); a man on the
confirmed bench does not (0) and comes on with his own rate of coming on from the bench; a man left off a confirmed sheet does not play.

THE MINUTES. If he starts, the recency-weighted mean of his minutes in his recent starts; if he comes on, of his recent appearances
from the bench; both shrunk towards the mean of his position. Expected minutes = P(start) x minutes if he starts + P(comes on) x
minutes if he comes on. Pure functions of a ``History``: no database, no clock.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from fbi.players.history import DOUBTFUL, OUT, History, SheetLine

RECENT_MATCHES: Final = 10
DECAY: Final = 0.8
START_SMOOTHING: Final = 0.25
"""Pseudo-starts added to the weighted share, (starts + 0.25) / (weight + 0.5): a share of exactly 0 or 1 has no logit."""
MINUTES_PSEUDO: Final = 2.0
"""Matches' worth of the position's mean in a player's minutes (his own mean after two starts weighs as much as the position's)."""
DEFAULT_START_MINUTES: Final = 85.0
DEFAULT_SUB_MINUTES: Final = 20.0
DEFAULT_BENCH_RATE: Final = 0.5
"""Used only before the history holds a single start, sub or bench of the position (the first match of a fresh history)."""
OFF_PRIOR_FRACTION: Final = 0.5
"""The prior of P(comes on | does not start) as a fraction of the position's bench rate: a SETTING, not a measurement (a man who does
not start may not be in the squad at all). It weighs two matches; his own record replaces it after a few."""
RIDGE: Final = 1.0
MIN_FIT_SAMPLES: Final = 500

CONFIRMED_STARTER: Final = "confirmed_starter"
CONFIRMED_BENCH: Final = "confirmed_bench"
NOT_IN_LINEUP: Final = "not_in_lineup"
RULED_OUT: Final = "out"
PREDICTED: Final = "predicted"


@dataclass(frozen=True, slots=True)
class StartFeatures:
    share: float
    """Smoothed, recency-weighted share of the team's recent covered matches he started."""
    started_last: bool
    doubtful: bool
    matches: int
    """Covered team matches behind the share."""

    def vector(self) -> list[float]:
        p = min(max(self.share, 1e-4), 1 - 1e-4)
        return [1.0, math.log(p / (1 - p)), 1.0 if self.started_last else 0.0, 1.0 if self.doubtful else 0.0]


def start_features(h: History, team_id: int, player_id: int, *, doubtful: bool = False) -> StartFeatures:
    recent = h.recent_team(team_id, RECENT_MATCHES)
    w = s = 0.0
    for j, tm in enumerate(recent):
        weight = DECAY ** j
        w += weight
        line = tm.men.get(player_id)
        if line is not None and line.started:
            s += weight
    last = recent[0].men.get(player_id) if recent else None
    return StartFeatures((s + START_SMOOTHING) / (w + 2 * START_SMOOTHING), bool(last is not None and last.started), doubtful,
                         len(recent))


def candidates(h: History, team_id: int) -> list[int]:
    """The men of the team's recent sheets whose newest sheet is this team's."""
    seen: set[int] = set()
    for tm in h.recent_team(team_id, RECENT_MATCHES):
        seen.update(tm.men)
    return sorted(p for p in seen if h.last_team(p) == team_id)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def fit_logistic(x: Sequence[Sequence[float]], y: Sequence[int], ridge: float = RIDGE, iterations: int = 50) -> tuple[float, ...]:
    """Ridge-penalised logistic regression by Newton steps (the intercept is not penalised)."""
    xx = np.asarray(x, dtype=np.float64)
    yy = np.asarray(y, dtype=np.float64)
    beta = np.zeros(xx.shape[1])
    penalty = np.eye(xx.shape[1]) * ridge
    penalty[0, 0] = 0.0
    for _ in range(iterations):
        z = np.clip(xx @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = xx.T @ (p - yy) + penalty @ beta
        hess = (xx * (p * (1 - p))[:, None]).T @ xx + penalty + np.eye(xx.shape[1]) * 1e-9
        step = np.linalg.solve(hess, grad)
        beta = beta - step
        if float(np.abs(step).max()) < 1e-8:
            break
    return tuple(float(b) for b in beta)


@dataclass(frozen=True, slots=True)
class StartModel:
    """The calibration of the start probability. ``coef`` None: not fitted, the smoothed share is the probability."""

    coef: tuple[float, ...] | None = None
    samples: int = 0

    def p(self, f: StartFeatures) -> float:
        if self.coef is None:
            return f.share
        return _sigmoid(sum(c * v for c, v in zip(self.coef, f.vector(), strict=True)))

    @staticmethod
    def fit(features: Sequence[StartFeatures], started: Sequence[int]) -> StartModel:
        if len(features) < MIN_FIT_SAMPLES or len(set(started)) < 2:
            return StartModel(None, len(features))
        return StartModel(fit_logistic([f.vector() for f in features], started), len(features))


@dataclass(frozen=True, slots=True)
class Minutes:
    if_start: float
    if_sub: float
    bench_rate: float
    """P(comes on | on the bench)."""
    off_rate: float
    """P(comes on | does not start), whether on the bench or not in the squad."""


def _shrunk_mean(values: Sequence[float], prior: float, pseudo: float = MINUTES_PSEUDO) -> float:
    w = num = 0.0
    for j, v in enumerate(values):
        weight = DECAY ** j
        w += weight
        num += weight * v
    return (num + pseudo * prior) / (w + pseudo)


def _pos_mean(acc: Mapping[str, list[float]], pos: str, default: float) -> float:
    a = acc.get(pos)
    if a and a[1] > 0:
        return a[0] / a[1]
    total = sum(v[0] for v in acc.values())
    n = sum(v[1] for v in acc.values())
    return total / n if n > 0 else default


def minutes_profile(h: History, team_id: int, player_id: int, position: str) -> Minutes:
    apps = h.recent_apps(player_id, 40)
    starts = [float(a.line.minutes) for a in apps if a.line.started][:RECENT_MATCHES]
    subs = [float(a.line.minutes) for a in apps if not a.line.started and a.line.played][:RECENT_MATCHES]
    benches = [1.0 if a.line.played else 0.0 for a in apps if not a.line.started][:RECENT_MATCHES]
    bench_prior = _pos_mean(h.pos_bench, position, DEFAULT_BENCH_RATE)
    off: list[float] = []
    for tm in h.recent_team(team_id, RECENT_MATCHES):
        line = tm.men.get(player_id)
        if line is None or not line.started:
            off.append(1.0 if line is not None and line.played else 0.0)
    return Minutes(
        if_start=_shrunk_mean(starts, _pos_mean(h.pos_start_minutes, position, DEFAULT_START_MINUTES)),
        if_sub=_shrunk_mean(subs, _pos_mean(h.pos_sub_minutes, position, DEFAULT_SUB_MINUTES)),
        bench_rate=_shrunk_mean(benches, bench_prior),
        off_rate=_shrunk_mean(off, bench_prior * OFF_PRIOR_FRACTION),
    )


@dataclass(frozen=True, slots=True)
class Availability:
    p_start: float
    p_sub: float
    """P(does not start and comes on)."""
    minutes_start: float
    minutes_sub: float
    basis: str
    share: float | None = None
    absence: str | None = None

    @property
    def p_play(self) -> float:
        return self.p_start + self.p_sub

    @property
    def expected_minutes(self) -> float:
        return self.p_start * self.minutes_start + self.p_sub * self.minutes_sub

    def scenarios(self) -> list[tuple[float, float]]:
        """(probability, minutes) of starting and of coming on; the rest of the mass is not playing (0 minutes)."""
        return [(self.p_start, self.minutes_start), (self.p_sub, self.minutes_sub)]

    def as_json(self) -> dict[str, object]:
        return {"basis": self.basis, "p_start": round(self.p_start, 4), "p_sub": round(self.p_sub, 4), "p_play": round(self.p_play, 4),
                "minutes_if_start": round(self.minutes_start, 1), "minutes_if_sub": round(self.minutes_sub, 1),
                "expected_minutes": round(self.expected_minutes, 1), "share": None if self.share is None else round(self.share, 4),
                "absence": self.absence}


def availability(h: History, model: StartModel, team_id: int, player_id: int, position: str, *, absence: str | None = None,
                 sheet: Mapping[int, SheetLine] | None = None) -> Availability:
    """P(start) and the minutes of one man as of the moment ``h`` stands at. ``sheet``: the team's confirmed line-up, when there is one."""
    m = minutes_profile(h, team_id, player_id, position)
    if absence == OUT:
        return Availability(0.0, 0.0, m.if_start, m.if_sub, RULED_OUT, absence=OUT)
    if sheet is not None:
        line = sheet.get(player_id)
        if line is None:
            return Availability(0.0, 0.0, m.if_start, m.if_sub, NOT_IN_LINEUP, absence=absence)
        if line.is_starter:
            return Availability(1.0, 0.0, m.if_start, m.if_sub, CONFIRMED_STARTER, absence=absence)
        return Availability(0.0, m.bench_rate, m.if_start, m.if_sub, CONFIRMED_BENCH, absence=absence)
    f = start_features(h, team_id, player_id, doubtful=absence == DOUBTFUL)
    p = model.p(f)
    return Availability(p, (1.0 - p) * m.off_rate, m.if_start, m.if_sub, PREDICTED, share=f.share, absence=absence)

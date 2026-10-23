"""Does the real calendar make the model that reads rest score better? - the pre-registered experiment of plan F4.4 (protocol ``rest-ab-v1``).

THE QUESTION
------------
PrediGol's multinomial-logit family reads the days of rest of both sides (``home_rest_days`` and ``away_rest_days``; their difference,
clipped to a week, is one of its eight inputs). Those days are counted from the matches in the competitions PrediGol follows: a team that
played a cup tie two days ago has "eight days of rest" when its last league match was eight days ago. The calendar of F4 knows the cup tie.
Does the same model, reading the real rest (and the real load of the last fortnight), score better out of sample than reading the rest as it
is read today? Nothing in production changes by asking: this module trains throwaway models on a sample, scores them and writes a verdict.

THE ARMS (the same eight inputs, the same fit - ``fbi.models.logistic`` with its production penalty - on the same matches)
-------------------------------------------------------------------------------------------------------------------------
* ``production``      the stored feature set as it is: ``rest_diff`` counted from the followed competitions only;
* ``true_rest``       ``rest_diff`` taken from the shorter of the two: what production counted, or the days since the last match the
                      calendar knows outside the followed competitions (so the calendar can only *shorten* a rest, never lengthen it);
* ``true_rest_load``  ``true_rest`` plus one input, the difference in matches played in the last fortnight in any competition;
* ``no_rest``         ``rest_diff`` removed (a constant): how much the production rest is worth at all.

THE VERDICT IS ARITHMETIC AND FIXED BEFORE THE RUN
--------------------------------------------------
The window, the refit cadence, the minimum sizes and the margins below were written down before any outcome of these models was looked at; a
change to any of them is a new protocol version. The score is the log loss of the 1X2 probabilities (a proper rule; Brier and RPS are
reported beside it). The test is walk-forward: a block of ``step_days`` is predicted by models fitted on the matches whose result was known
(kick-off + 3 h) before the block began. The unit is the match; the uncertainty is a bootstrap that resamples whole match DAYS, because the
matches of one day share a weekend, a rating state and a referee pool.

  promising     the 95% interval of (true_rest - production) in log loss per match lies wholly below zero and its mean is at least
                ``min_gain`` better: the real rest is worth taking to the full gate (F10 / F14);
  harmful       the interval lies wholly above zero: the real rest makes the model worse;
  inconclusive  anything else, and always while the test blocks hold fewer than ``min_test`` matches.

``promising`` promotes nothing: it only says the full gate is worth running. The secondary pairs are reported, never decisive.

WHAT IT DOES NOT SHOW
---------------------
The sample is the matches whose two calendars are whole (``fbi.research.rest_features``): the current seasons of the teams the feed reads, so
a sample is thin until weeks of fixtures have been played and read. Rest is a small effect: a sample of a few thousand matches can only see a
gain of about a thousandth of a nat per match, and ``inconclusive`` then means "not enough evidence yet", not "no effect". The minimum
detectable difference is reported to say so.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from fbi.features.engine import RESULT_AVAILABLE_AFTER
from fbi.models.families import MNLOGIT_FEATURES, mnlogit_row
from fbi.models.logistic import LogisticModel, fit_logistic
from fbi.models.metrics import (
    block_bootstrap_ci,
    brier,
    log_loss,
    minimum_detectable_difference,
    per_match_log_loss,
    rps,
)

PROTOCOL: Final = "rest-ab-v1"
REST_CAP: Final = 7.0
"""Days: as production's ``mnlogit_row``, the difference of rest is clipped to a week either way."""
REST_AT: Final = MNLOGIT_FEATURES.index("rest_diff")
LOAD_INPUT: Final = "load14_diff"

ARMS: Final = ("production", "true_rest", "true_rest_load", "no_rest")
PRIMARY: Final = ("true_rest", "production")
"""(arm, reference): the only pair that decides."""
SECONDARY: Final = (("true_rest_load", "production"), ("no_rest", "production"), ("true_rest_load", "true_rest"))

Incomplete = Literal["not_read_after_the_match", "unconfirmed_match", "no_previous_match"]
Verdict = Literal["promising", "harmful", "inconclusive"]


@dataclass(frozen=True, slots=True)
class SideRest:
    """One side of one match, as the calendar knows it at the match's kick-off (``fbi.research.rest_features`` fills it)."""

    rest_days: float | None
    """Since the last match played in ANY competition (None: none known in the look-back)."""
    rest_days_tracked: float | None
    """Since the last match of a competition PrediGol follows."""
    rest_days_outside: float | None
    """Since the last match of a competition PrediGol does not follow (None: none in the look-back)."""
    played_7d: int
    played_14d: int
    played_30d: int
    outside_14d: int
    """Of ``played_14d``, those in a competition PrediGol does not follow."""
    next_gap_days: float | None
    """Days to the next match within the week after this one, as known when the list was read (None: none known). Context only: a
    list read after the match may know a next match that was announced after it, so it takes no part in the arms."""
    next_competition_type: str | None
    whole: bool
    """Is this side's calendar whole for this match (``fbi.research.rest_features.side_rest`` says when)?"""
    reason: Incomplete | None


@dataclass(frozen=True, slots=True)
class Observation:
    """A finished match with the stored feature set production read for it and the calendar of each side."""

    fixture_id: int
    kickoff_at: datetime
    outcome: int
    """0 home win, 1 draw, 2 away win (regulation time)."""
    values: Mapping[str, float | None]
    """The stored feature set (``features.fixture_features``)."""
    home: SideRest
    away: SideRest


@dataclass(frozen=True, slots=True)
class Protocol:
    """Everything the verdict depends on, fixed before the run. A change is a new protocol version."""

    step_days: int = 14
    min_train: int = 1500
    min_test: int = 2000
    l2: float = 1.0
    """As production's multinomial logit."""
    min_gain: float = 0.0005
    """Log loss per match the real rest must win by, besides the interval lying wholly below zero."""
    draws: int = 2000
    seed: int = 11
    level: float = 0.95

    def as_dict(self) -> dict[str, Any]:
        return {"protocol": PROTOCOL, "step_days": self.step_days, "min_train": self.min_train, "min_test": self.min_test,
                "l2": self.l2, "min_gain": self.min_gain, "draws": self.draws, "seed": self.seed, "level": self.level,
                "rest_cap": REST_CAP, "arms": list(ARMS), "primary": list(PRIMARY)}


# --------------------------------------------------------------------------------------------------------- the inputs


def clip(value: float) -> float:
    return max(-REST_CAP, min(REST_CAP, value))


def true_rest(production: float | None, outside: float | None) -> float | None:
    """The shorter of the rest production counted and the days since the last match outside the followed competitions."""
    known = [x for x in (production, outside) if x is not None]
    return min(known) if known else None


def true_rest_diff(o: Observation) -> float | None:
    home = true_rest(o.values.get("home_rest_days"), o.home.rest_days_outside)
    away = true_rest(o.values.get("away_rest_days"), o.away.rest_days_outside)
    return None if home is None or away is None else clip(home - away)


def arm_features(arm: str) -> tuple[str, ...]:
    return (*MNLOGIT_FEATURES, LOAD_INPUT) if arm == "true_rest_load" else MNLOGIT_FEATURES


def arm_row(arm: str, o: Observation) -> list[float | None]:
    """The model's inputs for one match in one arm: production's eight, with the rest changed as the arm says."""
    row = mnlogit_row(dict(o.values))
    if arm == "production":
        return row
    if arm == "no_rest":
        row[REST_AT] = None
        return row
    row[REST_AT] = true_rest_diff(o)
    if arm == "true_rest_load":
        row.append(float(o.home.played_14d - o.away.played_14d))
    elif arm != "true_rest":
        raise ValueError(f"unknown arm {arm!r}")
    return row


# ------------------------------------------------------------------------------------------------------- the scores


@dataclass(frozen=True, slots=True)
class Pair:
    """Two arms over the same matches. ``diff`` is arm - reference in mean log loss: negative means the arm is better."""

    arm: str
    reference: str
    n: int
    days: int
    loss_arm: float
    loss_reference: float
    diff: float
    lo: float
    hi: float
    brier_arm: float
    brier_reference: float
    rps_arm: float
    rps_reference: float
    minimum_detectable: float
    """The smallest true difference this sample would have shown with 80% power: a smaller one goes unseen."""

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in
                ((f, getattr(self, f)) for f in self.__dataclass_fields__)}


def pair(arm: str, reference: str, p_arm: NDArray[np.float64], p_ref: NDArray[np.float64], y: NDArray[np.int64],
         days: Sequence[object], protocol: Protocol) -> Pair:
    d = per_match_log_loss(p_arm, y) - per_match_log_loss(p_ref, y)
    mean, lo, hi, blocks = block_bootstrap_ci(d, list(days), draws=protocol.draws, level=protocol.level, seed=protocol.seed)
    se = (hi - lo) / (2 * 1.959964)
    return Pair(arm=arm, reference=reference, n=len(y), days=blocks, loss_arm=log_loss(p_arm, y),
                loss_reference=log_loss(p_ref, y), diff=mean, lo=lo, hi=hi, brier_arm=brier(p_arm, y),
                brier_reference=brier(p_ref, y), rps_arm=rps(p_arm, y), rps_reference=rps(p_ref, y),
                minimum_detectable=minimum_detectable_difference(d, level=protocol.level, se=se))


def verdict_of(primary: Pair | None, protocol: Protocol) -> tuple[Verdict, str]:
    """The arithmetic: (verdict, why)."""
    if primary is None:
        return "inconclusive", "no match was predicted: the sample is too small to fit and test"
    if primary.n < protocol.min_test:
        return "inconclusive", f"{primary.n} matches predicted, {protocol.min_test} needed: not enough evidence yet"
    if primary.lo > 0:
        return "harmful", "the 95% interval of the change in log loss lies wholly above zero: the real rest makes the model worse"
    if primary.hi < 0 and -primary.diff >= protocol.min_gain:
        return "promising", (f"the 95% interval lies wholly below zero and the gain is {-primary.diff:.5f} nats per match "
                             f"(at least {protocol.min_gain}): worth the full gate")
    if primary.hi < 0:
        return "inconclusive", (f"better, but by {-primary.diff:.5f} nats per match, less than the {protocol.min_gain} the "
                                f"protocol asks")
    return "inconclusive", "the 95% interval of the change in log loss includes zero"


@dataclass(frozen=True, slots=True)
class Result:
    protocol: dict[str, Any]
    verdict: Verdict
    why: str
    n_sample: int
    n_tested: int
    blocks: int
    first_kickoff: datetime | None
    last_kickoff: datetime | None
    primary: Pair | None
    secondary: tuple[Pair, ...]
    description: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"protocol": self.protocol, "verdict": self.verdict, "why": self.why, "n_sample": self.n_sample,
                "n_tested": self.n_tested, "blocks": self.blocks,
                "first_kickoff": None if self.first_kickoff is None else self.first_kickoff.isoformat(),
                "last_kickoff": None if self.last_kickoff is None else self.last_kickoff.isoformat(),
                "primary": None if self.primary is None else self.primary.as_dict(),
                "secondary": [p.as_dict() for p in self.secondary], "sample": self.description}


def describe(observations: Sequence[Observation]) -> dict[str, Any]:
    """What the calendar changes in the sample, before any model: how often, and by how many days, the real rest of a side is
    shorter than the rest production counted."""
    shortened: list[float] = []
    sides = 0
    outside = 0
    for o in observations:
        for prod, side in ((o.values.get("home_rest_days"), o.home), (o.values.get("away_rest_days"), o.away)):
            sides += 1
            outside += 1 if side.outside_14d > 0 else 0
            real = true_rest(prod, side.rest_days_outside)
            if prod is not None and real is not None:
                shortened.append(float(prod) - real)
    if not shortened:
        return {"sides": sides, "with_rest": 0}
    gaps = np.asarray(shortened, dtype=np.float64)
    return {
        "sides": sides, "with_rest": len(shortened),
        "sides_with_an_outside_match_in_14d": outside,
        "share_with_an_outside_match_in_14d": round(outside / sides, 4),
        "share_rest_shorter_by_1d_or_more": round(float((gaps >= 1.0).mean()), 4),
        "share_rest_shorter_by_2d_or_more": round(float((gaps >= 2.0).mean()), 4),
        "mean_days_shorter": round(float(gaps.mean()), 3),
        "p50_days_shorter": round(float(np.quantile(gaps, 0.5)), 3),
        "p90_days_shorter": round(float(np.quantile(gaps, 0.9)), 3),
        "max_days_shorter": round(float(gaps.max()), 3),
    }


# -------------------------------------------------------------------------------------------------------- the test


def blocks_of(observations: Sequence[Observation], step: timedelta) -> list[tuple[datetime, list[Observation], list[Observation]]]:
    """(block start, the matches known before it, the matches in it) for every block after the first."""
    if not observations:
        return []
    first = observations[0].kickoff_at
    last = observations[-1].kickoff_at
    out: list[tuple[datetime, list[Observation], list[Observation]]] = []
    start = first + step
    while start <= last:
        train = [o for o in observations if o.kickoff_at + RESULT_AVAILABLE_AFTER <= start]
        test = [o for o in observations if start <= o.kickoff_at < start + step]
        if test:
            out.append((start, train, test))
        start += step
    return out


def fit_arm(arm: str, train: Sequence[Observation], protocol: Protocol) -> LogisticModel:
    return fit_logistic([arm_row(arm, o) for o in train], [o.outcome for o in train], features=arm_features(arm), l2=protocol.l2)


def run(observations: Sequence[Observation], protocol: Protocol | None = None) -> Result:
    """The walk-forward test of every arm on the matches with a whole calendar on both sides, and the verdict."""
    protocol = protocol or Protocol()
    sample = sorted((o for o in observations if o.home.whole and o.away.whole), key=lambda o: (o.kickoff_at, o.fixture_id))
    description = describe(sample)
    probabilities: dict[str, list[tuple[float, float, float]]] = {arm: [] for arm in ARMS}
    outcomes: list[int] = []
    days: list[object] = []
    used = 0
    for _start, train, test in blocks_of(sample, timedelta(days=protocol.step_days)):
        if len(train) < protocol.min_train:
            continue
        used += 1
        models = {arm: fit_arm(arm, train, protocol) for arm in ARMS}
        for o in test:
            for arm in ARMS:
                probabilities[arm].append(models[arm].predict(arm_row(arm, o)))
            outcomes.append(o.outcome)
            days.append(o.kickoff_at.date())
    first = sample[0].kickoff_at if sample else None
    last = sample[-1].kickoff_at if sample else None
    if not outcomes:
        verdict, why = verdict_of(None, protocol)
        return Result(protocol.as_dict(), verdict, why, len(sample), 0, 0, first, last, None, (), description)
    y = np.asarray(outcomes, dtype=np.int64)
    p = {arm: np.asarray(rows, dtype=np.float64) for arm, rows in probabilities.items()}
    primary = pair(*PRIMARY, p[PRIMARY[0]], p[PRIMARY[1]], y, days, protocol)
    secondary = tuple(pair(a, b, p[a], p[b], y, days, protocol) for a, b in SECONDARY)
    verdict, why = verdict_of(primary, protocol)
    return Result(protocol.as_dict(), verdict, why, len(sample), len(y), used, first, last, primary, secondary, description)

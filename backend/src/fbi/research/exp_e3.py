"""EXP-E3 of the plan (RP-9.3): do corners and cards, calibrated without reading the market, stand within +0.005 of the market of the same line?

The protocol is ``fbi.research.exp_protocol.E3`` (registered and fingerprinted on 2026-11-26). This module COUNTS the sample and RUNS the comparison; thresholds,
interval by days, Holm and the verdict are those of ``exp_protocol`` / ``exp_common``.

What it reads (0 provider requests, 0 AI): the settled decisions of the over/under markets of corners and cards (``CORNERS_OU``, ``CORNERS_OU_HOME``,
``CORNERS_OU_AWAY``; ``CARDS_OU``, ``CARDS_OU_HOME``, ``CARDS_OU_AWAY``), the LAST decision of each selection before the kick-off: the raw probability of the
model (``p_model``: the figure before any calibrator, which reads no market) and the consensus of the market on the same line at the close
(``intel.decision_outcomes.close_p_fair``). A decision on the Under is the same question as one on the Over, so each row is read as «the Over happens» (the
probability of an Under is one minus the Over's) and a match with both is one row: nothing is counted twice. A decision that settled as a push, a void or half
a win is not a yes/no a probability can be read against and is left out.

CALIBRATION, day by day: for each day, the raw probabilities are mapped by a logistic regression (intercept and slope on the log odds) fitted ONLY on the
selections of the same family that settled before that day. A day with fewer than ``MIN_TRAIN`` earlier selections (or all of one outcome) has no calibrator, and
its selections are not scored (what one side does not predict does not count). The training may use selections from before the signature of the protocol (it is the
past, which the model could have known); what is SCORED is only what kicked off AFTER the signature day. The difference is the loss of the calibrated model minus the
loss of the market, per selection; families are corners and cards, Holm over the two, and the verdict is the one of ``exp_common.judge_segments``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final

import numpy as np
import psycopg
from psycopg.rows import dict_row

from fbi.core.decision_versions import DECISION_CORE
from fbi.research import exp_conditions, exp_protocol
from fbi.research.exp_common import judge_segments
from fbi.research.exp_protocol import Judgement

KEY: Final = "EXP-E3"
FAMILIES: Final = {
    "córneres": ("CORNERS_OU", "CORNERS_OU_HOME", "CORNERS_OU_AWAY"),
    "tarjetas": ("CARDS_OU", "CARDS_OU_HOME", "CARDS_OU_AWAY"),
}
MIN_TRAIN: Final = 100
"""The settled selections of the family before a day that a calibrator needs (with both outcomes among them)."""
CLIP: Final = 1e-6
TRAINING_FROM: Final = datetime(2026, 10, 1, tzinfo=UTC)

ROWS_SQL: Final = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.id, d.fixture_id, d.kickoff_at, d.market_key, d.selection, d.line,
           d.p_model, COALESCE(d.p_push, 0) AS p_push
      FROM intel.decisions d
     WHERE d.decision_version = %(version)s AND d.market_key = ANY(%(markets)s) AND d.selection IN ('Over', 'Under')
       AND d.kickoff_at >= %(start)s AND d.kickoff_at < %(until)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.id, l.fixture_id, l.kickoff_at, l.market_key, l.selection, l.line, l.p_model::float8 AS p, l.p_push::float8 AS p_push,
       o.result_status, o.close_p_fair::float8 AS q
  FROM last l JOIN intel.decision_outcomes o ON o.decision_id = l.id
 WHERE o.result_status IN ('win', 'loss') AND o.close_p_fair IS NOT NULL
 ORDER BY l.kickoff_at, l.fixture_id, l.market_key, l.line, l.selection
"""
"""The last decision of each selection of these markets that settled as a win or a loss and has a market at the close."""


@dataclass(frozen=True, slots=True)
class Selection:
    """One yes/no of the experiment, read as «the Over happens»."""

    fixture: int
    family: str
    day: date
    p: float
    q: float
    over: int


def family_of(market: str) -> str | None:
    return next((f for f, markets in FAMILIES.items() if market in markets), None)


def load(conn: psycopg.Connection[Any], *, start: datetime, until: datetime) -> list[Selection]:
    """The settled selections with kick-off in ``[start, end)``, one per (match, market, line), each read as the Over. Reads only."""
    markets = [m for ms in FAMILIES.values() for m in ms]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"version": DECISION_CORE, "markets": markets, "start": start, "until": until})
        rows = cur.fetchall()
    seen: dict[tuple[int, str, Decimal], Selection] = {}
    for r in rows:
        line = Decimal(r["line"])
        if r["p_push"] != 0.0 or (line * 2) % 1 != 0:
            continue
        family = family_of(str(r["market_key"]))
        if family is None:
            continue
        over = r["selection"] == "Over"
        won = r["result_status"] == "win"
        p, q = (r["p"], r["q"]) if over else (1.0 - r["p"], 1.0 - r["q"])
        happened = int(won) if over else int(not won)
        key = (int(r["fixture_id"]), str(r["market_key"]), line)
        seen.setdefault(key, Selection(int(r["fixture_id"]), family, r["kickoff_at"].date(), float(p), float(q), happened))
    return sorted(seen.values(), key=lambda s: (s.day, s.fixture))


def _logit(p: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    clipped = np.clip(p, CLIP, 1 - CLIP)
    return np.asarray(np.log(clipped / (1 - clipped)), dtype=float)


def platt(p: Sequence[float], y: Sequence[int]) -> tuple[float, float] | None:
    """(intercept, slope) of the logistic regression of the outcome on the log odds of ``p`` (a few Newton steps with a light ridge), or None when there are
    fewer than ``MIN_TRAIN`` points or the outcome is always the same."""
    if len(p) < MIN_TRAIN or len(set(y)) < 2:
        return None
    x = _logit(np.asarray(p, dtype=float))
    t = np.asarray(y, dtype=float)
    design = np.column_stack([np.ones_like(x), x])
    beta = np.array([0.0, 1.0])
    for _ in range(25):
        z = design @ beta
        mu = 1.0 / (1.0 + np.exp(-z))
        w = np.maximum(mu * (1 - mu), 1e-9)
        grad = design.T @ (t - mu) - 1e-4 * (beta - np.array([0.0, 1.0]))
        hess = (design * w[:, None]).T @ design + 1e-4 * np.eye(2)
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return float(beta[0]), float(beta[1])


def apply(coef: tuple[float, float], p: float) -> float:
    z = coef[0] + coef[1] * float(_logit(np.array([p]))[0])
    return float(min(max(1.0 / (1.0 + np.exp(-z)), CLIP), 1 - CLIP))


def calibrated(rows: Sequence[Selection], *, after: date) -> tuple[dict[str, list[tuple[Selection, float]]], int]:
    """Day by day, each family's selections that kicked off after ``after`` with the probability a calibrator fitted ONLY on the earlier days gives them (every
    selection of the family before that day trains it, whatever its date), and how many could not be scored for want of a calibrator."""
    by_family: dict[str, list[Selection]] = defaultdict(list)
    for s in rows:
        by_family[s.family].append(s)
    out: dict[str, list[tuple[Selection, float]]] = {f: [] for f in FAMILIES}
    skipped = 0
    for family, ss in by_family.items():
        for day in sorted({s.day for s in ss if s.day > after}):
            past = [s for s in ss if s.day < day]
            coef = platt([s.p for s in past], [s.over for s in past])
            today = [s for s in ss if s.day == day]
            if coef is None:
                skipped += len(today)
                continue
            out[family].extend((s, apply(coef, s.p)) for s in today)
    return out, skipped


def loss(p: float, over: int) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return float(-np.log(p if over else 1.0 - p))


def series_of(scored: Mapping[str, Sequence[tuple[Selection, float]]]) -> dict[str, tuple[list[float], list[date]]]:
    """For each family, the loss of the calibrated model minus the loss of the market of the same line, per selection, with its day."""
    return {f: ([loss(c, s.over) - loss(s.q, s.over) for s, c in items], [s.day for s, _ in items]) for f, items in scored.items()}


def after_signature(since: date) -> date:
    """The last day that does NOT count: the day of the signature (what kicks off the day after is scored)."""
    return since


def count(conn: psycopg.Connection[Any], since: date) -> int:
    """The sample of the experiment: the scorable selections of its fullest family after the signature."""
    far = datetime(2100, 1, 1, tzinfo=UTC)
    scored, _ = calibrated(load(conn, start=TRAINING_FROM, until=far), after=after_signature(since))
    return max((len(v) for v in scored.values()), default=0)


def judge(rows: Sequence[Selection], *, after: date, required: int, thresholds: Mapping[str, Any], seed: int) -> tuple[Judgement, dict[str, Any]]:
    scored, skipped = calibrated(rows, after=after)
    series = series_of(scored)
    judgement, figures = judge_segments(series, names=tuple(FAMILIES), required=required, thresholds=thresholds, seed=seed,
                                        abandon_reason="solo iguala al mercado leyéndolo: el intervalo de cada familia queda por encima de +0,005")
    population = {"families": figures, "not_scored_without_calibrator": skipped, "training_selections": len(rows), "comparator": "close_p_fair of the same line",
                  "calibration": "daily logistic on the log odds, fitted on earlier settled selections only", "holm_over": sorted(s for s, v in series.items() if len(v[0]) >= required)}
    return judgement, population


def run(conn: psycopg.Connection[Any], at: datetime) -> tuple[Judgement, dict[str, Any]]:
    protocol = exp_protocol.EXPERIMENTS[KEY]
    rows = load(conn, start=TRAINING_FROM, until=at)
    return judge(rows, after=exp_conditions.SIGNED_ON, required=int(exp_protocol.THRESHOLDS[KEY]["n_required"]), thresholds=exp_protocol.THRESHOLDS[KEY],
                 seed=protocol.seed)


def register() -> exp_conditions.Spec:
    """Say how the experiment counts and runs (``scripts.exp_run`` calls it for each module of its ``PLUGINS``)."""
    return exp_conditions.register(KEY, count=count, run=run)


__all__ = ["FAMILIES", "KEY", "Selection", "apply", "calibrated", "count", "judge", "load", "platt", "register", "run"]

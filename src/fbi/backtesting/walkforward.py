"""The walk-forward loop.

Time is cut into blocks of ``refit_days``. At the start of each block - one
cut-off before its first kick-off - every model is refitted on results known
at that moment (kick-off + 3 h before the cut-off, the same availability model
as the feature engine) and predicts every fixture in the block. Nothing a
model sees can post-date its block's cut-off, and that is checked on every
block, not assumed: a violation raises ``LeakageError``.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from fbi.backtesting.data import BacktestData
from fbi.features.data import MatchRecord
from fbi.features.engine import RESULT_AVAILABLE_AFTER, LeakageError
from fbi.models.elo_ologit import OLogitObs, fit_ologit
from fbi.models.families import MNLOGIT_FEATURES, mnlogit_row
from fbi.models.goals import GoalObs, InvalidCorrectionError, fit_goal_model
from fbi.models.logistic import fit_logistic
from fbi.models.metrics import log_loss
from fbi.models.scoring import MARKET_ROWS

MIN_GOAL_TRAIN = 100
MIN_OLOGIT_TRAIN = 200
MIN_MNLOGIT_TRAIN = 400
MNLOGIT_L2 = 1.0
MIN_BASE_RATE_TRAIN = 50
MIN_ELO_HISTORY = 10
"""An Elo rating built from fewer matches than this is still mostly the starting
value (1500 for every newcomer): the Elo model declines the fixture."""


def elo_history_short(features: dict[str, float | None]) -> bool:
    return min(features.get("home_history_n") or 0.0, features.get("away_history_n") or 0.0) < MIN_ELO_HISTORY


def outcome_index(m: MatchRecord) -> int:
    """Index into (home, draw, away): 0 home, 1 draw, 2 away - on the REGULATION
    score, which is what the market being compared settles on."""
    h, a = m.settle_home, m.settle_away
    assert h is not None and a is not None
    return 0 if h > a else 1 if h == a else 2


@dataclass(frozen=True, slots=True)
class GoalSpec:
    kind: str  # "poisson" | "dixon_coles"
    xi: float
    penalty: float

    @property
    def tag(self) -> str:
        return f"xi={self.xi:g},penalty={self.penalty:g}"


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    competition_ids: tuple[int, ...]
    test_season: int = 2024
    validation_season: int = 2023
    refit_days: int = 1
    validation_refit_days: int = 7
    history_days: int = 730
    cutoff_offset: timedelta = timedelta(minutes=60)
    xi_grid: tuple[float, ...] = (0.0, 0.001, 0.002, 0.004)
    penalty_grid: tuple[float, ...] = (1.0, 3.0, 10.0)
    interval_draws: int = 200


@dataclass(frozen=True, slots=True)
class PredRow:
    market_key: str
    selection: str
    line: float
    p: float
    lo: float | None
    hi: float | None


@dataclass(frozen=True, slots=True)
class Prediction:
    fixture_id: int
    model: str
    data_cutoff: datetime
    p: tuple[float, float, float]
    rows: tuple[PredRow, ...]
    input_hash: str
    """What the prediction was computed from: the training-set hash (goal models)
    or the fixture's feature-set input hash (Elo ordered logit)."""
    n_train: int


@dataclass(frozen=True, slots=True)
class Block:
    cutoff: datetime
    train_ids: tuple[int, ...]
    newest_train_kickoff: datetime | None
    target_ids: tuple[int, ...]
    first_target_kickoff: datetime


@dataclass
class ModelRun:
    model: str
    spec: str
    predictions: dict[int, Prediction] = field(default_factory=dict)
    uncovered: list[tuple[int, str]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    fits: int = 0
    failed_fits: int = 0
    no_interval: int = 0
    train_from: datetime | None = None
    train_to: datetime | None = None
    train_ids: set[int] = field(default_factory=set)

    def note_training(self, train: Sequence[MatchRecord]) -> None:
        for m in train:
            self.train_ids.add(m.fixture_id)
            if self.train_from is None or m.kickoff_at < self.train_from:
                self.train_from = m.kickoff_at
            if self.train_to is None or m.kickoff_at > self.train_to:
                self.train_to = m.kickoff_at


def blocks(fixtures: Sequence[MatchRecord], refit_days: int, offset: timedelta) -> list[tuple[datetime, list[MatchRecord]]]:
    ordered = sorted(fixtures, key=lambda m: (m.kickoff_at, m.fixture_id))
    out: list[tuple[datetime, list[MatchRecord]]] = []
    i = 0
    while i < len(ordered):
        start = ordered[i].kickoff_at
        end = start + timedelta(days=refit_days)
        group = []
        while i < len(ordered) and ordered[i].kickoff_at < end:
            group.append(ordered[i])
            i += 1
        out.append((start - offset, group))
    return out


def known_before(m: MatchRecord, cutoff: datetime) -> bool:
    return m.has_result and m.kickoff_at + RESULT_AVAILABLE_AFTER < cutoff


def train_hash(rows: Sequence[MatchRecord]) -> str:
    d = hashlib.sha256()
    for m in sorted(rows, key=lambda r: r.fixture_id):
        d.update(f"{m.fixture_id}:{m.settle_home}-{m.settle_away};".encode())
    return d.hexdigest()


def _check_block(cutoff: datetime, train: Sequence[MatchRecord], group: Sequence[MatchRecord]) -> Block:
    """The protocol, enforced: every training result was public before the
    cut-off, and the cut-off precedes every kick-off it predicts."""
    newest = max((m.kickoff_at for m in train), default=None)
    if newest is not None and newest + RESULT_AVAILABLE_AFTER >= cutoff:
        raise LeakageError(f"training result from {newest.isoformat()} not public before cut-off {cutoff.isoformat()}")
    first = min(m.kickoff_at for m in group)
    if cutoff >= first:
        raise LeakageError(f"cut-off {cutoff.isoformat()} is not before kick-off {first.isoformat()}")
    return Block(cutoff, tuple(sorted(m.fixture_id for m in train)), newest,
                 tuple(sorted(m.fixture_id for m in group)), first)


def run_goal_model(
    data: BacktestData,
    targets: Sequence[MatchRecord],
    *,
    spec: GoalSpec,
    cfg: WalkForwardConfig,
    refit_days: int,
    intervals: bool,
) -> ModelRun:
    by_comp: dict[int, list[MatchRecord]] = defaultdict(list)
    for m in data.matches:
        by_comp[m.competition_id].append(m)
    run = ModelRun(spec.kind, spec.tag)
    comp_targets: dict[int, list[MatchRecord]] = defaultdict(list)
    for t in targets:
        comp_targets[t.competition_id].append(t)
    for comp, ts in sorted(comp_targets.items()):
        for cutoff, group in blocks(ts, refit_days, cfg.cutoff_offset):
            horizon = cutoff - timedelta(days=cfg.history_days)
            train = [m for m in by_comp[comp] if known_before(m, cutoff) and m.kickoff_at >= horizon]
            run.blocks.append(_check_block(cutoff, train, group))
            if len(train) < MIN_GOAL_TRAIN:
                run.uncovered.extend(
                    (m.fixture_id, f"fewer than {MIN_GOAL_TRAIN} training matches before the cut-off") for m in group)
                continue
            obs = [GoalObs(m.home_team_id, m.away_team_id, m.settle_home or 0, m.settle_away or 0,
                           weight=math.exp(-spec.xi * (cutoff - m.kickoff_at).total_seconds() / 86400),
                           neutral=m.is_neutral) for m in train]
            run.fits += 1
            try:
                model = fit_goal_model(obs, kind=spec.kind, xi=spec.xi, penalty=spec.penalty,
                                       with_covariance=intervals)
            except (ValueError, np.linalg.LinAlgError):
                run.failed_fits += 1
                run.uncovered.extend((m.fixture_id, "model fit failed") for m in group)
                continue
            if not model.converged:
                run.failed_fits += 1
                run.uncovered.extend((m.fixture_id, "model fit did not converge") for m in group)
                continue
            run.note_training(train)
            th = train_hash(train)
            for m in group:
                if not (model.knows(m.home_team_id) and model.knows(m.away_team_id)):
                    run.uncovered.append((m.fixture_id, "a team has no match in this competition's training window"))
                    continue
                try:
                    probs = model.predict(m.home_team_id, m.away_team_id, neutral=m.is_neutral)
                except InvalidCorrectionError:
                    run.uncovered.append((m.fixture_id, "Dixon-Coles correction invalid at these expected goals"))
                    continue
                point = probs.as_rows()
                bounds = (model.interval_rows(m.home_team_id, m.away_team_id, neutral=m.is_neutral,
                                              draws=cfg.interval_draws) if intervals else None)
                if intervals and bounds is None:
                    run.no_interval += 1
                rows = tuple(
                    PredRow(mk, sel, line, float(point[k]),
                            None if bounds is None else float(bounds[0][k]),
                            None if bounds is None else float(bounds[1][k]))
                    for k, (mk, sel, line) in enumerate(MARKET_ROWS)
                )
                run.predictions[m.fixture_id] = Prediction(
                    m.fixture_id, spec.kind, cutoff, probs.as_1x2(), rows, th, len(train))
    return run


def run_elo_ologit(
    data: BacktestData, targets: Sequence[MatchRecord], *, cfg: WalkForwardConfig, refit_days: int
) -> ModelRun:
    """Parameters refitted per block at the block's cut-off; the Elo difference
    fed in is the fixture's own feature (cut-off kick-off - 60 min), which is
    public before kick-off and later than the block cut-off. The prediction's
    data cut-off is therefore the feature's, and is recorded as such."""
    domestic = set(cfg.competition_ids)
    labelled = [m for m in data.matches if m.has_result and m.competition_id in domestic
                and data.features.get(m.fixture_id, {}).get("elo_diff") is not None]
    run = ModelRun("elo_ologit", "elo=v2.0,K=20,home=65")
    for cutoff, group in blocks(targets, refit_days, cfg.cutoff_offset):
        train = [m for m in labelled if known_before(m, cutoff)]
        run.blocks.append(_check_block(cutoff, train, group))
        if len(train) < MIN_OLOGIT_TRAIN:
            run.uncovered.extend(
                (m.fixture_id, f"fewer than {MIN_OLOGIT_TRAIN} training matches with Elo features") for m in group)
            continue
        obs = []
        for m in train:
            x = data.features[m.fixture_id]["elo_diff"]
            assert x is not None
            obs.append(OLogitObs(float(x), m.is_neutral, 2 - outcome_index(m)))
        run.fits += 1
        model = fit_ologit(obs)
        if not model.converged:
            run.failed_fits += 1
            run.uncovered.extend((m.fixture_id, "model fit did not converge") for m in group)
            continue
        run.note_training(train)
        for m in group:
            fv = data.features.get(m.fixture_id, {})
            x = fv.get("elo_diff")
            feature_cutoff = data.feature_cutoff.get(m.fixture_id)
            if x is None or feature_cutoff is None:
                run.uncovered.append((m.fixture_id, "no feature set for this fixture"))
                continue
            if feature_cutoff >= m.kickoff_at:
                raise LeakageError(f"feature cut-off after kick-off for fixture {m.fixture_id}")
            if elo_history_short(fv):
                run.uncovered.append((m.fixture_id, f"a team has fewer than {MIN_ELO_HISTORY} rated matches"))
                continue
            try:
                p = model.predict(float(x), neutral=m.is_neutral)
            except ValueError as exc:
                run.uncovered.append((m.fixture_id, str(exc)))
                continue
            bounds = model.interval(float(x), neutral=m.is_neutral, draws=cfg.interval_draws)
            if bounds is None:
                run.no_interval += 1
            rows = tuple(
                PredRow("1X2", sel, 0.0, float(p[k]),
                        None if bounds is None else float(bounds[0][k]),
                        None if bounds is None else float(bounds[1][k]))
                for k, sel in enumerate(("Home", "Draw", "Away"))
            )
            run.predictions[m.fixture_id] = Prediction(
                m.fixture_id, "elo_ologit", max(cutoff, feature_cutoff), p, rows,
                data.feature_hash.get(m.fixture_id, ""), len(train))
    return run


def run_base_rates(
    data: BacktestData, targets: Sequence[MatchRecord], *, cfg: WalkForwardConfig, refit_days: int
) -> ModelRun:
    """Per competition, the home/draw/away frequencies of the results public before
    each block's cut-off (training window ``history_days``), Laplace-smoothed. The
    no-skill reference: a model that cannot beat it has learned nothing."""
    by_comp: dict[int, list[MatchRecord]] = defaultdict(list)
    for m in data.matches:
        if m.has_result:
            by_comp[m.competition_id].append(m)
    run = ModelRun("base_rates", f"window={cfg.history_days}d,laplace=1")
    comp_targets: dict[int, list[MatchRecord]] = defaultdict(list)
    for t in targets:
        comp_targets[t.competition_id].append(t)
    for comp, ts in sorted(comp_targets.items()):
        for cutoff, group in blocks(ts, refit_days, cfg.cutoff_offset):
            horizon = cutoff - timedelta(days=cfg.history_days)
            train = [m for m in by_comp[comp] if known_before(m, cutoff) and m.kickoff_at >= horizon]
            run.blocks.append(_check_block(cutoff, train, group))
            if len(train) < MIN_BASE_RATE_TRAIN:
                run.uncovered.extend((m.fixture_id, f"fewer than {MIN_BASE_RATE_TRAIN} results in the window")
                                     for m in group)
                continue
            run.fits += 1
            run.note_training(train)
            counts = np.bincount([outcome_index(m) for m in train], minlength=3) + 1.0
            p = counts / counts.sum()
            th = train_hash(train)
            for m in group:
                rows = tuple(PredRow("1X2", sel, 0.0, float(p[k]), None, None)
                             for k, sel in enumerate(("Home", "Draw", "Away")))
                run.no_interval += 1
                run.predictions[m.fixture_id] = Prediction(m.fixture_id, "base_rates", cutoff,
                                                           (float(p[0]), float(p[1]), float(p[2])), rows, th, len(train))
    return run


def run_mnlogit(
    data: BacktestData, targets: Sequence[MatchRecord], *, cfg: WalkForwardConfig, refit_days: int,
    l2: float = MNLOGIT_L2,
) -> ModelRun:
    """Refitted per block on domestic results with features known before the cut-off;
    each fixture is predicted from its own feature set (cut-off kick-off - 60 min),
    exactly as the ordered logit. The L2 strength is fixed a priori, not tuned."""
    domestic = set(cfg.competition_ids)
    labelled = [m for m in data.matches if m.has_result and m.competition_id in domestic
                and data.features.get(m.fixture_id, {}).get("elo_diff") is not None
                and data.features.get(m.fixture_id, {}).get("pi_expected_gd") is not None]
    run = ModelRun("mnlogit", f"features={','.join(MNLOGIT_FEATURES)},l2={l2:g}")
    for cutoff, group in blocks(targets, refit_days, cfg.cutoff_offset):
        train = [m for m in labelled if known_before(m, cutoff)]
        run.blocks.append(_check_block(cutoff, train, group))
        if len(train) < MIN_MNLOGIT_TRAIN:
            run.uncovered.extend(
                (m.fixture_id, f"fewer than {MIN_MNLOGIT_TRAIN} training matches with features") for m in group)
            continue
        run.fits += 1
        try:
            model = fit_logistic([mnlogit_row(data.features[m.fixture_id]) for m in train],
                                 [outcome_index(m) for m in train], features=MNLOGIT_FEATURES, l2=l2)
        except ValueError:
            run.failed_fits += 1
            run.uncovered.extend((m.fixture_id, "model fit failed") for m in group)
            continue
        if not model.converged:
            run.failed_fits += 1
            run.uncovered.extend((m.fixture_id, "model fit did not converge") for m in group)
            continue
        run.note_training(train)
        for m in group:
            fv = data.features.get(m.fixture_id, {})
            feature_cutoff = data.feature_cutoff.get(m.fixture_id)
            if fv.get("elo_diff") is None or fv.get("pi_expected_gd") is None or feature_cutoff is None:
                run.uncovered.append((m.fixture_id, "no feature set for this fixture"))
                continue
            if feature_cutoff >= m.kickoff_at:
                raise LeakageError(f"feature cut-off after kick-off for fixture {m.fixture_id}")
            if elo_history_short(fv):
                run.uncovered.append((m.fixture_id, f"a team has fewer than {MIN_ELO_HISTORY} rated matches"))
                continue
            p = model.predict(mnlogit_row(fv))
            rows = tuple(PredRow("1X2", sel, 0.0, float(p[k]), None, None)
                         for k, sel in enumerate(("Home", "Draw", "Away")))
            run.no_interval += 1
            run.predictions[m.fixture_id] = Prediction(m.fixture_id, "mnlogit", max(cutoff, feature_cutoff), p, rows,
                                                       data.feature_hash.get(m.fixture_id, ""), len(train))
    return run


MAX_GRID_EXPANSIONS = 3
MIN_PENALTY = 0.03


def select_goal_spec(
    data: BacktestData, cfg: WalkForwardConfig, kind: str, progress: Callable[[str], None] | None = None
) -> tuple[GoalSpec, dict[str, float], dict[str, list[float]]]:
    """Choose time decay and shrinkage on the VALIDATION season only.

    Returns (chosen spec, validation log loss per candidate, final grid).
    Candidates are scored on the fixtures EVERY candidate predicted, so a
    candidate cannot win by abstaining on the hard ones. When the best
    candidate sits on the edge of the grid the grid is extended in that
    direction (xi doubled; penalty divided or multiplied by 3) and the search
    repeated, at most MAX_GRID_EXPANSIONS times. The rule is fixed in advance
    and reads validation scores only: an optimum on the boundary of a grid is
    not an optimum.
    """
    val = [m for m in data.matches if m.competition_id in cfg.competition_ids
           and m.season == cfg.validation_season and m.has_result]
    by_id = {m.fixture_id: m for m in val}
    xis, pens = sorted(cfg.xi_grid), sorted(cfg.penalty_grid)
    runs: dict[GoalSpec, ModelRun] = {}
    best: tuple[float, GoalSpec] | None = None
    scores: dict[str, float] = {}
    for _ in range(MAX_GRID_EXPANSIONS + 1):
        for xi in xis:
            for penalty in pens:
                spec = GoalSpec(kind, xi, penalty)
                if spec not in runs:
                    runs[spec] = run_goal_model(data, val, spec=spec, cfg=cfg,
                                                refit_days=cfg.validation_refit_days, intervals=False)
        common = set.intersection(*(set(r.predictions) for r in runs.values()))
        if not common:
            raise ValueError("no validation fixture was predicted by every candidate")
        ids = sorted(common)
        y = np.array([outcome_index(by_id[i]) for i in ids])
        scores = {}
        best = None
        for spec, run in sorted(runs.items(), key=lambda kv: (kv[0].xi, kv[0].penalty)):
            score = log_loss(np.array([run.predictions[i].p for i in ids]), y)
            scores[spec.tag] = score
            if best is None or score < best[0]:
                best = (score, spec)
        assert best is not None
        chosen = best[1]
        expanded = False
        if chosen.xi == xis[-1] and chosen.xi > 0:
            xis.append(xis[-1] * 2)
            expanded = True
        if chosen.penalty == pens[0] and pens[0] / 3 >= MIN_PENALTY:
            pens.insert(0, round(pens[0] / 3, 6))
            expanded = True
        elif chosen.penalty == pens[-1] and len(pens) > 1:
            pens.append(pens[-1] * 3)
            expanded = True
        if not expanded:
            break
        if progress:
            progress(f"  {kind}: best {chosen.tag} is on the edge of the grid - extending it")
    assert best is not None
    if progress:
        for tag, score in scores.items():
            progress(f"  {kind} {tag}: validation log loss {score:.5f} on {len(ids)} fixtures")
    return best[1], scores, {"xi": xis, "penalty": pens}

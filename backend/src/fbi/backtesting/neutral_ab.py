"""The before/after backtest of the neutral-venue rule (plan F0, defect 1; protocol ``neutral-ab-v1``).

THE QUESTION
------------
``fbi.catalog.neutral`` marks some matches as played at a neutral venue (a final, a World Cup match in a third country).
Reading that flag removes the home advantage the Elo and the goal models give the nominal home side. Is a model that
reads it any worse where the flag is set, or anywhere else? "No model change without a test" - this is the test, run
with the models as they are (BEFORE: no match is neutral - nothing else ever wrote the flag) and with the rule's
verdicts (AFTER), walk-forward, over the same matches.

TWO LAYERS, AND WHY
-------------------
* PRIMARY - a pooled Elo + ordered logit over every competition, with the home advantage taken out of a labelled match
  the way the Elo itself takes it out. The ratings are recomputed inside each arm (a neutral result moves them
  differently, so the effect on the ratings is part of what is measured); a labelled match is priced from its rating
  difference minus the Elo home advantage, through the same mapping every other match goes through. That mapping (slope and
  thresholds) is fitted on the matches the rule does NOT label, identically in both arms, so it cannot learn that the
  labelled matches behave differently: if they have a home advantage after all, the arm that took it out is penalised.
  (A model that fitted a home term of its own for them would learn the truth from their own results, heal any wrong label
  and so could never show harm. The production ordered logit cannot be used either: it is trained on domestic leagues,
  where no match is neutral, so it refuses to price a neutral fixture - ``fbi.models.elo_ologit``.)
* GUARD - the production goal models (Poisson, Dixon-Coles) per competition, fitted as the forecast fits them, with the
  neutral flag in their training and in their prediction. They are what the switch changes in production; they cover few
  labelled matches (a competition needs 100 results in two years), so this layer can show harm but not prove safety.
* CONTROL - every other match, priced by the same mapping in both arms. The rule changes only labelled matches; the rest
  can differ only through the ratings, and that must not be for the worse.

THE VERDICT IS ARITHMETIC, AND FIXED BEFORE THE RUN
---------------------------------------------------
Everything in ``Protocol`` - the window, the refit cadence, the margin, the minimum sizes - was written down before any
outcome of these models was looked at, and a change to any of it is a new protocol version. The score is the log loss of
the 1X2 probabilities (a proper scoring rule; Brier, RPS and the calibration error are reported beside it). The unit is
the match; the uncertainty is a bootstrap that resamples whole match DAYS (matches of one day share a tournament, a
rating state and a venue, so they are not independent).

  justified      no layer shows harm, and the 95% interval of (after - before) on the neutral matches lies below
                 ``margin`` ("not worse": it may be better), and so does the control's below ``control_margin``;
  not_justified  some layer shows harm: an interval wholly above zero (above ``control_margin`` for the control);
  inconclusive   neither: too few neutral matches priced by both arms, or an interval too wide to say.

Only ``justified`` can be promoted. The verdict is stored with the whole result (``analytics.neutral_rule_runs``), the
fingerprint of the labels it is about and the code that produced it.

WHAT IT DOES NOT SHOW
---------------------
The labels are the rule's, and the rule saw the ground the payload names today (a venue corrected after the match is the
corrected one): that is information a forecast made before the match mostly had, but not all of it. The matches the rule
cannot call (no evidence) stay "home" in both arms. And a covered neutral match is a match the models can price: the
labelled matches of competitions with no history are in neither arm.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import psycopg
from numpy.typing import NDArray

from fbi.backtesting.data import BacktestData
from fbi.backtesting.walkforward import (
    MIN_ELO_HISTORY,
    MIN_OLOGIT_TRAIN,
    GoalSpec,
    WalkForwardConfig,
    outcome_index,
    run_goal_model,
)
from fbi.catalog.neutral import RULE_VERSION
from fbi.catalog.neutral_store import label_state
from fbi.features.data import MatchRecord, load_matches
from fbi.features.elo import EloBook, EloParams
from fbi.features.engine import RESULT_AVAILABLE_AFTER, TEAM_MEMORY
from fbi.models.elo_ologit import OLogitModel, OLogitObs, fit_ologit
from fbi.models.metrics import (
    block_bootstrap_ci,
    brier,
    calibration,
    log_loss,
    per_match_log_loss,
    rps,
)

PROTOCOL = "neutral-ab-v1"
MAX_GOAL_TEAMS = 250
"""As the real-time forecast (``fbi.predictions.forecast.MAX_GOAL_TEAMS``): a competition with more sides in its training
window is not fitted."""

Progress = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Protocol:
    """Everything the verdict depends on, fixed before the run. A change is a new protocol version."""

    test_from: datetime = datetime(2018, 7, 1, tzinfo=UTC)
    """First kick-off priced: three years of history precede it, enough for the ratings to have left their start."""
    pooled_refit_days: int = 28
    goal_refit_days: int = 7
    goal_history_days: int = 730
    goal_xi: float = 0.002
    goal_penalty: float = 3.0
    goal_kinds: tuple[str, ...] = ("poisson", "dixon_coles")
    cutoff_offset: timedelta = timedelta(minutes=60)
    min_history: int = MIN_ELO_HISTORY
    margin: float = 0.005
    """"Not worse": the upper end of the 95% interval of (after - before) in log loss per neutral match is below this.
    It is about a third of what removing a home advantage that is not there should buy (about 0.015), and a hundredth of
    the log loss itself."""
    control_margin: float = 0.0005
    """The same for the matches the rule does not touch: the sample is large, so the margin is tight."""
    min_primary: int = 300
    min_guard: int = 30
    min_basis: int = 100
    draws: int = 2000
    seed: int = 11
    level: float = 0.95

    def as_dict(self) -> dict[str, Any]:
        return {"protocol": PROTOCOL, "test_from": self.test_from.isoformat(),
                "pooled_refit_days": self.pooled_refit_days, "goal_refit_days": self.goal_refit_days,
                "goal_history_days": self.goal_history_days, "goal_xi": self.goal_xi,
                "goal_penalty": self.goal_penalty, "goal_kinds": list(self.goal_kinds),
                "cutoff_offset_min": int(self.cutoff_offset.total_seconds() // 60), "min_history": self.min_history,
                "margin": self.margin, "control_margin": self.control_margin, "min_primary": self.min_primary,
                "min_guard": self.min_guard, "min_basis": self.min_basis, "draws": self.draws, "seed": self.seed,
                "level": self.level, "elo": EloParams().as_dict(), "max_goal_teams": MAX_GOAL_TEAMS}


# ------------------------------------------------------------------------------------------------ the Elo of each arm


def elo_inputs(matches: Sequence[MatchRecord], params: EloParams, offset: timedelta) -> dict[int, tuple[float, int]]:
    """For every played match: (the Elo difference home - away, the smaller number of rated matches of its two sides) as
    of its cut-off (kick-off - ``offset``), with the ratings built from the results known by then and the matches'
    ``is_neutral`` flags as given. The feature engine's own pass (``fbi.features.engine.walk_forward``) without the
    feature vectors, so that the ratings of the whole history can be recomputed for each arm cheaply; a test holds the
    two equal."""
    events: list[tuple[datetime, int, datetime, int, MatchRecord]] = []
    for m in matches:
        if m.has_result:
            events.append((m.kickoff_at + RESULT_AVAILABLE_AFTER, 1, m.kickoff_at, m.fixture_id, m))
            events.append((m.kickoff_at - offset, 0, m.kickoff_at, m.fixture_id, m))
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    book = EloBook(params)
    seen: dict[int, int] = defaultdict(int)
    out: dict[int, tuple[float, int]] = {}
    for _at, kind, _kickoff, fixture_id, m in events:
        if kind == 1:
            assert m.goals_home is not None and m.goals_away is not None
            book.update(m.home_team_id, m.away_team_id, m.goals_home, m.goals_away, neutral=m.is_neutral)
            seen[m.home_team_id] += 1
            seen[m.away_team_id] += 1
        else:
            known = min(min(seen[m.home_team_id], TEAM_MEMORY), min(seen[m.away_team_id], TEAM_MEMORY))
            out[fixture_id] = (book.rating(m.home_team_id) - book.rating(m.away_team_id), known)
    return out


# ------------------------------------------------------------------------------------------------------- the scores


@dataclass(frozen=True, slots=True)
class Paired:
    """The two arms over the same matches. ``diff`` is after - before in mean log loss: negative means the rule helps."""

    n: int
    blocks: int
    loss_a: float
    loss_b: float
    diff: float
    lo: float
    hi: float
    brier_a: float
    brier_b: float
    rps_a: float
    rps_b: float
    ece_a: float
    ece_b: float
    home_rate: float
    """The share of these matches the nominal home side won."""
    home_bias_a: float
    home_bias_b: float
    """Mean predicted home-win probability minus the share of home wins: positive means the arm over-rates the home side.
    Where the venue is really neutral, an arm that gives a home advantage shows it here."""

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in
                ((f, getattr(self, f)) for f in self.__dataclass_fields__)}


def compare(p_a: NDArray[np.float64], p_b: NDArray[np.float64], y: NDArray[np.int64], days: Sequence[object],
            protocol: Protocol) -> Paired | None:
    """Score both arms on the same matches (rows of ``p_*`` in the order home, draw, away; ``y`` 0 home, 1 draw, 2 away)
    and bound their difference. None for no matches."""
    if len(y) == 0:
        return None
    d = per_match_log_loss(p_b, y) - per_match_log_loss(p_a, y)
    mean, lo, hi, blocks = block_bootstrap_ci(d, list(days), draws=protocol.draws, level=protocol.level,
                                              seed=protocol.seed)
    home = float((y == 0).mean())
    return Paired(
        n=len(y), blocks=blocks, loss_a=log_loss(p_a, y), loss_b=log_loss(p_b, y), diff=mean, lo=lo, hi=hi,
        brier_a=brier(p_a, y), brier_b=brier(p_b, y), rps_a=rps(p_a, y), rps_b=rps(p_b, y),
        ece_a=calibration(p_a, y)[0], ece_b=calibration(p_b, y)[0], home_rate=home,
        home_bias_a=float(p_a[:, 0].mean()) - home, home_bias_b=float(p_b[:, 0].mean()) - home)


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: str
    reasons: tuple[str, ...]
    notes: tuple[str, ...] = ()
    """What was too small to count (a layer under its minimum size): said, not hidden."""


def _interval(p: Paired) -> str:
    return f"{p.diff:+.4f} ({p.lo:+.4f}..{p.hi:+.4f}) on {p.n} matches"


def decide(protocol: Protocol, primary: Paired | None, guards: Mapping[str, Paired], control: Paired | None,
           bases: Mapping[str, Paired]) -> Decision:
    """The verdict, by arithmetic over the scores (see the module docstring). ``reasons`` say why in words.

    Harm anywhere settles it, whatever else is missing: a layer with enough matches whose whole interval lies above zero
    (above ``control_margin`` for the control). Without harm, too few labelled matches priced by both arms, or an interval
    that reaches above a margin, is "inconclusive"; otherwise the rule is "justified"."""
    enough = primary is not None and primary.n >= protocol.min_primary
    notes: list[str] = []
    harm: list[str] = []
    if primary is not None and enough and primary.lo > 0:
        harm.append(f"the neutral matches are priced worse with the rule: {_interval(primary)}")
    for kind, g in sorted(guards.items()):
        if g.n < protocol.min_guard:
            notes.append(f"the {kind} goal model priced only {g.n} labelled matches (fewer than {protocol.min_guard}): "
                         f"too few to count as evidence either way")
        elif g.lo > 0:
            harm.append(f"the {kind} goal model prices them worse with the rule: {_interval(g)}")
    if control is not None and control.lo > protocol.control_margin:
        harm.append(f"the matches the rule does not touch are priced worse: {_interval(control)}")
    for basis, b in sorted(bases.items()):
        if b.n < protocol.min_basis:
            notes.append(f"'{basis}': {b.n} labelled matches (fewer than {protocol.min_basis}) - not judged on its own")
        elif b.lo > 0:
            harm.append(f"the matches decided by '{basis}' are priced worse with the rule: {_interval(b)}")
    if harm:
        return Decision("not_justified", tuple(harm), tuple(notes))
    if primary is None or not enough:
        n = 0 if primary is None else primary.n
        return Decision("inconclusive", (f"{n} labelled matches could be priced by both arms; at least "
                                         f"{protocol.min_primary} are needed to say anything",), tuple(notes))
    said: list[str] = []
    if primary.hi > protocol.margin:
        said.append(f"the neutral matches: {_interval(primary)} reaches above the margin {protocol.margin:+.4f}")
    if control is not None and control.hi > protocol.control_margin:
        said.append(f"the matches the rule does not touch: {_interval(control)} reaches above "
                    f"{protocol.control_margin:+.4f}")
    if said:
        return Decision("inconclusive", tuple(said), tuple(notes))
    better = "better" if primary.hi < 0 else "not worse"
    why = [f"the neutral matches are {better} with the rule: {_interval(primary)}"]
    if control is not None:
        why.append(f"the matches the rule does not touch: {_interval(control)}")
    return Decision("justified", tuple(why), tuple(notes))


# --------------------------------------------------------------------------------------------------- the pooled layer


@dataclass(slots=True)
class Pooled:
    """Both arms' probabilities for every match priced by both, in kick-off order."""

    fixture_ids: list[int] = field(default_factory=list)
    days: list[date] = field(default_factory=list)
    primary: list[bool] = field(default_factory=list)
    y: list[int] = field(default_factory=list)
    p_a: list[tuple[float, float, float]] = field(default_factory=list)
    p_b: list[tuple[float, float, float]] = field(default_factory=list)
    fits: int = 0
    failed_fits: int = 0
    declined: Counter[str] = field(default_factory=Counter)

    def arrays(self, *, primary: bool | None = None, subset: Collection[int] | None = None) -> tuple[
            NDArray[np.float64], NDArray[np.float64], NDArray[np.int64], list[date]]:
        keep = [i for i in range(len(self.y))
                if (primary is None or self.primary[i] == primary)
                and (subset is None or self.fixture_ids[i] in subset)]
        return (np.array([self.p_a[i] for i in keep], dtype=np.float64).reshape(-1, 3),
                np.array([self.p_b[i] for i in keep], dtype=np.float64).reshape(-1, 3),
                np.array([self.y[i] for i in keep], dtype=np.int64), [self.days[i] for i in keep])


def pooled_scores(matches_a: Sequence[MatchRecord], matches_b: Sequence[MatchRecord], changed: Collection[int],
                  protocol: Protocol, *, end: datetime | None = None, progress: Progress | None = None) -> Pooled:
    """Price every match from ``protocol.test_from`` on with a pooled Elo + ordered logit in both arms.

    ``matches_a`` and ``matches_b`` are the same fixtures in the same order, differing only in ``is_neutral``;
    ``changed`` are the fixtures whose flag differs. Per block of ``pooled_refit_days``, each arm fits the mapping from
    rating difference to 1X2 on every result known one cut-off before the block's first kick-off EXCEPT the matches either
    arm flags - the same rows for both arms, so that only their ratings differ - and prices each match of the block from
    its own rating difference as of its own cut-off, minus the Elo home advantage when the arm flags the match. A match is
    scored only if both arms priced it (both teams with enough rated matches)."""
    if [m.fixture_id for m in matches_a] != [m.fixture_id for m in matches_b]:
        raise ValueError("the two arms must hold the same fixtures in the same order")
    say = progress or (lambda _msg: None)
    params = EloParams()
    inputs_a = elo_inputs(matches_a, params, protocol.cutoff_offset)
    inputs_b = elo_inputs(matches_b, params, protocol.cutoff_offset)
    by_b = {m.fixture_id: m for m in matches_b}
    played = [m for m in matches_a if m.has_result and m.fixture_id in inputs_a and m.fixture_id in inputs_b]
    known_order = sorted(played, key=lambda m: (m.kickoff_at + RESULT_AVAILABLE_AFTER, m.fixture_id))
    avail = np.array([(m.kickoff_at + RESULT_AVAILABLE_AFTER).timestamp() for m in known_order])
    x_a = np.array([inputs_a[m.fixture_id][0] for m in known_order])
    x_b = np.array([inputs_b[m.fixture_id][0] for m in known_order])
    # how many matches a side has rated is a count of results, not of flags: the same in both arms
    rated = np.array([inputs_a[m.fixture_id][1] >= protocol.min_history for m in known_order])
    outcome = np.array([2 - outcome_index(m) for m in known_order])  # the model's order: 0 away, 1 draw, 2 home
    flagged = np.array([m.is_neutral or by_b[m.fixture_id].is_neutral for m in known_order], dtype=bool)
    fit_rows = rated & ~flagged

    last = end or max((m.kickoff_at for m in played), default=protocol.test_from)
    targets = sorted((m for m in played if protocol.test_from <= m.kickoff_at <= last),
                     key=lambda m: (m.kickoff_at, m.fixture_id))
    span = timedelta(days=protocol.pooled_refit_days)
    groups: dict[int, list[MatchRecord]] = defaultdict(list)
    for m in targets:
        groups[int((m.kickoff_at - protocol.test_from) / span)].append(m)
    out = Pooled()
    for n, k in enumerate(sorted(groups), 1):
        group = groups[k]
        cutoff = min(m.kickoff_at for m in group) - protocol.cutoff_offset
        upto = int(np.searchsorted(avail, cutoff.timestamp(), side="left"))
        rows = np.nonzero(fit_rows[:upto])[0]
        out.fits += 2
        arms: list[OLogitModel] = []
        if len(rows) >= MIN_OLOGIT_TRAIN:
            for x in (x_a, x_b):
                arms.append(fit_ologit([OLogitObs(float(x[j]), False, int(outcome[j])) for j in rows]))
        if len(arms) != 2 or not all(model.converged for model in arms):
            out.failed_fits += 1
            out.declined["a fit failed or had too little to fit"] += len(group)
            continue
        for m in group:
            mb = by_b[m.fixture_id]
            if inputs_a[m.fixture_id][1] < protocol.min_history:
                out.declined["a team has too few rated matches"] += 1
                continue
            rating_a = inputs_a[m.fixture_id][0] - (params.home_advantage if m.is_neutral else 0.0)
            rating_b = inputs_b[m.fixture_id][0] - (params.home_advantage if mb.is_neutral else 0.0)
            out.fixture_ids.append(m.fixture_id)
            out.days.append(m.kickoff_at.date())
            out.primary.append(m.fixture_id in changed)
            out.y.append(outcome_index(m))
            out.p_a.append(arms[0].predict(rating_a))
            out.p_b.append(arms[1].predict(rating_b))
        if n % 10 == 0 or n == len(groups):
            say(f"  pooled model: block {n}/{len(groups)}, {len(out.y)} matches priced")
    return out


# ----------------------------------------------------------------------------------------------------- the guard layer


@dataclass(slots=True)
class Guard:
    """One production goal model, both arms, on the neutral matches both covered."""

    kind: str
    fixture_ids: list[int] = field(default_factory=list)
    days: list[date] = field(default_factory=list)
    y: list[int] = field(default_factory=list)
    p_a: list[tuple[float, float, float]] = field(default_factory=list)
    p_b: list[tuple[float, float, float]] = field(default_factory=list)
    uncovered_a: Counter[str] = field(default_factory=Counter)
    uncovered_b: Counter[str] = field(default_factory=Counter)


def guard_scores(matches_a: Sequence[MatchRecord], matches_b: Sequence[MatchRecord], changed: Collection[int],
                 protocol: Protocol, *, end: datetime | None = None, progress: Progress | None = None) -> dict[str, Guard]:
    """The production goal models (``fbi.backtesting.walkforward.run_goal_model``, as the forecast fits them) on the
    labelled matches, in both arms. A neutral match is priced with no home advantage in the AFTER arm."""
    say = progress or (lambda _msg: None)
    last = end or max((m.kickoff_at for m in matches_a if m.has_result), default=protocol.test_from)
    cfg = WalkForwardConfig(competition_ids=(), history_days=protocol.goal_history_days,
                            cutoff_offset=protocol.cutoff_offset)
    out: dict[str, Guard] = {}
    for kind in protocol.goal_kinds:
        spec = GoalSpec(kind, protocol.goal_xi, protocol.goal_penalty)
        runs = []
        for arm, matches in (("before", matches_a), ("after", matches_b)):
            targets = [m for m in matches if m.fixture_id in changed and m.has_result
                       and protocol.test_from <= m.kickoff_at <= last]
            data = BacktestData(list(matches), {}, {}, {}, {}, {})
            say(f"  goal model {kind}, {arm}: {len(targets)} labelled matches")
            runs.append(run_goal_model(data, targets, spec=spec, cfg=cfg, refit_days=protocol.goal_refit_days,
                                       intervals=False, max_teams=MAX_GOAL_TEAMS))
        before, after = runs
        g = Guard(kind)
        g.uncovered_a.update(reason.split(" in ")[0] if "teams" in reason else reason for _, reason in before.uncovered)
        g.uncovered_b.update(reason.split(" in ")[0] if "teams" in reason else reason for _, reason in after.uncovered)
        by_id = {m.fixture_id: m for m in matches_a}
        for fid in sorted(set(before.predictions) & set(after.predictions)):
            m = by_id[fid]
            g.fixture_ids.append(fid)
            g.days.append(m.kickoff_at.date())
            g.y.append(outcome_index(m))
            g.p_a.append(before.predictions[fid].p)
            g.p_b.append(after.predictions[fid].p)
        out[kind] = g
    return out


# -------------------------------------------------------------------------------------------------------- the result


@dataclass(slots=True)
class AbResult:
    protocol: Protocol
    rule: str
    labels: dict[str, Any]
    window: dict[str, Any]
    counts: dict[str, Any]
    primary: Paired | None
    guards: dict[str, Paired]
    control: Paired | None
    bases: dict[str, Paired]
    decision: Decision
    dataset_hash: str
    seconds: float

    @property
    def headline(self) -> str:
        p = self.primary
        if p is None:
            return f"{self.decision.verdict}: no labelled match could be priced"
        return (f"{self.decision.verdict}: neutral matches {p.diff:+.4f} log loss per match "
                f"({p.lo:+.4f}..{p.hi:+.4f}, n={p.n}); {self.decision.reasons[0]}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL, "rule_version": self.rule, "headline": self.headline,
            "verdict": self.decision.verdict, "reasons": list(self.decision.reasons),
            "notes": list(self.decision.notes),
            "window": self.window, "counts": self.counts, "labels": self.labels,
            "primary": None if self.primary is None else self.primary.as_dict(),
            "guards": {k: v.as_dict() for k, v in sorted(self.guards.items())},
            "control": None if self.control is None else self.control.as_dict(),
            "bases": {k: v.as_dict() for k, v in sorted(self.bases.items())},
            "seconds": round(self.seconds, 1),
        }


def _dataset_hash(matches: Sequence[MatchRecord]) -> str:
    d = hashlib.sha256()
    for m in sorted(matches, key=lambda r: r.fixture_id):
        if m.has_result:
            d.update(f"{m.fixture_id}|{m.kickoff_at.isoformat()}|{m.settle_home}-{m.settle_away}|"
                     f"{int(m.is_neutral)};".encode())
    return d.hexdigest()


def _bases(conn: psycopg.Connection[Any], rule: str) -> dict[int, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT fixture_id, basis FROM core.fixture_venue_class WHERE rule_version = %s AND neutral",
                    (rule,))
        return {int(i): str(b) for i, b in cur.fetchall()}


def evaluate(matches_a: Sequence[MatchRecord], matches_b: Sequence[MatchRecord], bases: Mapping[int, str],
             protocol: Protocol, *, rule: str = RULE_VERSION, labels: Mapping[str, Any] | None = None,
             progress: Progress | None = None) -> AbResult:
    """The whole comparison over two arms already loaded (no database): see the module docstring."""
    began = time.monotonic()
    say = progress or (lambda _msg: None)
    flag_a = {m.fixture_id: m.is_neutral for m in matches_a}
    changed = {m.fixture_id for m in matches_b if m.is_neutral and not flag_a[m.fixture_id]}
    played = [m for m in matches_a if m.has_result]
    end = max((m.kickoff_at for m in played), default=protocol.test_from)
    in_window = [m for m in played if protocol.test_from <= m.kickoff_at <= end]
    labelled = [m for m in in_window if m.fixture_id in changed]

    say(f"pooled Elo + ordered logit, {len(labelled)} labelled matches in the window")
    pooled = pooled_scores(matches_a, matches_b, changed, protocol, end=end, progress=progress)
    a, b, y, days = pooled.arrays(primary=True)
    primary = compare(a, b, y, days, protocol)
    a, b, y, days = pooled.arrays(primary=False)
    control = compare(a, b, y, days, protocol)
    by_basis: dict[str, Paired] = {}
    for basis in sorted(set(bases.values())):
        ids = {f for f in changed if bases.get(f) == basis}
        a, b, y, days = pooled.arrays(primary=True, subset=ids)
        paired = compare(a, b, y, days, protocol)
        if paired is not None:
            by_basis[basis] = paired

    say("goal models of production")
    guards: dict[str, Paired] = {}
    guard_cover: dict[str, Any] = {}
    for kind, g in guard_scores(matches_a, matches_b, changed, protocol, end=end, progress=progress).items():
        paired = compare(np.array(g.p_a, dtype=np.float64).reshape(-1, 3), np.array(g.p_b, dtype=np.float64).reshape(-1, 3),
                         np.array(g.y, dtype=np.int64), g.days, protocol)
        if paired is not None:
            guards[kind] = paired
        guard_cover[kind] = {"covered_by_both": len(g.y), "uncovered_before": dict(g.uncovered_a),
                             "uncovered_after": dict(g.uncovered_b)}

    decision = decide(protocol, primary, guards, control, by_basis)
    counts = {"matches": len(matches_a), "played": len(played), "labelled_in_window": len(labelled),
              "labelled_priced_by_both": 0 if primary is None else primary.n,
              "control_priced": 0 if control is None else control.n,
              "declined": dict(pooled.declined), "fits": pooled.fits, "failed_fits": pooled.failed_fits,
              "goal_models": guard_cover}
    window = {"from": protocol.test_from.isoformat(), "through": end.isoformat()}
    return AbResult(protocol, rule, dict(labels or {}), window, counts, primary, guards, control, by_basis, decision,
                    _dataset_hash(matches_b), time.monotonic() - began)


def run_ab(conn: psycopg.Connection[Any], *, rule: str = RULE_VERSION, protocol: Protocol | None = None,
           progress: Progress | None = None) -> AbResult:
    """Read the database (nothing is written) and run the comparison: BEFORE is every match as the models read it with no
    rule, AFTER the same with ``rule``'s verdicts."""
    protocol = protocol or Protocol()
    matches_a = load_matches(conn, neutral_rule=None)
    matches_b = load_matches(conn, neutral_rule=rule)
    end = max((m.kickoff_at for m in matches_a if m.has_result), default=protocol.test_from)
    labels = label_state(conn, rule, through=end)
    return evaluate(matches_a, matches_b, _bases(conn, rule), protocol, rule=rule, labels=labels, progress=progress)

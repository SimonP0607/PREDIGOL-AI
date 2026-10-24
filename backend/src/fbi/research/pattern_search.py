"""Plan F12.6 - the weekly search for patterns (plan §14, step 2): where, by the dimensions of the plan, the settled decisions of the system differ from
all the others by more than chance explains - and how often chance alone would have said the same.

What it looks at. Every settled decision of the window - the LAST decision of each selection, the way the memory reads them - is one row with three
measures, each a number per row:

    calibration   what happened minus what the system said (1 or 0, minus its probability). Positive: it happens more often than it says
    vs_close      the log loss of the closing consensus minus the log loss of the system. Positive: the system read the match better than the market
    clv           the closing-line value of the price taken. Positive: the price taken was better than the close

A GROUP is one value of one dimension: a competition, a team, a market, an odds band, the home or the away side, a model, a referee, a coach, a type of
match, how complete the context was. For every group and every measure the search asks one question: is the mean of this group different from the mean
of every other row? (When a dimension has only two groups, each is the other seen from the other side: it is asked once.) The answer is the difference,
its standard error and their ratio, ``z``. Two rules keep it honest:

* the rows of one match are not independent (the two sides of a market, the several markets of a match), so the standard error is CLUSTERED BY MATCH
  (the influence of each row on the difference is added up inside its match before it is squared);
* a group is tested only with a minimum of matches, and a difference that reaches ``z >= 3`` counts only if it also shows, with the same sign, in each
  half of the window (a chance difference rarely does).

Two more keep it from reporting its own plumbing as a discovery:

* the closing-line value of a price depends on the KIND of bet before it depends on anything else: the longer the odds and the stranger the line, and the
  earlier the price was taken (a day ahead it sits further from the close than in the last hour), the further the close is from it, for any decision
  whatever. So a group of a situational dimension (a competition, a team, a coach, a referee, a model, the context) is compared with the rest INSIDE each
  market line, odds band and lead time, and what is read is the mean of those differences, weighted as the Mantel-Haenszel estimator weights them (each
  cell by how many rows of the group and of the rest it holds). The groups of the dimensions that ARE that structure (market, line, selection, odds
  band) have no "inside": they are read as they come and marked DESCRIPTIVE - a fact about how the price is built, not a hypothesis about the system -
  and are never proposed. The other two measures need no such adjustment: no difference is the same as zero for them wherever the bet is;
* a group made of exactly the rows of another one (a market that has a single line is its own line) is tested once, and the report says what else it stands for.

What it does not do is hide how many questions it asked. A search over thousands of groups finds ``z >= 3`` by luck: the report says how many
comparisons it made, how many would reach ``z >= 3`` by chance alone and how large ``z`` would have to be to survive the correction for all of them.
Both numbers read the tails of Student's t with the matches of the smaller side (with 30 matches a ``z`` of 3 is reached by chance twice as often as
the normal curve says), and the correction is Bonferroni: a finding "survives" when its own chance is below ``alpha`` divided by the comparisons.
It reads only (0 provider requests, 0 AI); what it finds becomes at most a HYPOTHESIS proposed to the owner (``propose``), never a rule, a model or a
pick. The functions that decide are pure and sit first; the reading of the database and the proposals are at the end.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import NormalDist
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import psycopg
from psycopg.rows import dict_row
from scipy.special import stdtr

from fbi.core.env import environment
from fbi.research.evolution import propose

VERSION: Final = "search-v1"
WINDOW_DAYS: Final = 90
"""How far back the weekly search looks. The decisions of the system begin on 13 October 2026: until the window is longer than that, it is that long."""
MIN_Z: Final = 3.0
"""The plan's bar (§14): three standard errors from "no difference"."""
MIN_MATCHES: Final = 30
"""The matches a group needs, and the rest needs, before a difference is read at all. Below it the normal approximation of the standard error is not safe."""
HALF_MIN_MATCHES: Final = 10
"""The matches the group needs in each half of the window for the half to be read. With fewer the repetition is "not assessable", and a difference that
cannot be repeated is not proposed."""
HALF_MIN_Z: Final = 1.0
"""The ``z`` each half must reach, with the sign of the whole, for the difference to count as repeated (a loose bar: a half has half the matches)."""
ALPHA: Final = 0.05
"""The chance of one false finding among ALL the comparisons that the corrected threshold (Bonferroni) keeps below."""
MAX_PROPOSALS: Final = 5
"""The most hypotheses one search proposes: the ones with the largest ``z`` that repeat in both halves."""
NEAREST: Final = 10
"""How many of the groups that did not reach the bar the report lists, the nearest first, so that a reader sees what was close."""
OVERLAP: Final = 0.5
"""Two findings on one measure whose groups share at least this part of their rows (the rows of both over the rows of either) say the same thing twice
(the decisions with no calibrator are almost all the decisions of the double-chance market): only the one with the larger ``z`` is proposed."""

METRICS: Final = ("calibration", "vs_close", "clv")
DIMENSIONS: Final = ("market", "market_line", "selection", "model", "calibration_role", "odds_band", "context", "match_type", "competition", "team",
                     "coach", "referee")
STANDS_FOR: Final = ("competition", "team", "referee", "coach", "market", "market_line", "selection", "model", "calibration_role", "odds_band", "context",
                     "match_type")
"""The dimensions by how much their name tells a reader. When two groups are made of the very same rows (a competition that is the only one of its type),
the one of the dimension that comes first in this order is the one the search tests and the report names; the others are said to be the same rows."""
STRUCTURAL: Final = ("market", "market_line", "selection", "odds_band")
"""The dimensions that say what KIND of bet a decision is. The closing-line value of their groups is read as it comes and is DESCRIPTIVE (how the price is
built, not something the system does); for every other dimension it is read inside each market line, odds band and lead time."""
STRATA: Final = ("market_line", "odds_band", "lead")
"""What makes the strata the closing-line value is compared within: the market line, the odds band and the lead time (how long before the kick-off the
decision was taken). The first two are dimensions of the search; the lead time is only read from the row, to compare like with like."""
ADJUSTED: Final = ("clv",)
"""The measures whose value depends on the kind of bet, which the groups of the situational dimensions are therefore compared inside. For calibration and
for the comparison with the close, "no difference" is zero wherever the bet is."""

ODDS_BANDS: Final = ((1.4, "under 1.40"), (1.7, "1.40-1.69"), (2.0, "1.70-1.99"), (2.5, "2.00-2.49"), (3.5, "2.50-3.49"), (6.0, "3.50-5.99"))
"""The upper edges (excluded) of the odds bands of the price taken; from the last edge up it is ``6.00 and over``."""
LAST_BAND: Final = "6.00 and over"
LEAD_BANDS: Final = ((1.0, "under 1 h"), (3.0, "1-3 h"), (6.0, "3-6 h"), (12.0, "6-12 h"), (24.0, "12-24 h"))
"""The upper edges (excluded), in hours, of the lead times; from the last edge up it is ``24 h and over``."""
LAST_LEAD: Final = "24 h and over"

BACKS: Final = {
    ("1X2", "Home"): ("home",), ("1X2", "Away"): ("away",),
    ("DC", "1X"): ("home",), ("DC", "X2"): ("away",),
    ("AH", "Home"): ("home",), ("AH", "Away"): ("away",),
}
"""The side of the match a selection backs. A selection that backs one side belongs to the groups of THAT team and THAT team's coach (the system
backing the home side is a statement about the home side); one that backs none (the draw) or is about the match as a whole (goals, both to score)
belongs to the groups of both."""
NAMED: Final = {("calibration_role", "none"): "ninguno (sin calibrar)"}
"""The groups whose value in the database does not read as what it is: a decision with no calibrator is the group ``none``, written for the owner as
"ninguno (sin calibrar)". The key of a hypothesis keeps the value."""

Array = npt.NDArray[np.float64]
Codes = npt.NDArray[np.int64]


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Obs:
    """One settled decision: what the system believed, what the close said and what happened. ``won`` is 1 or 0 only when the decision settled as a
    win or a loss that the probability can be read against (no stake returned, no half win); ``tags`` gives, for each dimension, the groups the row is
    in (a team dimension has two when the selection backs neither side or is about the match as a whole); ``lead_hours`` is how long before the kick-off
    the decision was taken."""

    fixture_id: int
    kickoff_at: datetime
    p: float
    won: int | None
    p_close: float | None
    clv: float | None
    tags: Mapping[str, tuple[str, ...]]
    lead_hours: float | None = None


def loss(p: float, won: int) -> float:
    """The log loss of a probability ``p`` given to a yes/no that did (``won`` 1) or did not (0) happen; a probability is kept off 0 and 1. The
    same arithmetic as the scoreboard of the families (``fbi.families.versus.loss``, which a test holds equal): written here so that this package
    does not import that one - the import closed a loop of twelve packages that ``tests/unit/test_architecture.py`` does not let grow."""
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return -math.log(p if won else 1.0 - p)


def measure(metric: str, row: Obs) -> float | None:
    """The number a row contributes to a measure, or None when the row cannot be read for it."""
    if metric == "calibration":
        return None if row.won is None else row.won - row.p
    if metric == "vs_close":
        if row.won is None or row.p_close is None:
            return None
        return loss(row.p_close, row.won) - loss(row.p, row.won)
    if metric == "clv":
        return row.clv
    raise ValueError(f"{metric!r} is not a measure of the search")


def lead_band(hours: float | None) -> str:
    """The lead time as a band (``-`` where the row does not say it)."""
    if hours is None:
        return "-"
    for edge, name in LEAD_BANDS:
        if hours < edge:
            return name
    return LAST_LEAD


def stratum(row: Obs) -> tuple[str, ...]:
    """The kind of bet a row is: its market line, its odds band and its lead time (``-`` where a row cannot say one)."""
    return (row.tags.get("market_line", ("-",))[0], row.tags.get("odds_band", ("-",))[0], lead_band(row.lead_hours))


def adjusted(metric: str, dimension: str) -> bool:
    """Whether the groups of this dimension are read INSIDE the strata on this measure."""
    return metric in ADJUSTED and dimension not in STRUCTURAL


def descriptive(metric: str, dimension: str) -> bool:
    """Whether the groups of this dimension on this measure only describe how the price is built: read as they come, never proposed."""
    return metric in ADJUSTED and dimension in STRUCTURAL


def odds_band(odds: float) -> str:
    for edge, name in ODDS_BANDS:
        if odds < edge:
            return name
    return LAST_BAND


def line_text(line: Decimal) -> str:
    """A line the way a reader writes it: ``2.5``, ``-0.5``, ``0`` (and not ``2.50`` or ``-0.5000``)."""
    return "0" if line == 0 else format(line.normalize(), "f")


def side_tags(market: str, selection: str) -> tuple[str, ...]:
    """Which sides of the match (``home``, ``away``) a selection of a market is a statement about: the side it backs, or both."""
    return BACKS.get((market, selection), ("home", "away"))


def tags_of(*, market: str, line: Decimal, selection: str, model: str, calibrator_role: str | None, odds: float | None, context: str,
            competition_type: str, stage_role: str | None, competition_id: int, home_team: int, away_team: int, home_coach: str | None,
            away_coach: str | None, referee_id: int | None) -> dict[str, tuple[str, ...]]:
    """The groups of one decision, dimension by dimension; a dimension the row cannot say (no referee, no odds) is left out of its tags."""
    sides = side_tags(market, selection)
    teams = {"home": str(home_team), "away": str(away_team)}
    coaches = {"home": home_coach, "away": away_coach}
    tags: dict[str, tuple[str, ...]] = {
        "market": (market,), "market_line": (f"{market} {line_text(line)}",), "selection": (f"{market} {selection}",), "model": (model,),
        "calibration_role": (calibrator_role or "none",), "context": (context,),
        "match_type": (f"{competition_type}:{stage_role or 'unknown'}",), "competition": (str(competition_id),),
        "team": tuple(teams[s] for s in sides),
    }
    if odds is not None:
        tags["odds_band"] = (odds_band(odds),)
    found_coaches = tuple(c for s in sides if (c := coaches[s]) is not None)
    if found_coaches:
        tags["coach"] = found_coaches
    if referee_id is not None:
        tags["referee"] = (str(referee_id),)
    return tags


# ── the arithmetic ───────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Contrast:
    """The mean of a group, the mean of everything else and their difference with its standard error (clustered by match)."""

    n: int
    matches: int
    mean: float
    n_rest: int
    matches_rest: int
    mean_rest: float
    delta: float
    se: float

    @property
    def z(self) -> float:
        return self.delta / self.se


def contrast(values: Array, clusters: Codes, member: npt.NDArray[np.bool_], strata: Codes | None = None) -> Contrast | None:
    """The group (``member``) against the rest, over rows with ``values`` and a ``clusters`` code per row (the match, 0 to G - 1).

    The difference of the two means is a sum of one term per row: ``(x - mean of its side) / its side's count``, with the sign of its side. Rows of one
    match are added up first and the sums are squared: that is the variance when the errors of one match are correlated in any way, and it is the
    familiar ``s1^2 / n1 + s0^2 / n0`` when every row is its own match. ``G / (G - 1)`` gives the few matches their due. None when one side is empty
    or the difference has no spread (nothing to divide by). With ``strata`` (a code per row) the group is compared with the rest inside each stratum
    instead of over all the rows (see ``_within``)."""
    if strata is not None:
        return _within(values, clusters, member, strata)
    n = int(member.sum())
    n_rest = int(values.shape[0]) - n
    if n == 0 or n_rest == 0:
        return None
    inside, outside = values[member], values[~member]
    mean, mean_rest = float(inside.mean()), float(outside.mean())
    n_clusters = int(clusters.max()) + 1
    if n_clusters < 2:
        return None
    in_rows = np.bincount(clusters[member], minlength=n_clusters)
    out_rows = np.bincount(clusters[~member], minlength=n_clusters)
    influence = (np.bincount(clusters[member], weights=inside - mean, minlength=n_clusters) / n
                 - np.bincount(clusters[~member], weights=outside - mean_rest, minlength=n_clusters) / n_rest)
    variance = n_clusters / (n_clusters - 1) * float(np.dot(influence, influence))
    if variance <= 0.0 or not math.isfinite(variance):
        return None
    return Contrast(n, int((in_rows > 0).sum()), mean, n_rest, int((out_rows > 0).sum()), mean_rest, mean - mean_rest, math.sqrt(variance))


def _within(values: Array, clusters: Codes, member: npt.NDArray[np.bool_], strata: Codes) -> Contrast | None:
    """The same question asked inside each stratum (a code per row: the kind of bet it is) and answered with one number.

    Inside a stratum the group has a mean and the rest has a mean. The answer is the average of those differences over the strata that hold rows of
    BOTH, each weighted by ``in * out / (in + out)`` - the rows of the group times the rows of the rest, over all of them: the weights of the
    Mantel-Haenszel estimator, the ones that make the average the most precise when the difference is the same everywhere. A stratum with only the
    group, or only the rest, has nothing to be compared with and takes no part (its rows are not counted). Both means returned are the means of the
    strata means under those same weights, so that the answer is exactly their difference.

    The answer is a sum of one term per row, ``weight / in`` for a row of the group and ``- weight / out`` for one of the rest, and its standard error is
    the clustered one of that sum. Each row is measured from where the model "each stratum has its level, and the group adds the same difference in
    all of them" puts it - the mean of its stratum less the share of that difference that falls on its side - so that a real difference does not
    inflate its own error; and the distance is stretched by ``sqrt(k / (k - 1))`` for the ``k`` rows of the stratum, because a mean estimated from ``k``
    rows sits closer to each of them than the true one does (without it, many small strata would make the standard error too small). Where the group's
    difference is not the same in every stratum, what is left over is spread that the error counts."""
    if values.shape[0] == 0:
        return None
    n_strata = int(strata.max()) + 1
    size = np.bincount(strata, minlength=n_strata).astype(np.float64)
    in_count = np.bincount(strata[member], minlength=n_strata).astype(np.float64)
    out_count = size - in_count
    shared = (in_count > 0) & (out_count > 0)
    if not shared.any():
        return None
    in_sum = np.bincount(strata[member], weights=values[member], minlength=n_strata)
    out_sum = np.bincount(strata[~member], weights=values[~member], minlength=n_strata)
    safe_size, safe_in, safe_out = (np.where(shared, count, 1.0) for count in (size, in_count, out_count))
    weight = np.where(shared, in_count * out_count / safe_size, 0.0)
    weight = weight / weight.sum()
    mean, mean_rest = float(np.dot(weight, in_sum / safe_in)), float(np.dot(weight, out_sum / safe_out))
    row_weight = weight[strata]
    coefficient = np.where(member, row_weight / safe_in[strata], -row_weight / safe_out[strata])
    delta = mean - mean_rest
    deviation = (values - ((in_sum + out_sum) / safe_size)[strata] - delta * (member - (in_count / safe_size)[strata])) * np.sqrt(
        safe_size / np.maximum(safe_size - 1.0, 1.0))[strata]
    used = shared[strata]
    n_clusters = int(np.unique(clusters[used]).size)
    if n_clusters < 2:
        return None
    influence = np.bincount(clusters, weights=coefficient * deviation, minlength=int(clusters.max()) + 1)
    variance = n_clusters / (n_clusters - 1) * float(np.dot(influence, influence))
    if variance <= 0.0 or not math.isfinite(variance):
        return None
    inside, outside = member & used, ~member & used
    return Contrast(int(inside.sum()), int(np.unique(clusters[inside]).size), mean, int(outside.sum()), int(np.unique(clusters[outside]).size), mean_rest,
                    delta, math.sqrt(variance))


def two_sided_p(z: float) -> float:
    """The chance, under no difference at all, of a ``z`` this far from zero or farther, for a standard error known exactly (the normal)."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def student_two_sided_p(t: float, df: float) -> float:
    """The same chance when the standard error is itself estimated from ``df + 1`` matches (Student's t): with 30 matches a ``z`` of 3 is reached by
    chance about twice as often as the normal says, and with 300 about as often."""
    return float(2.0 * stdtr(df, -abs(t)))


def corrected_z(tests: int, alpha: float = ALPHA) -> float:
    """How far from zero a ``z`` must be to stay significant after ``tests`` comparisons (Bonferroni: ``alpha / tests`` for each one)."""
    if tests < 1:
        return MIN_Z
    return NormalDist().inv_cdf(1.0 - alpha / (2.0 * tests))


# ── the search ───────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Half:
    """The same difference read in half of the window."""

    matches: int
    delta: float
    z: float


@dataclass(frozen=True, slots=True)
class Finding:
    metric: str
    dimension: str
    value: str
    label: str
    stats: Contrast
    p: float = 1.0
    halves: tuple[Half | None, Half | None] = (None, None)
    stable: bool | None = None
    survives: bool = False
    inside_strata: bool = False
    same_as: tuple[tuple[str, str], ...] = ()

    @property
    def z(self) -> float:
        return self.stats.z

    @property
    def descriptive(self) -> bool:
        return descriptive(self.metric, self.dimension)


@dataclass(slots=True)
class _Table:
    """The rows one measure can be read on, as arrays, and the rows of every group among them."""

    values: Array
    clusters: Codes
    strata: Codes
    when: npt.NDArray[np.float64]
    groups: dict[tuple[str, str], list[int]] = field(default_factory=dict)


def _table(rows: Sequence[Obs], metric: str, dimensions: Iterable[str]) -> _Table:
    chosen = set(dimensions)
    values: list[float] = []
    fixtures: list[int] = []
    kinds: list[int] = []
    when: list[float] = []
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    codes: dict[int, int] = {}
    strata: dict[tuple[str, ...], int] = {}
    for row in rows:
        x = measure(metric, row)
        if x is None:
            continue
        position = len(values)
        values.append(x)
        fixtures.append(codes.setdefault(row.fixture_id, len(codes)))
        kinds.append(strata.setdefault(stratum(row), len(strata)))
        when.append(row.kickoff_at.timestamp())
        for dimension, found in row.tags.items():
            if dimension in chosen:
                for value in dict.fromkeys(found):
                    groups[(dimension, value)].append(position)
    return _Table(np.array(values, dtype=np.float64), np.array(fixtures, dtype=np.int64), np.array(kinds, dtype=np.int64),
                  np.array(when, dtype=np.float64), dict(groups))


def _mirrors(table: _Table) -> set[tuple[str, str]]:
    """The groups that only say again what another group says. When a dimension splits the rows into exactly two groups (every row in one of them),
    each is the other seen from the other side: the same difference with the opposite sign, counted twice and proposed twice. The second is left out."""
    sizes: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (dimension, value), positions in table.groups.items():
        sizes[dimension].append((value, len(positions)))
    total = int(table.values.shape[0])
    return {(dimension, sorted(groups)[1][0]) for dimension, groups in sizes.items() if len(groups) == 2 and sum(n for _, n in groups) == total}


def _twins(table: _Table) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """The groups made of exactly the rows of another group (a market with a single line is its own line; a coach who has only one team in the window
    is that team; the only cup of a window is the only match type of cups). They would be tested twice and told twice. The first in the order of
    ``STANDS_FOR`` stands for all of them: this maps it to the others."""
    order = {dimension: i for i, dimension in enumerate(STANDS_FOR)}
    same: dict[tuple[int, ...], list[tuple[str, str]]] = defaultdict(list)
    for key, positions in table.groups.items():
        same[tuple(positions)].append(key)
    twins: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for keys in same.values():
        if len(keys) > 1:
            first, *rest = sorted(keys, key=lambda k: (order[k[0]], k[1]))
            twins[first] = rest
    return twins


def _overlap(a: npt.NDArray[np.bool_], b: npt.NDArray[np.bool_]) -> float:
    """The part of the rows of either group that both share (0 to 1)."""
    union = int((a | b).sum())
    return int((a & b).sum()) / union if union else 0.0


def _members(size: int, positions: Sequence[int]) -> npt.NDArray[np.bool_]:
    mask = np.zeros(size, dtype=np.bool_)
    mask[np.array(positions, dtype=np.int64)] = True
    return mask


def _recode(clusters: Codes, keep: npt.NDArray[np.bool_]) -> Codes:
    """The cluster codes of the kept rows, renumbered from 0."""
    _, inverse = np.unique(clusters[keep], return_inverse=True)
    return inverse.astype(np.int64)


def _half(table: _Table, member: npt.NDArray[np.bool_], inside: npt.NDArray[np.bool_], min_matches: int, *, within: bool) -> Half | None:
    """The group against the rest using only the rows of one half (inside the strata of that half when ``within``). None when the half has too few
    matches of the group to be read."""
    got = contrast(table.values[inside], _recode(table.clusters, inside), member[inside], table.strata[inside] if within else None)
    if got is None or got.matches < min_matches:
        return None
    return Half(got.matches, got.delta, got.z)


def by_lead(rows: Sequence[Obs]) -> list[dict[str, Any]]:
    """The closing-line value by lead time: how many decisions and matches were taken in each band and the mean of the value of their price. It is what
    the comparison inside the lead times is for, shown from the same rows: the same price, taken earlier, sits further from the close."""
    order = [name for _, name in LEAD_BANDS] + [LAST_LEAD, "-"]
    values: dict[str, list[float]] = defaultdict(list)
    fixtures: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        if r.clv is not None:
            band = lead_band(r.lead_hours)
            values[band].append(r.clv)
            fixtures[band].add(r.fixture_id)
    if set(values) <= {"-"}:
        return []
    return [{"band": band, "decisions": len(values[band]), "matches": len(fixtures[band]), "mean": sum(values[band]) / len(values[band])}
            for band in order if band in values]


def search(rows: Sequence[Obs], *, labels: Mapping[tuple[str, str], str] | None = None, metrics: Sequence[str] = METRICS,
           dimensions: Sequence[str] = DIMENSIONS, min_matches: int = MIN_MATCHES, min_z: float = MIN_Z, half_min_matches: int = HALF_MIN_MATCHES,
           half_min_z: float = HALF_MIN_Z, alpha: float = ALPHA) -> dict[str, Any]:
    """Every group of every dimension against the rest, on every measure: what reaches ``min_z`` (with whether it repeats in both halves and whether it
    survives the correction for all the comparisons), the nearest misses and the numbers a reader needs to judge the lot - how many groups there
    were, how many could be tested, how many comparisons were made and how many would reach the bar by chance alone."""
    labels = {**NAMED, **(labels or {})}
    for metric in metrics:
        if metric not in METRICS:
            raise ValueError(f"{metric!r} is not a measure of the search")
    for dimension in dimensions:
        if dimension not in DIMENSIONS:
            raise ValueError(f"{dimension!r} is not a dimension of the search")
    kickoffs = [r.kickoff_at.timestamp() for r in rows]
    split = (min(kickoffs) + max(kickoffs)) / 2.0 if kickoffs else 0.0
    tables = {metric: _table(rows, metric, dimensions) for metric in metrics}
    tested: list[tuple[str, str, str, Contrast, float, tuple[tuple[str, str], ...]]] = []
    coverage: dict[str, dict[str, dict[str, int]]] = {}
    sample: dict[str, dict[str, Any]] = {}
    for metric, table in tables.items():
        size = int(table.values.shape[0])
        sample[metric] = {"rows": size, "matches": int(table.clusters.max()) + 1 if size else 0, "mean": float(table.values.mean()) if size else None}
        coverage[metric] = {d: {"groups": 0, "tested": 0, "same": 0} for d in dimensions}
        twins = _twins(table)
        left_out = {key for others in twins.values() for key in others}
        mirrors = _mirrors(table)
        for (dimension, value), positions in sorted(table.groups.items()):
            coverage[metric][dimension]["groups"] += 1
            if (dimension, value) in left_out:
                coverage[metric][dimension]["same"] += 1
                continue
            if (dimension, value) in mirrors or len(positions) < min_matches:
                continue
            got = contrast(table.values, table.clusters, _members(size, positions), table.strata if adjusted(metric, dimension) else None)
            if got is None or got.matches < min_matches or got.matches_rest < min_matches:
                continue
            coverage[metric][dimension]["tested"] += 1
            same = tuple((d, labels.get((d, v), v)) for d, v in twins.get((dimension, value), ()))
            tested.append((metric, dimension, value, got, student_two_sided_p(got.z, min(got.matches, got.matches_rest) - 1), same))
    count = len(tested)
    needed = corrected_z(count, alpha)
    graded: list[Finding] = []
    for metric, dimension, value, got, p, same in tested:
        survives = p <= alpha / count
        label = labels.get((dimension, value), value)
        within = adjusted(metric, dimension)
        if abs(got.z) < min_z:
            graded.append(Finding(metric, dimension, value, label, got, p, survives=survives, inside_strata=within, same_as=same))
            continue
        table = tables[metric]
        member = _members(int(table.values.shape[0]), table.groups[(dimension, value)])
        first = table.when < split
        halves = (_half(table, member, first, half_min_matches, within=within), _half(table, member, ~first, half_min_matches, within=within))
        stable = None if None in halves else all(
            h is not None and math.copysign(1.0, h.delta) == math.copysign(1.0, got.delta) and abs(h.z) >= half_min_z for h in halves)
        graded.append(Finding(metric, dimension, value, label, got, p, halves, stable, survives, within, same))
    graded.sort(key=lambda f: (-abs(f.z), f.metric, f.dimension, f.value))
    found = [f for f in graded if abs(f.z) >= min_z]
    near = [f for f in graded if abs(f.z) < min_z][:NEAREST]
    masks = [_members(int(tables[f.metric].values.shape[0]), tables[f.metric].groups[(f.dimension, f.value)]) for f in found]
    shared = [[j for j in range(i) if found[j].metric == f.metric and _overlap(masks[i], masks[j]) >= OVERLAP] for i, f in enumerate(found)]
    return {
        "version": VERSION,
        "criterion": {"min_z": min_z, "min_matches": min_matches, "half_min_matches": half_min_matches, "half_min_z": half_min_z, "alpha": alpha,
                      "split": datetime.fromtimestamp(split, tz=UTC).isoformat() if kickoffs else None,
                      "within": {"measures": list(ADJUSTED), "strata": list(STRATA), "descriptive": list(STRUCTURAL)}},
        "rows": {"decisions": len(rows), "matches": len({r.fixture_id for r in rows}), "by_measure": sample},
        "lead": by_lead(rows) if "clv" in metrics else [],
        "coverage": coverage,
        "tests": count,
        "expected_by_chance": sum(student_two_sided_p(min_z, min(got.matches, got.matches_rest) - 1) for _, _, _, got, _, _ in tested),
        "corrected_z": needed,
        "found": [as_dict(f, shared[i]) for i, f in enumerate(found)],
        "nearest": [as_dict(f) for f in near],
    }


def as_dict(f: Finding, overlaps: Sequence[int] = ()) -> dict[str, Any]:
    """A finding as the report keeps it; ``overlaps`` are the positions, in the list of findings, of the larger ones whose rows it largely shares."""
    c = f.stats
    return {"metric": f.metric, "dimension": f.dimension, "value": f.value, "label": f.label, "n": c.n, "matches": c.matches, "mean": c.mean,
            "n_rest": c.n_rest, "matches_rest": c.matches_rest, "mean_rest": c.mean_rest, "delta": c.delta, "se": c.se, "z": c.z, "p": f.p,
            "halves": [None if h is None else {"matches": h.matches, "delta": h.delta, "z": h.z} for h in f.halves], "stable": f.stable,
            "survives_correction": f.survives, "within_strata": f.inside_strata, "descriptive": f.descriptive,
            "same_rows_as": [[dimension, label] for dimension, label in f.same_as], "overlaps": list(overlaps)}


# ── the text ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _signed(x: float, digits: int = 3) -> str:
    return f"{x:+.{digits}f}"


def _line(f: Mapping[str, Any], min_z: float) -> str:
    """One group on one line. Only a group that reached the bar is read in its two halves; for the others the halves are not worked out ("-")."""
    halves = "/".join("n/a" if h is None else f"{h['z']:+.1f}" for h in f["halves"])
    repeats = {True: "repeats", False: "does not repeat", None: "not assessable"}[f["stable"]] if abs(f["z"]) >= min_z else "-"
    scale = 100.0 if f["metric"] == "clv" else 1.0
    kind = "  [descriptive]" if f["descriptive"] else "  [adjusted]" if f["within_strata"] else ""
    same = "".join(f"  (the same rows as {DIMENSION_ES[d]} {label})" for d, label in f["same_rows_as"])
    return (f"  {f['metric']:<11} {DIMENSION_ES[f['dimension']]:<16} {f['label'][:34]:<34} matches {f['matches']:>4} rows {f['n']:>5}  group {_signed(scale * f['mean'])} "
            f"rest {_signed(scale * f['mean_rest'])}  diff {_signed(scale * f['delta'])}  z {f['z']:+.1f}  p {f['p']:.4f}  halves {halves} {repeats}"
            f"{'  SURVIVES the correction' if f['survives_correction'] else ''}{kind}{same}")


def render(report: Mapping[str, Any]) -> str:
    """The reading as a reader of a terminal wants it: the window, what was read, how many questions were asked and how many answers chance alone would
    have given, what reached the bar and what came nearest."""
    lines = [f"pattern search {report['version']}"]
    window = report.get("window")
    if window:
        lines.append(f"  decisions with kick-off {window['start'][:10]} to {window['end'][:10]} ({window['days']} days"
                     f"{', picks only' if window.get('selected_only') else ''})")
    rows = report["rows"]
    lines.append(f"  settled decisions read: {rows['decisions']:,} in {rows['matches']:,} matches")
    for name, m in rows["by_measure"].items():
        mean = "-" if m["mean"] is None else _signed(100 * m["mean"] if name == "clv" else m["mean"])
        lines.append(f"    {name:<12} {m['rows']:>7,} rows in {m['matches']:>6,} matches, mean {mean}{' %' if name == 'clv' and m['mean'] is not None else ''}")
    if report.get("lead"):
        lines.append("  the value of the price (clv) by lead time, how long before the kick-off the decision was taken:")
        lines.extend(f"    {b['band']:<14} {b['decisions']:>6,} decisions in {b['matches']:>5,} matches, mean {_signed(100 * b['mean'], 2)} %" for b in report["lead"])
    c = report["criterion"]
    lines.append(f"  the bar: |z| >= {c['min_z']:g} with at least {c['min_matches']} matches in the group and in the rest; a finding is proposed only if it has "
                 f"the same sign with |z| >= {c['half_min_z']:g} in each half of the window (each half with {c['half_min_matches']} matches of the group)")
    lines.append(f"  comparisons made: {report['tests']:,}. By chance alone {report['expected_by_chance']:.1f} of them would reach |z| >= {c['min_z']:g}; "
                 f"to stay significant after all of them a group with many matches needs |z| of about {report['corrected_z']:.1f}")
    within = c.get("within")
    if within:
        lines.append(f"  {', '.join(within['measures'])}: a group is compared with the rest inside each ({', '.join(within['strata'])}) [adjusted]; the groups of "
                     f"{', '.join(DIMENSION_ES[d] for d in within['descriptive'])} are read as they come [descriptive: how the price is built, never proposed]")
    lines.append("  groups found / groups with enough matches to be tested, by dimension (+ those with the very rows of another group, tested once):")
    for name, per_dimension in report["coverage"].items():
        cells = ", ".join(f"{DIMENSION_ES[d]} {v['groups']}/{v['tested']}" + (f" +{v['same']}" if v.get("same") else "")
                          for d, v in per_dimension.items() if v["groups"])
        lines.append(f"    {name:<12} {cells or 'no groups'}")
    lines.append(f"FOUND, |z| >= {c['min_z']:g}: {len(report['found'])}")
    lines.extend(_line(f, c["min_z"]) for f in report["found"])
    lines.append(f"NEAREST of the rest ({len(report['nearest'])}):")
    lines.extend(_line(f, c["min_z"]) for f in report["nearest"])
    return "\n".join(lines)


# ── the database ─────────────────────────────────────────────────────────────────────────────────────────────────

SELECTED_ONLY: Final = "l.state NOT IN ('RECHAZADO', 'INVESTIGACION')"

DECISIONS_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line) d.*
      FROM intel.decisions d
     WHERE d.kickoff_at >= %(start)s AND d.kickoff_at < %(end)s
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.id, l.fixture_id, l.kickoff_at, l.market_key, l.line, l.selection, l.model_name, l.calibrator_role, l.odds::float8 AS odds,
       l.context_status, COALESCE(l.p_cal, l.p_model)::float8 AS p, COALESCE(l.p_push, 0)::float8 AS p_push, o.result_status,
       o.clv::float8 AS clv, o.close_p_fair::float8 AS p_close, EXTRACT(EPOCH FROM (l.kickoff_at - l.known_at))::float8 / 3600.0 AS lead_hours,
       f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name, cs.competition_id, c.name AS competition_name,
       c.competition_type, st.role AS stage_role, fr.referee_id, rf.name AS referee_name
  FROM last l
  JOIN intel.decision_outcomes o ON o.decision_id = l.id
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.competition_stages st ON st.id = f.stage_id
  LEFT JOIN core.fixture_referees fr ON fr.fixture_id = f.id
  LEFT JOIN core.referees rf ON rf.id = fr.referee_id
 WHERE o.result_status <> 'void' {extra}
 ORDER BY l.fixture_id, l.market_key, l.selection, l.line
"""
"""The settled decisions of the window, one per selection (the last one before the kick-off): their probability (the calibrated one when a calibrator
was applied), the closing consensus and the value of the price taken, how long before the kick-off the decision was taken, and where each one was
played. A voided decision is not a prediction that came out either way and is left out. A match has one referee here, the last one the provider
named: ``core.fixture_referees`` holds the newest observation of each match and no other, so the join does not multiply the decisions."""

COACHES_SQL = """
SELECT DISTINCT ON (l.fixture_id, l.team_side) l.fixture_id, l.team_side, COALESCE(l.coach_id::text, 'p' || l.provider_coach_id::text) AS coach,
       l.coach_name
  FROM core.fixture_lineups l
 WHERE l.fixture_id = ANY(%(fixtures)s) AND (l.coach_id IS NOT NULL OR l.provider_coach_id IS NOT NULL)
 ORDER BY l.fixture_id, l.team_side, l.fetched_at DESC, l.source
"""
"""The coach of each side of each match, by the identity the memory uses (his id, or the provider's when he has none yet), from the last sheet read."""


def readable(result: str, p_push: float, line: Decimal) -> bool:
    """A decision settled as a win or a loss of a bet no stake can come back from: a probability can be read against it."""
    return result in ("win", "loss") and p_push == 0.0 and (line * 2) % 1 == 0


def read(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, selected_only: bool = False) -> tuple[list[Obs], dict[tuple[str, str], str]]:
    """The settled decisions with kick-off in ``[start, end)`` as rows of the search, and the names of the groups. Reads only."""
    sql = DECISIONS_SQL.format(extra=f"AND {SELECTED_ONLY}" if selected_only else "")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"start": start, "end": end})
        decisions = cur.fetchall()
        fixtures = sorted({int(r["fixture_id"]) for r in decisions})
        cur.execute(COACHES_SQL, {"fixtures": fixtures})
        lineups = cur.fetchall()
    sides: dict[tuple[int, str], str] = {}
    labels: dict[tuple[str, str], str] = {}
    for r in lineups:
        sides[(int(r["fixture_id"]), str(r["team_side"]))] = str(r["coach"])
        if r["coach_name"]:
            labels[("coach", str(r["coach"]))] = str(r["coach_name"])
    rows: list[Obs] = []
    for r in decisions:
        fixture = int(r["fixture_id"])
        line = Decimal(r["line"])
        tags = tags_of(market=r["market_key"], line=line, selection=r["selection"], model=r["model_name"], calibrator_role=r["calibrator_role"],
                       odds=r["odds"], context=r["context_status"], competition_type=r["competition_type"], stage_role=r["stage_role"],
                       competition_id=int(r["competition_id"]), home_team=int(r["home_team_id"]), away_team=int(r["away_team_id"]),
                       home_coach=sides.get((fixture, "home")), away_coach=sides.get((fixture, "away")),
                       referee_id=None if r["referee_id"] is None else int(r["referee_id"]))
        won = (1 if r["result_status"] == "win" else 0) if readable(r["result_status"], float(r["p_push"]), line) else None
        rows.append(Obs(fixture, r["kickoff_at"], float(r["p"]), won, r["p_close"], r["clv"], tags, r["lead_hours"]))
        labels[("competition", str(r["competition_id"]))] = str(r["competition_name"])
        labels[("team", str(r["home_team_id"]))] = str(r["home_name"])
        labels[("team", str(r["away_team_id"]))] = str(r["away_name"])
        if r["referee_id"] is not None and r["referee_name"]:
            labels[("referee", str(r["referee_id"]))] = str(r["referee_name"])
    return rows, labels


def run(conn: psycopg.Connection[Any], *, at: datetime, days: int = WINDOW_DAYS, selected_only: bool = False, **options: Any) -> dict[str, Any]:
    """The search over the decisions with kick-off in the ``days`` before ``at``, with the window written in the report. Reads only."""
    start = at - timedelta(days=days)
    rows, labels = read(conn, start=start, end=at, selected_only=selected_only)
    report = search(rows, labels=labels, **options)
    report["window"] = {"start": start.isoformat(), "end": at.isoformat(), "days": days, "selected_only": selected_only}
    return report


# ── the hypotheses ───────────────────────────────────────────────────────────────────────────────────────────────

DIMENSION_ES: Final = {
    "market": "Mercado", "market_line": "Mercado y línea", "selection": "Selección", "model": "Modelo", "calibration_role": "Calibrador",
    "odds_band": "Rango de cuota", "context": "Contexto", "match_type": "Tipo de partido", "competition": "Competición", "team": "Equipo",
    "coach": "Entrenador", "referee": "Árbitro",
}
MEASURE_ES: Final = {"calibration": "calibración", "vs_close": "frente al cierre", "clv": "valor de cierre (CLV)"}
TARGET: Final = {"calibration": "models", "vs_close": "models", "clv": "pick_engine"}
INVESTIGATION: Final = "US$0 en IA: la comparación se repite en local y luego unos 30 días de shadow"


@dataclass(frozen=True, slots=True)
class Proposal:
    key: str
    title: str
    hypothesis: str
    rationale: str
    target: str
    evidence: dict[str, Any]


LABEL_CHARS: Final = 60
"""A group's name is cut at this many characters in what is written for the owner (a title has 160, the card's chips 90)."""


def _label(f: Mapping[str, Any]) -> str:
    return str(f["label"])[:LABEL_CHARS]


def _title(f: Mapping[str, Any]) -> str:
    who = f"{DIMENSION_ES[f['dimension']]} {_label(f)}"
    if f["metric"] == "calibration":
        return f"{who}: ocurre {'más' if f['delta'] > 0 else 'menos'} de lo que el sistema dice"[:160]
    if f["metric"] == "vs_close":
        return f"{who}: el sistema lee {'mejor' if f['delta'] > 0 else 'peor'} que el cierre"[:160]
    return f"{who}: el precio tomado {'bate' if f['delta'] > 0 else 'pierde contra'} el cierre más que en el resto"[:160]


def _hypothesis(f: Mapping[str, Any]) -> str:
    who = f"{DIMENSION_ES[f['dimension']].lower()} {_label(f)}"
    if f["metric"] == "calibration":
        what = "subestima" if f["delta"] > 0 else "sobrestima"
        return f"En {who} el sistema {what} sus probabilidades más que en el resto; corregirlo a la medida de ese grupo mejoraría su calibración."
    if f["metric"] == "vs_close":
        if f["delta"] > 0:
            return f"En {who} el sistema aporta información frente al cierre; vale la pena medirlo hacia delante antes de confiarle más."
        return f"En {who} el sistema no debería generar candidatos hasta corregir su sesgo frente al cierre."
    if f["delta"] > 0:
        return f"En {who} los precios que toma el sistema baten al cierre más que en el resto; conviene entender por qué antes de darle más peso."
    return f"En {who} los precios que toma el sistema pierden contra el cierre más que en el resto; elegir más cerca del cierre mejoraría el valor."


def _figures(f: Mapping[str, Any]) -> str:
    if f["metric"] == "clv":
        return f"{100 * f['mean']:+.1f} % frente a {100 * f['mean_rest']:+.1f} % en el resto"
    return f"{f['mean']:+.3f} frente a {f['mean_rest']:+.3f} en el resto"


def _difference(f: Mapping[str, Any]) -> str:
    return f"{100 * f['delta']:+.1f} puntos" if f["metric"] == "clv" else f"{f['delta']:+.3f}"


def triage(report: Mapping[str, Any], limit: int = MAX_PROPOSALS) -> tuple[list[Mapping[str, Any]], list[tuple[Mapping[str, Any], str]]]:
    """Which findings of a search become proposals, the largest ``z`` first, and why each of the others that repeat in both halves of the window does not:
    it is DESCRIPTIVE (how the price is built), another finding of the same dimension and measure is larger (the groups of a dimension are each other's
    rest: one tells what the others tell), it shares most of its rows with a larger finding, or the weekly limit is reached. What does not repeat is
    not listed: it is not a candidate."""
    taken: set[int] = set()
    seen: set[tuple[str, str]] = set()
    chosen: list[Mapping[str, Any]] = []
    left: list[tuple[Mapping[str, Any], str]] = []
    for i, f in enumerate(report["found"]):
        if f["stable"] is not True:
            continue
        if f["descriptive"]:
            left.append((f, "descriptive: how the price is built"))
        elif (f["metric"], f["dimension"]) in seen:
            left.append((f, "a larger finding in the same dimension says it already"))
        elif any(j in taken for j in f["overlaps"]):
            left.append((f, "shares most of its rows with a larger finding"))
        elif len(chosen) >= limit:
            left.append((f, f"beyond the {limit} proposals of a search"))
        else:
            taken.add(i)
            seen.add((f["metric"], f["dimension"]))
            chosen.append(f)
    return chosen, left


def proposals(report: Mapping[str, Any], *, limit: int = MAX_PROPOSALS) -> list[Proposal]:
    """The hypotheses a search leaves for the owner (see ``triage``). Each says how many comparisons the search made and how many would reach the bar by
    chance, because that is what a reader needs to weigh it; a finding is a question for an experiment, never a rule."""
    tests, expected = int(report["tests"]), float(report["expected_by_chance"])
    out: list[Proposal] = []
    for f in triage(report, limit)[0]:
        survives = "; sigue siendo significativa corrigiendo por todas las comparaciones" if f["survives_correction"] else ""
        inside = " El CLV se compara dentro del mismo mercado y línea, rango de cuota y antelación de la decisión." if f["within_strata"] else ""
        rationale = (f"En {f['matches']} partidos ({f['n']} decisiones), {_figures(f)}: diferencia {_difference(f)}, z {f['z']:.1f}{survives}. "
                     f"Se repite con el mismo signo en las dos mitades de la ventana.{inside} "
                     f"La búsqueda hizo {tests} comparaciones y por azar se esperarían {expected:.1f} con |z| ≥ {report['criterion']['min_z']:g}. "
                     "Cada dimensión se mira por separado y puede ser el reflejo de otra (un árbitro que solo pita en una competición). "
                     "Un patrón no es una regla: requiere experimento y shadow.")
        out.append(Proposal(
            key=f"pattern2:{f['metric']}:{f['dimension']}:{f['value']}:{'up' if f['delta'] > 0 else 'down'}",
            title=_title(f), hypothesis=_hypothesis(f), rationale=rationale, target=TARGET[f["metric"]],
            evidence={"group": f"{DIMENSION_ES[f['dimension']]}: {_label(f)}", "measure": MEASURE_ES[f["metric"]], "z": round(f["z"], 2),
                      "delta": round(f["delta"], 4), "tests": tests, "expected_by_chance": round(expected, 1), "n_matches": f["matches"],
                      "impact": f"{_figures(f)} en {f['matches']} partidos", "investigation_cost": INVESTIGATION, "pattern_version": VERSION}))
    return out


def known(conn: psycopg.Connection[Any], found: Sequence[Proposal]) -> dict[str, tuple[int, str]]:
    """The proposals of a search that the database already has, whatever the owner decided about them since: key -> (id, status). Reads only."""
    with conn.cursor() as cur:
        cur.execute("SELECT dedup_key, id, status FROM analytics.research_hypotheses WHERE dedup_key = ANY(%s)", ([p.key for p in found],))
        return {str(r[0]): (int(r[1]), str(r[2])) for r in cur.fetchall()}


def register(conn: psycopg.Connection[Any], found: Sequence[Proposal], *, at: datetime) -> list[int]:
    """Propose them to the owner (status PROPOSED, by the system). Keyed: the same group and direction is proposed once, however many weeks it is
    seen, and one the owner has already decided on is not proposed again. Returns the ids written. The caller owns the transaction."""
    ids: list[int] = []
    for p in found:
        hid = propose(conn, title=p.title, hypothesis=p.hypothesis, rationale=p.rationale, evidence=p.evidence, proposed_by="system", at=at,
                      key=p.key, target=p.target)
        if hid is not None:
            ids.append(hid)
    return ids


# ── the weekly job ───────────────────────────────────────────────────────────────────────────────────────────────

SWITCH: Final = "FBI_PATTERN_SEARCH"
MODES: Final = ("off", "report", "propose")
TOP: Final = 5
"""How many of the findings the weekly run writes in its record (the whole reading is one command away: ``python -m scripts.patterns search``)."""


def mode() -> str:
    """What the weekly job does with the search, by ``FBI_PATTERN_SEARCH``: ``off`` (the default, and what anything unknown means: it does not run),
    ``report`` (it runs and keeps a summary in the run's record - 0 writes anywhere else) or ``propose`` (...and the findings that repeat in both
    halves of the window are proposed to the owner in Evolución, once each). The worker reads it at the start of each run."""
    value = environment().get(SWITCH, "off").strip().lower()
    return value if value in MODES else "off"


def summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """The numbers of a reading that the weekly run's record keeps: how much was read, how many questions were asked, how many answers chance alone
    would have given, how many of the findings only describe how the price is built, and the largest of the others with whether they repeat."""
    found = report["found"]
    return {"version": report["version"], "decisions": report["rows"]["decisions"], "matches": report["rows"]["matches"], "tests": report["tests"],
            "expected_by_chance": round(report["expected_by_chance"], 1), "found": len(found), "descriptive": sum(1 for f in found if f["descriptive"]),
            "repeating": sum(1 for f in found if f["stable"] is True and not f["descriptive"]),
            "survive_correction": sum(1 for f in found if f["survives_correction"]),
            "top": [{"measure": f["metric"], "dimension": f["dimension"], "group": f["label"][:LABEL_CHARS], "z": round(f["z"], 1), "repeats": f["stable"]}
                    for f in found if not f["descriptive"]][:TOP]}


def weekly(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The weekly step of the intelligence job: nothing when the switch is ``off``; otherwise the search over the last ``WINDOW_DAYS`` days with its
    summary, and in ``propose`` the hypotheses it leaves written for the owner. The caller commits."""
    chosen = mode()
    if chosen == "off":
        return {"mode": chosen}
    report = run(conn, at=at)
    out: dict[str, Any] = {"mode": chosen, **summary(report)}
    if chosen == "propose":
        out["proposed"] = len(register(conn, proposals(report), at=at))
    return out

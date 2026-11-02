"""Dependence between the families inside one match (plan F11): is the product of two probabilities a fair price for two legs of one match?

A parlay multiplies the probabilities of its legs. It never holds two legs of one match today (``fbi.parlays.persist``), because the legs of a match
depend on each other; the plan asks to MEASURE that dependence between the families (goals, corners, cards) before anyone relaxes the rule. This
module measures it, from finished matches, and decides nothing: no model, price, parlay or pick reads it.

WHAT IS MEASURED, on the matches whose goals (after 90 minutes), corners and cards (counted as lines) are all known - the counts that grade the
bets, through the one door that waits for the result and reads cards only when they are complete (``fbi.families.history``):

* ``EVENTS``: the yes/no questions a leg asks of a family (goals over 2.5, both teams score, the home side wins, corners over 9.5, the away side
  has more cards...). For every pair of events of two different families there are four combinations - both, only the first, only the second,
  neither - and for each its LIFT: how many times it happened over how many times it would have happened had the two events been independent.
  The probability of a combination is the product of the probabilities of its legs times its lift. A lift of 0.95 says the product overstates the
  chance by 5 %, and a parlay that the product values at ``BAR`` (the value a parlay must show to be taken, ``PARLAY_MIN_EV``) is really worth
  ``(1 + BAR) * 0.95 - 1``: nothing is left of the bar.
* ``CORRELATIONS``: the same dependence for the counts themselves (the totals, and the difference home minus away), as a correlation, without
  having to choose a line.

DEPENDENCE INSIDE A STRATUM, NOT ACROSS THEM. A competition with many goals also has many corners and many cards, and a half-year of a competition
differs from the next. Pooled, that can read as a dependence between the families that no match has: it is the level of the competition, which a
forecast already knows. So every figure compares the matches of one STRATUM (a competition in a half-year) with each other and adds the strata
up, the way the Mantel-Haenszel test adds the observed and the expected counts of a table by strata: the matches in which two events would be
expected together, had they been independent, are in each stratum (the matches with the first event) x (the matches with the second) / (the
matches of the stratum), and the expected counts of the strata are added; the correlation is the covariances within strata, added, over the
variances within strata, added. (The expected count is made from the very sample it is compared with, which shrinks the dependence measured by one
match in the matches of the stratum - at most 3 % of it, with the smallest stratum allowed.) A stratum with fewer than ``MIN_STRATUM`` matches
is left out, and said.

THE INTERVALS are a bootstrap in which a competition-day is the unit that is drawn - the matches that a competition played on one day come
together, since they share the weather, the referees and the weekend - within each stratum, ``REPLICATES`` times from a fixed seed, so the same
history gives the same numbers every time.

WHAT IT DOES NOT CONDITION ON are the teams. A strong home side makes more goals, more corners and fewer cards at once, and the forecasts of the
families know the teams: what is left between two legs AFTER their forecasts is smaller than what is measured here. These figures are an upper
bound of the dependence the forecasts do not explain; a pair that is negligible here is negligible, a pair that is not may still be explained by the
teams. Measuring what is left needs the forecasts to be stored for weeks; it is a later reading.

THE VERDICT of a combination compares its lift, with its interval, to ``TOLERANCE``: the independent product is wrong by less than that (the
whole interval inside), by more than that (the whole interval outside, on one side), or the interval does not settle it. The verdict of a pair is
that of its worst combination. Nothing here says a parlay across families would be offered by any house, or at what price: the platform stores no
price for two legs of one match.
"""

from __future__ import annotations

import math
import warnings
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

import numpy as np
import psycopg
from numpy.typing import NDArray

from fbi.families import history
from fbi.families.fit import Match

VERSION: Final = "dependence-v1"
MEASURES: Final = {"goals": "goals_ft", "corners": "corners_ft", "cards": "cards_lines_ft"}
"""One count per family: the measure of the settlement rules that grades its bets (``history.load``)."""
FAMILIES: Final = tuple(MEASURES)
BAR: Final = 0.02
"""The value a parlay has to show to be taken (``fbi.intel.decision.PARLAY_MIN_EV``; a test holds them equal)."""
TOLERANCE: Final = BAR
"""How wrong the independent product may be before it matters: as much as the whole margin that a parlay must show."""
LEVEL: Final = 0.95
REPLICATES: Final = 400
SEED: Final = 11
MIN_STRATUM: Final = 30
"""A competition-half-year with fewer matches than this is left out: its expected counts would be noise."""
MIN_MATCHES: Final = 300
"""Fewer matches than this and nothing is measured."""
HISTORY_DAYS: Final = 3 * 365

OVER: Final = "over"
BTTS: Final = "btts"
HOME_MORE: Final = "home_more"
AWAY_MORE: Final = "away_more"
LINES: Final = {"goals": (1.5, 2.5, 3.5), "corners": (8.5, 9.5, 10.5, 11.5), "cards": (3.5, 4.5, 5.5)}
"""The lines of the totals that a leg can take; the same lines the families are evaluated on."""


@dataclass(frozen=True, slots=True)
class Event:
    """One yes/no question a leg asks of one family, about the counts of the home side and of the away side."""

    family: str
    kind: str
    line: float | None = None

    @property
    def key(self) -> str:
        if self.kind == OVER:
            return f"{self.family}.over_{str(self.line).replace('.', '_')}"
        return f"{self.family}.{self.kind}"

    @property
    def text(self) -> str:
        if self.kind == OVER:
            return f"{self.family} over {self.line:g}"
        if self.kind == BTTS:
            return "both teams score"
        side = "home" if self.kind == HOME_MORE else "away"
        return f"{side} win" if self.family == "goals" else f"{side} side has more {self.family}"

    def holds(self, home: NDArray[np.int64], away: NDArray[np.int64]) -> NDArray[np.bool_]:
        """Whether the event happened, for each match: the total is strictly above the line, both sides have at least one, one side has more."""
        if self.kind == OVER and self.line is not None:
            return np.asarray((home + away) > self.line, dtype=np.bool_)
        if self.kind == BTTS:
            return np.asarray((home > 0) & (away > 0), dtype=np.bool_)
        if self.kind == HOME_MORE:
            return np.asarray(home > away, dtype=np.bool_)
        return np.asarray(away > home, dtype=np.bool_)


def _events() -> tuple[Event, ...]:
    out: list[Event] = []
    for family in FAMILIES:
        out.extend(Event(family, OVER, line) for line in LINES[family])
        if family == "goals":
            out.append(Event(family, BTTS))
        out.extend((Event(family, HOME_MORE), Event(family, AWAY_MORE)))
    return tuple(out)


EVENTS: Final = _events()
VARIABLES: Final = ("goals_total", "corners_total", "cards_total", "goals_diff", "corners_diff", "cards_diff")
"""The counts themselves: the total of a match and the difference home minus away."""
CORRELATIONS: Final = (("goals_total", "corners_total"), ("goals_total", "cards_total"), ("corners_total", "cards_total"),
                       ("goals_diff", "corners_diff"), ("goals_diff", "cards_diff"), ("corners_diff", "cards_diff"))
COLUMNS: Final = tuple(e.key for e in EVENTS) + VARIABLES
PAIRS: Final = tuple((i, j) for i in range(len(EVENTS)) for j in range(i + 1, len(EVENTS)) if EVENTS[i].family != EVENTS[j].family)
"""Every pair of events of two different families (the dependence inside a family is the business of that family's model)."""
CELLS: Final = ("both", "first_only", "second_only", "neither")

NEGLIGIBLE: Final = "negligible"
MATERIAL: Final = "material"
BORDERLINE: Final = "borderline"
TOO_HIGH: Final = "product_overstates"
TOO_LOW: Final = "product_understates"
CELL_WORDS: Final = {NEGLIGIBLE: "negligible", TOO_HIGH: "the product overstates it", TOO_LOW: "the product understates it", BORDERLINE: "borderline"}
PAIR_WORDS: Final = {NEGLIGIBLE: "negligible", MATERIAL: "material", BORDERLINE: "borderline"}


@dataclass(frozen=True, slots=True)
class Row:
    """One finished match with the three counts (home, away) that grade the bets of the three families."""

    fixture_id: int
    competition_id: int
    kickoff_at: datetime
    goals: tuple[int, int]
    corners: tuple[int, int]
    cards: tuple[int, int]


def read(conn: psycopg.Connection[Any], *, since: datetime, cutoff: datetime) -> dict[str, dict[int, list[Match]]]:
    """The three histories, by family, through the door of the families (read-only when the connection is)."""
    return {family: history.load(conn, measure, since=since, cutoff=cutoff) for family, measure in MEASURES.items()}


def join(histories: Mapping[str, Mapping[int, Sequence[Match]]], *, since: datetime | None = None) -> tuple[list[Row], dict[str, int]]:
    """The matches with all three counts known, and how many matches each history had (``joined`` is what is left)."""
    by_fixture: dict[str, dict[int, tuple[int, Match]]] = {
        family: {m.fixture_id: (competition, m) for competition, ms in histories[family].items() for m in ms} for family in FAMILIES}
    coverage = {family: len(found) for family, found in by_fixture.items()}
    rows: list[Row] = []
    for fixture_id in sorted(set.intersection(*(set(found) for found in by_fixture.values()))):
        competition, goals = by_fixture["goals"][fixture_id]
        corners, cards = by_fixture["corners"][fixture_id][1], by_fixture["cards"][fixture_id][1]
        if since is not None and goals.kickoff_at < since:
            continue
        rows.append(Row(fixture_id, competition, goals.kickoff_at, (goals.home, goals.away), (corners.home, corners.away), (cards.home, cards.away)))
    coverage["joined"] = len(rows)
    return rows, coverage


def stratum_of(row: Row) -> tuple[int, int, int]:
    """A competition in a half-year (UTC): the matches that are compared with each other."""
    kickoff = row.kickoff_at.astimezone(UTC)
    return row.competition_id, kickoff.year, 1 if kickoff.month > 6 else 0


def day_of(row: Row) -> date:
    return row.kickoff_at.astimezone(UTC).date()


@dataclass(frozen=True, slots=True)
class Design:
    """The matches as numbers, ready to be added up: one row per match, sorted by stratum and day; one column per event, then per variable."""

    z: NDArray[np.float64]
    starts: NDArray[np.intp]
    """The first row of each stratum."""
    cluster: NDArray[np.intp]
    """The competition-day of each row, numbered in order: the unit that is drawn in the bootstrap."""
    first: NDArray[np.intp]
    """For each competition-day, the number of the first competition-day of its stratum."""
    span: NDArray[np.intp]
    """For each competition-day, how many competition-days its stratum has."""
    dropped: int
    first_kickoff: datetime | None
    last_kickoff: datetime | None

    @property
    def matches(self) -> int:
        return int(self.z.shape[0])

    @property
    def strata(self) -> int:
        return int(self.starts.size)

    @property
    def clusters(self) -> int:
        return int(self.first.size)


def design(rows: Sequence[Row], *, min_stratum: int = MIN_STRATUM) -> Design:
    sizes = Counter(stratum_of(r) for r in rows)
    kept = sorted((r for r in rows if sizes[stratum_of(r)] >= min_stratum), key=lambda r: (stratum_of(r), day_of(r), r.fixture_id))
    n = len(kept)
    dropped = len(rows) - n
    if n == 0:
        empty = np.zeros(0, dtype=np.intp)
        return Design(np.zeros((0, len(COLUMNS))), empty, empty, empty, empty, dropped, None, None)
    strata = [stratum_of(r) for r in kept]
    days = [day_of(r) for r in kept]
    new_stratum = np.array([i == 0 or strata[i] != strata[i - 1] for i in range(n)])
    new_cluster = np.array([i == 0 or strata[i] != strata[i - 1] or days[i] != days[i - 1] for i in range(n)])
    starts = np.flatnonzero(new_stratum).astype(np.intp)
    cluster = (np.cumsum(new_cluster) - 1).astype(np.intp)
    clusters = int(cluster[-1]) + 1
    stratum_of_cluster = (np.cumsum(new_stratum) - 1)[new_cluster]
    first_cluster = cluster[starts]
    first = first_cluster[stratum_of_cluster].astype(np.intp)
    span = np.diff(np.append(first_cluster, clusters))[stratum_of_cluster].astype(np.intp)
    home = {f: np.array([getattr(r, f)[0] for r in kept], dtype=np.int64) for f in FAMILIES}
    away = {f: np.array([getattr(r, f)[1] for r in kept], dtype=np.int64) for f in FAMILIES}
    total = {f: (home[f] + away[f]).astype(np.float64) for f in FAMILIES}
    diff = {f: (home[f] - away[f]).astype(np.float64) for f in FAMILIES}
    columns = [e.holds(home[e.family], away[e.family]).astype(np.float64) for e in EVENTS]
    columns += [total["goals"], total["corners"], total["cards"], diff["goals"], diff["corners"], diff["cards"]]
    return Design(np.column_stack(columns), starts, cluster, first, span, dropped, kept[0].kickoff_at, max(r.kickoff_at for r in kept))


@dataclass(frozen=True, slots=True)
class Totals:
    """What every figure is made of: ``g`` the sums of products over the matches, ``h`` the same expected had the columns been independent inside
    each stratum (``sum over strata of t_s t_s' / n_s``), ``t`` the sums of each column and ``n`` the matches (weights counted)."""

    g: NDArray[np.float64]
    h: NDArray[np.float64]
    t: NDArray[np.float64]
    n: float


def totals(d: Design, weights: NDArray[np.float64] | None = None, *, pooled: bool = False) -> Totals:
    """The sums of the design, each match counted ``weights`` times (once when none), with the strata or - ``pooled`` - as if there were one."""
    starts = np.zeros(1, dtype=np.intp) if pooled else d.starts
    w = np.ones(d.matches) if weights is None else weights
    zw = d.z if weights is None else d.z * w[:, None]
    per_stratum = np.add.reduceat(zw, starts, axis=0)
    size = np.add.reduceat(w, starts)
    return Totals(zw.T @ d.z, (per_stratum / size[:, None]).T @ per_stratum, per_stratum.sum(axis=0), float(size.sum()))


def correlation_matrix(t: Totals) -> NDArray[np.float64]:
    """The correlation of every pair of columns inside the strata (undefined, NaN, where a column does not vary)."""
    covariance = t.g - t.h
    spread = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(covariance / np.outer(spread, spread), dtype=np.float64)


_FIRST = np.array([i for i, _ in PAIRS], dtype=np.intp)
_SECOND = np.array([j for _, j in PAIRS], dtype=np.intp)
_CORRELATED = tuple((COLUMNS.index(a), COLUMNS.index(b)) for a, b in CORRELATIONS)


def cells(t: Totals) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """For every pair of events, the matches observed and the matches expected under independence in each of the four combinations."""
    gij, hij, ti, tj = t.g[_FIRST, _SECOND], t.h[_FIRST, _SECOND], t.t[_FIRST], t.t[_SECOND]
    observed = np.stack([gij, ti - gij, tj - gij, t.n - ti - tj + gij], axis=1)
    expected = np.stack([hij, ti - hij, tj - hij, t.n - ti - tj + hij], axis=1)
    return observed, expected


@dataclass(frozen=True, slots=True)
class Reading:
    """One reading of the history (the real one or one resampled): the correlations, the phi of each pair, the four lifts of each pair."""

    correlation: NDArray[np.float64]
    phi: NDArray[np.float64]
    observed: NDArray[np.float64]
    expected: NDArray[np.float64]
    lift: NDArray[np.float64]


def read_totals(t: Totals) -> Reading:
    matrix = correlation_matrix(t)
    observed, expected = cells(t)
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = observed / expected
    return Reading(np.array([matrix[a, b] for a, b in _CORRELATED]), matrix[_FIRST, _SECOND], observed, expected, lift)


def draw_clusters(d: Design, rng: np.random.Generator) -> NDArray[np.float64]:
    """How many times each competition-day is taken in one resample: every stratum draws, with replacement and among its own days, as many as it has."""
    source = d.first + np.floor(rng.random(d.clusters) * d.span).astype(np.intp)
    return np.bincount(source, minlength=d.clusters).astype(np.float64)


def draw(d: Design, rng: np.random.Generator) -> NDArray[np.float64]:
    """How many times each match is taken in one resample: the times its competition-day is."""
    return draw_clusters(d, rng)[d.cluster]


def bootstrap(d: Design, *, replicates: int, seed: int) -> list[Reading]:
    rng = np.random.default_rng(seed)
    return [read_totals(totals(d, draw(d, rng))) for _ in range(replicates)]


def _num(value: Any) -> float | None:
    x = float(value)
    return x if math.isfinite(x) else None


def _interval(samples: Sequence[NDArray[np.float64]], level: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The percentile interval of each element across the resamples (non-finite draws are not counted)."""
    stack = np.stack(samples)
    stack = np.where(np.isfinite(stack), stack, np.nan)
    low = 100.0 * (1.0 - level) / 2.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return (np.asarray(np.nanpercentile(stack, low, axis=0), dtype=np.float64),
                np.asarray(np.nanpercentile(stack, 100.0 - low, axis=0), dtype=np.float64))


def worth_at_the_bar(lift: float) -> float:
    """What a parlay that the independent product values at ``BAR`` is really worth when the chance of its legs together is ``lift`` times the product."""
    return (1.0 + BAR) * lift - 1.0


def cell_status(lift: float | None, low: float | None, high: float | None, *, tolerance: float = TOLERANCE) -> str:
    """Whether the independent product is wrong by less than ``tolerance`` (the whole interval inside), by more (the whole interval outside)
    or the interval does not say."""
    if lift is None or low is None or high is None:
        return BORDERLINE
    if low >= 1.0 - tolerance and high <= 1.0 + tolerance:
        return NEGLIGIBLE
    if high < 1.0 - tolerance:
        return TOO_HIGH
    if low > 1.0 + tolerance:
        return TOO_LOW
    return BORDERLINE


def pair_verdict(statuses: Iterable[str]) -> str:
    """A pair is material when any of its combinations is wrong by more than the tolerance, negligible when all of them are within it."""
    found = set(statuses)
    if found & {TOO_HIGH, TOO_LOW}:
        return MATERIAL
    return NEGLIGIBLE if found == {NEGLIGIBLE} else BORDERLINE


def measure(rows: Sequence[Row], *, replicates: int = REPLICATES, seed: int = SEED, tolerance: float = TOLERANCE, level: float = LEVEL,
            min_stratum: int = MIN_STRATUM, coverage: Mapping[str, int] | None = None) -> dict[str, Any]:
    """The dependence between the families of the matches ``rows``: correlations, the four lifts of every pair of events, their intervals, verdicts."""
    d = design(rows, min_stratum=min_stratum)
    report: dict[str, Any] = {
        "version": VERSION,
        "criterion": {"tolerance": tolerance, "bar": BAR, "level": level, "replicates": replicates, "seed": seed, "min_stratum": min_stratum,
                      "min_matches": MIN_MATCHES, "strata": "a competition in a half-year, UTC", "unit": "competition-day"},
        "data": {"matches": d.matches, "dropped": d.dropped, "strata": d.strata, "clusters": d.clusters,
                 "first": None if d.first_kickoff is None else d.first_kickoff.astimezone(UTC).isoformat(),
                 "last": None if d.last_kickoff is None else d.last_kickoff.astimezone(UTC).isoformat(), "coverage": dict(coverage or {})},
        "events": {}, "correlations": [], "pairs": [], "summary": {"pairs": 0, NEGLIGIBLE: 0, BORDERLINE: 0, MATERIAL: 0},
    }
    if d.matches < MIN_MATCHES or d.strata < 2:
        return report
    point = read_totals(totals(d))
    pooled = correlation_matrix(totals(d, pooled=True))
    resampled = bootstrap(d, replicates=replicates, seed=seed)
    corr_low, corr_high = _interval([x.correlation for x in resampled], level)
    phi_low, phi_high = _interval([x.phi for x in resampled], level)
    lift_low, lift_high = _interval([x.lift for x in resampled], level)
    t = totals(d)
    report["events"] = {e.key: {"family": e.family, "text": e.text, "rate": _num(t.t[k] / t.n)} for k, e in enumerate(EVENTS)}
    for k, (a, b) in enumerate(CORRELATIONS):
        report["correlations"].append({"a": a, "b": b, "r": _num(point.correlation[k]), "low": _num(corr_low[k]), "high": _num(corr_high[k]),
                                       "pooled": _num(pooled[COLUMNS.index(a), COLUMNS.index(b)])})
    summary = report["summary"]
    for p, (i, j) in enumerate(PAIRS):
        found: dict[str, Any] = {}
        for c, name in enumerate(CELLS):
            lift, low, high = _num(point.lift[p, c]), _num(lift_low[p, c]), _num(lift_high[p, c])
            found[name] = {"observed": _num(point.observed[p, c]), "expected": _num(point.expected[p, c]), "lift": lift, "low": low, "high": high,
                           "worth_at_the_bar": None if lift is None else worth_at_the_bar(lift), "status": cell_status(lift, low, high, tolerance=tolerance)}
        verdict = pair_verdict(x["status"] for x in found.values())
        summary["pairs"] += 1
        summary[verdict] += 1
        report["pairs"].append({"first": EVENTS[i].key, "second": EVENTS[j].key, "phi": _num(point.phi[p]), "phi_low": _num(phi_low[p]),
                                "phi_high": _num(phi_high[p]), "cells": found, "verdict": verdict})
    return report


def _signed(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _lift(cell: Mapping[str, Any]) -> str:
    if cell["lift"] is None:
        return "n/a"
    return f"x{cell['lift']:.3f} [{cell['low']:.3f}, {cell['high']:.3f}]" if cell["low"] is not None and cell["high"] is not None else f"x{cell['lift']:.3f}"


def render(report: Mapping[str, Any], *, top: int = 12) -> str:
    """The reading as text: the data, the correlations of the counts, the tally of the pairs and the pairs that depend most."""
    c, data = report["criterion"], report["data"]
    if not report["pairs"]:
        return (f"dependence between the families inside one match ({report['version']}): {data['matches']} matches with the goals, the corners and the "
                f"cards known ({data['dropped']} more left out in strata of fewer than {c['min_stratum']}); at least {c['min_matches']} matches in two "
                "strata are needed to measure anything")
    events = report["events"]
    cover = data["coverage"]
    lines = [f"dependence between the families inside one match ({report['version']}): {data['matches']} matches with the goals, the corners and the "
             f"cards known ({data['first'][:10]} to {data['last'][:10]}; {cover.get('goals', '?')} had goals, {cover.get('corners', '?')} corners, "
             f"{cover.get('cards', '?')} cards), in {data['strata']} strata ({c['strata']}; {data['dropped']} matches left out in strata of fewer "
             f"than {c['min_stratum']}); intervals {c['level'] * 100:g} %: {c['replicates']} resamples of the {data['clusters']} {c['unit']}s, seed {c['seed']}",
             "  correlation of the counts within a stratum [interval] (pooled over all the matches, as if the strata did not exist, in brackets):"]
    for x in report["correlations"]:
        shown = "n/a" if x["r"] is None else f"{x['r']:+.3f} [{_signed(x['low'])}, {_signed(x['high'])}]"
        lines.append(f"    {x['a']:<14} ~ {x['b']:<14} {shown}   (pooled {_signed(x['pooled'])})")
    s = report["summary"]
    lines.append(f"  {s['pairs']} pairs of events of two families, judged on how wrong the independent product is: {s[NEGLIGIBLE]} {PAIR_WORDS[NEGLIGIBLE]} (every "
                 f"combination within {c['tolerance'] * 100:g} %), {s[MATERIAL]} {PAIR_WORDS[MATERIAL]} (some combination off by more than "
                 f"{c['tolerance'] * 100:g} %), {s[BORDERLINE]} {PAIR_WORDS[BORDERLINE]} (the interval does not settle it)")
    lines.append(f"  the pairs that depend most (phi: the correlation of the two events; lift: times the independent product is exceeded; a parlay the "
                 f"product values at {c['bar'] * 100:g} % is worth the figure in brackets if the combination is the one named):")
    ranked = sorted(report["pairs"], key=lambda p: (-abs(p["phi"]) if p["phi"] is not None else 0.0, p["first"], p["second"]))
    for p in ranked[:top]:
        first, second = events[p["first"]]["text"], events[p["second"]]["text"]
        lines.append(f"    {first} ~ {second}: phi {_signed(p['phi'])} [{_signed(p['phi_low'])}, {_signed(p['phi_high'])}] -> {PAIR_WORDS[p['verdict']]}")
        for name, label in (("both", "both"), ("first_only", f"only {first}"), ("second_only", f"only {second}"), ("neither", "neither")):
            cell = p["cells"][name]
            worth = "" if cell["worth_at_the_bar"] is None else f" ({cell['worth_at_the_bar'] * 100:+.1f} %)"
            lines.append(f"        {label:<44} {_lift(cell)}{worth}  {CELL_WORDS[cell['status']]}")
    return "\n".join(lines)

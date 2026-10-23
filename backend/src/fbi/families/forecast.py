"""PrediGol's forecast of the counts (plan F10, ``family-v1``): the goals of each half, the corners and the cards. SHADOW, research.

What it is. For every upcoming match of a followed competition whose data is fit for a model (the gate of the forecast of F5), it fits the
count of each family on the finished matches of the competition that were already known - the result of a match counts from 6 hours after
its kick-off (``fbi.families.fit.OUTCOME_KNOWN_AFTER``) - and states a probability for every outcome of every market the catalogue has a key for
(``fbi.families.rows``): over/under lines of the total and of each side, the result of the count, double chance, the goals of a half,
HT/FT, the highest scoring half. Nothing here is a price, an edge or a pick: those are the decision layer's, and it does not read these rows.

Where it is written. In the forecast table of F5, under a version of its own (``family-v1``): the page of the forecast of a match reads the
rows of ``forecast-v1`` and nothing else, so no user sees these numbers until the owner decides to show them (plan §22, decision 4). The
number is always marked UNCALIBRATED (basis ``no_champion``): no family has a calibrator, and none will until the gate of the plan
(>= 300 bets and a closing-line value >= 0, which needs the price history of F1) says so.

How the dispersion is estimated. A count that is over-dispersed (corners, cards) needs the variance of the negative binomial, and the variance
a model measures on the matches it was fitted on is a little too small. Once a day (the first pass of the day; the passes that follow reuse it
from memory, a result changes it by a hair and a fit of every competition costs minutes) the dispersion of a measure is measured OUT OF SAMPLE
and pooled over the competitions: every competition is fitted ``DISPERSION_DAYS`` ago and predicts the matches played since; the pooled
residuals give the variance of each side and of the total. The goals of a half are Poisson (the pooled dispersion is not used).

The referee (the cards only). Some referees give more cards than the strengths of the two teams explain. A family with a ``referee_kappa``
scales the means of BOTH sides by the multiplier of the referee of the match (``fbi.families.referee``: the cards of his known matches over
the cards the fit expected of them, shrunk towards "no effect") when the referee is already assigned - the identity F3 settled on, seen by
``at`` - and has enough known matches; every other match is stated without it, and the row says which (the digest of what it was computed from
holds the referee and his multiplier). The dispersion of such a family is measured with the same multipliers, out of sample like the rest.

When a row is written. As in F5: when the market is new, when its model or version changed, or when any outcome moved by half a point.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import numpy as np
import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.families import history, referee, rows
from fbi.families.fit import (
    NO_DISPERSION,
    Dispersion,
    Fitted,
    Match,
    NotEnoughHistoryError,
    Prediction,
    estimate_dispersion,
    fit_family,
    known_at,
)
from fbi.families.versioning import ensure_version
from fbi.forecasting.match_forecast import (
    BASIS_NO_CHAMPION,
    STORED_SQL,
    UNCALIBRATED,
    MarketForecast,
    Outcome,
    Stored,
    fit_fixtures,
    says_something_new,
    store,
)
from fbi.predictions.forecast import HORIZON, upcoming

log = structlog.get_logger(__name__)

VERSION: Final = "family-v1"
"""The ``version`` of the rows in the forecast table. The page of F5 reads ``forecast-v1``."""

HISTORY_DAYS: Final = 3 * 365
"""How far back the finished matches go (the time decay makes the old ones count for little)."""
DISPERSION_DAYS: Final = 120
"""The out-of-sample window of the dispersion: fitted this long ago, predicting the matches since."""
MIN_DISPERSION_MATCHES: Final = 300
"""Fewer out-of-sample matches than this (pooled over the competitions) and a family with a dispersion states nothing."""
MAX_TEAMS: Final = 250
"""A competition with more sides than this in the window (club friendlies: thousands, a handful of matches each) is never fitted:
the strengths mean nothing (the goal models have the same guard, ``MAX_GOAL_TEAMS``)."""


@dataclass(frozen=True, slots=True)
class Spec:
    """One family: what it is fitted on, how it is fitted, and the markets it states."""

    key: str
    model: str
    description: str
    measures: tuple[str, ...]
    family: str
    xi: float
    penalty: float
    over_dispersed: bool
    build: Callable[[Sequence[Prediction], frozenset[str]], list[rows.MarketProbs]]
    referee_kappa: float = 0.0
    """With a value, the means of a match whose referee is known are scaled by his multiplier, shrunk with this prior (``fbi.families.referee``)."""

    @property
    def spec(self) -> str:
        return f"{self.key}:xi={self.xi},penalty={self.penalty}" + (f",referee={self.referee_kappa}" if self.referee_kappa else "")


def _halves(p: Sequence[Prediction], available: frozenset[str]) -> list[rows.MarketProbs]:
    return rows.goals_by_half_markets(p[0], p[1], available=available)


def _counts(prefix: str, total: Sequence[float], side: Sequence[float]) -> Callable[[Sequence[Prediction], frozenset[str]], list[rows.MarketProbs]]:
    def build(p: Sequence[Prediction], available: frozenset[str]) -> list[rows.MarketProbs]:
        return rows.count_markets(p[0], prefix=prefix, total_lines=total, side_lines=side, available=available)
    return build


SPECS: Final = (
    Spec("goals_halves", "family-goals_halves", "Goals of the first and of the second half: a Poisson per team and half, with HT/FT and the "
         "highest scoring half derived from the two fits (plan F10).", ("goals_1h", "goals_2h"), "GOALS_HALF", 0.0019, 8.0, False, _halves),
    Spec("corners_ft", "family-corners_ft", "Corners of the match: a negative binomial per team with an attack and a defence strength "
         "(plan F10).", ("corners_ft",), "CORNERS", 0.0019, 32.0, True,
         _counts("CORNERS", (8.5, 9.5, 10.5, 11.5, 12.5), (3.5, 4.5, 5.5, 6.5))),
    Spec("cards_lines_ft", "family-cards_lines_ft", "Cards of the match counted as lines (a yellow is one, a red is one more): a negative "
         "binomial per team, scaled by the referee when he is assigned (plan F10).", ("cards_lines_ft",), "CARDS", 0.0019, 32.0, True,
         _counts("CARDS", (3.5, 4.5, 5.5), (1.5, 2.5)), referee_kappa=150.0),
    Spec("yellow_ft", "family-yellow_ft", "Yellow cards of the match: a negative binomial per team, scaled by the referee when he is "
         "assigned (plan F10).", ("yellow_ft",), "YELLOW", 0.0019, 32.0, True, _counts("YELLOW", (2.5, 3.5, 4.5), (1.5, 2.5)),
         referee_kappa=150.0),
)


@dataclass
class SpecReport:
    competitions_fitted: int = 0
    competitions_skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dispersion: Dispersion = NO_DISPERSION
    dispersion_matches: int = 0
    fixtures: int = 0
    uses_referee: bool = False
    with_referee: int = 0
    markets_written: int = 0
    rows_written: int = 0
    unchanged: int = 0
    note: str = ""
    error: str = ""


@dataclass
class FamilyReport:
    at: datetime
    targets: int = 0
    not_fit: int = 0
    specs: dict[str, SpecReport] = field(default_factory=dict)

    def summary(self) -> str:
        parts = []
        for key, r in self.specs.items():
            skipped = ", ".join(f"{k} {v}" for k, v in sorted(r.competitions_skipped.items()))
            parts.append(f"{key}: {r.markets_written} markets written ({r.rows_written} rows)/{r.unchanged} unchanged for {r.fixtures} fixtures"
                         f"{f' ({r.with_referee} with a referee)' if r.uses_referee else ''}"
                         f" [{r.competitions_fitted} competitions fitted{', skipped: ' + skipped if skipped else ''}]"
                         f"{' - ' + r.note if r.note else ''}{' - FAILED: ' + r.error if r.error else ''}")
        return f"family forecasts ({self.targets} targets, {self.not_fit} not fit): " + "; ".join(parts)


# ── the pure part ────────────────────────────────────────────────────────────────────────────────────────────────

def _teams(matches: Sequence[Match]) -> int:
    return len({t for m in matches for t in (m.home_id, m.away_id)})


def out_of_sample(by_competition: dict[int, list[Match]], *, measure: str, at: datetime, xi: float, penalty: float,
                  days: int = DISPERSION_DAYS, referee_kappa: float = 0.0) -> tuple[Dispersion, int]:
    """The dispersion of the three counts from predictions made BEFORE the matches they predict, pooled over the competitions, and how many
    matches that is. Each competition is fitted as of ``at - days`` and predicts the matches that were known by ``at``.

    With ``referee_kappa`` the means of a match whose referee has a multiplier are scaled by it, the multiplier learned from the matches known
    when the fit was made - as the family will do when it states the next match - so the dispersion left is that of the numbers it states."""
    start = at - timedelta(days=days)
    yh: list[float] = []
    ya: list[float] = []
    mh: list[float] = []
    ma: list[float] = []
    for matches in by_competition.values():
        if _teams(matches) > MAX_TEAMS:
            continue
        try:
            fitted = fit_family(matches, measure=measure, at=start, xi=xi, penalty=penalty)
        except NotEnoughHistoryError:
            continue
        multipliers = referee.factors([m for m in matches if known_at(m) <= start], fitted, kappa=referee_kappa) if referee_kappa else {}
        for m in matches:
            if known_at(m) <= start or known_at(m) > at or not fitted.knows(m.home_id, m.away_id):
                continue
            mu_h, mu_a = fitted.means(m.home_id, m.away_id, neutral=m.neutral)
            factor = None if m.referee_id is None else multipliers.get(m.referee_id)
            if factor is not None:
                mu_h, mu_a = mu_h * factor, mu_a * factor
            yh.append(m.home)
            ya.append(m.away)
            mh.append(mu_h)
            ma.append(mu_a)
    if not yh:
        return NO_DISPERSION, 0
    return estimate_dispersion(np.array(yh), np.array(mh), np.array(ya), np.array(ma)), len(yh)


def input_hash(spec: Spec, fits: Sequence[Fitted], dispersion: Dispersion, home_id: int, away_id: int, *, referee_id: int | None = None,
               factor: float | None = None) -> str:
    """What the numbers of one match were computed from, in a digest: the family, the training of each fit, the dispersion and, when the
    referee's multiplier was applied, the referee and the multiplier."""
    parts: list[object] = [VERSION, spec.spec, home_id, away_id, round(dispersion.home, 6), round(dispersion.away, 6), round(dispersion.total, 6)]
    for f in fits:
        mu_h, mu_a = f.means(home_id, away_id)
        parts += [f.measure, f.n_train, f.at.isoformat(), round(mu_h, 6), round(mu_a, 6)]
    if factor is not None:
        parts += ["referee", referee_id, round(factor, 6)]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def market_forecast(fixture_id: int, probs: rows.MarketProbs, *, model: str, model_version_id: int, at: datetime, digest: str) -> MarketForecast:
    """A family's probabilities for one market, as the forecast table of F5 stores them: uncalibrated, with no interval."""
    outcomes = tuple(Outcome(selection=s, p_model=p, p=p, lo=None, hi=None, push=0.0) for s, p in probs.outcomes)
    return MarketForecast(fixture_id, probs.market_key, Decimal(str(probs.line)), model, model_version_id, at, outcomes, UNCALIBRATED,
                          BASIS_NO_CHAMPION, None, digest)


# ── reading and writing ──────────────────────────────────────────────────────────────────────────────────────────

FIXTURES_SQL = """
SELECT f.id, cs.competition_id, f.home_team_id, f.away_team_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.id = ANY(%(ids)s)
"""


REFEREES_SQL = """
SELECT fr.fixture_id, fr.referee_id
  FROM core.fixture_referees fr
 WHERE fr.fixture_id = ANY(%(ids)s) AND fr.referee_id IS NOT NULL AND fr.observed_at <= %(at)s
"""


def _referees(conn: psycopg.Connection[Any], ids: list[int], at: datetime) -> dict[int, int]:
    """The referee of each match that has one by ``at``: the identity F3 settled on (``core.fixture_referees`` keeps the latest sighting of a
    match, so a name seen after ``at`` hides an earlier one and the match counts as having none: never a referee that was not known by then)."""
    with conn.cursor() as cur:
        cur.execute(REFEREES_SQL, {"ids": ids, "at": at})
        return {int(r[0]): int(r[1]) for r in cur.fetchall()}


def _available(conn: psycopg.Connection[Any]) -> frozenset[str]:
    """The keys of the catalogue (``market.markets``): a family never invents one."""
    with conn.cursor() as cur:
        cur.execute("SELECT key FROM market.markets")
        return frozenset(str(r[0]) for r in cur.fetchall())


def _stored(conn: psycopg.Connection[Any], ids: list[int], at: datetime) -> dict[tuple[int, str, Decimal], Stored]:
    grouped: dict[tuple[int, str, Decimal], list[dict[str, Any]]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STORED_SQL, {"ids": ids, "at": at, "version": VERSION})
        for r in cur.fetchall():
            grouped[(int(r["fixture_id"]), str(r["market_key"]), Decimal(r["line"]))].append(r)
    return {k: Stored(str(v[0]["model_name"]), int(v[0]["model_version_id"]), str(v[0]["calibration"]),
                      None if v[0]["calibrator_id"] is None else int(v[0]["calibrator_id"]),
                      {str(r["selection"]): Decimal(r["p"]) for r in v})
            for k, v in grouped.items()}


DispersionCache = dict[tuple[str, date], tuple[Dispersion, int]]
"""What a long-lived process keeps between passes: (the spec, the day) -> (the dispersion, the matches it was measured on)."""


def _dispersion(spec: Spec, loaded: dict[str, dict[int, list[Match]]], at: datetime, cache: DispersionCache | None) -> tuple[Dispersion, int]:
    """The out-of-sample dispersion of the family, measured once a day when a cache is given (the entries of other days are dropped)."""
    key = (spec.spec, at.date())
    if cache is not None and key in cache:
        return cache[key]
    got = out_of_sample(loaded[spec.measures[0]], measure=spec.measures[0], at=at, xi=spec.xi, penalty=spec.penalty,
                        referee_kappa=spec.referee_kappa)
    if cache is not None:
        for old in [k for k in cache if k[1] != at.date()]:
            del cache[old]
        cache[key] = got
    return got


def _multipliers(spec: Spec, matches: Sequence[Match], fitted: Fitted, at: datetime) -> dict[int, float]:
    """The multiplier of each referee for a family with a ``referee_kappa`` (none for the others), learned from the matches known at ``at``."""
    if not spec.referee_kappa:
        return {}
    return referee.factors([m for m in matches if known_at(m) <= at], fitted, kappa=spec.referee_kappa)


def _run_spec(conn: psycopg.Connection[Any], spec: Spec, targets: dict[int, list[tuple[int, int, int]]], *, at: datetime,
              code_version: str, available: frozenset[str], stored: dict[tuple[int, str, Decimal], Stored], report: SpecReport,
              cache: DispersionCache | None = None, referees: dict[int, int] | None = None) -> None:
    since = at - timedelta(days=HISTORY_DAYS)
    loaded = {m: history.load(conn, m, since=since, cutoff=at, with_referee=bool(spec.referee_kappa)) for m in spec.measures}
    report.uses_referee = bool(spec.referee_kappa)
    dispersion = NO_DISPERSION
    if spec.over_dispersed:
        dispersion, n = _dispersion(spec, loaded, at, cache)
        report.dispersion, report.dispersion_matches = dispersion, n
        if n < MIN_DISPERSION_MATCHES:
            report.note = f"only {n} out-of-sample matches for the dispersion ({MIN_DISPERSION_MATCHES} needed): nothing stated"
            return
    version_id: int | None = None
    for competition_id, fixtures in sorted(targets.items()):
        fits: list[Fitted] = []
        for measure in spec.measures:
            matches = loaded[measure].get(competition_id, [])
            if _teams(matches) > MAX_TEAMS:
                report.competitions_skipped["too many sides"] += 1
                break
            try:
                fits.append(fit_family(matches, measure=measure, at=at, xi=spec.xi, penalty=spec.penalty,
                                       dispersion=dispersion if spec.over_dispersed else NO_DISPERSION))
            except NotEnoughHistoryError:
                report.competitions_skipped["short history"] += 1
                break
        else:
            report.competitions_fitted += 1
            multipliers = _multipliers(spec, loaded[spec.measures[0]].get(competition_id, []), fits[0], at)
            for fixture_id, home_id, away_id in fixtures:
                referee_id = (referees or {}).get(fixture_id)
                factor = None if referee_id is None else multipliers.get(referee_id)
                predictions = [f.predict(home_id, away_id, factor=1.0 if factor is None else factor) for f in fits]
                if any(p is None for p in predictions):
                    report.competitions_skipped["team not known"] += 1
                    continue
                markets = spec.build([p for p in predictions if p is not None], available)
                if not markets:
                    continue
                if version_id is None:
                    version_id = ensure_version(
                        conn, model=spec.model, description=spec.description, spec=spec.spec,
                        feature_names=["team attack", "team defence", *(["referee"] if spec.referee_kappa else [])],
                        hyper={"measures": list(spec.measures), "xi": spec.xi, "penalty": spec.penalty, "history_days": HISTORY_DAYS,
                               "over_dispersed": spec.over_dispersed, "dispersion_days": DISPERSION_DAYS if spec.over_dispersed else None,
                               "referee_kappa": spec.referee_kappa or None, "referee_min_matches": referee.MIN_MATCHES if spec.referee_kappa else None},
                        train_from=since.date(), train_to=at.date(), n_train=sum(f.n_train for f in fits), repo_commit=code_version)
                report.fixtures += 1
                report.with_referee += factor is not None
                digest = input_hash(spec, fits, dispersion, home_id, away_id, referee_id=referee_id, factor=factor)
                for probs in markets:
                    forecast = market_forecast(fixture_id, probs, model=spec.model, model_version_id=version_id, at=at, digest=digest)
                    if not says_something_new(stored.get((fixture_id, probs.market_key, forecast.line)), forecast):
                        report.unchanged += 1
                        continue
                    written = store(conn, forecast, at=at, code_version=code_version, version=VERSION, family=spec.family)
                    if written == 0:
                        report.unchanged += 1
                        continue
                    report.rows_written += written
                    report.markets_written += 1


def write_family_forecasts(conn: psycopg.Connection[Any], *, at: datetime, code_version: str, horizon: timedelta = HORIZON,
                           fixture_ids: list[int] | None = None, specs: Sequence[Spec] = SPECS,
                           dispersions: DispersionCache | None = None) -> FamilyReport:
    """Forecast every upcoming match for each family and write what is new. Database only: no provider request, no AI.

    ``dispersions`` is the memory of a long-lived process: with it the dispersion of a family is measured once a day, without it at every call."""
    report = FamilyReport(at=at)
    ids = fixture_ids if fixture_ids is not None else upcoming(conn, at, horizon)
    report.targets = len(ids)
    if not ids:
        return report
    fit = fit_fixtures(conn, ids, at)
    report.not_fit = len(ids) - len(fit)
    ids = [i for i in ids if i in fit]
    if not ids:
        return report
    targets: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"ids": ids})
        for r in cur.fetchall():
            targets[int(r["competition_id"])].append((int(r["id"]), int(r["home_team_id"]), int(r["away_team_id"])))
    available = _available(conn)
    stored = _stored(conn, ids, at)
    referees = _referees(conn, ids, at) if any(s.referee_kappa for s in specs) else {}
    for spec in specs:
        sub = SpecReport()
        report.specs[spec.key] = sub
        try:
            with conn.transaction():  # a savepoint: a family is written whole or not at all
                _run_spec(conn, spec, targets, at=at, code_version=code_version, available=available, stored=stored, report=sub,
                          cache=dispersions, referees=referees)
        except Exception as exc:  # recorded on the report and logged; the other families go on
            report.specs[spec.key] = SpecReport(error=f"{type(exc).__name__}: {exc}"[:300])
            log.error("family_forecasts.failed", family=spec.key, error=type(exc).__name__, detail=str(exc)[:300])
    return report

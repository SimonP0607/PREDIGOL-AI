"""EXP-E6 of the plan (RP-9.6): after a streak of ten matches, does the over/under market pay too much or too little in a systematic way?

The protocol is ``fbi.research.exp_protocol.E6`` (registered and fingerprinted on 2026-11-26, before this module could produce a number). This module COUNTS the
cases and RUNS the measurement; the interval by days, the Holm correction, the halves rule and the alpha are those of ``exp_protocol``. It adjusts nothing and
reads no model: it measures a residual of the market.

What it reads (0 provider requests, 0 AI): every finished match with its 90-minute score (not quarantined by the historical validation) and, for the matches that
have it, the LAST Shin consensus of the over/under 2.5 goals before kick-off (``market.market_consensus``, at least three books: the same as the rest of the
system). The experiment needs no prospective sample (the protocol says so): it uses everything that is stored.

THE DEFINITIONS THE PROTOCOL LEFT TO THE CODE, fixed here before any residual was computed (the counts of cases were looked at, never a residual):

* A STREAK is the ten previous finished matches of a team, in any competition, with no gap longer than ``MAX_SPAN_DAYS`` between the first of them and the match
  (a summer break would otherwise join two seasons). «Wins»: the team won all ten; «losses»: lost all ten; «many goals»: all ten had three goals or more in
  total; «few goals»: all ten had two or fewer. All ten, not «most of them»: a looser rule would be a different experiment.
* A match is in the type of a streak when EITHER team has it (it can be in several types: Holm over the types corrects for it).
* The RESIDUAL of a match is «more than 2.5 goals happened» (1 or 0) minus the fair probability of the Over 2.5 of the consensus. A mean residual above zero
  means that the market under-priced the goals after such a streak; below zero, that it over-priced them.
* ``REQUIRED`` is the sample a type needs to be judged: 500 matches, from the power of the question (two standard errors of a yes/no residual are about 4.5
  points with 500) and not from any residual. A type with fewer is not judged, and the experiment does not declare an abandonment until all four types have it.

The verdict: SUCCESS if any type has its sample, its interval by days excludes zero, its Holm-adjusted two-sided p-value is under ``ALPHA`` and both halves of the
period have the same sign; ABANDONMENT only when all four types have their sample and none succeeds (a residual within the error is what is expected);
INSUFFICIENT otherwise, with nothing declared. A success of this experiment alone promotes nothing: the factor «racha» only changes its state in the registry of
factors (RP-4.5).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.research import exp_conditions, exp_protocol
from fbi.research.exp_protocol import ALPHA, Judgement

KEY: Final = "EXP-E6"
STREAK: Final = 10
MAX_SPAN_DAYS: Final = 150
"""The first match of a streak is at most this many days before the match that follows it."""
REQUIRED: Final = 500
MIN_BOOKS: Final = 3
LINE: Final = 2.5
HISTORY_FROM: Final = datetime(2023, 1, 1, tzinfo=UTC)
TYPES: Final = exp_protocol.E6.segments
"""«racha de victorias», «racha de derrotas», «racha de partidos con muchos goles», «racha de partidos con pocos goles»."""
WINS, LOSSES, MANY, FEW = TYPES
NAN: Final = float("nan")

MATCHES_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id AS home, f.away_team_id AS away, r.reg_goals_home AS h, r.reg_goals_away AS a,
       (SELECT c.p_fair::float8 FROM market.market_consensus c
         WHERE c.fixture_id = f.id AND c.market_key = 'OU' AND c.selection = 'Over' AND c.line = %(line)s AND c.devig_method = 'shin'
           AND c.as_of < f.kickoff_at AND c.n_bookmakers >= %(books)s
         ORDER BY c.as_of DESC LIMIT 1) AS q_over
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM analytics.fixture_validation v WHERE v.fixture_id = f.id AND v.state IN ('QUARANTINED', 'INGESTED'))
 ORDER BY f.kickoff_at, f.id
"""
"""Every finished match from the history on, with the last Shin consensus of the Over 2.5 before it (NULL when it has none): the history is needed to see the streaks."""


@dataclass(frozen=True, slots=True)
class Played:
    """A finished match: who played, how it ended in 90 minutes and the market's fair probability of the Over 2.5 (None when it has no consensus)."""

    fixture: int
    kickoff: datetime
    home: int
    away: int
    goals_home: int
    goals_away: int
    q_over: float | None

    @property
    def total(self) -> int:
        return self.goals_home + self.goals_away


@dataclass(frozen=True, slots=True)
class Case:
    """A match that follows a streak, in the types it follows, with the residual of the market."""

    fixture: int
    day: date
    types: tuple[str, ...]
    residual: float


def _result(m: Played, team: int) -> int:
    """+1 a win, 0 a draw, -1 a defeat, for ``team`` in ``m``."""
    mine, theirs = (m.goals_home, m.goals_away) if m.home == team else (m.goals_away, m.goals_home)
    return (mine > theirs) - (mine < theirs)


def streaks_of(window: Sequence[Played], team: int) -> set[str]:
    """The streak types of the ten matches of ``window`` (the team's previous ten, oldest first). Empty if there are not ten."""
    if len(window) < STREAK:
        return set()
    mine = {WINS: all(_result(m, team) == 1 for m in window), LOSSES: all(_result(m, team) == -1 for m in window),
            MANY: all(m.total >= 3 for m in window), FEW: all(m.total <= 2 for m in window)}
    return {k for k, v in mine.items() if v}


def cases(matches: Sequence[Played]) -> list[Case]:
    """The matches (in order of kick-off) that follow a streak of either team and have a consensus, with their residual. Each match is read once; the window of a
    team holds its previous ten matches and nothing from the match itself or later."""
    recent: dict[int, deque[Played]] = defaultdict(lambda: deque(maxlen=STREAK))
    out: list[Case] = []
    for m in matches:
        types: set[str] = set()
        for team in (m.home, m.away):
            window = recent[team]
            if len(window) == STREAK and m.kickoff - window[0].kickoff <= timedelta(days=MAX_SPAN_DAYS):
                types |= streaks_of(list(window), team)
        if types and m.q_over is not None:
            out.append(Case(m.fixture, m.kickoff.date(), tuple(t for t in TYPES if t in types), float(m.total > LINE) - m.q_over))
        recent[m.home].append(m)
        recent[m.away].append(m)
    return out


def series_of(found: Sequence[Case]) -> dict[str, tuple[list[float], list[date]]]:
    """For each type of streak, the residuals of the matches that follow it, with their day."""
    out: dict[str, tuple[list[float], list[date]]] = {t: ([], []) for t in TYPES}
    for c in found:
        for t in c.types:
            out[t][0].append(c.residual)
            out[t][1].append(c.day)
    return out


def two_sided_p(values: Sequence[float], days: Sequence[date], *, seed: int) -> float:
    """P-value of «the mean residual is zero», by resampling whole days: twice the share of resamples on the other side of zero (never zero, capped at 1)."""
    above = exp_protocol.one_sided_p(values, days, below=0.0, seed=seed)
    below = exp_protocol.one_sided_p([-v for v in values], days, below=0.0, seed=seed)
    return float(min(1.0, 2.0 * min(above, below)))


def judge(series: Mapping[str, tuple[Sequence[float], Sequence[date]]], *, required: int = REQUIRED, seed: int) -> tuple[Judgement, dict[str, Any]]:
    """The verdict of the experiment over its four types and the figures of each one (mean residual, interval, adjusted p-value, halves)."""
    ready = {t: v for t, v in series.items() if len(v[0]) >= required}
    raw = {t: two_sided_p(v, d, seed=seed) for t, (v, d) in ready.items()}
    adjusted = exp_protocol.holm(raw) if raw else {}
    figures: dict[str, Any] = {}
    successes: dict[str, Judgement] = {}
    for t in TYPES:
        values, days = series.get(t, ([], []))
        n = len(values)
        if t not in ready:
            figures[t] = {"n": n, "verdict": None, "mean": None, "low": None, "high": None, "adjusted_p": None, "same_sign_halves": None}
            continue
        mean, low, high = exp_protocol.day_bootstrap_ci(values, days, seed=seed)
        halves = exp_protocol.same_sign_in_halves(values, days, centre=0.0)
        wins = (low > 0.0 or high < 0.0) and adjusted[t] < ALPHA and halves
        figures[t] = {"n": n, "verdict": "exito" if wins else "dentro del error", "mean": mean, "low": low, "high": high, "adjusted_p": adjusted[t],
                      "same_sign_halves": halves}
        if wins:
            successes[t] = Judgement("exito", f"{t}: residuo distinto de cero, con intervalo, corrección de Holm y mismo signo en las dos mitades",
                                     mean, low, high, n, adjusted[t])
    if successes:
        best = max(successes.values(), key=lambda j: abs(j.mean))
        return best, figures
    if len(ready) == len(TYPES):
        pooled = min(figures.values(), key=lambda f: abs(f["mean"]))
        return Judgement("abandono", "ningún tipo de racha se aparta de cero: el residuo queda dentro del error, que es lo esperable",
                         pooled["mean"], pooled["low"], pooled["high"], min(f["n"] for f in figures.values()), pooled["adjusted_p"]), figures
    top = max((len(v[0]) for v in series.values()), default=0)
    return Judgement("insuficiente", f"muestra {top} de {required} en el tipo más lleno; {len(ready)} de {len(TYPES)} tipos tienen la suya", NAN, NAN, NAN, top), figures


def load(conn: psycopg.Connection[Any], *, until: datetime) -> list[Played]:
    """Every finished match from the history on and before ``until``. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(MATCHES_SQL, {"line": LINE, "books": MIN_BOOKS, "since": HISTORY_FROM, "until": until})
        rows = cur.fetchall()
    return [Played(int(r["id"]), r["kickoff_at"], int(r["home"]), int(r["away"]), int(r["h"]), int(r["a"]),
                   None if r["q_over"] is None else float(r["q_over"])) for r in rows]


def count(conn: psycopg.Connection[Any], since: date) -> int:
    """The sample of the experiment: the matches that follow a streak of its fullest type (the experiment does not depend on the signature day)."""
    del since
    series = series_of(cases(load(conn, until=datetime(2100, 1, 1, tzinfo=UTC))))
    return max((len(v[0]) for v in series.values()), default=0)


def run(conn: psycopg.Connection[Any], at: datetime) -> tuple[Judgement, dict[str, Any]]:
    protocol = exp_protocol.EXPERIMENTS[KEY]
    found = cases(load(conn, until=at))
    judgement, figures = judge(series_of(found), seed=protocol.seed)
    population = {"types": figures, "cases": len(found), "streak": STREAK, "max_span_days": MAX_SPAN_DAYS, "line": LINE, "required_per_type": REQUIRED,
                  "comparator": "last Shin consensus of the Over 2.5 before kick-off (three books or more)"}
    return judgement, population


def register() -> exp_conditions.Spec:
    """Say how the experiment counts and runs (``scripts.exp_run`` calls it for each module of its ``PLUGINS``)."""
    return exp_conditions.register(KEY, count=count, required=REQUIRED, run=run)


__all__ = ["KEY", "REQUIRED", "STREAK", "TYPES", "Case", "Played", "cases", "count", "judge", "load", "register", "run", "series_of", "streaks_of", "two_sided_p"]

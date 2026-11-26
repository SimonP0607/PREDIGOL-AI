"""The difficulty of a team's coming matches, with its formula and its uncertainty (plan PM, PM-08-05): IN SHADOW.

``FBI_SCHEDULE_DIFFICULTY`` (off by default) and **no route, no page, no packet reads it**: an average of the strength of the coming
rivals can be read as a forecast, so it waits for the owner's publication signature (DM-14, «pieza a pieza»). Until then it is computed
only on request (``python -m scripts.schedule_difficulty``, read only), to be compared with artboard I05 and recomputed by hand.

THE FORMULA (``FORMULA``, the text Metodología will publish):

* the next ``N`` matches of the team in the competitions PrediGol follows (``core.fixtures`` still to be played, recorded by the moment
  asked), within ``HORIZON``;
* each rival's Elo (``features.elo_ratings``, the newest whole run computed by the moment asked; its rating after its last rated match):
  the rating the models read, World Football Elo with home advantage ``HOME_ADVANTAGE`` (``fbi.features.elo.EloParams``);
* the rival's rating **as faced**: minus the home advantage when the team plays at home, plus it when the team plays away, as it is at a
  neutral venue;
* the index is the mean of the ratings as faced; the same mean over the home matches and over the away matches;
* the uncertainty: each rival's rating moves - ``sigma`` is the population standard deviation of its last ``VOLATILITY_N`` ratings
  (how much its Elo moved lately) - and the index's 95 % margin is ``1.96 * sqrt(sum(sigma_i^2)) / n``. It is the uncertainty of the
  ratings, not of the results: the index says how strong the rivals are rated, never what will happen.
* a rival rated on fewer than ``MIN_RATED`` matches (``fbi.backtesting.walkforward.MIN_ELO_HISTORY``) is still mostly the starting
  value: it is listed with ``pocas_partidas`` and the index says ``incierto``; a rival with no rating is left out and counted.

Compared with the competition (``league``): the mean rating of the teams of the season, so the index reads as «above or below the
average rival of the league». The ranking between leagues stays in the LAB (the card's scope).

Reads only; writes nothing; 0 provider requests. Nothing that decides, prices or judges a pick imports it.
"""

from __future__ import annotations

import math
import os
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

SWITCH: Final = "FBI_SCHEDULE_DIFFICULTY"
VERSION: Final = "schedule-difficulty-v1"
N: Final = 5
HORIZON: Final = timedelta(days=60)
HOME_ADVANTAGE: Final = 65.0
"""As ``fbi.features.elo.EloParams.home_advantage`` (a test keeps them equal)."""
VOLATILITY_N: Final = 10
MIN_RATED: Final = 10
"""As ``fbi.backtesting.walkforward.MIN_ELO_HISTORY`` (a test keeps them equal)."""
Z95: Final = 1.96
FORMULA: Final = (
    "Dificultad = media de la fuerza Elo de los próximos rivales, tal como se les enfrenta: Elo del rival menos 65 si se juega en casa, "
    "más 65 si se juega fuera (ventaja de local del Elo), sin ajuste en campo neutral; con la misma media en casa y fuera. Margen del 95 %: "
    "1,96 por la raíz de la suma de los cuadrados de las sigma, dividido por n, con sigma la desviación típica de los 10 últimos Elo de cada rival (cuánto se ha movido). Es la fuerza con la "
    "que están valorados los rivales, no un pronóstico de resultados.")
TABLES: Final = ("core.fixtures", "features.elo_ratings")

Venue = Literal["home", "away", "neutral"]


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on: born off, and even on it only lets the owner's command say so - no reader reads it until
    the publication is signed (DM-14)."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Rival:
    fixture_id: int
    kickoff: datetime
    opponent_id: int
    venue: Venue
    rating: float | None
    rated: int
    """How many rated matches the rival's rating is built on."""
    sigma: float | None
    """Population standard deviation of its last ``VOLATILITY_N`` ratings (``None`` with fewer than two)."""

    @property
    def faced(self) -> float | None:
        return None if self.rating is None else faced(self.rating, self.venue)

    def as_json(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "kickoff_at": self.kickoff.isoformat(), "opponent_id": self.opponent_id,
                "venue": self.venue, "elo": None if self.rating is None else round(self.rating, 1),
                "elo_faced": None if self.faced is None else round(self.faced, 1), "rated_matches": self.rated,
                "sigma": None if self.sigma is None else round(self.sigma, 1),
                "flag": None if self.rating is None else ("pocas_partidas" if self.rated < MIN_RATED else None)}


def faced(rating: float, venue: Venue, *, advantage: float = HOME_ADVANTAGE) -> float:
    """The rival's rating as the team faces it: a rival playing away gives up the home advantage, one playing at home has it."""
    if venue == "home":
        return rating - advantage
    if venue == "away":
        return rating + advantage
    return rating


@dataclass(frozen=True, slots=True)
class Difficulty:
    n: int
    index: float | None
    margin95: float | None
    home_index: float | None
    away_index: float | None
    n_home: int
    n_away: int
    unrated: int
    state: str
    """``medido``, ``incierto`` (a rival rated on few matches, or a sigma unknown) or ``sin_partidos``."""

    def as_json(self) -> dict[str, Any]:
        def r(x: float | None) -> float | None:
            return None if x is None else round(x, 1)

        return {"n": self.n, "index": r(self.index), "margin95": r(self.margin95),
                "interval95": None if self.index is None or self.margin95 is None else [r(self.index - self.margin95),
                                                                                         r(self.index + self.margin95)],
                "home": {"n": self.n_home, "index": r(self.home_index)}, "away": {"n": self.n_away, "index": r(self.away_index)},
                "unrated": self.unrated, "state": self.state}


def difficulty(rivals: Sequence[Rival]) -> Difficulty:
    rated = [r for r in rivals if r.rating is not None]
    unrated = len(rivals) - len(rated)
    if not rated:
        return Difficulty(0, None, None, None, None, 0, 0, unrated, "sin_partidos")
    values = [r.faced for r in rated if r.faced is not None]
    home = [r.faced for r in rated if r.venue == "home" and r.faced is not None]
    away = [r.faced for r in rated if r.venue == "away" and r.faced is not None]
    sigmas = [r.sigma for r in rated]
    margin = None if any(s is None for s in sigmas) else Z95 * math.sqrt(sum(s * s for s in sigmas if s is not None)) / len(rated)
    uncertain = margin is None or any(r.rated < MIN_RATED for r in rated) or unrated > 0
    return Difficulty(
        n=len(rated), index=statistics.fmean(values), margin95=margin,
        home_index=statistics.fmean(home) if home else None, away_index=statistics.fmean(away) if away else None,
        n_home=len(home), n_away=len(away), unrated=unrated, state="incierto" if uncertain else "medido")


def sigma_of(ratings: Sequence[float]) -> float | None:
    return statistics.pstdev(ratings) if len(ratings) >= 2 else None


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

ELO_RUN_SQL: Final = """
WITH RECURSIVE runs AS (
    (SELECT elo_version, run_id, computed_at FROM features.elo_ratings ORDER BY elo_version DESC, run_id DESC LIMIT 1)
    UNION ALL
    SELECT nxt.elo_version, nxt.run_id, nxt.computed_at FROM runs, LATERAL (
        SELECT e.elo_version, e.run_id, e.computed_at FROM features.elo_ratings e
         WHERE (e.elo_version, e.run_id) < (runs.elo_version, runs.run_id)
         ORDER BY e.elo_version DESC, e.run_id DESC LIMIT 1) nxt
)
SELECT elo_version, run_id FROM runs WHERE computed_at <= %(at)s LIMIT 1
"""
"""The newest whole Elo run computed by the moment asked, walked on the primary key (as ``fbi.ai.packet.ELO_RUN_SQL``)."""

COMING_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, f.is_neutral
  FROM core.fixtures f
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.kickoff_at > %(at)s AND f.kickoff_at < %(hi)s AND f.created_at <= %(at)s
   AND f.status_group IN ('scheduled', 'postponed')
 ORDER BY f.kickoff_at, f.id
 LIMIT %(n)s
"""

PAST_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, f.is_neutral
  FROM core.fixtures f
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.kickoff_at < %(at)s AND f.kickoff_at >= %(lo)s AND f.status_group = 'finished'
 ORDER BY f.kickoff_at DESC, f.id DESC
 LIMIT %(n)s
"""
"""The team's last finished matches before the moment asked (RP-6.4: the calendar it has just played)."""
PAST_HORIZON: Final = timedelta(days=120)

RATINGS_SQL: Final = """
SELECT team_id, rating_after, n
  FROM (SELECT team_id, rating_after, kickoff_at,
               row_number() OVER (PARTITION BY team_id ORDER BY kickoff_at DESC, fixture_id DESC) AS rk,
               count(*) OVER (PARTITION BY team_id) AS n
          FROM features.elo_ratings
         WHERE elo_version = %(version)s AND run_id = %(run)s AND team_id = ANY(%(teams)s) AND kickoff_at <= %(at)s) x
 WHERE rk <= %(last)s
 ORDER BY team_id, kickoff_at DESC
"""
"""Each team's last ``VOLATILITY_N`` ratings of the run (the newest first) and how many rated matches it has."""

SEASON_TEAMS_SQL: Final = """
SELECT DISTINCT t FROM core.fixtures f, LATERAL (VALUES (f.home_team_id), (f.away_team_id)) v(t)
 WHERE f.competition_season_id = %(cs)s
"""


@dataclass(frozen=True, slots=True)
class Ratings:
    latest: dict[int, float]
    rated: dict[int, int]
    sigma: dict[int, float | None]


def ratings(conn: psycopg.Connection[Any], teams: Sequence[int], *, at: datetime) -> tuple[tuple[str, int] | None, Ratings]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ELO_RUN_SQL, {"at": at})
        run = cur.fetchone()
        if run is None or not teams:
            return None, Ratings({}, {}, {})
        cur.execute(RATINGS_SQL, {"version": run["elo_version"], "run": run["run_id"], "teams": list(teams), "at": at,
                                  "last": VOLATILITY_N})
        by_team: dict[int, list[float]] = {}
        rated: dict[int, int] = {}
        for r in cur.fetchall():
            by_team.setdefault(int(r["team_id"]), []).append(float(r["rating_after"]))
            rated[int(r["team_id"])] = int(r["n"])
    return (str(run["elo_version"]), int(run["run_id"])), Ratings(
        latest={t: v[0] for t, v in by_team.items()}, rated=rated, sigma={t: sigma_of(v) for t, v in by_team.items()})


@dataclass(frozen=True, slots=True)
class TeamDifficulty:
    team_id: int
    at: datetime
    elo_run: tuple[str, int] | None
    rivals: list[Rival]
    difficulty: Difficulty

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "team_id": self.team_id, "as_of": self.at.isoformat(),
                "elo_run": None if self.elo_run is None else {"version": self.elo_run[0], "run_id": self.elo_run[1]},
                "rivals": [r.as_json() for r in self.rivals], "difficulty": self.difficulty.as_json(), "formula": FORMULA,
                "sources": list(TABLES), "shadow": True}


def _rivals(conn: psycopg.Connection[Any], team_id: int, matches: Sequence[Mapping[str, Any]], *, at: datetime) -> TeamDifficulty:
    opponents = [int(m["away_team_id"]) if int(m["home_team_id"]) == team_id else int(m["home_team_id"]) for m in matches]
    run, rt = ratings(conn, sorted(set(opponents)), at=at)
    rivals = []
    for m, opp in zip(matches, opponents, strict=True):
        venue: Venue = "neutral" if m["is_neutral"] else ("home" if int(m["home_team_id"]) == team_id else "away")
        rivals.append(Rival(fixture_id=int(m["id"]), kickoff=m["kickoff_at"], opponent_id=opp, venue=venue, rating=rt.latest.get(opp),
                            rated=rt.rated.get(opp, 0), sigma=rt.sigma.get(opp)))
    return TeamDifficulty(team_id=team_id, at=at, elo_run=run, rivals=rivals, difficulty=difficulty(rivals))


def team_difficulty(conn: psycopg.Connection[Any], team_id: int, *, at: datetime, n: int = N) -> TeamDifficulty:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COMING_SQL, {"team": team_id, "at": at, "hi": at + HORIZON, "n": n})
        coming = cur.fetchall()
    return _rivals(conn, team_id, coming, at=at)


def recent_difficulty(conn: psycopg.Connection[Any], team_id: int, *, at: datetime, n: int = N) -> TeamDifficulty:
    """The same index over the ``n`` matches the team has just PLAYED (RP-6.4): the strength of the rivals its recent figures were made
    against, each rival's rating as of the moment asked (never a later one). It describes the past; it forecasts nothing."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PAST_SQL, {"team": team_id, "at": at, "lo": at - PAST_HORIZON, "n": n})
        played = cur.fetchall()
    return _rivals(conn, team_id, played, at=at)


CalendarState = Literal["desigual_dificil", "desigual_facil", "equilibrado", "incierto", "sin_datos"]


@dataclass(frozen=True, slots=True)
class CalendarNote:
    """Whether the recent calendar was uneven against the league: the note a figure of recent form carries (RP-6.4)."""

    state: CalendarState
    gap: float | None
    """The index minus the mean rating of the league, in Elo points (positive: the rivals were above the average)."""
    margin95: float | None
    text_es: str | None


def calendar_note(recent: Difficulty, league_mean_rating: float | None) -> CalendarNote:
    """Uneven when the 95 % interval of the index leaves the league's mean out - no threshold of its own: the interval is the uncertainty of
    the ratings the index is made of. Uncertain index (a rival on few matches, no sigma, an unrated rival) says ``incierto``, never a verdict."""
    if recent.index is None or league_mean_rating is None:
        return CalendarNote("sin_datos", None, None, None)
    gap = recent.index - league_mean_rating
    if recent.state != "medido" or recent.margin95 is None:
        return CalendarNote("incierto", gap, recent.margin95, None)
    if gap - recent.margin95 > 0:
        return CalendarNote("desigual_dificil", gap, recent.margin95,
                            "El calendario reciente fue más duro que la media de la liga: sus cifras recientes se midieron contra rivales más fuertes.")
    if gap + recent.margin95 < 0:
        return CalendarNote("desigual_facil", gap, recent.margin95,
                            "El calendario reciente fue más fácil que la media de la liga: sus cifras recientes se midieron contra rivales más flojos.")
    return CalendarNote("equilibrado", gap, recent.margin95, None)


def league_mean(conn: psycopg.Connection[Any], competition_season_id: int, *, at: datetime) -> tuple[int, float | None]:
    """The mean Elo of the teams of a season (the «average rival» of the league) and how many were rated."""
    with conn.cursor() as cur:
        teams = [int(r[0]) for r in cur.execute(SEASON_TEAMS_SQL, {"cs": competition_season_id}).fetchall()]
    _run, rt = ratings(conn, teams, at=at)
    values = list(rt.latest.values())
    return len(values), (statistics.fmean(values) if values else None)

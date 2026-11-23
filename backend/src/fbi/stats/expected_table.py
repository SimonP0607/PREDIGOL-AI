"""The expected table: the points each team would have from the xG of its matches (plan PM, PM-09-06, OP-13). IN SHADOW.

``FBI_EXPECTED_TABLE`` (off by default) and **no route, no page, no packet reads it**: a table of expected points can be read as a
forecast, so it waits for the owner's publication signature (DM-14, «pieza a pieza»). Until then it is computed only on request
(``python -m scripts.expected_table``, read only). It is never a signal of value: nothing that decides, prices or judges a pick imports
it, and the xG is the provider's black box (``LABEL``: «xG de API-Football»).

THE FORMULA (``FORMULA``, the text Metodología will publish):

* the matches: the finished matches of the competition season (``core.fixtures`` with a result in ``core.fixture_results`` recorded by
  the moment asked) whose two teams carry the provider's xG (``core.fixture_team_stats.expected_goals``, source ``api-football``, the
  newest row of each side fetched by then). A match without the xG of both teams is left out and counted (``without_xg``);
* each team's goals in a match are taken as Poisson with mean its xG, the two independent; the probabilities of a win, a draw and a
  loss are the sums over the scores up to ``MAX_GOALS`` plus three times the xG (the tail beyond it is below 1e-12);
* the expected points of a match are ``3·P(win) + P(draw)``; a team's expected points are their sum, next to the points it got in the
  same matches; the 95 % margin of the sum is ``1.96·sqrt(Σ var)``, with ``var = 9·P(win) + P(draw) - xpts²`` of each match under the
  same model: it says how far the real points may fall from the expected ones by chance alone, not how good a team is;
* the order: expected points, then expected goal difference, then expected goals for, then the name (a table of means: no tiebreaker
  of the rules applies).

WHEN IT MAY BE SHOWN (``gate``): only when the matrix (``analytics.coverage_cells``, phase ``todas``, datum ``xg``) grades the xG of
the competition season ``B`` or better - else ``sin_cobertura`` (or ``sin_medir`` before the matrix measured it); only for a league
(``core.competitions.type = 'league'``): the matches of a cup are not one table (``no_es_liga``).

Reads only; writes nothing; 0 provider requests.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

SWITCH: Final = "FBI_EXPECTED_TABLE"
VERSION: Final = "expected-table-v1"
LABEL: Final = "xG de API-Football"
MAX_GOALS: Final = 30
"""The scores summed: beyond ``MAX_GOALS + 3·xG`` goals the tail of a Poisson of mean xG is below 1e-12 for any xG under 10."""
Z95: Final = 1.96
SHOWN: Final = frozenset({"A", "B"})
"""The levels of ``coverage-levels-v1`` with which the table may appear (the card: «solo con xG de nivel B o superior»)."""
FORMULA: Final = (
    "Puntos esperados de un partido = 3 · P(ganar) + P(empatar), con los goles de cada equipo como Poisson de media su xG (xG de "
    "API-Football) e independientes. Puntos esperados de un equipo = su suma en los partidos con el xG de los dos equipos. Margen del "
    "95 %: 1,96 por la raíz de la suma de las varianzas de los puntos de cada partido bajo el mismo modelo. Es lo que dice el xG del "
    "proveedor de los partidos ya jugados, no un pronóstico ni una señal de valor.")
TABLES: Final = ("core.fixtures", "core.fixture_results", "core.fixture_team_stats", "analytics.coverage_cells")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on; even on, no reader reads the table until the owner signs its publication (DM-14)."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _poisson(mean: float) -> list[float]:
    if mean < 0:
        raise ValueError("an xG is never negative")
    top = MAX_GOALS + math.ceil(3 * mean)
    out = [math.exp(-mean)]
    for k in range(1, top + 1):
        out.append(out[-1] * mean / k)
    return out


def outcome(xg_for: float, xg_against: float) -> tuple[float, float, float]:
    """``(P(win), P(draw), P(loss))`` of the team with ``xg_for`` against ``xg_against``, both Poisson and independent."""
    a, b = _poisson(xg_for), _poisson(xg_against)
    win = draw = loss = 0.0
    for i, pa in enumerate(a):
        for j, pb in enumerate(b):
            if i > j:
                win += pa * pb
            elif i == j:
                draw += pa * pb
            else:
                loss += pa * pb
    return win, draw, loss


def expected_points(xg_for: float, xg_against: float) -> tuple[float, float]:
    """The expected points of one match and their variance under the model."""
    win, draw, _ = outcome(xg_for, xg_against)
    mean = 3 * win + draw
    return mean, max(0.0, 9 * win + draw - mean * mean)


@dataclass(frozen=True, slots=True)
class Played:
    """One finished match with the xG of both teams."""

    fixture_id: int
    home_id: int
    away_id: int
    goals_home: int
    goals_away: int
    xg_home: float
    xg_away: float


@dataclass(frozen=True, slots=True)
class Line:
    team_id: int
    name: str | None
    matches: int
    xpts: float
    margin95: float
    points: int
    xg_for: float
    xg_against: float
    goals_for: int
    goals_against: int

    @property
    def xgd(self) -> float:
        return self.xg_for - self.xg_against

    def as_json(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "name": self.name, "matches": self.matches, "xpts": round(self.xpts, 2),
                "margin95": round(self.margin95, 2), "points": self.points, "points_minus_xpts": round(self.points - self.xpts, 2),
                "xg_for": round(self.xg_for, 2), "xg_against": round(self.xg_against, 2), "xgd": round(self.xgd, 2),
                "goals_for": self.goals_for, "goals_against": self.goals_against}


def table(played: Iterable[Played], names: Mapping[int, str] | None = None) -> list[Line]:
    """The expected table of the matches given, ordered (see the module's docstring). Pure."""
    acc: dict[int, list[float]] = {}
    names = names or {}

    def add(team: int, xf: float, xa: float, gf: int, ga: int) -> None:
        mean, var = expected_points(xf, xa)
        got = 3 if gf > ga else 1 if gf == ga else 0
        row = acc.setdefault(team, [0, 0.0, 0.0, 0, 0.0, 0.0, 0, 0])
        row[0] += 1
        row[1] += mean
        row[2] += var
        row[3] += got
        row[4] += xf
        row[5] += xa
        row[6] += gf
        row[7] += ga

    for m in played:
        add(m.home_id, m.xg_home, m.xg_away, m.goals_home, m.goals_away)
        add(m.away_id, m.xg_away, m.xg_home, m.goals_away, m.goals_home)
    lines = [Line(team_id=t, name=names.get(t), matches=int(r[0]), xpts=r[1], margin95=Z95 * math.sqrt(r[2]), points=int(r[3]),
                  xg_for=r[4], xg_against=r[5], goals_for=int(r[6]), goals_against=int(r[7])) for t, r in acc.items()]
    return sorted(lines, key=lambda x: (-round(x.xpts, 9), -round(x.xgd, 9), -round(x.xg_for, 9), x.name or "", x.team_id))


def gate(level: str | None, competition_type: str | None) -> str:
    """Whether the table may be shown: ``visible``, ``no_es_liga``, ``sin_cobertura`` or ``sin_medir``."""
    if competition_type != "league":
        return "no_es_liga"
    if level is None:
        return "sin_medir"
    return "visible" if level in SHOWN else "sin_cobertura"


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

SEASON_SQL: Final = """
SELECT cs.id, cs.season, c.id AS competition_id, c.provider_league_id, c.name, c.type,
       (SELECT x.level FROM analytics.coverage_cells x
         WHERE x.competition_season_id = cs.id AND x.phase_key = 'todas' AND x.datum = 'xg') AS xg_level
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
 WHERE cs.id = %(cs)s
"""

PLAYED_SQL: Final = """
WITH m AS (
    SELECT f.id, f.home_team_id, f.away_team_id, r.goals_home, r.goals_away
      FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.competition_season_id = %(cs)s AND f.status_group = 'finished' AND r.settled_at <= %(at)s
), s AS (
    SELECT DISTINCT ON (t.fixture_id, t.team_side) t.fixture_id, t.team_side, t.expected_goals
      FROM core.fixture_team_stats t JOIN m ON m.id = t.fixture_id
     WHERE t.source = 'api-football' AND t.fetched_at <= %(at)s
     ORDER BY t.fixture_id, t.team_side, t.fetched_at DESC
)
SELECT m.id, m.home_team_id, m.away_team_id, m.goals_home, m.goals_away, h.expected_goals AS xg_home, a.expected_goals AS xg_away
  FROM m LEFT JOIN s h ON h.fixture_id = m.id AND h.team_side = 'home'
         LEFT JOIN s a ON a.fixture_id = m.id AND a.team_side = 'away'
 ORDER BY m.id
"""

NAMES_SQL: Final = "SELECT id, name FROM core.teams WHERE id = ANY(%s)"


@dataclass(frozen=True, slots=True)
class ExpectedTable:
    competition_season_id: int
    competition_id: int
    league: int
    name: str
    season: int
    at: datetime
    xg_level: str | None
    visibility: str
    matches: int
    without_xg: int
    lines: list[Line]

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "label_es": LABEL, "formula_es": FORMULA, "exposed": False,
                "competition_season_id": self.competition_season_id, "competition_id": self.competition_id, "league": self.league,
                "name": self.name, "season": self.season, "at": self.at.isoformat(), "xg_level": self.xg_level,
                "visibility": self.visibility, "matches": self.matches, "without_xg": self.without_xg,
                "rows": [x.as_json() for x in self.lines] if self.visibility == "visible" else []}


def played_of(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Played], int]:
    """The matches with the xG of both teams and how many were left out without it."""
    out, missing = [], 0
    for r in rows:
        if r["xg_home"] is None or r["xg_away"] is None:
            missing += 1
            continue
        out.append(Played(int(r["id"]), int(r["home_team_id"]), int(r["away_team_id"]), int(r["goals_home"]), int(r["goals_away"]),
                          float(r["xg_home"]), float(r["xg_away"])))
    return out, missing


def expected_table(conn: psycopg.Connection[Any], competition_season_id: int, *, at: datetime) -> ExpectedTable | None:
    """The expected table of a competition season as of ``at``; None for a season that does not exist. Its rows are filled only when
    the gate says ``visible`` (the owner's command shows the gate and the counts either way)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEASON_SQL, {"cs": competition_season_id})
        s = cur.fetchone()
        if s is None:
            return None
        cur.execute(PLAYED_SQL, {"cs": competition_season_id, "at": at})
        played, missing = played_of(cur.fetchall())
        teams = sorted({m.home_id for m in played} | {m.away_id for m in played})
        cur.execute(NAMES_SQL, (teams,))
        names = {int(r["id"]): str(r["name"]) for r in cur.fetchall()}
    return ExpectedTable(competition_season_id=int(s["id"]), competition_id=int(s["competition_id"]), league=int(s["provider_league_id"]),
                         name=str(s["name"]), season=int(s["season"]), at=at, xg_level=s["xg_level"],
                         visibility=gate(s["xg_level"], s["type"]), matches=len(played), without_xg=missing,
                         lines=table(played, names))


ELIGIBLE_SQL: Final = """
SELECT DISTINCT ON (cs.competition_id) cs.id, c.provider_league_id, c.name, c.type, cs.season, x.level
  FROM analytics.coverage_cells x
  JOIN core.competition_seasons cs ON cs.id = x.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE x.phase_key = 'todas' AND x.datum = 'xg' AND c.is_tracked AND x.level <> 'MI'
 ORDER BY cs.competition_id, cs.season DESC
"""
"""The newest graded season of every tracked competition (as the directory reads the matrix): where the table would appear."""


def eligible(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Every tracked competition's newest graded season with its xG level and the gate."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ELIGIBLE_SQL)
        return [{"competition_season_id": int(r["id"]), "league": int(r["provider_league_id"]), "name": r["name"], "type": r["type"],
                 "season": int(r["season"]), "xg_level": r["level"], "visibility": gate(r["level"], r["type"])}
                for r in cur.fetchall()]

"""The block «Árbitro designado»: what the referee of a match does, with its sample and its interval, against his league (plan PM,
PM-08-02). BUILT, NOT EXPOSED.

``FBI_REFEREE_BLOCK`` (off by default) and **no route, page or packet reads it**: a block about a named person needs the lawyer's answer
on Ley 1581 (DM-08) before any reader sees it. The block holds only his public professional performance - cards and penalties in the
matches he refereed - never anything of his person beyond the name and country the provider publishes, and no crossing of a referee with
a team (the card's scope). Until the owner has that answer it is read only with ``python -m scripts.referee_block`` (read only).

What it says, as of a moment (like every pre-match reader):

* **who**: the referee the provider had named by then (``fbi.people.officials.referee_as_of``); only a placed person (``identity`` ``id``)
  gets a block - a string the identity has not placed yet is ``sin_identidad``;
* **his matches**: those whose referee, as the provider had named it at the moment, is him under any spelling (the definition of
  ``fbi.intel.dossier``), kicked off in the ``WINDOW`` before the match, with a result recorded by then;
* **the figures**, each with its sample ``n``, a 95 % interval and the same figure for his league (the competition of the match, every
  referee, same window): cards per match (yellow and red of both teams, from the team statistics: only matches with both teams' rows)
  with the Poisson score interval (the analogue of Wilson's for a count); the share of matches with a red card and the share with a
  penalty awarded (from the events: only matches with events), with the Wilson interval;
* **when it may be shown**: the block appears only when the matrix grades the referee datum, and the datum each figure reads, ``B`` or
  better for the competition season (``analytics.coverage_cells``, ``todas``) - else ``sin_cobertura`` (or ``sin_medir`` before the
  matrix measured it); a figure on fewer than ``MIN_MATCHES`` matches is ``muestra_corta``.

Reads only; writes nothing; 0 provider requests. Nothing that decides, prices or judges a pick imports it.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.people.officials import ID, referee_as_of
from fbi.statmath.formulas import Z95, wilson

SWITCH: Final = "FBI_REFEREE_BLOCK"
VERSION: Final = "referee-block-v1"
WINDOW: Final = timedelta(days=400)
"""As ``fbi.intel.dossier.REFEREE_WINDOW`` (a test keeps them equal)."""
MIN_MATCHES: Final = 10
LEVELS: Final = ("A", "B", "C", "D", "MI")
SHOWN: Final = frozenset({"A", "B"})
"""The levels of ``coverage-levels-v1`` with which the block may appear (the card: «nivel B o superior»)."""
NEEDS: Final[Mapping[str, str]] = {"cards_per_match": "yellow_cards", "red_card_share": "yellow_cards", "penalty_share": "events"}
"""The datum of the matrix each figure reads, besides ``referee``."""
RULE: Final = (
    "Solo su actuación profesional pública en los partidos que dirigió (tarjetas y penaltis), sin cruces con equipos. Tarjetas por "
    "partido: amarillas y rojas de los dos equipos, intervalo de puntuación de Poisson al 95 %; partidos con roja y con penalti señalado: "
    "proporción con intervalo de Wilson al 95 %. Cada cifra con su muestra y la de su liga en la misma ventana de 400 días.")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on; even on, no reader reads the block until the lawyer has answered (DM-08)."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


# ── pure ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


def poisson_score(total: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The score interval of a Poisson rate total/n (per match): the analogue of Wilson's for a count,
    ``(x + z²/2 ± z·sqrt(x + z²/4)) / n``."""
    if n <= 0 or total < 0:
        raise ValueError("a rate needs total >= 0 and n > 0")
    centre = total + z * z / 2
    half = z * math.sqrt(total + z * z / 4)
    return max(0.0, (centre - half) / n), (centre + half) / n


@dataclass(frozen=True, slots=True)
class Figure:
    key: str
    kind: str
    """``rate`` (per match) or ``share`` (of matches)."""
    n: int
    value: float | None
    low: float | None
    high: float | None
    league_n: int
    league_value: float | None
    state: str
    """``medido``, ``muestra_corta`` or ``sin_datos``."""

    def as_json(self) -> dict[str, Any]:
        def r(x: float | None) -> float | None:
            return None if x is None else round(x, 3)

        return {"key": self.key, "kind": self.kind, "n": self.n, "value": r(self.value),
                "interval95": None if self.low is None or self.high is None else [r(self.low), r(self.high)],
                "league": {"n": self.league_n, "value": r(self.league_value)}, "state": self.state}


def rate(key: str, total: int, n: int, league_total: int, league_n: int) -> Figure:
    if n <= 0:
        return Figure(key, "rate", 0, None, None, None, league_n, league_total / league_n if league_n else None, "sin_datos")
    low, high = poisson_score(total, n)
    return Figure(key, "rate", n, total / n, low, high, league_n, league_total / league_n if league_n else None,
                  "medido" if n >= MIN_MATCHES else "muestra_corta")


def share(key: str, hits: int, n: int, league_hits: int, league_n: int) -> Figure:
    if n <= 0:
        return Figure(key, "share", 0, None, None, None, league_n, league_hits / league_n if league_n else None, "sin_datos")
    low, high = wilson(hits, n)
    return Figure(key, "share", n, hits / n, low, high, league_n, league_hits / league_n if league_n else None,
                  "medido" if n >= MIN_MATCHES else "muestra_corta")


def gate(levels: Mapping[str, str | None]) -> dict[str, str]:
    """Each figure's visibility from the matrix's levels: ``visible``, ``sin_cobertura`` or ``sin_medir``."""
    out = {}
    for key, datum in NEEDS.items():
        pair = (levels.get("referee"), levels.get(datum))
        if any(v is None for v in pair):
            out[key] = "sin_medir"
        else:
            out[key] = "visible" if all(v in SHOWN for v in pair) else "sin_cobertura"
    return out


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.competition_season_id, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.id = %(fixture)s
"""

LEVELS_SQL: Final = """
SELECT datum, level FROM analytics.coverage_cells
 WHERE competition_season_id = %(cs)s AND phase_key = 'todas' AND datum IN ('referee', 'yellow_cards', 'events')
"""

_FIGURES: Final = """
, s AS (
    SELECT DISTINCT ON (t.fixture_id, t.team_side) t.fixture_id, t.team_side, t.yellow_cards, t.red_cards
      FROM core.fixture_team_stats t JOIN m ON m.fixture_id = t.fixture_id
     WHERE t.fetched_at <= %(at)s
     ORDER BY t.fixture_id, t.team_side, (t.source = 'api-football') DESC, t.fetched_at DESC
), sm AS (
    SELECT fixture_id, sum(COALESCE(yellow_cards, 0) + COALESCE(red_cards, 0)) AS cards, sum(COALESCE(red_cards, 0)) AS reds
      FROM s GROUP BY fixture_id HAVING count(*) = 2 AND bool_and(yellow_cards IS NOT NULL)
), ev AS (
    SELECT e.fixture_id,
           count(*) FILTER (WHERE e.event_type = 'Goal' AND e.detail IN ('Penalty', 'Missed Penalty')
                              AND COALESCE(e.comments, '') <> 'Penalty Shootout') AS penalties
      FROM core.fixture_events e JOIN m ON m.fixture_id = e.fixture_id
     WHERE e.fetched_at <= %(at)s
     GROUP BY e.fixture_id
)
SELECT (SELECT count(*) FROM m) AS matches,
       (SELECT count(*) FROM sm) AS with_stats, (SELECT COALESCE(sum(cards), 0) FROM sm) AS cards,
       (SELECT count(*) FILTER (WHERE reds > 0) FROM sm) AS with_red,
       (SELECT count(*) FROM ev) AS with_events, (SELECT count(*) FILTER (WHERE penalties > 0) FROM ev) AS with_penalty
"""

REFEREE_SQL: Final = """
WITH m AS (
    SELECT o.fixture_id
      FROM core.referee_aliases a
      JOIN core.fixture_officials o ON o.alias_id = a.id AND o.role = 'referee'
      JOIN core.fixtures f ON f.id = o.fixture_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE a.referee_id = %(referee_id)s AND o.observed_at <= %(at)s AND f.kickoff_at < %(kickoff)s
       AND f.kickoff_at >= %(since)s AND r.settled_at <= %(at)s
       AND NOT EXISTS (SELECT 1 FROM core.fixture_officials n
                        WHERE n.fixture_id = o.fixture_id AND n.role = o.role
                          AND n.observed_at > o.observed_at AND n.observed_at <= %(at)s)
)""" + _FIGURES
"""His matches as the provider had named him at ``at`` (the newest officials row at or before it), under any of his spellings."""

LEAGUE_SQL: Final = """
WITH m AS (
    SELECT f.id AS fixture_id
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE cs.competition_id = %(competition)s AND f.kickoff_at < %(kickoff)s AND f.kickoff_at >= %(since)s AND r.settled_at <= %(at)s
)""" + _FIGURES
"""Every match of the competition in the same window, whoever refereed it: the league's figure."""


@dataclass(frozen=True, slots=True)
class RefereeBlock:
    fixture_id: int
    at: datetime
    state: str
    """``construido`` (a block exists; whether a figure may be shown is its ``visibility``), ``sin_arbitro``, ``sin_identidad``."""
    referee_id: int | None
    name: str | None
    country: str | None
    matches: int
    figures: list[Figure]
    visibility: dict[str, str]
    levels: dict[str, str | None]

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "fixture_id": self.fixture_id, "as_of": self.at.isoformat(), "state": self.state,
                "referee": None if self.referee_id is None else {"id": self.referee_id, "name": self.name, "country": self.country},
                "matches": self.matches, "figures": [f.as_json() for f in self.figures], "visibility": self.visibility,
                "levels": self.levels, "rule": RULE, "exposed": False}


def _one(cur: psycopg.Cursor[dict[str, Any]], sql: str, params: dict[str, Any]) -> dict[str, Any]:
    cur.execute(sql, params)
    return dict(cur.fetchone() or {})


def block_of(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> RefereeBlock | None:
    """The block of one match as of ``at`` (``None`` for an unknown match). Reads only, whatever the switch says."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, {"fixture": fixture_id})
        fx = cur.fetchone()
        if fx is None:
            return None
        cur.execute(LEVELS_SQL, {"cs": fx["competition_season_id"]})
        levels: dict[str, str | None] = dict.fromkeys(("referee", "yellow_cards", "events"))
        levels.update({str(r["datum"]): str(r["level"]) for r in cur.fetchall()})
    visibility = gate(levels)
    ref = referee_as_of(conn, fixture_id, at)
    if ref.identity is None:
        return RefereeBlock(fixture_id, at, "sin_arbitro", None, None, None, 0, [], visibility, levels)
    if ref.identity != ID or ref.referee_id is None:
        return RefereeBlock(fixture_id, at, "sin_identidad", None, ref.name, None, 0, [], visibility, levels)
    params = {"at": at, "kickoff": fx["kickoff_at"], "since": fx["kickoff_at"] - WINDOW}
    with conn.cursor(row_factory=dict_row) as cur:
        mine = _one(cur, REFEREE_SQL, params | {"referee_id": ref.referee_id})
        league = _one(cur, LEAGUE_SQL, params | {"competition": fx["competition_id"]})

    def i(row: Mapping[str, Any], k: str) -> int:
        return int(row.get(k) or 0)

    figures = [
        rate("cards_per_match", i(mine, "cards"), i(mine, "with_stats"), i(league, "cards"), i(league, "with_stats")),
        share("red_card_share", i(mine, "with_red"), i(mine, "with_stats"), i(league, "with_red"), i(league, "with_stats")),
        share("penalty_share", i(mine, "with_penalty"), i(mine, "with_events"), i(league, "with_penalty"), i(league, "with_events")),
    ]
    return RefereeBlock(fixture_id, at, "construido", ref.referee_id, ref.name, ref.country, i(mine, "matches"), figures, visibility,
                        levels)

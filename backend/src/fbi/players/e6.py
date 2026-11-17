"""The registered protocol E6 (``INT-A08``, ``proto-int-a08-v1``, IA-052) continued by ``player-engine-v2`` (IA-129): its dry run.

The protocol is NOT changed here: its text and fingerprint live in ``fbi.research.protocol`` and ``tests/unit/test_research_protocols.py``
pins them. What it says about WHEN it may be evaluated (its ``stopping`` rule):

    one evaluation only: the first day on which the dry run (which counts matches and audits leaks WITHOUT READING ANY SCORE) shows
    1.500 matches in both primary cells, or 31-mar-2027 if that does not happen before. The dry run may be repeated.

This module is that dry run's counting and its decision, nothing else:

* ``DRY_RUN_SQL`` counts, per segment, the finished matches that pass the protocol's exclusions that can be checked without a score:
  league-season with the provider's player statistics (``raw.league_coverage.statistics_players``), segment A with the provider's
  absences (``injuries = true``, kick-off from 24-oct-2026) and B without them (from 5-oct-2026), and both teams with at least 5
  covered matches known 90 minutes before kick-off in the 365 days before (``available_at`` of ``fbi.players.history``: kick-off + 3 h
  at the earliest). It reads ``core.fixtures`` (status, kick-off, teams), ``core.fixture_player_stats`` (only whether a match has
  statistics and when they were read) and the coverage; never ``core.fixture_results`` nor a goal.
* The two exclusions it does NOT check - a prediction of the current model at T90 and a complete Shin consensus of 3 h or less at T90 -
  can only REMOVE matches. So its count is an UPPER BOUND of the protocol's sample: below 1.500 the protocol is certainly «PENDIENTE
  POR MUESTRA»; at or above it the decision is ``RECUENTO_COMPLETO`` (the exact count with the two missing exclusions is due first),
  never «evaluate».
* ``decide`` is the stopping rule as a pure function of the counts and the day.

Running the evaluation itself (the challenger ``e6-xi-v1``, the bootstrap of days, Holm) is not here: it runs ONCE, when this dry run
and then the exact count allow it. Nothing here reads a score, writes, or changes a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

KEY: Final = "INT-A08"
PROTOCOL_VERSION: Final = "proto-int-a08-v1"
MIN_PER_CELL: Final = 1_500
DEADLINE: Final = date(2027, 3, 31)
SEGMENT_A_FROM: Final = date(2026, 10, 24)
SEGMENT_B_FROM: Final = date(2026, 10, 5)
MIN_COVERED: Final = 5
SEGMENTS: Final = ("A", "B")

PENDING: Final = "PENDIENTE POR MUESTRA"
FULL_COUNT: Final = "RECUENTO_COMPLETO"
DEADLINE_REACHED: Final = "FECHA_LIMITE"

DRY_RUN_SQL: Final = """
WITH base AS (
    SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id,
           CASE WHEN lc.injuries THEN 'A' ELSE 'B' END AS segment
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
     WHERE f.status_group = 'finished' AND lc.statistics_players
       AND f.kickoff_at >= %(b_from)s AND f.kickoff_at < %(until)s
       AND (NOT lc.injuries OR f.kickoff_at >= %(a_from)s)
), covered AS (
    SELECT s.fixture_id, max(s.fetched_at) AS fetched_at
      FROM core.fixture_player_stats s
     WHERE s.source = 'api-football' AND s.provider_player_id > 0
       AND s.fixture_id IN (SELECT f.id FROM core.fixtures f
                             WHERE f.kickoff_at >= %(b_from)s::timestamptz - interval '365 days' AND f.kickoff_at < %(until)s
                               AND f.status_group = 'finished')
     GROUP BY s.fixture_id
), known AS (
    SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id,
           greatest(f.kickoff_at + interval '3 hours', least(c.fetched_at, f.kickoff_at + interval '48 hours')) AS available_at
      FROM core.fixtures f JOIN covered c ON c.fixture_id = f.id
)
SELECT b.segment, count(*) AS matches
  FROM base b
 WHERE (SELECT count(*) FROM known k WHERE (k.home_team_id = b.home_team_id OR k.away_team_id = b.home_team_id)
          AND k.id <> b.id AND k.kickoff_at >= b.kickoff_at - interval '365 days'
          AND k.available_at <= b.kickoff_at - interval '90 minutes') >= %(min_covered)s
   AND (SELECT count(*) FROM known k WHERE (k.home_team_id = b.away_team_id OR k.away_team_id = b.away_team_id)
          AND k.id <> b.id AND k.kickoff_at >= b.kickoff_at - interval '365 days'
          AND k.available_at <= b.kickoff_at - interval '90 minutes') >= %(min_covered)s
 GROUP BY b.segment
"""
"""The upper bound of each primary cell (no score is read). Parameters: ``params(until)``."""


def params(until: date) -> dict[str, object]:
    return {"a_from": SEGMENT_A_FROM, "b_from": SEGMENT_B_FROM, "until": until, "min_covered": MIN_COVERED}


@dataclass(frozen=True, slots=True)
class Decision:
    state: str
    counts: Mapping[str, int]
    missing: Mapping[str, int]
    reason: str

    def as_json(self) -> dict[str, object]:
        return {"protocol": PROTOCOL_VERSION, "state": self.state, "upper_bound": dict(self.counts), "missing": dict(self.missing),
                "min_per_cell": MIN_PER_CELL, "deadline": DEADLINE.isoformat(), "reason": self.reason,
                "unchecked_exclusions": ["predicción del modelo actual en T90", "consenso Shin completo de 3 h o menos en T90"]}


def decide(counts: Mapping[str, int], today: date) -> Decision:
    """The stopping rule over the dry run's upper bounds. Pure."""
    full = {s: int(counts.get(s, 0)) for s in SEGMENTS}
    missing = {s: max(0, MIN_PER_CELL - n) for s, n in full.items()}
    if today >= DEADLINE:
        return Decision(DEADLINE_REACHED, full, missing, "31-mar-2027 alcanzado: una sola evaluación con lo que haya (protocolo)")
    if all(n >= MIN_PER_CELL for n in full.values()):
        return Decision(FULL_COUNT, full, missing, "la cota superior llega a 1.500 en A y B: falta el recuento exacto con las dos "
                                                   "exclusiones no comprobadas antes de evaluar")
    short = ", ".join(f"{s}: {full[s]} (faltan {missing[s]})" for s in SEGMENTS if missing[s])
    return Decision(PENDING, full, missing, f"cota superior por debajo de 1.500 - {short}")

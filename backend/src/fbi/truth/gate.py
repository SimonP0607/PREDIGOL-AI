"""MODEL_DATA_GATE: what each model needs before it may say anything about a match.

Every model input is one of:

* REQUIRED - without it (or with it stale) the model must not produce a pick.
* OPTIONAL - used when present; its absence lowers nothing but what it would add.
* UNAVAILABLE_BY_PROVIDER - the provider does not cover it for this competition and
  season (its coverage flag says so). A requirement the provider cannot meet is not a
  data failure, but it is not a pass either: the model that needs it cannot run there.
* NOT_USED - no current model reads it.

The thresholds are the minimum a model can be honest with, not a tuning knob: a team
with fewer than ten finished matches in two years has no form to read, a price older
than the capture window the match has reached is not the market's current view
(``fbi.truth.freshness.price_state``), and a consensus of one bookmaker is not a consensus.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.freshness import Freshness, price_state


class Need(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    UNAVAILABLE_BY_PROVIDER = "UNAVAILABLE_BY_PROVIDER"
    NOT_USED = "NOT_USED"


MODEL_NEEDS: dict[str, dict[str, Need]] = {
    "market_baseline": {"fixtures": Need.REQUIRED, "odds_prematch": Need.REQUIRED},
    "goals_poisson_dc": {"fixtures": Need.REQUIRED, "results": Need.REQUIRED, "odds_prematch": Need.REQUIRED,
                         "lineups": Need.OPTIONAL, "injuries": Need.OPTIONAL, "standings": Need.OPTIONAL},
    "elo_ordered_logit": {"fixtures": Need.REQUIRED, "results": Need.REQUIRED, "elo": Need.REQUIRED,
                          "odds_prematch": Need.REQUIRED, "injuries": Need.OPTIONAL},
    "logit_features_v2": {"fixtures": Need.REQUIRED, "results": Need.REQUIRED, "elo": Need.REQUIRED,
                          "match_detail": Need.REQUIRED, "odds_prematch": Need.REQUIRED,
                          "standings": Need.OPTIONAL},
}
"""Per model family, what it reads. ``odds_prematch`` is required of every family because a
pick is a comparison with a price: a probability without one is a forecast, not a pick."""

DATASETS = ("fixtures", "results", "live", "standings", "injuries", "lineups", "match_detail", "odds_prematch",
            "elo", "teams", "players", "coaches", "squads", "coverage")

STRENGTH = {Need.REQUIRED: 3, Need.OPTIONAL: 2, Need.UNAVAILABLE_BY_PROVIDER: 1, Need.NOT_USED: 0}


def dataset_role(dataset: str) -> Need:
    """The strongest need any model has for this dataset."""
    needs = [m.get(dataset, Need.NOT_USED) for m in MODEL_NEEDS.values()]
    return max(needs, key=lambda n: STRENGTH[n]) if needs else Need.NOT_USED


MIN_HISTORY = 10
"""Finished matches with a score per team in the last two years."""
MIN_DETAIL_HISTORY = 5
"""Matches with team statistics per team in the last year (for the shot features)."""
MIN_BOOKMAKERS = 2


GATE_SQL = """
WITH up AS (
    SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.home_team_id, f.away_team_id, c.name AS competition,
           cs.season, lc.odds AS cov_odds, lc.statistics_fixtures AS cov_stats
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
     WHERE c.is_tracked AND f.status_group = 'scheduled'
       AND f.kickoff_at BETWEEN %(at)s AND %(at)s + make_interval(hours => %(hours)s)
), elo_last AS (
    -- every stored rating is for a finished match, so for an upcoming one the newest is "before kick-off"
    SELECT team_id, max(kickoff_at) AS last_rated FROM features.elo_ratings GROUP BY 1
), team AS (
    SELECT t.team_id, t.kickoff_at,
           (SELECT count(*) FROM core.fixtures h JOIN core.fixture_results r ON r.fixture_id = h.id
             WHERE (h.home_team_id = t.team_id OR h.away_team_id = t.team_id) AND h.status_group = 'finished'
               AND h.kickoff_at < t.kickoff_at AND h.kickoff_at > t.kickoff_at - interval '730 days') AS history,
           (SELECT count(DISTINCT s.fixture_id) FROM core.fixture_team_stats s JOIN core.fixtures h ON h.id = s.fixture_id
             WHERE (h.home_team_id = t.team_id OR h.away_team_id = t.team_id) AND h.status_group = 'finished'
               AND h.kickoff_at < t.kickoff_at AND h.kickoff_at > t.kickoff_at - interval '365 days'
               AND s.shots IS NOT NULL) AS detail,
           el.last_rated
      FROM (SELECT home_team_id AS team_id, kickoff_at FROM up UNION SELECT away_team_id, kickoff_at FROM up) t
      LEFT JOIN elo_last el ON el.team_id = t.team_id
), price AS (
    SELECT o.fixture_id, max(o.captured_at) AS last_capture
      FROM market.odds_snapshots o JOIN up ON up.id = o.fixture_id GROUP BY 1
), asked AS (
    SELECT (p.params->>'fixture')::bigint AS provider_fixture_id, max(p.fetched_at) AS last_asked
      FROM raw.ingestion_payloads p
     WHERE p.endpoint = '/odds' AND p.params ? 'fixture' AND p.params->>'fixture' ~ '^[0-9]+$'
     GROUP BY 1
)
SELECT up.*, p.last_capture, a.last_asked,
       (SELECT count(DISTINCT o.bookmaker_id) FROM market.odds_snapshots o
         WHERE o.fixture_id = up.id AND o.market_key = '1X2'
           AND o.captured_at > p.last_capture - interval '20 minutes') AS bookmakers,
       th.history AS home_history, ta.history AS away_history, th.detail AS home_detail, ta.detail AS away_detail,
       th.last_rated AS home_rated, ta.last_rated AS away_rated
  FROM up
  LEFT JOIN price p ON p.fixture_id = up.id
  LEFT JOIN asked a ON a.provider_fixture_id = up.provider_fixture_id
  LEFT JOIN team th ON th.team_id = up.home_team_id AND th.kickoff_at = up.kickoff_at
  LEFT JOIN team ta ON ta.team_id = up.away_team_id AND ta.kickoff_at = up.kickoff_at
 ORDER BY up.kickoff_at
"""


@dataclass
class FixtureGate:
    provider_fixture_id: int
    competition: str
    kickoff_at: datetime
    datasets: dict[str, tuple[Need | str, str]] = field(default_factory=dict)
    """dataset -> ("ok" | "missing" | Need.UNAVAILABLE_BY_PROVIDER, explanation)."""

    def passes(self, model: str) -> tuple[bool, list[str]]:
        blocking: list[str] = []
        for dataset, need in MODEL_NEEDS[model].items():
            if need is not Need.REQUIRED:
                continue
            state, why = self.datasets.get(dataset, ("ok", ""))
            if state != "ok":
                blocking.append(f"{dataset}: {why}")
        return not blocking, blocking


def _evaluate(r: dict[str, Any], at: datetime) -> FixtureGate:
    g = FixtureGate(int(r["provider_fixture_id"]), f"{r['competition']} {r['season']}", r["kickoff_at"])
    g.datasets["fixtures"] = ("ok", "")
    history = min(int(r["home_history"] or 0), int(r["away_history"] or 0))
    g.datasets["results"] = ("ok", "") if history >= MIN_HISTORY else \
        ("missing", f"a side has {history} scored matches in two years (needs {MIN_HISTORY})")
    rated = [r["home_rated"], r["away_rated"]]
    if all(x is not None for x in rated):
        g.datasets["elo"] = ("ok", "")
    else:
        g.datasets["elo"] = ("missing", "a side has no Elo rating before kick-off")
    detail = min(int(r["home_detail"] or 0), int(r["away_detail"] or 0))
    if r["cov_stats"] is False:
        g.datasets["match_detail"] = (Need.UNAVAILABLE_BY_PROVIDER, "the provider publishes no match statistics here")
    elif detail >= MIN_DETAIL_HISTORY:
        g.datasets["match_detail"] = ("ok", "")
    else:
        g.datasets["match_detail"] = ("missing", f"a side has shot data for {detail} matches (needs "
                                                 f"{MIN_DETAIL_HISTORY})")
    state, why = price_state(kickoff=r["kickoff_at"], at=at, last_capture=r["last_capture"],
                             last_asked=r["last_asked"], covered=r["cov_odds"])
    if state is Freshness.UNAVAILABLE:
        g.datasets["odds_prematch"] = (Need.UNAVAILABLE_BY_PROVIDER, why)
    elif r["last_capture"] is None:
        g.datasets["odds_prematch"] = ("missing", "not priced yet" if state is Freshness.FRESH else why)
    elif state is Freshness.STALE:
        g.datasets["odds_prematch"] = ("missing", why)
    elif int(r["bookmakers"] or 0) < MIN_BOOKMAKERS:
        g.datasets["odds_prematch"] = ("missing", f"{int(r['bookmakers'] or 0)} bookmaker(s) in the newest capture")
    else:
        g.datasets["odds_prematch"] = ("ok", "")
    return g


@dataclass
class GateSummary:
    horizon_hours: int
    fixtures: int = 0
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"horizon_hours": self.horizon_hours, "fixtures": self.fixtures, "by_model": self.by_model,
                "needs": {m: {d: n.value for d, n in needs.items()} for m, needs in MODEL_NEEDS.items()}}


def evaluate(conn: psycopg.Connection, *, at: datetime, horizon_hours: int = 72) -> tuple[GateSummary,
                                                                                          list[FixtureGate]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GATE_SQL, {"at": at, "hours": horizon_hours})
        rows = cur.fetchall()
    gates = [_evaluate(r, at) for r in rows]
    summary = GateSummary(horizon_hours, len(gates))
    for model in MODEL_NEEDS:
        reasons: Counter[str] = Counter()
        passing = 0
        for g in gates:
            ok, blocking = g.passes(model)
            passing += ok
            for b in blocking:
                reasons[b.split(":", 1)[0]] += 1
        summary.by_model[model] = {"pass": passing, "blocked": len(gates) - passing,
                                   "blocked_by": dict(reasons.most_common())}
    return summary, gates

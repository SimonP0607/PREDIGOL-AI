"""Historical validation (GATE C): which played matches a model may learn from or be judged on.

Every finished match gets one state, recomputed from the data each run (rule version
``historical-validation-v1``; nothing is deleted, and ``failed`` names every rule a match
failed):

  INGESTED             stored, but no result row yet (a result awaited beats a wrong one)
  QUARANTINED          fails an integrity rule - excluded from every model and backtest:
                         provider_duplicate        the same pairing twice within 36 hours
                         halftime_exceeds_score    more goals at half-time than at 90 minutes
                         penalties_without_level   decided on penalties after an unlevel score
                         no_regulation_score       an extra-time match with no 90-minute score
                         finished_in_future        finished, with a kick-off still to come
  VALIDATED            passes every integrity rule
  HISTORICAL_APPROVED  validated, rated by Elo, and in a competition-season whose data score
                       class is MODEL_READY or PARTIAL

Each competition-season with finished matches gets a data score from the shares of its
finished matches that have a result, pass integrity, have team statistics, line-ups, a
market price (captured, read after the match, or from football-data.co.uk) and an Elo
rating, and a class:

  MODEL_READY   results >= 95%, integrity >= 98%, prices >= 60%, Elo >= 95%, >= 50 matches:
                train on it and judge against the market
  PARTIAL       results >= 95%, integrity >= 98%, >= 30 matches: train on it; too few prices
                (or ratings) to judge against the market
  PRODUCT_ONLY  results >= 80%: show it, do not learn from it
  INSUFFICIENT  fewer than 10 finished matches, or results < 80%

No provider request; a few set-based queries over the whole history.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

RULE_VERSION = "historical-validation-v1"
HARD_RULES = ("provider_duplicate", "halftime_exceeds_score", "penalties_without_level", "no_regulation_score",
              "finished_in_future")
SOFT_RULES = ("no_result", "not_rated", "competition_not_fit")
WEIGHTS = {"results": 0.35, "integrity": 0.15, "stats": 0.15, "lineups": 0.05, "odds": 0.20, "elo": 0.10}
FIT_CLASSES = ("MODEL_READY", "PARTIAL")

FLAGS_SQL = """
CREATE TEMP TABLE hv_fixtures ON COMMIT DROP AS
WITH dup AS (
    SELECT a.id FROM core.fixtures a
      JOIN core.fixtures b ON b.id <> a.id AND b.home_team_id = a.home_team_id AND b.away_team_id = a.away_team_id
                          AND abs(extract(epoch FROM b.kickoff_at - a.kickoff_at)) < 36 * 3600
     WHERE a.status_group = 'finished' AND b.status_group NOT IN ('cancelled', 'postponed')
), stats AS (
    SELECT DISTINCT fixture_id FROM core.fixture_team_stats WHERE shots IS NOT NULL
), lineups AS (
    SELECT DISTINCT fixture_id FROM core.fixture_lineups
), priced AS (
    SELECT DISTINCT fixture_id FROM market.final_prematch_odds
    UNION SELECT DISTINCT fixture_id FROM market.historical_odds
    UNION SELECT DISTINCT fixture_id FROM market.odds_snapshots WHERE source = 'prematch'
), rated AS (
    SELECT DISTINCT fixture_id FROM features.elo_ratings
)
SELECT f.id AS fixture_id, f.competition_season_id AS cs,
       r.fixture_id IS NOT NULL AS has_result,
       f.id IN (SELECT id FROM dup) AS provider_duplicate,
       COALESCE(r.ht_goals_home > r.reg_goals_home OR r.ht_goals_away > r.reg_goals_away, false)
           AS halftime_exceeds_score,
       COALESCE(upper(f.status_short) = 'PEN' AND r.goals_home <> r.goals_away, false) AS penalties_without_level,
       COALESCE(upper(f.status_short) IN ('AET', 'PEN') AND r.ft_goals_home IS NULL AND r.et_goals_home IS NULL,
                false) AS no_regulation_score,
       f.kickoff_at > {at} AS finished_in_future,
       s.fixture_id IS NOT NULL AS has_stats,
       l.fixture_id IS NOT NULL AS has_lineups,
       p.fixture_id IS NOT NULL AS has_price,
       e.fixture_id IS NOT NULL AS is_rated
  FROM core.fixtures f
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
  LEFT JOIN stats s ON s.fixture_id = f.id
  LEFT JOIN lineups l ON l.fixture_id = f.id
  LEFT JOIN priced p ON p.fixture_id = f.id
  LEFT JOIN rated e ON e.fixture_id = f.id
 WHERE f.status_group = 'finished'
"""

AGGREGATE_SQL = """
SELECT cs, count(*) AS finished,
       count(*) FILTER (WHERE has_result) AS results,
       count(*) FILTER (WHERE provider_duplicate OR halftime_exceeds_score OR penalties_without_level
                          OR no_regulation_score OR finished_in_future) AS quarantined,
       count(*) FILTER (WHERE has_stats) AS stats,
       count(*) FILTER (WHERE has_lineups) AS lineups,
       count(*) FILTER (WHERE has_price) AS odds,
       count(*) FILTER (WHERE is_rated) AS elo
  FROM hv_fixtures GROUP BY cs
"""

WRITE_SQL = """
INSERT INTO analytics.fixture_validation (fixture_id, state, rule_version, failed, validated_at)
SELECT h.fixture_id,
       CASE WHEN h.provider_duplicate OR h.halftime_exceeds_score OR h.penalties_without_level
                 OR h.no_regulation_score OR h.finished_in_future THEN 'QUARANTINED'
            WHEN NOT h.has_result THEN 'INGESTED'
            WHEN h.is_rated AND s.class = ANY(%(fit)s) THEN 'HISTORICAL_APPROVED'
            ELSE 'VALIDATED' END,
       %(version)s,
       to_jsonb(array_remove(ARRAY[
           CASE WHEN h.provider_duplicate THEN 'provider_duplicate' END,
           CASE WHEN h.halftime_exceeds_score THEN 'halftime_exceeds_score' END,
           CASE WHEN h.penalties_without_level THEN 'penalties_without_level' END,
           CASE WHEN h.no_regulation_score THEN 'no_regulation_score' END,
           CASE WHEN h.finished_in_future THEN 'finished_in_future' END,
           CASE WHEN NOT h.has_result THEN 'no_result' END,
           CASE WHEN NOT h.is_rated THEN 'not_rated' END,
           CASE WHEN s.class IS NULL OR NOT s.class = ANY(%(fit)s) THEN 'competition_not_fit' END
       ], NULL)),
       %(at)s
  FROM hv_fixtures h LEFT JOIN analytics.competition_data_scores s ON s.competition_season_id = h.cs
ON CONFLICT (fixture_id) DO UPDATE SET state = EXCLUDED.state, rule_version = EXCLUDED.rule_version,
       failed = EXCLUDED.failed, validated_at = EXCLUDED.validated_at
"""


@dataclass(frozen=True, slots=True)
class SeasonScore:
    competition_season_id: int
    finished: int
    components: dict[str, float]
    score: float
    klass: str
    reasons: tuple[str, ...]
    quarantined: int


def classify(finished: int, components: dict[str, float]) -> tuple[str, tuple[str, ...]]:
    """The class a competition-season's data earns, and every threshold it missed."""
    r, i, o, e = components["results"], components["integrity"], components["odds"], components["elo"]
    if finished < 10 or r < 0.80:
        return "INSUFFICIENT", tuple(x for x in (
            f"{finished} finished matches (needs 10)" if finished < 10 else "",
            f"results {r:.0%} (needs 80%)" if r < 0.80 else "") if x)
    missed: list[str] = []
    if r < 0.95:
        missed.append(f"results {r:.0%} (needs 95%)")
    if i < 0.98:
        missed.append(f"integrity {i:.0%} (needs 98%)")
    if finished < 30:
        missed.append(f"{finished} finished matches (needs 30)")
    if missed:
        return "PRODUCT_ONLY", tuple(missed)
    market: list[str] = []
    if o < 0.60:
        market.append(f"prices {o:.0%} (needs 60% to judge against the market)")
    if e < 0.95:
        market.append(f"Elo {e:.0%} (needs 95%)")
    if finished < 50:
        market.append(f"{finished} finished matches (needs 50)")
    return ("PARTIAL", tuple(market)) if market else ("MODEL_READY", ())


def score_of(row: dict[str, Any]) -> SeasonScore:
    n = int(row["finished"])
    q = int(row["quarantined"])
    comp = {
        "results": int(row["results"]) / n, "integrity": 1 - q / n, "stats": int(row["stats"]) / n,
        "lineups": int(row["lineups"]) / n, "odds": int(row["odds"]) / n, "elo": int(row["elo"]) / n,
    }
    klass, reasons = classify(n, comp)
    score = sum(WEIGHTS[k] * v for k, v in comp.items())
    return SeasonScore(int(row["cs"]), n, {k: round(v, 4) for k, v in comp.items()}, round(score, 4), klass,
                       reasons, q)


@dataclass
class ValidationReport:
    fixtures: int = 0
    states: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    classes: dict[str, int] = field(default_factory=dict)
    seasons: int = 0


def validate_history(conn: psycopg.Connection[Any], *, at: datetime) -> ValidationReport:
    """Recompute every finished match's state and every competition-season's score, in one
    transaction (committed by the caller's connection on success)."""
    report = ValidationReport()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL work_mem = '256MB'")
        # A utility statement takes no bound parameters: the instant is composed in as a literal.
        cur.execute(sql.SQL(FLAGS_SQL).format(at=sql.Literal(at)))
        cur.execute(AGGREGATE_SQL)
        scores = [score_of(r) for r in cur.fetchall()]
        cur.executemany(
            "INSERT INTO analytics.competition_data_scores (competition_season_id, computed_at, rule_version, class, "
            "score, finished, approved, quarantined, components, reasons) VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, "
            "%s) ON CONFLICT (competition_season_id) DO UPDATE SET computed_at = EXCLUDED.computed_at, "
            "rule_version = EXCLUDED.rule_version, class = EXCLUDED.class, score = EXCLUDED.score, "
            "finished = EXCLUDED.finished, quarantined = EXCLUDED.quarantined, components = EXCLUDED.components, "
            "reasons = EXCLUDED.reasons",
            [(s.competition_season_id, at, RULE_VERSION, s.klass, s.score, s.finished, s.quarantined,
              Jsonb(s.components), Jsonb(list(s.reasons))) for s in scores])
        cur.execute(WRITE_SQL, {"at": at, "version": RULE_VERSION, "fit": list(FIT_CLASSES)})
        cur.execute("UPDATE analytics.competition_data_scores s SET approved = a.n FROM ("
                    "SELECT h.cs, count(*) FILTER (WHERE v.state = 'HISTORICAL_APPROVED') AS n FROM hv_fixtures h "
                    "JOIN analytics.fixture_validation v ON v.fixture_id = h.fixture_id GROUP BY h.cs) a "
                    "WHERE s.competition_season_id = a.cs")
        cur.execute("SELECT v.state, count(*) AS n FROM analytics.fixture_validation v "
                    "JOIN hv_fixtures h ON h.fixture_id = v.fixture_id GROUP BY 1")
        report.states = {str(r["state"]): int(r["n"]) for r in cur.fetchall()}
        cur.execute("SELECT f.rule, count(*) AS n FROM analytics.fixture_validation v "
                    "JOIN hv_fixtures h ON h.fixture_id = v.fixture_id, jsonb_array_elements_text(v.failed) AS f(rule) "
                    "GROUP BY 1")
        report.failed = {str(r["rule"]): int(r["n"]) for r in cur.fetchall()}
    report.fixtures = sum(report.states.values())
    report.seasons = len(scores)
    report.classes = dict(Counter(s.klass for s in scores))
    return report


JOB = "historical_validation"


def run_validation(conn: psycopg.Connection[Any], *, at: datetime) -> ValidationReport:
    """validate_history inside its own ledger run, committed on success."""
    from fbi.ingestion.ledger import RunCounters, RunLedger

    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"rule_version": RULE_VERSION}, scheduled_for=at)
    counters = RunCounters()
    report = ValidationReport()
    try:
        report = validate_history(conn, at=at)
        conn.commit()
        counters.rows_updated = report.fixtures
        counters.rows_normalized = report.seasons
    finally:
        ledger.close(run_id, counters, notes=(
            f"{RULE_VERSION}: {report.fixtures:,} finished matches - "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(report.states.items()))
            + f"; {report.seasons:,} competition-seasons - "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(report.classes.items()))))
    return report

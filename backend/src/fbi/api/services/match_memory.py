"""MATCH INTELLIGENCE MEMORY: every match PrediGol looked at, before and after, searchable the way the owner asks -
by team, league, coach, player, market, odds band and model (Admin -> IA e investigación -> Memoria).

One row per match, built from what is already stored and never duplicated into another table (the memory is the
records themselves, read together, so nothing can drift out of sync):

  BEFORE  the AI's newest brief before kick-off (its summary, data quality, uncertainty), the AI's last decisions
          on the match's selections, and the shadow picks (markets, models, odds taken);
  AFTER   the 90-minute score, how the picks settled (won, lost, P&L), the post-mortems' classes and how the wins
          were judged (earned or lucky), the memory events written about it.

What is a FACT (a stored record), a STATISTICAL PATTERN (``ai.memory_events`` / ``fbi.ai.patterns``, three standard
errors and a minimum sample) and an AI HYPOTHESIS (``analytics.research_hypotheses``) is kept apart: this view
returns facts; the patterns and hypotheses live in their own tables and screens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Envelope, listing
from fbi.api.repositories import Conn, fetch_all
from fbi.core.clock import now as clock_now

ODDS_BANDS: dict[str, tuple[float, float]] = {
    "1.20-1.49": (1.20, 1.50), "1.50-1.79": (1.50, 1.80), "1.80-2.19": (1.80, 2.20),
    "2.20-2.99": (2.20, 3.00), "3.00-4.99": (3.00, 5.00), "5.00+": (5.00, 1000.0),
}
"""The owner's odds bands (F12)."""


class MemoryFilters(Contract):
    team: str | None = None
    competition: str | None = None
    coach: str | None = None
    player: str | None = None
    market: str | None = None
    odds_band: str | None = None
    model: str | None = None


class MatchMemory(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_short: str
    competition: str
    home: str
    away: str
    home_coach: str | None
    away_coach: str | None
    score_home: int | None
    score_away: int | None
    brief_summary: str | None = Field(description="The AI's newest brief before kick-off (BEFORE).")
    brief_quality: str | None
    brief_uncertainty: str | None
    ai_decisions: dict[str, int] = Field(description="The AI's last decision per selection, counted.")
    selections: int = Field(description="Shadow selections made before kick-off (one per selection and model).")
    markets: list[str]
    models: list[str]
    won: int
    lost: int
    pnl_units: float | None
    postmortem_classes: dict[str, int]
    win_quality: dict[str, int]
    memory_events: int


SQL = """
WITH base AS (
    SELECT f.id, f.kickoff_at, f.status_short, c.name AS competition, th.name AS home, ta.name AS away,
           lh.coach_name AS home_coach, la.coach_name AS away_coach, r.reg_goals_home, r.reg_goals_away
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.teams th ON th.id = f.home_team_id
      JOIN core.teams ta ON ta.id = f.away_team_id
      LEFT JOIN LATERAL (SELECT coach_name FROM core.fixture_lineups l WHERE l.fixture_id = f.id
                          AND l.team_side = 'home' ORDER BY l.fetched_at DESC LIMIT 1) lh ON true
      LEFT JOIN LATERAL (SELECT coach_name FROM core.fixture_lineups l WHERE l.fixture_id = f.id
                          AND l.team_side = 'away' ORDER BY l.fetched_at DESC LIMIT 1) la ON true
      LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.kickoff_at <= %(at)s
       AND (EXISTS (SELECT 1 FROM ai.match_packets p WHERE p.fixture_id = f.id)
            OR EXISTS (SELECT 1 FROM picks.picks p WHERE p.fixture_id = f.id))
       AND (%(team)s::text IS NULL OR th.name ILIKE %(team)s OR ta.name ILIKE %(team)s)
       AND (%(competition)s::text IS NULL OR c.name ILIKE %(competition)s)
       AND (%(coach)s::text IS NULL OR lh.coach_name ILIKE %(coach)s OR la.coach_name ILIKE %(coach)s)
       AND (%(player)s::text IS NULL OR EXISTS (
            SELECT 1 FROM core.fixture_lineup_players lp WHERE lp.fixture_id = f.id AND lp.player_name ILIKE %(player)s))
       AND (%(market)s::text IS NULL OR EXISTS (
            SELECT 1 FROM picks.picks p WHERE p.fixture_id = f.id AND p.market_key = %(market)s))
       AND (%(lo)s::numeric IS NULL OR EXISTS (
            SELECT 1 FROM picks.picks p WHERE p.fixture_id = f.id AND p.market_odds >= %(lo)s AND p.market_odds < %(hi)s))
       AND (%(model)s::text IS NULL OR EXISTS (
            SELECT 1 FROM picks.picks p JOIN models.model_versions v ON v.id = p.model_version_id
              JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = f.id AND m.name = %(model)s))
     ORDER BY f.kickoff_at DESC
     LIMIT %(limit)s
), last_pick AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, p.model_version_id)
           p.id, p.fixture_id, p.market_key, m.name AS model
      FROM picks.picks p JOIN base b ON b.id = p.fixture_id
      JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id
     WHERE p.created_at < b.kickoff_at
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, p.model_version_id, p.created_at DESC
)
SELECT b.*,
       (SELECT jsonb_build_object('summary', mb.content->>'summary', 'quality', mb.data_quality,
                                  'uncertainty', mb.uncertainty)
          FROM ai.match_briefs mb WHERE mb.fixture_id = b.id AND mb.created_at < b.kickoff_at AND mb.status = 'ok'
         ORDER BY mb.created_at DESC LIMIT 1) AS brief,
       (SELECT COALESCE(jsonb_object_agg(d.decision, d.n), '{}'::jsonb) FROM (
            SELECT x.decision, count(*) AS n FROM (
                SELECT DISTINCT ON (r.market_key, r.selection, r.line) r.decision
                  FROM ai.pick_reviews r WHERE r.fixture_id = b.id AND r.engine = 'combined'
                   AND r.reviewed_at < b.kickoff_at
                 ORDER BY r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC) x
             GROUP BY x.decision) d) AS decisions,
       (SELECT count(*) FROM last_pick lp WHERE lp.fixture_id = b.id) AS selections,
       (SELECT COALESCE(array_agg(DISTINCT lp.market_key), '{}') FROM last_pick lp WHERE lp.fixture_id = b.id) AS markets,
       (SELECT COALESCE(array_agg(DISTINCT lp.model), '{}') FROM last_pick lp WHERE lp.fixture_id = b.id) AS models,
       (SELECT count(*) FROM last_pick lp JOIN picks.pick_results pr ON pr.pick_id = lp.id
         WHERE lp.fixture_id = b.id AND pr.result_status IN ('win', 'half_win')) AS won,
       (SELECT count(*) FROM last_pick lp JOIN picks.pick_results pr ON pr.pick_id = lp.id
         WHERE lp.fixture_id = b.id AND pr.result_status IN ('loss', 'half_loss')) AS lost,
       (SELECT sum(pr.profit_units) FROM last_pick lp JOIN picks.pick_results pr ON pr.pick_id = lp.id
         WHERE lp.fixture_id = b.id AND pr.result_status <> 'pending') AS pnl,
       (SELECT COALESCE(jsonb_object_agg(k.classification, k.n), '{}'::jsonb) FROM (
            SELECT pm.classification, count(*) AS n FROM ai.pick_postmortems pm
             WHERE pm.fixture_id = b.id AND pm.classification IS NOT NULL GROUP BY 1) k) AS classes,
       (SELECT COALESCE(jsonb_object_agg(w.q, w.n), '{}'::jsonb) FROM (
            SELECT pm.answers->'win_quality'->'data'->>'win_quality' AS q, count(*) AS n FROM ai.pick_postmortems pm
             WHERE pm.fixture_id = b.id AND pm.answers->'win_quality'->'data'->>'win_quality' IS NOT NULL
             GROUP BY 1) w) AS wins,
       (SELECT count(*) FROM ai.memory_events e WHERE e.fixture_id = b.id) AS events
  FROM base b
 ORDER BY b.kickoff_at DESC
"""


def _like(text: str | None) -> str | None:
    return None if not text or not text.strip() else f"%{text.strip()}%"


def search(conn: Conn, f: MemoryFilters, *, limit: int, at: datetime | None = None) -> Envelope[list[MatchMemory]]:
    band = ODDS_BANDS.get(f.odds_band or "")
    rows = fetch_all(conn, SQL, {"at": at or clock_now(),
        "team": _like(f.team), "competition": _like(f.competition), "coach": _like(f.coach),
        "player": _like(f.player), "market": f.market or None, "model": f.model or None,
        "lo": band[0] if band else None, "hi": band[1] if band else None, "limit": limit})
    out = []
    for r in rows:
        brief: dict[str, Any] = r["brief"] or {}
        out.append(MatchMemory(
            fixture_id=r["id"], kickoff_at=r["kickoff_at"], status_short=r["status_short"],
            competition=r["competition"], home=r["home"], away=r["away"], home_coach=r["home_coach"],
            away_coach=r["away_coach"], score_home=r["reg_goals_home"], score_away=r["reg_goals_away"],
            brief_summary=brief.get("summary"), brief_quality=brief.get("quality"),
            brief_uncertainty=brief.get("uncertainty"), ai_decisions=dict(r["decisions"] or {}),
            selections=int(r["selections"] or 0), markets=sorted(r["markets"] or []), models=sorted(r["models"] or []),
            won=int(r["won"] or 0), lost=int(r["lost"] or 0),
            pnl_units=float(r["pnl"]) if r["pnl"] is not None else None,
            postmortem_classes=dict(r["classes"] or {}), win_quality=dict(r["wins"] or {}),
            memory_events=int(r["events"] or 0)))
    return listing(out, empty_reason="No match in the memory matches these filters.", total=len(out), limit=limit,
                   offset=0)

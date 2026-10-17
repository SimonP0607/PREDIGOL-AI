"""Whether a side is a national team or a club - decided from the competitions it plays, not from the provider's
flag alone (migration 0060 says why). A derived table, recomputed in seconds from the stored fixtures."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from fbi.catalog.scopes import FRIENDLY_LEAGUES

RULE_VERSION = "team-kind-1"

REFRESH_SQL = """
WITH plays AS (
    SELECT t.id AS team_id,
           count(*) FILTER (WHERE c.entity_scope = 'club' AND NOT (c.provider_league_id = ANY(%(friendly)s)))
               AS club_comp,
           count(*) FILTER (WHERE c.entity_scope = 'national_team') AS nat,
           count(*) FILTER (WHERE c.entity_scope = 'club' AND c.provider_league_id = ANY(%(friendly)s)) AS club_friendly
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
     GROUP BY t.id),
kind AS (
    SELECT t.id AS team_id, t.is_national AS provider_national,
           coalesce(p.club_comp, 0) AS club_comp, coalesce(p.nat, 0) AS nat,
           coalesce(p.club_friendly, 0) AS club_friendly
      FROM core.teams t LEFT JOIN plays p ON p.team_id = t.id)
INSERT INTO core.team_kind (team_id, is_national, basis, provider_national, competitive_club_matches, national_matches,
                            club_friendly_matches, rule_version, refreshed_at)
SELECT team_id,
       CASE WHEN club_comp > 0 THEN false WHEN nat > 0 AND club_friendly = 0 THEN true ELSE provider_national END,
       CASE WHEN club_comp > 0 THEN 'plays competitive club football'
            WHEN nat > 0 AND club_friendly = 0 THEN 'plays only national-team competitions'
            WHEN provider_national IS NOT NULL THEN 'the provider''s flag'
            ELSE 'unknown' END,
       provider_national, club_comp, nat, club_friendly, %(version)s, %(at)s
  FROM kind
ON CONFLICT (team_id) DO UPDATE SET
       is_national = EXCLUDED.is_national, basis = EXCLUDED.basis, provider_national = EXCLUDED.provider_national,
       competitive_club_matches = EXCLUDED.competitive_club_matches, national_matches = EXCLUDED.national_matches,
       club_friendly_matches = EXCLUDED.club_friendly_matches, rule_version = EXCLUDED.rule_version,
       refreshed_at = EXCLUDED.refreshed_at
 WHERE (core.team_kind.is_national, core.team_kind.basis, core.team_kind.provider_national,
        core.team_kind.competitive_club_matches, core.team_kind.national_matches,
        core.team_kind.club_friendly_matches, core.team_kind.rule_version)
       IS DISTINCT FROM
       (EXCLUDED.is_national, EXCLUDED.basis, EXCLUDED.provider_national, EXCLUDED.competitive_club_matches,
        EXCLUDED.national_matches, EXCLUDED.club_friendly_matches, EXCLUDED.rule_version)
"""

IS_NATIONAL = "COALESCE(k.is_national, t.is_national, false)"
"""The flag every product query uses: PrediGol's classification, the provider's where there is none yet."""


def refresh_team_kind(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Rows written (new or changed). The caller commits (the worker's connection does on exit)."""
    with conn.cursor() as cur:
        cur.execute(REFRESH_SQL, {"friendly": sorted(FRIENDLY_LEAGUES), "version": RULE_VERSION, "at": at})
        return max(cur.rowcount, 0)

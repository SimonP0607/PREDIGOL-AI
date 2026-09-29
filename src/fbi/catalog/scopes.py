"""Decide what a competition actually IS, from evidence rather than from two fields.

``classify()`` in from_raw reads the provider's ``league_type`` and ``country``, which
determine league-versus-cup and domestic-versus-not. They do not determine who plays:
the UEFA Champions League and the World Cup are both ``Cup`` with country ``World``, so
a rule built on those two fields calls the World Cup club football. It did - twenty-odd
national-team competitions were catalogued as continental club competitions with the
same rating weight as a Champions League tie.

The provider does publish the missing fact, on the team rather than the competition:
``/teams`` returns ``national: true``. So this module decides from the teams that
actually appear in a competition's fixtures, and where no team is known yet it records
an issue and changes nothing. An unresolved competition is visible in
audit.open_quality_issues; it is not quietly given a plausible value.

Friendlies are a separate problem with no evidence to appeal to. The provider marks them
only by name, and a rule that reads names is the drift this module exists to undo - so
the three ids observed on this account are pinned, with the date, and anything the
provider adds later shows up as an unpinned competition rather than being guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.quality.issues import EntityType, IssueRegistry, inconsistency, unknown_entity

log = structlog.get_logger(__name__)

FRIENDLY_LEAGUES: frozenset[int] = frozenset({10, 666, 667})
"""Friendlies, Friendlies Women, Friendlies Clubs - the provider's friendly competitions
as listed for this account on 2026-09-29 (one /leagues call, raw.league_coverage).

A friendly result must not move a rating, and the provider gives no flag that says a
competition is friendly. Pinning the ids keeps the judgement reviewable: re-check with
``SELECT provider_league_id, league_name FROM raw.league_coverage WHERE league_name
ILIKE '%friendl%'`` after a coverage refresh, and add what is new deliberately.
"""

NATIONAL_SHARE = Decimal("0.80")
"""How much of a competition's field must be national teams to call it one. Not 1.0:
a qualifying group can contain a provider record that is not flagged, and a single
unflagged team should not leave the World Cup classified as club football."""

CLUB_SHARE = Decimal("0.20")
"""Below this it is club football. Between the two, the evidence disagrees with itself
and the competition is left alone with an issue recorded."""


@dataclass
class ScopeReport:
    resolved_national: list[str] = field(default_factory=list)
    resolved_club: list[str] = field(default_factory=list)
    friendlies_weighted_zero: list[str] = field(default_factory=list)
    no_evidence: list[str] = field(default_factory=list)
    contradictory: list[str] = field(default_factory=list)
    unchanged: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"resolved_national": len(self.resolved_national),
                "resolved_club": len(self.resolved_club),
                "friendlies_weighted_zero": len(self.friendlies_weighted_zero),
                "no_evidence": len(self.no_evidence),
                "contradictory": len(self.contradictory),
                "unchanged": self.unchanged}


EVIDENCE_SQL = """
WITH participants AS (
    -- /teams?league&season says directly which teams are in a competition-season, so
    -- membership is the evidence of record. Fixtures are the fallback for a season whose
    -- squads were never fetched, and they are also the only evidence for a competition
    -- that is out of season right now: 34 of the tracked 124 had no fixture inside the
    -- sync horizon, which is exactly why membership had to be read as well.
    SELECT s.competition_id, m.team_id
      FROM core.team_season_memberships m
      JOIN core.competition_seasons s ON s.id = m.competition_season_id
    UNION
    SELECT s.competition_id, f.home_team_id
      FROM core.fixtures f JOIN core.competition_seasons s ON s.id = f.competition_season_id
    UNION
    SELECT s.competition_id, f.away_team_id
      FROM core.fixtures f JOIN core.competition_seasons s ON s.id = f.competition_season_id
)
SELECT c.id,
       c.provider_league_id,
       c.name,
       c.country,
       c.type,
       c.entity_scope,
       c.competition_type,
       c.elo_weight,
       count(DISTINCT t.id)                              AS teams_seen,
       count(DISTINCT t.id) FILTER (WHERE t.is_national) AS national_seen
  FROM core.competitions c
  LEFT JOIN participants p ON p.competition_id = c.id
  LEFT JOIN core.teams t   ON t.id = p.team_id
 WHERE (%(only_tracked)s IS FALSE OR c.is_tracked)
 GROUP BY c.id, c.provider_league_id, c.name, c.country, c.type, c.entity_scope,
          c.competition_type, c.elo_weight
 ORDER BY c.provider_league_id
"""

UPDATE_SQL = """
UPDATE core.competitions
   SET entity_scope = %(scope)s, competition_type = %(comp_type)s,
       elo_weight = %(elo)s, updated_at = now()
 WHERE id = %(id)s
   AND (entity_scope, competition_type, elo_weight)
       IS DISTINCT FROM (%(scope)s, %(comp_type)s, %(elo)s::numeric)
"""

WORLD = "World"

ELO_WEIGHT: dict[str, str] = {"domestic_league": "1.00", "domestic_cup": "0.80",
                              "continental": "0.90", "international": "0.70"}


def _intended(row: dict[str, Any], *, national: bool) -> tuple[str, str, str]:
    """(entity_scope, competition_type, elo_weight) given who was observed playing."""
    is_world = (row["country"] or "").strip() == WORLD
    if national:
        return "national_team", "international", ELO_WEIGHT["international"]
    if is_world:
        return "club", "continental", ELO_WEIGHT["continental"]
    kind = "domestic_cup" if row["type"] == "cup" else "domestic_league"
    return "club", kind, ELO_WEIGHT[kind]


def resolve_scopes(
    conn: psycopg.Connection,
    *,
    only_tracked: bool = True,
    run_id: int | None = None,
    apply: bool = True,
) -> ScopeReport:
    """Correct entity_scope, competition_type and elo_weight from observed teams.

    A competition with no team on record is reported and left alone: the provider's two
    fields cannot decide it and neither can this function without ``/teams``.
    """
    report = ScopeReport()
    registry = IssueRegistry(conn)
    issues = []

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(EVIDENCE_SQL, {"only_tracked": only_tracked})
        rows = cur.fetchall()

        for row in rows:
            league_id, label = int(row["provider_league_id"]), f"{row['provider_league_id']} {row['name']}"

            if league_id in FRIENDLY_LEAGUES:
                # Competitive weight of a friendly is zero whoever plays it. The scope
                # still comes from evidence, so this only pins the weight.
                seen, national = int(row["teams_seen"]), int(row["national_seen"])
                scope = row["entity_scope"]
                if seen:
                    scope = "national_team" if Decimal(national) / Decimal(seen) >= NATIONAL_SHARE \
                        else "club"
                comp_type = "international" if scope == "national_team" else row["competition_type"]
                target = (scope, comp_type, "0.00")
                report.friendlies_weighted_zero.append(label)
            else:
                seen, national = int(row["teams_seen"]), int(row["national_seen"])
                if seen == 0:
                    report.no_evidence.append(label)
                    issues.append(unknown_entity(
                        entity_type=EntityType.COMPETITION,
                        name=f"{row['name']} ({row['country']}): no team on record, so whether it "
                             "is club or national-team football is undecided - needs /teams",
                        provider_entity_id=league_id,
                        run_id=run_id,
                    ))
                    continue
                share = Decimal(national) / Decimal(seen)
                if share >= NATIONAL_SHARE:
                    target = _intended(row, national=True)
                    report.resolved_national.append(label)
                elif share <= CLUB_SHARE:
                    target = _intended(row, national=False)
                    report.resolved_club.append(label)
                else:
                    report.contradictory.append(f"{label}: {national}/{seen} national")
                    issues.append(inconsistency(
                        entity_type=EntityType.COMPETITION,
                        entity_id=int(row["id"]),
                        provider_entity_id=league_id,
                        field_name="entity_scope",
                        observed=f"{national} of {seen} teams flagged national",
                        expected=f"either at least {NATIONAL_SHARE:.0%} national or at most "
                                 f"{CLUB_SHARE:.0%}",
                        detail="a field that is part national teams and part clubs is not "
                               "something this rule can classify; left as catalogued",
                        run_id=run_id,
                    ))
                    continue

            if not apply:
                continue
            cur.execute(UPDATE_SQL, {"id": row["id"], "scope": target[0],
                                     "comp_type": target[1], "elo": target[2]})
            if cur.rowcount == 0:
                report.unchanged += 1

    if issues:
        registry.record_many(issues)
    if apply:
        conn.commit()
    log.info("catalogue.scopes_resolved", apply=apply, **report.as_dict())
    return report

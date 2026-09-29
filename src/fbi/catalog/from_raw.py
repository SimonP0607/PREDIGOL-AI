"""Build the competition catalogue from the coverage we already hold.

``raw.league_coverage`` holds what one ``/leagues`` call returned: 1,247 leagues and
8,746 league-seasons, each with the provider's name, country, type and twelve
coverage flags. Everything ``core.competitions`` and ``core.competition_seasons``
need is in there, so the catalogue can be built for **no provider request at all**.

That is the point. The alternative - a request per league to learn what we already
stored - would spend a thousand requests to re-read a payload on disk, and the rule
is not to repeat a request the RAW store can answer.

Two judgements this module makes, and both are recorded rather than guessed at:

``type``              the provider says ``League`` or ``Cup``. A cup whose country is
                      ``World`` is continental or international rather than domestic,
                      and a competition of national teams is scoped that way - both
                      inferred from the provider's own fields, never from the name.
``elo_weight``        how much a competition's results should move a rating. A
                      friendly is 0; a domestic league is 1; a cup where the sides
                      come from different leagues gets less, because the result says
                      less about either. Defaults only - config may override.

Nothing here invents a season. A league-season that ``/leagues`` did not list does
not get a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

log = structlog.get_logger(__name__)

WORLD = "World"

ELO_WEIGHT: dict[str, str] = {
    "domestic_league": "1.00",
    "domestic_cup": "0.80",
    "continental": "0.90",
    "international": "0.70",
}
"""A cup draws sides from different leagues, so its result says less about either
than a league match does. International fixtures say least about club strength."""


@dataclass
class CatalogueReport:
    competitions_inserted: int = 0
    competitions_updated: int = 0
    seasons_inserted: int = 0
    seasons_updated: int = 0
    tracked: int = 0
    untracked: int = 0
    skipped: list[str] = field(default_factory=list)
    tracked_outside_selection: list[str] = field(default_factory=list)
    """Competitions the pipeline already follows that this run did not select.

    Recorded, never changed. Untracking one stops its odds capture, and a capture
    window that closes unobserved is gone for good - so it is an operator's decision
    with the list in front of them, not a side effect of running the catalogue with a
    partial ``--tiers``.
    """

    def as_dict(self) -> dict[str, Any]:
        return {"competitions_inserted": self.competitions_inserted,
                "competitions_updated": self.competitions_updated,
                "seasons_inserted": self.seasons_inserted, "seasons_updated": self.seasons_updated,
                "tracked": self.tracked, "untracked": self.untracked,
                "skipped": self.skipped[:10],
                "tracked_outside_selection": self.tracked_outside_selection[:10]}


def classify(league_type: str | None, country: str | None) -> tuple[str, str, str]:
    """(type, entity_scope, competition_type) from the provider's own two fields.

    Never from the name: a competition called "Cup" in one language is a league in
    another, and guessing from strings is how a catalogue drifts.
    """
    raw_type = (league_type or "").strip().lower()
    is_world = (country or "").strip() == WORLD
    if raw_type == "cup":
        if is_world:
            return "cup", "club", "continental"
        return "cup", "club", "domestic_cup"
    if is_world:
        # A "League" with no country is an international competition of national teams
        # in this provider's model (World Cup qualifying groups, Nations League).
        return "league", "national_team", "international"
    return "league", "club", "domestic_league"


UPSERT_COMPETITION = """
INSERT INTO core.competitions
    (provider_league_id, name, country, type, entity_scope, competition_type, elo_weight, tier)
VALUES (%(league_id)s, %(name)s, %(country)s, %(type)s, %(scope)s, %(comp_type)s, %(elo)s, %(tier)s)
ON CONFLICT (provider_league_id) DO UPDATE SET
    name = EXCLUDED.name,
    country = COALESCE(EXCLUDED.country, core.competitions.country),
    type = EXCLUDED.type,
    entity_scope = EXCLUDED.entity_scope,
    competition_type = EXCLUDED.competition_type,
    tier = EXCLUDED.tier,
    updated_at = now()
RETURNING id, (xmax = 0) AS was_insert
"""

UPSERT_SEASON = """
INSERT INTO core.competition_seasons
    (competition_id, season, start_date, end_date, is_current, has_odds, has_fixtures, listed_at)
VALUES (%(competition_id)s, %(season)s, %(start)s, %(end)s, %(is_current)s, %(has_odds)s,
        %(has_fixtures)s, %(observed_at)s)
ON CONFLICT (competition_id, season) DO UPDATE SET
    start_date = COALESCE(EXCLUDED.start_date, core.competition_seasons.start_date),
    end_date = COALESCE(EXCLUDED.end_date, core.competition_seasons.end_date),
    is_current = EXCLUDED.is_current,
    has_odds = EXCLUDED.has_odds,
    has_fixtures = EXCLUDED.has_fixtures,
    listed_at = EXCLUDED.listed_at
RETURNING (xmax = 0) AS was_insert
"""

COVERAGE_SQL = """
SELECT provider_league_id, season, league_name, country, league_type, is_current,
       start_date, end_date, odds, observed_at,
       (events OR lineups OR statistics_fixtures OR statistics_players OR standings) AS any_detail
  FROM raw.league_coverage
 WHERE provider = %(provider)s AND provider_league_id = ANY(%(leagues)s)
 ORDER BY provider_league_id, season
"""


def build_catalogue(
    conn: psycopg.Connection,
    *,
    tiers: dict[int, int],
    tracked: set[int] | None = None,
    provider: str = "api_football",
) -> CatalogueReport:
    """Create or update the selected competitions and every season the provider listed.

    ``tiers`` maps provider league id -> tier, which is the selection's output.
    ``tracked`` is which of them the live pipeline should follow; when None, every
    selected competition is tracked, because a competition worth migrating is worth
    capturing prices for.
    """
    report = CatalogueReport()
    leagues = sorted(tiers)
    if not leagues:
        return report
    follow = set(leagues) if tracked is None else tracked

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE_SQL, {"provider": provider, "leagues": leagues})
        rows = cur.fetchall()

    by_league: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_league.setdefault(int(row["provider_league_id"]), []).append(dict(row))

    with conn.cursor(row_factory=dict_row) as cur:
        for league_id in leagues:
            seasons = by_league.get(league_id)
            if not seasons:
                report.skipped.append(f"league {league_id}: selected but absent from raw.league_coverage")
                continue
            newest = max(seasons, key=lambda s: int(s["season"]))
            kind, scope, comp_type = classify(newest["league_type"], newest["country"])
            cur.execute(UPSERT_COMPETITION, {
                "league_id": league_id,
                "name": newest["league_name"] or f"League {league_id}",
                "country": newest["country"],
                "type": kind,
                "scope": scope,
                "comp_type": comp_type,
                "elo": ELO_WEIGHT[comp_type],
                "tier": tiers[league_id],
            })
            got = cur.fetchone()
            assert got is not None
            competition_id = int(got["id"])
            if got["was_insert"]:
                report.competitions_inserted += 1
            else:
                report.competitions_updated += 1

            for s in seasons:
                cur.execute(UPSERT_SEASON, {
                    "competition_id": competition_id,
                    "season": int(s["season"]),
                    "start": s["start_date"],
                    "end": s["end_date"],
                    "is_current": bool(s["is_current"]),
                    "has_odds": bool(s["odds"]),
                    # The provider does not publish a fixtures flag in this payload;
                    # "any detail at all" is the closest honest proxy, and NULL would
                    # claim less than we know.
                    "has_fixtures": bool(s["any_detail"]) or None,
                    "observed_at": s["observed_at"],
                })
                inserted = cur.fetchone()
                if inserted is not None and inserted["was_insert"]:
                    report.seasons_inserted += 1
                else:
                    report.seasons_updated += 1

        # Only the leagues this run was asked about. Anything else keeps the tracking it
        # has: a run with --tiers 1 must not stop the odds capture of tiers 2-4.
        cur.execute("UPDATE core.competitions SET is_tracked = (provider_league_id = ANY(%s)), "
                    "updated_at = now() WHERE provider_league_id = ANY(%s)",
                    (sorted(follow), leagues))
        cur.execute("SELECT provider_league_id, name FROM core.competitions "
                    "WHERE is_tracked AND NOT (provider_league_id = ANY(%s)) "
                    "ORDER BY provider_league_id", (leagues,))
        report.tracked_outside_selection = [f"{r['provider_league_id']} {r['name']}"
                                            for r in cur.fetchall()]
        cur.execute("SELECT count(*) FILTER (WHERE is_tracked) AS tracked, "
                    "count(*) FILTER (WHERE NOT is_tracked) AS untracked FROM core.competitions")
        counts = cur.fetchone()
        assert counts is not None
        report.tracked, report.untracked = int(counts["tracked"]), int(counts["untracked"])

    conn.commit()
    log.info("catalogue.built", **report.as_dict())
    return report

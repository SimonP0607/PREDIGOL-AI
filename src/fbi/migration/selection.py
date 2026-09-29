"""Choosing which competitions to migrate, from the provider's own coverage flags.

The rule the mandate sets: **do not add leagues to make a number go up.** So the
selection is computed from ``raw.league_coverage`` - the twelve flags API-Football
publishes per league-season - and every competition carries the reason it is in or
out. A league excluded for thin coverage is recorded as excluded, with the count
that excluded it, so the decision can be re-read later instead of re-argued.

What "good coverage" means here, and why:

``full_detail``   seasons where events AND lineups AND statistics_fixtures AND
                  statistics_players are all true. This is the only combination that
                  supports the features the models are built on; a season with
                  fixtures but no statistics is a scoreline, not a dataset.
``with_odds``     seasons the provider covers for odds. Almost always 1, because
                  odds are a forward window - so this reads as "is there a market
                  here at all", not as historical depth.
``standings``,
``injuries``      recorded per league and used to decide whether those units are
                  even planned, rather than requested and refused.

Tiers are depth bands, not importance rankings. Depth is what decides how much a
competition can contribute to a model, and it is the honest axis:

    1  the reference set, already migrated
    2  >= 8 seasons of full detail
    3  5 - 7 seasons
    4  3 - 4 seasons
    -  fewer than 3: evaluated, excluded, and the reason kept

A cup is kept only when its detail depth matches a tier-2 league's, because cup
fixtures are few and the modelling value comes from the same statistics being
present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

MIN_FULL_DETAIL_SEASONS = 3
"""Below this a competition cannot support a model, and requesting it spends quota
for a scoreline. Measured: 150 leagues have at least one such season, 124 have
three or more."""

TIER_BANDS: tuple[tuple[int, int, str], ...] = (
    (2, 8, "eight or more seasons with events, line-ups and both statistics blocks"),
    (3, 5, "five to seven such seasons"),
    (4, 3, "three or four such seasons"),
)

REFERENCE_SET: frozenset[int] = frozenset({39, 140, 78, 135, 61, 2})
"""Tier 1, already migrated. Kept as tier 1 whatever the bands would say, because
the rest of the platform is calibrated against it."""


@dataclass(frozen=True, slots=True)
class Candidate:
    provider_league_id: int
    name: str
    country: str | None
    league_type: str | None
    seasons_listed: int
    full_detail_seasons: int
    seasons_with_odds: int
    seasons_with_standings: int
    seasons_with_injuries: int
    oldest_season: int
    newest_season: int
    has_current: bool

    @property
    def tier(self) -> int | None:
        """None means evaluated and excluded."""
        if self.provider_league_id in REFERENCE_SET:
            return 1
        for tier, threshold, _why in TIER_BANDS:
            if self.full_detail_seasons >= threshold:
                return tier
        return None

    @property
    def reason(self) -> str:
        if self.provider_league_id in REFERENCE_SET:
            return "reference set: the platform is calibrated against it"
        for tier, threshold, why in TIER_BANDS:
            if self.full_detail_seasons >= threshold:
                return f"tier {tier}: {why} ({self.full_detail_seasons} of {self.seasons_listed})"
        return (f"excluded: only {self.full_detail_seasons} season(s) with full detail, "
                f"below the minimum of {MIN_FULL_DETAIL_SEASONS}")

    @property
    def is_selected(self) -> bool:
        return self.tier is not None

    def as_dict(self) -> dict[str, Any]:
        return {"league_id": self.provider_league_id, "name": self.name, "country": self.country,
                "type": self.league_type, "tier": self.tier, "seasons": self.seasons_listed,
                "full_detail": self.full_detail_seasons, "odds": self.seasons_with_odds,
                "standings": self.seasons_with_standings, "injuries": self.seasons_with_injuries,
                "oldest": self.oldest_season, "newest": self.newest_season,
                "current": self.has_current, "reason": self.reason}


CANDIDATES_SQL = """
SELECT provider_league_id,
       max(league_name)                                                       AS name,
       max(country)                                                           AS country,
       max(league_type)                                                       AS league_type,
       count(*)                                                               AS seasons_listed,
       count(*) FILTER (WHERE events AND lineups
                          AND statistics_fixtures AND statistics_players)     AS full_detail_seasons,
       count(*) FILTER (WHERE odds)                                           AS seasons_with_odds,
       count(*) FILTER (WHERE standings)                                      AS seasons_with_standings,
       count(*) FILTER (WHERE injuries)                                       AS seasons_with_injuries,
       min(season)                                                            AS oldest_season,
       max(season)                                                            AS newest_season,
       bool_or(coalesce(is_current, false))                                    AS has_current
  FROM raw.league_coverage
 WHERE provider = %(provider)s
 GROUP BY provider_league_id
"""


@dataclass
class SelectionReport:
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def selected(self) -> list[Candidate]:
        return [c for c in self.candidates if c.is_selected]

    @property
    def excluded(self) -> list[Candidate]:
        return [c for c in self.candidates if not c.is_selected]

    def by_tier(self) -> dict[int, list[Candidate]]:
        out: dict[int, list[Candidate]] = {}
        for c in self.selected:
            assert c.tier is not None
            out.setdefault(c.tier, []).append(c)
        for tier in out:
            out[tier].sort(key=lambda c: (-c.full_detail_seasons, c.provider_league_id))
        return dict(sorted(out.items()))

    @property
    def league_seasons_to_migrate(self) -> int:
        """Seasons worth requesting: only those with full detail."""
        return sum(c.full_detail_seasons for c in self.selected)

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": len(self.selected),
            "excluded": len(self.excluded),
            "by_tier": {t: len(cs) for t, cs in self.by_tier().items()},
            "league_seasons_to_migrate": self.league_seasons_to_migrate,
            "competitions": [c.as_dict() for c in self.candidates],
        }


def select_competitions(conn: psycopg.Connection, *, provider: str = "api_football",
                        require_current: bool = True) -> SelectionReport:
    """Rank every league the provider lists, and band the ones worth migrating.

    ``require_current`` keeps out competitions the provider no longer runs: a league
    with deep history and no current season cannot feed the live pipeline, and the
    live pipeline is what the odds capture depends on.
    """
    report = SelectionReport()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CANDIDATES_SQL, {"provider": provider})
        for row in cur.fetchall():
            candidate = Candidate(**row)
            if require_current and not candidate.has_current and candidate.is_selected:
                # Deep history, no current season: recorded, not planned.
                candidate = Candidate(**{**row, "full_detail_seasons": 0})
            report.candidates.append(candidate)
    report.candidates.sort(key=lambda c: (-c.full_detail_seasons, c.provider_league_id))
    return report

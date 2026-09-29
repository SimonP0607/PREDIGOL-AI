"""Per-dataset completeness, measured from the data rather than from task rows.

    "fixture exists" is NOT proof that "fixture details exist"

and neither is a ``fixtures_season`` task marked done, nor a ``fixture_details``
task whose batch key happens to name the fixture. 1,893 played fixtures had no
detail of any kind while every task row said their seasons were complete.

Everything here answers the planner's real question - WHICH FIXTURES HAVE WE
NEVER FETCHED DETAIL FOR - from ``core.fixture_detail_coverage``, which records
what each payload actually carried. That distinction is what keeps the answer
finite: a dataset the provider does not publish has a row saying so, and asking
for it again would spend quota for ever.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row

DATASETS: tuple[str, ...] = ("events", "lineups", "team_statistics", "player_statistics")

COVERAGE_FLAG_OF_DATASET: dict[str, str] = {
    "events": "events",
    "lineups": "lineups",
    "team_statistics": "statistics_fixtures",
    "player_statistics": "statistics_players",
}
"""Which flag of raw.league_coverage speaks for each dataset. The provider's own
claim about a league-season: ``false`` means a missing block is expected, not a
gap of ours."""


@dataclass(frozen=True, slots=True)
class DatasetCompleteness:
    provider_league_id: int
    season: int
    tier: int | None
    dataset: str
    played: int
    """The denominator: fixtures with status_group = 'finished'."""
    fetched: int
    delivered: int
    with_rows: int
    never_fetched: int
    not_published: int
    provider_claims: bool | None
    """What raw.league_coverage says about this dataset, or None if we have not
    read the coverage for this league-season."""

    @property
    def ratio(self) -> float | None:
        """Fixtures with rows over fixtures played, or None when nothing was
        played. A season with no finished fixtures has no percentage; inventing
        0.0 or 1.0 for it would be a lie either way."""
        return None if self.played == 0 else self.with_rows / self.played

    @property
    def outstanding(self) -> int:
        """What the planner could still usefully request. Excludes what the
        provider has already declined to publish."""
        return self.never_fetched

    @property
    def state(self) -> str:
        if self.played == 0:
            return "nothing_played"
        if self.provider_claims is False:
            return "unsupported"
        if self.never_fetched == self.played:
            return "pending"
        if self.never_fetched:
            return "partial"
        if self.with_rows == self.played:
            return "complete"
        return "delivered_incomplete"

    def as_dict(self) -> dict[str, Any]:
        return {"league": self.provider_league_id, "season": self.season, "tier": self.tier,
                "dataset": self.dataset, "played": self.played, "fetched": self.fetched,
                "delivered": self.delivered, "with_rows": self.with_rows,
                "never_fetched": self.never_fetched, "not_published": self.not_published,
                "provider_claims": self.provider_claims, "ratio": self.ratio, "state": self.state}


def dataset_completeness(
    conn: psycopg.Connection,
    *,
    league_id: int | None = None,
    season: int | None = None,
    tier: int | None = None,
    datasets: Sequence[str] = DATASETS,
) -> list[DatasetCompleteness]:
    """One row per league-season and dataset, from core.detail_completeness."""
    sql = ["SELECT provider_league_id, season, tier, dataset, played, fetched, delivered, with_rows,",
           "       never_fetched, not_published, events, lineups, statistics_fixtures, statistics_players",
           "  FROM core.detail_completeness WHERE dataset = ANY(%s)"]
    params: list[object] = [list(datasets)]
    if league_id is not None:
        sql.append("AND provider_league_id = %s")
        params.append(league_id)
    if season is not None:
        sql.append("AND season = %s")
        params.append(season)
    if tier is not None:
        sql.append("AND tier = %s")
        params.append(tier)
    sql.append("ORDER BY tier NULLS LAST, provider_league_id, season DESC, dataset")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(" ".join(sql), params)
        rows = cur.fetchall()
    out: list[DatasetCompleteness] = []
    for r in rows:
        flag = COVERAGE_FLAG_OF_DATASET[str(r["dataset"])]
        out.append(DatasetCompleteness(
            provider_league_id=int(r["provider_league_id"]), season=int(r["season"]),
            tier=r["tier"], dataset=str(r["dataset"]), played=int(r["played"]),
            fetched=int(r["fetched"]), delivered=int(r["delivered"]), with_rows=int(r["with_rows"]),
            never_fetched=int(r["never_fetched"]), not_published=int(r["not_published"]),
            provider_claims=r[flag],
        ))
    return out


def fixtures_missing_detail(
    conn: psycopg.Connection,
    *,
    league_id: int | None = None,
    season: int | None = None,
    tier: int | None = None,
    datasets: Sequence[str] = DATASETS,
    limit: int | None = None,
) -> list[int]:
    """Provider fixture ids of played fixtures we have NEVER fetched detail for.

    "Never fetched" means no ``core.fixture_detail_coverage`` row for any of the
    datasets asked about - not "the table is empty for it". A fixture whose
    payload arrived without a line-ups block has a row saying so and is NOT
    returned: one request already answered that question, and the answer was no.

    Ordered by kick-off so a partial run leaves a contiguous, explicable gap.
    """
    sql = ["SELECT f.provider_fixture_id FROM core.fixtures f",
           "  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id",
           "  JOIN core.competitions c ON c.id = cs.competition_id",
           " WHERE f.status_group = 'finished'",
           "   AND NOT EXISTS (SELECT 1 FROM core.fixture_detail_coverage cov",
           "                    WHERE cov.fixture_id = f.id AND cov.dataset = ANY(%s))"]
    params: list[object] = [list(datasets)]
    if league_id is not None:
        sql.append("AND c.provider_league_id = %s")
        params.append(league_id)
    if season is not None:
        sql.append("AND cs.season = %s")
        params.append(season)
    if tier is not None:
        sql.append("AND c.tier = %s")
        params.append(tier)
    sql.append("ORDER BY f.kickoff_at, f.provider_fixture_id")
    if limit is not None:
        sql.append("LIMIT %s")
        params.append(limit)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(" ".join(sql), params)
        return [int(r[0]) for r in cur.fetchall()]


@dataclass(frozen=True, slots=True)
class SeasonGap:
    provider_league_id: int
    season: int
    tier: int | None
    played: int
    missing: int

    @property
    def batches(self) -> int:
        """Requests it would take at twenty fixtures per /fixtures?ids= call."""
        return -(-self.missing // 20)


def season_gaps(conn: psycopg.Connection, *, tier: int | None = None) -> list[SeasonGap]:
    """League-seasons with played fixtures whose detail has never been fetched.

    The report the planner bug made impossible to produce: how much is actually
    outstanding, and what it would cost.
    """
    sql = ["SELECT c.provider_league_id, cs.season, c.tier, count(*) AS played,",
           "       count(*) FILTER (WHERE NOT EXISTS (",
           "           SELECT 1 FROM core.fixture_detail_coverage cov WHERE cov.fixture_id = f.id)) AS missing",
           "  FROM core.fixtures f",
           "  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id",
           "  JOIN core.competitions c ON c.id = cs.competition_id",
           " WHERE f.status_group = 'finished'"]
    params: list[object] = []
    if tier is not None:
        sql.append("AND c.tier = %s")
        params.append(tier)
    sql.append("GROUP BY 1, 2, 3 HAVING count(*) FILTER (WHERE NOT EXISTS ("
               "SELECT 1 FROM core.fixture_detail_coverage cov WHERE cov.fixture_id = f.id)) > 0")
    sql.append("ORDER BY c.tier NULLS LAST, 5 DESC, 1, 2")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(" ".join(sql), params)
        return [SeasonGap(int(a), int(b), c, int(d), int(e)) for a, b, c, d, e in cur.fetchall()]

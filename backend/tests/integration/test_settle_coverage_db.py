"""Mi parlay takes a market of the catalogue only where the season records what its rule settles on (plan EA, EA-501; decision of
19-nov-2026), measured on market.fixture_outcomes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.market.rules import RULES_BY_MEASURE
from fbi.market.settle_coverage import MIN_MATCHES, SeasonCoverage, season_coverage

from .conftest import Seed

T0 = datetime(2034, 3, 1, 18, tzinfo=UTC)


def _season(db: psycopg.Connection[Any], seed: Seed, matches: int, with_stats: int) -> tuple[int, int]:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                "VALUES (988001, 'Liga Cobertura', 'league', 'club', 'domestic_league', true) RETURNING id")
    comp = cur.fetchone()[0]  # type: ignore[index]
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id", (comp,))
    cs = cur.fetchone()[0]  # type: ignore[index]
    teams = []
    for i in range(2):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (988100 + i, f"Cob {i}"))
        teams.append(cur.fetchone()[0])  # type: ignore[index]
    for k in range(matches):
        ko = T0 + timedelta(days=k)
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                    "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                    (9881000 + k, cs, teams[0], teams[1], ko))
        fid = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, settled_at) "
                    "VALUES (%s, 1, 0, 1, 0, %s)", (fid, ko + timedelta(hours=2)))
        if k < with_stats:
            for side in ("home", "away"):
                cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, shots_on_target, corners, "
                            "fouls, yellow_cards, red_cards, saves, payload_hash, fetched_at) "
                            "VALUES (%s, %s, 'api-football', 10, 4, 5, 11, 2, 0, 3, %s, %s)",
                            (fid, side, seed.payload_hash, ko + timedelta(hours=3)))
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                "VALUES (9889999, %s, %s, %s, %s) RETURNING id", (cs, teams[0], teams[1], T0 + timedelta(days=200)))
    return cs, cur.fetchone()[0]  # type: ignore[index]


def test_corners_are_covered_where_the_season_records_them(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, upcoming = _season(db, seed, matches=MIN_MATCHES + 2, with_stats=MIN_MATCHES + 2)
    corners = RULES_BY_MEASURE["corners_ft"]
    cov = season_coverage(db, cs, corners)
    assert (cov.finished, cov.with_data) == (MIN_MATCHES + 2, MIN_MATCHES + 2) and cov.enough
    assert SeasonCoverage.of_fixture(db, upcoming).covered(corners)
    assert SeasonCoverage.of_fixture(db, upcoming).covered(RULES_BY_MEASURE["goals_ft"]), "the score is always there"


def test_a_season_without_its_statistics_is_not_covered(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, upcoming = _season(db, seed, matches=20, with_stats=12)
    corners = RULES_BY_MEASURE["corners_ft"]
    assert season_coverage(db, cs, corners).share == 0.6
    assert not SeasonCoverage.of_fixture(db, upcoming).covered(corners)
    assert SeasonCoverage.of_fixture(db, upcoming).covered(RULES_BY_MEASURE["goals_1h"])


def test_too_few_matches_is_not_covered(db: psycopg.Connection[Any], seed: Seed) -> None:
    _cs, upcoming = _season(db, seed, matches=MIN_MATCHES - 1, with_stats=MIN_MATCHES - 1)
    assert not SeasonCoverage.of_fixture(db, upcoming).covered(RULES_BY_MEASURE["corners_ft"])

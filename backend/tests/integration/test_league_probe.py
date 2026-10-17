"""P3: a candidate league is probed before it is tracked - real coverage and internal consistency, three requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.catalog.league_probe import (
    LeagueProbe,
    goals_in_events,
    judge_detail,
    lineups_complete,
    probe_leagues,
)
from fbi.providers.api_football.details import (
    EventRef,
    FixtureDetail,
    LineupPlayerRef,
    LineupRef,
    PlayerStatsRef,
    StandingRef,
    TeamStatsRef,
)
from fbi.providers.api_football.normalize import iter_fixture_results, iter_fixtures
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
LEAGUE, SEASON = 9944, 2026


def goal(fid: int, seq: int, detail: str = "Normal Goal") -> EventRef:
    return EventRef(fid, seq, 10 * seq, None, 1, 100 + seq, None, None, None, "Goal", detail, None)


def lineup(fid: int, team: int, starters: int) -> LineupRef:
    players = tuple(LineupPlayerRef(team * 100 + i, None, i, "M", None, i < starters) for i in range(16))
    return LineupRef(fid, team, "4-4-2", None, None, players)


def detail(fid: int, goals: int, *, starters: int = 11, stats: bool = True, players: int = 28,
           missed: int = 0) -> FixtureDetail:
    events = tuple(goal(fid, i + 1) for i in range(goals)) + tuple(goal(fid, 50 + i, "Missed Penalty")
                                                                    for i in range(missed))
    team_stats = (TeamStatsRef(fid, 1, {"shots_total": 10}), TeamStatsRef(fid, 2, {"shots_total": 7})) if stats else ()
    people = tuple(PlayerStatsRef(fid, 1 + i % 2, 1000 + i, None, {"minutes": 90}) for i in range(players))
    return FixtureDetail(fid, team_stats, events, (lineup(fid, 1, starters), lineup(fid, 2, 11)), people,
                         frozenset({"events", "lineups", "statistics", "players"}))


def test_a_missed_penalty_is_not_a_goal_and_a_lineup_needs_eleven_starters() -> None:
    d = detail(1, 2, missed=1, starters=10)
    assert goals_in_events(d) == 2
    assert not lineups_complete(d)
    assert lineups_complete(detail(2, 0))


def test_the_detail_shares_and_the_goal_check_read_only_regular_time_finishes() -> None:
    probe = LeagueProbe(LEAGUE, SEASON)
    judge_detail(probe, [detail(1, 3), detail(2, 2, stats=False, players=5), detail(3, 4)],
                 {1: ("FT", 2, 1), 2: ("FT", 1, 0), 3: ("AET", 2, 2)})
    assert (probe.sampled, probe.with_team_stats, probe.with_player_stats) == (3, 2, 2)
    assert (probe.regular_time_sampled, probe.goals_match_events) == (2, 1), "an AET finish is not compared"
    assert probe.consistency == 0.5 and probe.data_score == round(10 / 12, 3)
    assert probe.examples == ["fixture 2: score 1-0, 2 goal events"]


def entry(fid: int, status: str, kickoff: datetime, goals: tuple[int | None, int | None]) -> dict[str, Any]:
    return {"fixture": {"id": fid, "date": kickoff.isoformat(), "status": {"short": status}, "venue": {}},
            "league": {"id": LEAGUE, "season": SEASON, "round": "Regular Season - 1"},
            "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}},
            "goals": {"home": goals[0], "away": goals[1]},
            "score": {"halftime": {"home": None, "away": None}, "fulltime": {"home": goals[0], "away": goals[1]},
                      "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}}}


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.body = {"response": [entry(9_944_001, "FT", NOW - timedelta(days=3), (2, 1)),
                                  entry(9_944_002, "FT", NOW - timedelta(days=2), (None, None)),
                                  entry(9_944_003, "NS", NOW + timedelta(days=4), (None, None))]}

    def raw(self, endpoint: str, n: int, body: dict[str, Any] | None = None) -> RawResponse:
        return RawResponse(endpoint=endpoint, params={}, fetched_at=NOW, http_status=200, results_count=1,
                           payload_hash=f"probe-test-{n}", file_path="x", bytes_written=1, body=body or {})

    async def fetch_fixtures(self, *, league_id: int, season: int) -> tuple[list[Any], RawResponse]:
        self.calls.append("/fixtures")
        return list(iter_fixtures(self.body)), self.raw("/fixtures", 1, self.body)

    def parse_results(self, body: dict[str, Any]) -> list[Any]:
        return list(iter_fixture_results(body))

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> tuple[list[Any], RawResponse]:
        self.calls.append(f"/fixtures?ids={provider_fixture_ids}")
        return [detail(9_944_001, 3)], self.raw("/fixtures", 2)

    async def fetch_standings(self, *, league_id: int, season: int) -> tuple[list[Any], RawResponse]:
        self.calls.append("/standings")
        rows = [StandingRef(LEAGUE, SEASON, 1, 1, 3, 1, 1, 0, 0, 2, 1, "W", "League"),
                StandingRef(LEAGUE, SEASON, 2, 2, 0, 1, 0, 0, 1, 1, 2, "L", "League")]
        return rows, self.raw("/standings", 3)


async def test_a_probe_reads_three_answers_and_says_what_the_league_really_serves(migrated_database: str,
                                                                                   seed: Seed) -> None:
    provider = FakeProvider()
    with psycopg.connect(migrated_database) as conn:
        try:
            probes, run_id = await probe_leagues(conn, provider, [(LEAGUE, SEASON)], at=NOW, max_requests=10)
            (p,) = probes
            assert provider.calls == ["/fixtures", "/fixtures?ids=[9944001]", "/standings"], \
                "only finished matches with a readable score are sampled"
            assert (p.requests, p.fixtures, p.finished, p.upcoming, p.unresolved_results) == (3, 3, 2, 1, 1)
            assert (p.sampled, p.goals_match_events, p.consistency, p.data_score) == (1, 1, 1.0, 1.0)
            assert (p.table_rows, p.table_groups, p.table_games) == (2, 1, 1)
            run = conn.execute("SELECT job_type, status, api_calls, payloads_stored FROM raw.ingestion_runs "
                               "WHERE id = %s", (run_id,)).fetchone()
            assert run == ("league_probe", "completed", 3, 3)
            capped, _ = await probe_leagues(conn, provider, [(LEAGUE, SEASON)], at=NOW, max_requests=2)
            assert capped == [], "a probe that could pass the cap is not started"
        finally:
            conn.rollback()
            conn.execute("DELETE FROM raw.ingestion_payloads WHERE hash LIKE 'probe-test-%'")
            conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'league_probe'")
            conn.commit()

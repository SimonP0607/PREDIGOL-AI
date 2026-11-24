"""PM-05-02 on a real database: the plan counts what is left without a request, the fill goes newest first and stops when its guard says
so (the clock, the day's total, the lane), and a competition whose decision is 'closed' is never asked again."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import period_backfill as pb

from fbi.ingestion import period_stats as ps
from tests.integration.test_period_stats_db import FakeProvider, Raw, conn, league, switch  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)
OLD = NOW - timedelta(days=200)


def guard(c: psycopg.Connection, *, until: datetime | None = None, lane_ceiling: int = 8_000) -> pb.Guard:
    return pb.Guard(c, until=until or NOW + timedelta(hours=3), budget=60_000, lane_ceiling=lane_ceiling, scheduled=True,
                    clock_fn=lambda: NOW)


def test_the_plan_counts_what_is_left_and_asks_nothing(conn: psycopg.Connection) -> None:  # noqa: F811
    league(conn, 21, matches=3, start=OLD)
    league(conn, 22, matches=2, start=OLD + timedelta(days=1))
    plan = pb.plan(conn, at=NOW)
    assert plan["left"] == 5 and plan["nights_at_cap"] == 1 and [r["left"] for r in plan["competitions"]] == [3, 2]
    assert conn.execute("SELECT count(*) FROM core.fixture_period_asks").fetchone() == (0,)


@pytest.mark.asyncio
async def test_the_fill_goes_newest_first_in_its_own_channel(conn: psycopg.Connection) -> None:  # noqa: F811
    _, _, fids = league(conn, 23, matches=3, start=OLD)
    fake = FakeProvider(conn)
    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=NOW - ps.SETTLE, limit=10, newest_first=True)
    assert [t.fixture_id for t in wanted] == list(reversed(fids))
    report = await ps.ask_targets(conn, fake, wanted, job_type=ps.FILL_JOB, channel="backfill", max_requests=2, at=NOW,
                                  pace_seconds=1.5, keep_going=guard(conn), sleep=_no_sleep)
    assert report.requests == 2 and report.stopped == "request cap 2"
    rows = conn.execute("SELECT channel, count(*) FROM core.fixture_period_asks GROUP BY 1").fetchall()
    assert rows == [("backfill", 2)]
    assert conn.execute("SELECT job_type FROM raw.ingestion_runs WHERE id = %s", (report.run_id,)).fetchone() == ("period_backfill",)


async def _no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_the_fill_stops_at_its_hour(conn: psycopg.Connection) -> None:  # noqa: F811
    league(conn, 24, matches=3, start=OLD)
    g = guard(conn, until=NOW)  # the stop time is now
    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=NOW - ps.SETTLE, limit=10, newest_first=True)
    report = await ps.ask_targets(conn, FakeProvider(conn), wanted, job_type=ps.FILL_JOB, channel="backfill", max_requests=10, at=NOW,
                                  keep_going=g, sleep=_no_sleep)
    assert report.requests == 0 and g.reason == "hora de parada" and report.stopped == "time or lane budget"


def test_the_guard_stops_when_the_day_passes_60_percent_of_the_budget(conn: psycopg.Connection) -> None:  # noqa: F811
    day = NOW.date()
    conn.execute("INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) VALUES ('api_football', %s, 36000, 60000) "
                 "ON CONFLICT (provider, quota_date) DO UPDATE SET spent = 36000", (day,))
    conn.commit()
    g = guard(conn)
    assert g() is False and g.reason is not None and "60 %" in g.reason
    conn.execute("UPDATE raw.provider_quota SET spent = 35999 WHERE provider = 'api_football' AND quota_date = %s", (day,))
    conn.commit()
    assert guard(conn)() is True


def test_the_guard_leaves_the_weekly_players_round_its_room_in_the_lane(conn: psycopg.Connection) -> None:  # noqa: F811
    day = NOW.date()
    conn.execute("DELETE FROM raw.provider_quota WHERE provider = 'api_football' AND quota_date = %s", (day,))
    conn.execute("INSERT INTO raw.provider_endpoint_usage (provider, usage_date, endpoint, lane, job, requests) "
                 "VALUES ('api_football', %s, '/players', 'historicos', 'historical_backfill', 7900) "
                 "ON CONFLICT (provider, usage_date, endpoint, lane, job) DO UPDATE SET requests = 7900", (day,))
    conn.commit()
    g = guard(conn)
    assert g() is False and g.reason is not None and "historicos" in g.reason
    assert guard(conn, lane_ceiling=9_000)() is True


@pytest.mark.asyncio
async def test_a_closed_competition_is_not_in_the_plan_nor_asked_again(conn: psycopg.Connection) -> None:  # noqa: F811
    """Five matches asked with no half in the answer: the competition's decision is taken and builds nothing; its sixth match is left out."""
    league(conn, 25, matches=6, start=OLD)

    class Empty(FakeProvider):
        async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> Any:
            self.calls += 1
            return Raw({"response": []}, self.calls)

    wanted = ps.targets(conn, since=ps.FILL_SINCE, until=NOW - ps.SETTLE, limit=5, newest_first=True)
    fake = Empty(conn)
    await ps.ask_targets(conn, fake, wanted, job_type=ps.FILL_JOB, channel="backfill", max_requests=5, at=NOW, sleep=_no_sleep)
    assert fake.calls == 5 and len(ps.closed_competitions(ps.competition_state(conn))) == 1
    plan = pb.plan(conn, at=NOW)
    assert plan["left"] == 0 and plan["closed_competitions"] == 1
    assert ps.targets(conn, since=ps.FILL_SINCE, until=NOW - ps.SETTLE, limit=10, skip=ps.closed_competitions(ps.competition_state(conn))) == []

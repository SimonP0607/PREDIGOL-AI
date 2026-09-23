"""A played fixture must stop claiming it has not been played.

The defect: sync_fixtures only looks forward, so a fixture whose kick-off
passed without another sync touching that date keeps status 'NS' for ever. Two
real Premier League matches sat that way for over a week - the database
asserting they were upcoming while they had been played and settled.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.payload_store import PayloadStore
from fbi.ingestion.results import ResultRepository, stale_fixtures, sync_results
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.normalize import iter_fixture_results
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.base import FixtureResultRef
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from tests.integration.conftest import Seed
from tests.integration.helpers import row, scalar

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
PLAYED = NOW - timedelta(hours=20)


# ---------------------------------------------------------------------------
# Parsing: the goals were always in the /fixtures payload
# ---------------------------------------------------------------------------

def entry(fid: int, status: str, gh: object, ga: object, **score: object) -> dict:
    return {
        "fixture": {"id": fid, "date": PLAYED.isoformat(), "status": {"short": status}},
        "league": {"id": 39, "season": 2025},
        "teams": {"home": {"id": 33, "name": "H"}, "away": {"id": 40, "name": "A"}},
        "goals": {"home": gh, "away": ga},
        "score": {
            "halftime": score.get("ht", {"home": None, "away": None}),
            "fulltime": {"home": gh, "away": ga},
            "extratime": score.get("et", {"home": None, "away": None}),
            "penalty": score.get("pen", {"home": None, "away": None}),
        },
    }


def body(*entries: dict) -> dict:
    return {"response": list(entries), "errors": [], "paging": {"current": 1, "total": 1}}


def test_a_finished_fixture_yields_its_score() -> None:
    r = next(iter_fixture_results(body(entry(1, "FT", 2, 1, ht={"home": 1, "away": 0}))))
    assert (r.provider_fixture_id, r.goals_home, r.goals_away) == (1, 2, 1)
    assert (r.ht_goals_home, r.ht_goals_away) == (1, 0)
    assert r.status_short == "FT"


@pytest.mark.parametrize("status", ["NS", "PST", "CANC", "ABD", "1H", "HT", "SUSP", "TBD"])
def test_a_fixture_that_was_not_played_yields_nothing(status: str) -> None:
    """The provider reports 0-0 for several of these. A postponed match must
    never acquire a score - something would later settle a market on it."""
    assert list(iter_fixture_results(body(entry(1, status, 0, 0)))) == []


def test_extra_time_and_penalties_are_kept_apart_from_the_90_minute_score() -> None:
    """1X2 settles on 90 minutes, a cup tie on penalties. Merging them would
    mis-settle every knockout match."""
    r = next(iter_fixture_results(body(entry(
        1, "PEN", 1, 1, ht={"home": 0, "away": 1},
        et={"home": 1, "away": 1}, pen={"home": 4, "away": 2},
    ))))
    assert (r.goals_home, r.goals_away) == (1, 1), "the 90-minute score, not the shoot-out"
    assert (r.pen_home, r.pen_away) == (4, 2)
    assert (r.et_goals_home, r.et_goals_away) == (1, 1)


def test_a_finished_fixture_with_no_goals_block_is_skipped_not_guessed() -> None:
    assert list(iter_fixture_results(body(entry(1, "FT", None, None)))) == []


# ---------------------------------------------------------------------------
# Applying: status AND score, together
# ---------------------------------------------------------------------------

@pytest.fixture()
def played(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    """The seed fixture, tracked, kicked off in the past, still saying 'NS'."""
    set_clock(FrozenClock(NOW))
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        cur.execute(
            "UPDATE core.fixtures SET kickoff_at = %s, status_short = 'NS', status_group = 'scheduled' "
            "WHERE id = %s",
            (PLAYED, seed.fixture_id),
        )
    db.commit()
    yield db
    set_clock(SystemClock())
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = %s", (seed.fixture_id,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN (SELECT id FROM raw.ingestion_runs WHERE job_type = 'results_sync')")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'results_sync'")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


def test_a_kicked_off_fixture_still_marked_not_started_is_reported_as_stale(
    played: psycopg.Connection, seed: Seed
) -> None:
    stale = stale_fixtures(played)
    assert [s.provider_fixture_id for s in stale] == [1001]
    assert stale[0].status_short == "NS"


def test_applying_a_result_fixes_the_status_and_writes_the_score(
    played: psycopg.Connection, seed: Seed
) -> None:
    updated, written = ResultRepository(played).apply(
        [FixtureResultRef(provider_fixture_id=1001, status_short="FT", goals_home=2, goals_away=1,
                          ht_goals_home=1, ht_goals_away=0)]
    )
    assert (updated, written) == (1, 1)
    with played.cursor() as cur:
        cur.execute("SELECT status_short, status_group FROM core.fixtures WHERE id = %s", (seed.fixture_id,))
        assert row(cur) == ("FT", "finished")
        cur.execute(
            "SELECT goals_home, goals_away, outcome_1x2, total_goals, btts "
            "FROM core.fixture_results WHERE fixture_id = %s",
            (seed.fixture_id,),
        )
        assert row(cur) == (2, 1, "Home", 3, True), "the derived columns come from the schema, not from us"
    assert stale_fixtures(played) == [], "nothing is stale once the result is in"


def test_a_result_for_a_fixture_we_do_not_track_is_skipped_not_invented(
    played: psycopg.Connection,
) -> None:
    """The date sweep returns every league on Earth; we track one."""
    updated, written = ResultRepository(played).apply(
        [FixtureResultRef(provider_fixture_id=999_999, status_short="FT", goals_home=3, goals_away=0)]
    )
    assert (updated, written) == (0, 0)
    with played.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id = 999999")
        assert scalar(cur) == 0


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def client_for(tmp_path: Path, handler_body: dict) -> ApiFootballProvider:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=handler_body)

    async def _no_sleep(_s: float) -> None:
        return None

    return ApiFootballProvider(ApiFootballClient(
        ApiFootballSettings(key=SECRET, plan="free", daily_budget=60, max_retries=0),
        PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(300, sleep=_no_sleep), quota=DailyQuota(budget=60),
    ))


async def test_the_sync_closes_the_gap_and_is_idempotent(
    played: psycopg.Connection, seed: Seed, tmp_path: Path
) -> None:
    payload = body(
        entry(1001, "FT", 2, 1, ht={"home": 1, "away": 0}),
        entry(777_001, "FT", 0, 0),  # another league, must be ignored
    )
    first = await sync_results(played, client_for(tmp_path, payload), lookback_days=1)

    assert first.api_calls == 2, "today and yesterday"
    assert first.payloads_stored == 2
    assert first.rows_updated == 2, "one tracked fixture, seen on both days"
    assert first.status == "completed"
    with played.cursor() as cur:
        cur.execute("SELECT status_short FROM core.fixtures WHERE id = %s", (seed.fixture_id,))
        assert scalar(cur) == "FT"

    second = await sync_results(played, client_for(tmp_path, payload), lookback_days=1)
    assert second.status == "completed"
    with played.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_results WHERE fixture_id = %s", (seed.fixture_id,))
        assert scalar(cur) == 1, "re-running overwrites the score, it does not duplicate it"
        cur.execute("SELECT goals_home, goals_away FROM core.fixture_results WHERE fixture_id = %s", (seed.fixture_id,))
        assert row(cur) == (2, 1)


async def test_a_plan_refusal_is_recorded_without_pretending_it_worked(
    played: psycopg.Connection, tmp_path: Path
) -> None:
    """Beyond the free plan's window the provider refuses. The request was
    still issued, so it is still billed, and the run says so."""
    refusal = {
        "response": [],
        "errors": {"plan": "Free plans do not have access to this date, try from 2026-09-22 to 2026-09-24."},
    }
    counters = await sync_results(played, client_for(tmp_path, refusal), lookback_days=1)
    assert counters.api_calls == 2, "issued and billed even though refused"
    assert len(counters.errors) == 2
    assert counters.status == "failed", "nothing durable came of it"
    assert stale_fixtures(played) != [], "and the fixture is still stale, honestly"

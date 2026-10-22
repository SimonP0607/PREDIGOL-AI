"""Every fixture and score can say which payload wrote it - and an older
payload can never overwrite a newer one.

Two properties, both needed before a Match Center can show a score:

* lineage: core.fixtures and core.fixture_results record the hash and fetch
  time of the payload that last wrote them (revision 0015);
* monotonicity: a write is applied only if its payload was fetched at the same
  instant as, or later than, the one already applied. Without it, replaying a
  stored response from the 12th turns a match finished on the 14th back into
  a scheduled one.

And the replay itself: stored /fixtures payloads re-normalised with zero
requests, refused if the file does not match its indexed hash.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.fixtures import (
    FixtureRepository,
    SyncStrategy,
    sync_fixtures,
    tracked_season_ids,
)
from fbi.ingestion.replay import replay_fixture_payloads
from fbi.ingestion.results import sync_results
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore, body_hash
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, row, scalar

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
T0 = datetime(2026, 9, 12, 21, 54, tzinfo=UTC)
KICKOFF = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
FID = 88_001


def entry(fid: int, status: str, goals: tuple[int | None, int | None] = (None, None), *,
          league: int = 39, round_: str | None = "Regular Season - 4",
          venue: dict | None = None) -> dict:
    return {
        "fixture": {
            "id": fid, "date": KICKOFF.isoformat(), "status": {"short": status},
            "venue": venue if venue is not None else {"id": 556, "name": "Old Trafford", "city": "Manchester"},
        },
        "league": {"id": league, "season": 2025, "round": round_},
        "teams": {"home": {"id": 33, "name": "Manchester United"}, "away": {"id": 40, "name": "Liverpool"}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {
            "halftime": {"home": None, "away": None},
            "fulltime": {"home": goals[0], "away": goals[1]},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        },
    }


def body(*entries: dict) -> dict:
    return {"response": list(entries), "errors": [], "paging": {"current": 1, "total": 1}}


def provider_for(tmp_path: Path, answer: dict | None = None) -> ApiFootballProvider:
    def handler(_request: httpx.Request) -> httpx.Response:
        if answer is None:
            raise AssertionError("this test must not reach the network")
        return httpx.Response(200, json=answer)

    async def _no_sleep(_s: float) -> None:
        return None

    return ApiFootballProvider(ApiFootballClient(
        ApiFootballSettings(key=SECRET, plan="free", daily_budget=60, max_retries=0),
        PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(300, sleep=_no_sleep), quota=DailyQuota(budget=60),
    ))


def index(conn: psycopg.Connection, payload: dict, fetched_at: datetime, store: PayloadStore | None = None) -> str:
    """Store (optionally) and index a payload the way a real fetch would."""
    digest = body_hash(payload)
    file_path = f"test/{digest[:12]}.json.gz"
    if store is not None:
        stored = store.store(endpoint="/fixtures", params={"date": "2026-09-12"}, fetched_at=fetched_at,
                             http_status=200, body=payload)
        file_path = stored.file_path
    with conn.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                    "VALUES ('t','lineage_test','completed', now()) RETURNING id")
        run_id = scalar(cur)
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
            "results_count, file_path, bytes) VALUES (%s,%s,'/fixtures','{}'::jsonb,%s,200,%s,%s,1) "
            "ON CONFLICT (hash) DO NOTHING",
            (digest, run_id, fetched_at, len(payload["response"]), file_path),
        )
    return digest


@pytest.fixture()
def tracked(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    db.commit()
    yield db
    set_clock(SystemClock())
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 88000 AND 88999")
        cur.execute("DELETE FROM core.venues WHERE provider_venue_id IN (556, 557)")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN "
                    "(SELECT id FROM raw.ingestion_runs WHERE job_type IN "
                    "('lineage_test','fixtures_sync','results_sync','raw_replay'))")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type IN "
                    "('lineage_test','fixtures_sync','results_sync','raw_replay')")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


def fixture_row(conn: psycopg.Connection, fid: int = FID) -> tuple:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT f.status_short, f.status_group, f.round, v.name, f.source_payload_hash, f.source_fetched_at "
            "FROM core.fixtures f LEFT JOIN core.venues v ON v.id = f.venue_id WHERE f.provider_fixture_id = %s",
            (fid,),
        )
        return row(cur)


def result_row(conn: psycopg.Connection, fid: int = FID) -> tuple | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.goals_home, r.goals_away, r.source_payload_hash, r.source_fetched_at "
            "FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id "
            "WHERE f.provider_fixture_id = %s", (fid,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Lineage through the live syncs
# ---------------------------------------------------------------------------

async def test_a_synced_fixture_records_the_payload_that_wrote_it(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    set_clock(FrozenClock(T0))
    await sync_fixtures(tracked, provider_for(tmp_path, body(entry(FID, "NS"))),
                        horizon_days=0, strategy=SyncStrategy.DATE)
    status, group, round_, venue, payload_hash, fetched_at = fixture_row(tracked)
    assert (status, group) == ("NS", "scheduled")
    assert round_ == "Regular Season - 4", "the round was always in the payload"
    assert venue == "Old Trafford"
    with tracked.cursor() as cur:
        cur.execute("SELECT hash, fetched_at FROM raw.ingestion_payloads WHERE hash = %s", (payload_hash,))
        indexed_hash, indexed_at = row(cur)
    assert payload_hash == indexed_hash, "the row points at an indexed payload"
    assert fetched_at == indexed_at


async def test_the_fixtures_sync_writes_the_scores_it_was_handed(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    """The fixtures sync used to parse the identity and discard the score in
    the same response. A day it fetches for any reason now yields its results."""
    set_clock(FrozenClock(T0))
    counters = await sync_fixtures(tracked, provider_for(tmp_path, body(entry(FID, "FT", (2, 1)))),
                                   horizon_days=0, strategy=SyncStrategy.DATE)
    assert counters.api_calls == 1
    status, group, *_ = fixture_row(tracked)
    assert (status, group) == ("FT", "finished")
    result = result_row(tracked)
    assert result is not None and result[:2] == (2, 1)
    assert result[2] is not None, "the score says which payload it came from"


async def test_a_postponement_seen_by_the_results_sync_is_recorded(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    """The old results path only read finished fixtures, so a postponed match
    stayed 'scheduled' - and counted as stale - for ever."""
    set_clock(FrozenClock(T0))
    await sync_fixtures(tracked, provider_for(tmp_path, body(entry(FID, "NS"))),
                        horizon_days=0, strategy=SyncStrategy.DATE)
    set_clock(FrozenClock(T0 + timedelta(hours=6)))
    await sync_results(tracked, provider_for(tmp_path, body(entry(FID, "PST"))), lookback_days=0)
    status, group, *_ = fixture_row(tracked)
    assert (status, group) == ("PST", "postponed")
    assert result_row(tracked) is None, "a postponed match never acquires a score"


# ---------------------------------------------------------------------------
# Monotonic writes
# ---------------------------------------------------------------------------

def test_an_older_payload_cannot_regress_a_finished_match(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    provider = provider_for(tmp_path)
    seasons = tracked_season_ids(tracked)
    finished = body(entry(FID, "FT", (3, 0)))
    earlier = body(entry(FID, "NS"))
    newer_hash = index(tracked, finished, T0 + timedelta(days=2))
    older_hash = index(tracked, earlier, T0)

    apply_fixtures_payload(tracked, provider, finished, payload_hash=newer_hash,
                           fetched_at=T0 + timedelta(days=2), season_ids=seasons)
    outcome = apply_fixtures_payload(tracked, provider, earlier, payload_hash=older_hash,
                                     fetched_at=T0, season_ids=seasons)

    assert (outcome.fixtures_inserted, outcome.fixtures_updated) == (0, 0), "the older payload changed nothing"
    status, group, _, _, payload_hash, _ = fixture_row(tracked)
    assert (status, group) == ("FT", "finished")
    assert payload_hash == newer_hash, "lineage still names the payload that established the state"
    assert result_row(tracked)[:2] == (3, 0)  # type: ignore[index]


def test_a_payload_listing_a_held_fixture_under_an_untracked_competition_flags_it(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    provider = provider_for(tmp_path)
    seasons = tracked_season_ids(tracked)
    first = body(entry(FID, "NS"))
    apply_fixtures_payload(tracked, provider, first, payload_hash=index(tracked, first, T0), fetched_at=T0,
                           season_ids=seasons)
    later = T0 + timedelta(days=1)
    moved = body(entry(FID, "PEN", (1, 1), league=916), entry(FID + 1, "NS", league=916))
    outcome = apply_fixtures_payload(tracked, provider, moved, payload_hash=index(tracked, moved, later),
                                     fetched_at=later, season_ids=seasons)
    assert (outcome.ours, outcome.left_tracked) == (0, 1)
    with tracked.cursor() as cur:
        cur.execute("SELECT c.provider_league_id, cs.season FROM core.fixtures f "
                    "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                    "JOIN core.competitions c ON c.id = cs.competition_id WHERE f.provider_fixture_id = %s", (FID,))
        assert row(cur) == (39, 2025)
        cur.execute("SELECT code, observed FROM audit.data_quality_issues WHERE entity_type = 'fixture' "
                    "AND provider_entity_id = %s AND field = 'competition'", (FID,))
        assert row(cur) == ("STALE_DATA", "league 916 season 2025")
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id = %s", (FID + 1,))
        assert scalar(cur) == 0, "a fixture of an untracked competition is still not ours"


def test_the_same_payload_applied_twice_is_idempotent(tracked: psycopg.Connection, tmp_path: Path) -> None:
    provider = provider_for(tmp_path)
    seasons = tracked_season_ids(tracked)
    payload = body(entry(FID, "FT", (1, 1)))
    digest = index(tracked, payload, T0)
    first = apply_fixtures_payload(tracked, provider, payload, payload_hash=digest, fetched_at=T0, season_ids=seasons)
    second = apply_fixtures_payload(tracked, provider, payload, payload_hash=digest, fetched_at=T0, season_ids=seasons)
    assert (first.fixtures_inserted, second.fixtures_inserted) == (1, 0)
    with tracked.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id "
                    "WHERE f.provider_fixture_id = %s", (FID,))
        assert scalar(cur) == 1


def test_a_write_without_lineage_cannot_overwrite_a_traced_row(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    provider = provider_for(tmp_path)
    seasons = tracked_season_ids(tracked)
    payload = body(entry(FID, "FT", (2, 2)))
    digest = index(tracked, payload, T0)
    apply_fixtures_payload(tracked, provider, payload, payload_hash=digest, fetched_at=T0, season_ids=seasons)

    repo = FixtureRepository(tracked)
    refs = provider.parse_fixtures(body(entry(FID, "NS")))
    team_ids = repo.ensure_teams(refs, {33: "Manchester United", 40: "Liverpool"})
    assert repo.upsert_fixtures(refs, seasons, team_ids) == (0, 0)
    assert fixture_row(tracked)[:2] == ("FT", "finished")


def test_lineage_hash_and_time_come_as_a_pair(tracked: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(tracked, "a hash without a fetch time cannot order writes") as cur:
        cur.execute("UPDATE core.fixtures SET source_payload_hash = %s, source_fetched_at = NULL WHERE id = %s",
                    (seed.payload_hash, seed.fixture_id))


# ---------------------------------------------------------------------------
# Replay from the raw store
# ---------------------------------------------------------------------------

def test_the_replay_recovers_what_was_observed_and_spends_nothing(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    """A stored response whose score was never parsed. The replay reads it back
    - no network: the provider's transport raises if touched."""
    store = PayloadStore(tmp_path)
    payload = body(entry(FID, "FT", (4, 2)), entry(88_002, "NS"), entry(99_001, "FT", (1, 0), league=140))
    index(tracked, payload, T0, store=store)
    tracked.commit()

    dry = replay_fixture_payloads(tracked, provider_for(tmp_path), store, apply=False)
    assert dry.payloads_applied >= 1 and dry.committed is False
    assert dry.fixtures_inserted == 2 and dry.results_written == 1
    with tracked.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id IN (88001, 88002)")
        assert scalar(cur) == 0, "a dry run writes nothing"

    done = replay_fixture_payloads(tracked, provider_for(tmp_path), store, apply=True)
    assert done.committed is True
    assert result_row(tracked)[:2] == (4, 2)  # type: ignore[index]
    with tracked.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id = 99001")
        assert scalar(cur) == 0, "another league stays out, as in the live sync"
        cur.execute("SELECT status, api_calls FROM raw.ingestion_runs WHERE id = %s", (done.run_id,))
        assert row(cur) == ("completed", 0), "recorded in the ledger, at zero requests"


def test_the_replay_refuses_a_file_that_does_not_match_its_hash(
    tracked: psycopg.Connection, tmp_path: Path
) -> None:
    store = PayloadStore(tmp_path)
    payload = body(entry(FID, "FT", (1, 0)))
    digest = index(tracked, payload, T0, store=store)
    tracked.commit()
    with tracked.cursor() as cur:
        cur.execute("SELECT file_path FROM raw.ingestion_payloads WHERE hash = %s", (digest,))
        path = tmp_path / str(scalar(cur))
    with gzip.open(path, "rt") as fh:
        tampered = json.loads(fh.read())
    tampered["body"]["response"][0]["goals"] = {"home": 9, "away": 0}
    with gzip.open(path, "wt") as out:
        out.write(json.dumps(tampered))

    report = replay_fixture_payloads(tracked, provider_for(tmp_path), store, apply=True)
    assert any("hash mismatch" in r for r in report.payloads_refused)
    assert result_row(tracked) is None, "bytes whose provenance cannot be proven are never applied"

"""IA-069 (plan piece AD-D05) on PostgreSQL: the first sighting of a line-up is kept, every change of its content is an arrival,
an identical re-send is not, the watch writes only its arrivals and stops at its budget, and the report reads them back.

The provider's answers are the recorded ``/fixtures?ids=`` of ``tests/fixtures/contracts/fixture_details_ids.json`` (our own RAW,
trimmed), re-addressed to the seeded match and replayed as the provider would have sent them before kick-off: the line-up
arriving, sent again unchanged, then with a starter corrected."""

from __future__ import annotations

import copy
import itertools
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.ingestion.details import apply_fixture_details
from fbi.ingestion.lineup_timing import report
from fbi.ingestion.lineup_watch import Budget, WatchSettings, budget_now, due_now, run_watch_job
from fbi.providers.api_football.details import FixtureDetail, iter_fixture_details
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed

RECORDED = json.loads((Path(__file__).parents[1] / "fixtures" / "contracts" / "fixture_details_ids.json")
                      .read_text(encoding="utf-8"))["body"]
KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
SHADOW = WatchSettings(mode="shadow")


def body(pid: int, home: int, away: int, *, kickoff: datetime, lineups: bool = True, swap: bool = False) -> dict[str, Any]:
    """The first recorded match, as match ``pid`` between provider teams ``home`` and ``away``, not started."""
    entry = copy.deepcopy(RECORDED["response"][0])
    rec_home, rec_away = entry["teams"]["home"]["id"], entry["teams"]["away"]["id"]
    entry["fixture"].update({"id": pid, "date": kickoff.isoformat(), "timestamp": int(kickoff.timestamp()),
                             "status": {"short": "NS", "long": "Not Started", "elapsed": None, "extra": None}})
    entry["teams"]["home"]["id"], entry["teams"]["away"]["id"] = home, away
    entry["events"], entry["statistics"], entry["players"] = [], [], []
    for lu in entry["lineups"]:
        lu["team"]["id"] = home if lu["team"]["id"] == rec_home else away if lu["team"]["id"] == rec_away else 0
    if swap:  # the home side's fourth starter corrected: the first substitute starts instead
        home_lu = next(lu for lu in entry["lineups"] if lu["team"]["id"] == home)
        home_lu["startXI"][3], home_lu["substitutes"][0] = home_lu["substitutes"][0], home_lu["startXI"][3]
    if not lineups:
        entry["lineups"] = []
    return {"response": [entry]}


def details(b: dict[str, Any]) -> list[FixtureDetail]:
    return list(iter_fixture_details(b))


def payload(db: psycopg.Connection[Any], seed: Seed, h: str, at: datetime) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING", (h, seed.run_id, at, h))
    return h


def apply(db: psycopg.Connection[Any], seed: Seed, h: str, at: datetime, b: dict[str, Any]) -> Any:
    return apply_fixture_details(db, details(b), payload_hash=payload(db, seed, h, at), fetched_at=at)


def arrivals(db: psycopg.Connection[Any], fixture_id: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT team_side, observed_at, channel, starters, players, starters_hash, kickoff_at "
                      "FROM core.fixture_lineup_arrivals WHERE fixture_id = %s ORDER BY observed_at, team_side",
                      (fixture_id,)).fetchall()


def lineups(db: psycopg.Connection[Any], fixture_id: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT team_side, first_seen_at, fetched_at FROM core.fixture_lineups WHERE fixture_id = %s "
                      "ORDER BY team_side", (fixture_id,)).fetchall()


# ── the detail writers ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_first_sighting_stays_and_only_a_change_of_content_is_a_new_arrival(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    fid = seed.fixture_id
    t1, t2, t3 = KO - timedelta(minutes=40), KO - timedelta(minutes=30), KO - timedelta(minutes=12)
    nothing_yet = apply(db, seed, "ia069-0", KO - timedelta(minutes=60), body(1001, 33, 40, kickoff=KO, lineups=False))
    assert nothing_yet.lineup_arrivals == 0 and lineups(db, fid) == [] and arrivals(db, fid) == []

    first = apply(db, seed, "ia069-1", t1, body(1001, 33, 40, kickoff=KO))
    assert first.lineups == 2 and first.lineup_arrivals == 2
    assert lineups(db, fid) == [("away", t1, t1), ("home", t1, t1)]
    rows = arrivals(db, fid)
    assert [(r[0], r[1], r[2], r[3], r[6]) for r in rows] == [("away", t1, "detail_writer", 11, KO),
                                                             ("home", t1, "detail_writer", 11, KO)]

    again = apply(db, seed, "ia069-2", t2, body(1001, 33, 40, kickoff=KO))
    assert again.lineup_arrivals == 0, "the same line-up sent again is not an arrival"
    assert lineups(db, fid) == [("away", t1, t2), ("home", t1, t2)], "fetched_at moves on, first_seen_at does not"

    corrected = apply(db, seed, "ia069-3", t3, body(1001, 33, 40, kickoff=KO, swap=True))
    assert corrected.lineup_arrivals == 1
    rows = arrivals(db, fid)
    assert [(r[0], r[1]) for r in rows] == [("away", t1), ("home", t1), ("home", t3)]
    assert rows[1][5] != rows[2][5], "a corrected starter changes the starters' hash"
    assert lineups(db, fid) == [("away", t1, t3), ("home", t1, t3)]


def test_an_older_payload_replayed_later_compares_with_what_was_known_at_its_own_instant(db: psycopg.Connection[Any],
                                                                                        seed: Seed) -> None:
    fid = seed.fixture_id
    t1, t2 = KO - timedelta(minutes=40), KO - timedelta(minutes=20)
    apply(db, seed, "ia069-r1", t1, body(1001, 33, 40, kickoff=KO))
    apply(db, seed, "ia069-r2", t2, body(1001, 33, 40, kickoff=KO, swap=True))
    # the line-ups' upsert refuses it (a newer payload is stored), and the whole fixture is stale: nothing is written
    stale = apply(db, seed, "ia069-r0", t1 - timedelta(minutes=5), body(1001, 33, 40, kickoff=KO))
    assert stale.stale == 1 and stale.lineup_arrivals == 0
    assert [(r[0], r[1]) for r in arrivals(db, fid)] == [("away", t1), ("home", t1), ("home", t2)]


def test_a_read_long_after_the_match_is_not_an_arrival_but_first_seen_at_is_still_written(db: psycopg.Connection[Any],
                                                                                         seed: Seed) -> None:
    late = KO + timedelta(hours=31)
    rep = apply(db, seed, "ia069-late", late, body(1001, 33, 40, kickoff=KO))
    assert rep.lineups == 2 and rep.lineup_arrivals == 0
    assert lineups(db, seed.fixture_id) == [("away", late, late), ("home", late, late)]


def test_the_arrivals_cannot_be_changed_or_deleted(db: psycopg.Connection[Any], seed: Seed) -> None:
    apply(db, seed, "ia069-ro", KO - timedelta(minutes=30), body(1001, 33, 40, kickoff=KO))
    for sql in ("UPDATE core.fixture_lineup_arrivals SET starters = 0 WHERE fixture_id = %s",
                "DELETE FROM core.fixture_lineup_arrivals WHERE fixture_id = %s"):
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
            db.execute(sql, (seed.fixture_id,))
        db.execute("ROLLBACK TO SAVEPOINT s")
    db.execute("UPDATE core.fixture_lineups SET first_seen_at = now() WHERE fixture_id = %s", (seed.fixture_id,))
    assert {r[1] for r in lineups(db, seed.fixture_id)} == {KO - timedelta(minutes=30)}, "never rewritten"


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_report_gives_the_minutes_before_kickoff_per_competition(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = seed.fixture_id
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
    apply(db, seed, "ia069-p1", KO - timedelta(minutes=38), body(1001, 33, 40, kickoff=KO))
    apply(db, seed, "ia069-p2", KO - timedelta(minutes=9), body(1001, 33, 40, kickoff=KO, swap=True))
    data = report(db, start=KO - timedelta(minutes=1), end=KO + timedelta(minutes=1), now=KO + timedelta(hours=3))
    comp = next(r for r in data["competitions"] if r["competition_id"] == seed.competition_id)
    assert (comp["played"], comp["with_lineups"], comp["before_kickoff"]) == (1, 1, 1)
    assert comp["median_min"] == 38.0 and comp["starter_changed"] == 1 and comp["first_by_watch"] == 0
    assert comp["official"] is None and "AD-C02" in data["official_note"]
    assert data["first_seen"] == {"rows": 2, "with_first_seen": 2, "without_first_seen": 0}


# ── the watch ────────────────────────────────────────────────────────────────────────────────────────────────────────


class Recorded:
    """The provider, answering with the recorded bodies in order."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self.bodies = bodies
        self.calls: list[list[int]] = []

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> tuple[list[FixtureDetail], RawResponse]:
        self.calls.append(list(provider_fixture_ids))
        b = self.bodies.pop(0)
        at = datetime.now(UTC)
        raw = RawResponse(endpoint="/fixtures", params={"ids": "-".join(map(str, provider_fixture_ids))}, fetched_at=at,
                          http_status=200, results_count=len(b["response"]),
                          payload_hash=f"ia069-watch-{len(self.calls)}-{at.timestamp()}", file_path="x", bytes_written=1,
                          body=b)
        return details(b), raw


_PIDS = itertools.count(8869001)
ROOMY = Budget(daily_budget=1_200, spent_today=0, ours_left=50_000, provider_left=None, floor=9_000)


@pytest.fixture
def upcoming(migrated_database: str, seed: Seed) -> Iterator[tuple[int, int, datetime, str]]:
    """A tracked match 30 minutes from now (and one 2 hours away, not due), committed: the watch commits per answer."""
    kickoff = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=30)
    pid, far = next(_PIDS), next(_PIDS)
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (86901,'Watch Home'),(86902,'Watch Away') "
                    "ON CONFLICT (provider_team_id) DO UPDATE SET name = EXCLUDED.name RETURNING id")
        home, away = (r[0] for r in cur.fetchall())
        ids = []
        for p, ko in ((pid, kickoff), (far, kickoff + timedelta(minutes=90))):
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'NS','scheduled') RETURNING id",
                        (p, seed.season_id, home, away, ko))
            ids.append(cur.fetchone()[0])  # type: ignore[index]
    yield ids[0], pid, kickoff, migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET fbi.history_maintenance = 'on'")
        cur.execute("DELETE FROM core.fixture_lineup_arrivals WHERE fixture_id = ANY(%s)", (ids,))
        cur.execute("SELECT id FROM raw.ingestion_runs WHERE job_type = 'lineup_watch'")
        runs = [r[0] for r in cur.fetchall()]
        if runs:
            cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id = ANY(%s)", (runs,))
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (runs,))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids,))
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))


async def test_the_watch_records_arrivals_and_writes_nothing_the_product_reads(
        upcoming: tuple[int, int, datetime, str]) -> None:
    fid, pid, kickoff, dsn = upcoming
    with psycopg.connect(dsn) as conn:
        due = [d.provider_fixture_id for d in due_now(conn, at=datetime.now(UTC))]
        assert pid in due and pid + 1 not in due, "T-90 to kick-off only"
        provider = Recorded([body(pid, 86901, 86902, kickoff=kickoff),
                             body(pid, 86901, 86902, kickoff=kickoff),
                             body(pid, 86901, 86902, kickoff=kickoff, swap=True)])
        first = await run_watch_job(conn, cfg=SHADOW, provider=provider, budget=ROOMY)
        assert first is not None and (first.requests, first.arrivals, first.allowance) == (1, 2, 1)
        second = await run_watch_job(conn, cfg=SHADOW, provider=provider, budget=ROOMY)
        assert second is not None and (second.requests, second.arrivals) == (1, 0), "the same answer: no arrival"
        third = await run_watch_job(conn, cfg=SHADOW, provider=provider, budget=ROOMY)
        assert third is not None and third.arrivals == 1, "a corrected starter is seen before kick-off"
        assert len(provider.calls) == 3 and all(pid in c for c in provider.calls)
        rows = arrivals(conn, fid)
        assert [(r[0], r[2]) for r in rows] == [("away", "lineup_watch"), ("home", "lineup_watch"),
                                                ("home", "lineup_watch")]
        # nothing the product reads was written: no line-up, no detail, no live state, the fixture as it was
        for table in ("core.fixture_lineups", "core.fixture_lineup_players", "core.fixture_events",
                      "core.fixture_live_states", "core.fixture_detail_coverage"):
            assert conn.execute(f"SELECT count(*) FROM {table} WHERE fixture_id = %s", (fid,)).fetchone() == (0,), table
        assert conn.execute("SELECT status_short, source_payload_hash FROM core.fixtures WHERE id = %s",
                            (fid,)).fetchone() == ("NS", None)
        runs = conn.execute("SELECT status, api_calls, rows_written FROM raw.ingestion_runs WHERE job_type = 'lineup_watch' "
                            "ORDER BY id").fetchall()
        assert [(r[1], r[2]) for r in runs] == [(1, 2), (1, 0), (1, 1)]


async def test_the_watch_asks_nothing_when_its_budget_or_the_floor_leaves_nothing(
        upcoming: tuple[int, int, datetime, str]) -> None:
    _, pid, kickoff, dsn = upcoming
    with psycopg.connect(dsn) as conn:
        provider = Recorded([body(pid, 86901, 86902, kickoff=kickoff)])
        for budget in (Budget(1_200, 1_200, 50_000, None, 9_000), Budget(1_200, 0, 9_000, None, 9_000),
                       Budget(1_200, 0, 50_000, 8_000, 9_000)):
            rep = await run_watch_job(conn, cfg=SHADOW, provider=provider, budget=budget)
            assert rep is not None and rep.requests == 0 and rep.allowance == 0 and rep.stopped_early
        assert provider.calls == []
        assert conn.execute("SELECT count(*) FROM raw.ingestion_runs WHERE job_type = 'lineup_watch'").fetchone() == (0,)
        # the real budget reads today's figures and the floor (reserve + the next 24 h of capture windows)
        real = budget_now(conn, at=datetime.now(UTC), cfg=SHADOW)
        assert real.daily_budget == 1_200 and real.spent_today == 0 and real.floor >= SHADOW.reserve
        assert await run_watch_job(conn, cfg=WatchSettings()) is None, "off: nothing at all"

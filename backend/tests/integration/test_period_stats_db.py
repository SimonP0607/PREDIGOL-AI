"""PM-05-01 on a real database: the closing pass keeps the halves the provider gives, asks only what the matrix and the decision let it,
never writes a zero for a figure not sent, takes the newest payload, and reads the PM-01-05 answers back from RAW without a request.
The answers are REAL ones kept from the probe (``tests/fixtures/period_stats``), their team ids set to the match's."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.core import period_rules as rules
from fbi.ingestion import period_stats as ps
from fbi.providers.api_football.period_stats import PERIOD_STAT_COLUMNS, parse_period_answer
from tests.integration.test_coverage_job import competition, match, one, payload, season

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "period_stats"
NOW = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)
START = NOW - timedelta(days=2)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        for t in ("core.fixture_team_stats_period", "core.fixture_period_asks", "analytics.coverage_cells"):
            c.execute(f"DELETE FROM {t}")
        c.execute("UPDATE core.competitions SET is_tracked = false")
        c.commit()
        yield c


def body_of(name: str, home: int, away: int) -> dict[str, Any]:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    body = data["body"]
    body["response"][0]["team"]["id"] = home
    body["response"][1]["team"]["id"] = away
    return body


def grade(c: psycopg.Connection, cs: int, level: str = "A") -> None:
    c.execute("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, level, "
              "measured_level, rules_version, measured_at) VALUES (%s, 'todas', 'corners', 40, 40, 1, %s, %s, 'coverage-levels-v1', now())",
              (cs, level, level))


def league(c: psycopg.Connection, n: int, *, matches: int, level: str | None = "A", start: datetime = START) -> tuple[int, int, list[int]]:
    comp = competition(c, 995_000 + n)
    cs = season(c, comp, 2026)
    h = payload(c)
    fixtures = [match(c, cs, start + timedelta(minutes=k), h=h) for k in range(matches)]
    if level:
        grade(c, cs, level)
    c.commit()
    return comp, cs, fixtures


def provider_ids(c: psycopg.Connection, fid: int) -> tuple[int, int, int]:
    row = c.execute("SELECT f.provider_fixture_id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f "
                    "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = %s",
                    (fid,)).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


class Raw:
    def __init__(self, body: dict[str, Any], n: int) -> None:
        self.params: dict[str, Any] = {}
        self.body, self.endpoint = body, "/fixtures/statistics"
        self.fetched_at = NOW
        self.payload_hash = f"period-test-{n}"
        self.http_status, self.results_count, self.file_path, self.bytes_written, self.persisted = 200, 2, "x", 1, True


class FakeProvider:
    """Answers every ``/fixtures/statistics`` with the real answer ``name`` (teams set to the match's); counts the requests."""

    def __init__(self, c: psycopg.Connection, answer: str | dict[str, str] = "typical") -> None:
        self.params: list[dict[str, Any]] = []
        self.c, self.answer, self.calls = c, answer, 0

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> Raw:
        assert endpoint == "/fixtures/statistics" and params["half"] == "true"
        self.calls += 1
        self.params.append(dict(params))
        row = self.c.execute("SELECT f.id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f "
                             "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id "
                             "WHERE f.provider_fixture_id = %s", (int(params["fixture"]),)).fetchone()
        assert row is not None
        name = self.answer if isinstance(self.answer, str) else self.answer.get(params["fixture"], "typical")
        return Raw(body_of(name, int(row[1]), int(row[2])), self.calls + 1000 * int(params["fixture"]))


@pytest.fixture(autouse=True)
def switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ps.SWITCH, "on")


def count(c: psycopg.Connection, sql: str, *params: object) -> int:
    return one(c, sql, params or None)


@pytest.mark.asyncio
async def test_the_pass_keeps_the_halves_of_a_settled_match_and_its_ask(conn: psycopg.Connection) -> None:
    c = conn
    _, _, fids = league(c, 1, matches=1)
    fake = FakeProvider(c)
    report = await ps.refresh_period_stats(c, fake, at=NOW)
    assert (report.requests, report.with_halves, report.rows) == (1, 1, 4) and fake.calls == 1
    assert fake.params[0]["half"] == "true" and fake.params[0]["fixture"] == str(provider_ids(c, fids[0])[0])
    rows = c.execute("SELECT team_side, period, corners, possession_pct, fouls FROM core.fixture_team_stats_period "
                     "WHERE fixture_id = %s ORDER BY team_side, period", (fids[0],)).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("away", "1h"), ("away", "2h"), ("home", "1h"), ("home", "2h")]
    assert all(r[2] is not None and r[3] is not None and r[4] is not None for r in rows)
    ask = c.execute("SELECT channel, outcome, filled, sums_off FROM core.fixture_period_asks WHERE fixture_id = %s", (fids[0],)).fetchone()
    assert ask is not None and ask[0] == "closing" and ask[1] == "with_halves" and "corners" in ask[2] and ask[3] == []
    # a match asked is not asked again
    again = await ps.refresh_period_stats(c, fake, at=NOW + timedelta(minutes=30))
    assert again.requests == 0 and fake.calls == 1
    run = c.execute("SELECT job_type, api_calls, status FROM raw.ingestion_runs WHERE id = %s", (report.run_id,)).fetchone()
    assert run is not None and run[0] == "period_stats" and run[1] == 1


@pytest.mark.asyncio
async def test_a_figure_the_provider_did_not_send_is_null_never_zero(conn: psycopg.Connection) -> None:
    c = conn
    _, _, fids = league(c, 2, matches=1)
    await ps.refresh_period_stats(c, FakeProvider(c, "no_fouls"), at=NOW)
    rows = c.execute("SELECT fouls, red_cards, corners FROM core.fixture_team_stats_period WHERE fixture_id = %s", (fids[0],)).fetchall()
    assert len(rows) == 4 and all(r[0] is None and r[1] is None and r[2] is not None for r in rows)
    ask = c.execute("SELECT filled FROM core.fixture_period_asks WHERE fixture_id = %s", (fids[0],)).fetchone()
    assert ask is not None and "fouls" not in ask[0] and "red_cards" not in ask[0] and "corners" in ask[0]


@pytest.mark.asyncio
async def test_a_match_is_asked_only_once_settled_and_only_in_a_graded_competition(conn: psycopg.Connection) -> None:
    c = conn
    league(c, 3, matches=1, start=NOW - timedelta(minutes=140))        # not settled: 140 minutes after the kick-off
    league(c, 4, matches=1, level="C")                                   # corners graded C: not built
    league(c, 5, matches=1, level="D")
    league(c, 6, matches=1, level=None)                                  # the matrix has not graded it, and has no A or B season
    league(c, 7, matches=1, start=NOW - timedelta(days=8))              # a week behind: the pass does not look back further
    _, _cs_ok, fids_ok = league(c, 8, matches=1)
    fake = FakeProvider(c)
    report = await ps.refresh_period_stats(c, fake, at=NOW)
    assert report.requests == 1 and fake.calls == 1
    assert count(c, "SELECT count(*) FROM core.fixture_period_asks WHERE fixture_id = %s", fids_ok[0]) == 1
    assert count(c, "SELECT count(*) FROM core.fixture_period_asks") == 1


@pytest.mark.asyncio
async def test_a_season_the_matrix_has_not_graded_follows_its_competition(conn: psycopg.Connection) -> None:
    """The matrix keeps the last two seasons: an older season of a competition graded A or B is asked; one of a competition never graded is not."""
    c = conn
    comp, _, _ = league(c, 9, matches=0)
    old = season(c, comp, 2025)
    h = payload(c)
    fid = match(c, old, START, h=h)
    c.commit()
    fake = FakeProvider(c)
    report = await ps.refresh_period_stats(c, fake, at=NOW)
    assert report.requests == 1 and count(c, "SELECT count(*) FROM core.fixture_period_asks WHERE fixture_id = %s", fid) == 1


@pytest.mark.asyncio
async def test_a_competition_with_no_statistic_built_is_closed_after_five(conn: psycopg.Connection) -> None:
    """Five matches asked, none with halves: the competition has a decision and nothing built, so the sixth is not asked."""
    c = conn
    _, _, fids = league(c, 10, matches=8)
    empty: dict[str, Any] = {"response": []}

    class Empty(FakeProvider):
        async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> Raw:
            self.calls += 1
            return Raw(empty, self.calls)

    fake = Empty(c)
    report = await ps.refresh_period_stats(c, fake, at=NOW)
    assert fake.calls == rules.MIN_SAMPLE and report.empty == 5 and report.skipped_closed == 3
    assert count(c, "SELECT count(*) FROM core.fixture_team_stats_period") == 0, "an answer with no half writes no row"
    assert count(c, "SELECT count(*) FROM core.fixture_period_asks WHERE outcome = 'empty'") == 5
    assert ps.competition_state(c)[one(c, "SELECT competition_id FROM core.competition_seasons cs JOIN core.fixtures f "
                                         "ON f.competition_season_id = cs.id WHERE f.id = %s", (fids[0],))].gate() == "closed"


@pytest.mark.asyncio
async def test_a_competition_that_builds_stays_open(conn: psycopg.Connection) -> None:
    c = conn
    league(c, 11, matches=8)
    fake = FakeProvider(c)
    report = await ps.refresh_period_stats(c, fake, at=NOW)
    assert report.requests == 8 and report.with_halves == 8
    state = next(iter(ps.competition_state(c).values()))
    assert state.asked == 8 and state.gate() == "build" and "corners" in ps.stats_built(state) and "fouls" in ps.stats_built(state)


@pytest.mark.asyncio
async def test_the_cap_of_a_pass_and_of_a_day(conn: psycopg.Connection) -> None:
    c = conn
    league(c, 12, matches=6)
    fake = FakeProvider(c)
    first = await ps.refresh_period_stats(c, fake, at=NOW, max_requests=2)
    assert first.requests == 2 and first.stopped == "request cap 2"
    second = await ps.refresh_period_stats(c, fake, at=NOW + timedelta(minutes=30), max_requests=10, day_max=3)
    assert second.requests == 1, "three a day, two used"
    third = await ps.refresh_period_stats(c, fake, at=NOW + timedelta(minutes=60), max_requests=10, day_max=3)
    assert third.requests == 0 and third.stopped == "day cap"
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_off_and_the_quiet_window_ask_nothing(conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    c = conn
    league(c, 13, matches=2)
    fake = FakeProvider(c)
    monkeypatch.setenv(ps.SWITCH, "off")
    assert (await ps.refresh_period_stats(c, fake, at=NOW)).requests == 0
    monkeypatch.delenv(ps.SWITCH)
    assert (await ps.refresh_period_stats(c, fake, at=NOW)).requests == 0, "off by default"
    monkeypatch.setenv(ps.SWITCH, "on")
    assert (await ps.refresh_period_stats(c, fake, at=NOW.replace(hour=4, minute=10))).requests == 0, "the copies' window"
    assert fake.calls == 0 and count(c, "SELECT count(*) FROM core.fixture_period_asks") == 0
    assert ps.in_quiet_window(NOW.replace(hour=3, minute=30)) and ps.in_quiet_window(NOW.replace(hour=4, minute=59))
    assert not ps.in_quiet_window(NOW.replace(hour=5, minute=0)) and not ps.in_quiet_window(NOW.replace(hour=3, minute=29))


@pytest.mark.asyncio
async def test_a_part_larger_than_its_whole_and_a_negative_count_are_dropped_and_named(conn: psycopg.Connection) -> None:
    c = conn
    _, _, fids = league(c, 14, matches=1)
    pid, home, away = provider_ids(c, fids[0])
    body = body_of("typical", home, away)
    for entry in body["response"][:1]:
        for item in entry["statistics_1h"]:
            if item["type"] == "Shots on Goal":
                item["value"] = 99          # more on target than shots: the table refuses it
            if item["type"] == "Corner Kicks":
                item["value"] = -1          # not a statistic
    answer = parse_period_answer(body, pid)
    with c.transaction(), c.cursor() as cur:
        written = ps.apply_answer(cur, fixture_id=fids[0], home_provider_id=home, away_provider_id=away, answer=answer,
                                  payload_hash=payload(c), fetched_at=NOW, channel="closing")
    assert written == 4
    row = c.execute("SELECT shots_on_target, corners, shots, dropped_fields FROM core.fixture_team_stats_period "
                    "WHERE fixture_id = %s AND team_side = 'home' AND period = '1h'", (fids[0],)).fetchone()
    assert row is not None and row[0] is None and row[1] is None and row[2] is not None
    assert row[3] == ["corners", "shots_on_target"]


@pytest.mark.asyncio
async def test_the_newest_payload_wins_and_an_older_one_never_overwrites(conn: psycopg.Connection) -> None:
    c = conn
    _, _, fids = league(c, 15, matches=1)
    pid, home, away = provider_ids(c, fids[0])
    newer, older = body_of("typical", home, away), body_of("typical", home, away)
    for item in older["response"][0]["statistics_1h"]:
        if item["type"] == "Corner Kicks":
            item["value"] = 9
    with c.transaction(), c.cursor() as cur:
        ps.apply_answer(cur, fixture_id=fids[0], home_provider_id=home, away_provider_id=away, answer=parse_period_answer(newer, pid),
                        payload_hash=payload(c), fetched_at=NOW, channel="closing")
        ps.apply_answer(cur, fixture_id=fids[0], home_provider_id=home, away_provider_id=away, answer=parse_period_answer(older, pid),
                        payload_hash=payload(c), fetched_at=NOW - timedelta(hours=1), channel="backfill")
    row = c.execute("SELECT corners FROM core.fixture_team_stats_period WHERE fixture_id = %s AND team_side = 'home' AND period = '1h'",
                    (fids[0],)).fetchone()
    expected = next(i["value"] for i in newer["response"][0]["statistics_1h"] if i["type"] == "Corner Kicks")
    assert row is not None and row[0] == expected != 9
    assert c.execute("SELECT channel FROM core.fixture_period_asks WHERE fixture_id = %s", (fids[0],)).fetchone() == ("closing",)


@pytest.mark.asyncio
async def test_the_probe_answers_are_read_back_from_raw_without_a_request(conn: psycopg.Connection) -> None:
    c = conn
    _, _, fids = league(c, 16, matches=2, level=None)
    pid, home, away = provider_ids(c, fids[0])
    run = one(c, "INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('half_probe', 'half_probe', 'completed') RETURNING id")
    c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, bytes) "
              "VALUES ('probe-hash-1', %s, '/fixtures/statistics', %s::jsonb, %s, 200, 'api-football/x.json.gz', 10)",
              (run, json.dumps({"fixture": str(pid), "half": "true"}), NOW - timedelta(days=1)))
    c.commit()

    class Store:
        def load(self, path: str) -> dict[str, Any]:
            assert path == "api-football/x.json.gz"
            return {"body": body_of("typical", home, away)}

    done = ps.load_probe_answers(c, Store())
    assert done == {"with_halves": 1}
    assert count(c, "SELECT count(*) FROM core.fixture_team_stats_period WHERE fixture_id = %s", fids[0]) == 4
    ask = c.execute("SELECT channel, payload_hash, run_id FROM core.fixture_period_asks WHERE fixture_id = %s", (fids[0],)).fetchone()
    assert ask == ("probe", "probe-hash-1", None)
    assert ps.load_probe_answers(c, Store()) == {}, "once read, not read again"


def test_the_columns_of_the_table_are_the_columns_the_code_writes(conn: psycopg.Connection) -> None:
    cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' "
                                       "AND table_name = 'fixture_team_stats_period' ORDER BY ordinal_position").fetchall()]
    assert cols[:4] == ["fixture_id", "team_side", "period", "source"]
    assert [c for c in cols if c in PERIOD_STAT_COLUMNS] == list(PERIOD_STAT_COLUMNS)
    assert set(cols) - set(PERIOD_STAT_COLUMNS) == {"fixture_id", "team_side", "period", "source", "payload_hash", "fetched_at",
                                                     "dropped_fields"}

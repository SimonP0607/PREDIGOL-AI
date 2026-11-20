"""PM-05-07: the market's margin and dispersion by competition, market and day on a real database - one day measured from
``market.final_prematch_odds`` (finished matches only, the day of kick-off in UTC, by competition), a second pass that changes nothing but
the time, the owner's check against an independent SQL computation, and the nightly process that does nothing while the switch is off."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import psycopg
import pytest

from fbi.market import league_daily as ld

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 21, 8, 0, tzinfo=UTC)
DAY = date(2026, 11, 15)
_ids = count(950_000)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        c.execute("DELETE FROM market.league_daily_stats")
        c.commit()
        yield c


def one(c: psycopg.Connection, sql: str, params: tuple[object, ...] | None = None) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def payload(c: psycopg.Connection) -> str:
    h = f"mls-{next(_ids)}"
    run = one(c, "INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t', 't', 'completed') RETURNING id")
    c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
              "VALUES (%s, %s, '/x', now(), 200, 'x', 1)", (h, run))
    return h


def competition(c: psycopg.Connection) -> int:
    league = next(_ids)
    comp = one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                  "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (league, f"L{league}"))
    return one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))


def match(c: psycopg.Connection, cs: int, kickoff: datetime, books: dict[str, list[tuple[str, ...]]], *, status: str = "finished",
          h: str) -> int:
    home = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A') RETURNING id", (next(_ids),))
    away = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'B') RETURNING id", (next(_ids),))
    fid = one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                 "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', %s) RETURNING id",
              (next(_ids), cs, home, away, kickoff, status))
    sels = {"1X2": (("Home", "Draw", "Away"), 0), "BTTS": (("Yes", "No"), 0), "OU": (("Over", "Under"), 2.5)}
    for market, rows in books.items():
        names, line = sels[market]
        for b, prices in enumerate(rows):
            book = one(c, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, 'b') "
                          "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name RETURNING id", (8100 + b,))
            for sel, odd in zip(names, prices, strict=False):
                c.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
                          "provider_update_at, minutes_to_ko, fetched_at, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, 10, %s, %s)",
                          (fid, book, market, sel, line, odd, kickoff - timedelta(hours=1), kickoff + timedelta(hours=3), h))
    return fid


def rows(c: psycopg.Connection) -> list[tuple[Any, ...]]:
    return c.execute("SELECT s.competition_id, market_key, line, n_fixtures, n_books, books_median, margin_median, n_dispersion "
                     "FROM market.league_daily_stats s WHERE day = %s ORDER BY 1, 2", (DAY,)).fetchall()


def test_a_day_is_measured_by_competition_and_market_and_measured_again_unchanged(conn: psycopg.Connection) -> None:
    h = payload(conn)
    a, b = competition(conn), competition(conn)
    ko = datetime(2026, 11, 15, 23, 30, tzinfo=UTC)  # 23:30 UTC still the 15th; 18:30 in Bogotá
    match(conn, a, ko, {"1X2": [("2.00", "3.40", "4.00"), ("2.10", "3.30", "3.80")], "OU": [("1.90", "1.90")]}, h=h)
    match(conn, a, ko - timedelta(hours=5), {"1X2": [("1.50", "4.00", "7.00")], "BTTS": [("1.80", "2.00")]}, h=h)
    match(conn, b, ko - timedelta(hours=3), {"1X2": [("2.50", "3.20", "2.90"), ("2.40", "3.25")]}, h=h)  # one book incomplete
    match(conn, a, ko + timedelta(hours=1), {"1X2": [("2.00", "3.00", "4.00")]}, h=h)                   # the 16th
    match(conn, a, ko - timedelta(hours=2), {"1X2": [("2.00", "3.00", "4.00")]}, status="postponed", h=h)
    conn.commit()
    comp_a = one(conn, "SELECT competition_id FROM core.competition_seasons WHERE id = %s", (a,))
    comp_b = one(conn, "SELECT competition_id FROM core.competition_seasons WHERE id = %s", (b,))

    report = ld.run_pass(conn, now=NOW, days=[DAY])
    assert (report.days, report.rows, report.rejected, report.errors) == (1, 4, 1, [])
    got = rows(conn)
    m = {(r[0], r[1]): r for r in got}
    m1 = (1 / 2.0 + 1 / 3.4 + 1 / 4.0 - 1, 1 / 2.1 + 1 / 3.3 + 1 / 3.8 - 1, 1 / 1.5 + 1 / 4.0 + 1 / 7.0 - 1)
    a1x2 = m[(comp_a, "1X2")]
    assert (a1x2[3], a1x2[4], a1x2[5], a1x2[7]) == (2, 3, Decimal("1.5"), 1)
    assert float(a1x2[6]) == pytest.approx(sorted(m1)[1], abs=1e-5)
    assert m[(comp_a, "OU")][2] == Decimal("2.50") and float(m[(comp_a, "OU")][6]) == pytest.approx(2 / 1.9 - 1, abs=1e-5)
    assert (comp_a, "BTTS") in m
    assert m[(comp_b, "1X2")][3:5] == (1, 1)

    first = conn.execute("SELECT first_measured_at FROM market.league_daily_stats WHERE day = %s LIMIT 1", (DAY,)).fetchone()
    again = ld.run_pass(conn, now=NOW + timedelta(days=1), days=[DAY])
    assert again.rows == 4 and rows(conn) == got
    assert conn.execute("SELECT first_measured_at FROM market.league_daily_stats WHERE day = %s LIMIT 1", (DAY,)).fetchone() == first
    assert one(conn, "SELECT count(DISTINCT measured_at) FROM market.league_daily_stats WHERE day = %s", (DAY,)) == 1

    # the owner's reading, and the independent check of the same day
    read = ld.read(conn, since=DAY, until=DAY + timedelta(days=1))
    assert {(r["competition_id"], r["market_key"]) for r in read} == set(m)

    from scripts import market_league_stats

    assert market_league_stats.check(conn, DAY, 20) == 0


def test_a_second_pass_waits_for_the_first(conn: psycopg.Connection, migrated_database: str) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (ld.LOCK,))
        report = ld.run_pass(conn, now=NOW, days=[DAY])
        other.execute("SELECT pg_advisory_unlock(%s)", (ld.LOCK,))
    assert report.stopped == "otro_pase_en_curso" and report.days == 0


def test_the_nightly_process_does_nothing_while_the_switch_is_off(conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from scripts import availability_refresh

    monkeypatch.delenv(ld.SWITCH, raising=False)
    before = one(conn, "SELECT count(*) FROM raw.ingestion_runs WHERE job_type = %s", (ld.JOB,))
    availability_refresh.market_phase(conn, at=NOW, process_started=time.monotonic(), scheduled=True)
    assert one(conn, "SELECT count(*) FROM raw.ingestion_runs WHERE job_type = %s", (ld.JOB,)) == before

    monkeypatch.setenv(ld.SWITCH, "1")
    availability_refresh.market_phase(conn, at=NOW, process_started=time.monotonic(), scheduled=True)
    status = conn.execute("SELECT status, params->'report'->>'method_version' FROM raw.ingestion_runs WHERE job_type = %s "
                          "ORDER BY id DESC LIMIT 1", (ld.JOB,)).fetchone()
    assert status == ("completed", ld.METHOD_VERSION)

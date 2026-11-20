"""PM-02-03: the nightly recalculation of the availability matrix on a real database - the facts of each match (rule 1: both teams),
the cells graded by ``coverage-levels-v1``, the season before inherited (rule 2), the one-match competitions pooled (rule 3), a level
lowered only on the second miss (rule 4), the provider's «no» (rule 5), the history of changes, and a second pass that changes nothing."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import count

import psycopg
import pytest

import fbi.coverage.job as job
from fbi.odds.quote_taxonomy import sync_definitions

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)  # a Sunday: the full pass
_ids = count(900_000)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        for t in ("analytics.coverage_cells", "analytics.market_availability", "analytics.coverage_fixture_facts",
                  "analytics.coverage_changes"):
            c.execute(f"DELETE FROM {t}")
        c.execute("UPDATE core.competitions SET is_tracked = false")
        c.commit()
        yield c


def one(c: psycopg.Connection, sql: str, params: tuple[object, ...] | None = None) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def payload(c: psycopg.Connection) -> str:
    h = f"cov-{next(_ids)}"
    run = one(c, "INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t', 't', 'completed') RETURNING id")
    c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
              "VALUES (%s, %s, '/x', now(), 200, 'x', 1)", (h, run))
    return h


def competition(c: psycopg.Connection, league: int, kind: str = "domestic_league") -> int:
    return one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                  "VALUES (%s, %s, 'league', 'club', %s, true) RETURNING id", (league, f"L{league}", kind))


def season(c: psycopg.Connection, comp: int, year: int) -> int:
    return one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, %s) RETURNING id", (comp, year))


def teams(c: psycopg.Connection) -> tuple[int, int]:
    a = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A') RETURNING id", (next(_ids),))
    b = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'B') RETURNING id", (next(_ids),))
    return a, b


def match(c: psycopg.Connection, cs: int, kickoff: datetime, *, corners: tuple[int | None, int | None] = (5, 4),
          events: bool = True, lineups: bool = True, books: int = 0, h: str) -> int:
    home, away = teams(c)
    fid = one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                 "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
              (next(_ids), cs, home, away, kickoff))
    c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away) "
              "VALUES (%s, 1, 0, 0, 0)", (fid,))
    for side, value in zip(("home", "away"), corners, strict=True):
        c.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, corners, shots, yellow_cards, payload_hash, "
                  "fetched_at) VALUES (%s, %s, 'api-football', %s, 10, 2, %s, now())", (fid, side, value, h))
    if events:
        c.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, payload_hash, fetched_at) "
                  "VALUES (%s, 'api-football', 0, 10, 'home', 'Goal', %s, now())", (fid, h))
    if lineups:
        for side in ("home", "away"):
            c.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                      "VALUES (%s, %s, 'api-football', %s, now())",
                      (fid, side, h))
    for b in range(books):
        book = one(c, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, 'b') "
                      "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name RETURNING id", (7000 + b,))
        for sel in ("Home", "Draw", "Away"):
            c.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
                      "provider_update_at, minutes_to_ko, fetched_at, payload_hash) "
                      "VALUES (%s, %s, '1X2', %s, 0, 2.5, %s, 10, %s, %s)",
                      (fid, book, sel, kickoff - timedelta(hours=1), kickoff - timedelta(minutes=30), h))
    return fid


def cell(c: psycopg.Connection, cs: int, datum: str) -> tuple[object, ...]:
    row = c.execute("SELECT level, measured_level, missed, provisional, reason, n_finished, n_with_data, pooled_seasons, declared_flag "
                    "FROM analytics.coverage_cells WHERE competition_season_id = %s AND datum = %s", (cs, datum)).fetchone()
    assert row is not None, (cs, datum)
    return tuple(row)


def market(c: psycopg.Connection, cs: int, key: str) -> tuple[object, ...]:
    row = c.execute("SELECT level, n_window, n_priced, median_books, n_settleable, reason FROM analytics.market_availability "
                    "WHERE competition_season_id = %s AND market_key = %s", (cs, key)).fetchone()
    assert row is not None, (cs, key)
    return tuple(row)


def test_a_full_pass_grades_every_cell_inherits_and_then_changes_nothing(conn: psycopg.Connection) -> None:
    c = conn
    sync_definitions(c)
    h = payload(c)
    comp = competition(c, 990001)
    old, new = season(c, comp, 2025), season(c, comp, 2026)
    # last season: 40 matches before the odds window, corners for both teams in 39 (one has a side missing: not a zero, not there)
    for i in range(40):
        match(c, old, datetime(2025, 3, 1, tzinfo=UTC) + timedelta(days=i), corners=(5, None) if i == 0 else (5, 4), h=h)
    # this season: 6 matches in the window, priced by 6 houses: short of sample, the season before is inherited, provisional
    for i in range(6):
        match(c, new, datetime(2026, 10, 10, tzinfo=UTC) + timedelta(days=i), books=6, h=h)
    c.execute("INSERT INTO raw.league_coverage (provider_league_id, season, events, lineups, statistics_fixtures, statistics_players, "
              "odds, payload_hash, observed_at) VALUES (990001, 2026, true, true, true, false, true, %s, now())", (h,))
    c.commit()

    r = job.run_pass(c, now=NOW)
    assert r.full and r.stopped is None and r.graded == 2
    assert r.cells == 2 * 10 and r.markets == 2 * 9

    assert cell(c, old, "corners")[:7] == ("A", "A", False, False, None, 40, 39)
    assert cell(c, old, "events")[0] == "A"
    assert cell(c, old, "xg")[:2] == ("D", "D")              # nobody sent xG
    assert cell(c, old, "player_stats")[0] == "D"
    # rule 2: six matches inherit the season before, provisional
    assert cell(c, new, "corners")[:5] == ("A", "A", False, True, "heredado")
    # rule 5: the provider says it does not deliver player statistics and none arrived: D, not inherited
    assert cell(c, new, "player_stats")[:5] == ("D", "D", False, False, "no_entregado")
    assert cell(c, new, "player_stats")[8] is False
    # markets: the season before has no odds window; this one 6 matches, all priced by 6 houses: short of sample
    assert market(c, old, "1X2")[0:3] == ("MI", 0, 0) and market(c, old, "1X2")[5] == "sin_ventana"
    lvl, n_window, n_priced, books, settleable, _ = market(c, new, "1X2")
    assert (n_window, n_priced, float(str(books)), settleable) == (6, 6, 6.0, 6)
    assert lvl == "MI"
    assert market(c, new, "corners")[1:3] == (6, 0)          # nothing priced on corners

    changes = one(c, "SELECT count(*) FROM analytics.coverage_changes WHERE reason = 'primera_medida'")
    assert changes == 2 * 19
    facts = one(c, "SELECT count(*) FROM analytics.coverage_fixture_facts")
    assert facts == 46
    # idempotent: the same data again changes no level and appends nothing
    r2 = job.run_pass(c, now=NOW + timedelta(minutes=5))
    assert r2.changes == 0 and r2.odds_facts == 0
    assert one(c, "SELECT count(*) FROM analytics.coverage_changes") == changes
    assert cell(c, old, "corners")[:7] == ("A", "A", False, False, None, 40, 39)


def test_a_level_goes_down_only_on_the_second_miss_and_the_incremental_pass_takes_recent_competitions(conn: psycopg.Connection) -> None:
    c = conn
    h = payload(c)
    comp = competition(c, 990002)
    cs = season(c, comp, 2026)
    ids = [match(c, cs, datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=i), h=h) for i in range(12)]
    c.commit()
    job.run_pass(c, now=NOW, full=True)
    assert cell(c, cs, "corners")[:3] == ("B", "B", False)  # 12 of 12, below 30 matches
    # the corners disappear from 8 of them (a correction of the provider): measured D
    c.execute("UPDATE core.fixture_team_stats SET corners = NULL WHERE fixture_id = ANY(%s)", (ids[:8],))
    c.commit()
    job.run_pass(c, now=NOW + timedelta(days=1), full=True)
    assert cell(c, cs, "corners")[:3] == ("B", "D", True)   # first miss: kept
    job.run_pass(c, now=NOW + timedelta(days=2), full=True)
    assert cell(c, cs, "corners")[:3] == ("D", "D", False)  # second: lowered
    reasons = [r[0] for r in c.execute("SELECT reason FROM analytics.coverage_changes WHERE competition_season_id = %s "
                                       "AND subject = 'corners' AND kind = 'datum' ORDER BY id", (cs,)).fetchall()]
    assert reasons == ["primera_medida", "incumple_una_vez", "baja"]

    # incremental: no match finished in the last 48 h - nothing in scope
    r = job.run_pass(c, now=NOW + timedelta(days=30), full=False)
    assert r.seasons == 0 and r.graded == 0
    # a new match two hours ago brings the competition back
    match(c, cs, NOW + timedelta(days=30, hours=-2), h=h)
    c.commit()
    r = job.run_pass(c, now=NOW + timedelta(days=30), full=False)
    assert r.seasons == 1 and r.graded == 1 and r.facts >= 1
    assert cell(c, cs, "corners")[5] == 13


def test_a_one_match_competition_pools_its_last_five_editions(conn: psycopg.Connection) -> None:
    c = conn
    h = payload(c)
    comp = competition(c, 990003, "domestic_cup")
    seasons = [season(c, comp, y) for y in range(2020, 2027)]
    for y, cs in zip(range(2020, 2027), seasons, strict=True):
        for leg in range(2):
            match(c, cs, datetime(y, 8, 1 + leg * 7, tzinfo=UTC), h=h)
    c.commit()
    r = job.run_pass(c, now=NOW, full=True)
    assert r.graded == 5                                      # the last five editions
    n, k, pooled = cell(c, seasons[-1], "corners")[5:8]
    assert (n, k, pooled) == (10, 10, 5)                      # 2 matches x 5 editions
    assert cell(c, seasons[-1], "corners")[0] == "B"
    assert cell(c, seasons[-5], "corners")[7] == 1            # the oldest kept edition pools only itself


def test_the_switch_and_the_full_day() -> None:
    assert job.mode({}) == "on"
    assert job.mode({job.SWITCH: "0"}) == "off"
    assert job.mode({job.SWITCH: "off"}) == "off"
    assert job.is_full_day(NOW) and not job.is_full_day(NOW + timedelta(days=1))

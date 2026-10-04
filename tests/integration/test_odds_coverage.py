"""BOOKMAKER_COVERAGE_REPORT on a small built world: one competition per state, three bookmakers,
and the Colombian operators matched by brand. Everything happens in 2031 so nothing other tests
committed falls inside the window; the transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.market.coverage import (
    BookmakerState,
    CompetitionState,
    LocalState,
    build_report,
    is_critical,
    render_markdown,
)
from fbi.market.local_operators import COLJUEGOS_OPERATORS, normalise, provider_match

from .conftest import Seed
from .helpers import scalar

AT = datetime(2031, 3, 10, 12, tzinfo=UTC)


def _book(cur: psycopg.Cursor[Any], pid: int, name: str) -> int:
    cur.execute("SELECT id FROM market.bookmakers WHERE provider_bookmaker_id = %s", (pid,))
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                (pid, name))
    return int(scalar(cur))


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.cur = db.cursor()
        self.next_fixture = 7_310_000
        cur = self.cur
        cur.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive) VALUES "
                    "('OU', 'Over/Under', 2, true, true) ON CONFLICT (key) DO NOTHING")
        self.books = {"Bet365": seed.bookmaker_id, "Betano": _book(cur, 9032, "Betano"),
                      "Bwin": _book(cur, 9006, "Bwin"), "": _book(cur, 9037, "")}

    def competition(self, league: int, name: str, country: str, flag: bool | None) -> int:
        cur = self.cur
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (%s, %s, %s, 'league', 'club', 'domestic_league', true) "
                    "RETURNING id", (league, name, country))
        cid = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                    "VALUES (%s, 2031, true) RETURNING id", (cid,))
        cs = int(scalar(cur))
        if flag is not None:
            cur.execute("INSERT INTO raw.league_coverage (provider_league_id, season, league_name, country, odds, "
                        "payload_hash, observed_at) VALUES (%s, 2031, %s, %s, %s, %s, %s)",
                        (league, name, country, flag, self.seed.payload_hash, AT - timedelta(days=1)))
        return cs

    def played(self, cs: int, days_ago: float, *, asked: bool, prices: dict[str, list[str]] | None = None) -> int:
        cur = self.cur
        self.next_fixture += 1
        kickoff = AT - timedelta(days=days_ago)
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                    "away_team_id, kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', "
                    "'finished') RETURNING id",
                    (self.next_fixture, cs, self.seed.home_team_id, self.seed.away_team_id, kickoff))
        fid = int(scalar(cur))
        if asked:
            cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                        "file_path, bytes) VALUES (%s, %s, '/odds', %s, %s, 200, 'x', 1)",
                        (f"cov-{self.next_fixture}", self.seed.run_id, Jsonb({"fixture": self.next_fixture}),
                         kickoff - timedelta(hours=6)))
        for book, markets in (prices or {}).items():
            for market in markets:
                selections = ("1", "X", "2") if market == "1X2" else ("Over", "Under")
                line = 0 if market == "1X2" else 2.5
                for sel in selections:
                    cur.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, "
                                "line, odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
                                "VALUES (%s, %s, %s, %s, %s, 2.10, %s, 360, 'prematch', %s)",
                                (fid, self.books[book], market, sel, line, kickoff - timedelta(hours=6),
                                 self.seed.payload_hash))
        return fid

    def final(self, fid: int, books: list[str]) -> None:
        cur = self.cur
        cur.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,))
        kickoff = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO market.final_prematch_checks (fixture_id, checked_at, outcome, provider_update_at, "
                    "bookmakers, quotes, payload_hash) VALUES (%s, %s, 'priced', %s, %s, %s, %s)",
                    (fid, kickoff + timedelta(hours=4), kickoff - timedelta(minutes=30), len(books), 3 * len(books),
                     self.seed.payload_hash))
        for book in books:
            for sel in ("1", "X", "2"):
                cur.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, "
                            "line, odds_decimal, provider_update_at, minutes_to_ko, fetched_at, payload_hash) "
                            "VALUES (%s, %s, '1X2', %s, 0, 2.30, %s, 30, %s, %s)",
                            (fid, self.books[book], sel, kickoff - timedelta(minutes=30), kickoff + timedelta(hours=4),
                             self.seed.payload_hash))

    def worker_ran(self, start: datetime, hours: float) -> None:
        """The pick pipeline every 30 minutes, as a running worker starts it."""
        t = start
        while t <= start + timedelta(hours=hours):
            self.cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, started_at) "
                             "VALUES ('pick_pipeline', 'pick_pipeline', %s)", (t,))
            t += timedelta(minutes=30)


def test_each_competition_gets_the_state_its_prices_earned(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    covered = w.competition(97001, "Liga Alfa", "Colombia", True)
    w.played(covered, 3, asked=True, prices={"Bet365": ["1X2", "OU"], "Betano": ["1X2"]})
    w.played(covered, 2, asked=True, prices={"Bet365": ["1X2"], "Betano": ["1X2", "OU"]})
    w.played(covered, 1, asked=False)  # its T-24 h window passed while the worker was running
    w.worker_ran(AT - timedelta(days=2) - timedelta(hours=1), hours=2)  # up across the T-24 h band only
    unpriced = w.competition(97002, "Liga Beta", "Peru", True)
    w.played(unpriced, 3, asked=True)
    w.played(unpriced, 1, asked=True)
    not_asked = w.competition(97003, "Liga Gamma", "Chile", None)
    w.played(not_asked, 2, asked=False)
    not_covered = w.competition(97004, "Liga Delta", "Bolivia", False)
    w.played(not_covered, 2, asked=False)
    partial = w.competition(97005, "Liga Epsilon", "Colombia", True)
    w.played(partial, 4, asked=True, prices={"Bet365": ["1X2"], "Betano": ["1X2"]})
    w.played(partial, 1, asked=True)
    thin = w.competition(97006, "Liga Zeta", "Ecuador", True)
    w.played(thin, 5, asked=True, prices={"Betano": ["1X2"]})
    w.played(thin, 15, asked=True, prices={"Bet365": ["1X2"]})  # outside the 14-day window
    recovered = w.competition(97007, "Liga Eta", "Colombia", True)
    w.final(w.played(recovered, 3.5, asked=False), ["Bet365", "Betano"])  # missed, read after the match

    report = build_report(db, at=AT, days=14)
    mine = {c.competition: c for c in report.competitions if c.competition.startswith("Liga ")}
    assert mine["Liga Alfa"].state is CompetitionState.COVERED
    assert mine["Liga Alfa"].priced_two_plus == 2
    assert mine["Liga Alfa"].markets == {"1X2": 2, "OU": 2}
    assert mine["Liga Alfa"].misses == {"missed_while_up": 1}
    assert mine["Liga Gamma"].misses == {"worker_down": 1}
    eta = mine["Liga Eta"]
    assert (eta.asked, eta.priced, eta.captured, eta.recovered) == (1, 1, 0, 1)
    assert eta.state is CompetitionState.COVERED and eta.misses == {"worker_down": 1}
    assert mine["Liga Beta"].state is CompetitionState.UNPRICED_BY_PROVIDER
    assert mine["Liga Gamma"].state is CompetitionState.NOT_ASKED
    assert mine["Liga Delta"].state is CompetitionState.NOT_COVERED
    assert mine["Liga Epsilon"].state is CompetitionState.PARTIAL
    assert (mine["Liga Epsilon"].priced, mine["Liga Epsilon"].fixtures) == (1, 2)
    assert mine["Liga Zeta"].state is CompetitionState.THIN
    assert mine["Liga Zeta"].fixtures == 1, "a match before the window is not counted"
    critical = is_critical(report)
    assert not any("Liga Gamma" in c for c in critical), "nobody asked, but the machine was off: explained"
    assert any("Liga Alfa" in c and "while the worker was running" in c for c in critical)
    assert not any("Liga Delta" in c for c in critical), "the provider's 'no' is not our gap"
    assert not any("Liga Eta" in c for c in critical), "a machine that was off is not a planner defect"

    books = {b.provider_bookmaker_id: b for b in report.bookmakers}
    assert books[9032].state is BookmakerState.ACTIVE
    assert books[9032].fixtures == 5, "a price read after the match still says the provider has the book"
    assert books[9006].state is BookmakerState.CATALOGUE_ONLY
    assert books[9037].name_missing and books[9037].name == "#9037"

    local = {x.brand: x for x in report.local}
    assert local["Betano"].state is LocalState.PRICED_BY_PROVIDER_BRAND
    assert not local["Betano"].colombian_edition_confirmed
    assert local["bwin"].state is LocalState.CATALOGUE_ONLY
    assert local["Betplay"].state is LocalState.NOT_IN_PROVIDER

    colombia = next(c for c in report.countries if c.country == "Colombia")
    assert (colombia.competitions, colombia.fixtures, colombia.priced, colombia.captured) == (3, 6, 4, 3)
    md = render_markdown(report)
    assert "# BOOKMAKER_COVERAGE_REPORT" in md and "| Liga Gamma 2031 | Chile | NOT_ASKED |" in md


def test_operators_match_by_whole_brand_name() -> None:
    names = {1: "Betano", 2: "BetPlay ", 3: "Stakers", 4: "Rush Bet", 5: "Bwin"}
    by_brand = {op.brand: provider_match(op, names) for op in COLJUEGOS_OPERATORS}
    assert by_brand["Betano"] == [1]
    assert by_brand["Betplay"] == [2]
    assert by_brand["Stake"] == [], "a longer name is a different book"
    assert by_brand["Rushbet"] == [4]
    assert by_brand["bwin"] == [5]
    assert normalise("Méga  Puesta!") == "mega puesta"


def test_the_admin_console_reads_the_coverage_and_a_user_cannot(migrated_database: str) -> None:
    import pytest
    from fastapi.testclient import TestClient

    from fbi.api.app import create_app
    from fbi.api.services import truth as truth_service
    from fbi.core.config import reset_cache
    from tests.integration.signed_in import SAME_SITE, admin_app, signed_in

    truth_service._cache.clear()
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        res = TestClient(admin_app(), headers=SAME_SITE).get("/api/v1/admin/data/odds-coverage", params={"days": 7})
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["days"] == 7
        assert len(data["local"]) == len(COLJUEGOS_OPERATORS)
        access = {s["key"]: s["access"] for s in data["sources"]}
        assert access["api_football"] == "ACTIVE" and access["odds_api_io"] == "PAYMENT_REQUIRED"
        user = TestClient(signed_in(create_app(), "USER"), headers=SAME_SITE)
        assert user.get("/api/v1/admin/data/odds-coverage").status_code == 403
    finally:
        mp.undo()
        reset_cache()
        truth_service._cache.clear()


def test_a_worker_is_up_only_between_two_job_starts() -> None:
    from fbi.market.coverage import Uptime

    t0 = datetime(2031, 1, 1, 18, tzinfo=UTC)
    up = Uptime([t0, t0 + timedelta(minutes=30), t0 + timedelta(minutes=60)])
    assert up.up_at(t0 + timedelta(minutes=45))
    assert not up.up_at(t0 + timedelta(minutes=75)), "stopped after its last job: down, not up for half an hour"
    assert not up.up_at(t0 - timedelta(minutes=10)), "nothing had started yet"


def test_a_moved_kick_off_explains_a_miss_the_planner_could_not_see(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    cs = w.competition(97008, "Liga Theta", "Colombia", True)
    fid = w.played(cs, 1, asked=False)
    w.worker_ran(AT - timedelta(days=2) - timedelta(hours=1), hours=2)
    kickoff = AT - timedelta(days=1)
    w.cur.execute("INSERT INTO core.fixture_kickoff_changes (fixture_id, observed_at, before_kickoff, after_kickoff) "
                  "VALUES (%s, %s, %s, %s)", (fid, kickoff - timedelta(hours=10), kickoff + timedelta(hours=3), kickoff))
    report = build_report(db, at=AT, days=14)
    theta = next(c for c in report.competitions if c.competition == "Liga Theta")
    assert theta.misses == {"kickoff_moved": 1}
    assert not any("Liga Theta" in c for c in is_critical(report))

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


def test_each_competition_gets_the_state_its_prices_earned(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    covered = w.competition(97001, "Liga Alfa", "Colombia", True)
    w.played(covered, 3, asked=True, prices={"Bet365": ["1X2", "OU"], "Betano": ["1X2"]})
    w.played(covered, 2, asked=True, prices={"Bet365": ["1X2"], "Betano": ["1X2", "OU"]})
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

    report = build_report(db, at=AT, days=14)
    mine = {c.competition: c for c in report.competitions if c.competition.startswith("Liga ")}
    assert mine["Liga Alfa"].state is CompetitionState.COVERED
    assert mine["Liga Alfa"].priced_two_plus == 2
    assert mine["Liga Alfa"].markets == {"1X2": 2, "OU": 2}
    assert mine["Liga Beta"].state is CompetitionState.UNPRICED_BY_PROVIDER
    assert mine["Liga Gamma"].state is CompetitionState.NOT_ASKED
    assert mine["Liga Delta"].state is CompetitionState.NOT_COVERED
    assert mine["Liga Epsilon"].state is CompetitionState.PARTIAL
    assert (mine["Liga Epsilon"].priced, mine["Liga Epsilon"].fixtures) == (1, 2)
    assert mine["Liga Zeta"].state is CompetitionState.THIN
    assert mine["Liga Zeta"].fixtures == 1, "a match before the window is not counted"
    assert any("Liga Gamma" in c for c in is_critical(report))
    assert not any("Liga Delta" in c for c in is_critical(report)), "the provider's 'no' is not our gap"

    books = {b.provider_bookmaker_id: b for b in report.bookmakers}
    assert books[9032].state is BookmakerState.ACTIVE
    assert books[9032].fixtures == 4
    assert books[9006].state is BookmakerState.CATALOGUE_ONLY
    assert books[9037].name_missing and books[9037].name == "#9037"

    local = {x.brand: x for x in report.local}
    assert local["Betano"].state is LocalState.PRICED_BY_PROVIDER_BRAND
    assert not local["Betano"].colombian_edition_confirmed
    assert local["bwin"].state is LocalState.CATALOGUE_ONLY
    assert local["Betplay"].state is LocalState.NOT_IN_PROVIDER

    colombia = next(c for c in report.countries if c.country == "Colombia")
    assert (colombia.competitions, colombia.fixtures, colombia.priced) == (2, 4, 3)
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

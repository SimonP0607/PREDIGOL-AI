"""Plan F0, defect 4, on a real database: a parlay with a quarter line settles by the factor of each leg.

The product's builders keep quarter lines out of parlays today, so the rows are written directly - the settlement must be
right the day a market with quarter lines (corner or card handicaps) is opened. The transaction is rolled back afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.picks.product_settlement import settle_products

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 8, 1, 12, tzinfo=UTC)
KICKOFF = AT - timedelta(hours=5)


def _fixture(db: psycopg.Connection[Any], seed: Seed, n: int, result: tuple[int, int] | None) -> int:
    teams = []
    for side in (0, 1):
        teams.append(scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                       (975000 + 2 * n + side, f"Half-{n}-{side}"))))
    status = ("FT", "finished") if result else ("NS", "scheduled")
    fixture = scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
        "status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (7350000 + n, seed.season_id, teams[0], teams[1], KICKOFF if result else AT + timedelta(hours=5), *status)))
    if result:
        db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                   (fixture, *result))
    return int(fixture)


def _parlay(db: psycopg.Connection[Any], user: int, legs: list[tuple[int, str, str, str, str]]) -> int:
    """legs: (fixture, market, selection, line, odds)."""
    parlay = scalar(db.execute("INSERT INTO picks.user_parlays (user_id, created_at, validation, status) "
                               "VALUES (%s, %s, %s, 'READY') RETURNING id", (user, AT - timedelta(days=1), Jsonb({}))))
    for n, (fixture, market, selection, line, odds) in enumerate(legs, start=1):
        db.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, line, "
                   "odds, snapshot) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                   (parlay, n, fixture, market, selection, line, odds, Jsonb({})))
    return int(parlay)


def _outcome(db: psycopg.Connection[Any], parlay: int) -> tuple[str, Decimal | None]:
    row = db.execute("SELECT status, profit_units FROM picks.user_parlays WHERE id = %s", (parlay,)).fetchone()
    assert row is not None
    return row[0], row[1]


def test_a_parlay_with_quarter_lines_settles_by_the_factor_of_each_leg(db: psycopg.Connection[Any], seed: Seed) -> None:
    user = scalar(db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                             "('half@test.local', 'Half', '$argon2id$x') RETURNING id"))
    won = _fixture(db, seed, 1, (1, 0))      # home wins
    drawn = _fixture(db, seed, 2, (0, 0))    # a draw: the quarter lines split here
    open_ = _fixture(db, seed, 3, None)      # not played yet

    # Home +0.25 on a draw: half the stake on "0" pushes, half on "+0.5" wins -> a half win.
    half_win = _parlay(db, int(user), [(won, "1X2", "Home", "0", "2.00"), (drawn, "AH", "Home", "0.25", "1.90")])
    # Home -0.25 on a draw: half pushes, half on "-0.5" loses -> a half loss.
    pays_back = _parlay(db, int(user), [(won, "1X2", "Home", "0", "2.00"), (drawn, "AH", "Home", "-0.25", "1.90")])
    lose_a_bit = _parlay(db, int(user), [(won, "1X2", "Home", "0", "1.50"), (drawn, "AH", "Home", "-0.25", "1.90")])
    waits = _parlay(db, int(user), [(open_, "1X2", "Home", "0", "2.00"), (drawn, "AH", "Home", "-0.25", "1.90")])

    report = settle_products(db, at=AT)

    assert _outcome(db, half_win) == ("PARTIAL_VOID", Decimal("1.9000")), "2.00 * (1.90 + 1) / 2 = 2.90, not 2.00 * 1.90"
    assert _outcome(db, pays_back) == ("VOID", Decimal("0.0000")), "2.00 * 1/2 = 1: the stake comes back"
    assert _outcome(db, lose_a_bit) == ("LOST", Decimal("-0.2500")), "1.50 * 1/2 = 0.75: a quarter of the stake is lost"
    assert _outcome(db, waits) == ("ACTIVE", None), "a half loss does not decide a parlay that still has a leg to play"
    assert report.user_parlays == 3

    legs = dict(db.execute("SELECT fixture_id, status FROM picks.user_parlay_legs WHERE user_parlay_id = %s",
                           (half_win,)).fetchall())
    assert legs[drawn] == "HALF_WIN" and legs[won] == "WIN"

    again = settle_products(db, at=AT + timedelta(hours=1))
    assert again.user_parlays == 0, "a settled parlay is never settled twice"
    assert _outcome(db, half_win) == ("PARTIAL_VOID", Decimal("1.9000"))

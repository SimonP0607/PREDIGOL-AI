"""Change-only storage, and the proof that nothing is lost.

The claim being tested is strong and worth stating precisely: for every instant
the capture observed, market.live_odds_at_instant returns exactly the book that
a writer storing every tick in full would have stored. Not approximately - the
same selections, the same prices, the same suspension flags.

That is only true because two things are recorded that are easy to omit:
market.live_fixture_states keeps every instant observed, and a key that stops
being quoted gets a row with a NULL price. Without the first there is no list of
instants to reconstruct; without the second, carrying a price forward would
report a quote for a market that had gone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg

from fbi.odds.live_repository import LiveOddsRepository, LiveWriteResult
from fbi.providers.api_football.live import LiveFixtureState, LiveOddsQuote
from tests.integration.conftest import Seed

AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
PROVIDER_FIXTURE = 1001
TICK = timedelta(seconds=30)


def state(n: int, **kw: object) -> LiveFixtureState:
    base: dict[str, object] = {
        "provider_fixture_id": PROVIDER_FIXTURE,
        "captured_at": AT + n * TICK,
        "payload_hash": "h1",
        "elapsed_minute": 10 + n,
        "elapsed_seconds": f"{10 + n}:00",
        "score_home": 0,
        "score_away": 0,
        "status_long": "First Half",
        "is_stopped": False,
        "is_blocked": False,
        "is_finished": False,
        "markets_offered": 1,
        "values_offered": 1,
        "values_suspended": 0,
        "provider_updated_at": AT + n * TICK,
    }
    base.update(kw)
    return LiveFixtureState(**base)  # type: ignore[arg-type]


def quote(n: int, odds: str, *, selection: str = "Home", bet: int = 59,
          suspended: bool = False, line: str = "0") -> LiveOddsQuote:
    return LiveOddsQuote(
        provider_fixture_id=PROVIDER_FIXTURE,
        provider_bet_id=bet,
        market_key="1X2" if bet == 59 else None,
        selection=selection,
        line=Decimal(line),
        odds_decimal=Decimal(odds),
        is_suspended=suspended,
        is_main_line=None,
        elapsed_minute=10 + n,
        elapsed_seconds=f"{10 + n}:00",
        score_home=0,
        score_away=0,
        status_long="First Half",
        is_stopped=False,
        is_blocked=False,
        provider_updated_at=AT + n * TICK,
        captured_at=AT + n * TICK,
        payload_hash="h1",
    )


def play(
    repo: LiveOddsRepository, ticks: list[list[LiveOddsQuote]]
) -> list[LiveWriteResult]:
    """Feed the repository one tick at a time, as the capture does."""
    return [repo.write([state(n)], quotes) for n, quotes in enumerate(ticks)]


Row = tuple[datetime, str, Decimal | None, bool]


def stored(conn: psycopg.Connection) -> list[Row]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT captured_at, selection, odds_decimal, is_suspended "
            "FROM market.live_odds_snapshots ORDER BY captured_at, selection"
        )
        return list(cur.fetchall())


def rebuilt(conn: psycopg.Connection) -> list[Row]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT captured_at, selection, odds_decimal, is_suspended "
            "FROM market.live_odds_at_instant ORDER BY captured_at, selection"
        )
        return list(cur.fetchall())


# --- the compression itself -------------------------------------------------


def test_an_unchanged_price_is_not_stored_again(
    db: psycopg.Connection, seed: Seed
) -> None:
    """72.9% of the rows written the old way were this case."""
    repo = LiveOddsRepository(db)
    results = play(repo, [[quote(0, "2.50")], [quote(1, "2.50")], [quote(2, "2.50")]])
    assert [r.quotes_written for r in results] == [1, 0, 0]
    assert [r.quotes_unchanged for r in results] == [0, 1, 1]
    assert len(stored(db)) == 1


def test_a_moved_price_is_stored(db: psycopg.Connection, seed: Seed) -> None:
    repo = LiveOddsRepository(db)
    play(repo, [[quote(0, "2.50")], [quote(1, "2.50")], [quote(2, "2.10")]])
    assert [(r[1], r[2]) for r in stored(db)] == [
        ("Home", Decimal("2.500")), ("Home", Decimal("2.100"))
    ]


def test_a_suspension_at_the_same_price_is_a_change(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A market that stops accepting the bet has changed in the way that
    matters, even when the number on it has not."""
    repo = LiveOddsRepository(db)
    play(repo, [
        [quote(0, "2.50")],
        [quote(1, "2.50", suspended=True)],
        [quote(2, "2.50", suspended=True)],
        [quote(3, "2.50")],
    ])
    assert [(r[2], r[3]) for r in stored(db)] == [
        (Decimal("2.500"), False), (Decimal("2.500"), True), (Decimal("2.500"), False)
    ]


# --- withdrawal, which is what makes it lossless ---------------------------


def test_a_key_that_stops_being_quoted_is_recorded_as_withdrawn(
    db: psycopg.Connection, seed: Seed
) -> None:
    """One measured cycle dropped 325 values as a match wound down. Without
    this row, carrying the last price forward would report a quote for a market
    that had gone - which is inventing data."""
    repo = LiveOddsRepository(db)
    results = play(repo, [[quote(0, "2.50")], []])
    assert results[1].withdrawals_written == 1
    rows = stored(db)
    assert len(rows) == 2
    assert rows[1][2] is None, "the withdrawal carries no price"


def test_a_withdrawn_key_drops_out_of_the_rebuilt_book(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    play(repo, [[quote(0, "2.50")], [], []])
    instants = {r[0] for r in rebuilt(db)}
    assert instants == {AT}, "only the instant it was actually on offer"


def test_a_key_that_returns_is_stored_again(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    play(repo, [[quote(0, "2.50")], [], [quote(2, "2.50")]])
    rows = stored(db)
    assert [r[2] for r in rows] == [Decimal("2.500"), None, Decimal("2.500")], (
        "the same price after a withdrawal is a change, because the market "
        "reopening is the event"
    )
    assert {r[0] for r in rebuilt(db)} == {AT, AT + 2 * TICK}


def test_a_withdrawal_is_recorded_once_not_every_tick(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    results = play(repo, [[quote(0, "2.50")], [], [], []])
    assert [r.withdrawals_written for r in results] == [0, 1, 0, 0]
    assert len(stored(db)) == 2


def test_a_fixture_absent_from_the_payload_withdraws_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A fixture that drops out of the live book has not withdrawn its markets -
    it has finished. Writing withdrawal rows for it would put a timestamp on an
    event nobody saw; the last price stands as the last thing known."""
    repo = LiveOddsRepository(db)
    repo.write([state(0)], [quote(0, "2.50")])
    repo.write([], [])            # the capture saw no fixtures at all
    assert len(stored(db)) == 1


# --- the claim: reconstruction is exact ------------------------------------


def test_the_rebuilt_series_matches_a_full_fidelity_recording(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The whole point, stated as an equality.

    A tick sequence with every behaviour in it: a price that holds, one that
    moves, one that freezes and thaws, a second selection, a withdrawal and a
    return. The rebuilt book at each instant must equal what a writer storing
    every tick in full would have stored - computed here independently of the
    repository.
    """
    ticks: list[list[LiveOddsQuote]] = [
        [quote(0, "2.50"), quote(0, "3.40", selection="Draw")],
        [quote(1, "2.50"), quote(1, "3.40", selection="Draw")],
        [quote(2, "2.10"), quote(2, "3.40", selection="Draw")],
        [quote(3, "2.10", suspended=True)],                      # Draw withdrawn
        [quote(4, "2.10", suspended=True)],
        [quote(5, "2.20"), quote(5, "3.60", selection="Draw")],  # Draw returns
        [quote(6, "2.20"), quote(6, "3.60", selection="Draw")],
    ]
    expected = sorted(
        (q.captured_at, q.selection, q.odds_decimal, q.is_suspended)
        for tick in ticks for q in tick
    )

    repo = LiveOddsRepository(db)
    play(repo, ticks)

    # Stored far fewer rows than the full recording...
    assert len(stored(db)) < len(expected)
    # ...and reconstructs it exactly.
    assert rebuilt(db) == expected


def test_the_compression_on_that_sequence_is_what_it_claims(
    db: psycopg.Connection, seed: Seed
) -> None:
    ticks: list[list[LiveOddsQuote]] = [
        [quote(n, "2.50" if n < 3 else "2.10") for _ in (0,)] for n in range(10)
    ]
    repo = LiveOddsRepository(db)
    play(repo, ticks)
    assert len(stored(db)) == 2, "ten observations, two distinct prices, two rows"
    assert len(rebuilt(db)) == 10, "and all ten instants come back"


def test_carried_forward_marks_the_instants_that_were_not_a_change(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    play(repo, [[quote(0, "2.50")], [quote(1, "2.50")], [quote(2, "2.10")]])
    with db.cursor() as cur:
        cur.execute(
            "SELECT captured_at, carried_forward, priced_at "
            "FROM market.live_odds_at_instant ORDER BY captured_at"
        )
        rows = cur.fetchall()
    assert [r[1] for r in rows] == [False, True, False]
    assert rows[1][2] == AT, "the second instant's price was set at the first"


# --- the movement view tells the kinds apart -------------------------------


def test_the_movement_view_separates_a_withdrawal_from_a_price_move(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    play(repo, [[quote(0, "2.50")], [quote(1, "2.10")], [], [quote(3, "2.10")]])
    with db.cursor() as cur:
        cur.execute(
            "SELECT price_moved, became_withdrawn, became_offered, odds_delta "
            "FROM market.live_market_movement ORDER BY captured_at"
        )
        rows = cur.fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (True, False, False),    # 2.50 -> 2.10
        (False, True, False),    # withdrawn
        (False, False, True),    # offered again
    ]
    assert rows[0][3] == Decimal("-0.400")
    assert rows[1][3] is None, "there is no delta between a price and its absence"
    assert rows[2][3] is None

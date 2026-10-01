"""The in-play series against a real database: append only, and kept apart.

The separation of the two odds series is the invariant this project is built on -
a backtest that reads an in-play price is a backtest that lies - so it is checked
here against the schema rather than trusted to the code that writes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from fbi.odds.live_repository import LiveOddsRepository
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)
from tests.integration.conftest import Seed

AT = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
"""Anchored to the wall clock, not to a date.

LiveOddsRepository.last_known bounds its scan to the last four hours so one
query per capture tick stays cheap. A fixed instant made these tests pass while
it happened to fall inside that window and fail once it did not - a test that
reports on the calendar rather than on the code."""
PROVIDER_FIXTURE = 1001


def state(**kw: object) -> LiveFixtureState:
    base: dict[str, object] = {
        "provider_fixture_id": PROVIDER_FIXTURE,
        "captured_at": AT,
        "payload_hash": "h1",
        "elapsed_minute": 77,
        "elapsed_seconds": "77:00",
        "score_home": 0,
        "score_away": 1,
        "status_long": "Second Half",
        "is_stopped": False,
        "is_blocked": False,
        "is_finished": False,
        "markets_offered": 2,
        "values_offered": 3,
        "values_suspended": 1,
        "provider_updated_at": AT,
    }
    base.update(kw)
    return LiveFixtureState(**base)  # type: ignore[arg-type]


def quote(**kw: object) -> LiveOddsQuote:
    base: dict[str, object] = {
        "provider_fixture_id": PROVIDER_FIXTURE,
        "provider_bet_id": 59,
        "market_key": "1X2",
        "selection": "Home",
        "line": Decimal(0),
        "odds_decimal": Decimal("2.50"),
        "is_suspended": False,
        "is_main_line": None,
        "elapsed_minute": 77,
        "elapsed_seconds": "77:00",
        "score_home": 0,
        "score_away": 1,
        "status_long": "Second Half",
        "is_stopped": False,
        "is_blocked": False,
        "provider_updated_at": AT,
        "captured_at": AT,
        "payload_hash": "h1",
    }
    base.update(kw)
    return LiveOddsQuote(**base)  # type: ignore[arg-type]


def count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        row = cur.fetchone()
        return int(row[0]) if row else 0


# --- the series is complete, because it can never be overwritten ------------


def test_a_second_price_at_a_new_instant_is_a_new_row(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state()], [quote()])
    later = AT + timedelta(seconds=31)
    repo.write(
        [state(captured_at=later)],
        [quote(captured_at=later, odds_decimal=Decimal("2.10"))],
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT captured_at, odds_decimal FROM market.live_odds_snapshots "
            "ORDER BY captured_at"
        )
        rows = cur.fetchall()
    assert [r[1] for r in rows] == [Decimal("2.500"), Decimal("2.100")]


def test_re_running_the_same_capture_writes_nothing_new(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Idempotency is a property of the primary key, so a replayed capture can
    add history but never replace a price.

    Since the series stores only changes, a replay is now caught BEFORE the
    insert - the price matches the last row for its key, so no row is offered -
    and it lands in quotes_unchanged rather than quotes_duplicate. The primary
    key is still the backstop; it just has less to do.
    """
    repo = LiveOddsRepository(db)
    first = repo.write([state()], [quote()])
    second = repo.write([state()], [quote()])
    assert first.quotes_written == 1
    assert second.quotes_written == 0
    assert second.quotes_unchanged == 1
    assert count(db, "market.live_odds_snapshots") == 1


def test_a_price_cannot_be_updated_to_a_different_number(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state()], [quote(odds_decimal=Decimal("2.50"))])
    repo.write([state()], [quote(odds_decimal=Decimal("9.99"))])
    with db.cursor() as cur:
        cur.execute("SELECT odds_decimal FROM market.live_odds_snapshots")
        assert cur.fetchall() == [(Decimal("2.500"),)]


# --- the two series never meet ---------------------------------------------


def test_writing_live_odds_leaves_the_prematch_series_empty(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The guarantee the whole design rests on."""
    before = count(db, "market.odds_snapshots")
    LiveOddsRepository(db).write([state()], [quote()])
    assert count(db, "market.odds_snapshots") == before
    assert count(db, "market.near_close_snapshots") == 0
    assert count(db, "market.live_odds_snapshots") == 1


def test_the_live_table_has_no_bookmaker_column(db: psycopg.Connection) -> None:
    """Measured: no /odds/live fixture carried a bookmakers key. A live price is
    the provider's single aggregated number, which is a different kind of
    observation from a price quoted BY a named book - and the schema says so,
    so nobody can later join the two as if they were comparable."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='market' AND table_name='live_odds_snapshots'"
        )
        columns = {r[0] for r in cur.fetchall()}
    assert "bookmaker_id" not in columns
    assert "elapsed_minute" in columns and "score_home" in columns


# --- what the schema refuses ------------------------------------------------


@pytest.mark.parametrize("bad", [Decimal("1.0"), Decimal("0"), Decimal("1000")])
def test_an_impossible_price_is_refused_by_the_database(
    db: psycopg.Connection, seed: Seed, bad: Decimal
) -> None:
    """Belt and braces: the normaliser refuses these, and so does the table."""
    with pytest.raises(psycopg.errors.CheckViolation):
        LiveOddsRepository(db).write([state()], [quote(odds_decimal=bad)])
    db.rollback()


def test_a_row_cannot_exist_without_the_bytes_it_came_from(
    db: psycopg.Connection, seed: Seed
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        LiveOddsRepository(db).write([state()], [quote(payload_hash="never-stored")])
    db.rollback()


# --- unmapped markets, and fixtures we do not track -------------------------


def test_an_unmapped_market_is_stored_with_a_null_key(
    db: psycopg.Connection, seed: Seed
) -> None:
    """67 of the 72 observed in-play bets have no market of ours. The row is kept
    because /odds/live has no history to re-fetch it from."""
    result = LiveOddsRepository(db).write(
        [state()],
        [quote(provider_bet_id=20, market_key=None, selection="Over",
               line=Decimal("9.5"))],
    )
    assert result.quotes_written == 1
    assert result.unmapped_markets_written == 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT provider_bet_id, market_key, selection, line "
            "FROM market.live_odds_snapshots"
        )
        assert cur.fetchall() == [(20, None, "Over", Decimal("9.50"))]


def test_a_market_key_we_do_not_have_degrades_to_null_instead_of_failing(
    db: psycopg.Connection, seed: Seed
) -> None:
    """One unknown key must not abort a capture that holds a thousand good
    prices - and the provider bet id keeps the row usable."""
    result = LiveOddsRepository(db).write(
        [state()], [quote(market_key="NOT_A_MARKET")]
    )
    assert result.quotes_written == 1
    assert result.unmapped_markets_written == 1


def test_a_fixture_we_do_not_track_is_counted_not_silently_dropped(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The provider prices competitions outside our 122. Those quotes cannot be
    stored - there is no fixture row to hang them on - so the count is reported
    and the capture's accounting still closes."""
    result = LiveOddsRepository(db).write(
        [state(provider_fixture_id=999_999)],
        [quote(provider_fixture_id=999_999)],
    )
    assert result.quotes_written == 0
    assert result.quotes_untracked == 1
    assert result.unknown_fixtures == 1
    assert (
        result.quotes_offered
        == result.quotes_written + result.quotes_duplicate + result.quotes_untracked
    )


# --- the catalogue ----------------------------------------------------------


def test_observing_a_bet_marks_it_in_the_inplay_catalogue_only(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Pre-match bet 59 and in-play bet 59 are different rows, so confirming one
    can never touch the other."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO market.provider_markets "
            "(provider,scope,provider_bet_id,name,source,first_seen_at,last_seen_at) "
            "VALUES ('api-football','inplay',59,'Fulltime Result','catalogue',"
            "        now() - interval '2 days', now() - interval '2 days'), "
            "       ('api-football','prematch',59,'Something Prematch','catalogue',"
            "        now() - interval '2 days', now() - interval '2 days') "
            "ON CONFLICT DO NOTHING"
        )
    LiveOddsRepository(db).record_live_markets(
        [LiveMarketSeen(59, "Fulltime Result", fixtures=1, values=3)]
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT scope, last_seen_at > now() - interval '1 minute' "
            "FROM market.provider_markets WHERE provider_bet_id = 59 ORDER BY scope"
        )
        assert cur.fetchall() == [("inplay", True), ("prematch", False)]


def test_market_coverage_is_derived_from_the_series_not_stored(
    db: psycopg.Connection, seed: Seed
) -> None:
    """How widely a market is offered is read off the prices themselves. A stored
    count would be a second copy of that fact, which is the shape of every defect
    this project has had to repair."""
    repo = LiveOddsRepository(db)
    repo.write(
        [state()],
        [
            quote(provider_bet_id=20, market_key=None, selection="Over",
                  line=Decimal("9.5")),
            quote(provider_bet_id=20, market_key=None, selection="Under",
                  line=Decimal("9.5")),
            quote(),
        ],
    )
    coverage = {bet: (fixtures, values) for bet, _, fixtures, values in
                repo.market_coverage(since_hours=24 * 365)}
    assert coverage[20] == (1, 2)
    assert coverage[59] == (1, 1)


def test_fixtures_in_play_ignores_a_finished_match(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Reads the wall clock, so the captures are placed relative to it rather
    than at a fixed instant that drifts out of the window as time passes."""
    with db.cursor() as cur:
        cur.execute("SELECT now()")
        row = cur.fetchone()
        assert row is not None
        wall: datetime = row[0]
    repo = LiveOddsRepository(db)
    repo.write([state(captured_at=wall - timedelta(minutes=1), is_finished=True)], [])
    assert repo.fixtures_in_play(within_minutes=60) == 0
    repo.write([state(captured_at=wall, is_finished=False)], [])
    assert repo.fixtures_in_play(within_minutes=60) == 1


# --- LIVE MARKET MOVEMENT: derived, and only where something moved ----------


def write_series(
    repo: LiveOddsRepository, prices: list[tuple[int, str, bool, int, int]]
) -> None:
    """(offset seconds, odds, suspended, score_home, score_away) for one selection."""
    for offset, odds, suspended, home, away in prices:
        when = AT + timedelta(seconds=offset)
        repo.write(
            [state(captured_at=when, score_home=home, score_away=away)],
            [
                quote(
                    captured_at=when,
                    odds_decimal=Decimal(odds),
                    is_suspended=suspended,
                    score_home=home,
                    score_away=away,
                )
            ],
        )


def movement_rows(conn: psycopg.Connection) -> list[tuple[object, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT previous_odds, odds, odds_delta, score_changed, "
            "       became_suspended, became_available, seconds_elapsed "
            "FROM market.live_market_movement ORDER BY captured_at"
        )
        return list(cur.fetchall())


def test_a_price_that_did_not_move_produces_no_movement_row(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The provider sweeps its whole book every ~31 s and only about 27% of
    prices move, so most consecutive snapshots carry the same number. 20.9% did
    not move at all across a two-minute measurement. The snapshot series keeps
    them - they are observations - and this view does not, because a reader
    asking "when did this move" must not have to filter out when it did not.
    """
    write_series(LiveOddsRepository(db), [(0, "2.50", False, 0, 1),
                                          (31, "2.50", False, 0, 1),
                                          (62, "2.50", False, 0, 1)])
    assert movement_rows(db) == []


def test_each_change_is_one_row_against_the_price_it_replaced(
    db: psycopg.Connection, seed: Seed
) -> None:
    write_series(LiveOddsRepository(db), [(0, "2.50", False, 0, 1),
                                          (31, "2.50", False, 0, 1),
                                          (62, "2.10", False, 0, 1),
                                          (93, "2.20", False, 0, 1)])
    rows = movement_rows(db)
    assert len(rows) == 2
    assert (rows[0][0], rows[0][1]) == (Decimal("2.500"), Decimal("2.100"))
    assert (rows[1][0], rows[1][1]) == (Decimal("2.100"), Decimal("2.200"))
    assert rows[0][2] == Decimal("-0.400"), "the delta is against the previous price"
    assert rows[0][6] == Decimal("62.000"), (
        "elapsed since the price was SET, not since the last observation - the "
        "unchanged tick at 31s is not a row, and saying the move took 31s would "
        "be claiming the price held until then when nothing says it did not"
    )


def test_a_goal_between_two_observations_is_marked(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The explanation for most large moves, which is why the score rides on
    every snapshot row rather than being joined at read time."""
    write_series(LiveOddsRepository(db), [(0, "2.60", False, 1, 1),
                                          (31, "8.00", False, 1, 2)])
    rows = movement_rows(db)
    assert len(rows) == 1
    assert rows[0][3] is True, "score_changed"


def test_a_move_with_no_goal_is_not_marked(db: psycopg.Connection, seed: Seed) -> None:
    write_series(LiveOddsRepository(db), [(0, "2.60", False, 1, 1),
                                          (31, "2.70", False, 1, 1)])
    assert movement_rows(db)[0][3] is False


def test_freezing_and_reopening_are_movement_even_at_the_same_price(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Measured: up to 96 values thawed in a single provider sweep. A market
    that stops accepting the bet has moved in the way that matters, even when
    the number on it is unchanged."""
    write_series(LiveOddsRepository(db), [(0, "2.50", False, 0, 1),
                                          (31, "2.50", True, 0, 1),
                                          (62, "2.50", False, 0, 1)])
    rows = movement_rows(db)
    assert len(rows) == 2
    assert (rows[0][4], rows[0][5]) == (True, False), "froze"
    assert (rows[1][4], rows[1][5]) == (False, True), "thawed"


def test_the_implied_probability_delta_is_what_ranks_a_move(
    db: psycopg.Connection, seed: Seed
) -> None:
    """2.00 -> 1.90 is a bigger move than 10.0 -> 9.90; the raw odds delta says
    the opposite, which is why both are exposed and the probability one is what
    the reader orders by."""
    repo = LiveOddsRepository(db)

    def tick(offset: int, home: str, over: str) -> None:
        """Both selections on every tick.

        They have to be: a key missing from a capture is a WITHDRAWAL now, so
        quoting only the Over would close the 1X2 market and the comparison
        would be against a withdrawal row instead of a price.
        """
        when = AT + timedelta(seconds=offset)
        repo.write(
            [state(captured_at=when)],
            [
                quote(captured_at=when, odds_decimal=Decimal(home)),
                quote(captured_at=when, provider_bet_id=36, market_key="OU",
                      selection="Over", line=Decimal("2.5"),
                      odds_decimal=Decimal(over)),
            ],
        )

    tick(0, "2.00", "10.00")
    tick(31, "1.90", "9.90")
    with db.cursor() as cur:
        cur.execute(
            "SELECT market_key, abs(odds_delta), abs(implied_prob_delta) "
            "FROM market.live_market_movement ORDER BY abs(implied_prob_delta) DESC"
        )
        rows = cur.fetchall()
    assert rows[0][0] == "1X2", "the short-odds move ranks first on probability"
    assert rows[0][1] == rows[1][1], "despite an identical odds delta"
    assert rows[0][2] > rows[1][2]


def test_the_movement_reader_returns_the_newest_first(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    write_series(repo, [(0, "2.50", False, 0, 1), (31, "2.10", False, 0, 1)])
    # The view is time-filtered against now(), and AT may be older than the
    # default window, so ask for a wide one.
    moves = repo.movements(since_minutes=60 * 24 * 365)
    assert len(moves) == 1
    m = moves[0]
    assert (m.previous_odds, m.odds) == (Decimal("2.500"), Decimal("2.100"))
    assert m.provider_fixture_id == PROVIDER_FIXTURE
    assert m.market_key == "1X2"
    assert m.implied_prob_delta > 0, "a shorter price is a higher probability"


def test_unmapped_markets_are_excluded_unless_asked_for(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    for offset, odds in ((0, "1.85"), (31, "1.75")):
        when = AT + timedelta(seconds=offset)
        repo.write(
            [state(captured_at=when)],
            [quote(captured_at=when, provider_bet_id=20, market_key=None,
                   selection="Over", line=Decimal("9.5"),
                   odds_decimal=Decimal(odds))],
        )
    year = 60 * 24 * 365
    assert repo.movements(since_minutes=year) == []
    unmapped = repo.movements(mapped_only=False, since_minutes=year)
    assert len(unmapped) == 1
    assert unmapped[0].market_key is None
    assert unmapped[0].provider_bet_id == 20


def test_movement_is_a_view_so_there_is_nothing_to_keep_in_sync(
    db: psycopg.Connection,
) -> None:
    """Storing movement would be a second copy of a fact derived from the
    snapshot series - the shape of every defect this project has repaired."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = 'market' AND table_name = 'live_market_movement'"
        )
        row = cur.fetchone()
    assert row is not None and row[0] == "VIEW"


def test_competition_coverage_answers_which_leagues_were_seen_in_play(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Coverage by competition, measured from what arrived rather than assumed
    from the plan - the user-facing question "which of my 124 competitions does
    this provider actually price live".

    This reader shipped with a join onto tables that do not exist
    (core.seasons, core.leagues) and the first `capture_live.py coverage` run
    found it. Its sibling market_coverage was tested and this one was not, which
    is the whole reason it got through.
    """
    repo = LiveOddsRepository(db)
    repo.write([state()], [quote()])
    rows = repo.competition_coverage(since_hours=24 * 365)
    assert rows, "the seeded fixture's competition must appear"
    league_id, name, fixtures = rows[0]
    assert league_id == 39 and name == "Premier League"
    assert fixtures == 1


def test_competition_coverage_is_empty_before_anything_is_captured(
    db: psycopg.Connection, seed: Seed
) -> None:
    assert LiveOddsRepository(db).competition_coverage(since_hours=1) == []

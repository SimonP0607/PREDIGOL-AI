"""``market-signals-v1`` (IA-011, shadow): the market's signals of a selection are numbers computed from the captured prices - the
series by the consensus' own de-vigging, the movement, the velocity, the steam, the staleness, the side relative to the model, the sharp
reference that does not exist yet, and the CLV after kick-off by the system's one definition."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.domain.market_probability import DevigMethod
from fbi.market import closing_value
from fbi.market import signals as s
from fbi.market.closing_reference import Close
from fbi.market.consensus import BookQuote, consensus
from fbi.providers.odds_sources import ODDS_SOURCES, Access

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
KO = T0 + timedelta(hours=24)
KEY = (7, "1X2", "Home", Decimal(0))


def book(b: int, home: str, draw: str, away: str) -> list[BookQuote]:
    return [BookQuote(b, "1X2", "Home", Decimal(0), Decimal(home)), BookQuote(b, "1X2", "Draw", Decimal(0), Decimal(draw)),
            BookQuote(b, "1X2", "Away", Decimal(0), Decimal(away))]


def cap(minutes: float, *books: list[BookQuote], h: str | None = None) -> s.Capture:
    return s.Capture(T0 + timedelta(minutes=minutes), h or f"h{minutes}", tuple(q for b in books for q in b))


def pt(minutes: float, p: float, books: dict[int, float] | None = None, n: int = 3) -> s.Point:
    return s.Point(T0 + timedelta(minutes=minutes), p, Decimal("2.0"), 1, n, None,
                   tuple(sorted((books or {}).items())))


def shin(quotes: list[BookQuote], selection: str = "Home", line: Decimal = Decimal(0)) -> float:
    return next(r.p_fair for r in consensus(quotes, (DevigMethod.SHIN,)) if r.selection == selection and r.line == line)


# ── the series is the consensus' own numbers ────────────────────────────────────────────────────────────────────────────

def test_a_point_is_the_shin_consensus_of_the_capture_and_each_books_own_fair_probability() -> None:
    a, b = book(1, "2.00", "3.40", "3.80"), book(2, "2.10", "3.30", "3.60")
    p = s.point_of(cap(0, a, b), "Home", Decimal(0))
    assert p is not None
    row = next(r for r in consensus(a + b, (DevigMethod.SHIN,)) if r.selection == "Home")
    assert (p.p_fair, p.n_bookmakers, p.dispersion, p.best_odds, p.best_bookmaker_id) == \
        (row.p_fair, 2, row.dispersion, Decimal("2.10"), 2), "no de-vigging of its own: the stored consensus' function"
    assert p.books == ((1, shin(a)), (2, shin(b)))


def test_an_incomplete_book_prices_nothing_and_is_not_guessed() -> None:
    half = [q for q in book(1, "2.00", "3.40", "3.80") if q.selection != "Away"]
    assert s.point_of(cap(0, half), "Home", Decimal(0)) is None
    assert s.series([cap(0, half)], "Home", Decimal(0)) == ()


def test_an_asian_handicap_away_side_is_read_at_its_own_opposite_line() -> None:
    quotes = (BookQuote(1, "AH", "Home", Decimal("-0.5"), Decimal("1.90")),
              BookQuote(1, "AH", "Away", Decimal("0.5"), Decimal("1.95")))
    away = s.point_of(s.Capture(T0, "h", quotes), "Away", Decimal("0.5"))
    assert away is not None and away.books == ((1, away.p_fair),)
    assert s.point_of(s.Capture(T0, "h", quotes), "Away", Decimal("-0.5")) is None


# ── as of a moment ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_only_captures_at_or_before_the_moment_and_before_kickoff_are_known() -> None:
    caps = [cap(0, book(1, "2.00", "3.40", "3.80")), cap(60, book(1, "1.90", "3.50", "4.00")),
            cap(120, book(1, "1.70", "3.80", "4.80")), s.Capture(KO, "live", tuple(book(1, "1.20", "6.0", "12.0")))]
    at = T0 + timedelta(minutes=60)
    got = s.market_signals(caps, KEY, at=at, kickoff_at=KO)
    assert got.n_captures == 2 and got.current is not None and got.current.at == at, "a capture AT the moment is known"
    assert got.current.p_fair == shin(book(1, "1.90", "3.50", "4.00")), "the later one was not known yet"
    after = s.market_signals(caps, KEY, at=KO + timedelta(hours=2), kickoff_at=KO)
    assert after.n_captures == 3 and after.effective_at == KO, "the capture at kick-off is not pre-match"
    assert after.staleness_minutes == pytest.approx(22 * 60), "staleness is measured to kick-off, not past it"


def test_no_prices_is_said_and_nothing_is_filled_in() -> None:
    got = s.market_signals([], KEY, at=T0, kickoff_at=KO, p_model=0.6)
    assert (got.status, got.opening, got.current, got.movement_points, got.side, got.stale, got.steam) == \
        (s.NO_PRICES, None, None, None, None, None, False)
    assert [v.status for v in got.velocities] == [s.NO_PRICES] * 3
    json.dumps(got.as_json())


def test_one_capture_is_its_own_opening_flat_with_no_velocity() -> None:
    got = s.market_signals([cap(0, book(1, "2.00", "3.40", "3.80"))], KEY, at=T0 + timedelta(minutes=30),
                           kickoff_at=KO, p_model=0.7)
    assert got.opening == got.current and got.movement_points == 0.0 and got.side == s.FLAT
    assert [v.status for v in got.velocities] == [s.SERIES_YOUNGER] * 3


def test_one_book_has_no_dispersion_and_cannot_steam() -> None:
    caps = [cap(0, book(1, "2.00", "3.40", "3.80")), cap(30, book(1, "1.60", "4.00", "6.00"))]
    got = s.market_signals(caps, KEY, at=T0 + timedelta(minutes=30), kickoff_at=KO)
    assert got.current is not None and (got.current.n_bookmakers, got.current.dispersion) == (1, None)
    assert got.movement_points is not None and got.movement_points > 5 and not got.steam


def test_a_price_older_than_three_hours_is_stale() -> None:
    caps = [cap(0, book(1, "2.00", "3.40", "3.80"))]
    assert s.market_signals(caps, KEY, at=T0 + timedelta(minutes=180), kickoff_at=KO).stale is False
    old = s.market_signals(caps, KEY, at=T0 + timedelta(minutes=181), kickoff_at=KO)
    assert old.stale is True and old.staleness_minutes == pytest.approx(181)


def test_opening_and_movement_in_points() -> None:
    first, last = book(1, "2.00", "3.40", "3.80"), book(1, "1.80", "3.60", "4.40")
    got = s.market_signals([cap(0, first), cap(90, last)], KEY, at=T0 + timedelta(hours=2), kickoff_at=KO, p_model=0.6)
    assert got.opening is not None and got.opening.best_odds == Decimal("2.00") and got.opening.at == T0
    assert got.movement_points == pytest.approx((shin(last) - shin(first)) * 100)
    assert got.side == s.TOWARD, "the model saw Home likelier than the opening and the market shortened it"


# ── velocity ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_velocity_is_current_minus_the_last_point_before_the_window() -> None:
    points = [pt(0, 0.40), pt(300, 0.42), pt(420, 0.45), pt(470, 0.46)]
    at = T0 + timedelta(minutes=480)
    one = s.velocity(points, at=at, window=timedelta(hours=1))
    assert (one.status, one.reference_at, one.captures_in_window) == (s.OK, T0 + timedelta(minutes=420), 1)
    assert one.delta_points == pytest.approx(1.0) and one.per_hour == pytest.approx(1.0)
    six = s.velocity(points, at=at, window=timedelta(hours=6))
    assert six.delta_points == pytest.approx(6.0) and six.per_hour == pytest.approx(1.0)
    day = s.velocity(points, at=at, window=timedelta(hours=24))
    assert (day.status, day.delta_points) == (s.SERIES_YOUNGER, None), "never extrapolated past the opening"


def test_a_window_with_no_capture_says_so() -> None:
    v = s.velocity([pt(0, 0.40), pt(60, 0.41)], at=T0 + timedelta(hours=5), window=timedelta(hours=1))
    assert (v.status, v.delta_points, v.captures_in_window) == (s.NO_CAPTURE_IN_WINDOW, None, 0)
    assert s.velocity([], at=T0, window=timedelta(hours=1)).status == s.NO_PRICES


# ── steam ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_steam_is_three_books_moving_three_points_the_same_way_within_an_hour() -> None:
    before = pt(0, 0.50, {1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50})
    after = pt(60, 0.535, {1: 0.54, 2: 0.535, 3: 0.531, 4: 0.51})
    (event,) = s.steam_events([before, after])
    assert (event.at, event.direction, event.books) == (after.at, s.UP, (1, 2, 3))
    assert event.median_move_points == pytest.approx(3.5)


@pytest.mark.parametrize(("why", "later"), [
    ("only two books moved", pt(30, 0.54, {1: 0.55, 2: 0.55, 3: 0.51})),
    ("a move of two points is not steam", pt(30, 0.52, {1: 0.52, 2: 0.52, 3: 0.52})),
    ("61 minutes between the captures: perhaps gradual", pt(61, 0.56, {1: 0.56, 2: 0.56, 3: 0.56})),
    ("the books moved opposite ways", pt(30, 0.50, {1: 0.55, 2: 0.55, 3: 0.45})),
])
def test_what_is_not_steam(why: str, later: s.Point) -> None:
    assert s.steam_events([pt(0, 0.50, {1: 0.50, 2: 0.50, 3: 0.50}), later]) == (), why


def test_steam_down_and_a_book_measured_against_its_own_previous_capture() -> None:
    a = pt(0, 0.50, {1: 0.50, 2: 0.50})
    b = pt(20, 0.50, {3: 0.50})  # book 3 is seen first here
    c = pt(50, 0.46, {1: 0.46, 2: 0.46, 3: 0.46})
    (event,) = s.steam_events([a, b, c])
    assert (event.direction, event.books) == (s.DOWN, (1, 2, 3))


def test_steam_through_the_signals() -> None:
    def three(home: str, away: str) -> list[list[BookQuote]]:
        return [book(b, home, "3.40", away) for b in (1, 2, 3)]
    caps = [cap(0, *three("2.00", "3.80")), cap(30, *three("1.70", "4.80"))]
    got = s.market_signals(caps, KEY, at=T0 + timedelta(minutes=30), kickoff_at=KO)
    assert got.steam and got.steam_events[0].direction == s.UP and len(got.steam_events[0].books) == 3


# ── side ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("p_model", "p_open", "p_now", "expected"), [
    (0.60, 0.50, 0.53, s.TOWARD), (0.40, 0.50, 0.47, s.TOWARD), (0.60, 0.50, 0.47, s.AGAINST),
    (0.40, 0.50, 0.53, s.AGAINST), (0.60, 0.50, 0.504, s.FLAT), (0.502, 0.50, 0.53, s.AGAINST),
    (0.60, 0.50, 0.65, s.TOWARD), (None, 0.50, 0.53, None), (0.60, None, None, None),
])
def test_the_side_the_market_moved_relative_to_the_model(p_model: float | None, p_open: float | None, p_now: float | None,
                                                         expected: str | None) -> None:
    assert s.side(p_model, p_open, p_now) == expected


# ── sharp reference ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_sharp_source_is_enabled_so_the_reference_is_none() -> None:
    ref = s.sharp_reference()
    assert (ref.status, ref.p_fair, ref.source) == (s.NO_SHARP_SOURCE, None, None)


def test_an_enabled_sharp_source_is_still_not_read_by_this_version() -> None:
    from dataclasses import replace

    betfair = next(p for p in ODDS_SOURCES if p.key == "betfair_exchange")
    ref = s.sharp_reference([replace(betfair, access=Access.ACTIVE)])
    assert (ref.status, ref.p_fair, ref.source) == (s.SHARP_NOT_READ, None, "betfair_exchange")


# ── closing-line value ─────────────────────────────────────────────────────────────────────────────────────────────────

CLOSE = Close(0.52, 1.95, KO - timedelta(minutes=40), 40)


def test_clv_exists_only_after_kickoff_and_is_the_systems_one_definition() -> None:
    assert s.closing_value_of(2.10, CLOSE, at=KO - timedelta(minutes=1), kickoff_at=KO).status == s.BEFORE_KICKOFF
    got = s.closing_value_of(2.10, CLOSE, at=KO, kickoff_at=KO)
    assert (got.status, got.clv, got.quality) == (s.OK, closing_value.clv(2.10, 0.52), "GOOD")
    assert got.as_json()["close"]["reference"] == "last-shin-consensus-before-kickoff"
    assert s.closing_value_of(None, CLOSE, at=KO, kickoff_at=KO).status == s.NO_TAKEN_PRICE
    missing = s.closing_value_of(2.10, None, at=KO, kickoff_at=KO)
    assert (missing.status, missing.clv, missing.quality) == (s.NO_CLOSE, None, "UNKNOWN")


# ── the summary ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_summary_counts_with_its_denominators() -> None:
    def three(home: str) -> list[list[BookQuote]]:
        return [book(b, home, "3.40", "3.80") for b in (1, 2, 3)]
    rising = [cap(0, *three("2.00")), cap(30, *three("1.70"))]
    later = KO + timedelta(hours=3)
    rows = [
        s.market_signals(rising, KEY, at=later, kickoff_at=KO, p_model=0.40, taken_odds=2.0, close=CLOSE),  # against + steam
        s.market_signals(rising, KEY, at=later, kickoff_at=KO, p_model=0.70, taken_odds=2.2, close=CLOSE),  # toward
        s.market_signals(rising, KEY, at=later, kickoff_at=KO),  # no model: no side
        s.market_signals([], KEY, at=later, kickoff_at=KO, p_model=0.5),  # no prices
    ]
    summary = s.summarise(rows)
    assert (summary.selections, summary.priced, summary.sided, summary.against, summary.toward, summary.flat) == (4, 3, 2, 1, 1, 0)
    assert summary.against_share == 0.5 and summary.with_steam == 3 and summary.steam_events == 3
    assert summary.median_movement_points == pytest.approx(rows[0].movement_points)
    assert summary.clv_n == 2 and summary.clv_median == pytest.approx((2.0 * 0.52 - 1 + 2.2 * 0.52 - 1) / 2)
    assert s.summarise([]).against_share is None
    json.dumps(summary.as_json())


# ── the constants ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_constants_that_mirror_the_decision_layer_stay_equal_to_it() -> None:
    from fbi.intel import decision

    assert s.STALE_AFTER == decision.MAX_PRICE_AGE
    assert s.STEAM_MIN_BOOKS == decision.MIN_BOOKS
    assert s.METHOD.value == "shin"
    assert s.VERSION == "market-signals-v1"


def test_the_report_is_plain_json_and_names_its_constants() -> None:
    got = s.market_signals([cap(0, book(1, "2.00", "3.40", "3.80"))], KEY, at=T0, kickoff_at=KO, p_model=0.5)
    doc = json.loads(json.dumps(got.as_json()))
    assert doc["shadow"] is True and doc["sharp"]["status"] == s.NO_SHARP_SOURCE
    assert doc["constants"]["steam_min_points"] == s.STEAM_MIN_POINTS and doc["closing"]["status"] == s.BEFORE_KICKOFF


def test_the_command_line_refuses_an_instant_without_a_zone() -> None:
    from scripts import ia_market_signals as cli

    assert cli.parse_at("2026-11-06T18:00:00Z") == datetime(2026, 11, 6, 18, tzinfo=UTC)
    with pytest.raises(ValueError, match="zone"):
        cli.parse_at("2026-11-06T18:00:00")
    with pytest.raises(ValueError):
        cli.parse_line("x")
    got = s.market_signals([cap(0, book(1, "2.00", "3.40", "3.80"))], KEY, at=T0, kickoff_at=KO, p_model=0.5)
    assert "1X2 Home 0" in cli.render("show", got.as_json() | {"decision": None})

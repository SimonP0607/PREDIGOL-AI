"""Market signals in SHADOW (``market-signals-v1``, IA-011): what the captured prices of a selection did, as numbers.

The models produce probabilities; the market's signals are NUMBERS computed deterministically from the prices we captured
(``market.odds_snapshots``). Nothing here is an opinion and nothing here asks a model, a provider or an LLM. And nothing
here is read by a decision: ``fbi.intel.decision``, ``fbi.picks``, ``fbi.familydecisions`` and ``fbi.api`` never import
this module (``tests/unit/test_market_signals_isolation.py`` holds the door shut). The signals are computed and reported -
by ``python -m scripts.ia_market_signals`` - and no pick, stake, filter or page a user can open moves because of them.

For ONE selection (fixture, market, selection, line) AS OF a moment ``at``:

    the series         one point per capture (one provider answer at one instant, ``(payload_hash, captured_at)``) holding
                       the selection: its de-vigged fair probability, averaged across the books of that answer, by the SAME
                       code as the stored consensus (``fbi.market.consensus.consensus``, Shin) - this module does no
                       de-vigging of its own. Each book's own fair probability is kept too (the same function, one book at a
                       time), because a steam move is a move ACROSS books. Only captures at or before ``at`` and before
                       kick-off are read: what was known then, and the pre-match market only.
    opening            the first point: fair probability, best price and its book.
    current            the last point: fair probability, best price and its book, books, dispersion across books.
    movement           current minus opening fair probability, in POINTS (one point = 0.01 of probability).
    velocity           the change of the fair probability over the last 1 h / 6 h / 24 h (``VELOCITY_WINDOWS``): current
                       minus the last point at or before ``at - window``. None, with the reason, when nothing was captured
                       inside the window or the series is younger than it - never an extrapolation.
    steam              at least ``STEAM_MIN_BOOKS`` books moved their own fair probability by at least ``STEAM_MIN_POINTS``
                       in the same direction between two of their captures at most ``STEAM_MAX_MINUTES`` apart.
    staleness          minutes from the current point to ``min(at, kick-off)``; ``stale`` past ``STALE_AFTER``.
    side               the direction the market moved relative to a given model probability: ``toward`` / ``against`` /
                       ``flat`` (``SIDE_FLAT_POINTS``), or None with no model probability or no prices.
    sharp reference    None with status ``no_sharp_source`` while no sharp source is enabled
                       (``fbi.providers.odds_sources.enabled_sources``): the shape is ready, no number is invented.
    closing value      after kick-off only: the CLV of a taken price against the closing fair probability, by the system's
                       one definition (``fbi.market.closing_value.clv``) at the system's one reference
                       (``fbi.market.closing_reference``). This module repeats neither.

PROBABILITIES ARE CONDITIONAL ON SETTLEMENT, as everywhere in the market layer: on a line that can push a two-way book
de-vigs to P(win | settled) (see ``fbi.market.consensus``). A model probability given for ``side`` must be on the same
basis - ``intel.decisions.p_model`` / ``p_cal`` are (``fbi.picks.engine`` stores the conditional one).

The constants are engineering choices, not measurements, and they are versioned: changing one is ``market-signals-v2``.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core.decision_versions import DECISION_CORE
from fbi.domain.market_probability import DevigMethod
from fbi.market import closing_reference, closing_value
from fbi.market.closing_reference import Close, Key
from fbi.market.consensus import BookQuote, ConsensusRow, consensus
from fbi.providers.odds_sources import OddsSourceProfile, enabled_sources

VERSION: Final = "market-signals-v1"

METHOD: Final = DevigMethod.SHIN
"""The de-vigging method of every number here: the one the decision layer and the closing reference read
(``devig_method = 'shin'``), so a movement here and a price there are on the same scale."""

POINTS: Final = 100.0
"""One point is 0.01 of probability: a fair probability moving from 0.50 to 0.53 moved 3 points."""

VELOCITY_WINDOWS: Final = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))
"""The windows the velocity is read over. Engineering choice: the capture windows of the pre-match series are hours
apart far from kick-off and tighter near it, so 1 h says "right now", 6 h "today" and 24 h "since yesterday"."""

STEAM_MIN_POINTS: Final = 3.0
"""Points a book's own fair probability must move, between two of its captures, to count towards steam. Engineering
choice: the books' de-vigged probabilities of one answer typically sit within a point or two of each other, so three
points is a move no ordinary re-quote explains."""

STEAM_MAX_MINUTES: Final = 60
"""The longest gap, in minutes, between the two captures of a book across which its move counts as sudden. A move seen
across a wider gap may have been gradual, and cannot be called steam on the evidence. Engineering choice."""

STEAM_MIN_BOOKS: Final = 3
"""Books that must move the same way within the same capture for steam: one book moving is that book; several at once
is the market. Three is the decision layer's own minimum of books for a price (``fbi.intel.decision.MIN_BOOKS``)."""

SIDE_FLAT_POINTS: Final = 0.5
"""A movement smaller than this (in points, either way) is ``flat``: half a point is inside the noise of re-quoting.
Engineering choice."""

STALE_AFTER: Final = timedelta(hours=3)
"""A current point older than this is ``stale``: the decision layer's own limit for a current price
(``fbi.intel.decision.MAX_PRICE_AGE``, filter 3; a unit test holds the two equal without this module importing it)."""

SHARP_SOURCE_KEYS: Final = frozenset({"betfair_exchange", "pinnacle_api"})
"""Sources of ``fbi.providers.odds_sources`` that would be a sharp reference. None is enabled (owner decision): the
reference is then None with status ``no_sharp_source``."""

NO_SHARP_SOURCE: Final = "no_sharp_source"
SHARP_NOT_READ: Final = "sharp_source_not_read"
"""A sharp source enabled but not yet read by this version: still None - wiring it is ``market-signals-v2``."""

# statuses
OK: Final = "ok"
NO_PRICES: Final = "no_prices"
NO_CAPTURE_IN_WINDOW: Final = "no_capture_in_window"
SERIES_YOUNGER: Final = "series_younger_than_window"
BEFORE_KICKOFF: Final = "before_kickoff"
NO_TAKEN_PRICE: Final = "no_taken_price"
NO_CLOSE: Final = "no_close"
TOWARD, AGAINST, FLAT = "toward", "against", "flat"
UP, DOWN = "up", "down"


# ── plain values ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Capture:
    """One provider answer at one instant: every book's quotes of the market in it."""

    captured_at: datetime
    payload_hash: str
    quotes: tuple[BookQuote, ...]


@dataclass(frozen=True, slots=True)
class Point:
    """The selection at one capture: the consensus of the books of that answer, and each book's own fair probability."""

    at: datetime
    p_fair: float
    best_odds: Decimal
    best_bookmaker_id: int
    n_bookmakers: int
    dispersion: float | None
    books: tuple[tuple[int, float], ...]
    """(bookmaker_id, that book's own fair probability), by bookmaker."""


@dataclass(frozen=True, slots=True)
class Velocity:
    window: timedelta
    status: str
    delta_points: float | None
    reference_at: datetime | None
    captures_in_window: int

    @property
    def per_hour(self) -> float | None:
        return None if self.delta_points is None else self.delta_points / (self.window.total_seconds() / 3600)

    def as_json(self) -> dict[str, Any]:
        return {"window_minutes": int(self.window.total_seconds() // 60), "status": self.status,
                "delta_points": _r(self.delta_points), "points_per_hour": _r(self.per_hour),
                "reference_at": _iso(self.reference_at), "captures_in_window": self.captures_in_window}


@dataclass(frozen=True, slots=True)
class SteamEvent:
    at: datetime
    direction: str
    books: tuple[int, ...]
    median_move_points: float

    def as_json(self) -> dict[str, Any]:
        return {"at": self.at.isoformat(), "direction": self.direction, "n_books": len(self.books),
                "books": list(self.books), "median_move_points": _r(self.median_move_points)}


@dataclass(frozen=True, slots=True)
class SharpReference:
    status: str
    p_fair: float | None = None
    source: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "p_fair": self.p_fair, "source": self.source}


@dataclass(frozen=True, slots=True)
class ClosingValue:
    """CLV (``clv-v1``) of a taken price against the closing fair probability; only after kick-off."""

    status: str
    odds: float | None = None
    p_close: float | None = None
    clv: float | None = None
    quality: str = "UNKNOWN"
    close: Close | None = None

    def as_json(self) -> dict[str, Any]:
        return {"status": self.status, "definition": closing_value.VERSION, "odds": self.odds, "p_close": self.p_close,
                "clv": _r(self.clv, 6), "quality": self.quality,
                "close": None if self.close is None else self.close.evidence()}


@dataclass(frozen=True, slots=True)
class MarketSignals:
    key: Key
    at: datetime
    kickoff_at: datetime
    effective_at: datetime
    """``min(at, kickoff)``: the pre-match market ends at kick-off, so staleness and velocity are measured to here."""
    status: str
    n_captures: int
    opening: Point | None
    current: Point | None
    movement_points: float | None
    velocities: tuple[Velocity, ...]
    steam_events: tuple[SteamEvent, ...]
    staleness_minutes: float | None
    stale: bool | None
    p_model: float | None
    side: str | None
    sharp: SharpReference
    closing: ClosingValue
    version: str = VERSION

    @property
    def steam(self) -> bool:
        return bool(self.steam_events)

    def as_json(self) -> dict[str, Any]:
        fixture, market, selection, line = self.key
        o, c = self.opening, self.current
        return {
            "version": self.version, "shadow": True, "fixture_id": fixture, "market_key": market, "selection": selection,
            "line": str(line), "at": self.at.isoformat(), "kickoff_at": self.kickoff_at.isoformat(),
            "effective_at": self.effective_at.isoformat(), "status": self.status, "n_captures": self.n_captures,
            "opening": None if o is None else {"at": o.at.isoformat(), "p_fair": _r(o.p_fair, 6),
                                              "odds": str(o.best_odds), "bookmaker_id": o.best_bookmaker_id},
            "current": None if c is None else {"at": c.at.isoformat(), "p_fair": _r(c.p_fair, 6),
                                              "best_odds": str(c.best_odds), "best_bookmaker_id": c.best_bookmaker_id,
                                              "n_bookmakers": c.n_bookmakers, "dispersion": _r(c.dispersion, 6)},
            "movement_points": _r(self.movement_points),
            "velocity": [v.as_json() for v in self.velocities],
            "steam": self.steam, "steam_events": [e.as_json() for e in self.steam_events],
            "staleness_minutes": _r(self.staleness_minutes, 1), "stale": self.stale,
            "p_model": self.p_model, "side": self.side, "sharp": self.sharp.as_json(),
            "closing": self.closing.as_json(),
            "constants": {"method": METHOD.value, "steam_min_points": STEAM_MIN_POINTS,
                          "steam_max_minutes": STEAM_MAX_MINUTES, "steam_min_books": STEAM_MIN_BOOKS,
                          "side_flat_points": SIDE_FLAT_POINTS, "stale_after_minutes": STALE_AFTER.total_seconds() / 60},
        }


def _r(x: float | None, places: int = 3) -> float | None:
    return None if x is None else round(x, places)


def _iso(x: datetime | None) -> str | None:
    return None if x is None else x.isoformat()


# ── pure computations ────────────────────────────────────────────────────────────────────────────────────────────

def _row_of(rows: Iterable[ConsensusRow], selection: str, line: Decimal) -> ConsensusRow | None:
    for r in rows:
        if r.selection == selection and r.line == line and r.method == METHOD.value:
            return r
    return None


def known_captures(captures: Iterable[Capture], *, at: datetime, kickoff_at: datetime) -> list[Capture]:
    """The as-of cut: captures at or before ``at`` and strictly before kick-off, oldest first."""
    return sorted((c for c in captures if c.captured_at <= at and c.captured_at < kickoff_at),
                  key=lambda c: (c.captured_at, c.payload_hash))


def point_of(capture: Capture, selection: str, line: Decimal) -> Point | None:
    """The selection at one capture, or None when the answer does not price it (an incomplete or margin-less book is
    left out by the consensus, never guessed)."""
    row = _row_of(consensus(capture.quotes, (METHOD,)), selection, line)
    if row is None:
        return None
    by_book: dict[int, list[BookQuote]] = defaultdict(list)
    for q in capture.quotes:
        by_book[q.bookmaker_id].append(q)
    books: list[tuple[int, float]] = []
    for book, quotes in sorted(by_book.items()):
        own = _row_of(consensus(quotes, (METHOD,)), selection, line)
        if own is not None:
            books.append((book, own.p_fair))
    return Point(capture.captured_at, row.p_fair, row.best_odds, row.best_bookmaker_id, row.n_bookmakers,
                 row.dispersion, tuple(books))


def series(captures: Iterable[Capture], selection: str, line: Decimal) -> tuple[Point, ...]:
    """One point per capture that prices the selection, oldest first (call ``known_captures`` first for an as-of)."""
    points = (point_of(c, selection, line) for c in sorted(captures, key=lambda c: (c.captured_at, c.payload_hash)))
    return tuple(p for p in points if p is not None)


def _last_at_or_before(points: Sequence[Point], moment: datetime) -> Point | None:
    found: Point | None = None
    for p in points:
        if p.at <= moment:
            found = p
    return found


def velocity(points: Sequence[Point], *, at: datetime, window: timedelta) -> Velocity:
    """Current minus the last point at or before ``at - window``, in points.

    None with a reason when nothing was captured inside ``(at - window, at]`` (the window says nothing about the
    present) or when no point is as old as the window (the series is younger: a change since opening is the movement,
    not a velocity over a window it did not span)."""
    current = _last_at_or_before(points, at)
    if current is None:
        return Velocity(window, NO_PRICES, None, None, 0)
    inside = sum(1 for p in points if at - window < p.at <= at)
    if inside == 0:
        return Velocity(window, NO_CAPTURE_IN_WINDOW, None, None, 0)
    reference = _last_at_or_before(points, at - window)
    if reference is None:
        return Velocity(window, SERIES_YOUNGER, None, None, inside)
    return Velocity(window, OK, (current.p_fair - reference.p_fair) * POINTS, reference.at, inside)


def steam_events(points: Sequence[Point], *, min_points: float = STEAM_MIN_POINTS,
                 max_minutes: int = STEAM_MAX_MINUTES, min_books: int = STEAM_MIN_BOOKS) -> tuple[SteamEvent, ...]:
    """Every capture at which at least ``min_books`` books moved their own fair probability by ``min_points`` or more
    in the same direction since their previous capture, that capture being at most ``max_minutes`` earlier."""
    last_seen: dict[int, tuple[datetime, float]] = {}
    events: list[SteamEvent] = []
    gap = timedelta(minutes=max_minutes)
    for point in points:
        moves: dict[str, list[tuple[int, float]]] = {UP: [], DOWN: []}
        for book, p in point.books:
            prev = last_seen.get(book)
            if prev is not None and point.at - prev[0] <= gap:
                move = (p - prev[1]) * POINTS
                if move >= min_points:
                    moves[UP].append((book, move))
                elif move <= -min_points:
                    moves[DOWN].append((book, move))
            last_seen[book] = (point.at, p)
        for direction in (UP, DOWN):
            moved = moves[direction]
            if len(moved) >= min_books:
                events.append(SteamEvent(point.at, direction, tuple(b for b, _ in moved),
                                         statistics.median(m for _, m in moved)))
    return tuple(events)


def side(p_model: float | None, p_open: float | None, p_now: float | None, *,
         flat_points: float = SIDE_FLAT_POINTS) -> str | None:
    """Which way the market moved relative to the model.

    ``toward``: the fair probability moved from the opening in the direction of the model (the model saw the selection
    likelier than the market opened, and it shortened - or the reverse). ``against``: it moved the other way, or the
    model agreed with the opening and the market moved away from both. ``flat``: it moved less than ``flat_points``.
    None without a model probability or without prices."""
    if p_model is None or p_open is None or p_now is None:
        return None
    move = (p_now - p_open) * POINTS
    if abs(move) < flat_points:
        return FLAT
    lean = (p_model - p_open) * POINTS
    if abs(lean) < flat_points:
        return AGAINST
    return TOWARD if (move > 0) == (lean > 0) else AGAINST


def sharp_reference(sources: Sequence[OddsSourceProfile] | None = None) -> SharpReference:
    """The sharp reference: None while no sharp source is enabled - and None still, with its own status, if one is
    enabled before a version of this module reads it. Never an invented number."""
    active = enabled_sources() if sources is None else sources
    sharp = sorted(s.key for s in active if s.key in SHARP_SOURCE_KEYS)
    if not sharp:
        return SharpReference(NO_SHARP_SOURCE)
    return SharpReference(SHARP_NOT_READ, None, sharp[0])


def closing_value_of(odds: float | None, close: Close | None, *, at: datetime, kickoff_at: datetime) -> ClosingValue:
    """CLV of a taken price, by ``fbi.market.closing_value`` - only once the match has kicked off: before it the close
    does not exist (``fbi.market.closing_reference``)."""
    if at < kickoff_at:
        return ClosingValue(BEFORE_KICKOFF, odds)
    if odds is None:
        return ClosingValue(NO_TAKEN_PRICE, None, None if close is None else close.p_fair, close=close)
    if close is None:
        return ClosingValue(NO_CLOSE, odds)
    value = closing_value.clv(float(odds), close.p_fair)
    return ClosingValue(OK, odds, close.p_fair, value, closing_value.quality(value), close)


def market_signals(captures: Iterable[Capture], key: Key, *, at: datetime, kickoff_at: datetime,
                   p_model: float | None = None, taken_odds: float | None = None, close: Close | None = None,
                   sources: Sequence[OddsSourceProfile] | None = None) -> MarketSignals:
    """Every signal of one selection as of ``at``, from plain values. ``captures`` may hold more than was known at
    ``at``: the cut is applied here."""
    _, _, selection, line = key
    effective = min(at, kickoff_at)
    points = series(known_captures(captures, at=at, kickoff_at=kickoff_at), selection, line)
    closing = closing_value_of(taken_odds, close, at=at, kickoff_at=kickoff_at)
    sharp = sharp_reference(sources)
    if not points:
        return MarketSignals(key, at, kickoff_at, effective, NO_PRICES, 0, None, None, None,
                             tuple(Velocity(w, NO_PRICES, None, None, 0) for w in VELOCITY_WINDOWS), (), None, None,
                             p_model, None, sharp, closing)
    opening, current = points[0], points[-1]
    staleness = (effective - current.at).total_seconds() / 60
    return MarketSignals(
        key, at, kickoff_at, effective, OK, len(points), opening, current, (current.p_fair - opening.p_fair) * POINTS,
        tuple(velocity(points, at=effective, window=w) for w in VELOCITY_WINDOWS), steam_events(points),
        staleness, staleness > STALE_AFTER.total_seconds() / 60, p_model,
        side(p_model, opening.p_fair, current.p_fair), sharp, closing)


@dataclass(frozen=True, slots=True)
class Summary:
    selections: int
    priced: int
    sided: int
    against: int
    toward: int
    flat: int
    median_movement_points: float | None
    median_abs_movement_points: float | None
    with_steam: int
    steam_events: int
    clv_n: int
    clv_median: float | None

    @property
    def against_share(self) -> float | None:
        return None if self.sided == 0 else self.against / self.sided

    def as_json(self) -> dict[str, Any]:
        return {"selections": self.selections, "priced": self.priced, "sided": self.sided, "against": self.against,
                "toward": self.toward, "flat": self.flat, "against_share": _r(self.against_share, 4),
                "median_movement_points": _r(self.median_movement_points),
                "median_abs_movement_points": _r(self.median_abs_movement_points),
                "with_steam": self.with_steam, "steam_events": self.steam_events, "clv_n": self.clv_n,
                "clv_median": _r(self.clv_median, 6)}


def summarise(signals: Sequence[MarketSignals]) -> Summary:
    """How often the market moved against the model, the median movement and the steam, over a set of selections.
    Every share comes with its count (``sided`` is the denominator of ``against_share``)."""
    moves = [s.movement_points for s in signals if s.movement_points is not None]
    sides = [s.side for s in signals if s.side is not None]
    clvs = [s.closing.clv for s in signals if s.closing.clv is not None]
    return Summary(
        len(signals), sum(1 for s in signals if s.status == OK), len(sides), sides.count(AGAINST), sides.count(TOWARD),
        sides.count(FLAT), statistics.median(moves) if moves else None,
        statistics.median(abs(m) for m in moves) if moves else None, sum(1 for s in signals if s.steam),
        sum(len(s.steam_events) for s in signals), len(clvs), statistics.median(clvs) if clvs else None)


# ── thin SQL readers (read-only) ─────────────────────────────────────────────────────────────────────────────────

KICKOFF_SQL = "SELECT kickoff_at FROM core.fixtures WHERE id = %(fixture)s"

CAPTURES_SQL = """
SELECT s.captured_at, s.payload_hash, s.bookmaker_id, s.market_key, s.selection, s.line, s.odds_decimal
  FROM market.odds_snapshots s JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.fixture_id = %(fixture)s AND s.market_key = %(market)s AND s.source = 'prematch'
   AND s.captured_at <= %(at)s AND s.captured_at < f.kickoff_at
 ORDER BY s.captured_at, s.payload_hash, s.bookmaker_id, s.selection, s.line
"""
"""Every pre-match quote of one market of one fixture known at ``at``: all lines and selections, because pairing an
Asian Handicap or a Double Chance book needs the other side of it (``fbi.market.consensus``)."""

DECISIONS_SQL = """
SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line)
       d.id, d.fixture_id, d.market_key, d.selection, d.line, d.kickoff_at, d.known_at, d.state,
       d.odds::float8 AS odds, d.bookmaker_id, COALESCE(d.p_cal, d.p_model)::float8 AS p_model,
       CASE WHEN d.p_cal IS NULL THEN 'p_model' ELSE 'p_cal' END AS p_basis
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at <= %(at)s
   AND (%(start)s::timestamptz IS NULL OR d.kickoff_at >= %(start)s)
   AND (%(end)s::timestamptz IS NULL OR d.kickoff_at < %(end)s)
   AND (%(fixture)s::bigint IS NULL OR (d.fixture_id = %(fixture)s AND d.market_key = %(market)s
        AND d.selection = %(selection)s AND d.line = %(line)s))
 ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
"""
"""The newest decision of each selection known at ``at`` (the pipeline's, ``DECISION_CORE``): its model probability
(calibrated when it has one) and the price it took."""


def read_captures(conn: psycopg.Connection[Any], fixture_id: int, market_key: str,
                  *, at: datetime) -> tuple[datetime | None, list[Capture]]:
    """(kick-off, the captures of the market known at ``at``); kick-off is None for an unknown fixture."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(KICKOFF_SQL, {"fixture": fixture_id})
        row = cur.fetchone()
        if row is None:
            return None, []
        cur.execute(CAPTURES_SQL, {"fixture": fixture_id, "market": market_key, "at": at})
        groups: dict[tuple[datetime, str], list[BookQuote]] = defaultdict(list)
        for r in cur.fetchall():
            groups[(r["captured_at"], str(r["payload_hash"]))].append(BookQuote(
                int(r["bookmaker_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]),
                Decimal(r["odds_decimal"])))
    return row["kickoff_at"], [Capture(t, h, tuple(q)) for (t, h), q in sorted(groups.items())]


def decisions(conn: psycopg.Connection[Any], *, at: datetime, start: datetime | None = None,
              end: datetime | None = None, key: Key | None = None) -> list[dict[str, Any]]:
    """The newest decision per selection known at ``at``, for kick-offs in ``[start, end)`` or for one ``key``."""
    params: dict[str, Any] = {"version": DECISION_CORE, "at": at, "start": start, "end": end, "fixture": None,
                              "market": None, "selection": None, "line": None}
    if key is not None:
        params |= {"fixture": key[0], "market": key[1], "selection": key[2], "line": key[3]}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DECISIONS_SQL, params)
        return list(cur.fetchall())


def read_signals(conn: psycopg.Connection[Any], key: Key, *, at: datetime, p_model: float | None = None,
                 taken_odds: float | None = None) -> MarketSignals | None:
    """The signals of one selection as of ``at`` from the database; None for an unknown fixture. The close is read
    only once ``at`` is past kick-off."""
    kickoff, captures = read_captures(conn, key[0], key[1], at=at)
    if kickoff is None:
        return None
    close = None
    if at >= kickoff:
        close = closing_reference.closing_probabilities(conn, [key]).get(key)
    return market_signals(captures, key, at=at, kickoff_at=kickoff, p_model=p_model, taken_odds=taken_odds,
                          close=close)

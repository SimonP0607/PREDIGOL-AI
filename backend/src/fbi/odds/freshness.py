"""When a price of the book is current, and when a scheduled ask was missed (plan Cuotas, BE-011): the ONE freshness rule the
explorer's board, a match's book and the book refreshes share.

A price is ``current`` when the ask that confirmed it (``checked_at``: the ask whose answer is in force, ``fbi.odds.book``) came at
or after the latest scheduled ask for its time to kick-off, with the window tolerance; ``stale`` when at least one scheduled ask was
missed since. The schedule is a set of points in minutes before kick-off:

* the model windows, ``FBI_ODDS_PREMATCH_WINDOWS`` (4320, 2880, 1440, 720, 360 and 180 by default): the capture's own;
* and, while the book refreshes run (``FBI_ODDS_BOOK_REFRESH`` with ``FBI_ODDS_BOOK``), ``refresh_points()``: every 180 min from
  T-72 h to T-6 h, every 60 min from T-6 h to T-1 h, and at T-30 and T-10 min.

The tolerance is the capture's, ``FBI_ODDS_WINDOW_TOLERANCE`` (45 min): a point ``p`` is due from ``kick-off - p`` until
``tolerance`` minutes later (the band of ``fbi.odds.schedule.CapturePlanner``, which runs FORWARD from the nominal instant), so a point
is missed only once its band has CLOSED with no ask at or after its nominal instant. A price whose ask came before every closed
band's point is ``stale``; before the first band closes nothing can have been missed.

Pure: no database, no clock, no settings. ``fbi.api.services.odds_explorer`` gives it the settings, ``fbi.odds.book_refresh`` uses
``due_point`` on the refresh points to decide what to ask.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

FAR_FROM, FAR_TO, FAR_EVERY = 4320, 360, 180
"""From T-72 h to T-6 h, every 3 hours: the provider's documented refresh period."""
NEAR_FROM, NEAR_TO, NEAR_EVERY = 360, 60, 60
"""From T-6 h to T-1 h, every hour: news and probable line-ups arrive."""
LAST_POINTS = (30, 10)
"""The last hour: in 84 % of the matches the provider updates after the T-180 capture, a median 103 min before kick-off."""

State = Literal["current", "stale"]
BookState = Literal["current", "stale", "none"]


def refresh_points() -> tuple[int, ...]:
    """The book refreshes' points, in minutes before kick-off, farthest first (30 points with the defaults)."""
    far = range(FAR_FROM, FAR_TO - 1, -FAR_EVERY)
    near = range(NEAR_FROM, NEAR_TO - 1, -NEAR_EVERY)
    return tuple(sorted({*far, *near, *LAST_POINTS}, reverse=True))


def schedule(windows: Iterable[int], *, refreshes: bool) -> tuple[int, ...]:
    """Every scheduled point of a match: the model windows, plus the refresh points while the refreshes run. Farthest first."""
    points = {int(w) for w in windows}
    if refreshes:
        points |= set(refresh_points())
    return tuple(sorted(points, reverse=True))


def minutes_to(kickoff_at: datetime, now: datetime) -> float:
    return (kickoff_at - now).total_seconds() / 60.0


def last_closed_point(points: Sequence[int], minutes_to_ko: float, tolerance: int) -> int | None:
    """The point nearest to kick-off whose band has closed at this distance (``p - tolerance > minutes``), or None when no band has
    closed yet."""
    closed = [p for p in points if p - tolerance > minutes_to_ko]
    return min(closed) if closed else None


def due_point(points: Sequence[int], minutes_to_ko: float, tolerance: int) -> int | None:
    """The point whose band holds this distance (``p - tolerance <= minutes <= p``), the tightest when bands overlap; None between
    bands. The same band as the capture planner's ``_due_window``."""
    for point in sorted(points):
        if point - tolerance <= minutes_to_ko <= point:
            return point
    return None


def price_state(*, checked_at: datetime, kickoff_at: datetime, now: datetime, points: Sequence[int], tolerance: int) -> State:
    """``current`` when the ask that confirmed the price came at or after the latest scheduled point whose band has closed;
    ``stale`` when that point (and so at least one scheduled ask) was missed."""
    point = last_closed_point(points, minutes_to(kickoff_at, now), tolerance)
    if point is None:
        return "current"
    return "current" if checked_at >= kickoff_at - timedelta(minutes=point) else "stale"


def book_state(*, checked_at: datetime | None, kickoff_at: datetime, now: datetime, points: Sequence[int],
               tolerance: int) -> BookState:
    """A match's book: ``none`` without a price in force, else ``price_state``."""
    if checked_at is None:
        return "none"
    return price_state(checked_at=checked_at, kickoff_at=kickoff_at, now=now, points=points, tolerance=tolerance)


def is_quarter(line: Decimal | None) -> bool:
    """A quarter line (x.25, x.75): half the stake on each neighbouring line. Mi Parlay refuses them."""
    return line is not None and (line * 4) % 2 != 0


def parlay_ok(*, parlay_market: bool, line: Decimal | None, outlier: bool, state: str, kickoff_at: datetime,
              now: datetime) -> bool:
    """Whether a price may go to Mi Parlay: one of its five markets, not a quarter line, not an outlier, current and not started."""
    return parlay_market and not is_quarter(line) and not outlier and state == "current" and kickoff_at > now

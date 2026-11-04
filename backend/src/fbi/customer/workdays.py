"""Colombian business days, for the legal deadlines of a privacy request (plan UX, A4).

Ley 1581 de 2012 gives the controller 10 business days to answer a query (art. 14, extendable by 5) and 15 to settle
a claim - a correction, an update, a deletion (art. 15, extendable by 8). A business day is a weekday that is not a
public holiday in Colombia. The holidays follow Ley 51 de 1983 (Ley Emiliani: most move to the next Monday) and the
Easter calendar; they are computed for any year, not listed by hand, and the test checks 2026 against the official
calendar (18 holidays).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

QUERY_DAYS = 10
QUERY_EXTENSION = 5
CLAIM_DAYS = 15
CLAIM_EXTENSION = 8


def easter(year: int) -> date:
    """Easter Sunday (Gregorian calendar; the anonymous algorithm of Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


@cache
def holidays(year: int) -> frozenset[date]:
    """Colombia's public holidays of a year."""
    fixed = [date(year, 1, 1), date(year, 5, 1), date(year, 7, 20), date(year, 8, 7), date(year, 12, 8),
             date(year, 12, 25)]
    # Ley Emiliani: on the next Monday when they do not fall on one
    moved = [_next_monday(date(year, m, d)) for m, d in ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1),
                                                          (11, 11))]
    sunday = easter(year)
    easter_based = [
        sunday - timedelta(days=3),  # Jueves Santo
        sunday - timedelta(days=2),  # Viernes Santo
        sunday + timedelta(days=43),  # Ascensión del Señor (moved to Monday)
        sunday + timedelta(days=64),  # Corpus Christi (moved to Monday)
        sunday + timedelta(days=71),  # Sagrado Corazón (moved to Monday)
    ]
    return frozenset(fixed + moved + easter_based)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def add_business_days(start: date, days: int) -> date:
    """The date ``days`` business days after ``start`` (the day a request arrives does not count)."""
    if days < 0:
        raise ValueError("days must be zero or more")
    d = start
    left = days
    while left > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            left -= 1
    return d

"""Colombian business days for the legal deadlines of a privacy request (plan UX, A4; Ley 1581 de 2012, arts. 14-15)."""

from __future__ import annotations

from datetime import date

import pytest

from fbi.customer import workdays

# The official calendar of 2026 (18 holidays: festivos.com.co and the press, checked on 25-oct-2026). Jueves Santo
# 2 April, Ascensión moved to 18 May, Corpus Christi to 8 June: Easter fell on 5 April.
HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1),
    date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 29), date(2026, 7, 20), date(2026, 8, 7),
    date(2026, 8, 17), date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 16), date(2026, 12, 8),
    date(2026, 12, 25),
}


def test_easter_sundays() -> None:
    assert workdays.easter(2025) == date(2025, 4, 20)
    assert workdays.easter(2026) == date(2026, 4, 5)
    assert workdays.easter(2027) == date(2027, 3, 28)
    assert workdays.easter(2028) == date(2028, 4, 16)


def test_the_holidays_of_2026_are_the_official_eighteen() -> None:
    assert set(workdays.holidays(2026)) == HOLIDAYS_2026


@pytest.mark.parametrize(("day", "business"), [
    (date(2026, 10, 23), True),   # a Friday
    (date(2026, 10, 24), False),  # Saturday
    (date(2026, 10, 25), False),  # Sunday
    (date(2026, 11, 2), False),   # Todos los Santos, moved to Monday
    (date(2026, 11, 3), True),
])
def test_a_business_day_is_a_weekday_that_is_not_a_holiday(day: date, business: bool) -> None:
    assert workdays.is_business_day(day) is business


def test_deadlines_count_business_days_after_the_request() -> None:
    # A query on Friday 23 October: 10 business days, skipping two weekends and Monday 2 November (a holiday).
    assert workdays.add_business_days(date(2026, 10, 23), workdays.QUERY_DAYS) == date(2026, 11, 9)
    # A claim the same day: 15 business days - Monday 16 November is a holiday too.
    assert workdays.add_business_days(date(2026, 10, 23), workdays.CLAIM_DAYS) == date(2026, 11, 17)
    # A request made on a Saturday starts counting on Monday.
    assert workdays.add_business_days(date(2026, 10, 24), 1) == date(2026, 10, 26)
    assert workdays.add_business_days(date(2026, 10, 24), 0) == date(2026, 10, 24)
    with pytest.raises(ValueError):
        workdays.add_business_days(date(2026, 10, 24), -1)

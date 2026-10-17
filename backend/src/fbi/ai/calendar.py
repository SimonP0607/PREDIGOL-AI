"""The AI layer's calendar: its day and its month are Bogotá's (America/Bogota, the product's day), never UTC.

A day of work starts at 00:05 Bogotá (``fbi.ai.day``); the budget's day and month are cut at Bogotá midnight
(``fbi.ai.usage``); the learning reads the finished Bogotá day."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DAY_TZ = ZoneInfo("America/Bogota")


def local_day(at: datetime) -> date:
    return at.astimezone(DAY_TZ).date()


def day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=DAY_TZ)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    return day_start(day), day_start(day + timedelta(days=1))


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    first = day.replace(day=1)
    return (first + timedelta(days=32)).replace(day=1)


def days_left_in_month(day: date) -> int:
    """Days from ``day`` to the end of its month, ``day`` included (at least 1)."""
    return max(1, (next_month(day) - day).days)


def days_in_month(day: date) -> int:
    return (next_month(day) - month_start(day)).days

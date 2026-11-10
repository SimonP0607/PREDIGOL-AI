"""IA-031: the daily attribution looks at the last seven Bogotá days again, so a match whose post-mortem arrives late is still attributed."""

from __future__ import annotations

import inspect
from datetime import date

from fbi.ai import cycle
from fbi.ai.agents import attribution


def test_the_step_reads_the_last_seven_days_and_today_oldest_first() -> None:
    days = cycle.attribution_days(date(2026, 11, 10))
    assert cycle.ATTRIBUTION_LOOKBACK_DAYS == 7
    assert days[0] == date(2026, 11, 3) and days[-1] == date(2026, 11, 10) and len(days) == 8
    assert days == sorted(days) and len(set(days)) == len(days)


def test_the_step_uses_those_days_and_the_rule_writes_nothing_twice() -> None:
    source = inspect.getsource(cycle._attributions)
    assert "attribution_days(today)" in source and "attribute_day(conn, day=d, at=at)" in source
    assert "ON CONFLICT" in attribution.INSERT_SQL and "DO NOTHING" in attribution.INSERT_SQL, "looking again costs a read, never a second row"

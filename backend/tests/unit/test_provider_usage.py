"""The owner's console of the provider's requests (plan PM, PM-04-05; BE-076): annex F's figures of a known window, the day's
projection, and nothing at all while ``FBI_USAGE_CONSOLE`` is off."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import Me
from fbi.api.contracts.provider_usage import UsageDay
from fbi.api.problem import ApiError
from fbi.api.services import provider_usage

# raw.provider_quota, 20 Oct to 18 Nov 2026 (read on the server 20 Nov 14:48 UTC): annex F's window
ANNEX_F_DAYS = [18648, 11825, 10665, 14266, 16810, 15276, 23320, 19413, 13534, 60000, 14671, 16734, 18396, 23430, 19355, 14245,
                14842, 14763, 16993, 15250, 22427, 17366, 11377, 13058, 13699, 16327, 13058, 23112, 19187, 13297]
START = date(2026, 10, 20)


def annex_f() -> list[UsageDay]:
    return [UsageDay(day=START + timedelta(days=i), spent=v, budget=60_000, exhausted=v >= 60_000) for i, v in enumerate(ANNEX_F_DAYS)]


def test_the_window_reproduces_annex_f() -> None:
    w = provider_usage.window_figures(annex_f(), START, date(2026, 11, 18))
    assert w.days == 30
    assert round(w.mean) == 17_845  # «Peticiones al día, media de 30 días»
    assert round(w.median) == 15_802  # «mediana» (15.801,5)
    assert (w.max, w.max_day) == (60_000, date(2026, 10, 29))  # the day the account answered as the free plan (OPS-009)
    assert (w.max_normal, w.max_normal_day) == (23_430, date(2026, 11, 2))  # «Máximo de un día normal»
    assert w.exhausted_days == 1


def test_an_empty_window_is_zero_not_an_error() -> None:
    w = provider_usage.window_figures([], START, START)
    assert (w.days, w.mean, w.max, w.max_day, w.max_normal_day) == (0, 0.0, 0, None, None)


@pytest.mark.parametrize(("hour", "spent", "expected"), [(12, 5_000, 10_000), (6, 4_000, 16_000), (0, 30, 30)])
def test_the_projection_is_today_at_todays_pace(hour: int, spent: int, expected: int) -> None:
    at = datetime(2026, 11, 20, hour, 0 if hour else 5, tzinfo=UTC)
    elapsed, projected = provider_usage.projection(spent, at)
    assert projected == expected
    assert 0 <= elapsed <= 1


def test_off_it_answers_404_and_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(switches.USAGE_CONSOLE, raising=False)
    with pytest.raises(ApiError) as found:
        provider_usage.usage(None)  # type: ignore[arg-type]  # no connection: it must not be touched
    assert found.value.status == 404
    assert Me.model_fields["usage_console"].default is False
    monkeypatch.setenv(switches.USAGE_CONSOLE, "1")
    assert switches.usage_console_on() is True

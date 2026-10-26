"""The switches of what a reader is shown (plan UX, A9 and A10): on without their line, off with ``0`` and off with a value they
cannot read - one rule (``fbi.api.switches``) for the forecast, the calendar, the post-match's base, the structured reading and
the news."""

from __future__ import annotations

from types import ModuleType

import pytest

from fbi.api import switches
from fbi.api.services import forecast, knowledge, match_calendar, news, reading

SERVICES = (forecast, match_calendar, knowledge, reading, news)


def test_the_five_switches_and_their_names() -> None:
    assert [s.USERS_SWITCH for s in SERVICES] == ["FBI_FORECAST_USERS", "FBI_CALENDAR_USERS", "FBI_KNOWLEDGE_USERS",
                                                  "FBI_READING_USERS", "FBI_NEWS_USERS"]


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.USERS_SWITCH)
@pytest.mark.parametrize(("value", "on"), [(None, True), ("", True), ("  ", True), ("1", True), ("on", True),
                                           ("TRUE", True), (" yes ", True), ("0", False), ("off", False),
                                           ("false", False), ("no", False), ("si", False), ("2", False)])
def test_on_without_its_line_off_with_zero_or_an_unreadable_value(service: ModuleType, value: str | None, on: bool,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    name = service.USERS_SWITCH
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    assert service.users_may_see() is on
    assert switches.user_switch(name, default=False) is (on and value is not None and bool(value.strip()))

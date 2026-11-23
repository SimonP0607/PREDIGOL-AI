"""The six switches of the plan de correcciones UX (23-nov-2026) are born off, reach the web in ``/auth/me`` and turn on with ``=1``."""

from __future__ import annotations

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import Me

PAIRS = (
    ("FBI_HOME_UNIFIED", "home_unified", switches.home_unified_on),
    ("FBI_MARKETS_V3", "markets_v3", switches.markets_v3_on),
    ("FBI_DAY_HIGHLIGHTS", "day_highlights", switches.day_highlights_on),
    ("FBI_MY_BOOKS", "my_books", switches.my_books_on),
    ("FBI_STAKES", "stakes", switches.stakes_on),
    ("FBI_TREND_BUILDER", "trend_builder", switches.trend_builder_on),
)


@pytest.mark.parametrize(("name", "field", "reader"), PAIRS)
def test_each_switch_is_born_off_and_turns_on_with_one(
    monkeypatch: pytest.MonkeyPatch, name: str, field: str, reader: object
) -> None:
    monkeypatch.delenv(name, raising=False)
    assert callable(reader)
    assert reader() is False
    assert Me.model_fields[field].default is False
    monkeypatch.setenv(name, "1")
    assert reader() is True
    monkeypatch.setenv(name, "0")
    assert reader() is False

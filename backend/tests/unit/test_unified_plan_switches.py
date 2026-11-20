"""The six switches of the unified plan UX/UI e Intelligence 2026 (BE-045): all off until the owner's line turns them on,
and /auth/me says each one to the page."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import Me

CASES: list[tuple[str, Callable[[], bool], str]] = [
    (switches.ODDS_BY_MATCH, switches.odds_by_match_on, "odds_by_match"),
    (switches.NAV_V2, switches.nav_v2_on, "nav_v2"),
    (switches.SEARCH, switches.search_on, "search"),
    (switches.PROFILES, switches.profiles_on, "profiles"),
    (switches.NEWS_V2, switches.news_v2_on, "news_v2"),
    (switches.MATCH_INTELLIGENCE, switches.match_intelligence_on, "match_intelligence"),
]


@pytest.mark.parametrize(("name", "on", "field"), CASES)
@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("on", True), ("0", False),
                                                 ("maybe", False)])
def test_each_switch_is_off_until_its_line_turns_it_on(name: str, on: Callable[[], bool], field: str,
                                                       value: str | None, expected: bool,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    assert on() is expected


@pytest.mark.parametrize(("name", "on", "field"), CASES)
def test_the_page_is_told_each_switch_and_it_is_off_by_default(name: str, on: Callable[[], bool], field: str) -> None:
    assert name.startswith("FBI_")
    assert Me.model_fields[field].default is False


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("0", False)])
def test_c16_availability_is_told_to_the_page_and_off_by_default(value: str | None, expected: bool,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan PM, PM-14-01 (UX-173): the page draws the states «información no disponible» and the console of the matrix only
    with C-16 on; /auth/me says it as ``availability``, off until FBI_AVAILABILITY's line turns it on."""
    if value is None:
        monkeypatch.delenv(switches.AVAILABILITY, raising=False)
    else:
        monkeypatch.setenv(switches.AVAILABILITY, value)
    assert Me.model_fields["availability"].default is False
    assert switches.availability_on() is expected


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("0", False)])
def test_shot_funnel_is_told_to_the_page_and_off_by_default(value: str | None, expected: bool,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan PM, PM-10-01 (FE-005): the Match Center's shot funnel and two zones only with FBI_MATCH_SHOT_FUNNEL's line on;
    /auth/me says it as ``match_shot_funnel``, off by default."""
    if value is None:
        monkeypatch.delenv(switches.MATCH_SHOT_FUNNEL, raising=False)
    else:
        monkeypatch.setenv(switches.MATCH_SHOT_FUNNEL, value)
    assert Me.model_fields["match_shot_funnel"].default is False
    assert switches.match_shot_funnel_on() is expected


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("0", False)])
def test_match_balance_is_told_to_the_page_and_off_by_default(value: str | None, expected: bool,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan PM, PM-10-02 (FE-006): the Match Center's balance and strip of the score's state only with FBI_MATCH_BALANCE's line
    on; /auth/me says it as ``match_balance``, off by default."""
    if value is None:
        monkeypatch.delenv(switches.MATCH_BALANCE, raising=False)
    else:
        monkeypatch.setenv(switches.MATCH_BALANCE, value)
    assert Me.model_fields["match_balance"].default is False
    assert switches.match_balance_on() is expected


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("0", False)])
def test_lineup_layers_are_told_to_the_page_and_off_by_default(value: str | None, expected: bool,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan PM, PM-10-04 (UX-176): the data layers of the line-up pitch only with FBI_LINEUP_LAYERS's line on; /auth/me says it
    as ``lineup_layers``, off by default."""
    if value is None:
        monkeypatch.delenv(switches.LINEUP_LAYERS, raising=False)
    else:
        monkeypatch.setenv(switches.LINEUP_LAYERS, value)
    assert Me.model_fields["lineup_layers"].default is False
    assert switches.lineup_layers_on() is expected

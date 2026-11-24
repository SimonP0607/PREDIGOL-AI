"""The four modules that read the availability matrix (plan PM, PM-14-04) are born off, one line each, and say so in ``/auth/me``."""

from __future__ import annotations

import pytest

from fbi.api import switches
from fbi.api.contracts.auth import MatrixModules, Me
from fbi.api.routers.auth import me_of
from fbi.auth.service import Principal
from tests.integration.signed_in import principal

LINES = {"odds": "FBI_MATRIX_ODDS", "picks": "FBI_MATRIX_PICKS", "news": "FBI_MATRIX_NEWS", "parlay": "FBI_MATRIX_PARLAY"}


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*LINES.values(), switches.AVAILABILITY):
        monkeypatch.delenv(name, raising=False)


def test_the_four_lines_are_the_four_modules() -> None:
    assert switches.MATRIX_MODULE_SWITCH == LINES and tuple(LINES) == switches.MATRIX_MODULES
    assert set(MatrixModules.model_fields) == set(LINES)


def test_born_off_for_every_module() -> None:
    assert Me.model_fields["matrix_modules"].default_factory is MatrixModules
    assert all(switches.matrix_mode(m) == "off" for m in LINES)
    assert MatrixModules().model_dump() == {"odds": "off", "picks": "off", "news": "off", "parlay": "off"}


def test_a_line_alone_does_nothing_while_the_matrix_itself_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_MATRIX_ODDS", "on")
    assert switches.matrix_mode("odds") == "off"


@pytest.mark.parametrize(("raw", "mode"), [("show", "show"), ("SHOW", "show"), ("1", "on"), ("on", "on"), ("", "off"),
                                           ("0", "off"), ("maybe", "off")])
def test_show_reads_and_only_says_and_one_turns_it_on(monkeypatch: pytest.MonkeyPatch, raw: str, mode: str) -> None:
    monkeypatch.setenv(switches.AVAILABILITY, "1")
    monkeypatch.setenv("FBI_MATRIX_PICKS", raw)
    assert switches.matrix_mode("picks") == mode
    assert switches.matrix_mode("odds") == "off", "each module has its own line"


def test_an_unknown_module_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(switches.AVAILABILITY, "1")
    assert switches.matrix_mode("nope") == "off"


def test_auth_me_carries_each_modules_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(switches.AVAILABILITY, "1")
    monkeypatch.setenv("FBI_MATRIX_NEWS", "show")
    monkeypatch.setenv("FBI_MATRIX_PARLAY", "on")
    p: Principal = principal("USER")
    assert me_of(p).matrix_modules.model_dump() == {"odds": "off", "picks": "off", "news": "show", "parlay": "on"}

"""The job that writes the state of each match (plan IA, phase 1) is on unless the owner says no: ``FBI_AI_PACKAGE=0`` is the phase's rollback,
and the admin's view of the settings says which."""

from __future__ import annotations

import pytest

from fbi.ai.config import AiSettings


@pytest.mark.parametrize(("raw", "expected"), [(None, True), ("", True), ("1", True), ("on", True), ("yes", True), ("true", True), ("anything", True),
                                                ("0", False), ("off", False), ("OFF", False), ("False", False), ("no", False), (" 0 ", False)])
def test_the_state_of_each_match_is_written_unless_the_switch_says_no(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: bool) -> None:
    env = {} if raw is None else {"FBI_AI_PACKAGE": raw}
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    settings = AiSettings.from_env()
    assert settings.package is expected
    assert settings.public()["package"] is expected


def test_a_settings_object_made_by_hand_has_it_on() -> None:
    assert AiSettings().package is True and AiSettings(mode="shadow").package is True


def test_the_switch_does_not_touch_the_mode_nor_the_other_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {"FBI_AI_PACKAGE": "0"})
    off = AiSettings.from_env()
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {})
    on = AiSettings.from_env()
    assert (off.mode, off.switches, off.legacy_postmortems) == (on.mode, on.switches, on.legacy_postmortems)

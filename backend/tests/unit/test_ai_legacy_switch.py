"""The two first post-mortems (by match, pm-v1; by selection, pm-v2) are frozen since plan F8 and write again only when the owner sets
``FBI_AI_LEGACY_POSTMORTEMS``: off unless the variable says yes, and the admin's view of the settings says which."""

from __future__ import annotations

import pytest

from fbi.ai.config import AiSettings


@pytest.mark.parametrize(("raw", "expected"), [(None, False), ("", False), ("0", False), ("off", False), ("no", False), ("false", False),
                                                ("1", True), ("on", True), ("True", True), (" yes ", True)])
def test_the_frozen_post_mortems_write_only_when_the_switch_says_yes(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                                      expected: bool) -> None:
    env = {} if raw is None else {"FBI_AI_LEGACY_POSTMORTEMS": raw}
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    settings = AiSettings.from_env()
    assert settings.legacy_postmortems is expected
    assert settings.public()["legacy_postmortems"] is expected


def test_a_settings_object_made_by_hand_has_them_frozen() -> None:
    assert AiSettings().legacy_postmortems is False and AiSettings(mode="shadow").legacy_postmortems is False

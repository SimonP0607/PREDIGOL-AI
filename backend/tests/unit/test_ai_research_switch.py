"""The switch of the research of an entity (plan IA, phase 2): ``FBI_AI_RESEARCH_V2`` is ``off`` unless the owner writes the word ``shadow`` or ``on``,
and the admin's view of the settings says which. Nothing else in the settings moves with it."""

from __future__ import annotations

import pytest

from fbi.ai import gates
from fbi.ai.config import AiSettings


def env_of(monkeypatch: pytest.MonkeyPatch, **env: str) -> AiSettings:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    return AiSettings.from_env()


@pytest.mark.parametrize(("raw", "expected"), [(None, "off"), ("", "off"), ("off", "off"), ("0", "off"), ("no", "off"), ("false", "off"),
                                                ("shadow", "shadow"), ("SHADOW", "shadow"), (" Shadow ", "shadow"),
                                                ("on", "on"), ("ON", "on"), (" on ", "on")])
def test_only_the_words_shadow_and_on_switch_it_on(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: str) -> None:
    settings = env_of(monkeypatch) if raw is None else env_of(monkeypatch, FBI_AI_RESEARCH_V2=raw)
    assert settings.research_v2 == expected
    assert settings.public()["research_v2"] == expected


@pytest.mark.parametrize("raw", ["1", "true", "yes", "enabled", "shadwo", "onn", "enforce", "auto", "shadow,on", "shadow on"])
def test_a_typo_or_another_word_for_yes_is_off_so_nothing_reaches_the_packet_by_accident(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    assert env_of(monkeypatch, FBI_AI_RESEARCH_V2=raw).research_v2 == "off"


def test_a_settings_object_made_by_hand_has_it_off() -> None:
    assert AiSettings().research_v2 == "off" and AiSettings(mode="shadow").research_v2 == "off" and AiSettings(mode="enforce").research_v2 == "off"


def test_the_switch_does_not_touch_the_mode_nor_the_other_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    on = env_of(monkeypatch, FBI_AI_RESEARCH_V2="on", FBI_AI_MODE="shadow")
    off = env_of(monkeypatch, FBI_AI_MODE="shadow")
    assert (on.mode, on.switches, on.package, on.legacy_postmortems, on.exa_monthly_budget, on.monthly_budget) == \
           (off.mode, off.switches, off.package, off.legacy_postmortems, off.exa_monthly_budget, off.monthly_budget)
    assert on.research_v2 == "on" and off.research_v2 == "off"


def test_it_is_not_one_of_the_five_two_state_optimisations() -> None:
    """``SWITCH_ENV`` holds the switches of phase 0 (off | on | auto); research v2 has three words and its own gate (``gates.research_mode``)."""
    from fbi.ai.config import SWITCH_ENV

    assert "research_v2" not in SWITCH_ENV and "FBI_AI_RESEARCH_V2" not in SWITCH_ENV.values()
    assert "research_v2" in gates.GATES, "the gate that lets ``on`` stand has a place in the evidence"
    assert AiSettings(research_v2="on").switch("research_v2") == "off", "and a name that is not a switch of phase 0 is never switched on by accident"


def test_the_words_of_the_docstring_are_the_words_of_the_code() -> None:
    import fbi.ai.config as config

    doc = config.__doc__ or ""
    assert "FBI_AI_RESEARCH_V2" in doc and "off (default) | shadow | on" in doc
    assert "``on`` behaves as ``shadow``" in doc, "the module tells the owner that on without the gate is shadow"

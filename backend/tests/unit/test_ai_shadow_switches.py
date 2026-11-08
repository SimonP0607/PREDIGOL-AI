"""The three words that switch the shadow of phase 3 on (plan IA, phase 3): ``FBI_AI_ENGINES``, ``FBI_AI_SHADOW_SAMPLE`` and ``FBI_AI_AGENTS``.

The rule for all three is the one of the other switches of the layer: validation is clamping, nothing raises, and a typo means OFF - the shadow spends
money, so a word the code does not know can only leave it as it was. ``rules`` and ``llm`` are the production baseline and no word of this list can take
them away; the list only adds. The orchestrator may run only when all three say so (``AiSettings.orchestrate``) and the layer is not off.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import config
from fbi.ai.config import AGENTS, BASELINE_ENGINES, KNOWN_ENGINES, SHADOW_ENGINES, AiSettings

BACKEND = Path(__file__).resolve().parents[2]
D = Decimal
THREE = ("engines", "shadow_sample", "agents")


def env_of(monkeypatch: pytest.MonkeyPatch, **env: str) -> AiSettings:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: env)
    return AiSettings.from_env()


# ── the vocabulary ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_engines_the_owner_can_name_are_these_five_in_this_order() -> None:
    assert KNOWN_ENGINES == ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1")
    assert BASELINE_ENGINES == ("rules", "llm") and SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1")
    assert "combined" not in KNOWN_ENGINES, "combined is what the production engines add up to, never a choice"
    assert len(set(KNOWN_ENGINES)) == len(KNOWN_ENGINES)


def test_the_agents_the_owner_can_name_are_one_list() -> None:
    assert AGENTS == ("match", "council", "stats", "player"), "phase 4 added the statistics agent here and IA-017 the player agent, and nowhere else"
    assert set(config.ORCHESTRATOR_AGENTS) <= set(AGENTS)


# ── FBI_AI_ENGINES ────────────────────────────────────────────────────────────────────────────────────────────────

BASE = ("rules", "llm")


@pytest.mark.parametrize(("raw", "expected"), [
    (None, BASE), ("", BASE), ("   ", BASE), ("rules,llm", BASE), ("rules", BASE), ("llm", BASE), ("llm,rules", BASE),
    ("ma-v1", (*BASE, "ma-v1")),
    ("rules,llm,ma-v1,ma-v1-h", (*BASE, "ma-v1", "ma-v1-h")),  # the plan's activation
    ("ma-v1-h", (*BASE, "ma-v1-h")),
    ("cs-v1", (*BASE, "cs-v1")),
    ("cs-v1,ma-v1-h,ma-v1", (*BASE, "ma-v1", "ma-v1-h", "cs-v1")),  # the canonical order, not the owner's
    ("ma-v1,ma-v1,MA-V1, ma-v1 ", (*BASE, "ma-v1")),  # duplicates collapse
    (" MA-V1 , Ma-V1-H ", (*BASE, "ma-v1", "ma-v1-h")),  # case and spaces do not matter
    ("RULES,LLM,CS-V1", (*BASE, "cs-v1")),
    ("ma-v1,", (*BASE, "ma-v1")), (",ma-v1", (*BASE, "ma-v1")), (",,,", BASE),
    ("ma-v1\n", (*BASE, "ma-v1")), ("\tma-v1\t,\tcs-v1", (*BASE, "ma-v1", "cs-v1")),
])
def test_the_list_of_engines_only_adds_shadow_engines_to_the_baseline(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                                       expected: tuple[str, ...]) -> None:
    settings = env_of(monkeypatch) if raw is None else env_of(monkeypatch, FBI_AI_ENGINES=raw)
    assert settings.engines == expected
    assert settings.shadow_engines == tuple(e for e in expected if e not in BASE)
    assert settings.public()["engines"] == list(expected)
    assert settings.public()["shadow_engines"] == list(settings.shadow_engines)


@pytest.mark.parametrize("raw", [
    "ma-v1 ma-v1-h", "ma_v1", "ma-v2", "ma", "v1", "multiagent", "ma-v1;ma-v1-h", "ma-v1|cs-v1", "ma-v1/cs-v1", "combined", "rules,llm,combined",
    "none", "off", "0", "1", "true", "all", "*", "ma\u2013v1", "ma\u2011v1", "ma-v1\u200b", "ma-v1 -h", "[ma-v1]", "'ma-v1'", '"ma-v1"', "ma-v1:cs-v1",
    "council", "match", "stats", "ma-v1-h2", "xma-v1", "ma-v1x",
])
def test_a_typo_or_another_word_is_dropped_and_switches_nothing_on(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    settings = env_of(monkeypatch, FBI_AI_ENGINES=raw)
    assert settings.engines == BASE and settings.shadow_engines == ()


def test_a_wrong_name_beside_a_right_one_does_not_take_the_right_one_down(monkeypatch: pytest.MonkeyPatch) -> None:
    assert env_of(monkeypatch, FBI_AI_ENGINES="ma-v1,typo,cs-v1").engines == (*BASE, "ma-v1", "cs-v1")


@pytest.mark.parametrize("raw", ["", "ma-v1", "cs-v1", "ma-v1,ma-v1-h,cs-v1", "anything", "off", "0"])
def test_no_word_takes_the_baseline_away(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    engines = env_of(monkeypatch, FBI_AI_ENGINES=raw).engines
    assert engines[:2] == BASE


def test_a_settings_object_made_by_hand_has_the_baseline_only() -> None:
    for settings in (AiSettings(), AiSettings(mode="shadow"), AiSettings(mode="enforce"), AiSettings(mode="off")):
        assert settings.engines == BASE and settings.shadow_engines == ()


# ── FBI_AI_SHADOW_SAMPLE ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected", "shown"), [
    (None, D(0), "0"), ("", D(0), "0"), ("  ", D(0), "0"), ("0", D(0), "0"), ("0.0", D(0), "0"), ("0.00", D(0), "0"),
    ("0.3", D("0.3"), "0.3"), (" 0.3 ", D("0.3"), "0.3"), ("0.30", D("0.3"), "0.3"), (".3", D("0.3"), "0.3"), ("3e-1", D("0.3"), "0.3"),
    ("0.5", D("0.5"), "0.5"), ("0.15", D("0.15"), "0.15"), ("0.0001", D("0.0001"), "0.0001"), ("1", D(1), "1"), ("1.0", D(1), "1"), ("1.00", D(1), "1"),
    ("1.5", D(1), "1"), ("2", D(1), "1"), ("30", D(1), "1"), ("1e9", D(1), "1"),  # above one counts as one
    ("-0.2", D(0), "0"), ("-1", D(0), "0"), ("-0", D(0), "0"),  # below zero counts as zero
    ("abc", D(0), "0"), ("30%", D(0), "0"), ("0,3", D(0), "0"), ("0.3.1", D(0), "0"), ("one", D(0), "0"), ("0.3 0.4", D(0), "0"), ("--1", D(0), "0"),
    ("nan", D(0), "0"), ("NaN", D(0), "0"), ("sNaN", D(0), "0"), ("inf", D(0), "0"), ("Infinity", D(0), "0"), ("-inf", D(0), "0"),
])
def test_the_sample_is_a_share_clamped_from_zero_to_one_and_a_word_that_is_not_a_number_is_zero(
        monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: Decimal, shown: str) -> None:
    settings = env_of(monkeypatch) if raw is None else env_of(monkeypatch, FBI_AI_SHADOW_SAMPLE=raw)
    assert settings.shadow_sample == expected and settings.shadow_sample.is_finite()
    assert 0 <= settings.shadow_sample <= 1
    assert settings.public()["shadow_sample"] == shown, "the Console reads a plain figure: no exponent, no trailing zeros"


def test_a_settings_object_made_by_hand_has_the_sample_at_zero() -> None:
    assert AiSettings().shadow_sample == 0 and AiSettings(mode="enforce").shadow_sample == 0


# ── FBI_AI_AGENTS ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    (None, ()), ("", ()), ("  ", ()), ("match", ("match",)), ("council", ("council",)), ("match,council", ("match", "council")),
    ("council,match", ("match", "council")), (" Match , COUNCIL ", ("match", "council")), ("match,match,MATCH", ("match",)), ("match,", ("match",)),
    ("match,typo,council", ("match", "council")),
    ("stats", ("stats",)), ("match,stats", ("match", "stats")), ("stats,council,match", ("match", "council", "stats")),  # phase 4's agent
    ("ma-v1", ()), ("matches", ()), ("match council", ()), ("match;council", ()), ("all", ()), ("*", ()), ("1", ()), ("true", ()), ("orchestrator", ()),
])
def test_the_agents_are_the_known_ones_the_list_names_in_the_canonical_order(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                                              expected: tuple[str, ...]) -> None:
    settings = env_of(monkeypatch) if raw is None else env_of(monkeypatch, FBI_AI_AGENTS=raw)
    assert settings.agents == expected
    assert settings.public()["agents"] == list(expected)


def test_a_settings_object_made_by_hand_has_no_agent() -> None:
    assert AiSettings().agents == () and AiSettings(mode="enforce").agents == ()


# ── the three together ────────────────────────────────────────────────────────────────────────────────────────────

def settings_with(*, mode: Any = "shadow", engines: tuple[str, ...] = BASE, sample: str = "0", agents: tuple[str, ...] = ()) -> AiSettings:
    return AiSettings(mode=mode, engines=engines, shadow_sample=D(sample), agents=agents)


ON: dict[str, Any] = {"engines": (*BASE, "ma-v1", "ma-v1-h"), "sample": "0.3", "agents": ("match", "council")}


def test_the_plans_activation_turns_the_orchestrator_on_and_its_rollback_turns_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    activated = {"FBI_AI_ENGINES": "rules,llm,ma-v1,ma-v1-h", "FBI_AI_SHADOW_SAMPLE": "0.3", "FBI_AI_AGENTS": "match,council"}
    assert env_of(monkeypatch, **activated).orchestrate is True
    assert env_of(monkeypatch, **activated).public()["orchestrate"] is True
    for rollback in ({"FBI_AI_ENGINES": "rules,llm"}, {"FBI_AI_SHADOW_SAMPLE": "0"}, {"FBI_AI_ENGINES": "rules,llm", "FBI_AI_SHADOW_SAMPLE": "0"},
                     {"FBI_AI_AGENTS": ""}, {"FBI_AI_MODE": "off"}):
        rolled = env_of(monkeypatch, **(activated | rollback))
        assert rolled.orchestrate is False, rollback
        assert rolled.public()["orchestrate"] is False


def test_nothing_runs_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert env_of(monkeypatch).orchestrate is False and AiSettings().orchestrate is False
    settings = env_of(monkeypatch)
    assert (settings.engines, settings.shadow_sample, settings.agents) == (BASE, D(0), ())


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_the_orchestrator_needs_every_word_and_a_layer_that_is_not_off(mode: str) -> None:
    """The whole truth table: of the 2 x 2 x 4 combinations of the words, exactly one per mode switches it on - and none when the layer is off."""
    for shadow, sampled, agents in itertools.product([False, True], [False, True], [(), ("match",), ("council",), ("match", "council")]):
        engines = (*BASE, "ma-v1") if shadow else BASE
        settings = settings_with(mode=mode, engines=engines, sample="0.3" if sampled else "0", agents=agents)
        expected = mode != "off" and shadow and sampled and agents == ("match", "council")
        assert settings.orchestrate is expected, (mode, engines, sampled, agents)


@pytest.mark.parametrize("engines", [("rules", "llm", "ma-v1"), ("rules", "llm", "ma-v1-h"), ("rules", "llm", "cs-v1"), ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1")])
def test_any_one_shadow_engine_is_enough_for_the_list(engines: tuple[str, ...]) -> None:
    assert settings_with(engines=engines, sample="0.01", agents=("match", "council")).orchestrate is True


def test_a_sample_of_a_hundredth_is_a_sample_and_zero_is_not() -> None:
    assert settings_with(**ON | {"sample": "0.0001"}).orchestrate is True
    assert settings_with(**ON | {"sample": "0"}).orchestrate is False


def test_the_three_words_move_nothing_else_of_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    on = env_of(monkeypatch, FBI_AI_MODE="shadow", FBI_AI_ENGINES="rules,llm,ma-v1,ma-v1-h", FBI_AI_SHADOW_SAMPLE="0.3", FBI_AI_AGENTS="match,council",
                FBI_AI_LAB_MONTHLY_BUDGET_USD="55")
    off = env_of(monkeypatch, FBI_AI_MODE="shadow", FBI_AI_LAB_MONTHLY_BUDGET_USD="55")
    as_on, as_off = dataclasses.asdict(on), dataclasses.asdict(off)
    for name in THREE:
        as_on.pop(name), as_off.pop(name)
    assert as_on == as_off, "every other setting is as the same environment without the words gives it"
    assert on.orchestrate and not off.orchestrate


def test_the_public_view_gains_five_keys_and_shows_no_key_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-ant-api03-THIS-MUST-NEVER-BE-SHOWN"
    settings = env_of(monkeypatch, FBI_AI_KEY_ANTHROPIC=secret, FBI_AI_ENGINES="ma-v1", FBI_AI_SHADOW_SAMPLE="0.3", FBI_AI_AGENTS="match")
    public = settings.public()
    assert {"engines", "shadow_engines", "shadow_sample", "agents", "orchestrate"} <= set(public)
    assert public["engines"] == ["rules", "llm", "ma-v1"] and public["shadow_engines"] == ["ma-v1"]
    assert public["shadow_sample"] == "0.3" and public["agents"] == ["match"] and public["orchestrate"] is False, "council is missing"
    assert secret not in json.dumps(public) and secret not in repr(settings)
    assert json.loads(json.dumps(public)) == public, "plain JSON: lists, strings and booleans"


def test_the_public_view_of_the_defaults_says_the_shadow_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    public = env_of(monkeypatch).public()
    assert (public["engines"], public["shadow_engines"], public["shadow_sample"], public["agents"], public["orchestrate"]) == (
        ["rules", "llm"], [], "0", [], False)


# ── the words of the docstring, the examples and the precheck are the words of the code ───────────────────────────

def test_the_module_tells_the_owner_the_defaults_and_the_activation_and_rollback_words() -> None:
    doc = config.__doc__ or ""
    for name in ("FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS"):
        assert name in doc, name
    assert "default ``rules,llm``" in doc and "``rules,llm,ma-v1,ma-v1-h``" in doc and "its rollback is ``rules,llm``" in doc
    assert "default 0" in doc and "The plan's activation is ``0.3``; its rollback is ``0``" in doc
    assert "default empty" in doc and "``match,council``" in doc
    assert "ALL THREE" in doc, "the module says that one word alone switches nothing on"


def example_value(path: Path, name: str) -> str:
    """The value a template shows for ``name`` as a commented default: ``# NAME=value`` (the template keeps the three off)."""
    found = re.findall(rf"^# {name}=(\S*)\s*$", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert len(found) == 1, f"{path.name} must show {name} once, as a comment"
    return found[0]


@pytest.mark.parametrize("path", [BACKEND / ".env.example", BACKEND / "deploy" / "vps" / "app.env.example"], ids=lambda p: p.name)
def test_the_examples_show_the_three_words_at_the_default_the_code_has(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shown = {name: example_value(path, name) for name in ("FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS")}
    assert shown == {"FBI_AI_ENGINES": "rules,llm", "FBI_AI_SHADOW_SAMPLE": "0", "FBI_AI_AGENTS": ""}
    from_example = env_of(monkeypatch, **shown)
    from_nothing = env_of(monkeypatch)
    assert (from_example.engines, from_example.shadow_sample, from_example.agents) == (from_nothing.engines, from_nothing.shadow_sample, from_nothing.agents)
    assert from_example.orchestrate is False, "copying the example as it is switches nothing on"


def test_the_precheck_may_print_the_value_of_the_three_words_because_they_are_words_and_figures() -> None:
    script = (BACKEND / "deploy" / "release" / "templates" / "server" / "step_precheck.sh").read_text(encoding="utf-8")
    allowed = re.search(r"function safe\(n\) \{ return n ~ /\^FBI_AI_\((.*?)\)\$/ \}", script)
    assert allowed, "the allow-list of the precheck was not found"
    names = allowed.group(1).split("|")
    for word in ("ENGINES", "SHADOW_SAMPLE", "AGENTS"):
        assert word in names, f"FBI_AI_{word} would be printed as 'set' and its value would never be seen"
    assert not any(re.search(r"KEY|TOKEN|SECRET|PASSWORD", f"FBI_AI_{w}") for w in ("ENGINES", "SHADOW_SAMPLE", "AGENTS"))

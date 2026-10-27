"""The words of the owner that the worker writes to the ledger (``fbi.ai.gates.switch_words``, review of phase 2, M5): which ones, in which
shape, and never a key. Pure: no database (the ledger itself is held in ``tests/integration/test_switch_ledger.py``)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from fbi.ai import gates
from fbi.ai.config import SWITCH_ENV, TIERS, AiSettings, TierModel

D = Decimal
KEY = "sk-ant-api03-THIS-MUST-NEVER-BE-WRITTEN-ANYWHERE"


def settings(**kw: object) -> AiSettings:
    base: dict[str, object] = {"mode": "shadow", "tiers": {"analysis": TierModel("anthropic", "claude-sonnet-5-5"),
                                                           "bulk": TierModel("anthropic", "claude-haiku-4-5")},
                               "keys": {"anthropic": KEY}, "lab_keys": {"anthropic": KEY + "-LAB"}, "monthly_budget": D(185),
                               "lab_monthly_budget": D(15), "exa_monthly_budget": D(35)}
    return AiSettings(**(base | kw))  # type: ignore[arg-type]


def test_the_words_are_the_ones_that_decide_what_the_layer_does_and_nothing_else() -> None:
    words = gates.switch_words(settings())
    assert set(words) == {"mode", "package", "research_v2", "switches", "models", "budgets_usd"}
    assert words["mode"] == "shadow" and words["package"] is True and words["research_v2"] == "off"
    assert words["switches"] == dict.fromkeys(sorted(SWITCH_ENV), "auto"), "every switch of phase 0, whatever its word"
    assert words["models"] == {"bulk": "claude-haiku-4-5", "analysis": "claude-sonnet-5-5"}, "the tiers that have a model, in the order of TIERS"
    assert list(words["models"]) == [t for t in TIERS if t in words["models"]]
    assert words["budgets_usd"] == {"production": "185", "lab": "15", "exa": "35"}


def test_no_key_no_url_and_no_label_ever_reaches_the_words() -> None:
    text = json.dumps(gates.switch_words(settings(workspace="PREDIGOL", key_label="worker-prod")), sort_keys=True)
    assert KEY not in text and "sk-ant" not in text and "worker-prod" not in text and "PREDIGOL" not in text and "http" not in text


def test_a_budget_is_a_word_in_its_plainest_form() -> None:
    for raw in (D(185), D("185.0"), D("185.00"), D("1.85E+2")):
        assert gates.switch_words(settings(monthly_budget=raw))["budgets_usd"]["production"] == "185", raw
    assert gates.switch_words(settings(monthly_budget=D("185.5")))["budgets_usd"]["production"] == "185.5"
    assert gates.switch_words(settings(monthly_budget=D(0)))["budgets_usd"]["production"] == "0"


def test_the_same_environment_gives_the_same_words_twice() -> None:
    assert gates.switch_words(settings()) == gates.switch_words(settings())
    assert json.dumps(gates.switch_words(settings()), sort_keys=True) == json.dumps(gates.switch_words(settings()), sort_keys=True)


@pytest.mark.parametrize(("change", "line"), [
    ({"research_v2": "shadow"}, "research_v2: off -> shadow"),
    ({"mode": "enforce"}, "mode: shadow -> enforce"),
    ({"package": False}, "package: True -> False"),
    ({"switches": {**dict.fromkeys(SWITCH_ENV, "auto"), "native_schema": "on"}}, "switches.native_schema: auto -> on"),
    ({"monthly_budget": D(200)}, "budgets_usd.production: 185 -> 200"),
    ({"tiers": {"analysis": TierModel("anthropic", "claude-opus-4-7"), "bulk": TierModel("anthropic", "claude-haiku-4-5")}},
     "models.analysis: claude-sonnet-5-5 -> claude-opus-4-7"),
])
def test_what_changed_is_said_one_line_per_word(change: dict[str, object], line: str) -> None:
    old, new = gates.switch_words(settings()), gates.switch_words(settings(**change))
    assert gates.words_diff(old, new) == [line]
    assert gates.words_diff(new, new) == []


def test_a_word_that_appears_or_disappears_is_a_change_too() -> None:
    old = gates.switch_words(settings())
    gone = gates.switch_words(settings(tiers={"analysis": TierModel("anthropic", "claude-sonnet-5-5")}))
    assert gates.words_diff(old, gone) == ["models.bulk: claude-haiku-4-5 -> None"]
    assert gates.words_diff(gone, old) == ["models.bulk: None -> claude-haiku-4-5"]
    assert gates.words_diff({}, {"a": 1}) == ["a: None -> 1"]


def test_two_changes_are_two_lines_in_a_stable_order() -> None:
    old = gates.switch_words(settings())
    new = gates.switch_words(settings(research_v2="shadow", mode="enforce"))
    assert gates.words_diff(old, new) == ["mode: shadow -> enforce", "research_v2: off -> shadow"]


def test_switches_is_a_gate_of_the_vocabulary_and_the_last_one() -> None:
    assert gates.GATES[-1] == gates.SWITCHES == "switches"
    assert len(set(gates.GATES)) == len(gates.GATES)

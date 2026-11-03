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


# ---- phase 3: the three words of the shadow (FBI_AI_ENGINES, FBI_AI_SHADOW_SAMPLE, FBI_AI_AGENTS) ----

SHADOW = {"engines": ("rules", "llm", "ma-v1", "ma-v1-h"), "shadow_sample": D("0.3"), "agents": ("match", "council")}


def test_the_shadow_words_are_not_written_while_they_hold_their_defaults() -> None:
    """Putting the phase-3 code in place is not a change of the owner's words: Gate A anchors its window on the last one."""
    assert gates.shadow_words(settings()) == {}
    assert gates.shadow_words(settings(engines=("rules", "llm"), shadow_sample=D(0), agents=())) == {}
    assert not {"engines", "shadow_sample", "agents"} & set(gates.switch_words(settings()))


def test_each_shadow_word_appears_only_once_it_has_been_moved_from_its_default() -> None:
    assert gates.shadow_words(settings(engines=("rules", "llm", "cs-v1"))) == {"engines": "rules,llm,cs-v1"}
    assert gates.shadow_words(settings(shadow_sample=D("0.3"))) == {"shadow_sample": "0.3"}
    assert gates.shadow_words(settings(agents=("match",))) == {"agents": "match"}
    assert gates.shadow_words(settings(**SHADOW)) == {"engines": "rules,llm,ma-v1,ma-v1-h", "shadow_sample": "0.3", "agents": "match,council"}
    assert gates.switch_words(settings(**SHADOW))["engines"] == "rules,llm,ma-v1,ma-v1-h"


def test_the_words_of_the_shadow_do_not_touch_the_other_words() -> None:
    base, shadowed = gates.switch_words(settings()), gates.switch_words(settings(**SHADOW))
    assert {k: v for k, v in shadowed.items() if k not in ("engines", "shadow_sample", "agents")} == base


def test_a_sample_is_a_word_in_its_plainest_form() -> None:
    for raw in (D("0.3"), D("0.30"), D("0.300"), D("3E-1")):
        assert gates.switch_words(settings(shadow_sample=raw))["shadow_sample"] == "0.3", raw
    assert gates.shadow_words(settings(shadow_sample=D(1))) == {"shadow_sample": "1"}
    assert gates.shadow_words(settings(shadow_sample=D("1.00"))) == {"shadow_sample": "1"}
    assert gates.shadow_words(settings(shadow_sample=D("0.0001"))) == {"shadow_sample": "0.0001"}


def test_switching_the_shadow_on_is_one_line_per_word_and_taking_it_back_is_too() -> None:
    off, on = gates.switch_words(settings()), gates.switch_words(settings(**SHADOW))
    assert gates.words_diff(off, on) == ["agents: None -> match,council", "engines: None -> rules,llm,ma-v1,ma-v1-h", "shadow_sample: None -> 0.3"]
    assert gates.words_diff(on, off) == ["agents: match,council -> None", "engines: rules,llm,ma-v1,ma-v1-h -> None", "shadow_sample: 0.3 -> None"]
    assert gates.words_diff(on, on) == []


def test_the_rollback_of_the_plan_is_a_change_of_the_ledger_but_not_a_new_state() -> None:
    """Rollback = FBI_AI_ENGINES=rules,llm and FBI_AI_SHADOW_SAMPLE=0 (the agents may stay): back to the words of before, plus the agents."""
    on = gates.switch_words(settings(**SHADOW))
    rolled = gates.switch_words(settings(engines=("rules", "llm"), shadow_sample=D(0), agents=("match", "council")))
    assert gates.words_diff(on, rolled) == ["engines: rules,llm,ma-v1,ma-v1-h -> None", "shadow_sample: 0.3 -> None"]
    assert rolled == {**gates.switch_words(settings()), "agents": "match,council"}


def test_no_key_no_url_and_no_label_reaches_the_shadow_words_either() -> None:
    text = json.dumps(gates.switch_words(settings(workspace="PREDIGOL", key_label="worker-prod", **SHADOW)), sort_keys=True)
    assert KEY not in text and "sk-ant" not in text and "worker-prod" not in text and "PREDIGOL" not in text and "http" not in text


def test_the_shadow_words_do_not_depend_on_how_the_owner_typed_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order, case, spaces and duplicates are read away before the words are written, so retyping the same switch is not a change."""
    typed = (({"FBI_AI_ENGINES": "cs-v1, MA-V1 ,llm,ma-v1", "FBI_AI_AGENTS": "council,match", "FBI_AI_SHADOW_SAMPLE": ".30"}),
             ({"FBI_AI_ENGINES": "rules,llm,ma-v1,cs-v1", "FBI_AI_AGENTS": "match,council", "FBI_AI_SHADOW_SAMPLE": "0.3"}))
    words = []
    for env in typed:
        monkeypatch.setattr("fbi.ai.config.environment", lambda env=env: env)
        words.append(gates.switch_words(AiSettings.from_env()))
    assert words[0] == words[1] and gates.words_diff(words[0], words[1]) == []
    assert words[0]["engines"] == "rules,llm,ma-v1,cs-v1" and words[0]["agents"] == "match,council" and words[0]["shadow_sample"] == "0.3"


def test_gate_a_does_not_move_its_window_when_the_shadow_code_is_deployed_but_does_when_the_shadow_is_switched_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate A anchors its window on the last change of the owner's words (``gate_a.switch_changes``). A worker that restarts with the phase-3
    code and the words of before writes the same words (no row); the day the owner switches the shadow on, the ledger carries a change."""
    from datetime import UTC, datetime

    from fbi.ai import gate_a

    before = gates.switch_words(settings())
    deployed = gates.switch_words(settings())  # the new code, the old words
    activated = gates.switch_words(settings(**SHADOW))
    rolled_back = gates.switch_words(settings())
    day = lambda d: datetime(2026, 11, d, 12, tzinfo=UTC)  # noqa: E731

    def ledger(rows: list[tuple[int, datetime, dict[str, object]]]) -> None:
        monkeypatch.setattr(gates, "switch_ledger", lambda conn: rows)

    ledger([(1, day(1), before), (2, day(2), deployed)])
    assert gate_a.switch_changes(None) == []  # type: ignore[arg-type]
    ledger([(1, day(1), before), (2, day(5), activated)])
    changes = gate_a.switch_changes(None)  # type: ignore[arg-type]
    assert [(d.day, why.startswith("the owner's words changed")) for d, why in changes] == [(5, True)]
    assert "engines: None -> rules,llm,ma-v1,ma-v1-h" in changes[0][1]
    ledger([(1, day(1), before), (2, day(5), activated), (3, day(20), rolled_back)])
    assert [d.day for d, _ in gate_a.switch_changes(None)] == [5, 20]  # type: ignore[arg-type]

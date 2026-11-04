"""«Explícame» (plan UX, B9): the codes and the door, without a database.

* Every sentence the service can send (``_say("<code>")``, both branches of a conditional, and the caution table's) has its
  template in the web, in Spanish and in English (``explain.say.<code>``): a code the page does not know would be left out, and
  an answer would lose a line without anybody noticing.
* The caution table answers every reason a pick's state can have (``fbi.picks.user_status.StatusReason``) - no more, no less.
* A question that is not the place's is refused before anything is read (422 ``unknown_question``), and the parlay being built
  only has its own door (``POST /explain/parlay``).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import get_args

import pytest

from fbi.api.problem import ApiError
from fbi.api.services import explain
from fbi.picks.user_status import StatusReason

LOCALES = Path(__file__).resolve().parents[3] / "web" / "src" / "locales"


def codes_said() -> set[str]:
    """The string codes ``explain.py`` passes to ``_say``: constants, both sides of a conditional, and the caution table."""
    tree = ast.parse(Path(explain.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_say" and node.args):
            continue
        first = node.args[0]
        options = [first.body, first.orelse] if isinstance(first, ast.IfExp) else [first]
        for option in options:
            if isinstance(option, ast.Constant) and isinstance(option.value, str):
                found.add(option.value)
    return found | set(explain.CAUTION_LINES.values())


def templates(lang: str) -> dict[str, object]:
    data = json.loads((LOCALES / lang / "explain.json").read_text(encoding="utf-8"))
    say: dict[str, object] = data["say"]
    return say


def test_the_codes_are_found() -> None:
    found = codes_said()
    assert {"has_pick", "no_pick_no_value", "forecast_market", "risks_intro", "pick_probability", "caution_downgraded",
            "parlay_product", "parlay_dependency", "parlay_related", "forecast_calibrated", "forecast_uncalibrated",
            "parlay_single", "parlay_all_win"} <= found
    assert len(found) >= 35


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_sentence_the_service_can_send_has_its_template(lang: str) -> None:
    """A template is the code itself or, for a sentence that counts, its plural forms (``<code>_one`` / ``<code>_other``)."""
    written = templates(lang)
    missing = sorted(code for code in codes_said() if code not in written and f"{code}_other" not in written)
    assert not missing, f"{lang}: codes without a template in explain.say: {missing}"


def terms_named() -> set[str]:
    """The glossary terms an answer offers: every ``terms=(...)`` the service writes."""
    tree = ast.parse(Path(explain.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        named = (isinstance(node, ast.keyword) and node.arg == "terms") or (
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "terms" for t in node.targets))
        value = getattr(node, "value", None)
        if named and isinstance(value, ast.Tuple):
            found |= {e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return found


def test_every_term_an_answer_offers_is_in_the_glossary() -> None:
    glossary = (LOCALES.parent / "lib" / "glossary" / "index.ts").read_text(encoding="utf-8")
    keys = set(re.findall(r"^  (\w+): \{\s*category:", glossary, flags=re.M))
    found = terms_named()
    assert {"pick", "value", "parlay", "dependency"} <= found and len(keys) >= 25, (found, len(keys))
    assert found <= keys, f"terms that are not in the glossary: {sorted(found - keys)}"


def test_both_languages_word_the_same_codes() -> None:
    assert set(templates("es")) == set(templates("en"))


def test_the_caution_table_answers_every_reason_of_a_state() -> None:
    assert set(explain.CAUTION_LINES) == set(get_args(StatusReason))


def test_the_questions_of_each_place() -> None:
    assert explain.INTENTS == {"match": ("no_pick", "forecast", "risks"), "pick": ("risks", "caution"),
                               "parlay": ("probability",)}


@pytest.mark.parametrize(("entity", "intent"), [("pick", "no_pick"), ("pick", "forecast"), ("match", "caution"),
                                                ("match", "probability"), ("parlay", "probability")])
def test_a_question_that_is_not_the_places_is_refused_before_anything_is_read(entity: str, intent: str) -> None:
    with pytest.raises(ApiError) as refused:
        explain.explain(None, entity, 1, intent, preview=False)  # type: ignore[arg-type]
    assert refused.value.status == 422 and refused.value.code == "unknown_question"

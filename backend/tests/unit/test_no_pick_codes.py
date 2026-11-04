"""Why a day has no pick (plan UX, A9): every reason ``GET /today`` can send - the published set's funnel reasons
(``fbi.picks.funnel`` with the daily set's own risk and context stages, ``fbi.picks.daily``) and the two of ``fbi.api.services.
today`` - has a sentence in the web, in Spanish and in English (``records.noPick.reason``), and every stage has one to fall back
on (``records.noPick.stage``). A reason without a sentence is left out on the page; this test makes sure none is.

The selection stage's reasons (a match already in the set, the set full) only happen on a day WITH picks: they need none."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from fbi.api.services import today
from fbi.picks import daily, funnel

LOCALES = Path(__file__).resolve().parents[3] / "web" / "src" / "locales"
ONLY_WITH_PICKS = frozenset({"match_taken", "day_full"})


def _strings_returned(path: Path, function: str) -> set[str]:
    """The string constants a function returns, alone or as the second item of a tuple."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            for ret in ast.walk(node):
                if not isinstance(ret, ast.Return) or ret.value is None:
                    continue
                value = ret.value
                if isinstance(value, ast.Tuple) and len(value.elts) == 2:
                    value = value.elts[1]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
    return found


def _stopped_literals(path: Path) -> set[str]:
    """``("context", "ai_rejected", x)``: the reasons ``funnel.report`` adds itself."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) != 3:
            continue
        stage, reason = node.elts[0], node.elts[1]
        if (isinstance(stage, ast.Constant) and isinstance(reason, ast.Constant) and isinstance(reason.value, str)
                and stage.value in funnel.STAGES):
            found.add(reason.value)
    return found


def reasons() -> set[str]:
    out = _strings_returned(Path(funnel.__file__), "first_stop")
    out |= _strings_returned(Path(daily.__file__), "stop")
    out |= _stopped_literals(Path(funnel.__file__))
    out |= {"no_matches", "no_qualified_candidates"}
    return out


def sentences(lang: str) -> dict[str, dict[str, str]]:
    data = json.loads((LOCALES / lang / "records.json").read_text(encoding="utf-8"))
    no_pick: dict[str, dict[str, str]] = data["noPick"]
    return no_pick


def test_the_reasons_are_found() -> None:
    found = reasons()
    assert {"non_positive_ev", "odds_above_cap", "not_reviewed", "ai_rejected", "day_full"} <= found
    assert len(found) >= 20


def test_every_reason_of_an_empty_day_has_its_sentence_in_both_languages() -> None:
    for lang in ("es", "en"):
        written = sentences(lang)
        # no_matches is said whole by its own sentence (records.noPick.noMatches), not as a reason
        missing = sorted(reasons() - ONLY_WITH_PICKS - {"no_matches"} - set(written["reason"]))
        assert not missing, f"{lang}: reasons without a sentence: {missing}"
        assert written["noMatches"] and written["honest"] and written["reviewing"]


def test_every_stage_has_a_sentence_to_fall_back_on() -> None:
    for lang in ("es", "en"):
        stages = set(sentences(lang)["stage"])
        assert set(today.STAGE_ORDER) - {"selection"} <= stages, lang
        assert set(today.STAGE_ORDER) == set(funnel.STAGES)

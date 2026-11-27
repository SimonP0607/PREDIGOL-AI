"""IA-215: the wording of the chronicle's prompt does not lead the model into sentences its own verifier drops.

Measured in production on 27 Nov 2026 (200 chronicles written after the cut of RP-1.3 was fixed): 197 lost sentences, and 542 of the 720 lost came
from two wordings of the prompt itself. These tests hold the cause, not the model: the glossary of a fact never carries the cue of a class the fact
does not authorise, the words the prompt gives for what is missing pass the verifier's own rules, and a market's code is told to stay out."""

from __future__ import annotations

import re

import pytest

from fbi.chronicle import claims, writer
from fbi.chronicle.verify import OWN_TOKENS
from fbi.narrative.job import FORBIDDEN, SYSTEM_TOKENS, fold

MISSING = {"es": "Todavía no están calculados los objetivos de la tabla para este partido",
           "en": "The table objectives have not been calculated yet for this match"}


@pytest.mark.parametrize("kind", sorted(k for k in writer.GLOSSARY if k.startswith("unknown.")))
def test_the_glossary_of_what_is_not_known_carries_no_cue_of_a_class_it_does_not_authorise(kind: str) -> None:
    """The explanation of a fact to the model must not carry the cue of a class the fact does not authorise (the old wording of two of them said
    «what is at stake»: the model repeated it and the verifier dropped the sentence)."""
    stated = claims.classes_stated(fold(writer.GLOSSARY[kind]), "en")
    assert [c for c in stated if c not in claims.classes_of_kind(kind)] == [], kind


@pytest.mark.parametrize("lang", ["es", "en"])
def test_the_words_given_for_what_is_missing_are_in_the_prompt_and_pass_the_verifiers_rules(lang: str) -> None:
    text = MISSING[lang]
    assert f"«{text}»" in writer.SYSTEM
    assert claims.classes_stated(fold(text), lang) == []
    assert SYSTEM_TOKENS.search(text) is None and OWN_TOKENS.search(text) is None
    assert FORBIDDEN[lang].search(fold(text)) is None


def test_the_cue_the_old_wording_carried_is_still_a_cue_of_the_class() -> None:
    """The verifier is untouched: «what is at stake» in a sentence that cites only an ``unknown.*`` fact is still dropped."""
    for lang, text in (("en", "There is no calculation yet of what is at stake in the table."), ("es", "Aún no hay cálculo de lo que se juega en la tabla.")):
        assert "OBJETIVO_EN_JUEGO" in claims.classes_stated(fold(text), lang)
    assert not claims.authorises("OBJETIVO_EN_JUEGO", ["unknown.scenarios", "unknown.rules", "unknown.lineups"])


def test_a_markets_code_is_told_to_stay_out_and_the_readers_words_are_given() -> None:
    assert "never as its code" in writer.SYSTEM
    for words in ("la victoria local", "el empate", "la victoria visitante", "más de / menos de", "que ambos equipos marquen"):
        assert words in writer.SYSTEM
    section = writer.SYSTEM[writer.SYSTEM.index("MARKETS."):writer.SYSTEM.index("NOT KNOWN YET.")]
    assert SYSTEM_TOKENS.search(re.sub(r"«[^»]*»", "", section).replace("1X2", "")) is None


def test_the_revision_of_the_wording_is_part_of_the_identity_of_what_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_chronicle_cut_rp13 import _input

    before = _input().hash
    monkeypatch.setattr(writer, "PROMPT_REVISION", writer.PROMPT_REVISION + 1)
    assert _input().hash != before and writer.PROMPT_REVISION >= 3

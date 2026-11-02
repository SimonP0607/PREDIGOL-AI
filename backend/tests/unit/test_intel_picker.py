"""The two pure pieces of the admin's match picker and dossier (``fbi.api.services.intelligence``): the text of a search as a LIKE pattern that
matches itself, and what a pass counted about the research a brief asked for. The queries themselves are held by
``tests/integration/test_intel_picker_and_dossier.py``."""

from __future__ import annotations

import pytest

from fbi.api.services.intelligence import _like, research_counts


@pytest.mark.parametrize(("text", "pattern"), [
    ("madrid", "%madrid%"),
    ("50%", "%50\\%%"),
    ("a_b", "%a\\_b%"),
    ("a\\b", "%a\\\\b%"),
    ("%_\\", "%\\%\\_\\\\%"),
    ("", "%%"),
])
def test_a_search_text_is_a_pattern_that_matches_itself(text: str, pattern: str) -> None:
    assert _like(text) == pattern


def test_a_pass_that_asked_for_nothing_counts_nothing() -> None:
    assert research_counts({}) == {"requested": 0, "asked": 0, "searched": 0, "unserved": {}, "web_searches": 0}


def test_the_research_of_a_pass_is_what_its_counts_say_by_reason() -> None:
    counts = {"research_requested": 1, "research_asked": 3, "research_searched": 1, "web_searches": 4,
              "research_unserved_no_allowance": 1, "research_unserved_near_budget": 1, "research_unserved_pass_budget": 0,
              "evidence_new": 9}
    assert research_counts(counts) == {"requested": 1, "asked": 3, "searched": 1, "web_searches": 4,
                                       "unserved": {"near_budget": 1, "no_allowance": 1}}


def test_counts_that_are_not_numbers_are_zero_not_an_error() -> None:
    counts = {"research_requested": "2", "research_asked": None, "research_searched": "many", "web_searches": [1],
              "research_unserved_no_search_pass": "x"}
    assert research_counts(counts) == {"requested": 2, "asked": 0, "searched": 0, "unserved": {}, "web_searches": 0}

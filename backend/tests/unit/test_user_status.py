"""The visible state of a pick (plan UX, B3): the one table, walked through every combination it can be asked about.

«Criterio de terminado: cada estado visible equivale a uno interno (prueba de la tabla con todas las combinaciones)». The
expected states below are written out, not computed: a change to the table has to change this file too.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from fbi.picks import user_status as us

REVIEWS = (*us.DECISIONS, None)

# (published, value, review, applied) -> (state, reason, context_pending), for the published picks with value: the rows where
# the AI's review can matter. Every other combination is in the two blocks after it.
PUBLISHED_WITH_VALUE = {
    (True, True, "APPROVE", True): ("RECOMMENDED", "approved", False),
    (True, True, "DOWNGRADE", True): ("CAUTION", "downgraded", False),
    (True, True, "REJECT", True): ("NOT_RECOMMENDED", "rejected", False),
    (True, True, "ABSTAIN", True): ("RECOMMENDED", "not_reviewed", True),
    (True, True, None, True): ("RECOMMENDED", "not_reviewed", True),
    (True, True, "APPROVE", False): ("RECOMMENDED", "value", True),
    (True, True, "DOWNGRADE", False): ("RECOMMENDED", "value", True),
    (True, True, "REJECT", False): ("RECOMMENDED", "value", True),
    (True, True, "ABSTAIN", False): ("RECOMMENDED", "value", True),
    (True, True, None, False): ("RECOMMENDED", "value", True),
}
WITHOUT_VALUE = {(True, False, review, applied): ("NOT_RECOMMENDED", "no_value_now", False)
                 for review in REVIEWS for applied in (True, False)}
IN_EVALUATION = {(False, value, review, applied): ("EVALUATION", "evaluation", False)
                 for value in (True, False) for review in REVIEWS for applied in (True, False)}
TABLE = PUBLISHED_WITH_VALUE | WITHOUT_VALUE | IN_EVALUATION


def test_the_table_covers_every_combination_once() -> None:
    combos = set(itertools.product((True, False), (True, False), REVIEWS, (True, False)))
    assert len(combos) == 40
    assert set(TABLE) == combos


@pytest.mark.parametrize(("key", "expected"), sorted(TABLE.items(), key=repr))
def test_each_combination_has_its_state(key: tuple[bool, bool, str | None, bool], expected: tuple[str, str, bool]) -> None:
    published, value, review, applied = key
    got = us.shown(published=published, value=value, review=review, applied=applied)
    assert (got.status, got.reason, got.context_pending) == expected


def test_every_state_and_every_reason_is_reachable_and_nothing_else() -> None:
    assert {v[0] for v in TABLE.values()} == set(us.STATES)
    assert {v[1] for v in TABLE.values()} == set(us.REASONS)


def test_a_review_that_is_not_applied_changes_nothing() -> None:
    for published, value, review in itertools.product((True, False), (True, False), REVIEWS):
        assert us.shown(published=published, value=value, review=review, applied=False) == us.shown(
            published=published, value=value, review=None, applied=False)


def test_only_a_recommendation_says_its_context_review_is_pending() -> None:
    for state, _, pending in TABLE.values():
        assert not pending or state == "RECOMMENDED"


def test_the_list_of_picks_never_shows_a_rejected_an_unpriced_or_an_evaluation_pick() -> None:
    assert {"RECOMMENDED", "CAUTION"} == us.IN_LIST
    for key, (state, _, _) in TABLE.items():
        published, value, review, applied = key
        listed = state in us.IN_LIST
        assert listed == (published and value and not (applied and review == "REJECT")), key


def test_publication_states() -> None:
    assert us.is_published("qualified") and us.is_published("published")
    for status in ("shadow", "candidate", "rejected", "settled", "", None):
        assert not us.is_published(status)


CARD_KINDS = ("value", "evaluated", "no_market")


def card_expected(kind: str, qualified: bool, review: str | None, applied: bool) -> tuple[str, str, bool] | None:
    """A match analysis's card, written out: a value card is a pick (published when qualified), an evaluated card has no value
    at its price, and an unpriced market has no state."""
    if kind == "no_market":
        return None
    if kind == "evaluated":
        return ("NOT_RECOMMENDED", "no_value_now", False)
    return TABLE[(qualified, True, review, applied)]


@pytest.mark.parametrize(("kind", "qualified", "review", "applied"),
                         list(itertools.product(CARD_KINDS, (True, False), REVIEWS, (True, False))))
def test_each_analysis_card_has_its_state(kind: str, qualified: bool, review: str | None, applied: bool) -> None:
    got = us.of_card(kind=kind, qualified=qualified, review=review, applied=applied)
    expected = card_expected(kind, qualified, review, applied)
    assert (None if got is None else (got.status, got.reason, got.context_pending)) == expected


def test_the_card_rows_are_sixty_and_the_value_ones_follow_the_table() -> None:
    rows = list(itertools.product(CARD_KINDS, (True, False), REVIEWS, (True, False)))
    assert len(rows) == 60
    assert us.of_card(kind="value", qualified=True, review="DOWNGRADE", applied=True) == us.shown(
        published=True, value=True, review="DOWNGRADE", applied=True)


def test_the_module_reads_and_decides_nothing_else() -> None:
    """Pure: it imports no rule, no engine, no database driver, nothing of the user layer - only the standard library."""
    tree = ast.parse(Path(us.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "dataclasses", "typing"}, imported

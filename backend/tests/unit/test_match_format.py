"""RP-3.2: the pure reading of a match's format from the role of its stage and the format of its tie."""

from __future__ import annotations

import pytest

from fbi.competitions import match_format as mf


@pytest.mark.parametrize(("role", "tie", "leg", "expected"), [
    ("league", None, None, mf.LEAGUE),
    ("group", None, None, mf.GROUP),
    ("friendly", None, None, mf.FRIENDLY),
    ("final", "single", 1, mf.FINAL),
    ("third_place", "single", 1, mf.THIRD_PLACE),
    ("knockout", "single", 1, mf.KNOCKOUT_SINGLE),            # Copa del Rey / FA Cup round of 16
    ("knockout", "two_legged", 1, mf.KNOCKOUT_TWO_LEGGED),    # Champions League round of 16, first leg
    ("knockout", "two_legged", 2, mf.KNOCKOUT_TWO_LEGGED),
    ("qualifying", "two_legged", 1, mf.KNOCKOUT_TWO_LEGGED),
    ("playoff", "series", 3, mf.KNOCKOUT_SERIES),             # MLS Cup best of three, third game
    ("knockout", "replay", 2, mf.REPLAY),                     # FA Cup replay
    ("knockout", "replay", 1, mf.KNOCKOUT_SINGLE),            # the first match of a tie that needed a replay shows ONE match
    ("knockout", "series", 1, mf.KNOCKOUT_SINGLE),
])
def test_format_of_real_cases(role: str, tie: str | None, leg: int | None, expected: str) -> None:
    assert mf.format_of(role, tie, leg) == expected


@pytest.mark.parametrize(("role", "tie", "leg"), [
    (None, None, None), ("unresolved", "single", 1),
    ("knockout", None, None),   # a stage that is not a bracket / a cancelled match: no pairing, no format
    ("playoff", "single", None),
])
def test_what_cannot_be_read_is_unknown_never_guessed(role: str | None, tie: str | None, leg: int | None) -> None:
    assert mf.format_of(role, tie, leg) == mf.UNKNOWN


def test_every_format_is_listed_once() -> None:
    assert len(set(mf.FORMATS)) == len(mf.FORMATS) and mf.UNKNOWN in mf.FORMATS

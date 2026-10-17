"""The provider spells one status two ways; we read both as one.

Fixture 1438655 (AFC Champions League Two 2025) arrives with ``"short": "Canc"``
while most cancelled fixtures arrive as ``"CANC"``. Every map downstream is keyed
on the documented upper-case codes, so the mixed-case one fell through to the
default and 78 cancelled fixtures plus one abandoned one were stored as
*scheduled* - past kick-off, waiting for a result that would never come, and
counted by the Data Quality page as "awaiting a result".
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.ingestion.fixtures import STATUS_GROUP, status_group
from fbi.ingestion.live_match import iter_live_states
from fbi.picks.settlement import MatchState, Status, settle
from fbi.providers.api_football.normalize import (
    CANONICAL_STATUSES,
    canonical_status,
    iter_fixture_results,
    iter_fixtures,
)

KICKOFF = datetime(2025, 11, 5, 11, 0, tzinfo=UTC)


def entry(status: object, goals: tuple[int | None, int | None] = (None, None)) -> dict:
    return {
        "fixture": {"id": 1438655, "date": KICKOFF.isoformat(), "status": {"short": status, "elapsed": None}},
        "league": {"id": 18, "season": 2025, "round": "Group Stage - 4"},
        "teams": {"home": {"id": 1, "name": "H"}, "away": {"id": 2, "name": "A"}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {"halftime": {"home": None, "away": None}, "fulltime": {"home": goals[0], "away": goals[1]},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
    }


@pytest.mark.parametrize(("raw", "expected"), [
    ("Canc", "CANC"), ("CANC", "CANC"), ("Abd", "ABD"), (" ft ", "FT"), ("Pen", "PEN"),
    ("", "NS"), (None, "NS"), (7, "NS"),
])
def test_a_short_status_is_spelled_one_way(raw: object, expected: str) -> None:
    assert canonical_status(raw) == expected


def test_every_documented_code_already_is_its_own_spelling() -> None:
    assert {canonical_status(code) for code in CANONICAL_STATUSES} == CANONICAL_STATUSES
    assert set(STATUS_GROUP) <= CANONICAL_STATUSES


@pytest.mark.parametrize(("raw", "group"), [("Canc", "cancelled"), ("Abd", "cancelled"), ("Pst", "postponed"),
                                            ("Susp", "postponed"), ("ft", "finished"), ("Ns", "scheduled")])
def test_a_mixed_case_status_lands_in_its_group(raw: str, group: str) -> None:
    ref = next(iter_fixtures({"response": [entry(raw)]}))
    assert ref.status_short == raw.upper()
    assert status_group(ref.status_short) == group
    assert status_group(raw) == group, "the lookup itself does not depend on the spelling either"


def test_an_unknown_status_keeps_the_caller_s_default() -> None:
    assert status_group("XYZ") == "scheduled"
    assert status_group("XYZ", "finished") == "finished"


def test_a_finished_match_spelled_in_mixed_case_still_has_a_result() -> None:
    result = next(iter_fixture_results({"response": [entry("Ft", (2, 1))]}))
    assert (result.status_short, result.goals_home, result.goals_away) == ("FT", 2, 1)


def test_a_cancelled_match_spelled_in_mixed_case_has_no_result() -> None:
    assert list(iter_fixture_results({"response": [entry("Canc", (0, 0))]})) == []


def test_the_live_follower_reads_the_same_spelling() -> None:
    state = next(iter_live_states({"response": [entry("Canc")]}))
    assert state.status_short == "CANC"


def test_a_pick_on_a_cancelled_match_is_void_however_the_status_is_spelled() -> None:
    state = MatchState("Canc", None, None, None, None)
    out = settle("1X2", "Home", Decimal(0), Decimal("2.10"), Decimal(1), state)
    assert out.status is Status.VOID

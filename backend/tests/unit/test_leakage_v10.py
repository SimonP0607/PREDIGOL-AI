"""``leak-audit-v10`` without a database (IA-061, ``fbi.intel.leakage_v10``): the verdicts of its rules over hand-made rows, the case of 12 Nov 2026
(state 6912) replayed, and that v9 is left exactly as it was."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.ai import final_reread as fr
from fbi.intel import leakage
from fbi.intel import leakage_v10 as v10

KNOWN = datetime(2026, 11, 12, 19, 20, 51, tzinfo=UTC)
WRITTEN = datetime(2026, 11, 12, 19, 26, 51, tzinfo=UTC)
STATED = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
REAL = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)
M = timedelta(minutes=1)


def test_v9_is_the_audit_v10_extends_and_it_is_untouched() -> None:
    assert leakage.VERSION == "leak-audit-v9" == v10.BASE_VERSION
    assert v10.VERSION == "leak-audit-v10"
    assert not set(v10.RULE_NAMES) & set(leakage.RULE_NAMES), "v10 writes only rules v9 does not have: v9's rows are never written twice"
    for rule in v10.RULE_NAMES:
        assert rule in (v10.__doc__ or "")
    assert fr.VERSION in v10.READINGS


# ── final_started_known: the case of 12 November ────────────────────────────────────────────────────────────────

def state(**over: Any) -> dict[str, Any]:
    base = {"id": 6912, "fixture_id": 180277, "run_kind": "live", "known_at": KNOWN, "created_at": WRITTEN, "kickoff_at": REAL, "stated_then": STATED}
    return base | over


def test_state_6912_is_explained_by_the_provider_not_honest_and_not_hidden() -> None:
    """Today the kick-off is 19:00, before the moment 19:20:51: the state was written with the match under way. When it was written the provider
    said 20:00 (the change was observed on 13 Nov at 10:57:29): explained, and written down as such."""
    assert v10.started_verdict(state()) == "explained"


def test_a_state_known_before_the_kickoff_of_today_is_honest() -> None:
    assert v10.started_verdict(state(kickoff_at=STATED, stated_then=None)) == "honest"
    assert v10.started_verdict(state(kickoff_at=KNOWN + M, stated_then=None)) == "honest"


def test_a_state_written_when_the_system_already_had_the_match_started_is_a_violation() -> None:
    assert v10.started_verdict(state(stated_then=None)) == "violation", "no change after the writing: its own data said the match had started"
    assert v10.started_verdict(state(stated_then=KNOWN)) == "violation", "the provider said a kick-off at the moment itself: not later"
    assert v10.started_verdict(state(stated_then=KNOWN - M)) == "violation"
    assert v10.started_verdict(state(kickoff_at=None, stated_then=STATED)) == "violation", "a match that is not there cannot be explained"


# ── final_reread_known ──────────────────────────────────────────────────────────────────────────────────────────

def shadow(rec: Any, **over: Any) -> dict[str, Any]:
    base = {"id": 1, "fixture_id": 9, "run_kind": "shadow", "known_at": KNOWN, "created_at": WRITTEN, "reread": rec,
            "packet_kickoff": STATED.isoformat(), "kickoff_at": STATED}
    return base | over


def honest_record(at: datetime = WRITTEN - M) -> dict[str, Any]:
    return fr.judge(STATED, "NS", fr.Reading(9, at, STATED, "NS"), at=at).record()


def test_a_state_with_the_reading_the_pass_made_is_honest() -> None:
    assert v10.reread_problems(shadow(honest_record())) == []
    assert v10.reread_problems(shadow(honest_record(at=KNOWN))) == [] and v10.reread_problems(shadow(honest_record(at=WRITTEN))) == []


def test_a_state_without_a_reading_or_with_one_this_code_does_not_know_is_a_violation() -> None:
    assert v10.reread_problems(shadow(None)) == ["no_reread"]
    assert v10.reread_problems(shadow("text")) == ["no_reread"]
    assert v10.reread_problems(shadow(honest_record() | {"version": "reread-v9"})) == ["reread_version"]


@pytest.mark.parametrize("change, code", [
    ({"ok": False, "reason": "kickoff_moved"}, "reread_not_ok"),
    ({"at": (KNOWN - M).isoformat()}, "reread_out_of_time"),
    ({"at": (WRITTEN + M).isoformat()}, "reread_out_of_time"),
    ({"at": None}, "reread_out_of_time"),
    ({"kickoff_at": (STATED + M).isoformat()}, "reread_kickoff_differs"),
    ({"packet_kickoff_at": (STATED - M).isoformat()}, "reread_kickoff_differs"),
    ({"status": "1H"}, "reread_not_scheduled"),
    ({"status": "PST"}, "reread_not_scheduled"),
    ({"in_play_at": WRITTEN.isoformat()}, "reread_not_scheduled"),
])
def test_each_way_a_reading_can_be_wrong_is_found(change: dict[str, Any], code: str) -> None:
    assert code in v10.reread_problems(shadow(honest_record() | change))


def test_a_reading_that_saw_a_kickoff_already_passed_is_found_even_when_it_is_the_packets() -> None:
    rec = honest_record() | {"kickoff_at": (WRITTEN - 2 * M).isoformat(), "packet_kickoff_at": (WRITTEN - 2 * M).isoformat()}
    assert v10.reread_problems(shadow(rec, packet_kickoff=(WRITTEN - 2 * M).isoformat())) == ["reread_after_kickoff"]

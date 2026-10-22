"""One answer to "what state is this match in?" (fbi.core.match_state), checked code by code."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.core import match_state as ms
from fbi.core.match_state import Phase

KO = datetime(2026, 10, 9, 18, tzinfo=UTC)

EXPECTED = {  # the provider's documented codes and the phase every screen shows
    "TBD": Phase.SCHEDULED, "NS": Phase.SCHEDULED,
    "1H": Phase.LIVE, "HT": Phase.LIVE, "2H": Phase.LIVE, "ET": Phase.LIVE, "BT": Phase.LIVE, "P": Phase.LIVE,
    "LIVE": Phase.LIVE, "INT": Phase.LIVE, "SUSP": Phase.SUSPENDED,
    "FT": Phase.FINISHED, "AET": Phase.FINISHED, "PEN": Phase.FINISHED,
    "PST": Phase.POSTPONED, "CANC": Phase.CANCELLED, "ABD": Phase.ABANDONED,
    "AWD": Phase.NOT_PLAYED, "WO": Phase.NOT_PLAYED,
}


@pytest.mark.parametrize(("code", "phase"), sorted(EXPECTED.items()))
def test_every_provider_code_has_one_phase(code: str, phase: Phase) -> None:
    assert ms.phase_of(code) is phase
    assert ms.phase_of(code.lower()) is phase, "the provider spells 'Canc' too"
    assert ms.is_live(code) == (code in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"})
    assert ms.is_finished(code) == (code in {"FT", "AET", "PEN"})
    assert ms.is_scheduled(code) == (code in {"TBD", "NS"})


def test_nothing_that_was_not_played_is_finished() -> None:
    """The web used to show a cancelled, abandoned or awarded match as "Final"."""
    for code in ("CANC", "ABD", "AWD", "WO", "PST", "SUSP"):
        assert not ms.is_finished(code)
        assert ms.phase_of(code) is not Phase.FINISHED


def test_an_unknown_code_is_unknown() -> None:
    assert ms.phase_of("XYZ") is Phase.UNKNOWN and ms.phase_of(None) is Phase.UNKNOWN and ms.phase_of("") is Phase.UNKNOWN


def test_a_stale_scheduled_or_live_code_is_not_believed() -> None:
    assert ms.phase("NS", KO, KO + timedelta(minutes=14)) is Phase.SCHEDULED
    assert ms.phase("NS", KO, KO + timedelta(minutes=15)) is Phase.AWAITING
    assert ms.phase("2H", KO, KO + timedelta(hours=3, minutes=29)) is Phase.LIVE
    assert ms.phase("HT", KO, KO + timedelta(hours=3, minutes=30)) is Phase.AWAITING
    assert ms.phase("SUSP", KO, KO + timedelta(days=2)) is Phase.SUSPENDED, "suspended until the provider says"
    assert ms.phase("FT", KO, KO + timedelta(days=30)) is Phase.FINISHED
    assert ms.phase("NS", None, KO) is Phase.SCHEDULED


def test_the_stored_group_has_not_changed() -> None:
    """Features, backtests and audits read core.fixtures.status_group: its meaning must not move."""
    assert ms.STORED_GROUP == {
        "TBD": "scheduled", "NS": "scheduled",
        "1H": "live", "HT": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live",
        "INT": "live", "FT": "finished", "AET": "finished", "PEN": "finished",
        "SUSP": "postponed", "PST": "postponed",
        "CANC": "cancelled", "ABD": "cancelled", "AWD": "cancelled", "WO": "cancelled",
    }
    from fbi.ingestion.fixtures import STATUS_GROUP, status_group
    from fbi.truth.compare import STATUS_GROUP as AUDIT_GROUP
    assert STATUS_GROUP == ms.STORED_GROUP == AUDIT_GROUP
    assert status_group(" canc ") == "cancelled"


def test_what_triggers_settlement() -> None:
    assert {"FT", "AET", "PEN", "CANC", "ABD", "AWD", "WO", "PST", "SUSP"} == ms.ENDED
    assert set(EXPECTED) == ms.KNOWN


# ── why a match that should be over has no result (REVIEW 11 Oct 2026) ─────────────────────────────────────────

KO_R = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _wait(status: str, at: datetime, *, read: datetime | None = None, result: bool = False,
          healthy: bool = True) -> ms.ResultWait | None:
    return ms.result_wait(status, KO_R, provider_read_at=read, has_result=result, at=at, jobs_healthy=healthy)


def test_nothing_is_wrong_before_kickoff_while_playing_and_after_a_result() -> None:
    assert _wait("NS", KO_R - timedelta(hours=1)) is None
    assert _wait("2H", KO_R + timedelta(minutes=80)) is None
    assert _wait("INT", KO_R + timedelta(hours=2)) is None, "interrupted, but still within any match's length"
    for status in ("FT", "AET", "PEN"):
        assert _wait(status, KO_R + timedelta(hours=3), result=True) is None


def test_a_match_the_provider_has_not_closed_is_the_providers_to_close() -> None:
    """Rayo Vallecano - Athletic, 10 Oct 2026: still "INT" when read 17 h after kick-off."""
    at = KO_R + timedelta(hours=18)
    assert _wait("INT", at, read=KO_R + timedelta(hours=17)) is ms.ResultWait.PROVIDER_PENDING
    assert _wait("NS", at, read=KO_R + timedelta(hours=17)) is ms.ResultWait.PROVIDER_PENDING


def test_no_read_since_the_match_should_have_ended_is_silence_or_our_stalled_jobs() -> None:
    at = KO_R + timedelta(hours=5)
    assert _wait("NS", at, read=KO_R - timedelta(hours=2)) is ms.ResultWait.PROVIDER_SILENT
    assert _wait("1H", at, read=None) is ms.ResultWait.PROVIDER_SILENT
    assert _wait("1H", at, read=None, healthy=False) is ms.ResultWait.JOBS_STALLED


def test_a_finished_match_with_a_kickoff_ahead_is_a_provider_conflict() -> None:
    """Sporting JAX - Birmingham Legion, 10 Oct 2026: FT, then its kick-off moved to 14 Oct."""
    assert _wait("FT", KO_R - timedelta(days=4), result=True) is ms.ResultWait.PROVIDER_CONFLICT


def test_a_finished_match_without_its_score_is_flagged_for_us() -> None:
    assert _wait("FT", KO_R + timedelta(hours=3)) is ms.ResultWait.RESULT_MISSING


def test_a_match_the_provider_says_will_have_no_normal_result_is_not_waiting() -> None:
    at = KO_R + timedelta(days=2)
    for status in ("PST", "CANC", "ABD", "AWD", "WO", "SUSP"):
        assert _wait(status, at, read=KO_R + timedelta(days=1)) is None, status


# --------------------------------------------------------------------------------- a final whistle needs a match first

GWANGJU_ULSAN_KO = datetime(2026, 10, 11, 5, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("code", "minutes_after_kickoff", "plausible"),
    [
        ("FT", 4, False),  # 11 Oct 2026, Gwangju - Ulsan: "FT, 90 minutes, 1-1" four minutes after kick-off (it ended 4-3)
        ("FT", 59, False),
        ("FT", 60, True),
        ("FT", 112, True),
        ("ft", 4, False),  # the provider spells codes both ways
        ("AET", 99, False),
        ("AET", 100, True),
        ("PEN", 60, False),
        ("PEN", 130, True),
        ("1H", 3, True),  # only a FINISHED code can be too early
        ("HT", 5, True),
        ("NS", 0, True),
        ("PST", 0, True),
        ("CANC", 1, True),  # a cancellation can come at any time
        ("AWD", 0, True),
        ("WO", 0, True),
        ("ABD", 20, True),
        ("SUSP", 30, True),
    ],
)
def test_a_final_whistle_cannot_come_before_a_match_could_end(code: str, minutes_after_kickoff: int,
                                                              plausible: bool) -> None:
    seen = GWANGJU_ULSAN_KO + timedelta(minutes=minutes_after_kickoff)
    assert ms.final_is_plausible(code, GWANGJU_ULSAN_KO, seen) is plausible


def test_a_reading_before_kickoff_is_not_a_final_either() -> None:
    """Sporting JAX - Birmingham Legion, 10 Oct 2026: FT, then moved to 14 Oct - the reading came before the match."""
    assert not ms.final_is_plausible("FT", GWANGJU_ULSAN_KO, GWANGJU_ULSAN_KO - timedelta(days=4))


def test_without_a_kickoff_date_there_is_nothing_to_refuse_it_by() -> None:
    assert ms.final_is_plausible("FT", None, GWANGJU_ULSAN_KO)
    assert ms.final_is_plausible(None, GWANGJU_ULSAN_KO, GWANGJU_ULSAN_KO)


def test_every_floor_is_for_a_finished_code_and_below_what_a_real_match_lasts() -> None:
    assert set(ms.FINAL_NOT_BEFORE) == ms.FINISHED
    assert ms.FINAL_NOT_BEFORE["FT"] <= timedelta(minutes=70), "a true 90-minute result must never be held back"
    assert ms.FINAL_NOT_BEFORE["AET"] <= timedelta(minutes=110) and ms.FINAL_NOT_BEFORE["PEN"] <= timedelta(minutes=110)
    assert ms.FINAL_NOT_BEFORE["AET"] > ms.FINAL_NOT_BEFORE["FT"], "extra time takes longer than ninety minutes"


def test_a_kickoff_without_a_zone_is_read_as_utc_and_never_breaks_the_comparison() -> None:
    """The guard runs on every payload: a date that came without an offset must not be what fails the payload."""
    naive = GWANGJU_ULSAN_KO.replace(tzinfo=None)  # as `datetime.fromisoformat` reads a date with no offset
    four_minutes_in = GWANGJU_ULSAN_KO + timedelta(minutes=4)
    assert not ms.final_is_plausible("FT", naive, four_minutes_in)
    assert ms.final_is_plausible("FT", naive, GWANGJU_ULSAN_KO + timedelta(minutes=112))
    assert ms.minutes_after_kickoff(naive, four_minutes_in) == 4.0
    assert ms.minutes_after_kickoff(GWANGJU_ULSAN_KO, naive) == 0.0

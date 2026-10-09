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

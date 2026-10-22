"""The server's 5-minute health check (deploy/vps/bin/healthcheck.sh) raises an alarm only when it is true."""

from __future__ import annotations

import re
from pathlib import Path

from fbi.core import match_state

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin" / "healthcheck.sh"


def test_a_match_the_provider_left_interrupted_for_days_is_not_in_play() -> None:
    """Regression (22 Oct 2026): the in-play check counted every fixture whose stored group is 'live'. The provider leaves
    some matches at INT for days (Rayo Vallecano - Athletic on 10 Oct; two more by 22 Oct, one since 31 Aug), so the verdict
    read "2 matches in play, last in-play capture 27133s ago" - 'problem' - for days, while there was nothing to capture.
    An alarm that is always on hides the day it is true."""
    text = SCRIPT.read_text(encoding="utf-8")
    query = re.search(r'playing="\$\(psql_q "(SELECT count\(\*\) FROM core\.fixtures WHERE [^"]*)"', text)
    assert query is not None, "the in-play count is a query on core.fixtures"
    where = query.group(1)
    assert "status_group = 'live'" in where
    window = re.search(r"kickoff_at > now\(\) - interval '(\d+) minutes'", where)
    assert window is not None, "a stored in-play code only counts for a while after kick-off"
    assert int(window.group(1)) * 60 == match_state.LIVE_STALE_AFTER.total_seconds(), (
        "the same window the application believes (match_state.LIVE_STALE_AFTER), not another one")

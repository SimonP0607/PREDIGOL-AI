"""An error inside a run that spoke to the provider is the provider's only when it came from the provider."""

from __future__ import annotations

import pytest

from fbi.quality.metrics import is_provider_error


@pytest.mark.parametrize("text", [
    "HTTP 429",
    "players_season 32/2024: /players: provider reported errors: {'rateLimit': 'Too many requests.'}",
    "ConnectError: [Errno 104] Connection reset by peer",
    "ReadTimeout: timed out",
    "HTTP 503 Service Unavailable",
    "circuit open after 5 failures",
])
def test_provider_errors(text: str) -> None:
    assert is_provider_error(text)


@pytest.mark.parametrize("text", [
    "QueryCanceled: canceling statement due to statement timeout",
    "CheckViolation: new row for relation \"picks\" violates check constraint \"picks_interval_check\"",
    "run cap of 400 request(s) reached (400 spent in this run)",
    "request cap 10 reached; 35 fixtures not followed this pass",
    "interrupted: timed out after 600 s (job deadline)",
    "stale: no owner recorded and open for 12 h; closed by the run watchdog",
    None,
    "",
])
def test_not_provider_errors(text: str | None) -> None:
    assert not is_provider_error(text)

"""The kind of caller of an endpoint on its way out (BE-033): only a reader's browser keeps ``/odds/best`` alive."""

from __future__ import annotations

import pytest

from fbi.api.services.deprecated import SUCCESSORS, caller_kind


@pytest.mark.parametrize(
    ("user_agent", "kind"),
    [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari", "browser"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "browser"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/131.0 Safari/537.36", "e2e"),
        ("Playwright/1.57.0 (x64; linux)", "e2e"),
        ("testclient", "testclient"),
        ("curl/8.5.0", "script"),
        ("python-httpx/0.28.1", "script"),
        ("python-requests/2.32", "script"),
        ("", "other"),
        (None, "other"),
        ("SomethingElse/1.0", "other"),
    ],
)
def test_caller_kind(user_agent: str | None, kind: str) -> None:
    assert caller_kind(user_agent) == kind


def test_odds_best_names_its_successor() -> None:
    assert SUCCESSORS["/odds/best"] == "/api/v1/odds/board"

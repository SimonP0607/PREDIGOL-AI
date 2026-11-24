"""The kind of caller of an endpoint on its way out (BE-033): only a reader's browser keeps it alive. And the register of the routes
already retired (PM-13-07, UX-232): none of them is mounted, so each answers 404."""

from __future__ import annotations

import pytest

from fbi.api.services.deprecated import RETIRED, SUCCESSORS, caller_kind


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


def test_no_route_is_on_its_way_out_now() -> None:
    assert SUCCESSORS == {}, "a route on its way out names its successor here; an empty register is the state after UX-232"


def test_a_retired_route_is_not_mounted_and_its_successor_is() -> None:
    from fbi.api.app import create_app

    mounted = set(create_app().openapi()["paths"])
    assert RETIRED == {"/odds/best": "/api/v1/odds/board"}
    for path, successor in RETIRED.items():
        assert f"/api/v1{path}" not in mounted, f"{path} was retired (PM-13-07) and must answer 404"
        assert successor in mounted, f"{path} was replaced by {successor}, which must be mounted"

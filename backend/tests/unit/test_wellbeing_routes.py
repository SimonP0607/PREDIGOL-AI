"""The single table of what shows a price (plan PM, PM-14-07): every call outside the Admin Console is decided, none by omission."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.api import wellbeing_routes as table


@pytest.fixture(scope="module")
def calls() -> list[tuple[str, str]]:
    from fbi.api.app import create_app

    spec: dict[str, Any] = create_app().openapi()
    found = [(m.upper(), p.removeprefix("/api/v1")) for p, ops in spec["paths"].items()
             if p.startswith("/api/v1/") and not p.startswith("/api/v1/admin")
             for m in ops if m in ("get", "post", "put", "patch", "delete")]
    assert len(found) >= 150, "the routes were not found in the OpenAPI document"
    return sorted(found)


def kind(method: str, path: str) -> str | None:
    if table.blocked(method, path):
        return "blocked"
    if table.mixed(method, path):
        return "mixed"
    if table.open_(method, path):
        return "open"
    return None


def test_every_call_is_decided(calls: list[tuple[str, str]]) -> None:
    undecided = [f"{m} {p}" for m, p in calls if kind(m, p) is None]
    assert not undecided, ("a route that is not in fbi/api/wellbeing_routes.py: say whether it shows a price (BLOCKED), carries one "
                           f"among its fields (MIXED) or none (OPEN): {undecided}")


def test_no_call_is_in_two_lists(calls: list[tuple[str, str]]) -> None:
    both = [f"{m} {p}" for m, p in calls
            if sum((table.blocked(m, p), table.mixed(m, p))) > 1]
    assert not both, both


def test_the_tables_name_no_route_that_no_longer_exists(calls: list[tuple[str, str]]) -> None:
    real = {f"{m} {p}" for m, p in calls}
    assert not (table.BLOCKED - real), table.BLOCKED - real
    assert not (table.MIXED - real), table.MIXED - real


def test_what_is_a_price_is_blocked() -> None:
    for entry in ("GET /picks", "GET /odds", "GET /odds/fixtures/12/movement", "GET /matches/7/markets", "GET /me/picks",
                  "POST /me/parlays/validate", "GET /parlays/daily", "GET /daily", "GET /transparency/export"):
        method, path = entry.split(" ", 1)
        assert table.blocked(method, path), entry


def test_the_football_stays_open() -> None:
    for entry in ("GET /matches/7/news", "GET /competitions/3/standings", "GET /teams/9", "GET /me/favorites", "GET /me/wellbeing",
                  "PUT /me/wellbeing", "GET /auth/me"):
        method, path = entry.split(" ", 1)
        assert not table.blocked(method, path) and (table.open_(method, path)), entry

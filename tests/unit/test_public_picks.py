"""The client-facing API must never expose shadow picks or shadow-mode candidates."""

from __future__ import annotations

from typing import Any, cast

import pytest

import fbi.api.repositories.analytics as repo
from fbi.api.deps import public_mode


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(conn: Any, sql: str, params: Any = None) -> list[Any]:
        seen.append(sql)
        return []

    monkeypatch.setattr(repo, "fetch_all", fake)
    return seen


def test_public_picks_query_is_limited_to_qualified(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    repo.picks(cast(Any, None), limit=5, offset=0, qualified_only=True)
    sql = seen[0]
    assert "'qualified', 'published'" in sql
    assert sql.index("qualified") < sql.index("ORDER BY")


def test_internal_picks_query_is_unfiltered(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    repo.picks(cast(Any, None), limit=5, offset=0)
    assert "'qualified', 'published'" not in seen[0]


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("true", True), ("", False), ("0", False)])
def test_public_mode_flag(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("FBI_API_PUBLIC", value)
    assert public_mode() is expected

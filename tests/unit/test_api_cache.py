"""fbi.api.cache: one computation per key while fresh, separate keys per argument, off by default."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from fbi.api import cache


@pytest.fixture(autouse=True)
def _clean() -> Any:
    cache.clear()
    yield
    cache.clear()


def counted(seconds: float) -> tuple[Any, list[int]]:
    calls: list[int] = []

    @cache.shared(seconds)
    def board(conn: object, *, include_shadow: bool, hours: int = 72) -> tuple[bool, int, int]:
        calls.append(1)
        time.sleep(0.05)
        return include_shadow, hours, len(calls)

    return board, calls


def test_off_unless_turned_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_API_CACHE", raising=False)
    board, calls = counted(30)
    board(object(), include_shadow=False)
    board(object(), include_shadow=False)
    assert len(calls) == 2


def test_one_computation_per_key_and_never_across_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_CACHE", "1")
    board, calls = counted(30)
    first = board(object(), include_shadow=False)
    assert board(object(), include_shadow=False) == first  # another connection, same answer
    assert len(calls) == 1
    shadow = board(object(), include_shadow=True)  # a SUPER_ADMIN's preview is its own entry
    assert shadow[0] is True and len(calls) == 2
    board(object(), include_shadow=False, hours=24)
    assert len(calls) == 3


def test_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_CACHE", "1")
    board, calls = counted(0.1)
    board(object(), include_shadow=False)
    time.sleep(0.15)
    board(object(), include_shadow=False)
    assert len(calls) == 2


def test_concurrent_readers_wait_for_one_computation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_CACHE", "1")
    board, calls = counted(30)
    threads = [threading.Thread(target=board, args=(object(),), kwargs={"include_shadow": False}) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1

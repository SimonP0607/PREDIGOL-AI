"""fbi.api.warm: the keeper of the heavy admin reads (AP-A06) - off unless the API's cache is on, one answer at a time,
renewed before it expires, a failure retried later and never raised."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from fbi.api import cache, warm


class FakeConn:
    def __init__(self) -> None:
        self.closed = False
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clean() -> Any:
    cache.clear()
    yield
    cache.clear()


def test_off_unless_the_api_cache_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_API_CACHE", raising=False)
    assert warm.enabled() is False and warm.start() is None
    monkeypatch.setenv("FBI_API_CACHE", "1")
    assert warm.enabled() is True
    for word in ("0", "off", "false", "no"):
        monkeypatch.setenv("FBI_API_WARM", word)
        assert warm.enabled() is False


def test_the_jobs_are_the_three_heavy_reads_and_renew_before_they_expire() -> None:
    assert {j.name for j in warm.JOBS} == {"analytics.competitions", "analytics.coverage", "performance"}
    for job in warm.JOBS:
        assert 0 < job.every_s < 6 * 3600


def test_run_one_computes_on_its_own_connection_and_leaves_the_answer_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_API_CACHE", "1")
    conns: list[FakeConn] = []
    calls: list[int] = []

    @cache.shared(60)
    def heavy(conn: object) -> int:
        calls.append(1)
        return len(calls)

    def connect() -> FakeConn:
        conns.append(FakeConn())
        return conns[-1]

    monkeypatch.setattr(warm, "read_only_connection", connect)
    warm.run_one(warm.Job("heavy", heavy, every_s=30))
    assert len(calls) == 1 and conns[0].closed and conns[0].rolled_back
    assert heavy(object()) == 1 and len(calls) == 1  # the reader finds it ready


def test_the_loop_renews_each_job_when_due_and_retries_a_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(warm, "START_DELAY_S", 0.0)
    monkeypatch.setattr(warm, "POLL_S", 0.01)
    monkeypatch.setattr(warm, "RETRY_S", 0.03)
    ran: dict[str, int] = {"good": 0, "bad": 0}
    both = threading.Event()

    def run_one(job: warm.Job) -> None:
        ran[job.name] += 1
        if job.name == "bad":
            raise RuntimeError("the database said no")
        if ran["good"] >= 2 and ran["bad"] >= 2:
            both.set()

    monkeypatch.setattr(warm, "run_one", run_one)
    stop = threading.Event()
    thread = threading.Thread(
        target=warm._loop,
        args=(stop, (warm.Job("good", lambda c: None, every_s=0.02), warm.Job("bad", lambda c: None, every_s=0.02))),
    )
    thread.start()
    assert both.wait(5), ran  # the good job renewed itself, the bad one was tried again, the loop never died
    stop.set()
    thread.join(5)
    assert not thread.is_alive()


def test_the_loop_stops_at_once_when_asked_before_its_first_read(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(warm, "run_one", lambda job: called.append(1))
    stop = threading.Event()
    stop.set()
    warm._loop(stop, warm.JOBS)
    assert called == []

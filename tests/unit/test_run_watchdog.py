"""The run watchdog's rules, the job deadline and the run statuses (no database)."""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fbi.core.deadline import cancel_reason, run_with_deadline
from fbi.ingestion.ledger import RunCounters, _record_in_flight
from fbi.ops.run_watchdog import judge, owner_alive, process_start, timeout_for

AT = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
HOST = socket.gethostname()


def fake_proc(tmp_path: Path, pid: int, start: int, comm: str = "python3 -m (worker)") -> Path:
    (tmp_path / str(pid)).mkdir(parents=True, exist_ok=True)
    fields = ["S", "1", "2", "3"] + ["0"] * 15 + [str(start)] + ["0"] * 10
    (tmp_path / str(pid) / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
    return tmp_path


def test_the_process_start_time_is_read_after_the_command_name(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path, 4242, 987654, comm="weird ) name")
    assert process_start(4242, proc) == 987654
    assert process_start(4243, proc) is None


def test_a_pid_reused_by_another_process_is_not_the_owner(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path, 4242, 1000)
    assert owner_alive(4242, 1000, proc)
    assert not owner_alive(4242, 999, proc), "same pid, another process"
    assert not owner_alive(4300, 1000, proc), "no such process"


def test_every_job_has_a_deadline() -> None:
    assert timeout_for("live_odds_capture") == timedelta(minutes=10)
    assert timeout_for("truth_v2_standings") == timedelta(hours=4)
    assert timeout_for("raw_backfill_fixture_facts") == timedelta(hours=12)
    assert timeout_for("something_new") == timedelta(hours=6)


def row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": 1, "job_type": "odds_capture", "started_at": AT - timedelta(minutes=5),
                            "owner_host": None, "owner_pid": None, "owner_started": None, "heartbeat_at": None,
                            "deadline_at": None}
    return {**base, **kw}


def verdict(r: dict[str, Any], proc: Path, worker_started: datetime | None = None,
            booted: datetime | None = None) -> tuple[str, str] | None:
    return judge(r, at=AT, host=HOST, worker_started_at=worker_started, worker_job_types={"odds_capture"},
                 booted_at=booted, proc=proc)


def test_a_dead_owner_is_interrupted_at_once_and_a_live_one_is_left(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path, 4242, 1000)
    dead = verdict(row(owner_host=HOST, owner_pid=5555, owner_started=1, deadline_at=AT + timedelta(hours=1)), proc)
    assert dead is not None and dead[0] == "interrupted" and "pid 5555" in dead[1]
    alive = row(owner_host=HOST, owner_pid=4242, owner_started=1000, deadline_at=AT + timedelta(hours=1))
    assert verdict(alive, proc, worker_started=AT) is None, "its process lives: not the worker rule's business"


def test_a_run_past_its_deadline_is_stale_even_when_its_process_lives(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path, 4242, 1000)
    hung = row(owner_host=HOST, owner_pid=4242, owner_started=1000, deadline_at=AT - timedelta(minutes=1),
               heartbeat_at=AT - timedelta(minutes=50))
    v = verdict(hung, proc)
    assert v is not None and v[0] == "stale" and "50 min ago" in v[1] and "run watchdog" in v[1]


def test_legacy_runs_are_judged_by_the_worker_lock_and_by_age(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path, 4242, 1000)
    worker = verdict(row(started_at=AT - timedelta(hours=11)), proc, worker_started=AT - timedelta(minutes=10))
    assert worker is not None and worker[0] == "interrupted" and "previous worker" in worker[1]
    cli = row(job_type="raw_backfill_fixture_facts", started_at=AT - timedelta(hours=11))
    assert verdict(cli, proc, worker_started=AT - timedelta(minutes=10)) is None, "11 h: a CLI job may still run"
    old = verdict({**cli, "started_at": AT - timedelta(hours=13)}, proc)
    assert old is not None and old[0] == "stale"
    booted = verdict(row(started_at=AT - timedelta(days=1)), proc, booted=AT - timedelta(hours=2))
    assert booted is not None and booted[0] == "interrupted" and "booted" in booted[1]


def test_statuses_tell_a_cap_from_an_interruption() -> None:
    assert RunCounters(api_calls=3, stopped_early="allowance 300").status == "aborted"
    assert RunCounters(api_calls=3, stopped_early="interrupted (KeyboardInterrupt)").status == "interrupted"
    assert RunCounters(api_calls=3, stopped_early="interrupted: timed out after 600 s (job deadline)").status \
        == "interrupted"
    assert RunCounters(errors=["x"]).status == "failed" and RunCounters(errors=["x"], rows_inserted=1).status \
        == "partial"


def test_a_deadline_cancels_the_job_and_its_run_says_why() -> None:
    seen: dict[str, Any] = {}

    async def hangs() -> str:
        counters = RunCounters()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError as exc:
            seen["reason"] = cancel_reason()
            _record_in_flight(counters, exc)
            seen["status"] = counters.status
            seen["stopped"] = counters.stopped_early
            raise
        return "done"

    async def quick() -> str:
        return "done"

    assert asyncio.run(run_with_deadline("quick", quick, 1)) == "done"
    assert asyncio.run(run_with_deadline("hangs", hangs, 0.05)) is None
    assert seen["reason"] == "timed out after 0.05 s (job deadline)"
    assert seen["status"] == "interrupted" and "job deadline" in seen["stopped"]


def test_this_process_is_its_own_live_owner() -> None:
    assert owner_alive(os.getpid(), process_start(os.getpid()))

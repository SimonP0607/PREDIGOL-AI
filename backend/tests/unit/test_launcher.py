"""RP-1.6: the experiment launcher keeps a child under its ceilings of memory and time, reports how it ended, and launches only what is listed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from fbi.research import launcher


def test_only_listed_jobs_exist_and_their_ceilings_are_set() -> None:
    assert set(launcher.JOBS) == {"research_v2", "experiments_due"}
    j = launcher.JOBS["research_v2"]
    assert j.argv[:2] == ("-m", "scripts.research_v2") and "--apply" in j.argv and j.memory_mb <= 2048 and j.timeout_s > 0


def test_a_child_that_ends_well_is_completed_with_its_peak_memory() -> None:
    out = launcher.supervise([sys.executable, "-c", "print('hecho')"], memory_mb=2048, timeout_s=30, poll_s=0.05)
    assert (out.status, out.exit_code) == ("completed", 0) and "hecho" in out.extra["tail"] and out.seconds < 30


def test_a_child_that_fails_is_failed_with_its_exit_code_and_last_lines() -> None:
    out = launcher.supervise([sys.executable, "-c", "import sys; print('boom'); sys.exit(7)"], memory_mb=2048, timeout_s=30, poll_s=0.05)
    assert out.status == "failed" and out.exit_code == 7 and out.reason == "exit 7" and "boom" in out.extra["tail"]


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="reads /proc (Linux)")
def test_a_child_over_the_memory_ceiling_is_killed_and_says_so() -> None:
    code = "import time; x = bytearray(300 * 1024 * 1024); [x.__setitem__(i, 1) for i in range(0, len(x), 4096)]; time.sleep(60)"
    out = launcher.supervise([sys.executable, "-c", code], memory_mb=120, timeout_s=60, poll_s=0.05)
    assert out.status == "failed" and out.reason.startswith("memory_cap") and out.seconds < 30 and out.peak_mb > 120


def test_a_child_over_the_time_ceiling_is_killed_and_says_so() -> None:
    out = launcher.supervise([sys.executable, "-c", "import time; time.sleep(60)"], memory_mb=2048, timeout_s=1, poll_s=0.05)
    assert out.status == "failed" and out.reason.startswith("timeout") and out.seconds < 30


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="reads /proc (Linux)")
def test_the_whole_group_is_counted_and_killed_not_only_the_first_process() -> None:
    code = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)")
    out = launcher.supervise([sys.executable, "-c", code], memory_mb=2048, timeout_s=1, poll_s=0.05)
    assert out.status == "failed" and out.reason.startswith("timeout")
    assert launcher.rss_mb(os.getpgid(0) + 10_000_000) == 0


def test_rss_of_a_group_is_read_from_proc_and_a_missing_proc_is_zero(tmp_path: Path) -> None:
    for pid, pgrp, kb in ((101, 77, 2048), (102, 77, 1024), (103, 99, 4096)):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} (a (b) c) S 1 {pgrp} {pgrp} 0 -1 0\n", encoding="utf-8")
        (d / "status").write_text(f"Name:\tx\nVmRSS:\t{kb} kB\n", encoding="utf-8")
    assert launcher.rss_mb(77, proc=str(tmp_path)) == 3 and launcher.rss_mb(99, proc=str(tmp_path)) == 4
    assert launcher.rss_mb(77, proc=str(tmp_path / "nope")) == 0


def test_an_unknown_job_is_refused_without_touching_the_database() -> None:
    from datetime import UTC, datetime

    def no_db() -> object:
        raise AssertionError("must not connect")

    out = launcher.launch("rm_rf", connect=no_db, at=datetime.now(UTC))  # type: ignore[arg-type]
    assert out.refused and "rm_rf" in out.reason

"""RP-1.1 in the scheduler's source: every job that was outside the book is wrapped, none twice, and the watchdog knows its type."""

from __future__ import annotations

import re
from pathlib import Path

from apps.worker import scheduler

from fbi.ops import job_book

SOURCE = (Path(scheduler.__file__)).read_text(encoding="utf-8")


def test_every_job_outside_the_book_is_wrapped_exactly_once() -> None:
    wrapped = re.findall(r'^@_booked\("(\w+)"\)\ndef (_\w+)\(', SOURCE, re.M)
    types = [t for t, _ in wrapped]
    assert sorted(types) == sorted(job_book.BOOKED_JOB_TYPES), "the wrapped functions and BOOKED_JOB_TYPES must be the same set"
    assert len(types) == len(set(types)) == 34


def test_the_watchdog_knows_every_booked_type() -> None:
    assert set(job_book.BOOKED_JOB_TYPES) <= scheduler.WORKER_JOB_TYPES


def test_an_id_that_is_not_its_type_counts_as_its_type() -> None:
    expected = {
        "live_odds": "live_odds_capture", "live_match": "live_match_capture", "ai_cycle": "ai_cycle", "odds_capture": "odds_capture",
        "player_history_sweep": "player_history", "availability_refresh_retry_0840": "availability_refresh",
        "availability_shadow_retry_1150": "availability_shadow", "period_backfill_2230": "period_backfill",
    }
    for job_id, typ in expected.items():
        assert job_book.job_type_of(job_id) == typ, job_id


def test_the_error_hook_is_registered_with_the_logger() -> None:
    from fbi.core import logging as core_logging

    assert job_book.record_error in core_logging._error_sinks

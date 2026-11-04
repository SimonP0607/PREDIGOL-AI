"""The runtime guards of the Orchestrator (``fbi.ai.runtime``, Plan Maestro IA, sections 17, 18, 23 and 32): the slots, the circuit of each
model, the retries, the deadlines of a pass and the pause of an arm.

Every threshold is held on both sides (the 4th and the 5th failure, 20 % and just above, below / at / above the floor of calls, the
10-minute window by the microsecond, T-15 by the microsecond). The state of the circuit is held to a pure function of the ORDERED history of
what was recorded, against a reference worked out from scratch with plain lists. The threads are here to hold that the guards survive
contention - the half-open probe goes to exactly one of eight callers, the slots never pass their limit, no permit is lost - and none of
them waits on a sleep to decide a result: they wait for a condition, with a bound. No database, no network, no model."""

from __future__ import annotations

import ast
import json
import math
import random
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args
from zoneinfo import ZoneInfo

import pytest

from fbi.ai import router, usage
from fbi.ai import runtime as rt
from fbi.ai.contracts.mcp import PassKind
from fbi.ai.providers.base import ErrorCode
from fbi.ai.usage import CallOutcome

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
MODEL = "claude-haiku-5-5"
OTHER = "claude-sonnet-5-5"
SECOND = timedelta(seconds=1)
MINUTE = timedelta(minutes=1)
MICRO = timedelta(microseconds=1)
KICKOFF = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)
SOURCE = Path(rt.__file__).read_text(encoding="utf-8")

NOT_RETRYABLE = ["refused", "invalid_output", "over_budget", "not_configured", "limit_reached", "something_new", ""]
"""Every error code that is not a transport failure, the unknown ones among them."""


def feed(circuit: rt.Circuit, pattern: str, *, start: datetime = T0, step: timedelta = SECOND, model: str = MODEL) -> datetime:
    """One call per character of ``pattern`` ('.' served, 'x' failed), ``step`` apart from ``start``. Returns the moment of the last."""
    at = start
    for i, mark in enumerate(pattern):
        at = start + step * i
        circuit.record(model, mark == ".", at)
    return at


def opened_circuit() -> tuple[rt.Circuit, datetime]:
    """A circuit that five failures opened, and the moment it opened."""
    circuit = rt.Circuit()
    return circuit, feed(circuit, "xxxxx")


def wait_until(condition: Callable[[], bool], *, timeout: float = 5.0) -> None:
    """Wait for ``condition`` to become true: never longer than ``timeout``, and in steps of a millisecond."""
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "the condition never became true"
        time.sleep(0.001)


def run_all(workers: list[Callable[[], None]], *, timeout: float = 15.0) -> None:
    """Run each worker in its own thread; fail if one raises or is still running after ``timeout``."""
    failures: list[BaseException] = []

    def guarded(work: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                work()
            except BaseException as exc:
                failures.append(exc)
        return run

    threads = [threading.Thread(target=guarded(work), daemon=True) for work in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
    assert not any(thread.is_alive() for thread in threads), "a thread is stuck"
    assert not failures, failures


@pytest.fixture
def fast_switching() -> Iterator[None]:
    """Make the interpreter switch threads a million times more often, so that a missing lock shows itself."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(old)


# ---- what an error code means -----------------------------------------------------------------------------------------------------------

def documented_outcome_codes() -> set[str]:
    """The codes ``CallOutcome.error`` says it can hold, read from the docstring under the field in ``fbi/ai/usage.py``."""
    tree = ast.parse(Path(usage.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CallOutcome":
            for i, statement in enumerate(node.body):
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.target.id == "error":
                    doc = node.body[i + 1]
                    assert isinstance(doc, ast.Expr)
                    assert isinstance(doc.value, ast.Constant)
                    return set(re.findall(r"[a-z]+(?:_[a-z]+)*", str(doc.value.value).split(":", 1)[1]))
    raise AssertionError("CallOutcome.error is not documented where this test looks for it")


def test_every_code_the_layer_can_produce_is_classified() -> None:
    """A new code added to the providers or to ``CallOutcome`` must be put in the table (failure, answered or neutral) on purpose."""
    classified = rt.FAILURE_CODES | rt.ANSWERED_CODES | rt.NEUTRAL_CODES
    known = set(get_args(ErrorCode)) | {"over_budget"} | documented_outcome_codes()
    assert known == classified
    assert documented_outcome_codes() >= {"timeout", "over_budget", "not_configured"}  # the reading of the docstring is not vacuous


def test_the_three_classes_do_not_overlap_and_the_retryable_ones_are_failures() -> None:
    assert not rt.FAILURE_CODES & rt.ANSWERED_CODES
    assert not rt.FAILURE_CODES & rt.NEUTRAL_CODES
    assert not rt.ANSWERED_CODES & rt.NEUTRAL_CODES
    assert rt.RETRYABLE_CODES < rt.FAILURE_CODES


def test_the_table_is_in_the_docstring() -> None:
    doc = rt.__doc__ or ""
    for code in rt.FAILURE_CODES | rt.ANSWERED_CODES | rt.NEUTRAL_CODES:
        assert code in doc, code


@pytest.mark.parametrize(("error", "failure"), [
    (None, False),
    ("timeout", True), ("unavailable", True), ("rate_limited", True), ("limit_reached", True),
    ("invalid_output", False), ("refused", False),
    ("over_budget", False), ("not_configured", False),
    ("something_new", True), ("", True),
])
def test_what_counts_as_a_failure_of_the_provider(error: str | None, failure: bool) -> None:
    assert rt.counts_as_failure(error) is failure


@pytest.mark.parametrize(("error", "again"), [
    ("timeout", True), ("unavailable", True), ("rate_limited", True),
    (None, False), ("refused", False), ("invalid_output", False), ("over_budget", False), ("not_configured", False),
    ("limit_reached", False), ("something_new", False), ("", False),
])
def test_only_transport_failures_are_retried(error: str | None, again: bool) -> None:
    assert rt.retryable(error) is again


# ---- 1. slots ---------------------------------------------------------------------------------------------------------------------------

def test_the_figures_of_the_plan() -> None:
    assert rt.CONCURRENCY == {"simple": 4, "complex": 3, "critical": 1}
    assert set(rt.CONCURRENCY) == set(router.TIER_OF_LEVEL)  # the levels the orchestrator calls: «owner» (Fable) is never automatic
    assert set(rt.CONCURRENCY) < set(router.MODELS)
    slots = rt.Slots()
    assert {level: slots.limit(level) for level in rt.CONCURRENCY} == rt.CONCURRENCY


@pytest.mark.parametrize("level", ["owner", "", "SIMPLE", "bogus", "claude-haiku-5-5"])
def test_a_level_nobody_configured_is_refused_at_once(level: str) -> None:
    slots = rt.Slots()
    with pytest.raises(ValueError, match="no slots for level"):
        slots.acquire(level, timeout_s=0)  # raised by the call itself, not by the «with»
    for read in (slots.in_use, slots.waiting, slots.limit):
        with pytest.raises(ValueError, match="no slots for level"):
            read(level)


@pytest.mark.parametrize("limits", [{}, {"simple": 0}, {"simple": -1}, {"simple": True}, {"simple": 1.5}, {"": 1}])
def test_limits_that_make_no_sense_are_refused(limits: Any) -> None:
    with pytest.raises(ValueError, match=r"Slots needs|must be a whole number"):
        rt.Slots(limits)


def test_a_timeout_returns_false_and_takes_nothing() -> None:
    slots = rt.Slots({"critical": 1})
    with slots.acquire("critical", timeout_s=0) as first:
        assert first is True
        assert slots.in_use("critical") == 1
        began = time.monotonic()
        with slots.acquire("critical", timeout_s=0.01) as second:
            assert second is False
        assert time.monotonic() - began < 2.0
        assert slots.in_use("critical") == 1
        assert slots.waiting("critical") == 0
    assert slots.in_use("critical") == 0


def one_try(slots: rt.Slots, level: str, timeout_s: float) -> bool | None:
    """What one ``acquire`` yields, run on a thread of its own: a try that never returns fails the test instead of hanging it. (A NaN
    timeout that reached ``Condition.wait_for`` would spin for ever: Python takes ``nan > 0`` for false and tries again without waiting.)"""
    answer: list[bool] = []

    def work() -> None:
        with slots.acquire(level, timeout_s=timeout_s) as got:
            answer.append(got)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(5)
    return answer[0] if answer else None


@pytest.mark.parametrize("timeout_s", [0, -1, -0.0, float("nan"), -math.inf])
def test_a_zero_negative_or_nan_timeout_is_one_try_without_waiting(timeout_s: float) -> None:
    slots = rt.Slots({"simple": 1})
    with slots.acquire("simple", timeout_s=0) as held:
        assert held is True
        assert one_try(slots, "simple", timeout_s) is False  # no slot is free, and it did not wait for one
    assert one_try(slots, "simple", timeout_s) is True  # a free slot is taken by the single try
    assert slots.in_use("simple") == 0


def test_an_infinite_timeout_does_not_overflow_the_wait() -> None:
    slots = rt.Slots({"simple": 1})
    with slots.acquire("simple", timeout_s=math.inf) as got:
        assert got is True


def test_a_slot_is_released_when_the_body_raises() -> None:
    slots = rt.Slots({"complex": 2})
    for _ in range(5):
        with pytest.raises(RuntimeError, match="boom"), slots.acquire("complex", timeout_s=0) as got:
            assert got is True
            raise RuntimeError("boom")
    assert slots.in_use("complex") == 0
    with slots.acquire("complex", timeout_s=0) as one, slots.acquire("complex", timeout_s=0) as two:
        assert (one, two) == (True, True)
        assert slots.in_use("complex") == 2


def test_no_permit_leaks_after_a_thousand_cycles() -> None:
    slots = rt.Slots({"simple": 4})
    for i in range(1000):
        with suppress(ValueError), slots.acquire("simple", timeout_s=0) as got:
            assert got is True
            if i % 3 == 0:
                raise ValueError(i)  # a third of the bodies raise
        with slots.acquire("simple", timeout_s=0) as again:  # a fresh try always finds a free slot
            assert again is True
    assert slots.in_use("simple") == 0
    assert slots.waiting("simple") == 0
    with ExitStack() as stack:
        taken = [stack.enter_context(slots.acquire("simple", timeout_s=0)) for _ in range(4)]
        assert taken == [True] * 4  # all four permits are still there
        with slots.acquire("simple", timeout_s=0) as fifth:
            assert fifth is False
    assert slots.in_use("simple") == 0


def test_a_try_that_times_out_leaks_nothing_either() -> None:
    slots = rt.Slots({"simple": 1})
    with slots.acquire("simple", timeout_s=0):
        for _ in range(200):
            with slots.acquire("simple", timeout_s=0.0001) as got:
                assert got is False
        assert slots.waiting("simple") == 0
    assert slots.in_use("simple") == 0


def test_the_limit_holds_under_contention(fast_switching: None) -> None:
    slots = rt.Slots({"complex": 3})
    lock = threading.Lock()
    inside = {"now": 0, "peak": 0, "done": 0}

    def worker() -> None:
        for _ in range(100):
            with slots.acquire("complex", timeout_s=10) as got:
                assert got is True
                with lock:
                    inside["now"] += 1
                    inside["peak"] = max(inside["peak"], inside["now"])
                    assert inside["now"] <= 3, "more holders than slots"
                time.sleep(0)  # give the others a chance to run while the slot is held
                with lock:
                    inside["now"] -= 1
                    inside["done"] += 1

    run_all([worker] * 8)
    assert inside["done"] == 800
    assert 1 <= inside["peak"] <= 3
    assert slots.in_use("complex") == 0
    assert slots.waiting("complex") == 0


def test_the_levels_do_not_share_slots() -> None:
    slots = rt.Slots()
    with ExitStack() as stack:
        assert [stack.enter_context(slots.acquire("critical", timeout_s=0)) for _ in range(2)] == [True, False]
        assert [stack.enter_context(slots.acquire("complex", timeout_s=0)) for _ in range(4)] == [True, True, True, False]
        assert [stack.enter_context(slots.acquire("simple", timeout_s=0)) for _ in range(5)] == [True] * 4 + [False]
        assert (slots.in_use("simple"), slots.in_use("complex"), slots.in_use("critical")) == (4, 3, 1)


def test_waiting_counts_the_blocked_callers_and_each_one_gets_its_turn() -> None:
    slots = rt.Slots({"critical": 1})
    got: list[bool] = []
    holder = ExitStack()
    assert holder.enter_context(slots.acquire("critical", timeout_s=0)) is True

    def waiter() -> None:
        with slots.acquire("critical", timeout_s=10) as ok:
            got.append(ok)

    threads = [threading.Thread(target=waiter, daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()
    wait_until(lambda: slots.waiting("critical") == 3)
    assert slots.in_use("critical") == 1
    holder.close()  # the slot of the main thread is freed
    for thread in threads:
        thread.join(10)
    assert got == [True, True, True]
    assert slots.waiting("critical") == 0
    assert slots.in_use("critical") == 0


def test_a_caller_that_gives_up_does_not_swallow_the_turn_of_the_one_behind_it() -> None:
    slots = rt.Slots({"critical": 1})
    outcome: dict[str, bool] = {}
    holder = ExitStack()
    assert holder.enter_context(slots.acquire("critical", timeout_s=0)) is True

    def impatient() -> None:
        with slots.acquire("critical", timeout_s=0.02) as ok:
            outcome["impatient"] = ok

    def patient() -> None:
        with slots.acquire("critical", timeout_s=10) as ok:
            outcome["patient"] = ok

    first, second = threading.Thread(target=impatient, daemon=True), threading.Thread(target=patient, daemon=True)
    first.start()
    wait_until(lambda: slots.waiting("critical") >= 1)
    second.start()
    first.join(10)
    wait_until(lambda: slots.waiting("critical") == 1 and "impatient" in outcome)
    holder.close()
    second.join(10)
    assert outcome == {"impatient": False, "patient": True}
    assert slots.in_use("critical") == 0


# ---- 2. the circuit: the thresholds, on both sides --------------------------------------------------------------------------------------

def test_four_failures_in_a_row_do_not_open_the_circuit_and_the_fifth_does() -> None:
    circuit = rt.Circuit()
    last = feed(circuit, "xxxx")
    assert circuit.state(MODEL, last) == "closed"
    assert circuit.allow(MODEL, last) is True
    assert circuit.record(MODEL, False, last + SECOND) == "open"
    assert circuit.state(MODEL, last + SECOND) == "open"
    assert circuit.allow(MODEL, last + SECOND) is False


def test_a_success_ends_the_streak() -> None:
    circuit = rt.Circuit()
    last = feed(circuit, "xxxx.xxxx")  # nine calls: below the floor of the rate, and no streak reaches five
    assert circuit.state(MODEL, last) == "closed"
    assert circuit.snapshot(last)[MODEL]["consecutive_failures"] == 4
    feed(circuit, "xxxxx", start=last + SECOND)  # five in a row again
    assert circuit.state(MODEL, last + 6 * SECOND) == "open"


@pytest.mark.parametrize(("pattern", "state"), [
    ("....x....x", "closed"),  # 10 calls, 2 failures: exactly 20 %, which is not MORE than 20 %
    ("...x...x.x", "open"),  # 10 calls, 3 failures: 30 %, at the floor of calls
    (".x.x.x.x.", "closed"),  # 9 calls, 4 failures (44 %): below the floor of calls, the rate says nothing
    (".x", "closed"),  # 1 failure in 2 calls
    ("x.", "closed"),
    (".x.", "closed"),  # 1 in 3
    ("....x....xx", "open"),  # 11 calls, the third failure is the last: 27 %, above the floor
    ("....x....x.", "closed"),  # 11 calls, 2 failures: 18 %
])
def test_the_rate_rule_below_at_and_above_the_floor_of_calls(pattern: str, state: str) -> None:
    circuit = rt.Circuit()
    last = feed(circuit, pattern)
    assert circuit.state(MODEL, last) == state


def test_the_rate_never_opens_the_circuit_on_fewer_than_three_failures() -> None:
    for calls in range(rt.MIN_CALLS, 200):
        circuit = rt.Circuit()
        pattern = "." * (calls - 1) + "x"  # one failure
        two = "." * (calls - 6) + "x....x"  # two, far from each other: no streak
        assert circuit.state(MODEL, feed(circuit, pattern)) == "closed"
        other = rt.Circuit()
        assert other.state(MODEL, feed(other, two)) == "closed"


@pytest.mark.parametrize("fives", [2, 5, 10, 20, 40])
def test_twenty_percent_is_closed_and_anything_above_it_is_open(fives: int) -> None:
    """``fives`` failures in ``5 * fives`` calls, one every fifth: 20 % at every prefix. One more failure takes it above 20 %."""
    base = "....x" * fives
    exactly = rt.Circuit()
    assert exactly.state(MODEL, feed(exactly, base)) == "closed"
    above = rt.Circuit()
    assert above.state(MODEL, feed(above, base + "x")) == "open"  # (fives + 1) of (5 * fives + 1) calls
    served = rt.Circuit()
    assert served.state(MODEL, feed(served, base + ".")) == "closed"


def test_the_window_slides_ten_minutes_to_the_microsecond() -> None:
    old = "xxxx"  # four failures at one instant: a streak of four, no more
    for age, state in ((10 * MINUTE, "closed"), (10 * MINUTE - MICRO, "open")):
        circuit = rt.Circuit()
        feed(circuit, old, step=timedelta(0))
        feed(circuit, "." * 10, start=T0 + 9 * MINUTE)  # ten served calls reset the streak
        circuit.record(MODEL, False, T0 + age)  # a failure `age` after the old ones
        # at exactly ten minutes the old failures have LEFT the window (11 calls, 1 failure); a microsecond sooner they are in it
        # (15 calls, 5 failures: 33 %)
        assert circuit.state(MODEL, T0 + age) == state, age


def test_failures_that_aged_out_cannot_open_the_circuit_later() -> None:
    circuit = rt.Circuit()
    feed(circuit, "x.x.x.x.x.")  # 10 calls, 5 failures, none in a row; the fifth failure was call 9, and 5 of 9 is below the floor
    assert circuit.state(MODEL, T0 + 9 * SECOND) == "closed"
    # eleven minutes later the old calls have left the window: one failure now finds 1 failure in 2 calls, not 6 in 12
    circuit.record(MODEL, True, T0 + 11 * MINUTE)
    circuit.record(MODEL, False, T0 + 11 * MINUTE + SECOND)
    snapshot = circuit.snapshot(T0 + 11 * MINUTE + SECOND)[MODEL]
    assert (snapshot["calls_10m"], snapshot["errors_10m"]) == (2, 1)
    assert snapshot["state"] == "closed"


def test_a_success_never_opens_the_circuit() -> None:
    circuit = rt.Circuit()
    last = feed(circuit, "x.x.x.x.x")  # 9 calls, 5 failures: the rate is silent below ten calls
    assert circuit.record(MODEL, True, last + SECOND) == "closed"  # the tenth call is served: 50 % failures, and still closed
    assert circuit.state(MODEL, last + SECOND) == "closed"
    assert circuit.record(MODEL, False, last + 2 * SECOND) == "open"  # the next failure finds 6 of 11


def test_the_circuit_is_open_for_five_minutes_exactly() -> None:
    circuit, opened = opened_circuit()
    assert rt.OPEN_FOR == 5 * MINUTE
    assert circuit.state(MODEL, opened) == "open"
    assert circuit.state(MODEL, opened + 5 * MINUTE - MICRO) == "open"
    assert circuit.allow(MODEL, opened + 5 * MINUTE - MICRO) is False
    assert circuit.state(MODEL, opened + 5 * MINUTE) == "half_open"
    assert circuit.state(MODEL, opened + 20 * MINUTE) == "half_open"  # it stays half-open until a probe says otherwise


def test_a_late_answer_while_the_circuit_is_open_changes_nothing() -> None:
    circuit, opened = opened_circuit()
    before = circuit.snapshot(opened + MINUTE)
    assert circuit.record(MODEL, True, opened + MINUTE) == "open"  # a call made before it opened comes back served
    assert circuit.record(MODEL, False, opened + 2 * MINUTE) == "open"
    assert circuit.snapshot(opened + MINUTE) == before
    assert circuit.state(MODEL, opened + 5 * MINUTE) == "half_open"  # and the clock of the five minutes did not restart


# ---- 2. the circuit: half-open and the probe --------------------------------------------------------------------------------------------

def test_half_open_lets_one_probe_through_and_a_success_closes_the_circuit() -> None:
    circuit, opened = opened_circuit()
    half = opened + rt.OPEN_FOR
    assert circuit.allow(MODEL, half) is True  # the probe
    assert circuit.allow(MODEL, half) is False
    assert circuit.allow(MODEL, half + SECOND) is False
    assert circuit.state(MODEL, half + SECOND) == "half_open"
    assert circuit.record(MODEL, True, half + 2 * SECOND) == "closed"
    snapshot = circuit.snapshot(half + 2 * SECOND)[MODEL]
    assert snapshot == {"state": "closed", "consecutive_failures": 0, "calls_10m": 0, "errors_10m": 0, "opened_at": None}
    assert all(circuit.allow(MODEL, half + 3 * SECOND) for _ in range(5))  # everybody again
    assert circuit.record(MODEL, False, half + 3 * SECOND) == "closed"  # and the streak starts again from zero
    assert circuit.snapshot(half + 3 * SECOND)[MODEL]["consecutive_failures"] == 1


def test_a_failed_probe_reopens_the_circuit_for_five_more_minutes() -> None:
    circuit, opened = opened_circuit()
    half = opened + rt.OPEN_FOR
    assert circuit.allow(MODEL, half) is True
    failed_at = half + 3 * SECOND
    assert circuit.record(MODEL, False, failed_at) == "open"
    assert circuit.state(MODEL, failed_at + 5 * MINUTE - MICRO) == "open"
    assert circuit.state(MODEL, failed_at + 5 * MINUTE) == "half_open"
    assert circuit.snapshot(failed_at)[MODEL]["opened_at"] == failed_at.isoformat()
    assert circuit.allow(MODEL, failed_at + 5 * MINUTE) is True  # a new probe, a new half-open
    assert circuit.allow(MODEL, failed_at + 5 * MINUTE) is False


def test_a_lost_probe_is_taken_over_after_the_lease() -> None:
    circuit, opened = opened_circuit()
    half = opened + rt.OPEN_FOR
    assert circuit.allow(MODEL, half) is True  # the probe is handed out and its result never recorded
    assert circuit.allow(MODEL, half + rt.PROBE_LEASE - MICRO) is False
    assert circuit.allow(MODEL, half + rt.PROBE_LEASE) is True  # the next caller becomes the probe
    assert circuit.allow(MODEL, half + rt.PROBE_LEASE) is False


def test_a_probe_that_never_reached_the_provider_is_handed_back() -> None:
    circuit, opened = opened_circuit()
    half = opened + rt.OPEN_FOR
    assert circuit.allow(MODEL, half) is True
    assert circuit.record_outcome(MODEL, "over_budget", half) == "half_open"  # no call was made: the probe is free again
    assert circuit.allow(MODEL, half) is True
    assert circuit.record_outcome(MODEL, "timeout", half + SECOND) == "open"  # and a failed probe re-opens it


@pytest.mark.usefixtures("fast_switching")
def test_a_half_open_circuit_lets_exactly_one_probe_through_to_eight_callers() -> None:
    for _ in range(40):  # a race that exists shows in one of the rounds
        circuit, opened = opened_circuit()
        half = opened + rt.OPEN_FOR
        barrier = threading.Barrier(8)
        answers: list[bool] = []

        def caller(circuit: rt.Circuit = circuit, half: datetime = half, barrier: threading.Barrier = barrier,
                   answers: list[bool] = answers) -> None:
            barrier.wait(timeout=10)
            answers.append(circuit.allow(MODEL, half))

        run_all([caller] * 8)
        assert sorted(answers) == [False] * 7 + [True]
        circuit.record(MODEL, True, half + SECOND)  # the probe's result is recorded: everybody is let through
        assert circuit.allow(MODEL, half + 2 * SECOND) is True


@pytest.mark.usefixtures("fast_switching")
def test_records_from_many_threads_are_all_counted() -> None:
    circuit = rt.Circuit()

    def served() -> None:
        for _ in range(100):
            circuit.record(MODEL, True, T0)

    run_all([served] * 8)
    snapshot = circuit.snapshot(T0)[MODEL]
    assert (snapshot["calls_10m"], snapshot["errors_10m"], snapshot["consecutive_failures"]) == (800, 0, 0)

    def failed() -> None:
        for _ in range(10):
            circuit.record(MODEL, False, T0 + SECOND)

    run_all([failed] * 8)
    after = circuit.snapshot(T0 + SECOND)[MODEL]
    assert after["state"] == "open"
    assert after["consecutive_failures"] == 5  # the rest were late answers of an open circuit
    assert after["opened_at"] == (T0 + SECOND).isoformat()


# ---- 2. the circuit: by error code, models, views ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("error", sorted(rt.FAILURE_CODES))
def test_five_provider_failures_of_any_kind_open_the_circuit(error: str) -> None:
    circuit = rt.Circuit()
    for i in range(5):
        circuit.record_outcome(MODEL, error, T0 + i * SECOND)
    assert circuit.state(MODEL, T0 + 5 * SECOND) == "open"


@pytest.mark.parametrize("error", [*sorted(rt.ANSWERED_CODES), None])
def test_an_answer_that_cannot_be_used_never_opens_the_circuit_and_ends_a_streak(error: str | None) -> None:
    circuit = rt.Circuit()
    for i in range(60):
        circuit.record_outcome(MODEL, error, T0 + i * SECOND)
    assert circuit.state(MODEL, T0 + 60 * SECOND) == "closed"
    assert circuit.snapshot(T0 + 60 * SECOND)[MODEL]["calls_10m"] == 60  # they are calls, and served ones
    streak = rt.Circuit()
    for i in range(4):
        streak.record_outcome(MODEL, "timeout", T0 + i * SECOND)
    streak.record_outcome(MODEL, error, T0 + 4 * SECOND)
    for i in range(4):
        streak.record_outcome(MODEL, "timeout", T0 + (5 + i) * SECOND)
    assert streak.state(MODEL, T0 + 9 * SECOND) == "closed"


@pytest.mark.parametrize("error", sorted(rt.NEUTRAL_CODES))
def test_a_call_that_was_never_made_is_not_recorded(error: str) -> None:
    circuit = rt.Circuit()
    for i in range(4):
        circuit.record_outcome(MODEL, "timeout", T0 + i * SECOND)
    for i in range(50):
        assert circuit.record_outcome(MODEL, error, T0 + (4 + i) * SECOND) == "closed"
    snapshot = circuit.snapshot(T0 + 60 * SECOND)[MODEL]
    assert (snapshot["calls_10m"], snapshot["errors_10m"], snapshot["consecutive_failures"]) == (4, 4, 4)  # the streak was not ended
    circuit.record_outcome(MODEL, "timeout", T0 + 60 * SECOND)
    assert circuit.state(MODEL, T0 + 60 * SECOND) == "open"  # and the fifth failure still opens it


def test_a_neutral_code_for_a_model_never_seen_creates_nothing() -> None:
    circuit = rt.Circuit()
    assert circuit.record_outcome(MODEL, "over_budget", T0) == "closed"
    assert circuit.snapshot(T0) == {}


def test_an_unknown_code_is_a_failure() -> None:
    circuit = rt.Circuit()
    for i in range(5):
        circuit.record_outcome(MODEL, "something_new", T0 + i * SECOND)
    assert circuit.state(MODEL, T0 + 5 * SECOND) == "open"


def test_models_are_independent() -> None:
    circuit = rt.Circuit()
    feed(circuit, "xxxxx", model=MODEL)
    feed(circuit, "xxxx", model=OTHER)
    at = T0 + 5 * SECOND
    assert circuit.state(MODEL, at) == "open"
    assert circuit.state(OTHER, at) == "closed"
    assert circuit.allow(OTHER, at) is True
    assert circuit.allow(MODEL, at) is False


def test_reading_never_creates_the_entry_of_a_model() -> None:
    circuit = rt.Circuit()
    assert circuit.state("never-seen", T0) == "closed"
    assert circuit.allow("never-seen", T0) is True
    assert circuit.snapshot(T0) == {}  # asking is not remembered: a stream of names cannot fill the memory


def test_the_snapshot_is_plain_json_data() -> None:
    circuit = rt.Circuit()
    last = feed(circuit, "xxxxx", model=MODEL)
    feed(circuit, ".x.", model=OTHER)
    snapshot = circuit.snapshot(last)
    assert list(snapshot) == sorted([MODEL, OTHER])  # sorted by model, so that two reads of the same state are the same text
    assert list(snapshot) == [MODEL, OTHER]
    assert snapshot[MODEL] == {"state": "open", "consecutive_failures": 5, "calls_10m": 5, "errors_10m": 5, "opened_at": last.isoformat()}
    assert snapshot[OTHER] == {"state": "closed", "consecutive_failures": 0, "calls_10m": 3, "errors_10m": 1, "opened_at": None}
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert set(snapshot[MODEL]) == {"state", "consecutive_failures", "calls_10m", "errors_10m", "opened_at"}


def test_the_counts_of_the_snapshot_are_those_of_the_window_ending_at_the_moment_asked() -> None:
    circuit = rt.Circuit()
    feed(circuit, ".x.", step=MINUTE)  # at 0, 1 and 2 minutes
    assert circuit.snapshot(T0 + 2 * MINUTE)[MODEL]["calls_10m"] == 3
    assert circuit.snapshot(T0 + 10 * MINUTE)[MODEL]["calls_10m"] == 2  # the call at minute 0 has left
    assert circuit.snapshot(T0 + 10 * MINUTE + MINUTE)[MODEL]["calls_10m"] == 1
    assert circuit.snapshot(T0 + 12 * MINUTE)[MODEL]["calls_10m"] == 0


@pytest.mark.parametrize("use", [
    lambda c, at: c.record(MODEL, True, at),
    lambda c, at: c.record_outcome(MODEL, "over_budget", at),
    lambda c, at: c.record_outcome(MODEL, "timeout", at),
    lambda c, at: c.allow(MODEL, at),
    lambda c, at: c.state(MODEL, at),
    lambda c, at: c.snapshot(at),
])
def test_a_naive_datetime_is_refused(use: Callable[[rt.Circuit, datetime], object]) -> None:
    circuit = rt.Circuit()
    feed(circuit, "x")
    with pytest.raises(ValueError, match="timezone-aware"):
        use(circuit, datetime(2026, 11, 3, 15, 0))  # noqa: DTZ001 - the point of the test


def test_the_zone_of_the_datetime_does_not_matter() -> None:
    circuit = rt.Circuit()
    bogota = timezone(timedelta(hours=-5))
    for i in range(5):
        circuit.record(MODEL, False, (T0 + i * SECOND).astimezone(bogota))
    assert circuit.state(MODEL, (T0 + 5 * MINUTE + 4 * SECOND).astimezone(ZoneInfo("Asia/Tokyo"))) == "half_open"
    assert circuit.snapshot(T0)[MODEL]["opened_at"] == (T0 + 4 * SECOND).isoformat()  # always UTC


# ---- 2. the circuit: a pure function of the history -------------------------------------------------------------------------------------

class Reference:
    """The rules of the circuit written out the plainest way, to be held against the real one: every call since the last close in a list
    that is never pruned, three numbers, and the plan's figures written out here (not read from the module)."""

    def __init__(self) -> None:
        self.opened: datetime | None = None
        self.streak = 0
        self.window: list[tuple[datetime, bool]] = []

    def record(self, ok: bool, when: datetime) -> None:
        if self.opened is not None:
            if when < self.opened + timedelta(minutes=5):
                return  # the late answer of a call made before it opened
            if ok:
                self.opened, self.streak, self.window = None, 0, []
            else:
                self.streak, self.opened = self.streak + 1, when
            return
        self.window.append((when, ok))
        if ok:
            self.streak = 0
            return
        self.streak += 1
        recent = [served for (then, served) in self.window if when - timedelta(minutes=10) < then <= when]
        failures = len(recent) - sum(recent)
        if self.streak >= 5 or (len(recent) >= 10 and failures * 100 > 20 * len(recent)):
            self.opened = when

    def view(self, at: datetime) -> dict[str, Any]:
        recent = [served for (then, served) in self.window if at - timedelta(minutes=10) < then <= at]
        if self.opened is None:
            state = "closed"
        else:
            state = "open" if at < self.opened + timedelta(minutes=5) else "half_open"
        return {"state": state, "consecutive_failures": self.streak, "calls_10m": len(recent), "errors_10m": len(recent) - sum(recent),
                "opened_at": None if self.opened is None else self.opened.isoformat()}


GAPS = [timedelta(0), timedelta(0), SECOND, SECOND, 30 * SECOND, 2 * MINUTE, 4 * MINUTE + 59 * SECOND, 5 * MINUTE, 7 * MINUTE, 11 * MINUTE]


def random_history(rng: random.Random) -> list[tuple[bool, datetime]]:
    served = rng.choice([0.1, 0.5, 0.8, 0.95])
    at = T0
    history: list[tuple[bool, datetime]] = []
    for _ in range(rng.randint(3, 70)):
        at += rng.choice(GAPS)
        history.append((rng.random() < served, at))
    return history


def test_the_state_is_a_pure_function_of_the_ordered_history() -> None:
    """For 400 random histories, after every call and at several moments after it: the circuit says what the reference says, whatever else
    was asked in between (queries and probes change nothing), and a second model recorded in the same circuit does not disturb the first."""
    rng = random.Random(20261103)
    seen: set[tuple[str, str]] = set()
    for _ in range(400):
        history = random_history(rng)
        reference = Reference()
        plain, noisy, shared = rt.Circuit(), rt.Circuit(), rt.Circuit()
        for ok, when in history:
            before = noisy.state(MODEL, when)
            reference.record(ok, when)
            plain.record(MODEL, ok, when)
            after = noisy.record(MODEL, ok, when)
            shared.record(OTHER, not ok, when)  # another model, with the opposite results, in the same circuit
            shared.record(MODEL, ok, when)
            seen.add((before, after))
            if ok and before == "closed":
                assert after == "closed", "a success opened the circuit"
            noisy.snapshot(when)  # asking changes nothing
            noisy.allow(MODEL, when)  # (in half-open this hands out the probe, which is not part of the state)
            noisy.state(MODEL, when + MINUTE)
            for ask in (when, when + 4 * MINUTE + 59 * SECOND, when + 5 * MINUTE, when + 11 * MINUTE):
                expected = reference.view(ask)
                assert plain.snapshot(ask)[MODEL] == expected, (history, ask)
                assert noisy.snapshot(ask)[MODEL] == expected
                assert shared.snapshot(ask)[MODEL] == expected
                assert plain.state(MODEL, ask) == expected["state"]
    # the generator reaches every way the state can change: it opens, a late answer is ignored, a probe closes it, a probe re-opens it
    assert {("closed", "open"), ("open", "open"), ("half_open", "closed"), ("half_open", "open"), ("closed", "closed")} <= seen


def test_replaying_the_same_history_gives_the_same_state() -> None:
    rng = random.Random(7)
    history = random_history(rng)
    first, second = rt.Circuit(), rt.Circuit()
    for ok, when in history:
        first.record(MODEL, ok, when)
        second.record(MODEL, ok, when)
    at = history[-1][1] + 6 * MINUTE
    assert first.snapshot(at) == second.snapshot(at)


# ---- 3. retries -------------------------------------------------------------------------------------------------------------------------

@dataclass
class Out:
    """What a call returns, as far as the retries care: an error."""

    error: str | None = None


class World:
    """A clock that moves only when the code under test sleeps or a call takes time, and a record of the sleeps it was asked for."""

    def __init__(self, start: datetime = T0) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += timedelta(seconds=seconds)


def scripted(world: World, errors: list[str | None], *, takes: timedelta = timedelta(0)) -> tuple[Callable[[], Out], list[datetime]]:
    """A call that returns the given errors in turn, takes ``takes`` of the world's time, and notes when it was started."""
    answers = iter(errors)
    started: list[datetime] = []

    def call() -> Out:
        started.append(world.t)
        world.t += takes
        return Out(next(answers))

    return call, started


def attempt(world: World, errors: list[str | None], circuit: rt.Circuit | None = None, **options: Any) -> tuple[rt.Attempts[Out], rt.Circuit]:
    circuit = rt.Circuit() if circuit is None else circuit
    takes = options.pop("takes", timedelta(0))
    call, _ = scripted(world, errors, takes=takes)
    return rt.run_with_retries(call, sleep=world.sleep, circuit=circuit, model=MODEL, now=world.now, **options), circuit


def test_the_backoff_is_one_two_four_and_then_eight() -> None:
    assert [rt.backoff_s(n) for n in range(1, 8)] == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0, 8.0]
    assert rt.backoff_s(10**9) == 8.0  # no overflow
    assert rt.backoff_s(1, jitter=0.0) == 1.0


def test_the_jitter_lengthens_the_wait_by_a_fraction_up_to_the_cap() -> None:
    assert rt.backoff_s(1, jitter=0.5) == 1.5
    assert rt.backoff_s(2, jitter=0.25) == 2.5
    assert rt.backoff_s(3, jitter=0.5) == 6.0
    assert rt.backoff_s(3, jitter=1.0) == 8.0
    assert rt.backoff_s(4, jitter=1.0) == 8.0  # never more than the cap
    assert rt.backoff_s(1, jitter=1.0) == 2.0


def test_the_backoff_is_monotonic_and_bounded_for_any_jitter() -> None:
    rng = random.Random(3)
    for _ in range(500):
        jitter = rng.random()
        waits = [rt.backoff_s(n, jitter=jitter) for n in range(1, 12)]
        assert waits == sorted(waits)
        assert min(waits) >= 1.0
        assert max(waits) <= rt.BACKOFF_CAP_S


@pytest.mark.parametrize("attempt_number", [0, -1, -100])
def test_the_first_retry_is_number_one(attempt_number: int) -> None:
    with pytest.raises(ValueError, match="counts from 1"):
        rt.backoff_s(attempt_number)


@pytest.mark.parametrize("jitter", [-0.01, 1.01, 2.0, math.nan, math.inf, -math.inf])
def test_a_jitter_that_is_not_a_fraction_is_refused(jitter: float) -> None:
    with pytest.raises(ValueError, match="fraction"):
        rt.backoff_s(1, jitter=jitter)


def test_a_call_that_succeeds_is_made_once() -> None:
    world = World()
    attempts, circuit = attempt(world, [None])
    assert (attempts.errors, attempts.retries, attempts.stopped_by, attempts.calls) == ([None], 0, "ok", 1)
    assert world.sleeps == []
    assert circuit.snapshot(world.t)[MODEL]["calls_10m"] == 1


def test_transport_failures_are_retried_until_one_call_succeeds() -> None:
    world = World()
    attempts, _ = attempt(world, ["timeout", "unavailable", None])
    assert attempts.errors == ["timeout", "unavailable", None]
    assert (attempts.retries, attempts.stopped_by) == (2, "ok")
    assert world.sleeps == [1.0, 2.0]
    assert attempts.last is not None
    assert attempts.last.error is None


@pytest.mark.parametrize("first", sorted(rt.RETRYABLE_CODES))
def test_each_transport_failure_is_retried(first: str) -> None:
    world = World()
    attempts, _ = attempt(world, [first, None])
    assert (attempts.errors, attempts.retries, attempts.stopped_by) == ([first, None], 1, "ok")


def test_the_retries_are_spent_after_the_third() -> None:
    world = World()
    attempts, _ = attempt(world, ["timeout"] * 10)
    assert rt.MAX_RETRIES == 3
    assert attempts.errors == ["timeout"] * 4  # the first call and three retries
    assert (attempts.retries, attempts.stopped_by) == (rt.MAX_RETRIES, "exhausted")
    assert world.sleeps == [1.0, 2.0, 4.0]


def test_the_last_retry_that_succeeds_is_not_exhausted() -> None:
    world = World()
    attempts, _ = attempt(world, ["rate_limited", "rate_limited", "rate_limited", None])
    assert (attempts.retries, attempts.stopped_by) == (3, "ok")


@pytest.mark.parametrize("error", NOT_RETRYABLE)
def test_an_error_that_a_second_try_cannot_cure_stops_at_once(error: str) -> None:
    world = World()
    attempts, _ = attempt(world, [error, None, None])
    assert attempts.errors == [error]
    assert (attempts.retries, attempts.stopped_by) == (0, "non_retryable")
    assert world.sleeps == []


def test_a_transport_failure_that_turns_into_a_refusal_stops_there() -> None:
    world = World()
    attempts, _ = attempt(world, ["timeout", "refused", None])
    assert attempts.errors == ["timeout", "refused"]
    assert (attempts.retries, attempts.stopped_by) == (1, "non_retryable")
    assert world.sleeps == [1.0]


def test_an_open_circuit_stops_before_the_first_call() -> None:
    world = World()
    circuit, opened = opened_circuit()
    world.t = opened + SECOND
    call, started = scripted(world, [None])
    attempts = rt.run_with_retries(call, sleep=world.sleep, circuit=circuit, model=MODEL, now=world.now)
    assert (attempts.errors, attempts.retries, attempts.stopped_by, attempts.last) == ([], 0, "circuit_open", None)
    assert started == []
    assert world.sleeps == []


def test_a_circuit_that_opens_on_this_failure_stops_without_waiting() -> None:
    world = World()
    circuit = rt.Circuit()
    feed(circuit, "xxx", start=T0 - MINUTE)  # three failures just before
    attempts, _ = attempt(world, ["timeout"] * 10, circuit)
    assert attempts.errors == ["timeout", "timeout"]  # the fourth and the fifth failure in a row
    assert attempts.stopped_by == "circuit_open"
    assert world.sleeps == [1.0]  # it waited before the second call, and not after the one that opened the circuit
    assert circuit.state(MODEL, world.t) == "open"


def test_the_half_open_probe_closes_the_circuit_when_it_succeeds() -> None:
    world = World()
    circuit, opened = opened_circuit()
    world.t = opened + rt.OPEN_FOR
    attempts, _ = attempt(world, [None], circuit)
    assert (attempts.errors, attempts.stopped_by) == ([None], "ok")
    assert circuit.state(MODEL, world.t) == "closed"


def test_a_failed_probe_is_not_retried_and_reopens_the_circuit() -> None:
    world = World()
    circuit, opened = opened_circuit()
    world.t = opened + rt.OPEN_FOR
    attempts, _ = attempt(world, ["timeout", None], circuit)
    assert (attempts.errors, attempts.retries, attempts.stopped_by) == (["timeout"], 0, "circuit_open")
    assert world.sleeps == []
    assert circuit.state(MODEL, world.t) == "open"


def test_a_deadline_that_has_passed_stops_before_the_first_call() -> None:
    world = World()
    call, started = scripted(world, [None])
    for deadline in (T0, T0 - SECOND):  # at the deadline is already late
        attempts = rt.run_with_retries(call, sleep=world.sleep, circuit=rt.Circuit(), model=MODEL, now=world.now, deadline_at=deadline)
        assert (attempts.errors, attempts.stopped_by, attempts.last) == ([], "deadline", None)
    assert started == []


def test_an_expired_task_does_not_take_the_half_open_probe() -> None:
    """The deadline is looked at BEFORE the circuit: ``allow`` hands out the probe, and a probe handed out for a call that is then not
    made keeps the model out of use until the lease runs out."""
    world = World()
    circuit, opened = opened_circuit()
    world.t = opened + rt.OPEN_FOR  # half-open
    call, started = scripted(world, [None])
    attempts = rt.run_with_retries(call, sleep=world.sleep, circuit=circuit, model=MODEL, now=world.now, deadline_at=world.t)
    assert (attempts.stopped_by, started) == ("deadline", [])
    assert circuit.allow(MODEL, world.t) is True  # the probe is still there for whoever comes next
    assert circuit.allow(MODEL, world.t) is False


def test_a_retry_that_could_not_start_before_the_deadline_is_not_waited_for() -> None:
    for deadline, outcome in ((T0 + SECOND, "deadline"), (T0 + SECOND - MICRO, "deadline"), (T0 + SECOND + MICRO, "ok")):
        world = World()
        attempts, _ = attempt(world, ["timeout", None], deadline_at=deadline)
        assert attempts.stopped_by == outcome, deadline
        # the wait of the first retry is one second: it must END before the deadline, not at it
        assert world.sleeps == ([] if outcome == "deadline" else [1.0])
        assert attempts.errors == (["timeout"] if outcome == "deadline" else ["timeout", None])


def test_the_time_the_calls_take_counts_against_the_deadline() -> None:
    world = World()
    attempts, _ = attempt(world, ["timeout"] * 10, deadline_at=T0 + 8 * SECOND, takes=3 * SECOND)
    # call 1: 0 to 3 s, wait 1 s; call 2: 4 to 7 s, the next wait (2 s) would end at 9 s: after the deadline
    assert attempts.errors == ["timeout", "timeout"]
    assert attempts.stopped_by == "deadline"
    assert world.sleeps == [1.0]
    assert world.t == T0 + 7 * SECOND


def test_a_deadline_in_another_zone_is_the_same_deadline() -> None:
    world = World()
    deadline = (T0 + SECOND + MICRO).astimezone(timezone(timedelta(hours=-5)))
    attempts, _ = attempt(world, ["timeout", None], deadline_at=deadline)
    assert attempts.stopped_by == "ok"


def test_every_call_is_recorded_in_the_circuit_by_its_code() -> None:
    world = World()
    attempts, circuit = attempt(world, ["timeout", "rate_limited", None])
    assert attempts.stopped_by == "ok"
    snapshot = circuit.snapshot(world.t)[MODEL]
    assert (snapshot["calls_10m"], snapshot["errors_10m"], snapshot["consecutive_failures"]) == (3, 2, 0)


@pytest.mark.parametrize(("error", "calls", "errors"), [
    ("invalid_output", 1, 0), ("refused", 1, 0),  # the provider answered
    ("over_budget", 0, 0), ("not_configured", 0, 0),  # no call was made
    ("limit_reached", 1, 1), ("something_new", 1, 1),
])
def test_what_is_recorded_for_an_error_that_is_not_retried(error: str, calls: int, errors: int) -> None:
    world = World()
    attempts, circuit = attempt(world, [error])
    assert attempts.stopped_by == "non_retryable"
    snapshot = circuit.snapshot(world.t).get(MODEL, {"calls_10m": 0, "errors_10m": 0})
    assert (snapshot["calls_10m"], snapshot["errors_10m"]) == (calls, errors)


def test_the_same_call_and_the_same_model_every_time() -> None:
    """The retries cannot change the request: the call takes no arguments, and the circuit hears of one model only."""
    world = World()
    request = {"tier": "bulk", "prompt": "frozen"}
    seen: list[dict[str, str]] = []
    answers = iter(["timeout", "unavailable", "rate_limited", None])

    def call(*args: object, **kwargs: object) -> Out:
        assert not args
        assert not kwargs
        seen.append(request)
        return Out(next(answers))

    models: list[str] = []

    class Spy(rt.Circuit):
        def allow(self, model: str, at: datetime) -> bool:
            models.append(model)
            return super().allow(model, at)

        def record_outcome(self, model: str, error: str | None, at: datetime) -> rt.CircuitState:
            models.append(model)
            return super().record_outcome(model, error, at)

    attempts = rt.run_with_retries(call, sleep=world.sleep, circuit=Spy(), model=MODEL, now=world.now)
    assert (attempts.retries, attempts.stopped_by) == (3, "ok")
    assert seen == [request] * 4
    assert all(item is request for item in seen)
    assert set(models) == {MODEL}


def test_the_jitter_comes_from_the_caller() -> None:
    world = World()
    attempts, _ = attempt(world, ["timeout"] * 10, jitter=lambda: 0.5)
    assert attempts.stopped_by == "exhausted"
    assert world.sleeps == [1.5, 3.0, 6.0]


def test_a_jitter_outside_zero_to_one_is_refused() -> None:
    world = World()
    with pytest.raises(ValueError, match="fraction"):
        attempt(world, ["timeout", None], jitter=lambda: 1.5)


def test_a_naive_clock_or_deadline_is_refused_before_anything_is_called() -> None:
    world = World()
    call, started = scripted(world, [None])
    with pytest.raises(ValueError, match="timezone-aware"):
        rt.run_with_retries(call, sleep=world.sleep, circuit=rt.Circuit(), model=MODEL,
                            now=lambda: datetime(2026, 11, 3, 15, 0))  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        rt.run_with_retries(call, sleep=world.sleep, circuit=rt.Circuit(), model=MODEL, now=world.now,
                            deadline_at=datetime(2026, 11, 3, 16, 0))  # noqa: DTZ001 - the point of the test
    assert started == []


def test_an_exception_of_the_call_is_not_swallowed() -> None:
    world = World()
    circuit = rt.Circuit()

    def broken() -> Out:
        raise RuntimeError("a bug")

    with pytest.raises(RuntimeError, match="a bug"):
        rt.run_with_retries(broken, sleep=world.sleep, circuit=circuit, model=MODEL, now=world.now)
    assert world.sleeps == []
    assert circuit.snapshot(world.t) == {}  # nothing was recorded for a call that returned nothing


def test_it_works_with_the_real_call_outcome() -> None:
    world = World()
    outcomes = iter([CallOutcome(None, None, None, "anthropic", MODEL, Decimal(0), "timeout"),
                     CallOutcome(None, 7, "bulk", "anthropic", MODEL, Decimal("0.01"))])
    attempts = rt.run_with_retries(lambda: next(outcomes), sleep=world.sleep, circuit=rt.Circuit(), model=MODEL, now=world.now)
    assert (attempts.errors, attempts.stopped_by) == (["timeout", None], "ok")
    assert attempts.last is not None
    assert attempts.last.usage_id == 7  # the caller gets what the last call returned


def test_the_attempts_it_returns_are_not_shared_between_runs() -> None:
    world = World()
    first, _ = attempt(world, ["timeout", None])
    second, _ = attempt(world, [None])
    assert first.errors == ["timeout", None]
    assert second.errors == [None]


# ---- 4. deadlines -----------------------------------------------------------------------------------------------------------------------

def test_the_final_deadline_is_fifteen_minutes_before_kickoff() -> None:
    assert timedelta(minutes=15) == rt.FINAL_MARGIN
    assert rt.final_deadline(KICKOFF) == KICKOFF - timedelta(minutes=15)
    assert rt.final_deadline(KICKOFF) == datetime(2026, 11, 3, 19, 45, tzinfo=UTC)


def test_the_deadline_is_the_same_instant_in_any_zone() -> None:
    bogota = KICKOFF.astimezone(timezone(timedelta(hours=-5)))
    assert bogota.hour == 15
    assert rt.final_deadline(bogota) == rt.final_deadline(KICKOFF)
    assert rt.final_deadline(bogota).utcoffset() == timedelta(0)


def test_the_minutes_are_taken_off_the_instant_and_not_off_the_wall_clock() -> None:
    new_york = ZoneInfo("America/New_York")
    kickoff = datetime(2026, 3, 8, 3, 10, tzinfo=new_york)  # ten minutes after the clocks went forward (2:00 became 3:00)
    assert kickoff.astimezone(UTC) == datetime(2026, 3, 8, 7, 10, tzinfo=UTC)
    assert rt.final_deadline(kickoff) == datetime(2026, 3, 8, 6, 55, tzinfo=UTC)  # not 7:55, which is what 2:55 «local» would give
    now = datetime(2026, 3, 8, 1, 50, tzinfo=new_york)  # 6:50 UTC, in the SAME zone as the kick-off: Python alone would subtract wall clocks
    assert rt.time_left("final", kickoff, now) == timedelta(minutes=5)


@pytest.mark.parametrize("pass_kind", get_args(PassKind))
def test_every_pass_is_held_to_the_same_deadline(pass_kind: PassKind) -> None:
    assert rt.time_left(pass_kind, KICKOFF, KICKOFF - timedelta(hours=2)) == timedelta(hours=1, minutes=45)
    deadline = rt.final_deadline(KICKOFF)
    assert rt.time_left(pass_kind, KICKOFF, deadline - SECOND) == SECOND
    assert rt.time_left(pass_kind, KICKOFF, deadline) == timedelta(0)
    assert rt.time_left(pass_kind, KICKOFF, deadline + SECOND) == -SECOND
    assert rt.time_left(pass_kind, KICKOFF, KICKOFF + timedelta(hours=1)) == -timedelta(hours=1, minutes=15)


@pytest.mark.parametrize("pass_kind", ["first", "pre", "final"])
def test_a_pass_that_ends_before_t_minus_15_goes_and_one_that_would_not_is_too_late(pass_kind: PassKind) -> None:
    expected = timedelta(minutes=20)
    start = rt.final_deadline(KICKOFF) - expected  # a pass that starts now would end exactly at T-15
    assert rt.verdict(pass_kind, KICKOFF, start - MICRO, expected) == "go"
    assert rt.verdict(pass_kind, KICKOFF, start, expected) == "too_late"  # ending AT T-15 is late: the plan says «antes de»
    assert rt.verdict(pass_kind, KICKOFF, start + MICRO, expected) == "too_late"
    assert rt.verdict(pass_kind, KICKOFF, KICKOFF - timedelta(hours=3), expected) == "go"
    assert rt.verdict(pass_kind, KICKOFF, KICKOFF + timedelta(minutes=1), expected) == "too_late"  # the match has begun


def test_a_pass_that_takes_no_time_still_cannot_start_at_the_deadline() -> None:
    deadline = rt.final_deadline(KICKOFF)
    assert rt.verdict("final", KICKOFF, deadline - MICRO, timedelta(0)) == "go"
    assert rt.verdict("final", KICKOFF, deadline, timedelta(0)) == "too_late"


def test_the_verdict_does_not_depend_on_the_zone() -> None:
    expected = timedelta(minutes=10)
    now = KICKOFF - timedelta(minutes=30)
    tokyo = ZoneInfo("Asia/Tokyo")
    assert rt.verdict("final", KICKOFF.astimezone(tokyo), now.astimezone(timezone(timedelta(hours=-5))), expected) == "go"
    assert rt.verdict("final", KICKOFF, now + timedelta(minutes=6), expected) == "too_late"


def test_a_negative_duration_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        rt.verdict("final", KICKOFF, KICKOFF - timedelta(hours=1), -SECOND)


@pytest.mark.parametrize("pass_kind", ["", "FINAL", "last", "postmortem"])
def test_an_unknown_pass_is_refused(pass_kind: str) -> None:
    with pytest.raises(ValueError, match="unknown pass"):
        rt.time_left(pass_kind, KICKOFF, KICKOFF - timedelta(hours=1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown pass"):
        rt.verdict(pass_kind, KICKOFF, KICKOFF - timedelta(hours=1), SECOND)  # type: ignore[arg-type]


def test_a_naive_datetime_is_refused_by_every_deadline_function() -> None:
    naive = datetime(2026, 11, 3, 19, 0)  # noqa: DTZ001 - the point of the test
    aware = KICKOFF - timedelta(hours=1)
    calls: list[Callable[[], object]] = [
        lambda: rt.final_deadline(naive),
        lambda: rt.time_left("final", naive, aware),
        lambda: rt.time_left("final", KICKOFF, naive),
        lambda: rt.verdict("final", naive, aware, SECOND),
        lambda: rt.verdict("final", KICKOFF, naive, SECOND),
    ]
    for call in calls:
        with pytest.raises(ValueError, match="timezone-aware"):
            call()


# ---- 5. when an arm stops ---------------------------------------------------------------------------------------------------------------

def pause(invalid: int = 0, calls: int = 0, state: str = "closed", left: str = "10") -> list[str]:
    return rt.arm_pause(invalid=invalid, calls=calls, circuit_state=state, envelope_left_usd=Decimal(left))


@pytest.mark.parametrize(("invalid", "calls", "reasons"), [
    (0, 0, []),
    (1, 3, []),  # one invalid of three calls does not pause a day
    (3, 3, []),  # nor do three of three: the sample is too small to say anything
    (33, 33, []),  # below the floor, whatever the share
    (1, 33, []),  # (3.03 %, but 33 calls)
    (1, 34, []),  # at the floor: 2.94 %
    (1, 1000, []),
    (2, 34, ["invalid_over_3pct"]),  # 5.9 %
    (34, 34, ["invalid_over_3pct"]),
    (2, 66, ["invalid_over_3pct"]),  # 3.03 %
    (2, 67, []),  # 2.99 %
    (3, 100, []),  # exactly 3 % is not MORE than 3 %
    (4, 100, ["invalid_over_3pct"]),
    (30, 1000, []),
    (31, 1000, ["invalid_over_3pct"]),
])
def test_the_invalid_output_rule(invalid: int, calls: int, reasons: list[str]) -> None:
    assert pause(invalid, calls) == reasons


def test_a_single_invalid_output_never_pauses_a_day() -> None:
    assert rt.MIN_CALLS_FOR_RATE == 34
    assert all(pause(min(1, calls), calls) == [] for calls in range(0, 5000))
    assert pause(2, rt.MIN_CALLS_FOR_RATE) == ["invalid_over_3pct"]


def test_the_rule_is_silent_below_the_floor_and_speaks_at_it() -> None:
    assert pause(rt.MIN_CALLS_FOR_RATE - 1, rt.MIN_CALLS_FOR_RATE - 1) == []
    assert pause(rt.MIN_CALLS_FOR_RATE, rt.MIN_CALLS_FOR_RATE) == ["invalid_over_3pct"]


@pytest.mark.parametrize(("state", "reasons"), [("closed", []), ("half_open", []), ("open", ["circuit_open"])])
def test_an_open_circuit_pauses_the_arm_and_a_half_open_one_does_not(state: str, reasons: list[str]) -> None:
    assert pause(state=state) == reasons
    assert state in get_args(rt.CircuitState)


@pytest.mark.parametrize(("left", "reasons"), [
    ("10", []), ("0.01", []), ("0.0001", []),
    ("0", ["envelope_spent"]), ("0.00", ["envelope_spent"]), ("-0", ["envelope_spent"]),
    ("-0.01", ["envelope_spent"]), ("-5", ["envelope_spent"]),
])
def test_a_spent_envelope_pauses_the_arm(left: str, reasons: list[str]) -> None:
    assert pause(left=left) == reasons


def test_the_reasons_come_in_the_order_of_the_plan() -> None:
    assert pause(invalid=34, calls=34, state="open", left="0") == ["invalid_over_3pct", "circuit_open", "envelope_spent"]
    assert pause(invalid=34, calls=34, state="open", left="0") == list(rt.PAUSE_REASONS)
    assert pause(state="open", left="-1") == ["circuit_open", "envelope_spent"]
    assert pause(invalid=40, calls=100, left="0") == ["invalid_over_3pct", "envelope_spent"]
    assert pause(invalid=40, calls=100, state="open") == ["invalid_over_3pct", "circuit_open"]


def test_the_reason_code_names_the_limit() -> None:
    assert f"invalid_over_{rt.INVALID_LIMIT_PERCENT}pct" == rt.PAUSE_INVALID


def test_it_returns_a_fresh_list_each_time() -> None:
    first = pause(state="open")
    first.append("x")
    assert pause(state="open") == ["circuit_open"]


@pytest.mark.parametrize("arguments", [
    {"invalid": -1, "calls": 10}, {"invalid": 0, "calls": -1}, {"invalid": 11, "calls": 10},
    {"state": "OPEN"}, {"state": ""}, {"state": "broken"}, {"state": "half-open"},
    {"left": "NaN"}, {"left": "Infinity"}, {"left": "-Infinity"},
])
def test_arguments_that_make_no_sense_are_refused(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"invalid|circuit state|finite"):
        pause(**arguments)


def test_the_arm_reads_the_state_the_circuit_reports() -> None:
    circuit, opened = opened_circuit()
    for at, reasons in ((opened, ["circuit_open"]), (opened + rt.OPEN_FOR, []), (opened + rt.OPEN_FOR - MICRO, ["circuit_open"])):
        state = circuit.state(MODEL, at)
        assert pause(state=state) == reasons


# ---- the module itself ------------------------------------------------------------------------------------------------------------------

def imports_when_it_runs(tree: ast.AST) -> list[str]:
    """Every module the code imports when it RUNS: what sits under ``if TYPE_CHECKING:`` is for the annotations only."""
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and isinstance(child.test, ast.Name) and child.test.id == "TYPE_CHECKING":
                continue
            if isinstance(child, ast.Import):
                found.extend(alias.name for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                found.append(child.module or "")
            visit(child)

    visit(tree)
    return found


def test_the_module_imports_only_the_standard_library_when_it_runs() -> None:
    """No import of ours (the retries would close a cycle with ``fbi.ai.usage``) and nothing that reads the world."""
    allowed = {"__future__", "threading", "collections", "collections.abc", "contextlib", "dataclasses", "datetime", "decimal", "typing"}
    assert set(imports_when_it_runs(ast.parse(SOURCE))) <= allowed


def test_the_module_reads_no_clock_and_sleeps_nowhere() -> None:
    clocks = {"now", "utcnow", "today", "sleep", "time", "monotonic", "perf_counter", "random", "uniform"}
    reads = [f"{node.value.id}.{node.attr}" for node in ast.walk(ast.parse(SOURCE))
             if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
             and node.value.id in {"datetime", "time", "random", "date"} and node.attr in clocks]
    assert reads == []


def test_the_passes_are_those_of_the_contracts() -> None:
    assert get_args(PassKind) == rt.PASS_KINDS
    assert rt.CIRCUIT_STATES == ("closed", "open", "half_open")

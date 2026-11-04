"""The guards the Orchestrator puts around every model call: how many at once, when to stop asking, how often to ask again, and when it is
too late (Plan Maestro IA, sections 17, 18, 23 and 32; architecture note, section 17).

Five small parts. They are PURE in the sense that matters for a guard: no database, no network, no wall clock (every function takes the
moment it is asked about, or a clock that is injected), nothing sleeps unless a ``sleep`` is injected, and nothing here imports the rest of
the AI layer - so every threshold can be tested on both sides and the module cannot add an import cycle. What they keep (the slots in
use, the circuit of each model) lives in memory and is thread-safe. The orchestrator holds ONE ``Slots`` and ONE ``Circuit`` for the life
of the process: one per 15-minute tick would forget that a model was down.

    1. CONCURRENCY  ``Slots``, ``CONCURRENCY``: how many calls of each level may be in flight at once.
    2. CIRCUIT      ``Circuit``: a model that keeps failing is not asked for a while, and the rules' reviewer decides.
    3. RETRIES      ``retryable``, ``backoff_s``, ``run_with_retries``: transport failures only, never another model or request.
    4. DEADLINES    ``final_deadline``, ``time_left``, ``verdict``: a ``final`` pass with no verdict before T-15 is too late.
    5. ARM PAUSE    ``arm_pause``: when an experiment's arm stops for the day.

What an error code means to the guards. The codes are those of ``fbi.ai.usage.CallOutcome.error``: the ``ErrorCode`` of
``fbi.ai.providers.base`` plus ``over_budget`` (``call_json`` turns a provider's ``limit_reached`` into it, so through a ``CallOutcome``
that code never arrives; it is classified here all the same, for a caller that holds the raw ``ProviderError``).

    code            what happened                                          provider failed?  retried?  the circuit records
    None            an answer came back                                    no                -         a success
    timeout         no answer in time                                      YES               yes       a failure
    unavailable     HTTP 5xx, an overload (529) or the network             YES               yes       a failure
    rate_limited    HTTP 429 (the provider already asked once more)        YES               yes       a failure
    limit_reached   the workspace's spend limit or the account's tier cap  YES               no        a failure
    invalid_output  an answer came back and does not validate              no                no        a success (it answered)
    refused         HTTP 4xx other than 429: the request was refused       no                no        a success (it answered)
    over_budget     our budget (or the LAB envelope) said no               no                no        nothing: no call was made
    not_configured  no key, or no model for the tier                       no                no        nothing: no call was made
    anything else   a code this module does not know                       YES (fail-safe)   no        a failure

An invalid output or a refusal is the model's (or the request's) answer, not the provider's outage: it is the ARM's metric (``arm_pause``
reads it) and repeating the call cannot cure it. A call that was never made says nothing about the provider, so it is not recorded - a
"success" for it would end a streak of real failures and thin the error rate. A code nobody classified is treated as a failure (the safe
reading: the layer falls back to the rules' reviewer) and is never retried (a retry is money); a test holds the known codes to the table.
Retries and the circuit never change the model or the request: the router forbids going up or down a model because a call failed.

Two figures differ between the plan and the architecture note's first draft, and the plan (the later text) wins: the circuit tries one
call after 5 minutes, not 15 (``OPEN_FOR``), and Haiku has 4 slots, not 6 (``CONCURRENCY``).
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal, Protocol, get_args

if TYPE_CHECKING:  # the type of a pass, for the annotations only: this module imports nothing of ours when it runs
    from fbi.ai.contracts.mcp import PassKind

# -- what an error code means --------------------------------------------------------------------------------------------------------

FAILURE_CODES: Final = frozenset({"timeout", "unavailable", "rate_limited", "limit_reached"})
"""The provider did not serve the call: it counts against the circuit of its model."""
ANSWERED_CODES: Final = frozenset({"invalid_output", "refused"})
"""The provider ANSWERED - with something that cannot be used, or with a no: not an outage, and not for the circuit."""
NEUTRAL_CODES: Final = frozenset({"over_budget", "not_configured"})
"""No call reached the provider (our budget or our configuration said no): the circuit learns nothing from it."""
RETRYABLE_CODES: Final = frozenset({"timeout", "unavailable", "rate_limited"})
"""A transport failure that a second try can cure. ``limit_reached`` is not one: the limit does not lift in seconds."""


def counts_as_failure(error: str | None) -> bool:
    """Whether a call that ended with ``error`` counts against its model's circuit (the table in the module's docstring). No error is no
    failure, an answer that cannot be used is no failure, a call that was not made is no failure, and a code nobody classified IS one."""
    if error is None:
        return False
    return error not in ANSWERED_CODES and error not in NEUTRAL_CODES


def retryable(error: str | None) -> bool:
    """Whether a call that ended with ``error`` may be made again: a timeout, an unavailable provider or a rate limit - and nothing else.
    Never a refusal, an invalid output, a spent budget, a missing configuration, a spent limit or a code nobody classified."""
    return error in RETRYABLE_CODES


# -- time ----------------------------------------------------------------------------------------------------------------------------

def _utc(moment: datetime, name: str) -> datetime:
    """The moment in UTC. A naive datetime is refused: read in the wrong zone, a deadline is hours off and nothing says so. Arithmetic on
    UTC instants is exact; on two datetimes of ONE ``ZoneInfo`` Python subtracts the wall clocks and is wrong across a change of hour."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware, got the naive {moment.isoformat()}")
    return moment.astimezone(UTC)


# -- 1. concurrency ------------------------------------------------------------------------------------------------------------------

CONCURRENCY: Final[dict[str, int]] = {"simple": 4, "complex": 3, "critical": 1}
"""How many calls of each level of ``fbi.ai.router.MODELS`` may be in flight at once: Haiku 4, Sonnet 3, Opus 1 (plan, section 18). The
owner tunes it here; the limits of the API (1,000 requests a minute per model on the Start tier) are far above, so this is about not
saturating the worker and the database, not about the provider. ``owner`` (Fable) has none: it is never called by the orchestrator."""


class _Lane:
    """The slots of one level: a bounded counter and a condition to wait on."""

    __slots__ = ("_cond", "in_use", "limit", "waiting")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.in_use = 0
        self.waiting = 0
        self._cond = threading.Condition(threading.Lock())

    def take(self, timeout_s: float) -> bool:
        with self._cond:
            if self.in_use < self.limit:
                self.in_use += 1
                return True
            if timeout_s <= 0:
                return False
            self.waiting += 1
            try:
                got = self._cond.wait_for(lambda: self.in_use < self.limit, timeout=timeout_s)
                if got:
                    self.in_use += 1
                return got
            finally:
                self.waiting -= 1

    def give(self) -> None:
        with self._cond:
            self.in_use -= 1
            self._cond.notify_all()  # not notify(): a waiter that timed out at that very moment would swallow the only wake-up

    def counts(self) -> tuple[int, int]:
        with self._cond:
            return self.in_use, self.waiting


def _wait_seconds(timeout_s: float) -> float:
    """A timeout a condition can wait on: a negative, zero or NaN timeout does not wait; an infinite one waits as long as one can."""
    if not timeout_s > 0:
        return 0.0
    return min(timeout_s, threading.TIMEOUT_MAX)


class Slots:
    """Bounded concurrency per level: at most ``CONCURRENCY[level]`` holders at once, the others wait their turn or give up.

        with slots.acquire("simple", timeout_s=5.0) as got:
            if got:
                ...  # one slot of the level is ours until the block ends, however it ends
            else:
                ...  # none came free in time: this task does not run now (the caller decides what that means)

    The slot is released when the block ends, by a return or by an exception: a body that raises never leaves a permit behind, and a
    timeout never takes one. A level nobody configured (``owner``, a typo) is a ``ValueError``, raised when ``acquire`` is called."""

    def __init__(self, limits: Mapping[str, int] | None = None) -> None:
        wanted = CONCURRENCY if limits is None else limits
        if not wanted:
            raise ValueError("Slots needs at least one level")
        for level, limit in wanted.items():
            if not level or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError(f"the limit of level {level!r} must be a whole number of at least 1, got {limit!r}")
        self._lanes: dict[str, _Lane] = {level: _Lane(limit) for level, limit in wanted.items()}

    def _lane(self, level: str) -> _Lane:
        lane = self._lanes.get(level)
        if lane is None:
            raise ValueError(f"no slots for level {level!r}; known levels: {sorted(self._lanes)}")
        return lane

    def acquire(self, level: str, *, timeout_s: float) -> AbstractContextManager[bool]:
        """A context manager that waits up to ``timeout_s`` seconds for a slot of ``level`` and yields whether it got one (``timeout_s``
        of 0 or less: a single non-blocking try)."""
        return self._hold(self._lane(level), _wait_seconds(timeout_s))

    @contextmanager
    def _hold(self, lane: _Lane, timeout_s: float) -> Iterator[bool]:
        got = lane.take(timeout_s)
        try:
            yield got
        finally:
            if got:
                lane.give()

    def in_use(self, level: str) -> int:
        """The slots of ``level`` that are held right now."""
        return self._lane(level).counts()[0]

    def waiting(self, level: str) -> int:
        """The callers blocked in ``acquire`` for ``level`` right now."""
        return self._lane(level).counts()[1]

    def limit(self, level: str) -> int:
        """How many slots ``level`` has."""
        return self._lane(level).limit


# -- 2. the circuit of a model -------------------------------------------------------------------------------------------------------

FAILURES_IN_A_ROW: Final = 5
"""This many failures with no success between them open the circuit (plan, section 18)."""
ERROR_RATE_PERCENT: Final = 20
"""More than this share of the calls of the window being failures opens the circuit: 21 % does, 20 % does not. Whole numbers are compared
(``errors * 100 > 20 * calls``), never floats."""
RATE_WINDOW: Final = timedelta(minutes=10)
"""The window of the error rate. A call stays in it while it is younger than this: one exactly this old has left."""
MIN_CALLS: Final = 10
"""The rate rule is silent below this many calls in the window. Fewer, and one error is already 10 % (1 in 2 is 50 %): the circuit would
open on noise. At 10 calls two errors are exactly 20 % (closed) and three open it, so the rate NEVER opens the circuit on fewer than 3
errors, whatever the volume. The streak of ``FAILURES_IN_A_ROW`` has no floor: five failures in a row are five failures."""
OPEN_FOR: Final = timedelta(minutes=5)
"""How long an open circuit refuses every call, and how long a failed probe re-opens it for (plan, section 18; the architecture note's
draft said 15 minutes)."""
PROBE_LEASE: Final = timedelta(minutes=5)
"""A half-open circuit lets ONE probe through and refuses the rest until the probe's result is recorded. If that result never comes (the
thread was cancelled, or the call raised, between ``allow`` and ``record``), the next caller after this long becomes the probe: without
it a lost probe would keep the model out for the life of the process. A call is bounded by its own timeout (at most 150 s in the plan),
so a live probe is never taken over."""

CircuitState = Literal["closed", "open", "half_open"]
CIRCUIT_STATES: Final[tuple[str, ...]] = get_args(CircuitState)


@dataclass(slots=True)
class _Book:
    """What the circuit remembers of one model."""

    events: deque[tuple[datetime, bool]] = field(default_factory=deque)
    """The calls of the window, in the order they were recorded: when they ended and whether they were served."""
    streak: int = 0
    opened_at: datetime | None = None
    probe_since: datetime | None = None
    """When the half-open probe was handed out (None: nobody holds it)."""


def _phase(book: _Book, moment: datetime) -> CircuitState:
    if book.opened_at is None:
        return "closed"
    return "open" if moment < book.opened_at + OPEN_FOR else "half_open"


def _counts(events: deque[tuple[datetime, bool]], moment: datetime) -> tuple[int, int]:
    """(calls, failures) among the events younger than the window at ``moment`` and not after it."""
    since = moment - RATE_WINDOW
    calls = failures = 0
    for when, ok in events:
        if since < when <= moment:
            calls += 1
            failures += 0 if ok else 1
    return calls, failures


class Circuit:
    """A circuit breaker per model, in memory, thread-safe. Every method takes the moment it is about (``at``, timezone-aware): there is
    no clock in here, and the state is a pure function of the ORDERED history of ``record`` calls and of the moment asked about.

        CLOSED     --  5 failures in a row, or more than 20 % of at least 10 calls of the last 10 minutes  -->  OPEN
        OPEN       --  5 minutes  -->  HALF_OPEN
        HALF_OPEN  --  the one probe succeeds  -->  CLOSED (the window is cleared)
        HALF_OPEN  --  the one probe fails  -->  OPEN for 5 more minutes

    The rules, one by one:

      * Only a FAILURE can open the circuit: a success never does. The rate is worked out over the window at the moment of the failure.
      * ``allow`` is True while CLOSED, False while OPEN, and in HALF_OPEN True for exactly ONE caller (the probe); the others see False
        until the probe's result is recorded - or, if it never is, until ``PROBE_LEASE`` has passed (see there).
      * The first result recorded once the circuit is HALF_OPEN is the probe's: a success closes it and clears the window (the probe is
        not counted as a call), a failure re-opens it for ``OPEN_FOR`` from then.
      * A result that ends while the circuit is OPEN is the late answer of a call made before it opened: it changes nothing.
      * ``allow``, ``state`` and ``snapshot`` never create the entry of a model they have not seen; they only read (``allow`` also
        hands out the probe).

    ``record`` takes a boolean; ``record_outcome`` takes the error code of a call and applies the table of the module's docstring."""

    def __init__(self) -> None:
        self._books: dict[str, _Book] = {}
        self._lock = threading.Lock()

    def record(self, model: str, ok: bool, at: datetime) -> CircuitState:
        """Record that a call to ``model`` ended at ``at``, served (``ok``) or not. Returns the state afterwards."""
        moment = _utc(at, "at")
        with self._lock:
            book = self._books.setdefault(model, _Book())
            phase = _phase(book, moment)
            if phase == "open":
                return "open"
            if phase == "half_open":
                book.probe_since = None
                if ok:
                    book.events.clear()
                    book.streak = 0
                    book.opened_at = None
                    return "closed"
                book.streak += 1
                book.opened_at = moment
                return "open"
            since = moment - RATE_WINDOW
            while book.events and book.events[0][0] <= since:
                book.events.popleft()
            book.events.append((moment, ok))
            if ok:
                book.streak = 0
                return "closed"
            book.streak += 1
            calls, failures = _counts(book.events, moment)
            if book.streak >= FAILURES_IN_A_ROW or (
                    calls >= MIN_CALLS and failures * 100 > ERROR_RATE_PERCENT * calls):
                book.opened_at = moment
                return "open"
            return "closed"

    def record_outcome(self, model: str, error: str | None, at: datetime) -> CircuitState:
        """Record the end of a call by its error code (``CallOutcome.error``): a failure of the provider is a failure, an answer that
        cannot be used is a success (the provider answered), and a call that was never made (``over_budget``, ``not_configured``) is
        not recorded at all - if it was the half-open probe, the probe is handed back so that the next caller may take it."""
        if error not in NEUTRAL_CODES:
            return self.record(model, not counts_as_failure(error), at)
        moment = _utc(at, "at")
        with self._lock:
            book = self._books.get(model)
            if book is None:
                return "closed"
            phase = _phase(book, moment)
            if phase == "half_open":
                book.probe_since = None
            return phase

    def allow(self, model: str, at: datetime) -> bool:
        """Whether a call to ``model`` may be made at ``at``. In HALF_OPEN the first caller gets True (it is the probe and MUST record
        its result); the rest get False."""
        moment = _utc(at, "at")
        with self._lock:
            book = self._books.get(model)
            if book is None:
                return True
            phase = _phase(book, moment)
            if phase == "closed":
                return True
            if phase == "open":
                return False
            if book.probe_since is not None and moment - book.probe_since < PROBE_LEASE:
                return False
            book.probe_since = moment
            return True

    def state(self, model: str, at: datetime) -> CircuitState:
        """``closed``, ``open`` or ``half_open`` at ``at``; a model never seen is closed. It reads and changes nothing."""
        moment = _utc(at, "at")
        with self._lock:
            book = self._books.get(model)
            return "closed" if book is None else _phase(book, moment)

    def snapshot(self, at: datetime) -> dict[str, dict[str, str | int | None]]:
        """Every model the circuit has seen, as plain JSON-able data, for the Console and the run's record: ``state``,
        ``consecutive_failures``, ``calls_10m`` and ``errors_10m`` (the window ending at ``at``) and ``opened_at`` (ISO 8601, UTC; the
        moment the circuit opened, kept while it is half-open, None when closed)."""
        moment = _utc(at, "at")
        with self._lock:
            out: dict[str, dict[str, str | int | None]] = {}
            for model, book in sorted(self._books.items()):
                calls, failures = _counts(book.events, moment)
                out[model] = {
                    "state": _phase(book, moment),
                    "consecutive_failures": book.streak,
                    "calls_10m": calls,
                    "errors_10m": failures,
                    "opened_at": None if book.opened_at is None else book.opened_at.isoformat(),
                }
            return out


# -- 3. retries ----------------------------------------------------------------------------------------------------------------------

MAX_RETRIES: Final = 3
"""A call is made again at most this many times after the first (so up to 4 calls). The plan says «como mucho 3 intentos»; the backoff that
goes with it (1, 2 and 4 seconds) is three waits, so this reads it as 3 RETRIES. Set it to 2 if three attempts in all are meant."""
BACKOFF_BASE_S: Final = 1.0
BACKOFF_CAP_S: Final = 8.0
"""The wait before the n-th retry is 1, 2, 4 seconds, and never more than 8 whatever the jitter. The plan also says «respetando
retry-after»: the provider does that itself (``AnthropicProvider`` asks once more after the API's ``retry-after``), and a ``CallOutcome``
does not carry the header, so the waits here are the plan's fixed ones."""

StoppedBy = Literal["ok", "non_retryable", "exhausted", "circuit_open", "deadline"]


def backoff_s(attempt: int, *, jitter: float = 0.0) -> float:
    """Seconds to wait before retry number ``attempt`` (1 is the first retry): 1, 2, 4, then 8 for ever. ``jitter`` is a fraction from 0
    to 1 that the CALLER draws (``random.random()``): the wait is lengthened by that share, up to the cap. With no jitter it is
    deterministic."""
    if attempt < 1:
        raise ValueError(f"attempt counts from 1, got {attempt}")
    if not 0.0 <= jitter <= 1.0:
        raise ValueError(f"jitter is a fraction from 0 to 1, got {jitter}")
    grown = BACKOFF_BASE_S * (1 << min(attempt - 1, 16))  # the exponent is cut: past 3 the cap rules, and a huge attempt must not overflow
    return min(BACKOFF_CAP_S, grown * (1.0 + jitter))


class HasError(Protocol):
    """What ``run_with_retries`` needs of what a call returns: ``fbi.ai.usage.CallOutcome`` has it. A protocol, because this module does not
    import ``fbi.ai.usage`` (it would close an import cycle)."""

    @property
    def error(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Attempts[T: HasError]:
    """How a ``run_with_retries`` ended."""

    errors: list[str | None]
    """The error of each call made, in order (None for a call that succeeded): one entry per call, so ``len(errors)`` is the calls."""
    retries: int
    """The calls made after the first."""
    stopped_by: StoppedBy
    """``ok`` the call succeeded; ``non_retryable`` it failed in a way a second try cannot cure; ``exhausted`` it failed ``MAX_RETRIES + 1``
    times; ``circuit_open`` the circuit of the model refused (or opened on this failure); ``deadline`` there was no time left to try
    again. With anything but ``ok`` the layer falls back to the rules' reviewer."""
    last: T | None = None
    """What the last call returned (its result when ``stopped_by`` is ``ok``); None when no call was made."""

    @property
    def calls(self) -> int:
        return len(self.errors)


def run_with_retries[T: HasError](call: Callable[[], T], *, sleep: Callable[[float], None], circuit: Circuit, model: str,
                                  now: Callable[[], datetime], deadline_at: datetime | None = None,
                                  jitter: Callable[[], float] | None = None) -> Attempts[T]:
    """Make ``call`` (no arguments; it returns an object with ``.error``, like ``CallOutcome``) and, if it failed in a way that a second
    try can cure, make the SAME call again after ``backoff_s``, up to ``MAX_RETRIES`` times.

    Stops, in this order at every turn: the deadline has passed (``deadline``, before the first call too: a call after its deadline is paid
    for and thrown away); the circuit of ``model`` refuses (``circuit_open``); the call succeeded (``ok``); its error is not
    ``retryable`` (``non_retryable``); the retries are spent (``exhausted``); the circuit opened on this very failure (``circuit_open``,
    with no wait); the next wait would end at or after ``deadline_at`` (``deadline``, with no wait). Every call is recorded in the circuit
    by its error code (``Circuit.record_outcome``), at the moment it ended.

    It never changes the model or the request: the router forbids going up or down a model because a call failed, and a changed request
    is another question, paid as another task. ``now`` is a clock (``SystemClock().now``): the time the calls and the waits really took
    is what the deadline is measured against. ``sleep`` waits (``time.sleep``); ``jitter`` draws the fraction of ``backoff_s``
    (``random.random``; none: no jitter). An exception of ``call`` is not caught: ``call_json`` does not raise, and a bug must show."""
    errors: list[str | None] = []
    last: T | None = None
    limit = None if deadline_at is None else _utc(deadline_at, "deadline_at")

    def ended(why: StoppedBy) -> Attempts[T]:
        return Attempts(errors=errors, retries=max(0, len(errors) - 1), stopped_by=why, last=last)

    while True:
        moment = _utc(now(), "now()")
        if limit is not None and moment >= limit:
            return ended("deadline")
        if not circuit.allow(model, moment):
            return ended("circuit_open")
        last = call()
        errors.append(last.error)
        finished = _utc(now(), "now()")
        circuit.record_outcome(model, last.error, finished)
        if last.error is None:
            return ended("ok")
        if not retryable(last.error):
            return ended("non_retryable")
        if len(errors) > MAX_RETRIES:
            return ended("exhausted")
        if circuit.state(model, finished) == "open":
            return ended("circuit_open")
        wait = backoff_s(len(errors), jitter=0.0 if jitter is None else jitter())
        if limit is not None and finished + timedelta(seconds=wait) >= limit:
            return ended("deadline")
        sleep(wait)


# -- 4. deadlines --------------------------------------------------------------------------------------------------------------------

FINAL_MARGIN: Final = timedelta(minutes=15)
"""The ``final`` pass must have its verdict BEFORE kick-off minus this (plan, section 32: «pasada final sin veredicto antes de T-15»)."""
PASS_KINDS: Final[tuple[str, ...]] = ("first", "pre", "final", "request")
"""The passes (``fbi.ai.contracts.mcp.PassKind``, held equal by a test)."""
Verdict = Literal["go", "too_late"]


def final_deadline(kickoff_at: datetime) -> datetime:
    """Kick-off minus ``FINAL_MARGIN``, in UTC. The minutes are taken off the instant, not off the wall clock."""
    return _utc(kickoff_at, "kickoff_at") - FINAL_MARGIN


def time_left(pass_kind: PassKind, kickoff_at: datetime, now: datetime) -> timedelta:
    """How long a pass has before its deadline: negative once it has passed. ``final`` is held to ``final_deadline``; so are ``first``,
    ``pre`` and the owner's ``request``, because none of them may ever overrun a final. (Their own bound - the next pass - is the
    orchestrator's to apply.) The kind is checked, so that a pass of its own can get another bound later without touching the callers."""
    if pass_kind not in PASS_KINDS:
        raise ValueError(f"unknown pass {pass_kind!r}; known: {PASS_KINDS}")
    return final_deadline(kickoff_at) - _utc(now, "now")


def verdict(pass_kind: PassKind, kickoff_at: datetime, now: datetime, expected: timedelta) -> Verdict:
    """``go`` if a pass that takes ``expected`` and starts at ``now`` ends STRICTLY before its deadline, ``too_late`` if not (ending at T-15
    exactly is already late: the plan says «antes de»). A ``too_late`` pass is not started: the rules' reviewer decides and the metric
    «final sin veredicto antes de T-15» is recorded by the orchestrator."""
    if expected < timedelta(0):
        raise ValueError(f"expected must not be negative, got {expected}")
    return "go" if expected < time_left(pass_kind, kickoff_at, now) else "too_late"


# -- 5. when an arm stops ------------------------------------------------------------------------------------------------------------

INVALID_LIMIT_PERCENT: Final = 3
"""More than this share of an arm's calls of the day ending as an invalid output pauses it (plan, section 23; the same 3 % as the service
objective and the alert of section 32)."""
MIN_CALLS_FOR_RATE: Final = 34
"""The invalid-output rule is silent below this many calls in the day. 34 is the fewest for which ONE invalid output is not already above
3 % (1 of 34 is 2.94 %, 1 of 33 is 3.03 %): a single bad answer never pauses a day. That matters because a paused day leaves the arm's
analysis whole and counts against Gate B's «días excluidos». With a lower floor (20, say) an arm that makes 20 to 33 calls a day, and whose
true invalid rate is 1.5 % - half the objective - would lose 26 to 39 % of its days to one stray output (1 - 0.985^n, calls independent).
Two invalid outputs pause the day when there are 66 calls or fewer; three, when there are 99 or fewer."""
PAUSE_INVALID: Final = "invalid_over_3pct"
PAUSE_CIRCUIT: Final = "circuit_open"
PAUSE_ENVELOPE: Final = "envelope_spent"
PAUSE_REASONS: Final = (PAUSE_INVALID, PAUSE_CIRCUIT, PAUSE_ENVELOPE)


def arm_pause(*, invalid: int, calls: int, circuit_state: str, envelope_left_usd: Decimal) -> list[str]:
    """Why an experiment's arm does not run (plan, section 23): the reason codes in the order of the plan's sentence, or an empty list
    when it runs. ``invalid`` and ``calls`` are the arm's invalid outputs and calls of the day; ``circuit_state`` is the state of the
    circuit of the arm's model; ``envelope_left_usd`` what is left of the arm's envelope.

      * ``invalid_over_3pct``  at least ``MIN_CALLS_FOR_RATE`` calls and strictly more than 3 % of them invalid.
      * ``circuit_open``       the circuit is ``open``. ``half_open`` does not pause: the arm's next call is the probe that closes the
                               circuit, and pausing there would leave nobody to send it.
      * ``envelope_spent``     nothing is left (zero or less).

    A pause is not lifted by this function: a paused day leaves the analysis whole, and that bookkeeping is the orchestrator's."""
    if calls < 0 or invalid < 0 or invalid > calls:
        raise ValueError(f"invalid ({invalid}) must be between 0 and calls ({calls})")
    if circuit_state not in CIRCUIT_STATES:
        raise ValueError(f"unknown circuit state {circuit_state!r}; known: {CIRCUIT_STATES}")
    if not envelope_left_usd.is_finite():
        raise ValueError(f"the envelope must be a finite amount, got {envelope_left_usd}")
    reasons: list[str] = []
    if calls >= MIN_CALLS_FOR_RATE and invalid * 100 > INVALID_LIMIT_PERCENT * calls:
        reasons.append(PAUSE_INVALID)
    if circuit_state == "open":
        reasons.append(PAUSE_CIRCUIT)
    if envelope_left_usd <= 0:
        reasons.append(PAUSE_ENVELOPE)
    return reasons

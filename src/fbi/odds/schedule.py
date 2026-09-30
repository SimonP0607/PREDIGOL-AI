"""What to capture, and when.

The cadence is dictated by the provider, not by preference:

  * ``/odds`` is refreshed **every 3 hours** and keeps a 7-day history. Polling a
    fixture more often than that returns identical rows and burns quota, so the
    windows are expressed in minutes-to-kickoff and none may be below 180.
  * ``/odds/live`` is the only endpoint that shows a price near kick-off. The
    provider publishes a fixture there roughly between T-15 and T-5.

What comes out of ``/odds/live`` at T-12 is a NEAR-CLOSE snapshot. It is not the
closing line, and this module never calls it one. Until an empirical study shows
those two coincide, the distance to kick-off travels with the price so any later
analysis can judge it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

CaptureKind = Literal["prematch", "near_close"]

NEAR_CLOSE_TOLERANCE_MINUTES = 3
"""How far either side of the near-close window a fixture still counts as due.

The provider publishes /odds/live only between T-15 and T-5 and keeps NO history, so a
window that closes unobserved is gone for good. With the default window at T-12 this
tolerance makes the opportunity T-15..T-9 - six minutes wide - and that width is what the
worker's tick interval has to be no coarser than. apps.worker.scheduler derives its
default from this constant for exactly that reason; a 15-minute tick against a 6-minute
window hits it 40% of the time."""


@dataclass(frozen=True, slots=True)
class CaptureTask:
    provider_fixture_id: int
    kickoff_at: datetime
    kind: CaptureKind
    window_minutes: int
    minutes_to_ko: int

    @property
    def window_key(self) -> str:
        """Stable identity of "this fixture, this scheduled window".

        Idempotency hangs off this: a second run inside the same window is a
        no-op instead of a duplicate call.
        """
        return f"{self.provider_fixture_id}:{self.kind}:{self.window_minutes}"


@dataclass(frozen=True, slots=True)
class ScheduledFixture:
    provider_fixture_id: int
    kickoff_at: datetime
    status_short: str = "NS"


class CapturePlanner:
    def __init__(
        self,
        prematch_windows: Sequence[int],
        near_close_window: int,
        tolerance_minutes: int,
    ) -> None:
        windows = sorted({int(w) for w in prematch_windows}, reverse=True)
        if not windows:
            raise ValueError("at least one prematch window is required")
        if min(windows) < 180:
            raise ValueError(
                "a prematch window below 180 minutes cannot observe anything new: "
                "/odds refreshes every 3 hours"
            )
        if not 5 <= near_close_window <= 15:
            raise ValueError(
                "the near-close window must sit inside the T-15..T-5 band the "
                "provider publishes /odds/live in"
            )
        self._windows = windows
        self._near_close = near_close_window
        self._tolerance = tolerance_minutes

    def plan(
        self, fixtures: Iterable[ScheduledFixture], *, at: datetime, already_done: set[str] | None = None
    ) -> list[CaptureTask]:
        """Tasks due right now, nearest to kick-off first.

        ``already_done`` holds the window keys captured earlier; passing it is
        what makes repeated runs idempotent.
        """
        done = already_done or set()
        tasks: list[CaptureTask] = []

        for fixture in fixtures:
            if fixture.status_short not in {"NS", "TBD", "PST"}:
                continue
            minutes = (fixture.kickoff_at - at).total_seconds() / 60.0
            if minutes < 0:
                continue

            if abs(minutes - self._near_close) <= NEAR_CLOSE_TOLERANCE_MINUTES:
                task = CaptureTask(
                    provider_fixture_id=fixture.provider_fixture_id,
                    kickoff_at=fixture.kickoff_at,
                    kind="near_close",
                    window_minutes=self._near_close,
                    minutes_to_ko=int(minutes),
                )
                if task.window_key not in done:
                    tasks.append(task)
                continue

            window = self._due_window(minutes)
            if window is None:
                continue
            task = CaptureTask(
                provider_fixture_id=fixture.provider_fixture_id,
                kickoff_at=fixture.kickoff_at,
                kind="prematch",
                window_minutes=window,
                minutes_to_ko=int(minutes),
            )
            if task.window_key not in done:
                tasks.append(task)

        tasks.sort(key=lambda t: t.minutes_to_ko)
        return tasks

    def _due_window(self, minutes: float) -> int | None:
        """The tightest configured window this fixture currently sits in.

        The band runs FORWARD from the nominal instant: window W is due while
        ``W - tolerance <= minutes_to_kickoff <= W``, which in wall-clock time
        is ``kickoff - W`` through ``kickoff - W + tolerance``. Both readings
        matter and they are easy to confuse, so:

          * ``next_run_at`` returns ``kickoff - W``, the instant the band
            OPENS. A scheduler that sleeps until then and wakes up to
            ``tolerance`` minutes late still captures the window - which is
            the whole point of having a tolerance.
          * a snapshot that satisfies window W is therefore never FURTHER from
            kick-off than W claims. Overshooting the other way would file a
            price taken at T-765 under the "720" window, and this project does
            not label a price as closer to kick-off than it really was.

        The band used to run backwards - ``W <= minutes <= W + tolerance`` -
        which made ``next_run_at`` point at the instant the band CLOSED, so a
        tick even one minute late lost the window entirely.
        """
        for window in sorted(self._windows):
            if window - self._tolerance <= minutes <= window:
                return window
        return None

    def covered_keys(self, observations: Iterable[tuple[int, str, int]]) -> set[str]:
        """Map stored snapshots back onto the windows they satisfy.

        ``observations`` are (provider_fixture_id, source, minutes_to_ko) rows
        from the database. A snapshot at T-1400 satisfies the 1440 window when
        the tolerance is 45; one at T-1200 satisfies nothing, and neither does
        one at T-1460, taken before the window opened. Coverage is therefore
        derived from what was really captured, never from a separate
        bookkeeping table that can drift out of step with it.

        Same band as ``_due_window`` and deliberately so: if these two ever
        disagree, a window is either captured twice or never marked done.
        """
        keys: set[str] = set()
        for fixture_id, source, minutes in observations:
            if source == "live":
                if abs(minutes - self._near_close) <= NEAR_CLOSE_TOLERANCE_MINUTES:
                    keys.add(f"{fixture_id}:near_close:{self._near_close}")
                continue
            for window in sorted(self._windows):  # same order as _due_window
                if window - self._tolerance <= minutes <= window:
                    keys.add(f"{fixture_id}:prematch:{window}")
                    break
        return keys

    def next_run_at(self, fixtures: Iterable[ScheduledFixture], *, at: datetime) -> datetime | None:
        """When the scheduler should next wake up. None = nothing pending.

        This is the instant a window OPENS, so waking here and running late by
        up to the tolerance still captures it. See ``_due_window``.
        """
        candidates: list[datetime] = []
        for fixture in fixtures:
            for window in (*self._windows, self._near_close):
                moment = fixture.kickoff_at - timedelta(minutes=window)
                if moment > at:
                    candidates.append(moment)
        return min(candidates) if candidates else None


@dataclass(frozen=True, slots=True)
class PlanCheck:
    """What a plan must satisfy before a single request is spent."""

    issues: list[str]
    estimated_requests: int

    @property
    def ok(self) -> bool:
        return not self.issues


def validate_plan(
    tasks: Sequence[CaptureTask],
    *,
    at: datetime,
    budget_remaining: int,
    known_fixture_ids: set[int] | None = None,
) -> PlanCheck:
    """Refuse a plan that would capture nonsense.

    Checked: duplicate window keys, fixtures already kicked off, timestamps
    that make no sense, fixtures the database does not know, and the number
    of requests against the budget that is actually left.
    """
    issues: list[str] = []
    keys = [t.window_key for t in tasks]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        issues.append(f"duplicate windows: {dupes[:5]}")
    for t in tasks:
        if t.kickoff_at <= at:
            issues.append(f"{t.window_key}: kick-off {t.kickoff_at.isoformat()} is not in the future")
        if t.kickoff_at.tzinfo is None:
            issues.append(f"{t.window_key}: naive kick-off timestamp")
        if t.minutes_to_ko < 0 or t.minutes_to_ko > 60 * 24 * 14:
            issues.append(f"{t.window_key}: implausible minutes_to_ko {t.minutes_to_ko}")
        if known_fixture_ids is not None and t.provider_fixture_id not in known_fixture_ids:
            issues.append(f"{t.window_key}: fixture unknown to the database")
    # /odds for one fixture is one page in practice; /odds/live is one call.
    estimated = len(tasks)
    if estimated > budget_remaining:
        issues.append(f"plan needs ~{estimated} requests but only {budget_remaining} remain in the budget")
    return PlanCheck(issues=issues, estimated_requests=estimated)

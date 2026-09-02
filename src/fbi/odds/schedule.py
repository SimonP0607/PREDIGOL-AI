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

            if abs(minutes - self._near_close) <= 3:
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

        A window is 'due' from its nominal time until ``tolerance`` minutes
        later, so a scheduler tick that lands late still captures it once.
        """
        for window in sorted(self._windows):
            if window <= minutes <= window + self._tolerance:
                return window
        return None

    def covered_keys(self, observations: Iterable[tuple[int, str, int]]) -> set[str]:
        """Map stored snapshots back onto the windows they satisfy.

        ``observations`` are (provider_fixture_id, source, minutes_to_ko) rows
        from the database. A snapshot at T-1421 satisfies the 1440 window when
        the tolerance is 45; it satisfies nothing when it is 200 minutes late.
        Coverage is therefore derived from what was really captured, never from
        a separate bookkeeping table that can drift out of step with it.
        """
        keys: set[str] = set()
        for fixture_id, source, minutes in observations:
            if source == "live":
                if abs(minutes - self._near_close) <= 3:
                    keys.add(f"{fixture_id}:near_close:{self._near_close}")
                continue
            for window in self._windows:
                if window <= minutes <= window + self._tolerance:
                    keys.add(f"{fixture_id}:prematch:{window}")
                    break
        return keys

    def next_run_at(self, fixtures: Iterable[ScheduledFixture], *, at: datetime) -> datetime | None:
        """When the scheduler should next wake up. None = nothing pending."""
        candidates: list[datetime] = []
        for fixture in fixtures:
            for window in (*self._windows, self._near_close):
                moment = fixture.kickoff_at - timedelta(minutes=window)
                if moment > at:
                    candidates.append(moment)
        return min(candidates) if candidates else None

"""How often to ask /odds/live. Chosen from the provider's own refresh rate.

MEASURED 2026-10-01: THE PROVIDER REFRESHES ONCE EVERY ~31 SECONDS
------------------------------------------------------------------
12 unfiltered calls, 10.4 s apart, 7 live fixtures. Per consecutive pair, how
many fixtures changed their ``update`` stamp and how many prices moved::

    gap     update changed   prices moved
    10.6s        7/7          387/1682
    10.4s        0/7            0/1682
    10.4s        0/7            0/1682
    10.4s        7/7          518/1673
    10.4s        0/7            0/1678
    10.4s        0/7            0/1678
    10.4s        7/7          303/1353
    10.4s        0/7            0/1362
    10.4s        0/7            0/1362
    10.4s        7/7          334/1350
    10.4s        0/7            0/1356

Exactly one real refresh every three ticks, and ``update`` moves for ALL seven
fixtures at once or for none: the provider sweeps its whole live book on a
single ~31 s cycle. 5 distinct payloads came back from 12 calls, so **58% of a
10-second poll is spent on bytes we already hold** - our own payload dedup
recognised them (cached=True) but the request was still gone.

So POLL_FLOOR_SECONDS is 30, and it is a floor on information, not a budget
compromise: asking faster cannot return anything new. The user's instruction not
to poll every 5 seconds turns out to be a lower bound the provider enforces
anyway - at 5 s, five of every six calls would be waste.

What the same measurement says about the data being worth capturing: 9.2% of
prices moved per 10 s tick, about 27% per refresh cycle, and suspensions churn
heavily (96 values thawed in one cycle). Markets appear and vanish between
cycles - one cycle dropped 325 values as a match wound down. 20.9% of prices
never moved across the whole two minutes, so a snapshot is far from redundant.

WHAT A TICK COSTS, AND WHY NOTHING-LIVE MUST COST NOTHING
---------------------------------------------------------
One unfiltered call covers every live fixture, so the cost is per TICK, not per
match: 30 s ticks are 2,880 calls per 24 h of continuous football - under 5% of
the 60,000/day guard - whether two matches are live or ninety. The number that
actually decides the daily spend is therefore how many hours have any football
at all, which is why ``decide`` returns SKIP when nothing can be in play and
says when to look again. That check reads core.fixtures and costs no request.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

POLL_FLOOR_SECONDS = 30
"""Measured provider refresh period. Below this a call cannot return new prices."""

IDLE_RECHECK_SECONDS = 300
"""How long to wait before re-reading the fixture list when nothing is in play.
Costs no provider request - it only re-asks the database."""

MAX_MATCH_MINUTES = 150
"""A fixture is treated as possibly in play from kick-off until this long after:
90 regulation + half-time + stoppages + a generous delay allowance. Extra time
and penalties are covered by the live payload itself once it appears."""

DEFAULT_LIVE_DAILY_BUDGET = 12_000
"""Of the 60,000/day internal guard. At the 30 s floor this buys 100 hours of
live football a day, far more than exists, so the budget is not the binding
constraint - but it is enforced so a provider change cannot drain the day."""


@dataclass(frozen=True, slots=True)
class CadenceDecision:
    """What the next live tick should do."""

    should_capture: bool
    next_in_seconds: int
    reason: str
    fixtures_possibly_live: int
    budget_floor_seconds: int = POLL_FLOOR_SECONDS

    @property
    def interval(self) -> timedelta:
        return timedelta(seconds=self.next_in_seconds)


def possibly_live_count(
    kickoffs: list[datetime], *, at: datetime, max_match_minutes: int = MAX_MATCH_MINUTES
) -> int:
    """Fixtures that could be on the pitch right now, from kick-off times alone.

    Deliberately errs wide: a fixture counted here that turns out not to be live
    costs one call that returns an empty list, while one missed loses prices that
    /odds/live will never serve again.
    """
    window = timedelta(minutes=max_match_minutes)
    return sum(1 for ko in kickoffs if at - window <= ko <= at)


def seconds_until_next_kickoff(kickoffs: list[datetime], *, at: datetime) -> int | None:
    ahead = [ko for ko in kickoffs if ko > at]
    if not ahead:
        return None
    return max(1, math.floor((min(ahead) - at).total_seconds()))


def decide(
    *,
    kickoffs: list[datetime],
    at: datetime,
    live_calls_today: int,
    live_daily_budget: int = DEFAULT_LIVE_DAILY_BUDGET,
    remaining_quota: int,
    last_capture_at: datetime | None = None,
    floor_seconds: int = POLL_FLOOR_SECONDS,
    idle_recheck_seconds: int = IDLE_RECHECK_SECONDS,
    max_match_minutes: int = MAX_MATCH_MINUTES,
) -> CadenceDecision:
    """Whether to call /odds/live now, and when to come back.

    The order of the guards is the priority the platform runs on: live capture
    comes before everything, but not before the quota that protects it.
    """
    in_play = possibly_live_count(kickoffs, at=at, max_match_minutes=max_match_minutes)

    if remaining_quota <= 0:
        return CadenceDecision(
            False, idle_recheck_seconds, "daily quota exhausted", in_play
        )

    live_left = live_daily_budget - live_calls_today
    if live_left <= 0:
        return CadenceDecision(
            False,
            idle_recheck_seconds,
            f"live budget spent ({live_calls_today}/{live_daily_budget})",
            in_play,
        )

    if in_play == 0:
        # Nothing on the pitch: do not spend a call to be told so. Come back when
        # the next match starts, or at the idle re-check, whichever is sooner.
        until_ko = seconds_until_next_kickoff(kickoffs, at=at)
        wait = (
            min(idle_recheck_seconds, until_ko)
            if until_ko is not None
            else idle_recheck_seconds
        )
        reason = (
            f"nothing in play; next kick-off in {until_ko}s"
            if until_ko is not None
            else "nothing in play and nothing scheduled"
        )
        return CadenceDecision(False, max(1, wait), reason, 0)

    # The rest of today's live football, bounded by the longest match still to
    # finish. The budget must cover it at the chosen interval.
    horizon = _live_seconds_remaining(
        kickoffs, at=at, max_match_minutes=max_match_minutes
    )
    budget_floor = (
        max(floor_seconds, math.ceil(horizon / live_left)) if live_left > 0 else floor_seconds
    )
    interval = max(floor_seconds, budget_floor)

    # The scheduler fires at the floor; the interval may be longer than that.
    # Elapsed time since the last capture is read from the record of captures
    # themselves, so a restarted worker resumes the right cadence instead of
    # starting a fresh clock and over-spending.
    if last_capture_at is not None:
        since = (at - last_capture_at).total_seconds()
        if since < interval:
            wait = max(1, math.ceil(interval - since))
            return CadenceDecision(
                False,
                wait,
                f"{in_play} possibly live; {since:.0f}s since last capture, "
                f"interval is {interval}s",
                in_play,
                budget_floor,
            )

    if interval == floor_seconds:
        reason = f"{in_play} possibly live; at the measured {floor_seconds}s refresh floor"
    else:
        reason = (
            f"{in_play} possibly live; stretched to {interval}s so {live_left} calls "
            f"cover {horizon}s of remaining football"
        )
    return CadenceDecision(True, interval, reason, in_play, budget_floor)


def _live_seconds_remaining(
    kickoffs: list[datetime], *, at: datetime, max_match_minutes: int
) -> int:
    """Seconds from now until the last of today's known matches could still be on.

    Only fixtures already known to the database count. A fixture added later
    shortens nobody's budget retroactively, because the interval is recomputed
    every tick.
    """
    window = timedelta(minutes=max_match_minutes)
    ends = [ko + window for ko in kickoffs if ko + window > at]
    if not ends:
        return 0
    return max(0, math.ceil((max(ends) - at).total_seconds()))

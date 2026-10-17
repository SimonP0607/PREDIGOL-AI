"""One answer to "what state is this match in?", for every layer.

API-Football reports a match's state as a short code (``fixture.status.short``). Before this
module each layer answered the question on its own - the stored group said SUSP was
"postponed" while the live board showed it in play, the web showed a cancelled match as
"Final", an awarded one as over and a postponed one as nothing at all - so the same match
could be live on one screen and finished on another. Every layer now reads this table:

  code  provider's group  phase        in play  bets on it
  ----  ----------------  -----------  -------  ------------------------------------------
  TBD   Scheduled         scheduled    no       wait
  NS    Scheduled         scheduled    no       wait
  1H    In Play           live         yes      wait
  HT    In Play           live         yes      wait (break)
  2H    In Play           live         yes      wait
  ET    In Play           live         yes      wait (90' already decided, extra time playing)
  BT    In Play           live         yes      wait (break before extra time)
  P     In Play           live         yes      wait (shoot-out)
  LIVE  In Play           live         yes      wait (the provider does not say which part)
  INT   In Play           live         yes      wait (interrupted, "should resume in a few minutes")
  SUSP  In Play           suspended    yes      a human: "may be rescheduled another day"
  FT    Finished          finished     no       settle on the 90' score
  AET   Finished          finished     no       settle on the 90' score
  PEN   Finished          finished     no       settle on the 90' score
  PST   Postponed         postponed    no       a human: books void after a delay of their own
  CANC  Cancelled         cancelled    no       void
  ABD   Abandoned         abandoned    no       a human: some markets may already be decided
  AWD   Not Played        not_played   no       a human: the awarded result is not the played one
  WO    Not Played        not_played   no       a human: walkover

TIME GUARD. A stored code can be stale - we stop following a match three hours after
kick-off, and lower leagues have no live coverage at all. Two cases are not believed:

  * still TBD/NS fifteen minutes after kick-off: not "about to start" but AWAITING;
  * still in play three and a half hours after kick-off (longer than any match with
    extra time and penalties lasts): not "live" but AWAITING.

SUSP is not timed out: a suspended match stays suspended until the provider says
otherwise.

The STORED group (``core.fixtures.status_group``) keeps its historical mapping
(``STORED_GROUP``) on purpose: features, backtests and audits read it, and changing what
it means would change what the models were trained on. The phase refines it; it does not
rewrite it. The web mirrors this table in src/product/matches/state.ts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class Phase(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    SUSPENDED = "suspended"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    NOT_PLAYED = "not_played"
    AWAITING = "awaiting"
    UNKNOWN = "unknown"


SCHEDULED = frozenset({"TBD", "NS"})
IN_PLAY = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"})
"""The provider's "In Play" group, SUSP included: a suspended match has kicked off and is not over."""
BREAKS = frozenset({"HT", "BT", "INT", "SUSP"})
"""In play, but the ball is not rolling."""
FINISHED = frozenset({"FT", "AET", "PEN"})
AFTER_EXTRA_TIME = frozenset({"AET", "PEN"})
POSTPONED = frozenset({"PST"})
CANCELLED = frozenset({"CANC"})
ABANDONED = frozenset({"ABD"})
NOT_PLAYED = frozenset({"AWD", "WO"})
OVER = FINISHED | CANCELLED | ABANDONED | NOT_PLAYED
"""Nothing more will be played under this fixture (an abandoned match may be replayed, as a new state)."""
ENDED = OVER | POSTPONED | frozenset({"SUSP"})
"""Codes after which a bet on the match can be decided or must go to a human: what triggers settlement."""
KNOWN = SCHEDULED | IN_PLAY | FINISHED | POSTPONED | CANCELLED | ABANDONED | NOT_PLAYED

START_GRACE = timedelta(minutes=15)
"""Still scheduled this long after kick-off: the start is late or our copy is stale."""
LIVE_STALE_AFTER = timedelta(hours=3, minutes=30)
"""Still in play this long after kick-off: longer than any match with extra time and penalties."""

STORED_GROUP: dict[str, str] = {
    "TBD": "scheduled", "NS": "scheduled",
    "1H": "live", "HT": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live", "INT": "live",
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "SUSP": "postponed", "PST": "postponed",
    "CANC": "cancelled", "ABD": "cancelled", "AWD": "cancelled", "WO": "cancelled",
}
"""What ``core.fixtures.status_group`` stores for each code - unchanged since it was first written (see above)."""

_PHASE: dict[str, Phase] = {
    **dict.fromkeys(SCHEDULED, Phase.SCHEDULED),
    **dict.fromkeys(IN_PLAY - {"SUSP"}, Phase.LIVE),
    "SUSP": Phase.SUSPENDED,
    **dict.fromkeys(FINISHED, Phase.FINISHED),
    **dict.fromkeys(POSTPONED, Phase.POSTPONED),
    **dict.fromkeys(CANCELLED, Phase.CANCELLED),
    **dict.fromkeys(ABANDONED, Phase.ABANDONED),
    **dict.fromkeys(NOT_PLAYED, Phase.NOT_PLAYED),
}


def code(status_short: str | None) -> str:
    """The provider spells "CANC" and "Canc"; one spelling here."""
    return (status_short or "").strip().upper()


def is_scheduled(status_short: str | None) -> bool:
    return code(status_short) in SCHEDULED


def is_live(status_short: str | None) -> bool:
    """In play, breaks and suspensions included: kicked off and not over."""
    return code(status_short) in IN_PLAY


def is_finished(status_short: str | None) -> bool:
    """Played to the end (FT, AET, PEN): the 90-minute score settles bets."""
    return code(status_short) in FINISHED


def is_over(status_short: str | None) -> bool:
    return code(status_short) in OVER


def phase_of(status_short: str | None) -> Phase:
    """The phase the code alone says, without the time guard."""
    return _PHASE.get(code(status_short), Phase.UNKNOWN)


def phase(status_short: str | None, kickoff_at: datetime | None, at: datetime) -> Phase:
    """The phase a reader should see at ``at``: the code, unless it is too old to believe."""
    p = phase_of(status_short)
    if kickoff_at is None:
        return p
    if p is Phase.SCHEDULED and at >= kickoff_at + START_GRACE:
        return Phase.AWAITING
    if p is Phase.LIVE and at >= kickoff_at + LIVE_STALE_AFTER:
        return Phase.AWAITING
    return p


def stored_group(status_short: str | None, default: str = "scheduled") -> str:
    return STORED_GROUP.get(code(status_short), default)


class ResultWait(StrEnum):
    """Why a match that should be over still has no result (REVIEW, 11 Oct 2026: "partidos empezados que siguen
    esperando resultado"). Each case has a different owner, so a screen names it instead of one vague "awaiting":

    * PROVIDER_PENDING - we read the provider after the match should have ended and it still says the match is not
      over (Rayo Vallecano - Athletic, 10 Oct: "INT" 17 h after kick-off). Nothing for us to fix; we keep asking.
    * PROVIDER_SILENT - the provider has not told us anything about the match since before it should have ended.
      The repair job asks again, oldest read first.
    * JOBS_STALLED - as SILENT, but our own result jobs have not run lately: the fault is ours.
    * PROVIDER_CONFLICT - the provider contradicts itself: a finished match with a kick-off still ahead
      (Sporting JAX - Birmingham Legion, 10 Oct: FT, then moved to 14 Oct).
    * RESULT_MISSING - the provider says the match finished and we have no score stored: an internal check.
    """

    PROVIDER_PENDING = "provider_pending"
    PROVIDER_SILENT = "provider_silent"
    JOBS_STALLED = "jobs_stalled"
    PROVIDER_CONFLICT = "provider_conflict"
    RESULT_MISSING = "result_missing"


EXPECTED_END = timedelta(hours=2, minutes=15)
"""Kick-off to the end of a match with stoppage time and the break: a provider read after this saw a match that
should already be over."""


def result_wait(status_short: str | None, kickoff_at: datetime | None, *, provider_read_at: datetime | None,
                has_result: bool, at: datetime, jobs_healthy: bool = True) -> ResultWait | None:
    """None when nothing is wrong (not started, being played, over with its result, or over in a way that has no
    result - postponed, cancelled, abandoned, awarded, suspended: the provider said so and the screen says so)."""
    if kickoff_at is None:
        return None
    c = code(status_short)
    if c in FINISHED:
        if kickoff_at > at:
            return ResultWait.PROVIDER_CONFLICT
        return None if has_result else ResultWait.RESULT_MISSING
    if phase(status_short, kickoff_at, at) is not Phase.AWAITING:
        return None
    if provider_read_at is not None and provider_read_at >= kickoff_at + EXPECTED_END:
        return ResultWait.PROVIDER_PENDING
    return ResultWait.PROVIDER_SILENT if jobs_healthy else ResultWait.JOBS_STALLED

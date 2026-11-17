"""The settlement rule of a player's count (IA-130, AD-E04): ``player_count_ft@v1``. Pure: no database, no clock.

A price ``"<name> - N"`` of a player's shots (240, 241) or shots on target (269) wins when his count of the match reaches N. The count is
his line of ``core.fixture_player_stats`` (``shots_total``, ``shots_on``) - the same figures ``player-engine-v2`` is fitted on - over
the 90 minutes and stoppage time the provider's statistics cover (extra time is not separated by the provider: a match that went to
extra time is not settled, ``None``, as the corners are). The match itself follows ``settle-v4`` (``fbi.picks.settlement``): cancelled
is void, not finished waits, and 72 hours after kick-off without a result is void.

THE CASES OF MINUTES (all tested):

    did not play: not on the sheet, or on it with 0 minutes ......... VOID (the house voids a prop of a man who does not play; the
                                                                     engine prices it with ``p_over_if_plays``)
    played (a starter or from the bench), any minutes > 0 ........... WIN when count >= N, else LOSS - one minute is playing
    played but his figure is NULL (the provider did not report it) .. None: no settlement, never a loss
    the match has no player statistics at all ....................... None
    the match went to extra time ..................................... None

``None`` is never a loss and never a void: the selection leaves the sample with its reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fbi.picks.settlement import FINISHED, VOID_AFTER, VOID_STATUSES, Status

RULE: Final = "player_count_ft@v1"
STATS: Final = {"player_shots": "shots", "player_shots_on": "shots_on"}
"""family -> count of ``fbi.players.families.STATS``."""
EXTRA_TIME: Final = frozenset({"AET", "PEN"})

NOT_PLAYED: Final = "no_jugo"
NO_FIGURE: Final = "sin_estadistica"
NO_STATS: Final = "partido_sin_estadisticas"
EXTRA: Final = "prorroga"
WAITING: Final = "partido_pendiente"
MATCH_VOID: Final = "partido_anulado"
SETTLED: Final = "liquidada"


@dataclass(frozen=True, slots=True)
class PlayerLine:
    """What the statistics say of one man in one match (None: he is on no sheet and in no statistics of it)."""

    on_sheet: bool
    minutes: int | None
    count: int | None


@dataclass(frozen=True, slots=True)
class Outcome:
    status: Status | None
    basis: str


def settle(*, at_least: int, match_status: str, kickoff_at: datetime, at: datetime, has_stats: bool,
           line: PlayerLine | None) -> Outcome:
    """The outcome of «he reaches at least ``at_least``» for one man. Pure."""
    if at_least < 1:
        raise ValueError("a player count settles on at least 1")
    status = match_status.strip().upper()
    if status in VOID_STATUSES:
        return Outcome(Status.VOID, MATCH_VOID)
    if status not in FINISHED:
        if at >= kickoff_at + VOID_AFTER:
            return Outcome(Status.VOID, MATCH_VOID)
        return Outcome(None, WAITING)
    if status in EXTRA_TIME:
        return Outcome(None, EXTRA)
    if not has_stats:
        return Outcome(None, NO_STATS)
    if line is None or not line.on_sheet or not line.minutes:
        return Outcome(Status.VOID, NOT_PLAYED)
    if line.count is None:
        return Outcome(None, NO_FIGURE)
    return Outcome(Status.WIN if line.count >= at_least else Status.LOSS, SETTLED)

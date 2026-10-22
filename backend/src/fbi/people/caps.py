"""A player and his national team (plan F3): which sides count, what the matchday squad and the statistics say he did, and the
profile the dossier of a match reads.

A cap here is an entry in the matchday squad of a SENIOR national team in a finished match - starter or bench - with what we can say
of whether he played: ``appeared`` is true (minutes on the pitch), false (he stayed on the bench) or ``None`` (the statistics of the
match have not arrived, so it cannot be said yet). The statistics come hours after the final whistle, so a match is revisited
until they do. A youth side (``Spain U21``), an Olympic one, is a national team of the provider's but not the player's senior
career: its matches are not caps.

Pure: the database reads and writes are in ``fbi.people.player_history``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

VERSION: Final = "caps-v1"

_YOUTH: Final = re.compile(r"(?:^|[\s(])(?:U[\s-]?(?:1\d|2[0-3])|Under[\s-]?(?:1\d|2[0-3])|Olympics?)(?:$|[\s)])", re.IGNORECASE)


def is_youth(name: str) -> bool:
    """A youth or Olympic side by its name (``Spain U21``, ``Brazil U-20``, ``Argentina Under 23``, ``Japan Olympic``)."""
    return _YOUTH.search(name) is not None


def is_senior_national(name: str, is_national: bool | None) -> bool:
    """A side whose matches are caps: classified as a national team (None: not known to be one) and not a youth side."""
    return is_national is True and not is_youth(name)


def appeared(*, is_starter: bool, finished: bool, has_stats: bool, minutes: int | None) -> bool | None:
    """Did he play? ``has_stats``: the match has player statistics for his side at all (an unused substitute is listed in them
    with no minutes, so a side with statistics and no minutes for him means he did not play)."""
    if not finished:
        return None
    if is_starter:
        return minutes != 0
    if not has_stats:
        return None
    return minutes is not None and minutes > 0


@dataclass(frozen=True, slots=True)
class Cap:
    fixture_id: int
    kickoff: datetime
    team_id: int
    is_starter: bool
    appeared: bool | None
    minutes: int | None


@dataclass(frozen=True, slots=True)
class Profile:
    """What a player did for his national side before a moment."""

    squads: int
    """Matchday squads he was in (played or not)."""
    caps: int
    """Matches he played."""
    starts: int
    minutes: int
    unknown: int
    """Squads of which we cannot say yet whether he played."""
    last_squad: datetime | None
    last_cap: datetime | None


def profile(caps: Sequence[Cap], *, before: datetime) -> Profile:
    """The record of a player strictly before ``before`` (the kick-off of the match the dossier is for)."""
    past = [c for c in caps if c.kickoff < before]
    played = [c for c in past if c.appeared is True]
    return Profile(
        squads=len(past), caps=len(played), starts=sum(1 for c in played if c.is_starter),
        minutes=sum(c.minutes or 0 for c in played), unknown=sum(1 for c in past if c.appeared is None),
        last_squad=max((c.kickoff for c in past), default=None), last_cap=max((c.kickoff for c in played), default=None))

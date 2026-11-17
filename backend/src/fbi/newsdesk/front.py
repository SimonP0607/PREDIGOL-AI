"""The front page's order (IA-120, plan piece AD-G06): ``front-v1``. Pure: it orders what it is given and reads nothing.

From the stories of the window (active, with at least one article that may be shown), four blocks, each empty when nothing fits it -
never filled with something else:

* **Destacadas** (``featured``): every story, by its level first (oficial, dos orígenes, declaración, un medio, rumor; none last), then by
  the nearness of the next match of what it names (a match within ``UPCOMING``, the nearest first), then the newest; the key breaks ties.
* **Principal** (``lead``): the first featured story whose level is ``oficial``, ``dos_origenes`` or ``declaracion`` - a single outlet
  or a rumour never leads. None when no story qualifies. It is not repeated in ``featured``.
* **Última hora** (``breaking``): the stories with an article whose publication date came as structured data (feed, sitemap, page
  metadata) within ``BREAKING``, newest first - a story without a structured date never enters, whatever its level.
* **Tus equipos** (``mine``): the stories that name one of the reader's favourite teams or players, newest first; without favourites the
  block says so (``sin_favoritos``) - the suggested ones do not fill it.

Every list is cut at its own maximum. The same input gives the same order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

VERSION: Final = "front-v1"
LEVEL_RANK: Final[dict[str | None, int]] = {"oficial": 0, "dos_origenes": 1, "declaracion": 2, "un_medio": 3, "rumor": 4, None: 5}
LEADS: Final = frozenset({"oficial", "dos_origenes", "declaracion"})
UPCOMING: Final = timedelta(hours=72)
BREAKING: Final = timedelta(hours=24)
WINDOW: Final = timedelta(hours=72)
"""The stories the front page reads: a version written in the last 72 hours."""
MAX_FEATURED: Final = 12
MAX_BREAKING: Final = 5
MAX_MINE: Final = 6


@dataclass(frozen=True, slots=True)
class Candidate:
    """One story as the order sees it."""

    key: str
    level: str | None
    latest_at: datetime
    structured_at: datetime | None
    entities: frozenset[tuple[str, int]]


@dataclass(frozen=True, slots=True)
class Followed:
    """The reader's favourites, as PrediGol's ids (read only from ``customer.favorites``)."""

    teams: frozenset[int] = frozenset()
    players: frozenset[int] = frozenset()

    @property
    def any(self) -> bool:
        return bool(self.teams or self.players)


@dataclass(frozen=True, slots=True)
class Front:
    lead: str | None
    featured: list[str] = field(default_factory=list)
    breaking: list[str] = field(default_factory=list)
    mine: list[str] | None = None
    """None: the reader follows nothing."""


def next_match(c: Candidate, upcoming: Mapping[int, datetime], now: datetime) -> datetime | None:
    """The nearest kick-off within ``UPCOMING`` of a team the story names (``upcoming``: team -> its next kick-off)."""
    kicks = [upcoming[i] for t, i in c.entities if t == "team" and i in upcoming and now <= upcoming[i] <= now + UPCOMING]
    return min(kicks, default=None)


def featured_key(c: Candidate, upcoming: Mapping[int, datetime], now: datetime) -> tuple[int, float, float, str]:
    nxt = next_match(c, upcoming, now)
    nearness = (nxt - now).total_seconds() if nxt is not None else float("inf")
    return LEVEL_RANK.get(c.level, 5), nearness, -c.latest_at.timestamp(), c.key


def order(candidates: Sequence[Candidate], *, now: datetime, followed: Followed, upcoming: Mapping[int, datetime]) -> Front:
    ranked = sorted(candidates, key=lambda c: featured_key(c, upcoming, now))
    lead = next((c.key for c in ranked if c.level in LEADS), None)
    featured = [c.key for c in ranked if c.key != lead][:MAX_FEATURED]
    newest = sorted(candidates, key=lambda c: (-c.latest_at.timestamp(), c.key))
    breaking = [c.key for c in sorted((c for c in candidates if c.structured_at is not None and now - BREAKING <= c.structured_at <= now),
                                      key=lambda c: (-(c.structured_at or now).timestamp(), c.key))][:MAX_BREAKING]
    mine = None
    if followed.any:
        wanted = {("team", t) for t in followed.teams} | {("player", p) for p in followed.players}
        mine = [c.key for c in newest if c.entities & wanted][:MAX_MINE]
    return Front(lead, featured, breaking, mine)


__all__ = ["BREAKING", "LEADS", "LEVEL_RANK", "MAX_BREAKING", "MAX_FEATURED", "MAX_MINE", "UPCOMING", "VERSION", "WINDOW", "Candidate",
           "Followed", "Front", "featured_key", "next_match", "order"]

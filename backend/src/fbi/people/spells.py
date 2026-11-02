"""Where a player was, and since when: the rules that fold what the provider said into streaks at a club (plan F3, ``spells-v1``).

The provider gives no history of a player's clubs, only pieces of one: the transfers it lists (a date, the club he left, the club he
joined), the matches whose squad sheet carries him (a club, a day) and the squad lists it published (a club, the first and the
last day we saw him in one). This module folds those pieces, in time order, into the STREAKS he spent at each club. It is a pure
function: it reads no database, and the order of its input does not matter.

ONE ROW PER STREAK
------------------
A player who goes A, B, A has three streaks, not two: the second A is not the first one reopened. Streaks do not overlap and they are
dated like this: ``valid_from`` is the first day he is there, ``valid_to`` the first day he is NOT (the day the next streak starts or
the day a transfer says he left), ``None`` when he is still there as far as we know and, for ``valid_from``, when we do not know the
start (the oldest transfer names the club he came from and nothing says since when: that streak is history to show, not an answer
to "where was he on day D"). "Where was he on day D" is ``valid_from <= D < valid_to``.

WHAT COUNTS, AND HOW MUCH
-------------------------
Four kinds of event act on a day, in this order, and the last word of the day is the state at its end:

``squad``   a squad list carried him (our first and last sighting). The weakest evidence, WEIGHT ZERO: it fills a gap - it opens a
            streak when nothing else says where he is, and it confirms the club he is already known to be at - but it never takes
            him out of a club that a transfer or a match put him at, because a squad list lags behind (a player who left stays in
            it for weeks, a parent club keeps the players it lent out) and one stale list would make the history flap.
``left``    a transfer says he left the club that day: closes his streak there. Nothing else changes when he is known to be
            elsewhere; when it is the very first thing we know of him, it dates a streak whose start nobody gave (``valid_from``
            ``None``).
``joined``  a transfer says he joined the club that day: closes the streak he is in and opens one (``source`` transfer, the
            provider's wording of the move in ``via``: Loan, Free, a fee, Return from loan).
``seen``    he was in the matchday squad (starter or bench) of a match of the club that day: the hardest evidence there is. It
            opens a streak when he was not at that club (``source`` lineup) - so a loan that nobody recorded, or a return from
            one, shows as soon as he plays - and counts one more match when he was.

THE EDGES
---------
* **A paper transfer is not a streak.** A club joined and left on the same day (bought and lent out at once, a hop through a
  holding club) is skipped, whatever the order of its two records; any streak that still starts and ends on the same day (two clubs
  on the same day, a transfer contradicted the same day by a match for a third club) is dropped and counted as a PHANTOM.
* **A match on the day he left is the old club's.** A transfer dated the day of his last match for the club neither undoes the move
  nor loses the match: it counts for the club he left, and the new streak starts that day.
* **The same club on both sides of a phantom is one streak** (A, a club of one day, A).
* **A transfer with no date cannot be placed in time** and is left out by the reader of the database, not here.

Because every rule looks only at the events up to the day in question, ``club_at(build(events), D)`` is the same as
``club_at(build(events up to D), D)``: reading the history as of a past day never uses anything that happened later, which is what
the dossier of a match needs (``tests/unit/test_spells.py`` checks it on random histories). What the transfers say about the past
is taken as a fact about the past - a transfer we learned of after the match but dated before it is used for that match - and the
dossier says so.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

VERSION: Final = "spells-v1"

KINDS: Final = ("squad", "left", "joined", "seen")
"""The kinds of event, in the order in which they act within one day (the later one has the last word)."""
SOURCES: Final = ("transfer", "lineup", "squad")
"""How a streak began to be known: a transfer dated it, a match put him there, or a squad list carried him."""

_RANK: Final = {kind: n for n, kind in enumerate(KINDS)}


@dataclass(frozen=True, slots=True)
class Event:
    """One piece of evidence about one player: on ``day`` something put him at (or took him from) ``club``."""

    day: date
    kind: str
    club: int
    """The provider's id of the club (a national team is not a club: the reader of the database never gives one)."""
    ref: int = 0
    """The match of a ``seen`` event (what is counted once even if two sources both carry it); 0 for the others."""
    via: str | None = None
    """The provider's wording of the move (``Loan``, ``Free``, ``€ 80M``, ``Return from loan``) for ``left`` and ``joined``."""

    def __post_init__(self) -> None:
        if self.kind not in _RANK:
            raise ValueError(f"unknown kind of event: {self.kind!r}")


@dataclass(frozen=True, slots=True)
class Spell:
    """One streak at one club."""

    club: int
    valid_from: date | None
    """The first day he is there; ``None``: we do not know since when."""
    valid_to: date | None
    """The first day he is NOT there (exclusive); ``None``: still there as far as we know."""
    source: str
    """How the streak began to be known (``SOURCES``)."""
    matches: int
    """Matches in the matchday squad (starters and bench) that the events place in the streak."""
    last_evidence: date
    """The latest day something says he was there: the freshness of the streak (an open one with an old day is probably over)."""
    via: str | None = None


@dataclass(frozen=True, slots=True)
class Build:
    spells: list[Spell]
    phantoms: int
    """Streaks of zero days that were dropped (see THE EDGES)."""


@dataclass(slots=True)
class _Run:
    club: int
    start: date | None
    source: str
    last: date
    via: str | None = None
    end: date | None = None
    matches: set[int] = field(default_factory=set)


def _order(event: Event) -> tuple[date, int, int, int, str]:
    return event.day, _RANK[event.kind], event.club, event.ref, event.via or ""


def _open(runs: list[_Run]) -> _Run | None:
    return runs[-1] if runs and runs[-1].end is None else None


def _closed(runs: list[_Run]) -> _Run | None:
    """The streak that ended last (the one before the open streak, or the last one when none is open)."""
    if runs and runs[-1].end is None:
        return runs[-2] if len(runs) >= 2 else None
    return runs[-1] if runs else None


def _squad(runs: list[_Run], event: Event) -> None:
    cur = _open(runs)
    if cur is None:
        runs.append(_Run(event.club, event.day, "squad", event.day))
    elif cur.club == event.club:
        cur.last = max(cur.last, event.day)


def _left(runs: list[_Run], event: Event) -> None:
    cur = _open(runs)
    if cur is not None and cur.club == event.club:
        cur.end = event.day
    elif cur is None and not runs:
        runs.append(_Run(event.club, None, "transfer", event.day, end=event.day))


def _joined(runs: list[_Run], event: Event) -> None:
    # a club he is already at is not a special case: the streak that opens here is the same club's, and build() joins the two
    cur = _open(runs)
    if cur is not None:
        cur.end = event.day
    runs.append(_Run(event.club, event.day, "transfer", event.day, via=event.via))


def _seen(runs: list[_Run], event: Event) -> None:
    cur = _open(runs)
    if cur is not None and cur.club == event.club:
        cur.matches.add(event.ref)
        cur.last = max(cur.last, event.day)
        return
    left = _closed(runs)
    if left is not None and left.club == event.club and left.end == event.day:
        left.matches.add(event.ref)
        left.last = max(left.last, event.day)
        return
    if cur is not None:
        cur.end = event.day
    runs.append(_Run(event.club, event.day, "lineup", event.day, matches={event.ref}))


_ACT: Final = {"squad": _squad, "left": _left, "joined": _joined, "seen": _seen}


def _fold(events: Iterable[Event]) -> list[_Run]:
    runs: list[_Run] = []
    for _, group in itertools.groupby(sorted(set(events), key=_order), key=lambda e: e.day):
        today = list(group)
        paper = {e.club for e in today if e.kind == "joined"} & {e.club for e in today if e.kind == "left"}
        for event in today:
            if event.kind in ("joined", "left") and event.club in paper:
                continue
            _ACT[event.kind](runs, event)
    return runs


def _spell(run: _Run) -> Spell:
    return Spell(club=run.club, valid_from=run.start, valid_to=run.end, source=run.source, matches=len(run.matches),
                 last_evidence=run.last, via=run.via)


def build(events: Iterable[Event]) -> Build:
    """The streaks of one player, oldest first, from every event we have about him."""
    runs = _fold(events)
    kept = [r for r in runs if r.start != r.end]
    merged: list[_Run] = []
    for run in kept:
        before = merged[-1] if merged else None
        if before is not None and before.club == run.club and before.end is not None and before.end == run.start:
            before.end = run.end
            before.last = max(before.last, run.last)
            before.matches |= run.matches
        else:
            merged.append(run)
    return Build(spells=[_spell(r) for r in merged], phantoms=len(runs) - len(kept))


def club_at(spells: Sequence[Spell], day: date) -> Spell | None:
    """The streak he was in on ``day`` (``valid_from <= day < valid_to``), or None when nothing says where he was.

    A streak with no known start says where he was BEFORE a day that only a later record revealed, so it is history to show and
    never an answer to "where was he on day D": using it would read the past with what came after."""
    for spell in spells:
        if spell.valid_from is not None and spell.valid_from <= day and (spell.valid_to is None or day < spell.valid_to):
            return spell
    return None

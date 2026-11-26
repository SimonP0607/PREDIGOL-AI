"""Who gets researched first: by the importance of the match, not by whether a pick candidate exists (plan RP-5.4, finding H11): ``research-order-v1``.

The order in force puts first the matches that have a selection eligible to be a pick, so the research goes where the money might be and not where
the readers are: 205 requests went unserved for lack of allowance and the Primera A of Colombia had 0 of 6 matches searched. The plan fixes four
levels (section 10) and this module is their rule and the order they give, pure, plus the measure that says what the new order would do with the
days already kept:

    A ... the owner's priority competitions (groups 1-3 of ``fbi.intel.day_priority``) and, by decision D2, the Primera A of Colombia:
          researched 48 h before, 24 h before and the day of the match
    B ... the rest of the tier 1 and 2 leagues and the matches somebody follows: the first pass of the day
    C ... the other followed competitions with a market: only on a novelty from the provider or on a request
    D ... no market and no followers: not researched; the text says it only has the provider's data

Inside a level the order is the novelty, then the followers (an aggregate and anonymous count: it raises a match a level, it never makes content
different for a user), and only then the pick candidate, as a tie-break inside the allowance that is left. The module changes nothing by itself: the
cycle keeps its order until the owner turns the switch on after the simulation (``scripts/ia_research_order.py``), and the budgets and caps stay.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from fbi.ai.day import DayFixture
from fbi.intel import day_priority

VERSION: Final = "research-order-v1"

LEVELS: Final = ("A", "B", "C", "D")
EXTRA_A: Final[Mapping[int, str]] = {239: "Primera A (Colombia)"}
"""Decision D2: the owner's list plus the Primera A of Colombia (API-Football league 239)."""
A_GROUPS: Final = (1, 2, 3)
ANTICIPATION: Final = (("t48", timedelta(hours=48)), ("t24", timedelta(hours=24)))
"""Level A is researched 48 and 24 hours before the match, besides the day of the match."""


@dataclass(frozen=True, slots=True)
class Ranked:
    fixture: DayFixture
    level: str


def level_of(fixture: DayFixture, *, followers: int = 0) -> str:
    """The level of a match (pure). A match of a priority competition is A with or without a market: the research does not wait for a price."""
    league = fixture.provider_league_id
    if (league in EXTRA_A) or day_priority.group_of(league) in A_GROUPS:
        return "A"
    if fixture.tier in (1, 2) or followers > 0:
        return "B"
    if fixture.has_market:
        return "C"
    return "D"


def order_key(r: Ranked, *, novelty: int = 0, followers: int = 0, candidate: float = 0.0) -> tuple[int, int, int, float, datetime]:
    """Level, then novelty, then followers, then the pick candidate as the tie-break, then the kick-off (all ascending: the bigger the better)."""
    return (LEVELS.index(r.level), -novelty, -followers, -candidate, r.fixture.kickoff_at)


def ranked(fixtures: Iterable[DayFixture], *, followers: Mapping[int, int] | None = None) -> list[Ranked]:
    f = followers or {}
    return [Ranked(x, level_of(x, followers=f.get(x.fixture_id, 0))) for x in fixtures]


def due_anticipation(level: str, kickoff: datetime, *, at: datetime, done: Collection[str]) -> str | None:
    """The anticipated pass level A needs now (``t48`` from 48 h before, ``t24`` from 24 h before), None for the other levels or when it was done."""
    if level != "A" or kickoff <= at:
        return None
    lead = kickoff - at
    due = [name for name, span in ANTICIPATION if lead <= span and name not in done]
    return due[-1] if due else None


def choose(fixtures: Sequence[Ranked], slots: int, *, novelty: Mapping[int, int] | None = None, followers: Mapping[int, int] | None = None,
           candidates: Mapping[int, float] | None = None) -> list[Ranked]:
    """The ``slots`` matches the new order would research, level D never."""
    n, f, c = novelty or {}, followers or {}, candidates or {}
    eligible = [r for r in fixtures if r.level != "D"]
    eligible.sort(key=lambda r: order_key(r, novelty=n.get(r.fixture.fixture_id, 0), followers=f.get(r.fixture.fixture_id, 0),
                                          candidate=c.get(r.fixture.fixture_id, 0.0)))
    return eligible[:max(slots, 0)]


def coverage(fixtures: Sequence[Ranked], searched: Collection[int], *, chosen: Collection[int] | None = None) -> dict[str, dict[str, int]]:
    """Per level: how many matches, how many were searched (what happened) and, if ``chosen`` is given, how many the new order would search."""
    total, done, would = Counter[str](), Counter[str](), Counter[str]()
    for r in fixtures:
        total[r.level] += 1
        if r.fixture.fixture_id in searched:
            done[r.level] += 1
        if chosen is not None and r.fixture.fixture_id in chosen:
            would[r.level] += 1
    out = {lv: {"matches": total[lv], "searched": done[lv]} for lv in LEVELS}
    if chosen is not None:
        for lv in LEVELS:
            out[lv]["would_search"] = would[lv]
    return out


def level_a_unsearched(fixtures: Sequence[Ranked], chosen: Collection[int]) -> list[int]:
    """The level A matches the new order leaves out: the plan's acceptance is that there is none."""
    return [r.fixture.fixture_id for r in fixtures if r.level == "A" and r.fixture.fixture_id not in chosen]


__all__ = [
    "ANTICIPATION",
    "A_GROUPS",
    "EXTRA_A",
    "LEVELS",
    "VERSION",
    "Ranked",
    "choose",
    "coverage",
    "due_anticipation",
    "level_a_unsearched",
    "level_of",
    "order_key",
    "ranked",
]

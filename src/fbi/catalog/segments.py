"""Which kind of football a competition is: the segments every audit and model splits by.

Club and national-team football, men's and women's, senior and youth do not share a
base rate, a home advantage or a market's efficiency, so a number pooled across them
describes none of them. ``core.competitions`` already said club or national team
(``entity_scope``) and league, cup or continental (``competition_type``); gender and
age group were nowhere, so a women's league and a U21 tournament were averaged in
with the Premier League.

The provider has no field for either. Both are read from the competition's name, by
the patterns below - the same ones the database uses for its generated columns
(migration 0048), so Python and SQL cannot classify one competition two ways. A
pattern is narrow on purpose: "W" alone or "II" would catch reserve sides and Welsh
leagues, so they are not patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

WOMEN_PATTERN = (r"(women|woman|femin|fémin|frauen|damen|ladies|\mwsl\M|damallsvenskan|nwsl|"
                 r"femenil|femenina|feminino|kvinner|naiset|\mliga f\M)")
"""PostgreSQL syntax (\\m, \\M are its word boundaries); see ``_py``."""

YOUTH_PATTERN = r"(\mu-?(1[3-9]|2[0-3])\M|youth|junior|primavera|juvenil|\msub-?(1[3-9]|2[0-3])\M)"


def _py(pattern: str) -> re.Pattern[str]:
    """The SQL pattern for Python's ``re``: \\m and \\M are both \\b there."""
    return re.compile(pattern.replace(r"\m", r"\b").replace(r"\M", r"\b"), re.IGNORECASE)


_WOMEN = _py(WOMEN_PATTERN)
_YOUTH = _py(YOUTH_PATTERN)


class Segment(StrEnum):
    TOP_LEAGUE = "top_league"
    OTHER_LEAGUE = "other_league"
    DOMESTIC_CUP = "domestic_cup"
    CONTINENTAL_CLUB = "continental_club"
    CLUB_FRIENDLY = "club_friendly"
    NATIONAL_TEAM = "national_team"
    WOMEN = "women"
    YOUTH = "youth"


FRIENDLY_PATTERN = re.compile(r"\bfriendl", re.IGNORECASE)


def gender_of(name: str) -> str:
    return "women" if _WOMEN.search(name or "") else "men"


def age_group_of(name: str) -> str:
    return "youth" if _YOUTH.search(name or "") else "senior"


@dataclass(frozen=True, slots=True)
class CompetitionFacts:
    name: str
    competition_type: str | None
    entity_scope: str | None
    tier: int | None


def segment_of(c: CompetitionFacts) -> Segment:
    """One segment per competition, the most specific that applies.

    Youth and women first: a women's continental cup is a women's competition before
    it is a continental one, for every purpose a segment serves.
    """
    if age_group_of(c.name) == "youth":
        return Segment.YOUTH
    if gender_of(c.name) == "women":
        return Segment.WOMEN
    if c.entity_scope == "national_team":
        return Segment.NATIONAL_TEAM
    if FRIENDLY_PATTERN.search(c.name):
        return Segment.CLUB_FRIENDLY
    if c.competition_type == "continental":
        return Segment.CONTINENTAL_CLUB
    if c.competition_type == "domestic_cup":
        return Segment.DOMESTIC_CUP
    if c.competition_type == "domestic_league" and c.tier == 1:
        return Segment.TOP_LEAGUE
    return Segment.OTHER_LEAGUE

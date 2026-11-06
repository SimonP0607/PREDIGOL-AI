"""The competitions the owner wants first among the PICKS DEL DÍA (``comp-priority-v1``, BE-003, 5 Nov 2026).

An ORDERING, nothing else. It decides which of the selections that are ALREADY eligible for PICK_DEL_DIA (approved by
the ten filters and the edge gate, decided at most 30 minutes ago, more than 10 minutes from kick-off) the day takes
first. It never touches a probability, an EV, an edge, a threshold, a calibrator, a gate, a state, a score or a stake,
and it never makes a selection eligible or ineligible.

THE RULE (``order_for_day``, applied by ``fbi.intel.decision.select_day`` under ``daily-set-v7``): the eligible
selections are sorted by (priority group, best PrediGol Pick Score first); then the day's existing caps run over that
order unchanged - at most five picks, one per match, at most two per competition. So a lower-scored selection of a
priority competition is taken before a higher-scored one of a lower group, and within a group the score decides as
before. When none of the eligible selections is in a priority competition, every one is in group 4 and the order is
exactly the previous one (score first; Python's sort is stable, so ties keep their earlier order too).

The day is chosen incrementally and frozen when chosen (a selection that becomes eligible later only fills the slots
left), so the priority orders each pass of ``select_day``; it never takes back a pick already frozen.

THE GROUPS (API-Football league ids, ``core.competitions.provider_league_id``):

    1  the UEFA Champions League and the top league of England, Spain, Germany, France, Portugal - and Italy's Serie A,
       which the repository already treats as a top league (tier 1 of ``config/migration.yaml``)
    2  continental and intercontinental club cups
    3  national-team tournaments and the World Cup qualifiers of every confederation
    4  everything else

The ids come from ``config/migration.yaml`` (where the provider's own names are recorded), except 7 (Asian Cup), 29
(World Cup qualifiers, Africa) and 33 (World Cup qualifiers, Oceania), which no file of the repository lists yet: they
follow the provider's numbering and are listed so the priority holds the day they are tracked. An id in this list that
is not tracked simply never appears among the candidates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

VERSION = "comp-priority-v1"
DEFAULT_GROUP = 4
"""The group of every competition not listed below."""

GROUPS: Mapping[int, Mapping[int, str]] = {
    1: {
        2: "UEFA Champions League",
        39: "Premier League (England)",
        140: "La Liga (Spain)",
        78: "Bundesliga (Germany)",
        61: "Ligue 1 (France)",
        94: "Primeira Liga (Portugal)",
        135: "Serie A (Italy)",
    },
    2: {
        3: "UEFA Europa League",
        848: "UEFA Europa Conference League",
        13: "CONMEBOL Libertadores",
        11: "CONMEBOL Sudamericana",
        16: "CONCACAF Champions League / Champions Cup",
        17: "AFC Champions League Elite",
        15: "FIFA Club World Cup",
        1168: "FIFA Intercontinental Cup",
    },
    3: {
        1: "World Cup",
        4: "Euro Championship",
        9: "Copa America",
        22: "CONCACAF Gold Cup",
        7: "AFC Asian Cup",
        5: "UEFA Nations League",
        536: "CONCACAF Nations League",
        29: "World Cup - Qualification Africa",
        30: "World Cup - Qualification Asia",
        31: "World Cup - Qualification CONCACAF",
        32: "World Cup - Qualification Europe",
        33: "World Cup - Qualification Oceania",
        34: "World Cup - Qualification South America",
        37: "World Cup - Qualification Intercontinental Play-offs",
    },
}

_GROUP_OF: dict[int, int] = {league: group for group, leagues in GROUPS.items() for league in leagues}


def group_of(provider_league_id: int | None) -> int:
    """The priority group of a competition by its API-Football league id: 1, 2, 3, or 4 for every other one."""
    if provider_league_id is None:
        return DEFAULT_GROUP
    return _GROUP_OF.get(int(provider_league_id), DEFAULT_GROUP)


def order_for_day[T](items: Iterable[T], *, league: Callable[[T], int | None],
                     score: Callable[[T], float]) -> list[T]:
    """The eligible selections in the order the day takes them: priority group first, then the best score. Stable, so
    equal keys keep the order they came in. It only orders: what it returns is what it was given."""
    return sorted(items, key=lambda x: (group_of(league(x)), -score(x)))

"""Does a coded regulation, applied to the results, give back the table the provider published? (IA-072, plan piece AD-B01.)

The closing test of AD-B01: for every coded competition, the final table of the last closed season rebuilt from its results
with ``fbi.competitions.ranking`` must match ``core.standings`` place by place. This module is the pure comparison; the
command ``scripts/ia_rules.py reconstruct`` feeds it from the database (read-only) and the unit tests from frozen seasons.

A place counts as:

* ``same``: the team the rules put there is the provider's;
* ``shared``: the rules leave the teams level (a criterion the results cannot settle: fair play, lots, a play-off never needed)
  and the provider ordered them some way inside the same places - not a disagreement, and said apart;
* ``different``: the rules and the provider disagree. Each one comes with whether the provider's row itself (points, played,
  goals) differs from what the results add up to - then it is the data, not the rule, that disagrees.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fbi.competitions.ranking import Result, Table, rank
from fbi.competitions.rules import CompetitionRules, Phase

VERSION: Final = "reconstruction-v1"
PLAYED_STATUSES: Final = frozenset({"FT", "AET", "PEN", "AWD", "WO"})


@dataclass(frozen=True, slots=True)
class Match:
    round: str | None
    status: str | None
    home: int
    away: int
    home_goals: int | None
    away_goals: int | None

    @property
    def played(self) -> bool:
        return (self.status or "") in PLAYED_STATUSES and self.home_goals is not None and self.away_goals is not None


@dataclass(frozen=True, slots=True)
class ProviderRow:
    rank: int
    team: int
    points: int
    played: int
    goals_for: int
    goals_against: int


@dataclass(frozen=True, slots=True)
class Comparison:
    phase: str
    group: str
    teams: int
    same: int
    shared: int
    different: tuple[dict[str, Any], ...]
    data_differs: tuple[int, ...]
    """Teams whose provider row (points, played, goals) is not what the results add up to."""
    complete: bool

    @property
    def identical(self) -> bool:
        return not self.different

    def as_json(self) -> dict[str, Any]:
        return {"phase": self.phase, "group": self.group, "teams": self.teams, "same": self.same, "shared": self.shared,
                "different": list(self.different), "data_differs": list(self.data_differs), "complete": self.complete,
                "version": VERSION}


def results_of(phase: Phase, matches: Iterable[Match]) -> tuple[list[Result], int, int]:
    """The played results of a phase, and how many of its matches there are and how many were played."""
    mine = [m for m in matches if phase.covers(m.round)]
    played = [Result(m.home, m.away, int(m.home_goals or 0), int(m.away_goals or 0)) for m in mine if m.played]
    return played, len(mine), len(played)


def compare(table: Table, provider: Sequence[ProviderRow], *, phase: str, group: str) -> Comparison:
    ours = {p.team: p for p in table.places}
    theirs = sorted(provider, key=lambda r: r.rank)
    same = shared = 0
    different: list[dict[str, Any]] = []
    data: list[int] = []
    for index, row in enumerate(theirs, start=1):
        place = ours.get(row.team)
        if place is None:
            different.append({"position": index, "provider": row.team, "rules": None, "why": "team not in the results"})
            continue
        if (place.row.points, place.row.played, place.row.goals_for, place.row.goals_against) != (
                row.points, row.played, row.goals_for, row.goals_against):
            data.append(row.team)
        at = table.places[index - 1].team if index - 1 < len(table.places) else None
        if at == row.team:
            same += 1
        elif place.shared_with and place.position <= index < place.position + len(place.shared_with) + 1:
            shared += 1
        else:
            different.append({"position": index, "provider": row.team, "rules": at,
                              "rules_position_of_provider_team": place.position, "decided_by": place.decided_by})
    return Comparison(phase=phase, group=group, teams=len(theirs), same=same, shared=shared, different=tuple(different),
                      data_differs=tuple(data), complete=table.complete)


def reconstruct(rules: CompetitionRules, phase_ref: str, matches: Sequence[Match],
                groups: Mapping[str, Sequence[ProviderRow]], *, external: Mapping[str, Mapping[int, float]] | None = None,
                names: Mapping[int, str] | None = None) -> list[Comparison]:
    """Rebuild the table(s) of one phase (``tournament.phase``) from ``matches`` and compare each with the provider's group of
    the same teams (``groups``: provider group label -> its rows). A phase of groups is ranked group by group, each group's
    rows counting all the phase's matches of its teams."""
    _, phase = rules.phase(phase_ref)
    if phase.ranking is None:
        raise ValueError(f"{phase_ref} is a knockout phase: it has no table")
    results, total, played = results_of(phase, matches)
    complete = total > 0 and total == played
    out: list[Comparison] = []
    for label, rows in groups.items():
        members = [r.team for r in rows]
        size = len(members)
        table = rank(results, phase.ranking, points=rules.points, complete=complete, legs=phase.legs_between_pair,
                     zones=phase.zones, size=size, external=external, names=names,
                     members=members if phase.format == "groups" or len(groups) > 1 else None)
        out.append(compare(table, rows, phase=phase_ref, group=label))
    return out

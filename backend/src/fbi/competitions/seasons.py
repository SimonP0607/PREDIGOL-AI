"""A whole competition season, read once: its stages, its ties, and which tie each fixture is part of (plan F2).

``fbi.competitions.stages`` reads the words of a round label; ``fbi.competitions.ties`` groups the matches of one
knock-out stage into pairings and says who went through. This module is what puts them together for one competition
season, with no database in it: fixtures in, stages and ties out. ``fbi.competitions.builder`` reads the fixtures from
the database, calls it, and writes what comes back.

The one thing this module adds is the WITNESS the ties need (``ties.build_stage_ties(..., advanced=...)``): for each
team, the last time it played in a round that comes after the stage being read. Only some matches can be a witness:

* those of the same bracket (``stages.bracket_key``): the Apertura's quarter-finals say nothing about the Clausura's;
* knock-out and qualifying rounds other than the one being read and its replays, but never the third-place match or a
  placement match, whose players are the ones who LOST the semi-finals;
* and group or league stages, which come after the qualifying rounds that lead to them.

A cancelled match is no witness. Whether a match comes after the tie is decided by the tie itself (a team's match
only counts if it kicks off after the tie's last leg), because round labels get reused inside one season and a team
that played an earlier round under the same label has not "gone through" anything.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fbi.competitions import stages as stg
from fbi.competitions import ties as tl
from fbi.core import match_state


@dataclass(frozen=True, slots=True)
class SeasonFixture:
    """A fixture of the season with what the stage and tie readers need of it."""

    fixture_id: int
    round: str | None
    home: int
    away: int
    kickoff_at: datetime
    status: str | None = None
    goals_home: int | None = None
    goals_away: int | None = None
    ft_home: int | None = None
    ft_away: int | None = None
    et_home: int | None = None
    et_away: int | None = None
    pen_home: int | None = None
    pen_away: int | None = None
    home_winner: bool | None = None
    away_winner: bool | None = None
    settled_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One stage of the season (a round label without its match day), as stored in ``core.competition_stages``."""

    reading: stg.Reading
    fixtures: int
    first_kickoff_at: datetime
    last_kickoff_at: datetime
    tie_format: tl.StageFormat | None = None
    """How the ties of the stage are played; ``None`` for a stage that has none (a league stage)."""
    tie_reason: str | None = None
    ties: int = 0


@dataclass(frozen=True, slots=True)
class Slot:
    """Where a fixture sits: its stage and, in a knock-out stage, its tie and leg."""

    stage: str
    tie: tuple[str, int, int] | None = None
    """(the stage the tie is built in, the lower team id, the higher team id) - the key of ``Tie``."""
    leg: int | None = None


@dataclass(frozen=True, slots=True)
class SeasonBuild:
    stages: dict[str, StageRecord]
    ties: tuple[tl.Tie, ...]
    slots: dict[int, Slot]
    """Every fixture of the season."""
    dropped: dict[int, str]
    """Fixtures in a knock-out stage that belong to no tie, and why: ``cancelled`` or ``rescheduled``."""

    def tie_of(self, fixture_id: int) -> tl.Tie | None:
        slot = self.slots.get(fixture_id)
        if slot is None or slot.tie is None:
            return None
        stage, low, high = slot.tie
        for t in self.ties:
            if t.stage == stage and t.key == (low, high):
                return t
        return None


def _match(f: SeasonFixture, *, in_replay_stage: bool) -> tl.Match:
    return tl.Match(fixture_id=f.fixture_id, home=f.home, away=f.away, kickoff_at=f.kickoff_at, status=f.status,
                   goals_home=f.goals_home, goals_away=f.goals_away, ft_home=f.ft_home, ft_away=f.ft_away,
                   et_home=f.et_home, et_away=f.et_away, pen_home=f.pen_home, pen_away=f.pen_away,
                   home_winner=f.home_winner, away_winner=f.away_winner, settled_at=f.settled_at,
                   in_replay_stage=in_replay_stage)


def witnesses(base: str, by_stage: dict[str, list[SeasonFixture]],
              readings: dict[str, stg.Reading]) -> dict[int, datetime] | None:
    """For each team, the last time it played in a round that can say whether it went through ``base`` (see the module
    docstring), or ``None`` when no such match exists."""
    bracket = stg.bracket_key(base)
    last: dict[int, datetime] = {}
    for stage, fixtures in by_stage.items():
        reading = readings[stage]
        if reading.base == base:
            continue
        same_bracket = (reading.is_knockout_like and reading.role not in ("third_place", "placement")
                        and stg.bracket_key(stage) == bracket)
        if not (same_bracket or reading.role == "group"):
            continue
        for f in fixtures:
            if match_state.code(f.status) in tl.NEVER_PLAYED:
                continue
            for team in (f.home, f.away):
                if team not in last or f.kickoff_at > last[team]:
                    last[team] = f.kickoff_at
    return last or None


def build_season(fixtures: Sequence[SeasonFixture], *, now: datetime) -> SeasonBuild:
    """The stages and ties of one competition season, and the slot of every fixture in it."""
    by_stage: dict[str, list[SeasonFixture]] = defaultdict(list)
    numbered: dict[str, bool] = defaultdict(bool)
    for f in fixtures:
        stage = stg.stage_of(f.round)
        by_stage[stage].append(f)
        numbered[stage] = numbered[stage] or stg.match_day_of(f.round) is not None
    readings = {stage: stg.classify(stage, numbered=numbered[stage]) for stage in by_stage}

    knockout: dict[str, list[tl.Match]] = defaultdict(list)
    for stage, members in by_stage.items():
        reading = readings[stage]
        if reading.is_knockout_like:
            knockout[reading.base].extend(_match(f, in_replay_stage=reading.replay) for f in members)

    built: dict[str, tl.StageTies] = {}
    ties: list[tl.Tie] = []
    for base, matches in knockout.items():
        result = tl.build_stage_ties(base, matches, now=now, advanced=witnesses(base, by_stage, readings))
        built[base] = result
        ties.extend(result.ties)

    slots: dict[int, Slot] = {}
    dropped: dict[int, str] = {}
    for stage, members in by_stage.items():
        for f in members:
            slots[f.fixture_id] = Slot(stage=stage)
    for t in ties:
        low, high = t.key
        for fixture_id, leg in t.legs:
            slots[fixture_id] = Slot(stage=slots[fixture_id].stage, tie=(t.stage, low, high), leg=leg)
    status_of = {f.fixture_id: f.status for f in fixtures}
    for result in built.values():
        for fixture_id in result.dropped:
            dropped[fixture_id] = ("cancelled" if match_state.code(status_of.get(fixture_id)) in tl.NEVER_PLAYED
                                   else "rescheduled")

    records: dict[str, StageRecord] = {}
    for stage, members in by_stage.items():
        reading = readings[stage]
        of_stage = built.get(reading.base) if reading.is_knockout_like else None
        kicks = [f.kickoff_at for f in members]
        records[stage] = StageRecord(
            reading=reading, fixtures=len(members), first_kickoff_at=min(kicks), last_kickoff_at=max(kicks),
            tie_format=of_stage.format if of_stage is not None else None,
            tie_reason=of_stage.reason if of_stage is not None else None,
            ties=len(of_stage.ties) if of_stage is not None and not reading.replay else 0)
    return SeasonBuild(stages=records, ties=tuple(ties), slots=slots, dropped=dropped)

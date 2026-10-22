"""A match's place in its competition, as it can be said BEFORE the match is played (plan F2).

``core.competition_stages`` and ``core.ties`` store the structure of a competition season - which stage a match belongs to,
which tie, which leg - AND what came out of it: who went through, the aggregate, how it was decided, whether a replay or a third
game turned out to be needed. The second kind of column is post-match data (it includes the result of the very match about to
be played), and nothing that decides, prices or judges a pick before a match may read it.

This module is the only door the pre-match readers (the AI packet, the dossier) have to those tables. It reads

* the STAGE of the fixture - its name, kind, role and round, all of which come from the words of the round label;
* the TIE the fixture is a leg of, only for its format (single, two-legged, replay, series) and the fixture's own leg;
* the OTHER legs of that tie that kicked off earlier, each with the result it had when the question is asked
  (``settled_at <= at``, like every other pre-match reader) - from ``core.fixtures`` and ``core.fixture_results``.

It never reads the winner, the aggregate, the status, the shoot-out, the way a tie was decided, the reason it is unresolved,
the next round's witness - and ``tests/integration/test_competition_context.py`` poisons all of them to prove it. Two more
columns look like structure and are not used either: the stored number of legs of a replay or a series (a replay, or a third
game, exists only because the matches before it did not decide the tie: for the first match that number IS the result), and
the stage's own format and counts (the same, summed over the round). For the first match of such a tie the schedule shows a
single match, and that is what is said.

"Recorded" follows the convention of every reader of ``core.fixture_results``: ``settled_at <= at``, the time the result was first
stored (a later correction of the score keeps that time, so a correction reaches a reader asked about the interval before it -
the revision log has the earlier value; no pre-match reader uses it).

Nothing is assumed about the rules of a competition. The arithmetic below is about the first 90 minutes of the match being
played and the goals of the legs already played; what happens when the aggregate is level - extra time, penalties, away
goals where a competition still applies them - is the competition's rule and is said to be so, never guessed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.competitions import stages as stg
from fbi.competitions import ties as tl
from fbi.core import match_state

VERSION: Final = "phase-v1"
"""The shape of ``Phase.as_json`` (stored in the AI packets): a change to it bumps this."""

NOTE: Final = (
    "Read from the stage of the round and from the legs of the tie that had a recorded result when this was built. "
    "aggregate_before sums the goals of those legs (extra time included, shoot-out excluded); the outlook is about the first "
    "90 minutes of this match, as its home side's goals minus its away side's. What happens when the aggregate is level "
    "(extra time, penalties, away goals) is the competition's own rule and is not assumed here.")

TABLES: Final = ("core.competition_stages", "core.ties", "core.fixtures", "core.fixture_results")
"""What a phase is read from, as the packet lists it among its sources: of ``core.competition_stages`` only the words of the
label, of ``core.ties`` only the format, of the results only those recorded by the moment asked."""

KnownFormat = Literal["single", "two_legged", "replay", "series"]

STAGE_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, f.leg, f.tie_id,
       s.stage, s.kind, s.role, s.round_key, s.is_replay,
       t.format AS tie_format
  FROM core.fixtures f
  JOIN core.competition_stages s ON s.id = f.stage_id
  LEFT JOIN core.ties t ON t.id = f.tie_id
 WHERE f.id = %(fixture)s
"""
"""The one place that names ``core.ties``: its ``format`` and nothing else. ``core.competition_stages`` is read for the words of
the label (stage, kind, role, round_key, is_replay), never for what the build counted over the round."""

EARLIER_LEGS_SQL: Final = """
SELECT g.id, g.leg, g.kickoff_at, g.home_team_id, g.away_team_id, g.status_short,
       r.goals_home, r.goals_away, (r.et_goals_home IS NOT NULL OR r.et_goals_away IS NOT NULL) AS extra_time
  FROM core.fixtures g
  LEFT JOIN core.fixture_results r ON r.fixture_id = g.id AND r.settled_at <= %(at)s
 WHERE g.tie_id = %(tie)s AND g.id <> %(fixture)s AND g.kickoff_at < %(kickoff)s
 ORDER BY g.kickoff_at, g.id
"""
"""The other legs that kicked off before this match, with the result each had at ``at`` (none when it was recorded later)."""


@dataclass(frozen=True, slots=True)
class StageOf:
    """The stage of a fixture: what the words of its round label say (``fbi.competitions.stages``)."""

    name: str
    kind: str
    role: str
    round_key: str | None
    replay: bool = False


@dataclass(frozen=True, slots=True)
class EarlierLeg:
    """Another match of the tie that kicked off before this one: ``goals_home`` / ``goals_away`` are None while no result
    was recorded."""

    fixture_id: int
    leg: int | None
    kickoff_at: datetime
    home_team_id: int
    away_team_id: int
    status: str | None
    goals_home: int | None
    goals_away: int | None
    extra_time: bool = False

    @property
    def recorded(self) -> bool:
        """A result a reader may count: the match was played to a result (or awarded one), and the goals are known."""
        return (match_state.code(self.status) in tl.PLAYED and self.goals_home is not None
                and self.goals_away is not None)


@dataclass(frozen=True, slots=True)
class PreviousLeg:
    """An earlier leg from the point of view of THIS match's home side."""

    fixture_id: int
    leg: int | None
    kickoff_at: datetime
    home_side_was: Literal["home", "away"]
    goals_home_side: int
    goals_away_side: int
    after_extra_time: bool

    def as_json(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "leg": self.leg, "kickoff_at": self.kickoff_at.isoformat(),
                "home_side_was": self.home_side_was, "goals_home_side": self.goals_home_side,
                "goals_away_side": self.goals_away_side, "after_extra_time": self.after_extra_time}


@dataclass(frozen=True, slots=True)
class TieAsOf:
    """The tie this match is a leg of, as it could be seen before the match."""

    format: KnownFormat
    leg: int
    legs: int | None
    """How many matches the tie has: known for a single match and for two legs, not for a series."""
    previous: tuple[PreviousLeg, ...]
    without_result: int
    """Earlier legs with no result recorded at the moment asked."""
    aggregate: tuple[int, int] | None
    """The goals of this match's home side and of its away side in the earlier legs; None when there are none or one of them
    has no result."""
    outlook: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"format": self.format, "leg": self.leg, "legs": self.legs,
                "previous": [p.as_json() for p in self.previous], "previous_without_result": self.without_result,
                "aggregate_before": None if self.aggregate is None else {
                    "home_side": self.aggregate[0], "away_side": self.aggregate[1]},
                "outlook": self.outlook, "note": NOTE}


@dataclass(frozen=True, slots=True)
class Phase:
    """A fixture's stage and, when it is a leg of a tie, the tie as seen before the match."""

    stage: StageOf
    tie: TieAsOf | None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": VERSION, "stage": self.stage.name, "kind": self.stage.kind,
                               "role": self.stage.role, "round_key": self.stage.round_key}
        if self.stage.replay:
            out["replay_stage"] = True
        out["tie"] = None if self.tie is None else self.tie.as_json()
        return out


# ── the label alone ─────────────────────────────────────────────────────────


def reading_of(round_label: str | None) -> stg.Reading | None:
    """What the words of one round label say, without a competition season to read them against: the stage (the label without
    its match day), numbered when the label ends with one."""
    if not round_label or not round_label.strip():
        return None
    return stg.classify(stg.stage_of(round_label), numbered=stg.match_day_of(round_label) is not None)


def coarse_stage(round_label: str | None) -> str:
    """The coarse reading the AI packet has always carried in ``fixture.stage``: final | knockout | group | league |
    unknown - by the one classifier of round labels, not a regular expression of its own."""
    reading = reading_of(round_label)
    if reading is None or reading.kind == "unresolved":
        return "unknown"
    if reading.role == "final":
        return "final"
    if reading.kind in ("knockout", "qualifying"):
        return "knockout"
    return "group" if reading.role == "group" else "league"


# ── the tie, as it could be seen ────────────────────────────────────────────


_FORMATS: Final[dict[str, KnownFormat]] = {"single": "single", "two_legged": "two_legged", "replay": "replay",
                                           "series": "series"}


def known_format(stored: str, leg: int) -> KnownFormat:
    """The format a tie shows before the match. A replay, or the third game of a series, exists only because the matches
    before it did not decide the tie: seen from the first match, the schedule shows a single match."""
    if stored in ("replay", "series") and leg <= 1:
        return "single"
    return _FORMATS.get(stored, "single")


def _legs_of(fmt: KnownFormat) -> int | None:
    return {"single": 1, "two_legged": 2, "replay": 2}.get(fmt)


def previous_legs(home: int, away: int, earlier: Sequence[EarlierLeg]) -> tuple[list[PreviousLeg], int]:
    """The earlier legs that have a result, from the point of view of this match's home side, and how many have none."""
    seen: dict[int, EarlierLeg] = {}
    for leg in earlier:
        seen.setdefault(leg.fixture_id, leg)
    out: list[PreviousLeg] = []
    without = 0
    for leg in sorted(seen.values(), key=lambda x: (x.kickoff_at, x.fixture_id)):
        if not leg.recorded or leg.goals_home is None or leg.goals_away is None:
            without += 1
            continue
        if leg.home_team_id == home and leg.away_team_id == away:
            was: Literal["home", "away"] = "home"
            mine, theirs = leg.goals_home, leg.goals_away
        elif leg.home_team_id == away and leg.away_team_id == home:
            was = "away"
            mine, theirs = leg.goals_away, leg.goals_home
        else:  # not between these two sides: the tie is not what the build said, and nothing is claimed
            without += 1
            continue
        out.append(PreviousLeg(leg.fixture_id, leg.leg, leg.kickoff_at, was, mine, theirs, leg.extra_time))
    return out, without


def second_leg_outlook(lead: int) -> dict[str, Any]:
    """What the first 90 minutes of the second leg do to a two-legged tie, given how far this match's home side leads on
    aggregate (negative: trails). With ``margin`` = its goals minus the away side's in this match, the home side is ahead on
    aggregate when margin > -lead, level when margin == -lead, behind when margin < -lead."""
    return {"kind": "second_leg",
            "home_side_ahead_if_home_margin_at_least": 1 - lead,
            "level_if_home_margin_is": -lead,
            "away_side_ahead_if_home_margin_at_most": -lead - 1,
            "if_level": "competition_rules"}


def tie_as_of(*, home: int, away: int, leg: int, stored_format: str, earlier: Sequence[EarlierLeg]) -> TieAsOf:
    """The tie of a match from the point of view of the moment before it: its format as the schedule showed it, the earlier legs
    that had a result, the aggregate of those and what the match does to it. Pure."""
    fmt = known_format(stored_format, leg)
    previous, without = previous_legs(home, away, earlier)
    aggregate = (sum(p.goals_home_side for p in previous), sum(p.goals_away_side for p in previous)) \
        if previous and not without else None
    outlook: dict[str, Any]
    if fmt == "single":
        outlook = {"kind": "single_match"}
    elif fmt == "two_legged":
        if leg <= 1:
            outlook = {"kind": "first_leg"}
        elif aggregate is None:
            outlook = {"kind": "second_leg", "aggregate": "unknown"}
        else:
            outlook = second_leg_outlook(aggregate[0] - aggregate[1])
    elif fmt == "replay":
        outlook = {"kind": "replay", "decides_the_tie": True}
    else:
        wins_home = sum(1 for p in previous if p.goals_home_side > p.goals_away_side)
        wins_away = sum(1 for p in previous if p.goals_home_side < p.goals_away_side)
        outlook = {"kind": "series", "game": leg, "wins_home_side": wins_home, "wins_away_side": wins_away,
                   "draws": len(previous) - wins_home - wins_away, "complete": without == 0}
    return TieAsOf(format=fmt, leg=leg, legs=_legs_of(fmt), previous=tuple(previous), without_result=without,
                   aggregate=aggregate, outlook=outlook)


# ── from the database ───────────────────────────────────────────────────────


def phase_as_of(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> Phase | None:
    """The stage of a fixture and, when it is a leg of a tie, the tie as seen before the match - from what had been recorded
    at ``at``. None when the fixture has no stored stage (its season was never built)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STAGE_SQL, {"fixture": fixture_id})
        row = cur.fetchone()
        if row is None:
            return None
        stage = StageOf(name=str(row["stage"]), kind=str(row["kind"]), role=str(row["role"]),
                        round_key=None if row["round_key"] is None else str(row["round_key"]),
                        replay=bool(row["is_replay"]))
        if row["tie_id"] is None or row["tie_format"] is None or row["leg"] is None:
            return Phase(stage, None)
        cur.execute(EARLIER_LEGS_SQL, {"fixture": fixture_id, "tie": row["tie_id"], "kickoff": row["kickoff_at"], "at": at})
        earlier = [EarlierLeg(fixture_id=int(r["id"]), leg=None if r["leg"] is None else int(r["leg"]),
                              kickoff_at=r["kickoff_at"], home_team_id=int(r["home_team_id"]),
                              away_team_id=int(r["away_team_id"]), status=r["status_short"],
                              goals_home=None if r["goals_home"] is None else int(r["goals_home"]),
                              goals_away=None if r["goals_away"] is None else int(r["goals_away"]),
                              extra_time=bool(r["extra_time"])) for r in cur.fetchall()]
    tie = tie_as_of(home=int(row["home_team_id"]), away=int(row["away_team_id"]), leg=int(row["leg"]),
                    stored_format=str(row["tie_format"]), earlier=earlier)
    return Phase(stage, tie)

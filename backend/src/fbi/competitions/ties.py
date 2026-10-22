"""Ties: how the matches of a knock-out round group into pairings, and who went through (plan F2).

A round label says WHICH round a match belongs to (``fbi.competitions.stages``); it does not say how many matches a
pairing has. A round of 16 has two legs in the Champions League and one in the Coupe de France; a "Final" has two in a
Bundesliga relegation play-off; an FA Cup round has replays. That is read from the matches themselves, by the one fact
every bracket shares: **a team plays one opponent per round**. So, inside one stage of one competition season:

* the matches between the same two teams are one TIE;
* a tie of one match is ``single``; of two matches with the home and away sides swapped in a round where most ties have
  two, ``two_legged``; of two matches in a round where most ties have one, the second of which belongs to the stage of
  replays or follows a first that ended level, ``replay``; of two or three in a round where some tie has three,
  ``series`` (the MLS Cup's best-of-three);
* a team that appears in two different pairings of one stage is not in a bracket (a mini-league labelled "Playoffs"):
  no tie is built and the stage says so, instead of inventing pairings;
* a cancelled match is not part of any tie, and a postponed match that was scheduled again is its later fixture.

WHO WENT THROUGH comes from the goals, with the rules of the sport and nothing assumed about the competition:

* one match: the goals (extra time included, as the provider's ``goals`` are); level, the penalty shoot-out;
* two legs: the sum of the goals of both legs (the second leg's extra time included); level, the shoot-out if one is
  stored;
* a replay: the winner of the replay; a series: the first side to two wins.

THE PROVIDER'S EXTRA-TIME SCORE CANNOT ALWAYS BE BELIEVED, and one fact of the sport says when. On 22 Oct 2026, of the
2,260 matches stored as decided on penalties, 239 had a different number of goals for each side - and a shoot-out is only
played when the sides are level (the match, or the aggregate of two legs). The provider's ``extratime`` block carries the
running 120-minute score instead of the extra-time goals on about one match in ten, and its ``goals`` is the sum of the
90-minute score and that block, so it counts the first ninety minutes twice (Riga - CSKA Sofia, 19 Jul 2018: 1-0 at 90
minutes, no extra-time goals, shown as 2-0). The 90-minute score is unaffected and is what bets settle on; the goals of
the whole match are not. So a shoot-out, when it is stored, decides the winner whatever the goals say, and the score
the match ended on is chosen among the readings of the provider's three blocks as the one that agrees with the shoot-out
(``score_repaired``); if none does, the score is left unknown (``score_inconsistent_with_shootout``) rather than
published wrong.

When the goals cannot say - level with no shoot-out stored (the provider often keeps "FT" for a match decided on
penalties, and a tie can be decided by seeding or by away goals) - the only honest witness is the next round: the side
that plays on in the same bracket went through. ``advanced`` is that witness (for each team, when it last played in a
later round of the bracket, collected by the caller); it is used to settle exactly those ties, and to CHECK every other
winner (a winner must play on after the tie, a loser must not). Without it the tie stays ``unresolved`` with the reason.
A winner is never guessed, and the away-goals rule is never assumed: where it decided a tie, the next round agrees
with it. A winner the next round contradicts stays the winner on the pitch and says ``contradicted``: those are
administrative decisions (a club thrown out for an ineligible player) or data errors, and an audit lists them.

This module is pure: matches in, ties out. ``fbi.competitions.builder`` reads the database, calls it, and writes
the result.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final, Literal

from fbi.core import match_state

VERSION: Final = "ties-2"
"""The version of the rules below; stored with every tie."""

TieFormat = Literal["single", "two_legged", "replay", "series"]
TieStatus = Literal["scheduled", "in_progress", "decided", "unresolved"]
DecidedBy = Literal["normal_time", "extra_time", "penalties", "aggregate", "away_goals", "tiebreak", "walkover", "series"]
StageFormat = Literal["single", "two_legged", "mixed", "series", "not_a_bracket", "empty"]
WinnerCheck = Literal["confirmed", "contradicted", "unknown"]
Score = tuple[int, int]

AWARDED: Final = frozenset({"AWD", "WO"})
"""Decided off the pitch (a technical loss, a walkover): the provider gives the awarded score as the goals."""
PLAYED: Final = match_state.FINISHED | AWARDED
NEVER_PLAYED: Final = frozenset({"CANC"})
"""A cancelled match is in no tie."""
RESCHEDULABLE: Final = frozenset({"PST", "ABD"})
"""A postponed or abandoned match that appears again, between the same sides in the same order, is the same match."""

TWO_LEGGED_SHARE: Final = 0.5
"""A stage in which at least this share of the pairings have two swapped matches is a two-legged round."""
SETTLED_AFTER_DAYS: Final = 3
"""A round whose last match kicked off this long ago and still lacks a leg is not waiting for it."""
SETTLED_BY_EVIDENCE: Final = frozenset({"level_without_shootout", "level_on_aggregate", "awarded_without_score"})
"""The reasons a tie has no winner that the next round can settle."""


@dataclass(frozen=True, slots=True)
class Match:
    """One fixture of a knock-out stage, as the tie reader needs it. ``goals`` are the provider's total (the 90 minutes
    plus extra time, never the shoot-out); ``ft`` and ``et`` its other two blocks; ``None`` while nothing is known."""

    fixture_id: int
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
    in_replay_stage: bool = False
    """The fixture belongs to the stage of replays of the round it is tied to ("1st Round Replays")."""

    @property
    def played(self) -> bool:
        return (match_state.code(self.status) in PLAYED and self.goals_home is not None
                and self.goals_away is not None)

    @property
    def level(self) -> bool:
        return self.played and self.goals_home == self.goals_away

    @property
    def awarded_unscored(self) -> bool:
        """Decided off the pitch with no score stored (a walkover: the provider names no goals). Nobody can say from the
        match alone who went through."""
        return match_state.code(self.status) in AWARDED and (self.goals_home is None or self.goals_away is None)

    @property
    def goes_to_penalties(self) -> bool:
        """A shoot-out was played: the provider says so, or a shoot-out score is stored."""
        return match_state.code(self.status) == "PEN" or _shootout(self) is not None

    def goals_of(self, team: int) -> int | None:
        """The goals (the provider's total) a side scored here, whichever side of the match it was."""
        return self.goals_home if team == self.home else self.goals_away if team == self.away else None


@dataclass(frozen=True, slots=True)
class Tie:
    stage: str
    team_a: int
    """The home side of the first match."""
    team_b: int
    format: TieFormat
    status: TieStatus
    legs: tuple[tuple[int, int], ...]
    """(fixture id, leg number) in the order played."""
    played: int
    aggregate_a: int | None = None
    aggregate_b: int | None = None
    winner: int | None = None
    decided_by: DecidedBy | None = None
    reason: str | None = None
    decided_at: datetime | None = None
    shootout: tuple[int, int] | None = None
    """The shoot-out score as (team A, team B) when the tie went to penalties and the score is stored."""
    check: WinnerCheck = "unknown"
    """Whether a later round agrees with the winner."""
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> tuple[int, int]:
        return (min(self.team_a, self.team_b), max(self.team_a, self.team_b))

    @property
    def fixture_ids(self) -> tuple[int, ...]:
        return tuple(f for f, _ in self.legs)

    @property
    def loser(self) -> int | None:
        if self.winner is None:
            return None
        return self.team_b if self.winner == self.team_a else self.team_a


@dataclass(frozen=True, slots=True)
class StageTies:
    format: StageFormat
    ties: tuple[Tie, ...]
    reason: str | None = None
    """Why the stage has no ties (``not_a_bracket``)."""
    dropped: tuple[int, ...] = ()
    """Fixtures of the stage that belong to no tie: cancelled, or postponed and scheduled again."""


# ── the score a match ended on ──────────────────────────────────────────────


def _shootout(m: Match) -> Score | None:
    if m.pen_home is None or m.pen_away is None or m.pen_home == m.pen_away:
        return None
    return (m.pen_home, m.pen_away)


def _readings(m: Match) -> list[tuple[str, Score]]:
    """The scores the match may have ended on (extra time in, shoot-out out), the provider's own total first, then the
    readings of its other blocks that differ from it: the extra-time block taken as the running score (possible only
    when it is no lower than the 90 minutes), and the 90 minutes alone (extra time without goals)."""
    if m.goals_home is None or m.goals_away is None:
        return []
    total = (m.goals_home, m.goals_away)
    out: list[tuple[str, Score]] = [("goals", total)]
    if m.ft_home is None or m.ft_away is None:
        return out
    if (m.et_home is not None and m.et_away is not None and m.et_home >= m.ft_home and m.et_away >= m.ft_away
            and (m.et_home, m.et_away) != total):
        out.append(("extratime_total", (m.et_home, m.et_away)))
    if (m.ft_home, m.ft_away) not in [s for _, s in out]:
        out.append(("fulltime", (m.ft_home, m.ft_away)))
    return out


def _pick(m: Match, ok: Callable[[Score], bool]) -> tuple[Score | None, str | None]:
    """The first reading of the match's score that a rule of the sport accepts, and which reading it was."""
    for name, score in _readings(m):
        if ok(score):
            return score, name
    return None, None


def _side(m: Match, score: Score, team: int) -> int:
    """The goals ``team`` scored in match ``m`` when the match ended on ``score`` (home, away)."""
    return score[0] if team == m.home else score[1]


@dataclass(frozen=True, slots=True)
class Outcome:
    """How ONE match answers "who went through" (a single tie, a replay, a game of a series)."""

    winner: int | None
    how: DecidedBy | None
    shootout: Score | None
    """(home, away) of the match."""
    score: Score | None
    """The score the match ended on (home, away), extra time in and shoot-out out; ``None`` if it cannot be known."""
    flags: tuple[str, ...] = ()
    reason: str | None = None


def _flagged_winner(m: Match) -> int | None:
    """The provider's own winner flag, which it sets after a shoot-out as well: used only when it is unambiguous."""
    if m.home_winner and not m.away_winner:
        return m.home
    if m.away_winner and not m.home_winner:
        return m.away
    return None


def single_outcome(m: Match) -> Outcome:
    """The outcome of ONE match played to a result: the goals, or the shoot-out. Nothing is returned for a match that
    is not played, and a match that ended level with nothing to say who went through has no winner."""
    if m.awarded_unscored:
        return Outcome(None, None, None, None, reason="awarded_without_score")
    if not m.played or m.goals_home is None or m.goals_away is None:
        return Outcome(None, None, None, None)
    code = match_state.code(m.status)
    shoot = _shootout(m)
    flags: list[str] = []
    if m.goes_to_penalties:
        # the sides were level when the shoot-out started: that is a rule of the sport, not a reading of the data
        score, name = _pick(m, lambda s: s[0] == s[1])
        if score is None:
            flags.append("score_inconsistent_with_shootout")
        elif name != "goals":
            flags.append("score_repaired")
        if shoot is not None:
            return Outcome(m.home if shoot[0] > shoot[1] else m.away, "penalties", shoot, score, tuple(flags))
        flagged = _flagged_winner(m)
        if flagged is not None:
            return Outcome(flagged, "penalties", None, score, (*flags, "shootout_not_stored"))
        return Outcome(None, None, None, score, tuple(flags), reason="level_without_shootout")
    score = (m.goals_home, m.goals_away)
    if code == "AET" and score[0] == score[1]:
        # extra time was played to a result, so the match cannot have ended level: try the other readings
        other, name = _pick(m, lambda s: s[0] != s[1])
        if other is not None:
            score = other
            flags.append("score_repaired")
    if score[0] != score[1]:
        winner = m.home if score[0] > score[1] else m.away
        how: DecidedBy = "walkover" if code in AWARDED else "extra_time" if code == "AET" else "normal_time"
        return Outcome(winner, how, None, score, tuple(flags))
    flagged = _flagged_winner(m)
    if flagged is not None:
        return Outcome(flagged, "penalties", None, score, (*flags, "shootout_not_stored"))
    return Outcome(None, None, None, score, tuple(flags), reason="level_without_shootout")


def match_winner(m: Match) -> tuple[int | None, DecidedBy | None, Score | None]:
    """(winner, how, shoot-out as (home, away)) of ONE finished match. ``(None, None, None)`` while it is not played
    or when it ended level with nothing to say who went through."""
    o = single_outcome(m)
    return o.winner, o.how, o.shootout


def _stamp(matches: list[Match]) -> datetime | None:
    stamps = [m.settled_at for m in matches if m.settled_at is not None]
    return max(stamps) if stamps else None


def _goals(team: int, games: list[Match]) -> int | None:
    """The goals a side scored in the matches played so far (the provider's totals); ``None`` while none is played."""
    played = [m for m in games if m.played]
    if not played:
        return None
    return sum(g for m in played if (g := m.goals_of(team)) is not None)


def _orient(score: Score | None, *, as_home: bool) -> Score | None:
    """A (home, away) score of a match, as (side A, side B) when side A is the home side (or not)."""
    if score is None:
        return None
    return score if as_home else (score[1], score[0])


# ── one pairing ─────────────────────────────────────────────────────────────


def _single(stage: str, m: Match) -> Tie:
    o = single_outcome(m)
    status: TieStatus = ("decided" if o.winner is not None
                         else "unresolved" if m.played or m.awarded_unscored else "scheduled")
    return Tie(stage=stage, team_a=m.home, team_b=m.away, format="single", status=status, legs=((m.fixture_id, 1),),
               played=1 if m.played or m.awarded_unscored else 0, aggregate_a=o.score[0] if o.score else None,
               aggregate_b=o.score[1] if o.score else None, winner=o.winner,
               decided_by=o.how, reason=o.reason if o.winner is None else None,
               decided_at=_stamp([m]) if o.winner is not None else None, shootout=o.shootout, flags=o.flags)


def _two_legged(stage: str, first: Match, second: Match, *, flags: tuple[str, ...] = ()) -> Tie:
    a, b = first.home, first.away
    legs = ((first.fixture_id, 1), (second.fixture_id, 2))

    def tie(status: TieStatus, **kw: Any) -> Tie:
        return Tie(stage=stage, team_a=a, team_b=b, format="two_legged", status=status, legs=legs, **kw)

    games = [first, second]
    played = [m for m in games if m.played]
    if any(m.awarded_unscored for m in games):
        return tie("unresolved", played=len(played) + sum(m.awarded_unscored for m in games), reason="awarded_without_score",
                   flags=flags)
    if len(played) < 2:
        return tie("in_progress" if played else "scheduled", played=len(played), aggregate_a=_goals(a, games),
                   aggregate_b=_goals(b, games), flags=flags)
    assert first.goals_home is not None and first.goals_away is not None
    assert second.goals_home is not None and second.goals_away is not None
    first_score = (first.goals_home, first.goals_away)
    stamp = _stamp(games)
    shoot = _shootout(second) or _shootout(first)

    def aggregate(second_score: Score) -> Score:
        return (_side(first, first_score, a) + _side(second, second_score, a),
                _side(first, first_score, b) + _side(second, second_score, b))

    if shoot is not None or second.goes_to_penalties:
        # the aggregate was level when the shoot-out started: a rule of the sport, not a reading of the data
        second_score, name = _pick(second, lambda s: aggregate(s)[0] == aggregate(s)[1])
        found: Score | None = None if second_score is None else aggregate(second_score)
        kept = list(flags)
        if second_score is None:
            kept.append("score_inconsistent_with_shootout")
        elif name != "goals":
            kept.append("score_repaired")
        agg = {"aggregate_a": found[0] if found else None, "aggregate_b": found[1] if found else None}
        if shoot is not None:
            decider = second if _shootout(second) is not None else first
            winner = decider.home if shoot[0] > shoot[1] else decider.away
            return tie("decided", played=2, decided_at=stamp, winner=winner, decided_by="penalties",
                       flags=tuple(kept), shootout=_orient(shoot, as_home=decider.home == a), **agg)
        return tie("unresolved", played=2, decided_at=stamp, reason="level_on_aggregate", flags=tuple(kept), **agg)
    total = aggregate((second.goals_home, second.goals_away))
    if total[0] != total[1]:
        codes = {match_state.code(first.status), match_state.code(second.status)}
        by: DecidedBy = ("walkover" if AWARDED & codes
                         else "extra_time" if match_state.code(second.status) == "AET" else "aggregate")
        return tie("decided", played=2, decided_at=stamp, aggregate_a=total[0], aggregate_b=total[1],
                   winner=a if total[0] > total[1] else b, decided_by=by, flags=flags)
    return tie("unresolved", played=2, decided_at=stamp, aggregate_a=total[0], aggregate_b=total[1],
               reason="level_on_aggregate", flags=flags)


def _replay(stage: str, first: Match, second: Match) -> Tie:
    """A tie of a match and its replay: the replay decides, unless the first match already did."""
    legs = ((first.fixture_id, 1), (second.fixture_id, 2))
    played = sum(1 for m in (first, second) if m.played)
    decider = second
    o = single_outcome(second)
    if o.winner is None and first.played and not first.level:
        o = single_outcome(first)  # a decisive first match: the second was not needed
        decider = first
    if o.winner is not None:
        status: TieStatus = "decided"
    elif second.played:
        status = "unresolved"
    else:
        status = "in_progress" if first.played else "scheduled"
    return Tie(stage=stage, team_a=first.home, team_b=first.away, format="replay", status=status, legs=legs,
               played=played, winner=o.winner, decided_by=o.how,
               reason="level_without_shootout" if second.played and o.winner is None else None,
               decided_at=_stamp([decider]) if o.winner is not None else None,
               shootout=_orient(o.shootout, as_home=decider.home == first.home), flags=o.flags)


def _series(stage: str, games: list[Match]) -> Tie:
    first = games[0]
    a, b = first.home, first.away
    wins = {a: 0, b: 0}
    for g in games:
        w = single_outcome(g).winner
        if w is not None:
            wins[w] += 1
    played = sum(1 for g in games if g.played)
    legs = tuple((g.fixture_id, i) for i, g in enumerate(games, 1))
    leader = a if wins[a] >= wins[b] else b
    if wins[leader] >= 2 and wins[a] != wins[b]:
        done = [g for g in games if g.played]
        return Tie(stage=stage, team_a=a, team_b=b, format="series", status="decided", legs=legs, played=played,
                   aggregate_a=wins[a], aggregate_b=wins[b], winner=leader, decided_by="series",
                   decided_at=_stamp(done[-1:]))
    return Tie(stage=stage, team_a=a, team_b=b, format="series", status="in_progress" if played else "scheduled",
               legs=legs, played=played, aggregate_a=wins[a] if played else None,
               aggregate_b=wins[b] if played else None)


def _unresolved(stage: str, games: list[Match], reason: str) -> Tie:
    first = games[0]
    return Tie(stage=stage, team_a=first.home, team_b=first.away,
               format="series" if len(games) > 2 else "two_legged" if len(games) == 2 else "single",
               status="unresolved", legs=tuple((g.fixture_id, i) for i, g in enumerate(games, 1)),
               played=sum(1 for g in games if g.played), reason=reason)


# ── the next round as a witness ─────────────────────────────────────────────


def _went_on(team: int, after: datetime, advanced: Mapping[int, datetime]) -> bool:
    last = advanced.get(team)
    return last is not None and last > after


def _with_evidence(tie: Tie, games: list[Match], advanced: Mapping[int, datetime] | None) -> Tie:
    """Settle a level tie with the witness of the later rounds, and check every other winner against it. A team
    "went on" if it plays in a later round AFTER the last leg of this tie: a team that has played the round before in
    the same competition (labels are reused) is not evidence."""
    if advanced is None:
        return tie
    after = max(g.kickoff_at for g in games)
    a_in, b_in = _went_on(tie.team_a, after, advanced), _went_on(tie.team_b, after, advanced)
    if tie.status == "unresolved" and tie.reason in SETTLED_BY_EVIDENCE:
        if a_in == b_in:
            return replace(tie, reason=f"{tie.reason}_evidence_inconclusive")
        winner = tie.team_a if a_in else tie.team_b
        flags = (*tie.flags, "settled_by_next_round")
        how: DecidedBy = "penalties"
        if tie.reason == "awarded_without_score":
            how = "walkover"
        elif tie.format == "two_legged" and len(games) == 2:
            first, second = games
            away_a, away_b = second.goals_of(tie.team_a), first.goals_of(tie.team_b)
            if away_a is not None and away_b is not None and away_a != away_b and winner == (
                    tie.team_a if away_a > away_b else tie.team_b):
                how = "away_goals"
            elif match_state.code(second.status) != "PEN":
                how = "tiebreak"
            else:
                flags = (*flags, "shootout_not_stored")
        else:
            flags = (*flags, "shootout_not_stored")
        return replace(tie, status="decided", winner=winner, decided_by=how, reason=None, flags=flags,
                       check="confirmed", decided_at=_stamp([g for g in games if g.played]))
    if tie.status == "decided" and tie.winner is not None:
        won = a_in if tie.winner == tie.team_a else b_in
        lost = b_in if tie.winner == tie.team_a else a_in
        if won and not lost:
            return replace(tie, check="confirmed")
        if lost and not won:
            return replace(tie, check="contradicted")
    return tie


def _is_stale(tie: Tie, games: list[Match], now: datetime) -> bool:
    """A tie still waiting for a match that kicked off days ago is not waiting for it."""
    if tie.status not in ("scheduled", "in_progress"):
        return False
    return (now - max(g.kickoff_at for g in games)).days >= SETTLED_AFTER_DAYS


def _lone_leg(tie: Tie, games: list[Match]) -> Tie | None:
    """A round of two legs in which only one match was ever played (the other was postponed for good, or is not listed:
    the 2020 Europa League's last-16 ties, the 2025-26 AFC Champions League's West ties) and that match decided the tie
    on its own."""
    if tie.format != "two_legged" or tie.played != 1:
        return None
    game = next(g for g in games if g.played)
    o = single_outcome(game)
    if o.winner is None:
        return None
    a, b = tie.team_a, tie.team_b
    return replace(tie, status="decided", winner=o.winner, decided_by=o.how, reason=None, decided_at=_stamp([game]),
                   aggregate_a=_side(game, o.score, a) if o.score else None,
                   aggregate_b=_side(game, o.score, b) if o.score else None,
                   shootout=_orient(o.shootout, as_home=game.home == a),
                   flags=(*tie.flags, "single_leg_in_two_legged_round", *o.flags))


def _finalize(tie: Tie, games: list[Match], now: datetime, advanced: Mapping[int, datetime] | None) -> Tie:
    """The tie as it stands: settled or checked by the next round, and, when a leg is not coming any more, either decided
    by the one match that was played (only if the next round agrees) or unresolved with the reason."""
    tie = _with_evidence(tie, games, advanced)
    if not _is_stale(tie, games, now):
        return tie
    lone = _lone_leg(tie, games)
    if lone is not None:
        checked = _with_evidence(lone, games, advanced)
        if checked.check == "confirmed":
            return checked
    codes = {match_state.code(g.status) for g in games}
    reason = ("abandoned" if "ABD" in codes else "postponed_for_good" if "PST" in codes
              else "never_played" if tie.played == 0 else "second_leg_missing")
    return replace(tie, status="unresolved", reason=reason)


# ── one stage ───────────────────────────────────────────────────────────────


def _swapped(first: Match, second: Match) -> bool:
    return first.home == second.away and first.away == second.home


def _distinct(matches: list[Match]) -> tuple[list[Match], list[int]]:
    """Drop what is in no tie: cancelled matches, and an earlier postponed or abandoned fixture of a match that appears
    again between the same sides in the same order."""
    kept = [m for m in matches if match_state.code(m.status) not in NEVER_PLAYED]
    dropped = [m.fixture_id for m in matches if match_state.code(m.status) in NEVER_PLAYED]
    by_order: dict[tuple[int, int], list[Match]] = defaultdict(list)
    for m in kept:
        by_order[(m.home, m.away)].append(m)
    out: list[Match] = []
    for same in by_order.values():
        same.sort(key=lambda m: (m.kickoff_at, m.fixture_id))
        for i, m in enumerate(same):
            if match_state.code(m.status) in RESCHEDULABLE and i < len(same) - 1:
                dropped.append(m.fixture_id)
            else:
                out.append(m)
    return out, sorted(dropped)


def build_stage_ties(stage: str, matches: list[Match], *, now: datetime,
                     advanced: Mapping[int, datetime] | None = None) -> StageTies:
    """The ties of one knock-out stage (replays included) from all its matches. ``now`` only decides whether a missing
    second leg is still to come or is missing for good; ``advanced`` is, for each team, the last time it played in a
    later round of the bracket (see the module docstring), or ``None`` when that is not known."""
    usable, dropped = _distinct(matches)
    if not usable:
        return StageTies("empty", (), dropped=tuple(dropped))
    pairs: dict[frozenset[int], list[Match]] = defaultdict(list)
    for m in usable:
        pairs[frozenset((m.home, m.away))].append(m)
    opponents: dict[int, int] = defaultdict(int)
    for pair in pairs:
        for t in pair:
            opponents[t] += 1
    if any(n > 1 for n in opponents.values()):
        return StageTies("not_a_bracket", (), reason="a_team_plays_several_opponents", dropped=tuple(dropped))
    ordered = {k: sorted(v, key=lambda m: (m.kickoff_at, m.fixture_id)) for k, v in pairs.items()}
    sizes = {len(v) for v in ordered.values()}
    two_legged = [v for v in ordered.values() if len(v) == 2 and not v[1].in_replay_stage]
    share = len(two_legged) / len(ordered)
    is_series = any(n >= 3 for n in sizes) and all(n in (2, 3) for n in sizes)
    ties: list[Tie] = []
    for games in ordered.values():
        n = len(games)
        if n == 1:
            m = games[0]
            if share >= TWO_LEGGED_SHARE and not m.in_replay_stage:
                # a round of two legs with one leg listed: still to come, or missing for good
                ties.append(Tie(stage=stage, team_a=m.home, team_b=m.away, format="two_legged",
                                status="in_progress" if m.played else "scheduled", legs=((m.fixture_id, 1),),
                                played=1 if m.played else 0, aggregate_a=m.goals_home if m.played else None,
                                aggregate_b=m.goals_away if m.played else None, flags=("second_leg_not_listed",)))
            else:
                ties.append(_single(stage, m))
        elif is_series:
            ties.append(_series(stage, games))
        elif n == 2:
            first, second = games
            if second.in_replay_stage:
                ties.append(_replay(stage, first, second))
            elif share >= TWO_LEGGED_SHARE:
                ties.append(_two_legged(stage, first, second,
                                        flags=() if _swapped(first, second) else ("legs_not_swapped",)))
            elif first.level or not first.played:
                # most ties of the round have one match: this second match is a replay of a first that settled nothing
                ties.append(_replay(stage, first, second))
            else:
                ties.append(_two_legged(stage, first, second,
                                        flags=() if _swapped(first, second) else ("legs_not_swapped",)))
        else:
            ties.append(_unresolved(stage, games, "too_many_matches"))
    ties = [_finalize(t, ordered[frozenset(t.key)], now, advanced) for t in ties]
    fmt: StageFormat
    if is_series:
        fmt = "series"
    elif share >= TWO_LEGGED_SHARE:
        fmt = "two_legged"
    elif share == 0:
        fmt = "single"
    else:
        fmt = "mixed"
    return StageTies(fmt, tuple(ties), dropped=tuple(dropped))

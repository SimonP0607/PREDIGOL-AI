"""The stage and the tie of a match, for the match page (plan F2).

``core.competition_stages`` and ``core.ties`` are written by the worker (``fbi.competitions.builder``). Here they are told as
of NOW, the way a person looking at the page needs them:

* the legs that have a final result are summed from the legs themselves (extra time in, shoot-out out) - the same arithmetic as
  the builder's, checked by its audit - so a tie in progress shows the aggregate so far, not a stale row;
* a tie that is DECIDED shows the audited aggregate the builder stored, and who went through, only once this match is over:
  the page of a match that has not been played never carries what the tie went on to decide;
* every score is from THIS match's home and away: the left side of the header is the left side of the aggregate.

Pure apart from ``stage_and_tie`` (two small queries); ``tie_view`` takes the rows."""

from __future__ import annotations

from collections.abc import Sequence

from fbi.api.contracts.center import MatchStage, MatchTie, TieLeg, TieOutcome, TieScore
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.api.repositories import center as repo

SUMMED_FORMATS = frozenset({"two_legged"})
"""The formats whose tie is settled on an aggregate. A single match has none, a replay is decided by itself, and a series is
counted in games won."""


def stage_and_tie(conn: Conn, fx: Row) -> tuple[MatchStage | None, MatchTie | None]:
    """The stage of the fixture ``fx`` (a row of ``repo.FIXTURE``) and its tie. Null for a competition season the worker has
    not built, and no tie for a match that is not a leg of one (a league match)."""
    row = fetch_one(conn, repo.STAGE_AND_TIE, {"f": fx["id"]})
    if row is None:
        return None, None
    stage = MatchStage(name=row["stage"], kind=row["kind"], role=row["role"], round_key=row["round_key"],
                       is_replay=row["is_replay"], ordinal=row["ordinal"])
    if row["tie_id"] is None:
        return stage, None
    legs = fetch_all(conn, repo.TIE_LEGS, {"tie": row["tie_id"]})
    return stage, tie_view(row, legs, fixture_id=int(fx["id"]), home_team_id=int(fx["home_team_id"]),
                           status_group=str(fx["status_group"]))


def has_result(leg: Row) -> bool:
    """A leg that counts: it is over and its goals are stored."""
    return leg["status_group"] == "finished" and leg["goals_home"] is not None and leg["goals_away"] is not None


def toward(home_team_id: int, home_goals: int, away_goals: int, *, leg_home_team_id: int) -> tuple[int, int]:
    """A leg's goals as (the side that hosts THIS match, the side that visits it)."""
    if leg_home_team_id == home_team_id:
        return home_goals, away_goals
    return away_goals, home_goals


def summed(legs: Sequence[Row], home_team_id: int) -> TieScore | None:
    pairs = [toward(home_team_id, int(leg["goals_home"]), int(leg["goals_away"]), leg_home_team_id=int(leg["home_team_id"]))
             for leg in legs if has_result(leg)]
    if not pairs:
        return None
    return TieScore(home=sum(p[0] for p in pairs), away=sum(p[1] for p in pairs))


def _unscored(legs: Sequence[Row]) -> bool:
    """A leg that is over but has no goals stored (decided at the table): a sum over the others would mislead."""
    return any(leg["status_group"] == "finished" and not has_result(leg) for leg in legs)


def _stored(tie: Row, home_team_id: int, a: str, b: str) -> TieScore | None:
    if tie[a] is None or tie[b] is None:
        return None
    if int(tie["team_a_id"]) == home_team_id:
        return TieScore(home=int(tie[a]), away=int(tie[b]))
    return TieScore(home=int(tie[b]), away=int(tie[a]))


def tie_view(tie: Row, legs: Sequence[Row], *, fixture_id: int, home_team_id: int, status_group: str) -> MatchTie:
    this = next((leg for leg in legs if int(leg["fixture_id"]) == fixture_id), None)
    before = [] if this is None else [leg for leg in legs
                                      if (leg["kickoff_at"], int(leg["fixture_id"])) < (this["kickoff_at"], fixture_id)]
    over = status_group == "finished"
    decided = tie["status"] == "decided"
    sums = tie["format"] in SUMMED_FORMATS

    aggregate_before = summed(before, home_team_id) if sums and not _unscored(before) else None
    if not sums:
        aggregate = None
    elif decided and over:
        aggregate = _stored(tie, home_team_id, "aggregate_a", "aggregate_b")
    else:
        aggregate = summed(legs, home_team_id) if not _unscored(legs) else None

    outcome = None
    if decided and over and tie["winner_team_id"] is not None and tie["decided_by"] is not None:
        outcome = TieOutcome(winner="home" if int(tie["winner_team_id"]) == home_team_id else "away",
                             decided_by=tie["decided_by"], shootout=_stored(tie, home_team_id, "shootout_a", "shootout_b"),
                             contradicted=tie["winner_check"] == "contradicted")

    return MatchTie(
        format=tie["format"], state=tie["status"], leg=None if this is None or this["leg"] is None else int(this["leg"]),
        legs=int(tie["legs"]), played=sum(1 for leg in legs if has_result(leg)),
        aggregate_before=aggregate_before, aggregate=aggregate, outcome=outcome,
        legs_list=[_leg(leg, fixture_id) for leg in legs])


def _leg(leg: Row, fixture_id: int) -> TieLeg:
    return TieLeg(
        fixture_id=int(leg["fixture_id"]), leg=None if leg["leg"] is None else int(leg["leg"]),
        kickoff_at=leg["kickoff_at"], home=leg["home"], away=leg["away"], status=leg["status"],
        status_group=leg["status_group"], goals_home=leg["goals_home"], goals_away=leg["goals_away"],
        extra_time=bool(leg["extra_time"]), shootout_home=leg["shootout_home"], shootout_away=leg["shootout_away"],
        is_this=int(leg["fixture_id"]) == fixture_id)

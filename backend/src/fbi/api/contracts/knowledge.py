"""A finished match put together as one object, as the API serves it (plan F7, Match Knowledge ``mk-v1``).

When a match is over and settled, PrediGol builds ONE object from the facts it has stored (``fbi.knowledge``): the result, the
statistics of the teams, the events, the players, the tactics and the story of the score, and the market from its opening to its
close. Each layer says how far it can be trusted (``status``), how fresh it is (``known_at``) and what it could not say (``notes``).

What a user may be shown is written here and nowhere else: a layer reaches a user through one of the models below, which name every
field they may see, so a field the build adds later is not shown until it is added to its model. Everything PrediGol knows about how
it judged itself - the decision layer's picks, the post-mortems, the rows as stored and the chain of rebuilds - is the Admin
Console's preview (``MatchKnowledge.stored``) and is never a user's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract, Outcome1x2
from fbi.api.envelope import Section

LayerStatus = Literal["ok", "partial", "missing", "off"]
Completeness = Literal["complete", "partial", "minimal"]
Side = Literal["home", "away"]
Period = Literal["1H", "2H", "ET", "PEN"]
Number = int | float
Pair = tuple[int, int]
"""``[home, away]``."""


class Layer[D](Contract):
    status: LayerStatus = Field(
        description="ok: built from everything it needs. partial: built from less, and the notes say what. missing: it could not be "
                    "built (its data is null). off: not switched on.")
    known_at: datetime | None = Field(default=None, description="The newest moment any input of the layer was known to PrediGol.")
    notes: list[str] = Field(default_factory=list, description="Stable codes of what the layer could not say.")
    data: D | None = None


# ── the result ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class KnowledgeTie(Contract):
    """The tie the match was a leg of. What the tie came to is told only by the leg that closed it."""

    format: str
    legs: int
    leg: int | None = None
    aggregate: Pair | None = Field(default=None, description="Over all the legs, from this match's home side.")
    winner: Side | None = None
    decided_by: str | None = None
    shootout: Pair | None = None
    contradicted: bool = Field(default=False, description="The provider's winner disagrees with the aggregate: not to be quoted.")


class KnowledgeResult(Contract):
    match_status: str = Field(description="The provider's status of the match: FT, AET, PEN, AWD, WO...")
    kickoff: datetime | None = None
    reg: Pair = Field(description="The score of the 90 minutes: the one the markets settle on.")
    outcome: Outcome1x2
    total: int
    btts: bool
    decided_by: Literal["regulation", "extra_time", "penalties"]
    ht: Pair | None = Field(default=None, description="The score at the break.")
    final: Pair | None = Field(default=None, description="The score after extra time (a shoot-out is not in it).")
    pen: Pair | None = Field(default=None, description="The shoot-out.")
    neutral: bool = False
    corrected: bool = Field(default=False, description="The provider changed this result after first giving it.")
    tie: KnowledgeTie | None = None


# ── the statistics of the teams ─────────────────────────────────────────────────────────────────────────────────────────


class TeamFigures(Contract):
    """What the provider counted for one team. A figure it did not give is null, never zero."""

    shots: Number | None = None
    on_target: Number | None = None
    off_target: Number | None = None
    blocked: Number | None = None
    in_box: Number | None = None
    out_box: Number | None = None
    corners: Number | None = None
    fouls: Number | None = None
    offsides: Number | None = None
    yellow: Number | None = None
    red: Number | None = None
    saves: Number | None = None
    possession: Number | None = Field(default=None, description="Percent of the ball.")
    passes: Number | None = None
    passes_ok: Number | None = None
    xg: Number | None = Field(default=None, description="Expected goals, as the provider computes them.")
    prevented: Number | None = Field(default=None, description="Goals prevented by the goalkeeper (provider's figure).")


class TeamStatsData(Contract):
    home: TeamFigures | None = None
    away: TeamFigures | None = None


# ── the events ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class EventLine(Contract):
    """One line of the provider's list, read (``events-v1``)."""

    seq: int
    kind: str = Field(description="goal, own_goal, penalty_goal, penalty_missed, shootout_goal, shootout_miss, yellow, second_yellow, "
                                  "red, card_unknown, var_*... A line the rules did not know is 'other', never a guess.")
    period: Period
    minute: int
    extra: int | None = Field(default=None, description="Stoppage time: minute 90, extra 4 is 90+4.")
    side: Side | None = Field(default=None, description="The side the line counts for (for an own goal, the side that gets the goal).")
    player_side: Side | None = Field(default=None, description="The side of the man, only when it is not `side` (an own goal).")
    player: int | None = None
    name: str | None = None
    assist: int | None = None
    assist_name: str | None = None
    pair: int | None = Field(default=None, description="The other line of a dismissal for two yellows.")
    flags: list[str] = Field(default_factory=list)


class EventChecks(Contract):
    """Do the lists say what the result says? True they do, false they do not, null it cannot be told."""

    reg: bool | None = None
    ht: bool | None = None
    et: bool | None = None
    pen: bool | None = None
    cards: bool | None = None
    listed: Pair | None = Field(default=None, description="What the list gives for the 90 minutes, only when it differs from the result.")


class EventsData(Contract):
    rules: str
    n: int
    counts: dict[str, int]
    by_period: dict[str, Pair] = Field(description="Goals of each period of the match: 1H, 2H, ET and PEN.")
    check: EventChecks
    goals: list[EventLine] = Field(default_factory=list, description="Goals of the match, own goals and penalties among them, in the order they happened.")
    missed: list[EventLine] = Field(default_factory=list, description="Penalties missed in the match.")
    shootout: list[EventLine] = Field(default_factory=list, description="The kicks of the shoot-out.")
    cards: list[EventLine] = Field(default_factory=list)
    var: list[EventLine] = Field(default_factory=list)


# ── the players ─────────────────────────────────────────────────────────────────────────────────────────────────────────


class TopPlayer(Contract):
    player_id: int
    name: str | None = None
    rating: float | None = None
    minutes: int | None = None
    goals: int = 0
    assists: int = 0


class PlayersSide(Contract):
    listed: int = Field(description="Men on the sheet.")
    played: int
    started: int
    came_on: int
    top: list[TopPlayer] = Field(default_factory=list, description="The best rated, at most three.")
    captain_id: int | None = None


class PlayersData(Contract):
    home: PlayersSide | None = None
    away: PlayersSide | None = None
    goals_with_no_player: int = Field(default=0, description="Goals the list gives to nobody: in the score, not attributable to a man.")


# ── the tactics and the story of the score ──────────────────────────────────────────────────────────────────────────────


class Substitution(Contract):
    minute: int
    lead: int | None = Field(default=None, description="The lead of the side that made it at that moment (negative: behind). "
                                                       "Null when the events do not give the score.")


class TacticsSide(Contract):
    formation: str | None = None
    substitutions: list[Substitution] = Field(default_factory=list)


class FirstGoal(Contract):
    minute: int
    side: Side


class FirstDismissal(Contract):
    minute: int
    side: Side = Field(description="The side that lost the man.")
    lead: int = Field(description="Its lead at that moment (negative: behind).")


class MinutesAhead(Contract):
    home_ahead: int
    level: int
    away_ahead: int


class Ahead(Contract):
    home: bool
    away: bool


class Story(Contract):
    """How the score went in the 90 minutes. Only told when the list of events gives the score the match ended with."""

    ahead: Ahead = Field(description="Which sides were ahead at some moment.")
    lead_changes: int
    minutes: MinutesAhead = Field(description="Minutes of the 90 in which each side led, or neither did.")
    first_goal: FirstGoal | None = None
    last_goal_minute: int | None = None
    first_dismissal: FirstDismissal | None = None


class TacticsData(Contract):
    home: TacticsSide | None = None
    away: TacticsSide | None = None
    story: Story | None = None


# ── the market ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class MarketFinal(Contract):
    """The provider's last pre-match prices: the middle of the bookmakers' (not de-vigged), read after the match. A price, so the Admin
    Console's preview alone: a user is told what the market believed (``MarketBlock.probabilities``), never what a bet would have paid."""

    odds: dict[str, float]
    books: int
    at: datetime = Field(description="When the provider last moved them.")
    minutes_to_kickoff: int


class MarketBlock(Contract):
    """What the market said of one line of one market, from its first reading of the week to its last before kick-off."""

    probabilities: dict[str, tuple[float | None, float]] = Field(
        default_factory=dict, description="Per selection, the consensus probability without the bookmakers' margin: "
                                          "[opening, closing]; the opening is null when it was not quoted that week.")
    books: int | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    minutes_to_kickoff: int | None = Field(default=None, description="Of the closing reading.")
    line: float | None = Field(default=None, description="Over/Under and handicap: the line the market is read at.")
    final: MarketFinal | None = Field(
        default=None, description="The provider's last pre-match prices. Only in the Admin Console's preview: always null for a user.")


class MarketData(Contract):
    markets: dict[str, MarketBlock] = Field(description="1X2, OU, BTTS and AH, the ones that were quoted.")


# ── the answer ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class KnowledgeQuality(Contract):
    events_give_the_score: bool | None = Field(default=None, description="The list of events gives the score of the 90 minutes.")
    doubts: list[str] = Field(default_factory=list, description="Stable codes of what could not be said, or may not be right.")


class AfterMatch(Contract):
    version: str = Field(description="The rules that put it together: mk-v1.")
    completeness: Completeness = Field(description="complete: result, statistics, events and players, all trustworthy. "
                                                   "minimal: the result alone, or not even that. partial: anything between.")
    built_at: datetime
    known_at: datetime = Field(description="The newest moment anything in it was known to PrediGol.")
    quality: KnowledgeQuality
    result: Layer[KnowledgeResult]
    team_stats: Layer[TeamStatsData]
    events: Layer[EventsData]
    players: Layer[PlayersData]
    tactics: Layer[TacticsData]
    market: Layer[MarketData]


class BuildStub(Contract):
    id: int
    supersedes: int | None
    built_at: datetime
    known_at: datetime
    completeness: Completeness
    content_hash: str


class StoredBuild(Contract):
    """The newest row as stored, with the rows it replaced. Admin preview only."""

    id: int
    supersedes: int | None
    inputs_hash: str
    content_hash: str
    layers: dict[str, dict[str, Any]] = Field(description="The nine layers, c1_result to c9_postmortem, exactly as stored: the "
                                                          "sources, the decisions and picks, the post-mortems and the external context.")
    quality: dict[str, Any]
    chain: list[BuildStub] = Field(default_factory=list, description="Every build of the match, oldest first: a rebuild is a new row.")


class MatchKnowledge(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    knowledge: Section[AfterMatch | None]
    stored: StoredBuild | None = Field(default=None, description="Admin preview only; null for a user.")

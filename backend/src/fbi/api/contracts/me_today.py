"""«Para ti», the reader's layer of Home (closing plan 3.2; plan UX, A13 and section 38). Mirrored by
web/src/lib/api/v1/types_me_today.ts.

Home has two layers. **PrediGol** is the same for everyone: the day's picks, the parlays, the featured matches, the best prices.
**Para ti** is what the reader chose to follow, on top of it, and only when they chose something. Most of it Home already knows
from ``GET /today`` (the matches and why each is theirs, what is at stake) and ``GET /today/news``; this is the rest, each part
a real fact of the reader's own favourites and never a number of PrediGol's:

* the players they follow - starter, on the bench, left out, missing or doubtful, or nothing yet - for the next match of his team;
* which of the day's published picks are of their matches - a team or a league they follow, or the next match of a player they
  follow - or in a market they follow (the picks themselves are the day's, said once: here only which they are), or that none is;
* their notices: the bells they rang for the matches to come and whether the line-ups of their teams can reach them.

Nothing here computes a probability, prices a selection, chooses a pick or changes one. The favourites order and label.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.personal import MarketKey
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.today import FollowReason

PlayerState = Literal["starter", "bench", "left_out", "absent", "doubtful", "waiting", "no_match"]


class PlayerMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge


class WatchedPlayer(Contract):
    id: int = Field(description="core.players id: the one the line-ups and the favourites carry.")
    name: str
    position: str | None
    team: TeamBadge | None = Field(description="The team of the match below (his club - or his national team when that plays "
                                               "first); None without a match to come.")
    state: PlayerState = Field(description=(
        "starter / bench: in the published line-up of the next match of his team; left_out: the line-up is out and he is not in "
        "it; absent / doubtful: the provider's current list of absences names him (missing, or questionable); waiting: nothing "
        "yet - no line-up and no absence reported; no_match: his team has no match to come in the next 120 days (or he "
        "played for no team PrediGol follows in the last 400 days)."))
    reason: str | None = Field(description="absent / doubtful: the provider's own words for the absence, as the match's "
                                          "«Bajas» show it; the page classifies them. Null otherwise.")
    next: PlayerMatch | None = Field(description="The next match of his team still to be played, within 120 days.")


class RelatedPick(Contract):
    rank: int = Field(description="The pick's rank in the day's published set: the card Home already shows (GET /daily).")
    fixture_id: int
    market_key: MarketKey
    followed: FollowReason | None = Field(description="Why its match is the reader's (a team or a league they follow); null "
                                                      "when only its market is.")
    market_followed: bool = Field(description="Its market is one the reader follows.")
    players: list[str] = Field(default_factory=list, description=(
        "The players the reader follows whose next match is this pick's match (plan de Inicio, 3.4: «Tu jugador»), by name, in the "
        "order chosen; empty when none is."))


class RelatedPicks(Contract):
    day: date = Field(description="The product day (America/Bogota) of the set.")
    published: int = Field(description="How many picks of the day a reader is shown (the day's published set, «solo verde»). "
                                       "0: the day has none, whatever the reader follows.")
    items: list[RelatedPick] = Field(description="Those of them that are of the reader's matches or markets, in the set's "
                                                 "order. Empty with published > 0: none of today's picks is theirs.")


class MatchBell(Contract):
    fixture_id: int
    kickoff_at: datetime
    minutes_before: int = Field(description="«Avísame N minutos antes» (15, 30 or 60).")
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge


class Notices(Contract):
    available: bool = Field(description="Notices can be offered at all (FBI_PUSH on and PrediGol's VAPID key set, P12).")
    devices: int = Field(description="The reader's devices that receive notices now.")
    lineup: bool = Field(description="Their «alineaciones» category is on: the line-ups of the teams they follow.")
    bells: list[MatchBell] = Field(description="The bells the reader rang for matches still to be played, soonest first.")


class MeToday(Contract):
    personalization: bool = Field(description="FBI_PERSONALIZATION: false gives every reader the common view - Home has "
                                              "its PrediGol layer alone.")
    chosen: bool = Field(description=(
        "The reader chose at least one favourite - a league, a team, a player or a market - and personalisation is on: Home "
        "shows «Para ti». False: only the PrediGol layer and a discreet «Elige tus favoritos». The leagues and the team "
        "PrediGol suggests until they choose never make it true."))
    players: list[WatchedPlayer] = Field(description="The players the reader follows, in the order chosen.")
    markets: list[MarketKey] = Field(description="The markets the reader follows, in the order chosen.")
    picks: RelatedPicks | None = Field(description="Null while the reader follows no league, team, player or market.")
    notices: Notices | None = Field(description="Null while the reader has chosen nothing (Home shows no «Para ti»).")

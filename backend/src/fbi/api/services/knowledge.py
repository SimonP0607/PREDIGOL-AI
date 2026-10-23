"""Match Knowledge of a finished match, read for the product and for the Admin Console's preview (plan F7). Reading only.

The knowledge is what the worker wrote to ``intel.match_knowledge`` (``fbi.knowledge``): a finished match as one object, in layers, built
by rules from facts already stored once the match is settled. This module only lays it out. It never builds, rebuilds or changes a
row, never asks the provider for anything and never turns a layer into a recommendation.

Who sees what. A user sees the layers of FACTS - the result, the statistics of the teams, the events, the players, the tactics and the
story of the score, the market from its opening to its close - and only once the owner has decided that users see them
(``FBI_KNOWLEDGE_USERS``; off until then). Each layer is read through a model of ``fbi.api.contracts.knowledge`` that names every field
a user may see, so what the build adds later stays out of their view until it is added there. The Admin Console's preview
(``preview=shadow``) adds the row as stored (all nine layers: the sources, the decisions and picks, the post-mortems, the external
context) and the chain of rebuilds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final, cast

import structlog

from fbi.api.contracts.knowledge import (
    AfterMatch,
    Ahead,
    BuildStub,
    EventsData,
    FirstDismissal,
    FirstGoal,
    KnowledgeQuality,
    KnowledgeResult,
    KnowledgeTie,
    Layer,
    LayerStatus,
    MarketBlock,
    MarketData,
    MarketFinal,
    MatchKnowledge,
    MinutesAhead,
    Pair,
    PlayersData,
    PlayersSide,
    StoredBuild,
    Story,
    Substitution,
    TacticsData,
    TacticsSide,
    TeamFigures,
    TeamStatsData,
    TopPlayer,
)
from fbi.api.envelope import DataStatus, Envelope, ok, section, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.core.env import environment
from fbi.knowledge import builder, layers

log = structlog.get_logger(__name__)

VERSION: Final = layers.VERSION
"""The rules this reads rows of: ``mk-v1``. A new version of the rules adds rows beside the old ones; this keeps reading the one it knows."""
SETTLE: Final = builder.SETTLE
"""A match is put together 26 hours after kick-off: before that the answer says it is not settled yet."""
USERS_SWITCH: Final = "FBI_KNOWLEDGE_USERS"
"""``FBI_KNOWLEDGE_USERS=1`` lets every signed-in account see the knowledge of a finished match. Off until the owner decides: the Admin
Console's preview does not depend on it. The API needs a restart to read it."""
MAX_CHAIN: Final = 50
MARKET_ORDER: Final = {market: n for n, market in enumerate(layers.MARKETS)}
"""The order of the board: 1X2, Over/Under, both teams to score, handicap. The row keeps its keys in the order the database likes."""

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, c.is_tracked
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(f)s
"""

ROW_SQL = """
SELECT id, supersedes, built_at, known_at, inputs_hash, content_hash, completeness, layers, quality
  FROM intel.match_knowledge
 WHERE fixture_id = %(f)s AND version = %(version)s AND built_at <= %(at)s
 ORDER BY id DESC LIMIT 1
"""
"""The newest build made by ``at``: the rows of a match are a chain, the newest one is what the match is today."""

CHAIN_SQL = """
SELECT id, supersedes, built_at, known_at, completeness, content_hash
  FROM intel.match_knowledge
 WHERE fixture_id = %(f)s AND version = %(version)s AND built_at <= %(at)s
 ORDER BY id LIMIT %(limit)s
"""

STATUSES: Final = frozenset(layers.STATUSES)


def users_may_see() -> bool:
    return environment().get(USERS_SWITCH, "0").strip().lower() in {"1", "on", "true", "yes"}


# ── a stored layer, read through its model ───────────────────────────────────────────────────────────────────────────────


def _moment(value: Any) -> datetime | None:
    return None if value in (None, "") else datetime.fromisoformat(str(value))


def _when(value: Any) -> datetime:
    moment = _moment(value)
    if moment is None:
        raise ValueError("a moment is missing")
    return moment


def _pair(value: Any) -> Pair:
    home, away = value
    return int(home), int(away)


def _maybe_pair(value: Any) -> Pair | None:
    return None if value is None else _pair(value)


def _result(d: Mapping[str, Any]) -> KnowledgeResult:
    tie = d.get("tie")
    return KnowledgeResult(
        match_status=str(d["status"]), kickoff=_moment(d.get("kickoff")), reg=_pair(d["reg"]), outcome=d["outcome"], total=int(d["total"]),
        btts=bool(d["btts"]), decided_by=d["decided_by"], ht=_maybe_pair(d.get("ht")), final=_maybe_pair(d.get("final")),
        pen=_maybe_pair(d.get("pen")), neutral=bool(d.get("neutral", False)), corrected=bool(d.get("revisions")),
        tie=None if not tie else KnowledgeTie(
            format=str(tie["format"]), legs=int(tie["legs"]), leg=tie.get("leg"), aggregate=_maybe_pair(tie.get("aggregate")),
            winner=tie.get("winner"), decided_by=tie.get("decided_by"), shootout=_maybe_pair(tie.get("shootout")),
            contradicted=bool(tie.get("contradicted", False))))


def _figures(d: Mapping[str, Any] | None) -> TeamFigures | None:
    return TeamFigures.model_validate(d) if d else None


def _team_stats(d: Mapping[str, Any]) -> TeamStatsData:
    return TeamStatsData(home=_figures(d.get("home")), away=_figures(d.get("away")))


def _events(d: Mapping[str, Any]) -> EventsData:
    return EventsData.model_validate(d)


def _players_side(d: Mapping[str, Any] | None) -> PlayersSide | None:
    if not d:
        return None
    return PlayersSide(
        listed=int(d["listed"]), played=int(d["played"]), started=int(d["started"]), came_on=int(d["came_on"]),
        top=[TopPlayer(player_id=int(m["p"]), name=m.get("name"), rating=m.get("rating"), minutes=m.get("min"),
                       goals=int(m.get("g", 0)), assists=int(m.get("a", 0))) for m in d.get("top", [])],
        captain_id=d.get("captain"))


def _players(d: Mapping[str, Any]) -> PlayersData:
    return PlayersData(home=_players_side(d.get("home")), away=_players_side(d.get("away")),
                       goals_with_no_player=int(d.get("goals_with_no_player", 0)))


def _tactics_side(d: Mapping[str, Any] | None) -> TacticsSide | None:
    if not d:
        return None
    return TacticsSide(formation=d.get("formation"), substitutions=[Substitution(minute=int(m), lead=lead) for m, lead in d.get("subs", [])])


def _story(s: Mapping[str, Any] | None) -> Story | None:
    if not s:
        return None
    first, dismissal = s.get("first_goal"), s.get("first_dismissal")
    return Story(
        ahead=Ahead(home=bool(s["ahead"]["home"]), away=bool(s["ahead"]["away"])), lead_changes=int(s["lead_changes"]),
        minutes=MinutesAhead(home_ahead=int(s["minutes"]["home_ahead"]), level=int(s["minutes"]["level"]),
                             away_ahead=int(s["minutes"]["away_ahead"])),
        first_goal=None if not first else FirstGoal(minute=int(first["minute"]), side=first["side"]), last_goal_minute=s.get("last_goal"),
        first_dismissal=None if not dismissal else FirstDismissal(minute=int(dismissal["minute"]), side=dismissal["side"],
                                                                  lead=int(dismissal["lead"])))


def _tactics(d: Mapping[str, Any]) -> TacticsData:
    return TacticsData(home=_tactics_side(d.get("home")), away=_tactics_side(d.get("away")), story=_story(d.get("story")))


def _market(d: Mapping[str, Any]) -> MarketData:
    markets: dict[str, MarketBlock] = {}
    for key in sorted(d, key=lambda k: (MARKET_ORDER.get(k, len(MARKET_ORDER)), k)):
        block = d[key]
        final = block.get("final")
        markets[str(key)] = MarketBlock(
            probabilities={str(sel): (None if pair[0] is None else float(pair[0]), float(pair[1])) for sel, pair in block.get("p", {}).items()},
            books=block.get("books"), opened_at=_moment(block.get("open_at")), closed_at=_moment(block.get("close_at")),
            minutes_to_kickoff=block.get("min_to_ko"), line=block.get("line"),
            final=None if not final else MarketFinal(odds={str(s): float(v) for s, v in final["odds"].items()}, books=int(final["books"]),
                                                     at=_when(final["at"]), minutes_to_kickoff=int(final["min_to_ko"])))
    return MarketData(markets=markets)


def _layer[D](stored: Mapping[str, Any] | None, read: Callable[[Mapping[str, Any]], D], name: str) -> Layer[D]:
    """One layer as the contract says it. A layer that is not built has no data; one the model cannot read is reported as missing and
    named in the log - the rest of the answer is still given."""
    if not stored:
        return Layer[D](status="missing", notes=["not_in_the_build"])
    status = cast(LayerStatus, stored["status"] if stored.get("status") in STATUSES else "missing")
    known = _moment(stored.get("known_at"))
    notes = [str(n) for n in stored.get("notes", [])]
    data = stored.get("data")
    if status not in ("ok", "partial") or not data:
        return Layer[D](status=status, known_at=known, notes=notes)
    try:
        value = read(data)
    except (KeyError, IndexError, TypeError, ValueError) as exc:  # a pydantic ValidationError is a ValueError
        log.warning("knowledge.layer_unreadable", layer=name, error=repr(exc)[:300])
        return Layer[D](status="missing", known_at=known, notes=[*notes, "unreadable"])
    return Layer[D](status=status, known_at=known, notes=notes, data=value)


def _after_match(row: Mapping[str, Any]) -> AfterMatch:
    stored: Mapping[str, Any] = row["layers"]
    quality: Mapping[str, Any] = row["quality"]
    return AfterMatch(
        version=VERSION, completeness=row["completeness"], built_at=row["built_at"], known_at=row["known_at"],
        quality=KnowledgeQuality(events_give_the_score=quality.get("events_give_the_score"),
                                 doubts=[str(x) for x in quality.get("doubts", [])]),
        result=_layer(stored.get(layers.C1_RESULT), _result, layers.C1_RESULT),
        team_stats=_layer(stored.get(layers.C2_TEAM_STATS), _team_stats, layers.C2_TEAM_STATS),
        events=_layer(stored.get(layers.C3_EVENTS), _events, layers.C3_EVENTS),
        players=_layer(stored.get(layers.C4_PLAYERS), _players, layers.C4_PLAYERS),
        tactics=_layer(stored.get(layers.C5_TACTICS), _tactics, layers.C5_TACTICS),
        market=_layer(stored.get(layers.C6_MARKET), _market, layers.C6_MARKET))


def _stored(conn: Conn, row: Mapping[str, Any], fixture_id: int, at: datetime) -> StoredBuild:
    chain = fetch_all(conn, CHAIN_SQL, {"f": fixture_id, "version": VERSION, "at": at, "limit": MAX_CHAIN})
    return StoredBuild(
        id=int(row["id"]), supersedes=row["supersedes"], inputs_hash=str(row["inputs_hash"]), content_hash=str(row["content_hash"]),
        layers={name: dict(stored) for name, stored in row["layers"].items()}, quality=dict(row["quality"]),
        chain=[BuildStub(id=int(c["id"]), supersedes=c["supersedes"], built_at=c["built_at"], known_at=c["known_at"],
                         completeness=c["completeness"], content_hash=str(c["content_hash"])) for c in chain])


def _why_none(fixture: Mapping[str, Any], at: datetime) -> tuple[str, str]:
    """Why a match has no knowledge, as a stable code and a sentence: said, not left to look like a gap."""
    if fixture["status_group"] != "finished":
        return "not_finished", "The match is not over: PrediGol puts a match together once it has finished."
    if fixture["kickoff_at"] + SETTLE > at:
        return "not_settled_yet", "The match is over, but PrediGol waits for the provider's last look at the result before putting it together."
    if not fixture["is_tracked"]:
        return "not_followed", "PrediGol does not follow this competition."
    return "no_build_yet", "PrediGol has not put this match together yet."


def match_knowledge(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None = None) -> Envelope[MatchKnowledge | None]:
    """The knowledge of a finished match; with ``preview`` (the Admin Console), beside the row as stored and the chain of rebuilds."""
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not preview and not users_may_see():
        return unavailable(None, "The after-match summary is not shown to users yet.")
    moment = at or now()
    head: dict[str, Any] = {"fixture_id": int(fixture["id"]), "kickoff_at": fixture["kickoff_at"],
                            "status_group": str(fixture["status_group"])}
    row = fetch_one(conn, ROW_SQL, {"f": fixture_id, "version": VERSION, "at": moment})
    if row is None:
        code, reason = _why_none(fixture, moment)
        return ok(MatchKnowledge(**head, knowledge=section(None, status=DataStatus.NOT_AVAILABLE, reason=reason, code=code)))
    data = MatchKnowledge(**head, knowledge=section(_after_match(row)), stored=_stored(conn, row, fixture_id, moment) if preview else None)
    return ok(data, data_as_of=row["known_at"])

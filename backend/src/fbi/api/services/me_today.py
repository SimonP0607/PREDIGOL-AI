"""«Para ti», the reader's layer of Home (closing plan 3.2; plan UX, A13 and section 38): the players they follow with the state of
the next match of his team, which of the day's published picks are of their matches or markets, and their notices.

The common board (``today``) and the news already say what is the reader's: this is what they do not know. Everything here is a
fact of the data, said as the data has it - a player is a starter or on the bench only when the line-up is published and names him,
missing or doubtful only when the provider's CURRENT list of absences names him (the same rule as the match's «Bajas»), and
«waiting» when neither is out yet: no state is made up to fill a row.

The picks are the day's published set (``records.daily_board``, «solo verde», the one every reader sees): this module marks which
of them are the reader's by rank - it never reads a probability, prices a selection, chooses or changes a pick. It never reads a
reader's data: the favourites arrive as ids and the notices as values, from the router.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.contracts.me_today import (
    MatchBell,
    PlayerMatch,
    PlayerState,
    RelatedPick,
    RelatedPicks,
    WatchedPlayer,
)
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import records
from fbi.api.services.follows import Follows, follow_reason
from fbi.api.services.today import NEXT_DAYS, NEXT_SQL
from fbi.core.clock import now
from fbi.picks.daily import product_day

PLAYER_DAYS: Final = 400
"""A player belongs to the team of his latest line-up within this many days (the window the favourites use to offer him)."""

PLAYER_TEAMS_SQL = """
SELECT p.id, p.name, p.position, p.provider_player_id, k.team_id
  FROM core.players p
  CROSS JOIN LATERAL (
        (SELECT tm.id AS team_id
           FROM core.fixture_lineup_players lp
           JOIN core.fixtures f ON f.id = lp.fixture_id
           JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
           JOIN core.competitions c ON c.id = cs.competition_id
           JOIN core.teams tm ON tm.id = CASE lp.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
          WHERE lp.provider_player_id = p.provider_player_id AND c.is_tracked AND NOT COALESCE(tm.is_national, false)
            AND f.kickoff_at > %(since)s
          ORDER BY f.kickoff_at DESC LIMIT 1)
        UNION ALL
        (SELECT tm.id
           FROM core.fixture_lineup_players lp
           JOIN core.fixtures f ON f.id = lp.fixture_id
           JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
           JOIN core.competitions c ON c.id = cs.competition_id
           JOIN core.teams tm ON tm.id = CASE lp.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
          WHERE lp.provider_player_id = p.provider_player_id AND c.is_tracked AND COALESCE(tm.is_national, false)
            AND f.kickoff_at > %(since)s
          ORDER BY f.kickoff_at DESC LIMIT 1)
  ) k
 WHERE p.id = ANY(%(ids)s)
"""
"""Each player of the reader's with the team of his latest line-up as a club and as a national team (either may be missing): a
player of a club is also called up by his country, and the nearer match of the two is the one worth telling about."""

LINEUPS_SQL = """
SELECT lp.fixture_id, lp.team_side, lp.provider_player_id, lp.is_starter
  FROM core.fixture_lineup_players lp
 WHERE lp.fixture_id = ANY(%(fixtures)s)
"""
"""The published line-ups of those matches: which sides have one, and who is in it."""

ABSENCES_SQL = """
SELECT a.fixture_id, a.provider_player_id, a.absence_type AS type, a.reason
  FROM core.player_absences a
 WHERE a.fixture_id = ANY(%(fixtures)s) AND a.provider_player_id = ANY(%(players)s)
   AND CASE
         WHEN EXISTS (SELECT 1 FROM core.context_checks k JOIN core.fixtures f ON f.competition_season_id = k.competition_season_id
                       WHERE f.id = a.fixture_id AND k.dataset = 'injuries')
         THEN a.payload_hash = (SELECT k.payload_hash FROM core.context_checks k
                                  JOIN core.fixtures f ON f.competition_season_id = k.competition_season_id
                                 WHERE f.id = a.fixture_id AND k.dataset = 'injuries')
         ELSE a.fetched_at = (SELECT max(b.fetched_at) FROM core.player_absences b WHERE b.fixture_id = a.fixture_id)
       END
"""
"""The provider's CURRENT list of absences for those matches - the rule of the match's «Bajas» (``repositories.center.ABSENCES``):
the newest answer for the season, and a player it no longer names has recovered or was never out."""

BELLS_SQL = """
SELECT f.id AS fixture_id, f.kickoff_at, f.home_team_id, th.name AS home_name, th.logo_url AS home_logo,
       f.away_team_id, ta.name AS away_name, ta.logo_url AS away_logo,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = ANY(%(fixtures)s)
"""


@dataclass(frozen=True)
class Report:
    """What the provider says of an absent player."""

    type: str | None
    reason: str | None


def doubtful(report: Report) -> bool:
    """A «Questionable» report is a doubt; «Missing Fixture» and anything else is an absence (the match page's rule)."""
    kind = (report.type or "").lower()
    return "question" in kind or "doubt" in kind


def state_of(*, published: bool, listed: bool, starter: bool, report: Report | None) -> PlayerState:
    """The state of a player for a match to come (pure): the published line-up is the newest word - he is in it (a starter or on
    the bench) - else the provider's absence report (missing or doubtful), else out of a line-up that is published, else nothing
    yet."""
    if published and listed:
        return "starter" if starter else "bench"
    if report is not None:
        return "doubtful" if doubtful(report) else "absent"
    return "left_out" if published else "waiting"


def _badge(r: Mapping[str, Any]) -> CompetitionBadge:
    return CompetitionBadge(id=int(r["competition_id"]), name=r["competition_name"], country=r["competition_country"],
                            logo_url=r["competition_logo"], flag_url=r["competition_flag"])


def _match(r: Mapping[str, Any]) -> PlayerMatch:
    return PlayerMatch(
        fixture_id=int(r["fixture_id"]), kickoff_at=r["kickoff_at"], competition=_badge(r),
        home=TeamBadge(id=int(r["home_team_id"]), name=r["home_name"], logo_url=r["home_logo"]),
        away=TeamBadge(id=int(r["away_team_id"]), name=r["away_name"], logo_url=r["away_logo"]))


def watched(conn: Conn, ids: Sequence[int], *, at: datetime | None = None) -> list[WatchedPlayer]:
    """The reader's players, in the order they chose them, each with the state for the next match of his team."""
    if not ids:
        return []
    moment = at or now()
    people: dict[int, dict[str, Any]] = {}
    teams: dict[int, list[int]] = {}
    for r in fetch_all(conn, PLAYER_TEAMS_SQL, {"ids": list(ids), "since": moment - timedelta(days=PLAYER_DAYS)}):
        pid = int(r["id"])
        people.setdefault(pid, r)
        if r["team_id"] is not None:
            teams.setdefault(pid, []).append(int(r["team_id"]))
    # a player with no line-up in the window has no row above: his name still has to be said
    for r in fetch_all(conn, "SELECT id, name, position, provider_player_id FROM core.players WHERE id = ANY(%(ids)s)",
                       {"ids": list(ids)}):
        people.setdefault(int(r["id"]), r)
    team_ids = sorted({t for ts in teams.values() for t in ts})
    nexts: dict[int, dict[str, Any]] = {}
    if team_ids:
        for r in fetch_all(conn, NEXT_SQL, {"teams": team_ids, "leagues": [], "at": moment,
                                            "until": moment + timedelta(days=NEXT_DAYS)}):
            nexts[int(r["ref"])] = r
    chosen: dict[int, dict[str, Any]] = {}
    for pid, candidates in teams.items():
        found = [nexts[t] | {"team_id": t} for t in candidates if t in nexts]
        if found:
            chosen[pid] = min(found, key=lambda r: (r["kickoff_at"], int(r["fixture_id"])))
    fixtures = sorted({int(r["fixture_id"]) for r in chosen.values()})
    published: set[tuple[int, str]] = set()
    listed: dict[tuple[int, int], bool] = {}
    reports: dict[tuple[int, int], Report] = {}
    if fixtures:
        for r in fetch_all(conn, LINEUPS_SQL, {"fixtures": fixtures}):
            published.add((int(r["fixture_id"]), r["team_side"]))
            listed[(int(r["fixture_id"]), int(r["provider_player_id"]))] = bool(r["is_starter"])
        provider = sorted({int(people[p]["provider_player_id"]) for p in chosen if people.get(p)})
        for r in fetch_all(conn, ABSENCES_SQL, {"fixtures": fixtures, "players": provider}):
            reports[(int(r["fixture_id"]), int(r["provider_player_id"]))] = Report(r["type"], r["reason"])
    out: list[WatchedPlayer] = []
    for pid in ids:
        who = people.get(pid)
        if who is None:  # a player that is gone from the catalogue
            continue
        nxt = chosen.get(pid)
        if nxt is None:
            out.append(WatchedPlayer(id=pid, name=who["name"], position=who["position"], team=None, state="no_match",
                                     reason=None, next=None))
            continue
        fixture, provider_id = int(nxt["fixture_id"]), int(who["provider_player_id"])
        side = "home" if int(nxt["home_team_id"]) == int(nxt["team_id"]) else "away"
        report = reports.get((fixture, provider_id))
        state = state_of(published=(fixture, side) in published, listed=(fixture, provider_id) in listed,
                         starter=listed.get((fixture, provider_id), False), report=report)
        mine = _match(nxt)
        out.append(WatchedPlayer(
            id=pid, name=who["name"], position=who["position"], state=state, next=mine,
            team=mine.home if side == "home" else mine.away,
            reason=report.reason if report is not None and state in ("absent", "doubtful") else None))
    return out


def related(conn: Conn, follows: Follows, markets: Sequence[str], *, at: datetime | None = None) -> RelatedPicks:
    """Which of the day's published picks are the reader's: their match has a team or a league they follow (``follows``: their
    own, never the suggested) or its market is one they follow. The day's set is the one Home shows - kept 30 seconds, the same
    for every reader - and only its order and its picks' match and market are read."""
    moment = at or now()
    # Without an explicit ``at`` the call is exactly the one of GET /daily (day=None, include_shadow=False): the shared cache
    # keys on the arguments, and a fresh ``at=now()`` on every call made each reader recompute the day's set.
    held = {} if at is None else {"at": at}
    board = records.daily_board(conn, day=None, include_shadow=False, **held).data
    items = board.set.items if board is not None and board.set is not None else []
    mine: list[RelatedPick] = []
    for item in items:
        m = item.match
        why = follow_reason((m.home.id, m.home.name), (m.away.id, m.away.name), (m.competition.id, m.competition.name),
                            follows)
        followed_market = item.market_key in markets
        if why is not None or followed_market:
            mine.append(RelatedPick(rank=item.rank, fixture_id=m.fixture_id, market_key=item.market_key,  # type: ignore[arg-type]
                                    followed=why, market_followed=followed_market))
    return RelatedPicks(day=board.day if board is not None else product_day(moment), published=len(items), items=mine)


def bells(conn: Conn, rung: Sequence[tuple[int, int]]) -> list[MatchBell]:
    """The reader's bells - (fixture id, minutes before), soonest first as given - with the match each rings for."""
    if not rung:
        return []
    found = {int(r["fixture_id"]): _match(r) for r in fetch_all(conn, BELLS_SQL, {"fixtures": [f for f, _ in rung]})}
    return [MatchBell(fixture_id=f, kickoff_at=found[f].kickoff_at, minutes_before=minutes,
                      competition=found[f].competition, home=found[f].home, away=found[f].away)
            for f, minutes in rung if f in found]

"""Competitions and teams."""

from __future__ import annotations

from fastapi import HTTPException

from fbi.api.contracts.catalog import (
    CompetitionDetail,
    CompetitionSummary,
    SeasonSummary,
    TeamDetail,
    TeamRecord,
    TeamSummary,
)
from fbi.api.contracts.common import TeamRef, VenueRef
from fbi.api.envelope import DataStatus, Envelope, Section, listing, ok
from fbi.api.repositories import Conn
from fbi.api.repositories import catalog as repo
from fbi.api.repositories import fixtures as fixtures_repo
from fbi.api.services.matches import summary
from fbi.core.clock import now


def list_competitions(
    conn: Conn, *, tracked: bool | None, q: str | None, limit: int, offset: int
) -> Envelope[list[CompetitionSummary]]:
    rows = repo.list_competitions(conn, tracked=tracked, q=q, limit=limit, offset=offset)
    total = repo.count_competitions(conn, tracked=tracked, q=q)
    return listing(
        [CompetitionSummary(**r) for r in rows],
        empty_reason="No competition matches these filters." if (tracked is not None or q) else "The catalogue is empty.",
        total=total, limit=limit, offset=offset,
    )


def competition_detail(conn: Conn, competition_id: int) -> Envelope[CompetitionDetail]:
    rows = repo.list_competitions(conn, tracked=None, q=None, limit=1, offset=0, competition_id=competition_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"competition {competition_id} not found")
    return ok(CompetitionDetail(
        competition=CompetitionSummary(**rows[0]),
        seasons=[SeasonSummary(**s) for s in repo.seasons_of(conn, competition_id)],
        teams=[TeamRef(**t) for t in repo.teams_of(conn, competition_id)],
    ))


def list_teams(
    conn: Conn, *, q: str | None, competition_id: int | None, limit: int, offset: int
) -> Envelope[list[TeamSummary]]:
    rows = repo.list_teams(conn, q=q, competition_id=competition_id, limit=limit, offset=offset)
    items = [TeamSummary(**{k: v for k, v in r.items() if k != "venue_id"}) for r in rows]
    return listing(
        items,
        empty_reason="No team matches these filters." if (q or competition_id) else "No teams have been ingested yet.",
        limit=limit, offset=offset,
    )


def team_detail(conn: Conn, team_id: int) -> Envelope[TeamDetail]:
    rows = repo.list_teams(conn, q=None, competition_id=None, limit=1, offset=0, team_id=team_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"team {team_id} not found")
    team = rows[0]
    venue = fixtures_repo.get_venue(conn, team["venue_id"]) if team["venue_id"] else None
    rec = repo.team_record(conn, team_id)
    record = (
        Section[TeamRecord | None](status=DataStatus.OK, data=TeamRecord(**rec)) if rec and rec["played"]
        else Section[TeamRecord | None](
            status=DataStatus.INSUFFICIENT_DATA, data=None,
            reason="No recorded result for this team yet: a record needs played matches with scores.")
    )
    moment = now()
    recent, _ = fixtures_repo.list_fixtures(
        conn, fixtures_repo.FixtureFilter(team_id=team_id, kickoff_before=moment), limit=10, offset=0, order="desc")
    upcoming, _ = fixtures_repo.list_fixtures(
        conn, fixtures_repo.FixtureFilter(team_id=team_id, kickoff_after=moment), limit=10, offset=0, order="asc")
    return ok(TeamDetail(
        team=TeamSummary(**{k: v for k, v in team.items() if k != "venue_id"}),
        venue=VenueRef(**venue) if venue else None,
        record=record,
        recent=[summary(r, moment) for r in recent],
        upcoming=[summary(r, moment) for r in upcoming],
    ))

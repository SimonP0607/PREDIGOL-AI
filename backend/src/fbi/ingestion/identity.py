"""Writing identity: teams, venues, players, coaches.

    OUR id, and the provider's reference, unique.

Storing a name twice under two ids is how a platform ends up with two Manchester
Uniteds, so nothing here matches on names. Every upsert keys on the provider's id;
the name is data that can change, not identity.

What this replaces: ``/teams?league&season`` had been fetched 54 times, returning
1,604 teams, and normalised into nothing - the unit stored raw bytes and wrote
zero rows. ``core.players`` had no writer at all, and 16,053 stored fixtures'
worth of line-ups and player statistics named players nobody recorded. Coaches
existed only as a name repeated inside every line-up row.

Monotonic, like every other writer in this package: a row is only overwritten by
a payload fetched at the same instant or later, so replaying an old payload can
never undo a newer one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.providers.api_football.details import PersonRef, TeamRef

log = structlog.get_logger(__name__)


@dataclass
class IdentityReport:
    teams_written: int = 0
    venues_written: int = 0
    players_written: int = 0
    coaches_written: int = 0
    memberships_written: int = 0
    lineups_linked: int = 0
    skipped_no_name: int = 0
    skipped_no_id: int = 0
    """People the provider sent with id 0: an unidentified player is not an identity."""
    notes: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return (self.teams_written + self.venues_written + self.players_written
                + self.coaches_written + self.memberships_written)


def _venue_id(cur: psycopg.Cursor[tuple[int]], team: TeamRef, *, payload_hash: str,
              fetched_at: datetime) -> int | None:
    """Upsert the venue, keyed on the provider's id.

    A venue the provider names without an id cannot be identified across payloads,
    so it is NOT stored: an unkeyable row would be a new venue every time.
    """
    v = team.venue
    if v is None or v.provider_venue_id is None or v.name is None:
        return None
    cur.execute(
        "INSERT INTO core.venues (provider_venue_id, name, city, country, capacity, surface, address, image_url, "
        " source_payload_hash, source_fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (provider_venue_id) DO UPDATE SET "
        "  name = EXCLUDED.name, city = EXCLUDED.city, country = EXCLUDED.country, "
        "  capacity = EXCLUDED.capacity, surface = EXCLUDED.surface, address = EXCLUDED.address, "
        "  image_url = COALESCE(EXCLUDED.image_url, core.venues.image_url), "
        "  source_payload_hash = EXCLUDED.source_payload_hash, "
        "  source_fetched_at = EXCLUDED.source_fetched_at "
        "WHERE core.venues.source_fetched_at IS NULL "
        "   OR core.venues.source_fetched_at <= EXCLUDED.source_fetched_at "
        "RETURNING id",
        (v.provider_venue_id, v.name, v.city, v.country, v.capacity, v.surface, v.address, v.image_url,
         payload_hash, fetched_at),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row[0])
    cur.execute("SELECT id FROM core.venues WHERE provider_venue_id = %s", (v.provider_venue_id,))
    existing = cur.fetchone()
    return int(existing[0]) if existing else None


def apply_teams(
    conn: psycopg.Connection,
    teams: Iterable[TeamRef],
    *,
    payload_hash: str,
    fetched_at: datetime,
    competition_season_id: int | None = None,
) -> IdentityReport:
    """Upsert teams and their venues, and record season membership when known.

    ``competition_season_id`` comes from the unit that asked for the payload -
    /teams is always fetched per league and season - so membership is a fact about
    that request, not a guess.
    """
    report = IdentityReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        for team in teams:
            venue_id = _venue_id(cur, team, payload_hash=payload_hash, fetched_at=fetched_at)
            if venue_id is not None and (team.venue is None or team.venue.provider_venue_id is None):
                report.notes.append(f"team {team.provider_team_id}: venue without a provider id, not stored")
            cur.execute(
                "INSERT INTO core.teams (provider_team_id, name, short_name, country, is_national, "
                " founded, venue_id, logo_url, source_payload_hash, source_fetched_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider_team_id) DO UPDATE SET "
                "  name = EXCLUDED.name, short_name = EXCLUDED.short_name, country = EXCLUDED.country, "
                "  is_national = EXCLUDED.is_national, founded = EXCLUDED.founded, "
                "  venue_id = COALESCE(EXCLUDED.venue_id, core.teams.venue_id), "
                "  logo_url = EXCLUDED.logo_url, source_payload_hash = EXCLUDED.source_payload_hash, "
                "  source_fetched_at = EXCLUDED.source_fetched_at, updated_at = now() "
                "WHERE core.teams.source_fetched_at IS NULL "
                "   OR core.teams.source_fetched_at <= EXCLUDED.source_fetched_at "
                "RETURNING id",
                (team.provider_team_id, team.name, team.code, team.country, team.is_national,
                 team.founded, venue_id, team.logo_url, payload_hash, fetched_at),
            )
            row = cur.fetchone()
            if row is not None:
                report.teams_written += 1
                if venue_id is not None:
                    report.venues_written += 1
                team_id: int | None = int(row[0])
            else:
                cur.execute("SELECT id FROM core.teams WHERE provider_team_id = %s",
                            (team.provider_team_id,))
                found = cur.fetchone()
                team_id = int(found[0]) if found else None
            if competition_season_id is None or team_id is None:
                continue
            cur.execute(
                "INSERT INTO core.team_season_memberships (team_id, competition_season_id, "
                " source_payload_hash, source_fetched_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (team_id, competition_season_id) DO UPDATE SET "
                "  source_payload_hash = EXCLUDED.source_payload_hash, "
                "  source_fetched_at = EXCLUDED.source_fetched_at "
                "WHERE core.team_season_memberships.source_fetched_at IS NULL "
                "   OR core.team_season_memberships.source_fetched_at <= EXCLUDED.source_fetched_at "
                "RETURNING team_id",
                (team_id, competition_season_id, payload_hash, fetched_at),
            )
            if cur.fetchone() is not None:
                report.memberships_written += 1
    log.info("identity.teams_applied", teams=report.teams_written, venues=report.venues_written,
             memberships=report.memberships_written)
    return report


def apply_people(
    conn: psycopg.Connection,
    players: Sequence[PersonRef],
    coaches: Sequence[PersonRef],
    *,
    payload_hash: str,
    fetched_at: datetime,
    report: IdentityReport | None = None,
) -> IdentityReport:
    """Upsert the players and coaches a payload NAMES.

    Identity only: an id and a name, which is all a detail payload carries. The
    richer fields (birth date, height, nationality) come from /players and
    /coachs, and a row written from a line-up must not pretend to hold them - so
    they are left untouched rather than overwritten with NULL.
    """
    out = report if report is not None else IdentityReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        for p in players:
            if p.provider_id <= 0:
                # The provider's "we do not know who this is". Writing it made one
                # core.players row out of 3,926 different people across 3,926 matches.
                out.skipped_no_id += 1
                continue
            if not p.name:
                out.skipped_no_name += 1
                continue
            cur.execute(
                "INSERT INTO core.players (provider_player_id, name, position, source_payload_hash, "
                " source_fetched_at) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider_player_id) DO UPDATE SET "
                "  name = EXCLUDED.name, "
                "  position = COALESCE(EXCLUDED.position, core.players.position), "
                "  source_payload_hash = EXCLUDED.source_payload_hash, "
                "  source_fetched_at = EXCLUDED.source_fetched_at, updated_at = now() "
                "WHERE core.players.source_fetched_at IS NULL "
                "   OR core.players.source_fetched_at <= EXCLUDED.source_fetched_at "
                "RETURNING id",
                (p.provider_id, p.name, p.position, payload_hash, fetched_at),
            )
            if cur.fetchone() is not None:
                out.players_written += 1
        for c in coaches:
            if c.provider_id <= 0:
                out.skipped_no_id += 1
                continue
            if not c.name:
                out.skipped_no_name += 1
                continue
            cur.execute(
                "INSERT INTO core.coaches (provider_coach_id, name, source_payload_hash, "
                " source_fetched_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (provider_coach_id) DO UPDATE SET "
                "  name = EXCLUDED.name, source_payload_hash = EXCLUDED.source_payload_hash, "
                "  source_fetched_at = EXCLUDED.source_fetched_at, updated_at = now() "
                "WHERE core.coaches.source_fetched_at IS NULL "
                "   OR core.coaches.source_fetched_at <= EXCLUDED.source_fetched_at "
                "RETURNING id",
                (c.provider_id, c.name, payload_hash, fetched_at),
            )
            if cur.fetchone() is not None:
                out.coaches_written += 1
    return out


def link_lineup_coaches(conn: psycopg.Connection, fixture_id: int) -> int:
    """Point a fixture's line-ups at the coach identity beside the stored name.

    The name is kept as the provider sent it; the id is what we made of it. Run
    after the coaches are upserted, in the same transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE core.fixture_lineups l SET coach_id = c.id FROM core.coaches c "
            "WHERE l.fixture_id = %s AND l.provider_coach_id = c.provider_coach_id "
            "  AND (l.coach_id IS NULL OR l.coach_id <> c.id)",
            (fixture_id,),
        )
        return max(cur.rowcount, 0)

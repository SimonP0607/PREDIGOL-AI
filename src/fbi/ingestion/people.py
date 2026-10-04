"""Who the players are: profiles and current squads.

``core.players`` was written only from match payloads - a line-up names a player and
says nothing else - so on 4 Oct 2026 four of the 58,663 players seen in a line-up in
the last year had a birth date. Two provider endpoints fill that in:

* ``/players/profiles?page=N`` - every player the provider knows, 250 a page in id
  order (2,741 pages on 4 Oct). A page updates the profiles of the players we
  already hold; a player we have never seen in a match is not created from it, so
  the catalogue stays the players of our competitions. The raw page is kept, so a
  player who appears later can be filled from it without asking again.
* ``/players/squads?team=`` - a team's current squad. Memberships are kept with when
  they were first and last seen; the current squad is whoever was seen at the team's
  latest read, and a player who left stays on record.

Both run as backfill units (``player_profiles``, ``team_squad``): behind the live
reserve, resumable, one request each. ``seed_people_refresh`` adds a profile sweep
once a month and a squad round once a week, for the teams of the current seasons of
tracked competitions - a refresh of the same scope, never a wider one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.providers.api_football.details import PlayerProfileRef, SquadMemberRef

PROFILE_COLUMNS = ("name", "firstname", "lastname", "birth_date", "birth_place", "birth_country", "nationality",
                   "height_cm", "weight_kg", "position", "photo_url")


@dataclass
class ProfilesOutcome:
    updated: int = 0
    unknown: int = 0


def apply_player_profiles(conn: psycopg.Connection, refs: Iterable[PlayerProfileRef], *, payload_hash: str,
                          fetched_at: datetime) -> ProfilesOutcome:
    """Fill the profiles of the players we hold. A value the provider leaves empty does not
    erase one we already have; a profile older than the one stored changes nothing."""
    rows = list(refs)
    out = ProfilesOutcome()
    if not rows:
        return out
    sets = ", ".join(f"{c} = COALESCE(v.{c}, p.{c})" for c in PROFILE_COLUMNS)
    values = [(r.provider_player_id, r.name, r.firstname, r.lastname, r.birth_date, r.birth_place, r.birth_country,
               r.nationality, r.height_cm, r.weight_kg, r.position, r.photo_url) for r in rows]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE core.players p SET {sets}, profile_fetched_at = %(at)s, profile_payload_hash = %(h)s,
                   updated_at = now()
              FROM (SELECT * FROM unnest(%(ids)s::int[], %(name)s::text[], %(fn)s::text[], %(ln)s::text[],
                                         %(bd)s::date[], %(bp)s::text[], %(bc)s::text[], %(nat)s::text[],
                                         %(h_cm)s::smallint[], %(w_kg)s::smallint[], %(pos)s::text[],
                                         %(photo)s::text[])
                      AS t(provider_player_id, {", ".join(PROFILE_COLUMNS)})) v
             WHERE p.provider_player_id = v.provider_player_id
               AND (p.profile_fetched_at IS NULL OR p.profile_fetched_at <= %(at)s)
            """,
            {"at": fetched_at, "h": payload_hash,
             "ids": [v[0] for v in values], "name": [v[1] for v in values], "fn": [v[2] for v in values],
             "ln": [v[3] for v in values], "bd": [v[4] for v in values], "bp": [v[5] for v in values],
             "bc": [v[6] for v in values], "nat": [v[7] for v in values], "h_cm": [v[8] for v in values],
             "w_kg": [v[9] for v in values], "pos": [v[10] for v in values], "photo": [v[11] for v in values]},
        )
        out.updated = max(cur.rowcount, 0)
        cur.execute("SELECT count(*) FROM core.players WHERE provider_player_id = ANY(%s)",
                    ([v[0] for v in values],))
        known = cur.fetchone()
    out.unknown = len(rows) - (int(known[0]) if known else 0)
    return out


@dataclass
class SquadOutcome:
    members: int = 0
    unknown_team: bool = False
    left: int = 0


def apply_squad(conn: psycopg.Connection, provider_team_id: int, members: list[SquadMemberRef], *,
                payload_hash: str, fetched_at: datetime) -> SquadOutcome:
    out = SquadOutcome()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, squad_checked_at FROM core.teams WHERE provider_team_id = %s", (provider_team_id,))
        row = cur.fetchone()
        if row is None:
            out.unknown_team = True
            return out
        team_id, checked = int(row[0]), row[1]
        if checked is not None and checked > fetched_at:
            return out  # an older answer than the one already applied
        for m in members:
            cur.execute(
                "INSERT INTO core.squad_members (team_id, provider_player_id, player_name, shirt_number, position, "
                "age, photo_url, first_seen_at, last_seen_at, payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (team_id, provider_player_id) DO UPDATE SET player_name = EXCLUDED.player_name, "
                "shirt_number = EXCLUDED.shirt_number, position = EXCLUDED.position, age = EXCLUDED.age, "
                "photo_url = EXCLUDED.photo_url, last_seen_at = EXCLUDED.last_seen_at, "
                "payload_hash = EXCLUDED.payload_hash "
                "WHERE core.squad_members.last_seen_at <= EXCLUDED.last_seen_at",
                (team_id, m.provider_player_id, m.name, m.number, m.position, m.age, m.photo_url, fetched_at,
                 fetched_at, payload_hash),
            )
            out.members += 1
        cur.execute("SELECT count(*) FROM core.squad_members WHERE team_id = %s AND last_seen_at < %s",
                    (team_id, fetched_at))
        left = cur.fetchone()
        out.left = int(left[0]) if left else 0
        cur.execute("UPDATE core.teams SET squad_checked_at = %s WHERE id = %s", (fetched_at, team_id))
    return out


# ── seeding the refresh ─────────────────────────────────────────────────────

SQUAD_TEAMS_SQL = """
SELECT DISTINCT t.provider_team_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE c.is_tracked AND cs.is_current AND c.name !~* 'friendl'
 ORDER BY 1
"""


@dataclass
class PeopleSeed:
    profile_generation: int
    squad_generation: int
    profile_units: int = 0
    squad_units: int = 0
    notes: list[str] = field(default_factory=list)


def _add(cur: psycopg.Cursor[Any], *, kind: str, season: int, endpoint: str, params: dict[str, Any],
         page: int | None = None, batch_key: str | None = None, priority: int = 50) -> bool:
    cur.execute(
        "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, params, page, "
        "batch_key, tier) VALUES (%s, 0, %s, %s, %s, %s, %s, %s, 1) ON CONFLICT DO NOTHING RETURNING id",
        (kind, season, priority, endpoint, Json(params), page, batch_key),
    )
    return cur.fetchone() is not None


PLAYER_SEASONS_SQL = """
SELECT c.provider_league_id, cs.season FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current AND coalesce(lc.players, true)
 ORDER BY c.provider_league_id
"""


def seed_player_seasons(conn: psycopg.Connection, *, at: datetime) -> int:
    """The week's sweep of the provider's season player statistics (/players?league&season, 20 a page) for every
    current tracked season its coverage says has them: page 1 of each, whose answer adds the other pages.
    ``batch_key`` names the ISO week, so each week is one new set of units and never two."""
    iso = at.isocalendar()
    generation = f"w{iso.year}{iso.week:02d}"
    added = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PLAYER_SEASONS_SQL)
        for league, season in cur.fetchall():
            cur.execute(
                "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, params, page, "
                "batch_key, tier) VALUES ('players_season', %s, %s, 70, '/players', %s, 1, %s, 1) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (int(league), int(season), Json({"league": int(league), "season": int(season), "page": 1}),
                 generation))
            added += 1 if cur.fetchone() is not None else 0
    conn.commit()
    return added


def seed_people_refresh(conn: psycopg.Connection, *, at: datetime) -> PeopleSeed:
    """The month's profile sweep (page 1; its answer adds the rest) and the week's squad round.

    ``season`` carries the generation - 202610 for October's sweep, 202640 for the 40th
    ISO week's squads - so a new month or week is a new set of units while the same one
    is never added twice.
    """
    iso = at.isocalendar()
    seed = PeopleSeed(profile_generation=at.year * 100 + at.month, squad_generation=iso.year * 100 + iso.week)
    with conn.cursor(row_factory=tuple_row) as cur:
        if _add(cur, kind="player_profiles", season=seed.profile_generation, endpoint="/players/profiles",
                params={"page": 1}, page=1):
            seed.profile_units += 1
        cur.execute(SQUAD_TEAMS_SQL)
        for (team,) in cur.fetchall():
            if _add(cur, kind="team_squad", season=seed.squad_generation, endpoint="/players/squads",
                    params={"team": int(team)}, batch_key=str(int(team)), priority=60):
                seed.squad_units += 1
    conn.commit()
    return seed

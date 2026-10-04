"""Entity identity: one provider id = one thing, one thing = one provider id.

Database checks (no request): team rows sharing a name and country; player rows sharing a name and
a birth date under two provider ids (duplicates) and display names shared by different people
(collisions - harmless while every join is by id); match rows of players we have no profile for;
national flags; coaches and venues twice; squads (when each was captured, players in two clubs'
newest squads); injury lists' freshness; and whether each entity's key is the provider's id.

Provider samples: ``/teams?id``, ``/players/profiles?player``, ``/coachs?id`` and ``/venues?id``
for a few ids each, compared field by field with the GATE A comparators.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth import compare
from fbi.truth.audit import db_coach, db_player, db_team
from fbi.truth.findings import Tally
from fbi.truth.v2.ledger import Evidence
from fbi.truth.v2.runner import V2Run

CHECKS: dict[str, str] = {
    "team_duplicates": """
        SELECT lower(unaccent_name) AS name, country, array_agg(provider_team_id ORDER BY provider_team_id) AS ids
          FROM (SELECT provider_team_id, country, regexp_replace(lower(translate(name,
                'áàâäãåéèêëíìîïóòôöõúùûüñçÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ', 'aaaaaaeeeeiiiiooooouuuuncAAAAAAEEEEIIIIOOOOOUUUUNC')),
                '[^a-z0-9]+', ' ', 'g') AS unaccent_name FROM core.teams) t
         GROUP BY 1, 2 HAVING count(*) > 1 ORDER BY 1 LIMIT 50""",
    "player_duplicates": """
        SELECT lower(coalesce(firstname, '') || ' ' || coalesce(lastname, '')) AS full_name, birth_date,
               array_agg(provider_player_id ORDER BY provider_player_id) AS ids
          FROM core.players WHERE birth_date IS NOT NULL AND lastname IS NOT NULL
         GROUP BY 1, 2 HAVING count(*) > 1 ORDER BY 1 LIMIT 50""",
    "player_name_collisions": """
        SELECT count(*) AS names, sum(n) AS players FROM (
            SELECT name, count(*) AS n FROM core.players GROUP BY name HAVING count(*) > 1) x""",
    "player_rows_without_profile": """
        SELECT count(DISTINCT ps.provider_player_id) AS players FROM core.fixture_player_stats ps
         WHERE NOT EXISTS (SELECT 1 FROM core.players p WHERE p.provider_player_id = ps.provider_player_id)""",
    "players_without_profile_fetch": """
        SELECT count(*) FILTER (WHERE profile_fetched_at IS NULL) AS never, count(*) AS total FROM core.players""",
    "national_flags": """
        SELECT count(*) FILTER (WHERE t.is_national) AS national,
               count(*) FILTER (WHERE NOT t.is_national AND EXISTS (
                   SELECT 1 FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                     JOIN core.competitions c ON c.id = cs.competition_id
                    WHERE c.entity_scope = 'national' AND t.id IN (f.home_team_id, f.away_team_id))) AS club_rows_in_national_comps,
               count(*) FILTER (WHERE t.is_national AND EXISTS (
                   SELECT 1 FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                     JOIN core.competitions c ON c.id = cs.competition_id
                    WHERE c.entity_scope = 'club' AND c.provider_league_id <> 667
                      AND t.id IN (f.home_team_id, f.away_team_id))) AS national_rows_in_club_comps
          FROM core.teams t""",
    "coach_duplicates": """
        SELECT lower(name) AS name, birth_date, array_agg(provider_coach_id) AS ids FROM core.coaches
         WHERE birth_date IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1 LIMIT 20""",
    "venue_duplicates": """
        SELECT lower(name) AS name, lower(city) AS city, array_agg(provider_venue_id) AS ids FROM core.venues
         WHERE name IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1 LIMIT 20""",
    "squads": """
        SELECT count(DISTINCT team_id) AS teams, count(*) AS rows, min(first_seen_at) AS first_capture,
               max(last_seen_at) AS last_capture,
               count(DISTINCT team_id) FILTER (WHERE last_seen_at < now() - interval '14 days') AS teams_stale_14d
          FROM core.squad_members""",
    "players_in_two_club_squads": """
        WITH newest AS (
            SELECT m.provider_player_id, m.team_id FROM core.squad_members m JOIN core.teams t ON t.id = m.team_id
             WHERE NOT t.is_national AND m.last_seen_at = t.squad_checked_at)
        SELECT count(*) AS players FROM (SELECT provider_player_id FROM newest GROUP BY 1 HAVING count(*) > 1) x""",
    "injuries_freshness": """
        SELECT count(DISTINCT f.id) AS upcoming_48h,
               count(DISTINCT f.id) FILTER (WHERE k.checked_at > now() - interval '6 hours') AS season_checked_6h,
               min(k.checked_at) AS oldest_check
          FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          LEFT JOIN core.context_checks k ON k.competition_season_id = cs.id AND k.dataset = 'injuries'
         WHERE c.is_tracked AND f.status_group = 'scheduled'
           AND f.kickoff_at BETWEEN now() AND now() + interval '48 hours'""",
    "coach_career_stored": """
        SELECT count(*) AS coaches, count(*) FILTER (WHERE source_payload_hash IS NOT NULL) AS from_provider
          FROM core.coaches""",
}


def db_checks(conn: psycopg.Connection[Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for name, sql in CHECKS.items():
            cur.execute(sql)
            out[name] = [dict(r) for r in cur.fetchall()]
    return out


def sample(conn: psycopg.Connection[Any], *, n: int = 10, seed: float = 0.42) -> dict[str, list[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (seed,))
        cur.execute("SELECT DISTINCT t.provider_team_id FROM core.teams t JOIN core.fixtures f ON t.id IN "
                    "(f.home_team_id, f.away_team_id) JOIN core.competition_seasons cs ON cs.id = "
                    "f.competition_season_id WHERE cs.is_current ORDER BY 1")
        teams = [int(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT provider_player_id FROM core.players WHERE profile_fetched_at IS NOT NULL "
                    "ORDER BY random() LIMIT %s", (n,))
        players = [int(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT provider_coach_id FROM core.coaches ORDER BY random() LIMIT %s", (n // 2,))
        coaches = [int(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT provider_venue_id FROM core.venues WHERE provider_venue_id IS NOT NULL "
                    "ORDER BY random() LIMIT %s", (n // 2,))
        venues = [int(r[0]) for r in cur.fetchall()]
    import random

    rnd = random.Random(seed)
    return {"teams": rnd.sample(teams, min(n, len(teams))), "players": players, "coaches": coaches, "venues": venues}


async def provider_samples(run: V2Run, conn: psycopg.Connection[Any], ids: Mapping[str, list[int]]
                           ) -> dict[str, Tally]:
    tallies = {k: Tally(k) for k in ("teams", "players", "coaches", "venues")}
    for tid in ids["teams"]:
        a = await run.get("/teams", {"id": tid})
        compare.compare_team(a.items[0] if a and a.items else None, db_team(conn, tid), provider_team_id=tid,
                             tally=tallies["teams"])
    for pid in ids["players"]:
        a = await run.get("/players/profiles", {"player": pid})
        item = a.items[0] if a and a.items else None
        compare.compare_player(item, db_player(conn, pid), provider_player_id=pid, tally=tallies["players"])
    for cid in ids["coaches"]:
        a = await run.get("/coachs", {"id": cid})
        compare.compare_coach(a.items[0] if a and a.items else None, db_coach(conn, cid), provider_coach_id=cid,
                              tally=tallies["coaches"])
    for vid in ids["venues"]:
        a = await run.get("/venues", {"id": vid})
        t = tallies["venues"]
        t.compared()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT name, city, capacity, surface FROM core.venues WHERE provider_venue_id = %s", (vid,))
            ours = cur.fetchone()
        api = a.items[0] if a and a.items else None
        same = api is not None and ours is not None and all(
            compare._same_text(api.get(k), ours.get(k)) if k != "capacity" else compare._int(api.get(k)) ==
            compare._int(ours.get(k)) for k in ("name", "city", "capacity", "surface"))
        if same:
            t.matched += 1
        else:
            t.notes.append(f"venue {vid}: provider {None if api is None else {k: api.get(k) for k in ('name', 'city', 'capacity')}} "
                           f"ours {ours}")
    return tallies


def evidence(checks: Mapping[str, list[dict[str, Any]]], tallies: Mapping[str, Tally], at: datetime
             ) -> list[Evidence]:
    out = []
    dup_teams = checks.get("team_duplicates", [])
    if dup_teams:
        out.append(Evidence(key="identity:team_duplicates", area="identity", issue_type="DUPLICATE_ENTITY",
                            severity="medium", at_fault="undetermined", entity=f"{len(dup_teams)} names",
                            claim=f"{len(dup_teams)} team names occur twice in one country under different provider "
                                  "ids (a club and its namesake, or one club split in two)",
                            db={"examples": dup_teams[:10]},
                            fix="check each pair on the provider's team page; merge only through an alias map"))
    dup_players = checks.get("player_duplicates", [])
    if dup_players:
        out.append(Evidence(key="identity:player_duplicates", area="identity", issue_type="DUPLICATE_ENTITY",
                            severity="medium", at_fault="provider", entity=f"{len(dup_players)} people",
                            claim=f"{len(dup_players)} people (same full name and birth date) have two or more "
                                  "provider player ids: their statistics are split",
                            db={"examples": dup_players[:10]},
                            fix="an alias table provider_player_id -> canonical id, per provider evidence"))
    orphans = (checks.get("player_rows_without_profile") or [{}])[0].get("players") or 0
    if orphans:
        out.append(Evidence(key="identity:player_rows_without_profile", area="identity", issue_type="MAPPING_ERROR",
                            severity="low", at_fault="predigol", entity=f"{orphans} players",
                            claim=f"{orphans} provider player ids have match rows but no core.players row",
                            fix="fetch their profiles (/players/profiles?player)"))
    flags = (checks.get("national_flags") or [{}])[0]
    if flags.get("club_rows_in_national_comps") or flags.get("national_rows_in_club_comps"):
        out.append(Evidence(key="identity:national_flags", area="identity", issue_type="MAPPING_ERROR",
                            severity="medium", at_fault="predigol", entity="core.teams.is_national",
                            claim=f"is_national contradicts the competitions: {flags.get('club_rows_in_national_comps')} "
                                  f"non-national rows play national-team competitions, "
                                  f"{flags.get('national_rows_in_club_comps')} national rows play club competitions",
                            db=flags))
    for name, t in tallies.items():
        if t.total_findings or t.notes:
            out.append(Evidence(key=f"identity:sample:{name}", area="identity", issue_type="STALE_ENTITY",
                                severity="low", at_fault="undetermined", entity=f"{t.checked} sampled {name}",
                                claim=f"{t.total_findings or len(t.notes)} of {t.checked} sampled {name} differ from the "
                                      "provider's current record",
                                api={"findings": [f.as_dict() for f in t.findings[:8]], "notes": t.notes[:8]}))
    out.append(Evidence(key="identity:coach_career", area="coaches", issue_type="UNSUPPORTED_FIELD", severity="low",
                        at_fault="predigol", entity="core.coaches",
                        claim="/coachs returns each coach's career (team, start, end); PrediGol keeps only the person - "
                              "a coach's tenure at a team cannot be read from the database",
                        db=(checks.get("coach_career_stored") or [{}])[0],
                        fix="store the career as dated rows (coach, team, start, end, payload hash)"))
    out.append(Evidence(key="identity:keys", area="identity", issue_type="MAPPING_ERROR", severity="info",
                        at_fault="none", entity="core.* provider ids",
                        claim="Every entity is keyed by the provider's id column (provider_team_id, provider_player_id, "
                              "...) with one provider: correct today, but the provider is implicit - a second "
                              "source would need provider + provider_id",
                        fix="add a provider column to the identity keys before any second data source",
                        status="ACCEPTED"))
    return out

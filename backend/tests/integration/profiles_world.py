"""A small fictitious world for the profiles of C-09 (AD-H07, IA-090): two clubs and a national team, one league with a season
that ended (a title) and one in play, six finished matches and one ahead, a player with enough minutes and one without, the
provider's injury report, two facts of the press (one a rumour that carries a diagnosis) and a national team's matchday squad.

Names are fictitious and links end in ``.invalid``. ``build`` returns the ids; nothing is committed (the ``db`` fixture rolls
back)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)
DIAGNOSIS = "rotura del ligamento cruzado anterior, seis meses de baja"
"""Written in a rumour of the press: it must never appear in a profile."""


@dataclass(frozen=True)
class World:
    league_id: int
    season_id: int
    old_season_id: int
    club_id: int
    rival_id: int
    nation_id: int
    nation_rival_id: int
    striker_id: int
    striker_pid: int
    rookie_id: int
    rookie_pid: int
    next_fixture_id: int
    finished: tuple[int, ...]


def _one(cur: psycopg.Cursor, sql: str, params: tuple[object, ...] = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def build(conn: psycopg.Connection, payload_hash: str) -> World:
    h = payload_hash
    with conn.cursor() as cur:
        league = _one(cur, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                           "competition_type, is_tracked, logo_url) VALUES (99101, 'Liga Ejemplo', 'País Ejemplo', 'league', "
                           "'club', 'domestic_league', true, 'https://logo.invalid/99101.png') RETURNING id")
        season = _one(cur, "INSERT INTO core.competition_seasons (competition_id, season, start_date, end_date, is_current) "
                           "VALUES (%s, 2026, '2026-01-20', '2026-12-15', true) RETURNING id", (league,))
        old = _one(cur, "INSERT INTO core.competition_seasons (competition_id, season, start_date, end_date, is_current) "
                        "VALUES (%s, 2025, '2025-01-20', '2025-12-15', false) RETURNING id", (league,))
        friendlies = _one(cur, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                               "VALUES (99102, 'Amistosos Ejemplo', 'friendly', 'national_team', 'international') RETURNING id")
        f_season = _one(cur, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                        (friendlies,))
        venue = _one(cur, "INSERT INTO core.venues (provider_venue_id, name, city, capacity) "
                          "VALUES (99201, 'Estadio Ejemplo', 'Ciudad Ejemplo', 30000) RETURNING id")
        club = _one(cur, "INSERT INTO core.teams (provider_team_id, name, short_name, country, founded, venue_id, logo_url) "
                         "VALUES (99301, 'Club Ejemplo Norte', 'CEN', 'País Ejemplo', 1920, %s, "
                         "'https://crest.invalid/99301.png') RETURNING id", (venue,))
        rival = _one(cur, "INSERT INTO core.teams (provider_team_id, name, country) VALUES (99302, 'Club Ejemplo Este', "
                          "'País Ejemplo') RETURNING id")
        nation = _one(cur, "INSERT INTO core.teams (provider_team_id, name, country, is_national) VALUES (99303, "
                           "'Selección Ejemplo', 'Selección Ejemplo', true) RETURNING id")
        nation_rival = _one(cur, "INSERT INTO core.teams (provider_team_id, name, country, is_national) VALUES (99304, "
                                 "'Selección Muestra', 'Selección Muestra', true) RETURNING id")
        for team, national in ((club, False), (rival, False), (nation, True), (nation_rival, True)):
            cur.execute("INSERT INTO core.team_kind (team_id, is_national, basis, competitive_club_matches, national_matches, "
                        "club_friendly_matches, rule_version, refreshed_at) VALUES (%s, %s, 'test', 0, 0, 0, 'test', now())",
                        (team, national))
        striker = _one(cur, "INSERT INTO core.players (provider_player_id, name, birth_date, nationality, position) "
                            "VALUES (99401, 'J. Ejemplo', '2002-03-01', 'País Ejemplo', 'Attacker') RETURNING id")
        rookie = _one(cur, "INSERT INTO core.players (provider_player_id, name, birth_date, nationality, position) "
                           "VALUES (99402, 'B. Ejemplo', '2007-06-01', 'País Ejemplo', 'Defender') RETURNING id")

        finished: list[int] = []
        scores = ((2, 0), (1, 1), (0, 1), (3, 2), (2, 2), (1, 0))
        shots = (4, 3, None, 5, 2, 6)
        for i, (gh, ga) in enumerate(scores):
            kickoff = AT - timedelta(days=7 * (len(scores) - i))
            home, away = (club, rival) if i % 2 == 0 else (rival, club)
            fx = _one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                           "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                      (99500 + i, season, home, away, kickoff))
            finished.append(fx)
            cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                        (fx, gh, ga))
            side = "home" if home == club else "away"
            if i < 3:
                cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, shots_on_target, "
                            "corners, yellow_cards, expected_goals, payload_hash, fetched_at) "
                            "VALUES (%s, %s, 'api-football', 12, 5, 6, 2, 1.40, %s, %s)", (fx, side, h, kickoff))
            cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, "
                        "minutes, is_substitute, shots_total, shots_on, goals, assists, fouls_committed, yellow_cards, "
                        "red_cards, payload_hash, fetched_at) VALUES (%s, 'api-football', 99401, %s, 'J. Ejemplo', 90, false, "
                        "%s, %s, %s, 0, 1, 0, 0, %s, %s)",
                        (fx, side, shots[i], None if shots[i] is None else 2, 1 if i in (0, 3) else 0, h, kickoff))
            if i >= 4:
                cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, "
                            "player_name, minutes, is_substitute, shots_total, goals, payload_hash, fetched_at) "
                            "VALUES (%s, 'api-football', 99402, %s, 'B. Ejemplo', 90, false, 0, 0, %s, %s)",
                            (fx, side, h, kickoff))
        for fx, side in ((finished[-1], "away"), (finished[-2], "home")):  # the coach of the club's newest sheets
            cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, provider_coach_id, coach_name, "
                        "payload_hash, fetched_at) VALUES (%s, %s, 'api-football', 99601, 'G. Ejemplo', %s, %s)",
                        (fx, side, h, AT - timedelta(days=7)))
        nxt = _one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at) VALUES (99510, %s, %s, %s, %s) RETURNING id", (season, club, rival, AT + timedelta(days=1)))

        # a selection of the cycle in shadow for the next match: only the private section may show it
        cur.execute("INSERT INTO intel.selection_lifecycle (chain_key, writer, fixture_id, market_key, selection, line, layer, "
                    "state, reason, actor, known_at, source, machine_version) VALUES (%s, 'shadow-test', %s, '1X2', 'home', 0, "
                    "'decision-v1', 'detectado', 'candidato_nuevo', 'code', %s, 'test.lifecycle', 'lifecycle-v1')",
                    (f"shadow-test|{nxt}|1X2|home|0.00", nxt, AT - timedelta(hours=5)))
        for pid, name, shirt, pos in ((99401, "J. Ejemplo", 9, "Attacker"), (99402, "B. Ejemplo", 4, "Defender")):
            cur.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, shirt_number, position, age, "
                        "first_seen_at, last_seen_at, payload_hash) VALUES (%s, %s, %s, %s, %s, 20, %s, %s, %s)",
                        (club, pid, name, shirt, pos, AT - timedelta(days=60), AT - timedelta(days=2), h))

        # the provider's report: the season was asked for; it names the rookie (a red card)
        cur.execute("INSERT INTO core.context_checks (competition_season_id, dataset, checked_at) VALUES (%s, 'injuries', %s)",
                    (season, AT - timedelta(hours=3)))
        cur.execute("INSERT INTO core.player_availability_obs (fixture_id, source, provider_player_id, observed_at, status, "
                    "provider_fixture_id, provider_team_id, player_name, absence_type, reason, payload_hash, origin, "
                    "normalizer_version) VALUES (%s, 'api-football', 99402, %s, 'LISTED', 99510, 99301, 'B. Ejemplo', "
                    "'Missing Fixture', 'Red Card', %s, 'answer', 'test')", (nxt, AT - timedelta(hours=4), h))
        # the press: a rumour with a diagnosis (changes nothing), and one outlet saying he is doubtful (the provider wins)
        for status, n in (("RUMOR", 1), ("PROBABLE", 2)):
            cur.execute(
                "INSERT INTO ai.evidence (fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, "
                "source_domain, source_tier, retrieved_at, story_key, content_hash, confidence, relevance, attributes, status, "
                "status_reason, status_changed_at) VALUES (%s, %s, 99401, 'injury', %s, 'web', 'Diario Ejemplo', "
                "'https://diario.invalid/nota', 'diario.invalid', 'media', %s, %s, %s, 0.5, 0.5, %s, %s, 'test', %s)",
                (nxt, club, f"J. Ejemplo: {DIAGNOSIS}", AT - timedelta(hours=n), f"story-{n}", f"hash-{n}",
                 Jsonb({"assertion": "doubtful", "player_name": "J. Ejemplo"}), status, AT - timedelta(hours=n)))

        # tables: the old season ended with the club first, played as one league stage; the current one in play
        cur.execute("INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, role, "
                    "rule, numbered, fixtures, first_kickoff_at, last_kickoff_at, stages_version, ties_version, build_hash) "
                    "VALUES (%s, 'Regular Season', 1, 'Regular Season', 'Regular Season', 'league', 'league', 'test', true, 10, "
                    "'2025-02-01', '2025-12-01', 'test', 'test', 'test')", (old,))
        for sid, at, rows in ((old, datetime(2025, 12, 10, tzinfo=UTC), ((club, 1, 60), (rival, 2, 55))),
                              (season, AT - timedelta(days=1), ((rival, 1, 30), (club, 2, 28)))):
            for team, rank, points in rows:
                cur.execute("INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, "
                            "wins, draws, losses, goals_for, goals_against) "
                            "VALUES (%s, %s, %s, %s, %s, 20, 8, 4, 8, 25, 20)", (sid, team, at, rank, points))

        # the national team: one match with its matchday squad; the striker started and played
        nfx = _one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                        "kickoff_at, status_short, status_group) VALUES (99520, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                   (f_season, nation, nation_rival, AT - timedelta(days=4)))
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)", (nfx,))
        cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                    "VALUES (%s, 'home', 'api-football', %s, %s)", (nfx, h, AT - timedelta(days=4)))
        cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, "
                    "shirt_number, position, is_starter) VALUES (%s, 'home', 'api-football', 99401, 'J. Ejemplo', 9, 'F', true)",
                    (nfx,))
        cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, "
                    "minutes, is_substitute, goals, payload_hash, fetched_at) VALUES (%s, 'api-football', 99401, 'home', "
                    "'J. Ejemplo', 90, false, 1, %s, %s)", (nfx, h, AT - timedelta(days=4)))
        cur.execute("INSERT INTO core.player_national_caps (provider_player_id, fixture_id, team_id, is_starter, appeared, "
                    "minutes, version) VALUES (99401, %s, %s, true, true, 90, 'test')", (nfx, nation))
    return World(league, season, old, club, rival, nation, nation_rival, striker, 99401, rookie, 99402, nxt, tuple(finished))

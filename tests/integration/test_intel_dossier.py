"""The match dossier (``fbi.intel.dossier``, packet-v2) on a built world, and its no-leakage rule: three past matches of
the home side with statistics, events, line-ups, players and a referee - and a fourth whose statistics were fetched
AFTER the packet's moment, which the dossier must not see."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai.packet import PacketBuilder
from fbi.intel.dossier import scoreline_behaviour
from fbi.intel.narrative import SECTIONS, rules_narrative

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 10, 5, 12, tzinfo=UTC)


def _fixture(cur: psycopg.Cursor[Any], season: int, home: int, away: int, kickoff: datetime, n: int) -> int:
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                (9890000 + n, season, home, away, kickoff))
    return int(scalar(cur))


def test_the_dossier_reads_only_what_was_known(db: psycopg.Connection[Any], seed: Seed) -> None:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                "competition_type, is_tracked) VALUES (98901, 'Dossier League', 'Colombia', 'league', 'club', "
                "'domestic_league', true) RETURNING id")
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2032, true) "
                "RETURNING id", (comp,))
    season = scalar(cur)
    teams = []
    for i in range(4):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                    (989100 + i, f"Dossier {i}"))
        teams.append(scalar(cur))
    h = seed.payload_hash
    past = []
    for n, (gh, ga) in enumerate(((2, 1), (0, 0), (3, 1))):
        ko = AT - timedelta(days=21 - 7 * n)
        fid = _fixture(cur, season, teams[0], teams[1 + n % 3], ko, n)
        past.append(fid)
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) "
                    "VALUES (%s, %s, %s, %s)", (fid, gh, ga, ko + timedelta(hours=2)))
        for side, yc, fouls, xg in (("home", 2, 11, 1.8), ("away", 3, 14, 0.7)):
            cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, shots_on_target, "
                        "corners, fouls, yellow_cards, red_cards, offsides, possession_pct, expected_goals, "
                        "payload_hash, fetched_at) VALUES (%s,%s,'api-football',12,5,6,%s,%s,0,2,55,%s,%s,%s)",
                        (fid, side, fouls, yc, xg, h, ko + timedelta(hours=3)))
        cur.execute("INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, payload_hash, normalizer_version) "
                    "VALUES (%s, %s, 'R. Tester', %s, 'v1')", (fid, ko - timedelta(days=1), h))
        cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, coach_name, "
                    "payload_hash, fetched_at) VALUES (%s, 'home', 'api-football', %s, 'C. Coach', %s, %s)",
                    (fid, "4-3-3" if n < 2 else "4-4-2", h, ko - timedelta(minutes=50)))
        for pid in range(11):
            cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, "
                        "is_starter) VALUES (%s, 'home', 'api-football', %s, true)",
                        (fid, 600 + pid + 10 * n if pid < 2 else 500 + pid))
        seq = 0
        goals = [("home", 10 + 20 * k) for k in range(gh)] + [("away", 15 + 20 * k) for k in range(ga)]
        for side, minute in sorted(goals, key=lambda g: g[1]):
            cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
                        "payload_hash, fetched_at) VALUES (%s,'api-football',%s,%s,%s,'Goal',%s,%s,%s)",
                        (fid, seq, minute, side, "Penalty" if minute == 10 else "Normal Goal", h, ko + timedelta(hours=3)))
            seq += 1
        cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
                    "payload_hash, fetched_at) VALUES (%s,'api-football',%s,60,'home','subst','Substitution 1',%s,%s)",
                    (fid, seq, h, ko + timedelta(hours=3)))
        cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, "
                    "player_name, minutes, is_substitute, goals, assists, shots_total, payload_hash, fetched_at) "
                    "VALUES (%s,'api-football',500,'home','Star Nine',90,false,%s,0,4,%s,%s)",
                    (fid, gh, h, ko + timedelta(hours=3)))
    # the opponents' Elo before each match (1500, 1600, 1700) and the side's own (1900, never an opponent's)
    cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at, finished_at) "
                "VALUES ('t', 'elo_refresh', 'completed', %s, %s) RETURNING id",
                (AT - timedelta(days=1, minutes=5), AT - timedelta(days=1)))
    elo_run = scalar(cur)
    for n, fid in enumerate(past):
        for team, rating in ((teams[1 + n % 3], 1500 + 100 * n), (teams[0], 1900)):
            cur.execute("INSERT INTO features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, "
                        "rating_before, rating_after, expected_score, actual_score, k_factor, margin_multiplier, "
                        "computed_at) VALUES ('zzz-dossier-test', %s, %s, %s, %s, %s, %s, 0.5, 1, 20, 1, %s)",
                        (elo_run, team, fid, AT - timedelta(days=21 - 7 * n), rating, rating,
                         AT - timedelta(days=1)))
    # a fourth match whose statistics arrived only after AT: invisible to a packet built at AT
    late = _fixture(cur, season, teams[0], teams[3], AT - timedelta(days=1), 9)
    cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) "
                "VALUES (%s, 5, 0, %s)", (late, AT + timedelta(hours=1)))
    upcoming = _fixture(cur, season, teams[0], teams[1], AT + timedelta(hours=6), 20)
    db.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s", (upcoming,))
    cur.execute("INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, payload_hash, normalizer_version) "
                "VALUES (%s, %s, 'R. Tester', %s, 'v1')", (upcoming, AT - timedelta(hours=2), h))

    packet = PacketBuilder(db).build(upcoming, at=AT)
    assert packet is not None and packet.version == "packet-v2"
    d = packet.content["dossier"]
    home = d["teams"]["home"]
    assert home["n"] == 3, "the 5-0 settled after AT is not known at AT"
    assert home["all"]["wins"] == 2 and home["all"]["draws"] == 1
    assert home["all"]["xg_for"] == 1.8 and home["all"]["fouls"] == 11.0 and home["all"]["cards"] == 2.0
    assert home["all"]["penalties_for"] == 2
    assert home["coach"]["name"] == "C. Coach" and home["coach"]["main_formation"] == "4-3-3"
    assert home["coach"]["rotation_avg_changes"] == 2.0, "two starters change between consecutive matches"
    assert home["coach"]["first_sub_minute"] == 60
    assert home["scoreline"]["scored_first"] == 2 and home["scoreline"]["leads_lost"] == 0
    assert home["opponents"] == {"n": 3, "mean_elo": 1600}, "the opponents' Elo, read by team on the primary key"
    ref = d["referee"]
    assert ref["name"] == "R. Tester" and ref["matches"] == 3 and ref["cards_per_match"] == 5.0
    assert ref["fouls_per_match"] == 25.0 and ref["penalties_per_match"] == round(2 / 3, 3)
    star = d["players"]["home"][0]
    assert star["name"] == "Star Nine" and star["goals"] == 5 and star["starts"] == 3
    assert d["h2h"]["n"] >= 1
    nar = rules_narrative(packet.content, [])
    assert set(nar) == set(SECTIONS) and "Dossier 0" in nar["como_llega_local"]
    assert "4-3-3" in nar["claves_tacticas"] and "R. Tester" in nar["riesgos"]


def test_scoreline_behaviour() -> None:
    evs = [{"event_type": "Goal", "detail": "Normal Goal", "team_side": "away", "comments": None},
           {"event_type": "Goal", "detail": "Normal Goal", "team_side": "home", "comments": None},
           {"event_type": "Goal", "detail": "Normal Goal", "team_side": "home", "comments": None}]
    b = scoreline_behaviour(evs, "home", 2, 1)
    assert b == {"scored_first": False, "conceded_first": True, "led": True, "trailed": True, "won": True,
                 "drew": False, "lost": False}


def test_the_opponents_elo_is_read_by_team_on_the_primary_key(db: psycopg.Connection[Any]) -> None:
    """Regression (13 Oct 2026): by fixture alone the query read the whole run (0.24-0.75 s per team on production)."""
    from fbi.intel.dossier import ELO_SQL

    db.execute("SET LOCAL enable_seqscan = off")  # a test table is tiny: ask for the path production's size forces
    plan = "\n".join(str(r[0]) for r in db.execute(
        "EXPLAIN " + ELO_SQL, {"version": "elo-v1", "run": 1, "teams": [1, 2], "fixtures": [10, 11]}).fetchall())
    assert "team_id = ANY" in plan and "Index Cond" in plan, plan

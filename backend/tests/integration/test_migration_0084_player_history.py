"""Migrations 0084 (a player's streaks at clubs, his national caps, the careers of the coaches tied to people and teams) and 0085 (an index
on the squad sheets by player, built without blocking the writers): additive, non-blocking and reversible.

Deploying must change nothing the system does: 0084 only ADDS two tables, a view and two nullable columns, the careers that exist keep
every value they had and read NULL in the new columns. Run on a scratch database at revision 0083 that already holds a coach's careers
and a match with its squad sheets, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0084"
NEW_TABLES = ("core.player_spells", "core.player_national_caps")
NEW_COLUMNS = ("coach_id", "team_id")
INDEX = "fixture_lineup_players_player"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> dict[str, Any]:
    """What exists that the migrations must not change: every column (but the two they add) and the careers themselves."""
    cols = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'analytics') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    kept = [r for r in cols if f"{r[0]}.{r[1]}" not in NEW_TABLES and r[1] != "coach_spells"
            and not (r[0] == "core" and r[1] == "coach_careers" and r[2] in NEW_COLUMNS)]
    careers = c.execute("SELECT provider_coach_id, observed_at, ordinal, provider_team_id, team_name, start_date, end_date, "
                        "payload_hash, normalizer_version FROM core.coach_careers ORDER BY 1, 2, 3").fetchall()
    return {"columns": kept, "careers": careers}


def _index(c: psycopg.Connection[Any]) -> tuple[str, bool] | None:
    row = c.execute("SELECT i.indexdef, x.indisvalid FROM pg_indexes i JOIN pg_class k ON k.relname = i.indexname "
                    "JOIN pg_namespace n ON n.oid = k.relnamespace AND n.nspname = i.schemaname "
                    "JOIN pg_index x ON x.indexrelid = k.oid WHERE i.schemaname = 'core' AND i.indexname = %s", (INDEX,)).fetchone()
    return None if row is None else (str(row[0]), bool(row[1]))


def _seed(c: psycopg.Connection[Any]) -> dict[str, Any]:
    comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                     "VALUES (10, 'Friendlies', 'cup', 'national_team', 'international') RETURNING id").fetchone()
    assert comp is not None
    season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                       (comp[0],)).fetchone()
    home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (33, 'Spain') RETURNING id").fetchone()
    away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (34, 'Italy') RETURNING id").fetchone()
    assert season is not None and home is not None and away is not None
    fixture = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                        "VALUES (1001, %s, %s, %s, '2026-10-17 15:00Z') RETURNING id", (season[0], home[0], away[0])).fetchone()
    run = c.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                    "VALUES ('t', 'reference', 'completed', now()) RETURNING id").fetchone()
    assert fixture is not None and run is not None
    c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
              "VALUES ('coachs-1', %s, '/coachs', '2026-10-01 10:00Z', 200, 'x', 1), "
              "('lineups-1', %s, '/fixtures/lineups', '2026-10-17 14:00Z', 200, 'y', 1)", (run[0], run[0]))
    for ordinal, (team, name, start, end) in enumerate([(33, "Spain", "2018-07-01", "2022-12-10"), (34, "Italy", "2023-01-01", None)]):
        c.execute("INSERT INTO core.coach_careers (provider_coach_id, observed_at, ordinal, provider_team_id, team_name, start_date, "
                  "end_date, payload_hash, normalizer_version) VALUES (77, '2026-10-01 10:00Z', %s, %s, %s, %s, %s, 'coachs-1', 'v1')",
                  (ordinal, team, name, start, end))
    # an older snapshot of the same career: the view must not show it
    c.execute("INSERT INTO core.coach_careers (provider_coach_id, observed_at, ordinal, provider_team_id, team_name, start_date, "
              "end_date, payload_hash, normalizer_version) VALUES (77, '2026-09-01 10:00Z', 0, 33, 'Spain', '2018-07-01', NULL, "
              "'coachs-1', 'v1')")
    c.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) VALUES "
              "(%s, 'home', 'api-football', 'lineups-1', '2026-10-17 14:00Z')", (fixture[0],))
    for player in (9001, 9002):
        c.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) "
                  "VALUES (%s, 'home', 'api-football', %s, true)", (fixture[0], player))
    coach = c.execute("INSERT INTO core.coaches (provider_coach_id, name) VALUES (77, 'A. Coach') RETURNING id").fetchone()
    assert coach is not None
    c.commit()
    return {"fixture": fixture[0], "home": home[0], "away": away[0], "coach": coach[0]}


def test_0084_and_0085_add_two_tables_a_view_two_null_columns_and_an_index_and_come_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0083")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW_TABLES) and not _exists(c, "core.coach_spells")
            ids = _seed(c)
            before = _shape(c)
            assert _index(c) is None

        command.upgrade(_cfg(), "0084")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW_TABLES) and _exists(c, "core.coach_spells")
            assert _shape(c) == before, "nothing that existed was changed"
            assert _index(c) is None, "0085 is a separate revision"
            for table in NEW_TABLES:
                assert c.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
            assert c.execute("SELECT coach_id, team_id FROM core.coach_careers").fetchall() == [(None, None)] * 3, (
                "no link is invented by the migration: linking is a separate, visible step")
            columns = {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'core' AND table_name = 'coach_careers' AND column_name = ANY(%s)", (list(NEW_COLUMNS),)).fetchall()}
            assert columns == dict.fromkeys(NEW_COLUMNS, ("YES", None)), "nullable and without a default (instant on a live table)"
            assert c.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'core.coach_careers'::regclass "
                             "AND NOT convalidated").fetchall() == [], "the foreign keys were added NOT VALID and validated in the same revision"
            indexes = {r[0]: r[1] for r in c.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'core' AND indexname = ANY(%s)",
                (["player_spells_club", "player_national_caps_fixture", "player_national_caps_open", "coach_careers_coach",
                  "coach_careers_team"],)).fetchall()}
            assert set(indexes) == {"player_spells_club", "player_national_caps_fixture", "player_national_caps_open",
                                    "coach_careers_coach", "coach_careers_team"}
            assert "WHERE (appeared IS NULL)" in indexes["player_national_caps_open"]
            assert "WHERE (coach_id IS NOT NULL)" in indexes["coach_careers_coach"]
            assert "WHERE (team_id IS NOT NULL)" in indexes["coach_careers_team"]

            # the careers can be linked, and the view shows the newest snapshot of each career with the links
            c.execute("UPDATE core.coach_careers SET coach_id = %s, team_id = %s WHERE provider_team_id = 33", (ids["coach"], ids["home"]))
            c.execute("UPDATE core.coach_careers SET coach_id = %s, team_id = %s WHERE provider_team_id = 34", (ids["coach"], ids["away"]))
            rows = c.execute("SELECT provider_coach_id, coach_id, provider_team_id, team_id, team_name, start_date::text, end_date::text "
                             "FROM core.coach_spells ORDER BY start_date").fetchall()
            assert rows == [(77, ids["coach"], 33, ids["home"], "Spain", "2018-07-01", "2022-12-10"),
                            (77, ids["coach"], 34, ids["away"], "Italy", "2023-01-01", None)], "the older snapshot is not there"
            c.commit()

            # a streak and a cap can be written, and the tables refuse what the readers could not mean
            c.execute("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, valid_from, valid_to, source, "
                      "last_evidence, version) VALUES (9001, 0, 33, '2025-07-01', '2026-01-10', 'transfer', '2025-07-01', 'spells-v1')")
            c.execute("INSERT INTO core.player_national_caps (provider_player_id, fixture_id, team_id, is_starter, appeared, minutes, "
                      "version) VALUES (9001, %s, %s, true, true, 90, 'caps-v1')", (ids["fixture"], ids["home"]))
            c.commit()
            spell = ("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, valid_from, valid_to, source, "
                     "matches, last_evidence, version) VALUES ({}) ")
            cap = ("INSERT INTO core.player_national_caps (provider_player_id, fixture_id, team_id, is_starter, appeared, minutes, "
                   "version) VALUES ({})")
            fx, home = ids["fixture"], ids["home"]
            refused = {
                "a player that is not one": (spell.format("0, 0, 33, NULL, NULL, 'lineup', 0, '2025-07-01', 'v'"), "player_spells_player_check"),
                "a negative position": (spell.format("9002, -1, 33, NULL, NULL, 'lineup', 0, '2025-07-01', 'v'"), "player_spells_ordinal_check"),
                "a source nobody reads": (spell.format("9002, 0, 33, NULL, NULL, 'rumour', 0, '2025-07-01', 'v'"), "player_spells_source_check"),
                "a negative number of matches": (spell.format("9002, 0, 33, NULL, NULL, 'lineup', -1, '2025-07-01', 'v'"),
                                                 "player_spells_matches_check"),
                "no version": (spell.format("9002, 0, 33, NULL, NULL, 'lineup', 0, '2025-07-01', ' '"), "player_spells_version_check"),
                "a streak that ends before it starts": (spell.format("9002, 0, 33, '2026-02-01', '2026-01-01', 'lineup', 0, '2026-01-01', 'v'"),
                                                        "player_spells_in_order"),
                "a streak of no days": (spell.format("9002, 0, 33, '2026-02-01', '2026-02-01', 'lineup', 0, '2026-01-01', 'v'"),
                                        "player_spells_in_order"),
                "an unknown start after the first streak": (spell.format("9002, 1, 33, NULL, NULL, 'lineup', 0, '2025-07-01', 'v'"),
                                                             "player_spells_start_known"),
                "the same position twice": (spell.format("9001, 0, 34, NULL, NULL, 'lineup', 0, '2025-07-01', 'v'"), "player_spells_pkey"),
                "a cap of a player that is not one": (cap.format(f"0, {fx}, {home}, true, true, 90, 'v'"), "player_national_caps_player_check"),
                "a cap of a match that does not exist": (cap.format(f"9002, 999999, {home}, true, true, 90, 'v'"),
                                                         "player_national_caps_fixture_fk"),
                "a cap for a team that does not exist": (cap.format(f"9002, {fx}, 999999, true, true, 90, 'v'"), "player_national_caps_team_fk"),
                "negative minutes": (cap.format(f"9002, {fx}, {home}, true, true, -1, 'v'"), "player_national_caps_minutes_check"),
                "minutes of a man who did not play": (cap.format(f"9002, {fx}, {home}, false, false, 20, 'v'"),
                                                      "player_national_caps_minutes_iff_played"),
                "minutes of a man we cannot say played": (cap.format(f"9002, {fx}, {home}, false, NULL, 20, 'v'"),
                                                          "player_national_caps_minutes_iff_played"),
                "no version in a cap": (cap.format(f"9002, {fx}, {home}, true, true, 90, ''"), "player_national_caps_version_check"),
                "the same man twice in a match": (cap.format(f"9001, {fx}, {home}, false, NULL, NULL, 'v'"), "player_national_caps_pkey"),
                "a career of a coach that does not exist": ("UPDATE core.coach_careers SET coach_id = 999999", "coach_careers_coach_fk"),
                "a career at a club that does not exist": ("UPDATE core.coach_careers SET team_id = 999999", "coach_careers_team_fk"),
            }
            for what, (sql, constraint) in refused.items():
                with pytest.raises(psycopg.errors.IntegrityError) as caught:
                    c.execute(sql)
                assert caught.value.diag.constraint_name == constraint, f"{what}: refused by {caught.value.diag.constraint_name}"
                c.rollback()
            # a streak with an unknown start and an open end is fine as the first of the player
            c.execute(spell.format("9003, 0, 33, NULL, NULL, 'squad', 0, '2025-07-01', 'v'"))
            c.rollback()

            # a match that goes takes its caps with it (the match is not ours to keep alive)
            c.execute("DELETE FROM core.fixture_lineup_players")
            c.execute("DELETE FROM core.fixture_lineups")
            c.execute("DELETE FROM core.fixtures")
            assert c.execute("SELECT count(*) FROM core.player_national_caps").fetchone() == (0,)
            c.rollback()

        # an interrupted concurrent build leaves an INVALID index of the same name: 0085 replaces it
        with psycopg.connect(dsn, autocommit=True) as c:
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(f"CREATE UNIQUE INDEX CONCURRENTLY {INDEX} ON core.fixture_lineup_players (team_side)")
            invalid = _index(c)
            assert invalid is not None and invalid[1] is False

        command.upgrade(_cfg(), "0085")
        with psycopg.connect(dsn) as c:
            index = _index(c)
            assert index is not None and index[1] is True, "built, and valid"
            assert "(provider_player_id, fixture_id)" in index[0] and "UNIQUE" not in index[0]
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0085",)
            used = c.execute("SET LOCAL enable_seqscan = off")  # noqa: F841 - the planner can reach a man's matches through it
            plan = "\n".join(r[0] for r in c.execute("EXPLAIN SELECT fixture_id FROM core.fixture_lineup_players "
                                                     "WHERE provider_player_id = 9001").fetchall())
            assert INDEX in plan
            c.rollback()

        command.downgrade(_cfg(), "0084")
        with psycopg.connect(dsn) as c:
            assert _index(c) is None
            assert all(_exists(c, t) for t in NEW_TABLES)

        command.downgrade(_cfg(), "0083")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW_TABLES) and not _exists(c, "core.coach_spells")
            names = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns "
                                            "WHERE table_schema = 'core' AND table_name = 'coach_careers'").fetchall()}
            assert not names & set(NEW_COLUMNS)
            assert _shape(c) == before, "and the careers are as they were"

        command.upgrade(_cfg(), "0085")  # and both apply again, in one run
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW_TABLES)
            index = _index(c)
            assert index is not None and index[1] is True
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()

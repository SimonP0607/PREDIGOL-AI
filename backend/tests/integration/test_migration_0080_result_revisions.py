"""Migration 0080 (result revisions and the re-settlement trail) over a database that already holds results.

The revision is additive: matches and results that exist before it are not touched, and the history starts empty
(what was corrected before the revision was never recorded; nothing is invented for it). Run on a scratch database at
revision 0079 with matches in place, the way production is, then up, down and up again."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0080"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _one(c: psycopg.Connection[Any], sql: str, *params: Any) -> tuple[Any, ...]:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _world(c: psycopg.Connection[Any]) -> dict[str, int]:
    """A season with three matches: finished with a result, scheduled, finished with a 0-0."""
    competition = _one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                          "competition_type) VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') "
                          "RETURNING id")[0]
    season = _one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id",
                  competition)[0]
    teams = [_one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                  100 + n, f"Team {n}")[0] for n in range(6)]
    ids: dict[str, int] = {}
    for key, (home, away), status, group in (("finished", (0, 1), "FT", "finished"),
                                              ("scheduled", (2, 3), "NS", "scheduled"),
                                              ("goalless", (4, 5), "FT", "finished")):
        ids[key] = _one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                           "away_team_id, kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, "
                           "'2026-09-15 19:00Z', %s, %s) RETURNING id",
                        900 + len(ids), season, teams[home], teams[away], status, group)[0]
    c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away) "
              "VALUES (%s, 2, 1, 2, 1), (%s, 0, 0, 0, 0)", (ids["finished"], ids["goalless"]))
    return ids


def test_0080_adds_the_history_without_touching_what_exists_and_goes_back(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0079")
        with psycopg.connect(dsn) as c:
            ids = _world(c)
            c.commit()
            fixtures_before = c.execute("SELECT * FROM core.fixtures ORDER BY id").fetchall()
            results_before = c.execute("SELECT * FROM core.fixture_results ORDER BY fixture_id").fetchall()
            assert c.execute("SELECT to_regclass('core.fixture_result_revisions')").fetchone() == (None,)

        command.upgrade(_cfg(), "0080")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT * FROM core.fixtures ORDER BY id").fetchall() == fixtures_before
            assert c.execute("SELECT * FROM core.fixture_results ORDER BY fixture_id").fetchall() == results_before
            assert _one(c, "SELECT count(*) FROM core.fixture_result_revisions") == (0,), (
                "what was corrected before this revision was never recorded, and nothing is invented for it")
            assert _one(c, "SELECT count(*) FROM picks.resettlements") == (0,)

            # the new column: every event is a 'status' unless it says otherwise
            col = _one(c, "SELECT is_nullable, column_default FROM information_schema.columns "
                          "WHERE table_schema = 'picks' AND table_name = 'pick_events' AND column_name = 'event_kind'")
            assert col[0] == "NO" and "'status'" in col[1]

            # the pick's record view reads only status events and counts the corrections
            def view_columns() -> set[str]:
                return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE "
                                                "table_schema = 'picks' AND table_name = 'v_pick_record'").fetchall()}

            assert {"status_before_settlement", "resettlements"} <= view_columns()
            assert _one(c, "SELECT count(*) FROM picks.v_pick_record") == (0,)
            assert "event_kind" in _one(c, "SELECT pg_get_viewdef('picks.v_pick_record'::regclass)")[0]

            # the writers of the history cannot be skipped by a role without rights on it, and cannot be hijacked
            for name in ("log_result_revision", "log_status_revision"):
                secdef, config = _one(c, "SELECT prosecdef, proconfig FROM pg_proc p JOIN pg_namespace n "
                                         "ON n.oid = p.pronamespace WHERE n.nspname = 'core' AND proname = %s", name)
                assert secdef is True and config == ["search_path=pg_catalog, pg_temp"]
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").fetchall()}
            assert {"fixture_results_revision", "fixtures_status_revision", "fixture_result_revisions_no_update",
                    "resettlements_no_update"} <= triggers

            # from now on a correction is recorded; a first read, a replay and the match being played are not
            c.execute("UPDATE core.fixture_results SET goals_home = 2, goals_away = 2, ft_goals_away = 2 "
                      "WHERE fixture_id = %s", (ids["finished"],))
            c.execute("UPDATE core.fixture_results SET goals_home = 1, ft_goals_home = 1 WHERE fixture_id = %s",
                      (ids["goalless"],))
            c.execute("UPDATE core.fixture_results SET goals_home = goals_home WHERE fixture_id = %s",
                      (ids["finished"],))  # a write that changes nothing is not a correction
            c.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s",
                      (ids["scheduled"],))
            c.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                      (ids["scheduled"],))
            c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 1, 0)",
                      (ids["scheduled"],))
            rows = c.execute("SELECT fixture_id, kind, changed FROM core.fixture_result_revisions ORDER BY id"
                             ).fetchall()
            assert [(r[0], r[1], sorted(r[2])) for r in rows] == [
                (ids["finished"], "score", ["ft_goals_away", "goals_away", "reg_goals_away"]),
                (ids["goalless"], "score", ["ft_goals_home", "goals_home", "reg_goals_home"])]
            old, new = _one(c, "SELECT old_state, new_state FROM core.fixture_result_revisions WHERE fixture_id = %s",
                            ids["finished"])
            assert (old["goals_home"], old["goals_away"]) == (2, 1) and (new["goals_home"], new["goals_away"]) == (2, 2)
            c.commit()

            # the trail refuses what is not a change, a blank reason, an unknown kind, and any edit
            ok = ("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, from_status, from_profit, "
                  "to_status, to_profit, rule_version, reason) VALUES (now(), %s, '1', %s, %s, %s, %s, %s, 'settle-v4', %s)")
            c.execute(ok, ("pick", ids["finished"], "win", 1.1, "loss", -1, "the provider corrected the score"))
            c.commit()
            refused = (
                (("pick", ids["finished"], "win", 1.1, "win", 1.1, "nothing changed"), psycopg.errors.CheckViolation),
                (("pick", ids["finished"], "win", 1.1, "loss", -1, "   "), psycopg.errors.CheckViolation),
                (("bet", ids["finished"], "win", 1.1, "loss", -1, "an unknown kind"), psycopg.errors.CheckViolation),
            )
            for params, error in refused:
                with pytest.raises(error):
                    c.execute(ok, params)
                c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation, match="never edited"):
                c.execute("UPDATE picks.resettlements SET reason = 'edited quietly afterwards'")
            c.rollback()
            c.execute("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, from_status, "
                      "to_status, rule_version, reason) VALUES (now(), 'parlay', '9', %s, 'WON', 'LOST', "
                      "'settle-v4', 'same profit is allowed when the status changes')", (ids["finished"],))
            c.commit()

            # the history of corrections refuses what is not a correction, an unknown kind, and a silent edit
            revision = ("INSERT INTO core.fixture_result_revisions (fixture_id, kind, old_state, new_state, changed) "
                        "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)")
            bad_revisions: list[tuple[Any, ...]] = [
                (ids["finished"], "score", '{"goals_home": 1}', '{"goals_home": 1}', ["goals_home"]),  # the same state
                (ids["finished"], "score", '{"goals_home": 1}', '{"goals_home": 2}', []),  # says nothing changed
                (ids["finished"], "lineup", '{"goals_home": 1}', '{"goals_home": 2}', ["goals_home"]),  # unknown kind
            ]
            for values in bad_revisions:
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(revision, values)
                c.rollback()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):  # a correction of a match that does not exist
                c.execute(revision, (0, "score", '{"goals_home": 1}', '{"goals_home": 2}', ["goals_home"]))
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation, match="never edited"):
                c.execute("UPDATE core.fixture_result_revisions SET changed = ARRAY['quietly']")
            c.rollback()
            assert _one(c, "SELECT count(*) FROM core.fixture_result_revisions") == (2,), "only the two real ones"

            # the revision a row of the trail answers cannot be deleted from under it (the history is never edited)
            revision_id = _one(c, "SELECT id FROM core.fixture_result_revisions WHERE fixture_id = %s",
                               ids["goalless"])[0]
            c.execute("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, revision_id, "
                      "from_status, from_profit, to_status, to_profit, rule_version, reason) VALUES (now(), 'pick', "
                      "'2', %s, %s, 'win', 1.1, 'loss', -1, 'settle-v4', 'answers a revision')",
                      (ids["goalless"], revision_id))
            c.commit()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("DELETE FROM core.fixture_result_revisions WHERE id = %s", (revision_id,))
            c.rollback()
            assert _one(c, "SELECT revision_id FROM picks.resettlements WHERE record_key = '2'") == (revision_id,)

        command.downgrade(_cfg(), "0079")
        with psycopg.connect(dsn) as c:
            for relation in ("core.fixture_result_revisions", "picks.resettlements"):
                assert _one(c, "SELECT to_regclass(%s)", relation) == (None,)
            for proc in ("core.log_result_revision()", "core.log_status_revision()", "core.refuse_history_update()"):
                assert _one(c, "SELECT to_regprocedure(%s)", proc) == (None,)
            assert c.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'pick_events' "
                             "AND column_name = 'event_kind'").fetchone() is None
            columns = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE "
                                               "table_schema = 'picks' AND table_name = 'v_pick_record'").fetchall()}
            assert "status_before_settlement" in columns and "resettlements" not in columns, (
                "the view is back as revision 0074 made it")
            assert _one(c, "SELECT count(*) FROM picks.v_pick_record") == (0,)
            assert "event_kind" not in _one(c, "SELECT pg_get_viewdef('picks.v_pick_record'::regclass)")[0]
            assert c.execute("SELECT tgname FROM pg_trigger WHERE tgname IN ('fixture_results_revision', "
                             "'fixtures_status_revision')").fetchall() == []
            assert _one(c, "SELECT count(*) FROM core.fixtures") == (3,), "the matches stay"
            assert _one(c, "SELECT goals_away FROM core.fixture_results WHERE fixture_id = %s",
                        ids["finished"]) == (2,), "and so does the corrected score: only the history goes"

        command.upgrade(_cfg(), "0080")
        with psycopg.connect(dsn) as c:
            assert _one(c, "SELECT count(*) FROM core.fixture_result_revisions") == (0,)
            c.execute("UPDATE core.fixture_results SET goals_home = 3 WHERE fixture_id = %s", (ids["finished"],))
            assert _one(c, "SELECT count(*) FROM core.fixture_result_revisions") == (1,), "recording works again"
            revision = _one(c, "SELECT id FROM core.fixture_result_revisions")[0]
            c.execute("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, revision_id, "
                      "from_status, from_profit, to_status, to_profit, rule_version, reason) VALUES (now(), 'pick', "
                      "'3', %s, %s, 'win', 1.1, 'loss', -1, 'settle-v4', 'answers a revision')",
                      (ids["finished"], revision))
            c.execute("DELETE FROM core.fixtures WHERE id = %s", (ids["finished"],))
            assert _one(c, "SELECT count(*) FROM core.fixture_result_revisions") == (0,), "and goes with its match"
            assert _one(c, "SELECT count(*) FROM picks.resettlements") == (0,), (
                "the trail goes with it too, even though one of its rows answers that revision")
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()

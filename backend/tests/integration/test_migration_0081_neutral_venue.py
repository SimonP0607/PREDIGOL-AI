"""Migration 0081 (neutral-venue verdicts, the backtests of the rule, the switch): additive, OFF, and reversible.

Deploying must change no probability: the migration only ADDS three tables, leaves the switch empty (rule OFF) and does not
touch what exists. Run on a scratch database at revision 0080 that already holds a fixture, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0081"
NEW = ("core.fixture_venue_class", "analytics.neutral_rule_runs", "analytics.neutral_rule_promotion")


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
    """What exists that the migration must not touch: the columns and the row counts of the tables it sits beside."""
    cols = c.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema IN ('core', 'analytics') ORDER BY 1, 2, ordinal_position").fetchall()
    rows = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone() for t in ("core.fixtures", "core.competitions",
                                                                           "analytics.backtest_sessions")}
    return {"columns": [r for r in cols if f"{r[0]}.{r[1]}" not in NEW], "rows": rows}


def test_0081_adds_three_tables_leaves_the_switch_off_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0080")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW)
            competition = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                                    "competition_type) VALUES (1, 'Cup', 'cup', 'club', 'domestic_cup') RETURNING id"
                                    ).fetchone()
            assert competition is not None
            season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) "
                               "RETURNING id", (competition[0],)).fetchone()
            home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert season is not None and home is not None and away is not None
            c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                      "away_team_id, kickoff_at, round) VALUES (1, %s, %s, %s, '2026-05-20 19:00Z', 'Final')",
                      (season[0], home[0], away[0]))
            c.commit()
            before = _shape(c)

        command.upgrade(_cfg(), "0081")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW)
            assert _shape(c) == before, "nothing that existed was changed"
            assert c.execute("SELECT count(*) FROM analytics.neutral_rule_promotion").fetchone() == (0,), (
                "the switch is empty after the migration: rule OFF, no probability changes")
            assert c.execute("SELECT count(*) FROM analytics.neutral_rule_runs").fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM core.fixture_venue_class").fetchone() == (0,), (
                "no verdict is invented by the migration: the backfill is a separate, visible step")
            index = c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'core' "
                              "AND indexname = 'fixture_venue_class_neutral'").fetchone()
            assert index is not None and "WHERE neutral" in index[0]
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal").fetchall()}
            assert {"neutral_rule_runs_append_only", "neutral_rule_promotion_append_only"} <= triggers

            # the two tables that record decisions refuse to be edited; the derived one may be rewritten
            run = c.execute("INSERT INTO analytics.neutral_rule_runs (rule_version, protocol, verdict, labels, params, "
                            "result) VALUES ('neutral-v1', 'neutral-ab-v1', 'justified', '{}', '{}', '{}') RETURNING id"
                            ).fetchone()
            assert run is not None
            c.execute("INSERT INTO analytics.neutral_rule_promotion (promoted_by, action, rule_version, reason, run_id) "
                      "VALUES ('owner', 'promote', 'neutral-v1', 'justified by the backtest', %s)", (run[0],))
            c.commit()
            for sql in ("UPDATE analytics.neutral_rule_runs SET verdict = 'inconclusive'",
                        "DELETE FROM analytics.neutral_rule_runs",
                        "UPDATE analytics.neutral_rule_promotion SET reason = 'edited quietly, after the fact'",
                        "DELETE FROM analytics.neutral_rule_promotion"):
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                    c.execute(sql)
                c.rollback()
            c.execute("DELETE FROM analytics.neutral_rule_promotion WHERE false")  # a statement that touches nothing

        command.downgrade(_cfg(), "0080")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW)
            assert c.execute("SELECT to_regprocedure('analytics.refuse_change()')").fetchone() != (None,), (
                "revision 0079's guard function is not this revision's to drop")
            assert _shape(c) == before

        command.upgrade(_cfg(), "0081")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW)
            assert c.execute("SELECT count(*) FROM analytics.neutral_rule_promotion").fetchone() == (0,)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()

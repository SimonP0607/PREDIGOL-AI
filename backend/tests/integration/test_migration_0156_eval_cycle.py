"""Migration 0156 (IA-105..IA-108): the five append-only tables of the evaluation cycle, on a scratch database at the revision below it;
decision-v2's tables accept the triggers E2 and E3; the checks refuse a run after kick-off, an E3 without its line-up, a fact looked at twice,
a selection of the group «siempre» that does not wait, a withdrawal verdict in another state and an alert that says nothing changed; going
back is clean."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0156"
BELOW = "0155"
TABLES = {"eval_runs", "eval_facts", "lineup_dependencies", "eval_verdicts", "private_alerts"}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def tables(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'intel'").fetchall()}


RUN = ("INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, trigger_at, "
       "finished_at, status, decided, lineup, conditions, error, version) VALUES (%s, %s, 1, %s, %s, %s::timestamptz, '2026-11-20 20:00+00', "
       "%s::timestamptz, %s::timestamptz, %s, false, %s, '{}', %s, 'eval-cycle-v1') RETURNING id")


def run_row(c: psycopg.Connection[Any], fx: int, evaluation: str = "E1", cause: str = "ventana", key: str = "ventana",
            at: str = "2026-11-20 07:00+00", lineup: str | None = None, trigger: str | None = None, status: str = "completa",
            error: str | None = None) -> int:
    got = c.execute(RUN, (fx, evaluation, cause, key, at, trigger, at, status, lineup, error)).fetchone()
    assert got is not None
    return int(got[0])


def test_0156_adds_five_append_only_tables_widens_decision_v2s_triggers_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = tables(c)
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (39, 'L', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            assert comp is not None
            s = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
            h = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            a = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert s is not None and h is not None and a is not None
            got = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                            "VALUES (77, %s, %s, %s, '2026-11-20 20:00+00') RETURNING id", (s[0], h[0], a[0])).fetchone()
            assert got is not None
            fx = int(got[0])
            c.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO intel.decision_v2_moments (fixture_id, trigger, evaluation, evaluation_version, known_at, kickoff_at, "
                          "config_key, config, candidates, decided, world_hash, writer_version) VALUES (%s, 'E3', 'E3', 1, "
                          "'2026-11-20 19:40+00', '2026-11-20 20:00+00', 'k|x|y', '{}', 0, 0, repeat('a', 64), 'decision-v2-shadow-v1')",
                          (fx,))
            c.rollback()
        command.upgrade(_cfg(), "0156")
        with psycopg.connect(dsn) as c:
            assert tables(c) - before == TABLES
            c.execute("INSERT INTO intel.decision_v2_moments (fixture_id, trigger, evaluation, evaluation_version, known_at, kickoff_at, "
                      "config_key, config, candidates, decided, world_hash, writer_version) VALUES (%s, 'E3', 'E3', 2, "
                      "'2026-11-20 19:40+00', '2026-11-20 20:00+00', 'k|x|y', '{}', 0, 0, repeat('a', 64), 'decision-v2-shadow-v1')", (fx,))
            r1 = run_row(c, fx)
            r3 = run_row(c, fx, "E3", "alineacion_oficial", "xi:home:a|away:b", "2026-11-20 19:41+00", '{"sides": ["home"]}',
                         "2026-11-20 19:40+00")
            c.execute("INSERT INTO intel.eval_facts (fixture_id, evidence_id, run_id, action, reason, retrieved_at, known_at) "
                      "VALUES (%s, 5, %s, 'anota', 'no_toca_el_modelo', '2026-11-20 06:00+00', '2026-11-20 07:00+00')", (fx, r1))
            c.execute("INSERT INTO intel.private_alerts (dedupe_key, kind, fixture_id, cause, before, after, run_id, evaluation, "
                      "evaluation_version, known_at, kickoff_at, version) VALUES ('cambio_horario|x|-', 'cambio_horario', %s, "
                      "'saque_adelantado', '{\"kickoff_at\": \"a\"}', '{\"kickoff_at\": \"b\"}', %s, 'E1', 1, '2026-11-20 07:00+00', "
                      "'2026-11-20 20:00+00', 'alerts-v1')", (fx, r1))
            c.commit()
            guarded = {r[0] for r in c.execute("SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p "
                                               "ON p.oid = t.tgfoid WHERE p.proname = 'refuse_change' AND NOT t.tgisinternal").fetchall()}
            assert guarded >= TABLES
            for table in ("eval_runs", "eval_facts", "private_alerts"):
                for sql in (f"UPDATE intel.{table} SET id = id", f"DELETE FROM intel.{table}"):
                    with pytest.raises(psycopg.Error):
                        c.execute(sql)
                    c.rollback()
            bad: list[tuple[str, tuple[Any, ...]]] = [
                (RUN, (fx, "E1", "ventana", "v2", "2026-11-20 21:00+00", None, "2026-11-20 21:00+00", "completa", None, None)),
                (RUN, (fx, "E3", "alineacion_oficial", "xi:2", "2026-11-20 19:41+00", None, "2026-11-20 19:41+00", "completa", None, None)),
                (RUN, (fx, "E2", "ventana", "v3", "2026-11-20 07:00+00", None, "2026-11-20 07:00+00", "completa", None, None)),
                (RUN, (fx, "E1", "ventana", "ventana", "2026-11-20 07:00+00", None, "2026-11-20 07:00+00", "completa", None, None)),
                ("INSERT INTO intel.eval_facts (fixture_id, evidence_id, run_id, action, reason, retrieved_at, known_at) "
                 "VALUES (%s, 5, %s, 'recalcula', 'variable_del_modelo', '2026-11-20 06:00+00', '2026-11-20 07:00+00')", (fx, r1)),
                ("INSERT INTO intel.lineup_dependencies (run_id, fixture_id, market_key, selection, line, market_group, status, waits, "
                 "evaluation, known_at, kickoff_at, version, model, estimate_version, input_hash) VALUES (%s, %s, 'player_shots', 'x', 0.5, "
                 "'siempre', 'no_aplica', false, 'E1', '2026-11-20 07:00+00', '2026-11-20 20:00+00', 'lineup-dep-v1', 'player-engine-v1', "
                 "'lineup-estimate-v1', repeat('a', 64))", (r1, fx)),
                ("INSERT INTO intel.eval_verdicts (run_id, fixture_id, market_key, selection, line, evaluation, evaluation_version, known_at, "
                 "kickoff_at, verdict, state, reason, cause, version) VALUES (%s, %s, 'OU', 'Over', 2.5, 'E3', 1, '2026-11-20 19:41+00', "
                 "'2026-11-20 20:00+00', 'retirada', 'confirmada_sombra', 'cumple_todo', 'alineacion', 'eval-verdict-v1')", (r3, fx)),
                ("INSERT INTO intel.eval_verdicts (run_id, fixture_id, market_key, selection, line, evaluation, evaluation_version, known_at, "
                 "kickoff_at, verdict, state, reason, cause, version) VALUES (%s, %s, 'OU', 'Over', 2.5, 'E1', 1, '2026-11-20 07:00+00', "
                 "'2026-11-20 20:00+00', 'confirmada', 'confirmada_sombra', 'cumple_todo', 'decision', 'eval-verdict-v1')", (r1, fx)),
                ("INSERT INTO intel.private_alerts (dedupe_key, kind, fixture_id, cause, before, after, run_id, evaluation, "
                 "evaluation_version, known_at, kickoff_at, version) VALUES ('same|x|-', 'cambio_horario', %s, 'saque_adelantado', "
                 "'{\"a\": 1}', '{\"a\": 1}', %s, 'E1', 1, '2026-11-20 07:00+00', '2026-11-20 20:00+00', 'alerts-v1')", (fx, r1)),
                ("INSERT INTO intel.private_alerts (dedupe_key, kind, fixture_id, cause, before, after, run_id, evaluation, "
                 "evaluation_version, known_at, kickoff_at, version) VALUES ('ret|x|-', 'retirada', %s, 'valor', "
                 "'{\"a\": 1}', '{\"a\": 2}', %s, 'E3', 1, '2026-11-20 19:41+00', '2026-11-20 20:00+00', 'alerts-v1')", (fx, r3)),
            ]
            for sql, args in bad:
                with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation)):
                    c.execute(sql, args)
                c.rollback()
            failed = run_row(c, fx, status="fallida", error="QueryCanceled")
            assert failed > r3, "a failed evaluation does not take the slot: it can run again"
            c.commit()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert tables(c) == before
            assert c.execute("SELECT count(*) FROM intel.decision_v2_moments WHERE trigger = 'E3'").fetchone() == (1,), (
                "decision-v2's rows stay; only new ones are held to the old check")

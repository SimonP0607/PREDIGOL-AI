"""Migration 0142 (IA-068, AD-D02): ``intel.selection_lifecycle`` - append-only, and the database itself refuses what the machine forbids
(a chain that does not start at «detectado», a move outside the cycle, a reason of another state, a model that raises a selection, an owner's
row that is not a signed authorisation of a confirmed selection, a fork, a row known before the one it follows, a key that does not match).
Nothing else in the schema moves, and the downgrade is clean. Its own scratch database (``<FBI_TEST_DB>_m0142``)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory

from fbi.lifecycle import machine
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.helpers import must_be_rejected, must_be_rejected_saying
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

PARENT = ScriptDirectory.from_config(_cfg()).get_revision("0142").down_revision
"""The revision 0142 chains on (0137 when it was written): re-chaining the migration needs no change here."""

SCRATCH = f"{TEST_DB}_m0142"
AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
WRITER = "lifecycle-shadow-v1"
SIGNATURE = "Autorizo esta selección, el dueño, 2026-11-20"


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop(SCRATCH)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), revision)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop(SCRATCH)


def schema(c: psycopg.Connection[Any]) -> dict[str, list[Any]]:
    columns = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2, ordinal_position").fetchall()
    constraints = c.execute("SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                            "JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                            "ORDER BY 1, 2").fetchall()
    return {"columns": columns, "constraints": constraints}


def fixture(c: psycopg.Connection[Any]) -> int:
    comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                     "VALUES (91420, 'Liga 0142', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
    assert comp is not None
    season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
    assert season is not None
    home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (914201, 'Local') RETURNING id").fetchone()
    away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (914202, 'Visitante') RETURNING id").fetchone()
    assert home is not None and away is not None
    fx = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                   "VALUES (914200, %s, %s, %s, %s) RETURNING id", (season[0], home[0], away[0], AT + timedelta(days=1))).fetchone()
    assert fx is not None
    return int(fx[0])


def put(c: psycopg.Connection[Any], fx: int, state: str, reason: str, *, previous: int | None = None, from_state: str | None = None,
        actor: str = "code", signature: str | None = None, result: str | None = None, at: datetime = AT, key: str | None = None,
        evaluation: str | None = None, evaluation_version: int | None = None) -> int:
    row = c.execute(
        "INSERT INTO intel.selection_lifecycle (chain_key, writer, fixture_id, market_key, selection, line, layer, previous_id, from_state, "
        "state, reason, actor, owner_signature, settlement_result, known_at, source, source_id, machine_version, map_version, evaluation, "
        "evaluation_version) VALUES (%s, %s, %s, 'OU', 'over', 2.5, 'decision-v1', %s, %s, %s, %s, %s, %s, %s, %s, 'intel.decisions', 1, "
        "'lifecycle-v1', 'lifecycle-map-v1', %s, %s) RETURNING id",
        (key or f"{WRITER}|{fx}|OU|over|2.50", WRITER, fx, previous, from_state, state, reason, actor, signature, result, at, evaluation,
         evaluation_version)).fetchone()
    assert row is not None
    return int(row[0])


def test_migration_0142_builds_the_cycle_and_the_database_holds_its_rules() -> None:
    assert isinstance(PARENT, str)
    with scratch_at(PARENT) as dsn:
        with psycopg.connect(dsn) as c:
            before = schema(c)
        command.upgrade(_cfg(), "0142")
        with psycopg.connect(dsn) as c:
            after = schema(c)
            added = {tuple(r) for r in after["columns"]} - {tuple(r) for r in before["columns"]}
            assert {r[1] for r in added} == {"selection_lifecycle"}, "nothing but the new table changes"
            assert {tuple(r) for r in before["constraints"]} <= {tuple(r) for r in after["constraints"]}
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'intel.selection_lifecycle'::regclass "
                                                  "AND NOT tgisinternal").fetchall()}
            assert triggers == {"selection_lifecycle_append_only", "selection_lifecycle_in_order"}

            fx = fixture(c)
            first = put(c, fx, "detectado", "candidato_nuevo")
            second = put(c, fx, "en_evaluacion", "valor_insuficiente", previous=first, from_state="detectado", at=AT + timedelta(hours=1))
            c.commit()

            with must_be_rejected_saying(c, "append-only") as cur:
                cur.execute("UPDATE intel.selection_lifecycle SET reason = 'riesgo' WHERE id = %s", (second,))
            with must_be_rejected_saying(c, "append-only") as cur:
                cur.execute("DELETE FROM intel.selection_lifecycle WHERE id = %s", (first,))

            with must_be_rejected_saying(c, "selection_lifecycle_first_state"):
                put(c, fx, "en_evaluacion", "riesgo")
            with must_be_rejected_saying(c, "selection_lifecycle_one_successor"):
                put(c, fx, "detectado", "candidato_nuevo")
            with must_be_rejected_saying(c, "selection_lifecycle_one_successor"):
                put(c, fx, "en_investigacion", "contexto_pendiente", previous=first, from_state="detectado", at=AT + timedelta(hours=2))
            with must_be_rejected_saying(c, "selection_lifecycle_move"):
                put(c, fx, "en_juego", "saque", previous=second, from_state="en_evaluacion", at=AT + timedelta(hours=2))
            with must_be_rejected_saying(c, "selection_lifecycle_reason"):
                put(c, fx, "descartada", "cumple_todo", previous=second, from_state="en_evaluacion", at=AT + timedelta(hours=2))
            with must_be_rejected_saying(c, "selection_lifecycle_previous_fk"):
                put(c, fx, "descartada", "riesgo", previous=second, from_state="en_investigacion", at=AT + timedelta(hours=2))
            with must_be_rejected_saying(c, "a move known at"):
                put(c, fx, "descartada", "riesgo", previous=second, from_state="en_evaluacion", at=AT)
            with must_be_rejected_saying(c, "selection_lifecycle_model_only_down"):
                put(c, fx, "confirmada_sombra", "cumple_todo", previous=second, from_state="en_evaluacion", actor="model",
                    at=AT + timedelta(hours=2))
            with must_be_rejected_saying(c, "selection_lifecycle_chain_key"):
                put(c, fx, "detectado", "candidato_nuevo", key=f"{WRITER}|{fx}|OU|over|2.5")
            with must_be_rejected_saying(c, "selection_lifecycle_evaluation"):
                put(c, fx, "en_evaluacion", "en_curso", previous=second, from_state="en_evaluacion", evaluation_version=2,
                    at=AT + timedelta(hours=2))

            confirmed = put(c, fx, "confirmada_sombra", "cumple_salvo_validacion", previous=second, from_state="en_evaluacion",
                            at=AT + timedelta(hours=3), evaluation="E2", evaluation_version=2)
            c.commit()
            with must_be_rejected_saying(c, "selection_lifecycle_owner"):
                put(c, fx, "confirmada_sombra", machine.AUTHORISED, previous=confirmed, from_state="confirmada_sombra",
                    at=AT + timedelta(hours=4))
            with must_be_rejected_saying(c, "selection_lifecycle_owner"):
                put(c, fx, "confirmada_sombra", "cumple_todo", previous=confirmed, from_state="confirmada_sombra", actor="owner",
                    signature=SIGNATURE, at=AT + timedelta(hours=4))
            with must_be_rejected_saying(c, "selection_lifecycle_owner"):
                put(c, fx, "retirada", "riesgo", previous=confirmed, from_state="confirmada_sombra", signature=SIGNATURE,
                    at=AT + timedelta(hours=4))
            with must_be_rejected(c, "an owner's authorisation of a selection that is not confirmed"):
                put(c, fx, "en_evaluacion", machine.AUTHORISED, previous=confirmed, from_state="confirmada_sombra", actor="owner",
                    signature=SIGNATURE, at=AT + timedelta(hours=4))
            played = put(c, fx, "en_juego", "saque", previous=confirmed, from_state="confirmada_sombra", at=AT + timedelta(days=1))
            with must_be_rejected_saying(c, "selection_lifecycle_settled"):
                put(c, fx, "liquidada", "resultado", previous=played, from_state="en_juego", at=AT + timedelta(days=2))
            settled = put(c, fx, "liquidada", "resultado", previous=played, from_state="en_juego", result="half_win", at=AT + timedelta(days=2))
            done = put(c, fx, "evaluada", "evaluacion_posterior", previous=settled, from_state="liquidada", at=AT + timedelta(days=3))
            c.commit()
            with must_be_rejected_saying(c, "selection_lifecycle_move"):
                put(c, fx, "liquidada", "resultado", previous=done, from_state="evaluada", result="win", at=AT + timedelta(days=4))
            assert c.execute("SELECT count(*) FROM intel.selection_lifecycle").fetchone() == (6,)

            with psycopg.connect(dsn) as other:
                second_fx = fixture_like(other, fx)
                ok = put(other, second_fx, "detectado", "candidato_nuevo", key=f"{WRITER}|{second_fx}|OU|over|2.50")
                put(other, second_fx, "confirmada_sombra", "cumple_todo", previous=ok, from_state="detectado",
                    key=f"{WRITER}|{second_fx}|OU|over|2.50", at=AT + timedelta(minutes=5))
                other.commit()

        command.downgrade(_cfg(), PARENT)
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT to_regclass('intel.selection_lifecycle')").fetchone() == (None,)
            assert c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'selection_lifecycle_in_order'").fetchone() == (0,)
            assert schema(c)["constraints"] == before["constraints"]
        command.upgrade(_cfg(), "head")


def fixture_like(c: psycopg.Connection[Any], fx: int) -> int:
    row = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                    "SELECT 914299, competition_season_id, home_team_id, away_team_id, kickoff_at FROM core.fixtures WHERE id = %s RETURNING id",
                    (fx,)).fetchone()
    assert row is not None
    return int(row[0])

"""Migration 0091 (one post-mortem, a memory with a confidence): additive, keeps every old row and comes back out.

Run on a scratch database at revision 0090, the way production does: a row written the old way (judged per decision, pm-v3) is in the table
before, it must be there after exactly as it was, the new columns are NULL for it, and the downgrade removes only what pm-v6 wrote."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0091"
OWN = {("intel", "postmortems"), ("intel", "entity_memory"), ("intel", "selection_postmortems"), ("intel", "match_postmortems"),
       ("intel", "entity_memory_latest"), ("ai", "postmortem_narratives")}
LEGACY = "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, answers) " \
         "VALUES (7, 11, '2026-10-14T12:00:00Z', 'pm-v3', 'won', 'GOOD', 'MERECIDO', '{\"k\": 1}') RETURNING id"
NEW = ("INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, answers, "
       "market_key, selection, line, roles, review_decision, review_verdict, loss_class, odds, close_odds, p_model, p_market, p_close, "
       "price_move, clv) VALUES (%s, %s, %s, %s, 'lost', 'BAD', 'ERROR', '{}', '1X2', 'Home', 0, %s, 'APPROVE', 'approved_lost', "
       "'MARKET_ERROR', 2.10, 2.00, 0.55, 0.50, 0.45, 0.05, -0.055) RETURNING id")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any], *, without: set[tuple[str, str]] | None = None) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw', 'ai') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if (r[0], r[1]) not in (without or set())]


def _constraints(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                     "WHERE conrelid IN ('intel.postmortems'::regclass, 'intel.entity_memory'::regclass) ORDER BY 1, 2").fetchall()


def _refuses(dsn: str, sql: str, *args: Any, replica: bool = True) -> bool:
    """True when the database refuses the statement (a fresh connection, so a refusal leaves nothing to roll back). ``replica``: the
    foreign keys to a world that was not built are not checked (the checks, the indexes and... not the triggers: a statement that a
    trigger must refuse is run with ``replica=False``)."""
    with psycopg.connect(dsn, autocommit=True) as c:
        if replica:
            c.execute("SET session_replication_role = replica")
        try:
            c.execute(sql, args)  # type: ignore[arg-type]
        except psycopg.Error:
            return True
    return False


def test_0091_extends_the_postmortems_keeps_the_old_row_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0090")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SET session_replication_role = replica")  # a row of the old kind, without building the world it points to
            legacy_id = c.execute(LEGACY).fetchone()
            assert legacy_id is not None
            c.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats) "
                      "VALUES ('team', '9', 'market:1X2', '2026-10-13', now(), 'memory-v1', '{\"decisions\": 3}')")
            before = _shape(c)
            before_constraints = _constraints(c)
            old_row = c.execute("SELECT * FROM intel.postmortems").fetchall()
            old_memory = c.execute("SELECT * FROM intel.entity_memory").fetchall()
            assert not _exists(c, "intel.selection_postmortems") and not _exists(c, "intel.match_postmortems")
            assert not _exists(c, "ai.postmortem_narratives") and not _exists(c, "intel.entity_memory_latest")

        command.upgrade(_cfg(), "0091")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SET session_replication_role = replica")
            assert _shape(c, without=OWN) == _shape_without(before), "nothing else that existed was changed"
            assert c.execute("SELECT * FROM intel.postmortems").fetchall() == [r + (None,) * 15 for r in old_row], \
                "the old row is as it was written, and the new columns are empty for it"
            assert c.execute("SELECT * FROM intel.entity_memory").fetchall() == [(*r, None, None) for r in old_memory]
            assert c.execute("SELECT count(*) FROM intel.selection_postmortems").fetchone() == (0,), "the old way has no selection key"
            assert c.execute("SELECT count(*) FROM intel.match_postmortems").fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM ai.postmortem_narratives").fetchone() == (0,)
            assert c.execute("SELECT version, confidence FROM intel.entity_memory_latest").fetchall() == [("memory-v1", None)], \
                "a memory with one version is as it was"
            for name in ("intel.postmortems", "intel.selection_postmortems", "intel.match_postmortems", "ai.postmortem_narratives",
                         "intel.entity_memory_latest"):
                comment = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
                assert comment is not None and comment[0], f"{name} says what it is"
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid IN ('intel.postmortems'::regclass, "
                                                "'intel.match_postmortems'::regclass, 'ai.postmortem_narratives'::regclass) "
                                                "AND NOT tgisinternal").fetchall()}
            assert {"postmortems_append_only", "match_postmortems_append_only", "postmortem_narratives_append_only"} <= triggers

            # a selection without a decision, a decision-less row has a key, and a row is about something
            a = c.execute(NEW, (None, 11, "2026-10-22T12:00:00Z", "pm-v6", ["daily_pick", "reviewed"])).fetchone()
            b = c.execute(NEW, (7, 11, "2026-10-23T12:00:00Z", "pm-v7", ["decision"])).fetchone()
            assert a is not None and b is not None
            rows = c.execute("SELECT id, version, settled, roles FROM intel.selection_postmortems").fetchall()
            assert rows == [(b[0], "pm-v7", "loss", ["decision"])], "the newest row of the selection, in the vocabulary the readers use"

        assert _refuses(dsn, NEW, None, 11, "2026-10-22T12:00:00Z", "pm-v6", ["x"]), "a selection has one row per version"
        assert _refuses(dsn, "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                             "verdict, answers) VALUES (7, 11, now(), 'pm-v3', 'won', 'GOOD', 'MERECIDO', '{}')"), \
            "a decision is still judged once per version"
        assert _refuses(dsn, "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                             "verdict, answers) VALUES (NULL, 11, now(), 'pm-v9', 'won', 'GOOD', 'MERECIDO', '{}')"), \
            "a row is about a decision or about a selection"
        assert _refuses(dsn, "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                             "verdict, answers, market_key) VALUES (7, 11, now(), 'pm-v9', 'won', 'GOOD', 'MERECIDO', '{}', '1X2')"), \
            "a key is whole or absent"
        assert _refuses(dsn, "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
                             "verdict, answers, market_key, selection, line, roles, loss_class) VALUES (NULL, 11, now(), 'pm-v9', "
                             "'lost', 'BAD', 'ERROR', '{}', '1X2', 'Home', 0, '{x}', 'BAD_LUCK')"), "a loss has one of the known classes"
        assert _refuses(dsn, "UPDATE intel.postmortems SET verdict = 'ERROR'", replica=False), "append-only"
        assert _refuses(dsn, "DELETE FROM intel.postmortems", replica=False), "append-only"
        assert _refuses(dsn, "INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats, "
                             "confidence) VALUES ('team', '9', 'x', '2026-10-13', now(), 'memory-v4', '{}', 1.5)"), "a confidence is 0 to 1"
        assert _refuses(dsn, "INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats, "
                             "evidence_ref) VALUES ('team', '9', 'x', '2026-10-13', now(), 'memory-v4', '{}', '[1]')"), "evidence is a map"

        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SET session_replication_role = replica")
            c.execute("INSERT INTO intel.match_postmortems (fixture_id, created_at, version, outcome, findings) "
                      "VALUES (11, now(), 'pm-v6', '{}', '{}')")
            first = c.execute("SELECT id FROM intel.postmortems WHERE version = 'pm-v6'").fetchone()
            assert first is not None
            c.execute("INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative) VALUES (%s, now(), 'n-v1', 'x')",
                      (first[0],))
            c.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats, confidence, "
                      "evidence_ref) VALUES ('team', '9', 'x', '2026-10-13', now(), 'memory-v4', '{}', 0.6, '{\"fixtures\": [11]}')")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SET session_replication_role = replica")
            for v in ("memory-v3", "memory-v10"):  # the number decides, not the text: v10 is newer than v4
                c.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats) "
                          "VALUES ('team', '9', 'x', '2026-10-13', now(), %s, '{}')", (v,))
            c.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, aspect, as_of_day, built_at, version, stats) "
                      "VALUES ('team', '9', 'x', '2026-10-14', now(), 'memory-v3', '{}')")
            latest = c.execute("SELECT as_of_day::text, version FROM intel.entity_memory_latest WHERE aspect = 'x' ORDER BY 1").fetchall()
            assert latest == [("2026-10-13", "memory-v10"), ("2026-10-14", "memory-v3")], \
                "the newest version of each day, and a day only an older version wrote is not lost"
        assert _refuses(dsn, "INSERT INTO intel.match_postmortems (fixture_id, created_at, version, outcome, findings) "
                             "VALUES (11, now(), 'pm-v6', '{}', '{}')"), "a match is judged once per version"
        assert _refuses(dsn, "UPDATE intel.match_postmortems SET outcome = '{\"a\": 1}'", replica=False), "append-only"
        assert _refuses(dsn, "UPDATE ai.postmortem_narratives SET narrative = 'y'", replica=False), "append-only"
        assert _refuses(dsn, "INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative) "
                             "VALUES (%s, now(), 'n-v1', 'again')", first[0]), "one narrative per post-mortem and version"

        command.downgrade(_cfg(), "0090")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "and it leaves as it came"
            assert _constraints(c) == before_constraints
            assert c.execute("SELECT * FROM intel.postmortems").fetchall() == old_row, "only what pm-v6 wrote went out; the old row stayed"
            assert c.execute("SELECT * FROM intel.entity_memory WHERE version = 'memory-v1'").fetchall() == old_memory
            assert not _exists(c, "intel.selection_postmortems") and not _exists(c, "intel.match_postmortems")
            assert not _exists(c, "ai.postmortem_narratives") and not _exists(c, "intel.entity_memory_latest")
            assert _refuses_in(c, "UPDATE intel.postmortems SET verdict = 'ERROR'"), "the table is append-only again after the downgrade"

        command.upgrade(_cfg(), "0091")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _exists(c, "intel.selection_postmortems") and _exists(c, "ai.postmortem_narratives")
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def _shape_without(before: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [r for r in before if (r[0], r[1]) not in OWN]


def _refuses_in(c: psycopg.Connection[Any], sql: str) -> bool:
    try:
        c.execute(sql)
    except psycopg.Error:
        return True
    return False

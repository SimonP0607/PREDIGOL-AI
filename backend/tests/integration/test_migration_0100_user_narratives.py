"""Migration 0100 (the readers' narrative, plan UX A11): three new tables in ``ai``, nothing else.

Deploying must change nothing the system already stores: 0100 adds ``ai.user_usage``, ``ai.user_narratives`` and
``ai.evidence_translations``; every other table keeps its columns. The tables refuse what they must never hold - a narrative shown
without its text, a text without both languages, a Spanish claim (only its headline is written), a headline over 80 characters,
a call of another purpose than the readers' narrative - and every row stays as it was written (append-only). Going back drops
them while no real spend is recorded and is refused once it is. Run on a scratch database at revision 0099, the way production
does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0100"
NEW = ("user_usage", "user_narratives", "evidence_translations")
H = "e" * 64


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND NOT (table_schema = 'ai' AND table_name = ANY(%s)) "
                     "ORDER BY 1, 2, ordinal_position", (list(NEW),)).fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


NARRATIVE = ("INSERT INTO ai.user_narratives (fixture_id, created_at, version, packet_id, data_at, reading_hash, input_hash, "
             "status, content) VALUES (1, now(), %s, 1, now() - interval '1 hour', %s, %s, %s, %s::jsonb) RETURNING id")


def test_0100_adds_the_readers_tables_append_only_and_goes_back_only_without_spend(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0099")
        with psycopg.connect(dsn) as c:
            before = _shape(c)
        command.upgrade(_cfg(), "0100")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            ok = c.execute(NARRATIVE, ("user-narrative-v1", H, H, "ok", '{"es": [], "en": []}')).fetchone()
            assert ok is not None
            c.execute(NARRATIVE, ("user-narrative-v1", H, H, "rejected", None))
            _refused(c, NARRATIVE, ("user-narrative-v1", H, H, "ok", None))  # shown without its text
            _refused(c, NARRATIVE, ("user-narrative-v1", H, H, "rejected", '{"es": []}'))  # a text while refused
            _refused(c, NARRATIVE, ("user-narrative-v1", H, H, "ok", '{"es": []}'))  # one language only
            _refused(c, NARRATIVE, ("narrative-v4", H, H, "ok", '{"es": [], "en": []}'))  # Intelligence's narrative
            _refused(c, NARRATIVE, ("user-narrative-v1", "x", H, "ok", '{"es": [], "en": []}'))
            translation = ("INSERT INTO ai.evidence_translations (evidence_id, content_hash, lang, headline, claim, version, "
                           "narrative_id, created_at) VALUES (9, 'h', %s, %s, %s, 'user-narrative-v1', %s, now())")
            c.execute(translation, ("en", "A headline", "The claim in English.", ok[0]))
            c.execute(translation, ("es", "Un titular", None, ok[0]))
            _refused(c, translation, ("es", "Un titular", "La afirmación en español.", ok[0]))  # the Spanish claim is not ours
            _refused(c, translation, ("en", "x" * 81, None, ok[0]))
            _refused(c, translation, ("en", None, None, ok[0]))
            _refused(c, translation, ("en", "A headline", "The claim in English.", ok[0]))  # the same item twice
            usage = ("INSERT INTO ai.user_usage (at, purpose, tier, provider, model, cost_usd, status, searches) "
                     "VALUES (now(), %s, 'bulk', 'anthropic', 'claude-haiku-5-5', %s, 'ok', %s)")
            c.execute(usage, ("user_narrative", 0, 0))
            _refused(c, usage, ("match_brief", 0, 0))  # Intelligence's purposes stay in ai.usage
            _refused(c, usage, ("user_narrative", 0, 1))  # never a web search
            for table in NEW:
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), c.transaction():
                    c.execute(f"DELETE FROM ai.{table}")
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), c.transaction():
                    c.execute(f"UPDATE ai.{table} SET id = id")
        command.downgrade(_cfg(), "0099")  # no real spend: the narratives are written again by the next passes
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT to_regclass('ai.user_narratives')").fetchone() == (None,)
            assert _shape(c) == before
        command.upgrade(_cfg(), "0100")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(usage, ("user_narrative", "0.004", 0))
        with pytest.raises(Exception, match="readers' AI spend"):
            command.downgrade(_cfg(), "0099")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM ai.user_usage").fetchone() == (1,), "the spend is kept"
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()

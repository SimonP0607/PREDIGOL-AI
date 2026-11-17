"""Migration 0154 (IA-101/IA-102, AD-G04/G05): ``news.story_texts`` and ``news.moderation_log``, append-only, on a scratch database at the
revision below it; a refused text is never kept and only the system flags; going back leaves the schema as it was."""

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
SCRATCH = f"{TEST_DB}_m0154"
BELOW = "0152"
STORY = "st-ejemplo-0154"


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


def shape(c: psycopg.Connection[Any]) -> list[Any]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema IN ('news', 'ai', 'core') ORDER BY 1, 2, 3").fetchall()


def test_0154_adds_two_append_only_tables_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            c.execute("INSERT INTO news.stories (story_key, version, at, first_seen_at, decided_by, written_by) "
                      "VALUES (%s, 1, now(), now(), 'system', 'news-pipeline-v1')", (STORY,))
            c.commit()
        command.upgrade(_cfg(), "0154")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {r[1] for r in added} == {"story_texts", "moderation_log"} and {r[0] for r in added} == {"news"}
            sid = c.execute("SELECT id FROM news.stories WHERE story_key = %s", (STORY,)).fetchone()[0]  # type: ignore[index]
            text = ("INSERT INTO news.story_texts (story_id, story_key, at, mode, prompt_version, verify_version, anticopy_version, input_hash, "
                    "outcome, headline_es, headline_en, summary_es, summary_en, written_by) VALUES (%s, %s, now(), 'shadow', 'news-text-v1', "
                    "'news-verify-v1', 'anticopy-v1', %s, %s, %s, %s, %s, %s, 'news-verify-v1')")
            c.execute(text, (sid, STORY, "a" * 64, "accepted", "Titular propio", "Own headline", "Resumen propio.", "Own summary."))
            c.execute(text, (sid, STORY, "b" * 64, "rejected", None, None, None, None))
            c.commit()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(text, (sid, STORY, "c" * 64, "rejected", "Copia del medio", "Copy", "Texto copiado.", "Copied."))
            c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(text, (sid, STORY, "d" * 64, "accepted", None, None, None, None))
            c.rollback()
            log = ("INSERT INTO news.moderation_log (story_key, story_id, at, action, rule, reason, requested_by, decided_by, written_by) "
                   "VALUES (%s, %s, now(), %s, %s, 'un motivo', %s, %s, 'moderation-v1')")
            c.execute(log, (STORY, sid, "flag", "texto_lesion", "sistema", "system"))
            c.execute(log, (STORY, sid, "withdraw", None, "club", "owner"))
            c.commit()
            for row in (("flag", "texto_lesion", "sistema", "owner"), ("withdraw", None, "club", "system"),
                        ("flag", None, "sistema", "system"), ("flag", "texto_lesion", "club", "system")):
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(log, (STORY, sid, *row))
                c.rollback()
            for sql in ("UPDATE news.story_texts SET outcome = 'failed'", "DELETE FROM news.story_texts",
                        "UPDATE news.moderation_log SET reason = 'otro'", "DELETE FROM news.moderation_log"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
            n = c.execute("SELECT count(*) FROM news.stories").fetchone()
            assert n is not None and n[0] == 1

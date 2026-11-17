"""Migration 0149 (IA-085, AD-C03): ``news.feed_reads``, append-only, on a scratch database at the revision below it; going back leaves the
schema as it was (the feeds and items of 0146 untouched)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.news import canonical
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0149"
BELOW = "0147"
FEED = "https://oficial.ejemplo.invalid/feed/"


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


def test_0149_adds_one_append_only_table_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            c.execute("INSERT INTO news.feeds (url_sha256, version, url, kind, source_id, source_domain, at, added_by) "
                      "VALUES (%s, 1, %s, 'rss', 'ej-oficial', 'oficial.ejemplo.invalid', now(), 'system')",
                      (canonical.sha256_hex(FEED), FEED))
            c.commit()
        command.upgrade(_cfg(), "0149")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {r[1] for r in added} == {"feed_reads"} and {r[0] for r in added} == {"news"}
            assert set(before) <= set(shape(c)), "nothing else of the schema moves"
            row = c.execute("INSERT INTO news.feed_reads (feed_id, url_sha256, source_id, at, mode, outcome, band, next_due_at, "
                            "reader_version, registry_version) SELECT id, url_sha256, source_id, now(), 'shadow', 'would_read', 'none', "
                            "now() + interval '1 day', 'signals-v1', 'dir-1' FROM news.feeds RETURNING id").fetchone()
            assert row is not None
            c.commit()
            for sql in ("UPDATE news.feed_reads SET failures = 1", "DELETE FROM news.feed_reads"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
            bad = [("read", None, 0), ("failed", None, 0), ("would_read", 200, 0)]
            for outcome, status, failures in bad:
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("INSERT INTO news.feed_reads (feed_id, url_sha256, source_id, at, mode, outcome, band, next_due_at, "
                              "reader_version, registry_version, http_status, failures) SELECT id, url_sha256, source_id, now(), 'shadow', "
                              "%s, 'none', now() + interval '1 day', 'signals-v1', 'dir-1', %s, %s FROM news.feeds",
                              (outcome, status, failures))
                c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO news.feed_reads (feed_id, url_sha256, source_id, at, mode, outcome, band, next_due_at, reader_version, "
                          "registry_version) SELECT id, url_sha256, source_id, now(), 'shadow', 'would_read', 'none', now(), 'signals-v1', "
                          "'dir-1' FROM news.feeds")
            c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
            n = c.execute("SELECT count(*) FROM news.feeds").fetchone()
            assert n is not None and n[0] == 1

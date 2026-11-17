"""Migration 0146 (IA-080, AD-G01): the schema ``news`` - five append-only tables - and ``ai.evidence.item_id``, on a scratch database at
the revision below it, the way production goes: a claim written before keeps NULL forever, the evidence still refuses a delete and a
change of content (``item_id`` included), its status still moves, nothing else of the schema moves, and going back leaves it as it was."""

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
SCRATCH = f"{TEST_DB}_m0146"
BELOW = "0145"
NEW = ("feeds", "items", "stories", "item_story", "item_entities")
URL = "https://oficial.ejemplo.invalid/convocatoria"


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


def shape(c: psycopg.Connection[Any]) -> dict[str, list[Any]]:
    columns = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'news') ORDER BY 1, 2, ordinal_position").fetchall()
    constraints = c.execute("SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                            "JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname NOT IN ('pg_catalog', 'news') "
                            "ORDER BY 1, 2").fetchall()
    triggers = c.execute("SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1, 2").fetchall()
    return {"columns": columns, "constraints": constraints, "triggers": triggers}


def evidence(c: psycopg.Connection[Any], claim: str, *, item_id: int | None = None, with_item: bool = True) -> int:
    columns = "kind, claim, origin, source_name, source_url, source_tier, retrieved_at, story_key, content_hash, confidence, relevance, " \
              "status, status_reason, status_changed_at"
    values = "'news', %s, 'web', 'Fuente Ejemplo', %s, 'media', now(), %s, md5(%s), 0.5, 0.5, 'RUMOR', 'one source', now()"
    params: list[Any] = [claim, URL, f"story-{claim}", claim]
    if with_item:
        columns += ", item_id"
        values += ", %s"
        params.append(item_id)
    row = c.execute(f"INSERT INTO ai.evidence ({columns}) VALUES ({values}) RETURNING id", params).fetchone()
    assert row is not None
    return int(row[0])


def an_item(c: psycopg.Connection[Any], *, canonical_url: str = URL, url_hash: str | None = None) -> int:
    key = url_hash or canonical.sha256_hex(canonical_url)
    row = c.execute(
        "INSERT INTO news.items (url_sha256, version, url, canonical_url, canon_version, content_sha256, fingerprint_version, found_via, "
        "source_id, source_domain, source_name, source_state, ai_reserved, store_level, publish_level, registry_version, policy_version, "
        "seen_at, written_by) VALUES (%s, 1, %s, %s, 'canon-v1', repeat('a', 64), 'fp-v1', 'rss', 'ej-oficial', 'oficial.ejemplo.invalid', "
        "'Oficial', 'verificada_autorizada', false, 'facts', 'summary', 'dir+excl', 'source-policy-v1', now(), 'ingest-v1') RETURNING id",
        (key, canonical_url, canonical_url)).fetchone()
    assert row is not None
    return int(row[0])


def refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> str:
    c.execute("SAVEPOINT s")
    try:
        c.execute(sql, params)
    except psycopg.errors.Error as exc:
        c.execute("ROLLBACK TO SAVEPOINT s")
        return str(exc.diag.constraint_name or exc.diag.message_primary or exc.sqlstate)
    raise AssertionError(f"the database took {sql}")


def test_0146_adds_the_news_store_and_a_column_that_old_claims_never_fill(migrated_database: str) -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            old = evidence(c, "una evidencia de antes de 0146", with_item=False)
            c.commit()
            before = shape(c)
        command.upgrade(_cfg(), "0146")
        with psycopg.connect(dsn) as c:
            after = shape(c)
            tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'news'").fetchall()}
            assert tables == set(NEW)
            for table in NEW:
                assert c.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s AND NOT tgisinternal",
                                 (f"news.{table}", f"{table}_append_only")).fetchone() == (1,)
            added = [r for r in after["columns"] if r not in before["columns"]]
            assert added == [("ai", "evidence", "item_id", "bigint", "YES", None)], "one column, nullable, no default - and nothing else"
            assert [r for r in before["columns"] if r not in after["columns"]] == []
            assert set(before["constraints"]) <= set(after["constraints"])
            assert {r for r in after["constraints"] if r not in before["constraints"]} == {
                ("ai.evidence", "evidence_item_fk", "FOREIGN KEY (item_id) REFERENCES news.items(id)")}
            assert c.execute("SELECT convalidated FROM pg_constraint WHERE conname = 'evidence_item_fk'").fetchone() == (True,)
            assert before["triggers"] == [t for t in after["triggers"] if not t[0].startswith("news.")]

            # the claim written before stays NULL and cannot be given an item afterwards; its status still moves
            assert c.execute("SELECT item_id FROM ai.evidence WHERE id = %s", (old,)).fetchone() == (None,)
            item_id = an_item(c)
            assert "never changes" in refused(c, "UPDATE ai.evidence SET item_id = %s WHERE id = %s", (item_id, old))
            assert "never deleted" in refused(c, "DELETE FROM ai.evidence WHERE id = %s", (old,))
            c.execute("UPDATE ai.evidence SET status = 'PROBABLE', status_reason = 'two sources', status_changed_at = now() WHERE id = %s",
                      (old,))
            assert c.execute("SELECT status, jsonb_array_length(status_history) FROM ai.evidence WHERE id = %s", (old,)).fetchone() == (
                "PROBABLE", 1)

            # a new claim carries its item from the start, and the item must exist
            new = evidence(c, "una evidencia con su artículo", item_id=item_id)
            assert c.execute("SELECT item_id FROM ai.evidence WHERE id = %s", (new,)).fetchone() == (item_id,)
            assert "never changes" in refused(c, "UPDATE ai.evidence SET item_id = NULL WHERE id = %s", (new,))
            assert refused(c, "INSERT INTO ai.evidence (kind, claim, origin, source_name, source_url, source_tier, retrieved_at, story_key, "
                              "content_hash, confidence, relevance, status, status_reason, status_changed_at, item_id) VALUES ('news', "
                              "'sin artículo real', 'web', 'F', 'https://x.invalid/a', 'media', now(), 'k', 'h', 0.5, 0.5, 'RUMOR', 'r', "
                              "now(), 999999)") == "evidence_item_fk"

            # the news tables refuse every change; the database checks the identity of an item
            assert "append-only" in refused(c, "UPDATE news.items SET author = 'x' WHERE id = %s", (item_id,))
            assert "append-only" in refused(c, "DELETE FROM news.items WHERE id = %s", (item_id,))
            assert refused(c, "INSERT INTO news.items (url_sha256, version, url, canonical_url, canon_version, content_sha256, "
                              "fingerprint_version, found_via, source_domain, source_name, source_state, ai_reserved, store_level, "
                              "publish_level, registry_version, policy_version, seen_at, written_by) VALUES (repeat('b', 64), 1, %s, %s, "
                              "'canon-v1', repeat('a', 64), 'fp-v1', 'rss', 'oficial.ejemplo.invalid', 'O', 'verificada_autorizada', "
                              "false, 'facts', 'summary', 'v', 'source-policy-v1', now(), 'ingest-v1')", (URL, URL)) == "items_url_identity"
            assert refused(c, "INSERT INTO news.items (url_sha256, version, url, canonical_url, canon_version, content_sha256, "
                              "fingerprint_version, found_via, source_domain, source_name, source_state, ai_reserved, store_level, "
                              "publish_level, registry_version, policy_version, seen_at, written_by) VALUES (%s, 1, %s, %s, "
                              "'canon-v1', repeat('c', 64), 'fp-v1', 'rss', 'radio.ejemplo.invalid', 'R', "
                              "'verificada_pendiente_derechos', false, 'link', 'summary', 'v', 'source-policy-v1', now(), 'ingest-v1')",
                           (canonical.sha256_hex(URL + "/2"), URL + "/2", URL + "/2")) == "items_summary_needs_facts", \
                "a source that may only be linked can never be published as a summary"
            c.rollback()

        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'news'").fetchone() == (0,)
            assert shape(c) == before, "going back leaves the schema exactly as it was"
            assert "never deleted" in refused(c, "DELETE FROM ai.evidence WHERE id = %s", (old,))
            c.rollback()
        command.upgrade(_cfg(), "0146")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'news'").fetchone() == (5,)

"""Migration 0114 (Plan Maestro IA, phase 2): the evidence learns who it is about and how long it lives, the research cache learns the scope
``entity``, and nothing that was written or that the code that ran before relies on changes.

The upgrade adds five NULL columns (the code that ran before writes none of them), the vocabularies are the words of the code, a typed claim
names a subject or none, the immutability guard of the evidence now covers the five columns (a claim is typed when it is written, never after)
and the old rules stay. The downgrade deletes nothing. It never waits for a lock longer than ten seconds.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError

from fbi.ai import cache
from fbi.ai.contracts import claim, mcp
from tests.integration.agent_tables import refuses
from tests.integration.test_migration_0111 import _cfg, scratch_at

pytestmark = pytest.mark.integration

NOON = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
OLD_CONTENT = ("fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, author, "
               "published_at, retrieved_at, event_at, story_key, content_hash, payload_hash, confidence, relevance, attributes")
NEW = ("claim_type", "subject_type", "subject_id", "source_class", "fresh_until")
SCOPE_RULE = "research_cache_scope_check"


def evidence(c: psycopg.Connection[Any], n: int, **typed: Any) -> int:
    """A row of evidence as the code writes it (provider origin, so no address is needed); ``typed`` fills the new columns."""
    cols = {"kind": "injury", "claim": f"claim number {n} about a player", "origin": "provider", "source_name": "provider", "source_tier": "provider",
            "retrieved_at": NOON, "story_key": f"story-{n}", "content_hash": f"hash-{n}", "confidence": 0.9, "relevance": 0.8, "status": "PROBABLE",
            "status_reason": "test", "status_changed_at": NOON, **typed}
    row = c.execute(f"INSERT INTO ai.evidence ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id", tuple(cols.values())).fetchone()
    assert row is not None
    return int(row[0])


def content(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute(f"SELECT id, {OLD_CONTENT}, status, status_reason, status_history FROM ai.evidence ORDER BY id").fetchall()


def words(c: psycopg.Connection[Any], table: str, name: str) -> list[str]:
    row = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s AND conrelid = %s::regclass", (name, table)).fetchone()
    assert row is not None, name
    return re.findall(r"'([^']*)'::text", row[0])


def column_rule(c: psycopg.Connection[Any], column: str) -> list[str]:
    rows = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ai.evidence'::regclass AND contype = 'c' "
                     "AND pg_get_constraintdef(oid) LIKE %s", (f"%({column} = ANY%",)).fetchall()
    assert len(rows) == 1, column
    return re.findall(r"'([^']*)'::text", rows[0][0])


def old_rules(c: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'ai.evidence'::regclass "
                     "AND conname NOT LIKE '%%subject%%' AND pg_get_constraintdef(oid) !~ '(claim_type|subject_|source_class|fresh_until)' "
                     "ORDER BY 1").fetchall()


def test_0114_keeps_what_was_written_adds_five_null_columns_and_the_words_of_the_code() -> None:
    with scratch_at("0113") as dsn:
        with psycopg.connect(dsn) as c:
            ids = [evidence(c, 1), evidence(c, 2, status="RUMOR")]
            c.commit()
            before, rules = content(c), old_rules(c)
            with refuses(c, psycopg.errors.UndefinedColumn):
                c.execute("SELECT claim_type FROM ai.evidence")

        command.upgrade(_cfg(), "0114")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0114",)
            assert content(c) == before and [r[0] for r in before] == ids, "every row written before is as it was"
            assert old_rules(c) == rules, "no old rule of the evidence moved"
            assert c.execute(f"SELECT {', '.join(NEW)} FROM ai.evidence ORDER BY id").fetchall() == [(None,) * 5] * 2
            assert column_rule(c, "claim_type") == list(get_args(claim.ClaimType))
            assert column_rule(c, "subject_type") == list(get_args(claim.SubjectKind))
            assert column_rule(c, "source_class") == list(mcp.SOURCE_CLASSES)
            assert words(c, "ai.research_cache", SCOPE_RULE) == sorted(cache.SCOPES, key=lambda s: words(c, "ai.research_cache", SCOPE_RULE).index(s))
            assert set(words(c, "ai.research_cache", SCOPE_RULE)) == set(cache.SCOPES), "the scopes of the database are the scopes of the code"

            until = NOON + timedelta(hours=24)
            typed = evidence(c, 3, claim_type="OUT", subject_type="PLAYER", subject_id=77, source_class="OFFICIAL", fresh_until=until)
            assert c.execute(f"SELECT {', '.join(NEW)} FROM ai.evidence WHERE id = %s", (typed,)).fetchone() == ("OUT", "PLAYER", 77, "OFFICIAL", until)
            evidence(c, 4, claim_type="OTHER")  # a claim may be typed without a subject
            evidence(c, 5, subject_type="TEAM", subject_id=1)  # and a subject may be named without a type of claim
            wrongs: list[dict[str, Any]] = [{"claim_type": "MAYBE"}, {"claim_type": "out"}, {"subject_type": "CLUB", "subject_id": 1}, {"source_class": "BLOG"},
                                       {"source_class": "official"}, {"subject_type": "TEAM"}, {"subject_id": 5}, {"subject_type": "TEAM", "subject_id": 0},
                                       {"subject_type": "TEAM", "subject_id": -4}]
            for n, wrong in enumerate(wrongs, start=10):
                with refuses(c, psycopg.errors.CheckViolation):
                    evidence(c, n, **wrong)
            c.rollback()


def test_0114_the_content_of_evidence_still_never_changes_and_that_includes_the_five_new_columns() -> None:
    with scratch_at("0114") as dsn, psycopg.connect(dsn) as c:
        old, typed = evidence(c, 1), evidence(c, 2, claim_type="OUT", subject_type="TEAM", subject_id=9, source_class="PROVIDER", fresh_until=NOON)
        for row, column, value in [(typed, "claim_type", "DOUBT"), (typed, "subject_type", "PLAYER"), (typed, "subject_id", 10), (typed, "source_class", "SOCIAL"),
                                   (typed, "fresh_until", NOON + timedelta(days=9)), (old, "claim_type", "OUT"), (old, "fresh_until", NOON),
                                   (old, "claim", "another claim entirely"), (old, "confidence", 0.1)]:
            with refuses(c, psycopg.errors.CheckViolation, saying="never changes"):
                c.execute(f"UPDATE ai.evidence SET {column} = %s WHERE id = %s", (value, row))
        with refuses(c, psycopg.errors.CheckViolation, saying="never deleted"):
            c.execute("DELETE FROM ai.evidence WHERE id = %s", (typed,))
        c.execute("UPDATE ai.evidence SET status = 'CONFIRMED', status_reason = 'two sources', status_changed_at = %s WHERE id = %s", (NOON + timedelta(hours=1), typed))
        moved = c.execute("SELECT status, jsonb_array_length(status_history) FROM ai.evidence WHERE id = %s", (typed,)).fetchone()
        assert moved == ("CONFIRMED", 1), "the status still moves, and the history says from what"
        c.rollback()


def test_0114_the_cache_accepts_the_scope_entity_and_nothing_else_new() -> None:
    with scratch_at("0114") as dsn, psycopg.connect(dsn) as c:
        for scope in sorted(cache.SCOPES):
            c.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES (%s, %s, %s, %s, 'h', '{}')",
                      (scope, f"k-{scope}", NOON, NOON + timedelta(hours=1)))
        for nonsense in ("Entity", "entities", "entity ", "", "page"):
            with refuses(c, psycopg.errors.CheckViolation, constraint=SCOPE_RULE):
                c.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES (%s, 'k', %s, %s, 'h', '{}')",
                          (nonsense, NOON, NOON + timedelta(hours=1)))
        c.rollback()


def test_0114_downgrade_deletes_nothing_and_the_old_list_of_scopes_judges_only_what_comes_after() -> None:
    with scratch_at("0114") as dsn:
        with psycopg.connect(dsn) as c:
            typed = evidence(c, 1, claim_type="OUT", subject_type="PLAYER", subject_id=3, source_class="OFFICIAL", fresh_until=NOON)
            c.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES ('entity', 'rk-v2:team:1:availability', %s, %s, 'h', '{}')",
                      (NOON, NOON + timedelta(hours=1)))
            c.commit()
            before = content(c)
            typed_before = c.execute(f"SELECT {', '.join(NEW)} FROM ai.evidence").fetchall()
        command.downgrade(_cfg(), "0113")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0113",)
            assert content(c) == before and c.execute(f"SELECT {', '.join(NEW)} FROM ai.evidence").fetchall() == typed_before, "no row and no typing was lost"
            assert c.execute("SELECT count(*) FROM ai.research_cache WHERE scope = 'entity'").fetchone() == (1,)
            assert words(c, "ai.research_cache", SCOPE_RULE) == ["fixture", "team", "player", "url", "story", "search"]
            assert c.execute("SELECT convalidated FROM pg_constraint WHERE conname = %s", (SCOPE_RULE,)).fetchone() == (False,)
            evidence(c, 2)  # the code that ran before writes evidence as ever
            c.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES ('search', 'old', %s, %s, 'h', '{}')", (NOON, NOON + timedelta(hours=1)))
            with refuses(c, psycopg.errors.CheckViolation, constraint=SCOPE_RULE):
                c.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES ('entity', 'again', %s, %s, 'h', '{}')", (NOON, NOON + timedelta(hours=1)))
            with refuses(c, psycopg.errors.CheckViolation, saying="never changes"):
                c.execute("UPDATE ai.evidence SET claim_type = 'DOUBT' WHERE id = %s", (typed,))  # the guard stays: it only adds rules about columns the older code never writes
            c.rollback()
        command.upgrade(_cfg(), "0114")  # and it goes up again with the rows that are there
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0114",)
            assert content(c) == before and set(words(c, "ai.research_cache", SCOPE_RULE)) == set(cache.SCOPES)


@pytest.mark.parametrize("direction", ["up", "down"])
def test_0114_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    before, after = ("0113", "0114") if direction == "up" else ("0114", "0113")

    def move() -> None:
        (command.upgrade if direction == "up" else command.downgrade)(_cfg(), after)

    with scratch_at(before) as dsn:
        holder = psycopg.connect(dsn)  # a pass writing evidence, with its transaction open
        holder.execute("LOCK TABLE ai.evidence, ai.research_cache IN ROW EXCLUSIVE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                move()
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate, daemon=True)
        worker.start()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and isinstance(failure[0], DBAPIError) and "lock timeout" in str(failure[0]).lower(), failure
        assert 8 < time.monotonic() - started < 40, "it waited for the lock, ten seconds, and then let go"
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (before,)
            has_columns = c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'ai' AND table_name = 'evidence' "
                                    "AND column_name = 'claim_type'").fetchone()
            assert has_columns == ((1,) if direction == "down" else (0,)), "nothing half done"
        move()  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (after,)


def test_the_chain_of_the_revisions_has_this_migration_after_0113() -> None:
    """0114 follows 0113 and nothing in the repository sits between them (0111 to 0113 are the first phase's)."""
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0114")
    assert revision is not None and revision.down_revision == "0113"
    heads = script.get_heads()
    assert "0114" in heads or all(h > "0114" for h in heads), heads
    assert re.fullmatch(r"\d{4}", revision.revision)

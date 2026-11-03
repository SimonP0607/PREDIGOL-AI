"""Migration 0119 (Plan Maestro IA, phase 3): the arms of the shadow - three engines a review can carry, the kind of cycle ``orchestrate`` and the
table that keeps the arm each match was assigned to - and nothing else changes.

The upgrade rewrites two CHECKs and adds one table: what was written is as it was, the new words are accepted, nonsense is still refused, no other
rule of the schema moves, the new table is append-only and holds in the database the rule the code applies (a match is sampled exactly when its
bucket is below the share), and nothing waits for a lock longer than ten seconds. The downgrade puts the old lists back without deleting a review:
the rows of the shadow stay (a review is evidence), the old lists judge only what is written from then on, and a cycle of the new kind left running
is closed first so that the recovery of the code that ran before does not stumble on it.

The scratch database is named after the one of this run (``FBI_TEST_DB``), so that two engineers on one cluster do not take each other's down.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from fbi.ai import cycle as cycles
from fbi.ai.config import SHADOW_ENGINES
from tests.integration.agent_tables import refuses
from tests.integration.conftest import ADMIN_URL, TEST_DB, Seed, _dsn
from tests.integration.test_migration_0111 import _cfg, _drop

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0119"
NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
OLD_ENGINES = ("rules", "llm", "combined")
NEW_ENGINES = ("ma-v1", "ma-v1-h", "cs-v1")
OLD_KINDS = ("analysis", "postmortem", "learning", "evaluation", "day_start", "prepare", "package")
ENGINE_CHECK, KIND_CHECK = "pick_reviews_engine_check", "cycles_kind_check"
TABLE = "ai.shadow_assignments"
EXPERIMENT = "ma-shadow-v1"
COLUMNS = [("experiment", "text", "NO"), ("fixture_id", "bigint", "NO"), ("bucket", "integer", "NO"), ("sampled", "boolean", "NO"),
           ("council_solo", "boolean", "NO"), ("share", "numeric", "NO"), ("assigned_at", "timestamp with time zone", "NO")]


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    """A database of this run's own, migrated to ``revision``; the environment is put back and the database dropped on the way out."""
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


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def a_fixture(c: psycopg.Connection[Any]) -> int:
    """The smallest graph a review hangs from: a competition, its season, two teams and a match (what the ``seed`` fixture builds on the main database)."""
    def one(sql: str, *args: Any) -> int:
        row = c.execute(sql, args).fetchone()
        assert row is not None
        return int(row[0])

    competition = one("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                      "VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') RETURNING id")
    season = one("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id", competition)
    home = one("INSERT INTO core.teams (provider_team_id, name) VALUES (33, 'Manchester United') RETURNING id")
    away = one("INSERT INTO core.teams (provider_team_id, name) VALUES (40, 'Liverpool') RETURNING id")
    return one("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
               "VALUES (1001, %s, %s, %s, '2026-11-04 19:00Z') RETURNING id", season, home, away)


def review(c: psycopg.Connection[Any], fixture_id: int, engine: str, *, n: int = 1, at: datetime = NOON) -> int:
    """A row of ``ai.pick_reviews`` as ``store_review`` leaves it, with the fewest columns the table asks for."""
    row = c.execute("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, input_hash, decision, "
                    "confidence, output, mode, status) VALUES (%s, %s, '1X2', 'HOME', 0, %s, 'test-v1', %s, 'APPROVE', 0.5, %s, 'shadow', 'ok') "
                    "RETURNING id", (at, fixture_id, engine, f"{n:064x}", Jsonb({"engine": engine}))).fetchone()
    assert row is not None
    return int(row[0])


def cycle(c: psycopg.Connection[Any], kind: str, *, status: str = "ok", at: datetime = NOON) -> int:
    """A row of the ledger as ``open_cycle`` and ``close_cycle`` leave it: a cycle that ended, or one that is still running."""
    row = c.execute("INSERT INTO ai.cycles (kind, started_at, finished_at, status, mode, budget_state, counts) "
                    "VALUES (%s, %s, %s, %s, 'shadow', 'ok', '{}'::jsonb) RETURNING id",
                    (kind, at, None if status == "running" else at, status)).fetchone()
    assert row is not None
    return int(row[0])


def assignment(c: psycopg.Connection[Any], fixture_id: int, *, experiment: str = EXPERIMENT, bucket: int = 10, sampled: bool = True,
               council_solo: bool = False, share: str | Decimal = "0.3", at: datetime = NOON) -> None:
    c.execute("INSERT INTO ai.shadow_assignments (experiment, fixture_id, bucket, sampled, council_solo, share, assigned_at) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s)", (experiment, fixture_id, bucket, sampled, council_solo, Decimal(share), at))


def table(c: psycopg.Connection[Any], name: str) -> list[tuple[Any, ...]]:
    return c.execute(f"SELECT * FROM {name} ORDER BY 1, 2").fetchall()


def version(c: psycopg.Connection[Any]) -> str:
    row = c.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


# ── what the database holds ──────────────────────────────────────────────────────────────────────────────────────────────────────

def check(c: psycopg.Connection[Any], relation: str, name: str) -> tuple[str, bool]:
    """The definition of a CHECK, and whether it has been validated against the rows."""
    row = c.execute("SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint WHERE conname = %s AND conrelid = %s::regclass",
                    (name, relation)).fetchone()
    assert row is not None, f"{relation} has no constraint {name}"
    return row[0], bool(row[1])


def words_of(definition: str) -> list[str]:
    """The words a definition of the constraint allows, in order: ``CHECK ((engine = ANY (ARRAY['rules'::text, ...])))``."""
    return re.findall(r"'([^']*)'::text", definition)


def outside_the_new_table(c: psycopg.Connection[Any]) -> dict[str, list[tuple[Any, ...]]]:
    """Everything the migration must leave as it is: every column, constraint, index and trigger of every table but its own - and, of the two
    constraints it rewrites, nothing (they are held by the tests that name them)."""
    system = "('pg_catalog', 'information_schema', 'pg_toast')"
    rewritten = f"('{ENGINE_CHECK}', '{KIND_CHECK}')"
    return {
        "columns": c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                             f"WHERE table_schema NOT IN {system} AND NOT (table_schema = 'ai' AND table_name = 'shadow_assignments') "
                             "ORDER BY 1, 2, ordinal_position").fetchall(),
        "constraints": c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid), convalidated FROM pg_constraint "
                                 f"WHERE connamespace::regnamespace::text NOT IN {system} AND conrelid::regclass::text <> 'ai.shadow_assignments' "
                                 f"AND conname NOT IN {rewritten} ORDER BY 1, 2").fetchall(),
        "indexes": c.execute("SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes "
                             f"WHERE schemaname NOT IN {system} AND NOT (schemaname = 'ai' AND tablename = 'shadow_assignments') ORDER BY 1, 2, 3").fetchall(),
        "triggers": c.execute("SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                              "WHERE NOT tgisinternal AND tgrelid::regclass::text <> 'ai.shadow_assignments' ORDER BY 1, 2").fetchall(),
    }


def exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


# ── the upgrade ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_0119_keeps_what_was_written_accepts_the_new_words_and_moves_nothing_else() -> None:
    with scratch_at("0118") as dsn:
        with psycopg.connect(dsn) as c:
            fixture = a_fixture(c)
            for n, engine in enumerate(OLD_ENGINES):
                review(c, fixture, engine, n=n)
            for kind in OLD_KINDS:
                cycle(c, kind)
            cycle(c, "package", status="running", at=NOON + timedelta(hours=1))
            c.commit()
            reviews, ledger, rest = table(c, "ai.pick_reviews"), table(c, "ai.cycles"), outside_the_new_table(c)
            (engine_def, engine_ok), (kind_def, kind_ok) = check(c, "ai.pick_reviews", ENGINE_CHECK), check(c, "ai.cycles", KIND_CHECK)
            assert engine_ok and kind_ok and not exists(c, TABLE)
            assert words_of(engine_def) == list(OLD_ENGINES) and words_of(kind_def) == list(OLD_KINDS)
            for engine in NEW_ENGINES:
                with refuses(c, psycopg.errors.CheckViolation, constraint=ENGINE_CHECK):
                    review(c, fixture, engine, n=99)  # 0118 knows no such engine
            with refuses(c, psycopg.errors.CheckViolation, constraint=KIND_CHECK):
                cycle(c, "orchestrate")

        command.upgrade(_cfg(), "0119")
        with psycopg.connect(dsn) as c:
            assert version(c) == "0119"
            assert table(c, "ai.pick_reviews") == reviews and table(c, "ai.cycles") == ledger, "every row written before is as it was: same ids, same content"
            assert outside_the_new_table(c) == rest, "no other column, constraint, index or trigger of the database moved"
            (engine_def, engine_ok), (kind_def, kind_ok) = check(c, "ai.pick_reviews", ENGINE_CHECK), check(c, "ai.cycles", KIND_CHECK)
            assert engine_ok and kind_ok, "both lists are validated against the rows"
            assert words_of(engine_def) == [*OLD_ENGINES, *NEW_ENGINES] and " OR " not in engine_def, engine_def
            assert words_of(kind_def) == [*OLD_KINDS, "orchestrate"] and " OR " not in kind_def, kind_def
            assert c.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,), "the migration writes no row"

            for n, engine in enumerate((*OLD_ENGINES, *NEW_ENGINES), start=10):
                review(c, fixture, engine, n=n)  # the old engines as before, the new ones now
            for nonsense in ("bogus", "", "ma-v1 ", " ma-v1", "MA-V1", "ma_v1", "ma-v2", "ma-v1-H", "ma-v1-h2", "cs-v2", "cs_v1", "council_solo",
                             "council-solo", "multiagent", "shadow", "production", "combined2", "Combined", "ma-v1,cs-v1", "stats-v1"):
                with refuses(c, psycopg.errors.CheckViolation, constraint=ENGINE_CHECK):
                    review(c, fixture, nonsense, n=500)
            for kind in (*OLD_KINDS, "orchestrate"):
                cycle(c, kind, at=NOON + timedelta(days=1))
            running = cycle(c, "orchestrate", status="running", at=NOON + timedelta(days=1, hours=1))
            assert c.execute("SELECT kind, status, finished_at FROM ai.cycles WHERE id = %s", (running,)).fetchone() == ("orchestrate", "running", None)
            for nonsense in ("", "Orchestrate", "orchestrate ", "orchestrator", "orchestrate-v1", "shadow", "ORCHESTRATE", "stats", "council"):
                with refuses(c, psycopg.errors.CheckViolation, constraint=KIND_CHECK):
                    cycle(c, nonsense)
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("UPDATE ai.pick_reviews SET decision = 'REJECT' WHERE engine = 'ma-v1'")  # the table is as append-only as it was
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("DELETE FROM ai.pick_reviews WHERE engine = 'cs-v1'")
            c.execute("UPDATE ai.cycles SET status = 'ok', finished_at = started_at WHERE id = %s", (running,))  # and the ledger of the jobs is still editable
            c.rollback()


def test_0119_the_table_has_the_columns_the_keys_and_the_trigger_the_arms_need() -> None:
    with scratch_at("0119") as dsn, psycopg.connect(dsn) as c:
        columns = c.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'ai' "
                            "AND table_name = 'shadow_assignments' ORDER BY ordinal_position").fetchall()
        assert columns == COLUMNS
        assert c.execute("SELECT column_name FROM information_schema.key_column_usage WHERE table_schema = 'ai' AND table_name = 'shadow_assignments' "
                         "AND constraint_name = 'shadow_assignments_pkey' ORDER BY ordinal_position").fetchall() == [("experiment",), ("fixture_id",)]
        constraints = {r[0] for r in c.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'ai.shadow_assignments'::regclass").fetchall()}
        assert constraints == {"shadow_assignments_pkey", "shadow_assignments_experiment_check", "shadow_assignments_fixture_id_check",
                               "shadow_assignments_bucket_check", "shadow_assignments_share_check", "shadow_assignments_solo_is_sampled",
                               "shadow_assignments_sample_rule"}
        assert c.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'ai.shadow_assignments'::regclass AND contype = 'f'").fetchall() == [], \
            "no foreign key: the busy tables are not pointed to"
        assert c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'ai' AND tablename = 'shadow_assignments'").fetchall() == [
            ("shadow_assignments_pkey",)]
        triggers = c.execute("SELECT tgname, tgenabled, (tgtype & 1) = 1 AS per_row, (tgtype & 2) = 2 AS before, (tgtype & 8) = 8 AS on_delete, "
                             "(tgtype & 16) = 16 AS on_update, (tgtype & 4) = 4 AS on_insert, tgfoid::regproc::text FROM pg_trigger "
                             "WHERE tgrelid = 'ai.shadow_assignments'::regclass AND NOT tgisinternal").fetchall()
        assert triggers == [("shadow_assignments_append_only", "O", True, True, True, True, False, "ai.refuse_change")], \
            "a trigger BEFORE UPDATE OR DELETE for each row, the one of the siblings, and not one on the insert"
        assert c.execute("SELECT obj_description('ai.shadow_assignments'::regclass)").fetchone() != (None,), "the table says what it is"
        said = {name for name, comment in c.execute("SELECT a.attname, col_description(a.attrelid, a.attnum) FROM pg_attribute a "
                                                    "WHERE a.attrelid = 'ai.shadow_assignments'::regclass AND a.attnum > 0 AND NOT a.attisdropped").fetchall()
                if comment}
        assert {"experiment", "fixture_id", "bucket", "council_solo", "share"} <= said, "and so does every column whose meaning is not in its name"


# ── the rows of the table ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_assignment_is_written_once_and_cannot_be_changed_or_removed(db: psycopg.Connection[Any], seed: Seed) -> None:
    assignment(db, seed.fixture_id)
    assert db.execute("SELECT experiment, fixture_id, bucket, sampled, council_solo, share, assigned_at FROM ai.shadow_assignments").fetchall() == [
        (EXPERIMENT, seed.fixture_id, 10, True, False, Decimal("0.3"), NOON)]
    with refuses(db, psycopg.errors.UniqueViolation, constraint="shadow_assignments_pkey"):
        assignment(db, seed.fixture_id, bucket=11)  # the match is assigned once in an experiment, whatever the second row says
    assignment(db, seed.fixture_id, experiment="ma-shadow-v2")  # in another experiment it has its own group
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("UPDATE ai.shadow_assignments SET sampled = false, bucket = 9000 WHERE fixture_id = %s", (seed.fixture_id,))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("UPDATE ai.shadow_assignments SET share = 0.9")
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("DELETE FROM ai.shadow_assignments WHERE fixture_id = %s", (seed.fixture_id,))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("DELETE FROM ai.shadow_assignments")
    assert db.execute("SELECT count(*) FROM ai.shadow_assignments").fetchone() == (2,), "and none of it left a trace"


@pytest.mark.parametrize(("what", "values", "constraint"), [
    ("an experiment with no name", {"experiment": ""}, "shadow_assignments_experiment_check"),
    ("an experiment that starts with a separator", {"experiment": "-ma"}, "shadow_assignments_experiment_check"),
    ("an experiment with a space", {"experiment": "ma shadow"}, "shadow_assignments_experiment_check"),
    ("an experiment with a slash", {"experiment": "ma/shadow"}, "shadow_assignments_experiment_check"),
    ("an experiment of 65 characters", {"experiment": "a" * 65}, "shadow_assignments_experiment_check"),
    ("a fixture that is not one", {"fixture_id": 0}, "shadow_assignments_fixture_id_check"),
    ("a negative fixture", {"fixture_id": -4}, "shadow_assignments_fixture_id_check"),
    ("a negative bucket", {"bucket": -1}, "shadow_assignments_bucket_check"),
    ("a bucket past the last", {"bucket": 10000, "share": "1", "sampled": False}, "shadow_assignments_bucket_check"),
    ("a share of zero (nothing is assigned at zero)", {"share": "0", "sampled": False}, "shadow_assignments_share_check"),
    ("a negative share", {"share": "-0.1", "sampled": False}, "shadow_assignments_share_check"),
    ("a share above one", {"share": "1.0001"}, "shadow_assignments_share_check"),
    ("a sampled match above the share", {"bucket": 3000, "share": "0.3", "sampled": True}, "shadow_assignments_sample_rule"),
    ("an unsampled match below the share", {"bucket": 2999, "share": "0.3", "sampled": False}, "shadow_assignments_sample_rule"),
    ("an unsampled match at bucket zero", {"bucket": 0, "share": "0.0001", "sampled": False}, "shadow_assignments_sample_rule"),
    ("a share with a tail of zeros is the same share", {"bucket": 3000, "share": "0.30000000000000000000000000000", "sampled": True},
     "shadow_assignments_sample_rule"),
    ("COUNCIL SOLO without the sample", {"bucket": 9000, "sampled": False, "council_solo": True}, "shadow_assignments_solo_is_sampled"),
])
def test_the_table_refuses_what_contradicts_itself(db: psycopg.Connection[Any], seed: Seed, what: str, values: dict[str, Any], constraint: str) -> None:
    base: dict[str, Any] = {"experiment": EXPERIMENT, "fixture_id": seed.fixture_id, "bucket": 10, "sampled": True, "council_solo": False,
                            "share": "0.3", "at": NOON}
    row = base | values
    with refuses(db, psycopg.errors.CheckViolation, constraint=constraint):
        assignment(db, row["fixture_id"], experiment=row["experiment"], bucket=row["bucket"], sampled=row["sampled"],
                   council_solo=row["council_solo"], share=row["share"], at=row["at"])


@pytest.mark.parametrize(("bucket", "share", "sampled"), [
    (0, "0.0001", True), (1, "0.0001", False), (2999, "0.3", True), (3000, "0.3", False), (9999, "1", True), (9999, "0.9999", False),
    (9998, "0.9999", True), (0, "0.00000000000000000000000000001", True), (3000, "0.30000000000000000000000000001", True),
    (3000, "0.3000", False), (5000, "0.5", False), (4999, "0.5", True), (1500, "0.15", False), (1499, "0.15", True),
])
def test_the_database_holds_the_rule_of_the_sample_to_the_last_digit(db: psycopg.Connection[Any], seed: Seed, bucket: int, share: str,
                                                                    sampled: bool) -> None:
    """``bucket < share * 10000`` with no rounding anywhere: the share is stored as it came, and so is the product."""
    assignment(db, seed.fixture_id, bucket=bucket, share=share, sampled=sampled)
    with refuses(db, psycopg.errors.CheckViolation, constraint="shadow_assignments_sample_rule"):
        assignment(db, seed.fixture_id, experiment="the-other-one", bucket=bucket, share=share, sampled=not sampled, council_solo=False)


@pytest.mark.parametrize("column", [c[0] for c in COLUMNS])
def test_every_column_is_required(db: psycopg.Connection[Any], seed: Seed, column: str) -> None:
    values: dict[str, Any] = {"experiment": EXPERIMENT, "fixture_id": seed.fixture_id, "bucket": 10, "sampled": True, "council_solo": False,
                              "share": Decimal("0.3"), "assigned_at": NOON}
    values[column] = None
    with refuses(db, psycopg.errors.NotNullViolation):
        db.execute(f"INSERT INTO ai.shadow_assignments ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))})", list(values.values()))


def test_a_match_that_is_in_council_solo_is_in_the_sample_and_one_outside_it_is_in_no_arm(db: psycopg.Connection[Any], seed: Seed) -> None:
    assignment(db, seed.fixture_id, bucket=10, sampled=True, council_solo=True)
    assignment(db, seed.fixture_id, experiment="a-second-one", bucket=9000, sampled=False, council_solo=False)  # outside the sample: no arm, but a row
    assert db.execute("SELECT experiment, sampled, council_solo FROM ai.shadow_assignments ORDER BY experiment").fetchall() == [
        ("a-second-one", False, False), (EXPERIMENT, True, True)]


# ── the new words and the words of the code ──────────────────────────────────────────────────────────────────────────────────────

def test_0119_the_words_of_the_database_are_words_of_the_code() -> None:
    """The engines the database accepts are the production three and the shadow three of the configuration, and the kinds of cycle are the ones of
    0112 and ``orchestrate`` (that the code opens no other is held, without a database, by ``tests/unit/test_migration_0119.py``)."""
    with scratch_at("0119") as dsn, psycopg.connect(dsn) as c:
        assert tuple(words_of(check(c, "ai.pick_reviews", ENGINE_CHECK)[0])[3:]) == tuple(SHADOW_ENGINES) == NEW_ENGINES
        assert words_of(check(c, "ai.cycles", KIND_CHECK)[0]) == [*OLD_KINDS, "orchestrate"]


# ── the downgrade ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_0119_downgrade_deletes_no_review_and_the_old_lists_judge_only_what_comes_after() -> None:
    with scratch_at("0119") as dsn:
        with psycopg.connect(dsn) as c:
            fixture = a_fixture(c)
            kept = [review(c, fixture, engine, n=n, at=NOON + timedelta(minutes=n)) for n, engine in enumerate((*OLD_ENGINES, *NEW_ENGINES, "ma-v1"))]
            old = [cycle(c, kind, at=NOON + timedelta(hours=n)) for n, kind in enumerate(OLD_KINDS)]
            finished = cycle(c, "orchestrate", at=NOON + timedelta(hours=9))
            stuck = cycle(c, "orchestrate", status="running", at=NOON + timedelta(hours=10))
            package = cycle(c, "package", status="running", at=NOON + timedelta(hours=11))
            assignment(c, fixture)
            c.commit()
            reviews, ledger = table(c, "ai.pick_reviews"), table(c, "ai.cycles")
            rest_before = outside_the_new_table(c)

        command.downgrade(_cfg(), "0118")
        with psycopg.connect(dsn) as c:
            assert version(c) == "0118"
            assert table(c, "ai.pick_reviews") == reviews, "no review was deleted and none was changed"
            assert [r[0] for r in reviews] == kept
            assert not exists(c, TABLE), "the assignments went with their table"
            assert outside_the_new_table(c) == rest_before, "nothing else moved on the way down either"

            (engine_def, engine_ok), (kind_def, kind_ok) = check(c, "ai.pick_reviews", ENGINE_CHECK), check(c, "ai.cycles", KIND_CHECK)
            assert not engine_ok and not kind_ok, "NOT VALID: the old lists judge what is written from now on, and the rows of the shadow stay"
            assert words_of(engine_def) == list(OLD_ENGINES) and " OR " not in engine_def
            assert words_of(kind_def) == list(OLD_KINDS) and " OR " not in kind_def
            for engine in NEW_ENGINES:
                with refuses(c, psycopg.errors.CheckViolation, constraint=ENGINE_CHECK):
                    review(c, fixture, engine, n=700)
            with refuses(c, psycopg.errors.CheckViolation, constraint=KIND_CHECK):
                cycle(c, "orchestrate")
            review(c, fixture, "combined", n=701, at=NOON + timedelta(days=1))  # the code that ran before goes on writing what it wrote
            with refuses(c, psycopg.errors.CheckViolation, saying="append-only"):
                c.execute("DELETE FROM ai.pick_reviews WHERE engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')")  # and the old schema cannot remove them either

            after = {r[0]: r for r in table(c, "ai.cycles")}
            assert [after[i] for i in old] == [r for r in ledger if r[0] in old], "the cycles of the kinds it knows are as they were"
            assert after[finished] == next(r for r in ledger if r[0] == finished), "a finished cycle of the new kind stays"
            closed_row = c.execute("SELECT status, finished_at = started_at, error FROM ai.cycles WHERE id = %s", (stuck,)).fetchone()
            assert closed_row is not None and closed_row[0] == "failed" and closed_row[1] is True and str(closed_row[2]).startswith("interrupted"), closed_row
            assert c.execute("SELECT status FROM ai.cycles WHERE id = %s", (package,)).fetchone() == ("running",), \
                "a cycle of a kind the old code opens is left to its own recovery"
            closed, requests = cycles.recover_interrupted(c, before=NOON + timedelta(days=2), at=NOON + timedelta(days=2))
            assert (closed, requests) == (1, 0), "the recovery of the old code (one statement over every cycle left running) goes through"
            c.rollback()


def test_0119_goes_down_and_up_again_with_the_rows_of_both_times() -> None:
    with scratch_at("0119") as dsn:
        with psycopg.connect(dsn) as c:
            fixture = a_fixture(c)
            first = review(c, fixture, "ma-v1", n=1)
            assignment(c, fixture)
            c.commit()
        command.downgrade(_cfg(), "0118")
        with psycopg.connect(dsn) as c:
            between = review(c, fixture, "llm", n=2, at=NOON + timedelta(hours=1))
            c.commit()
        command.upgrade(_cfg(), "0119")  # with a review of the shadow among the rows it validates
        with psycopg.connect(dsn) as c:
            assert version(c) == "0119"
            assert check(c, "ai.pick_reviews", ENGINE_CHECK)[1] and check(c, "ai.cycles", KIND_CHECK)[1], "validated again, against every row"
            assert [r[0] for r in table(c, "ai.pick_reviews")] == [first, between]
            assert table(c, TABLE) == [], "a new experiment: the old assignments went with their table"
            assignment(c, fixture, bucket=10)
            review(c, fixture, "cs-v1", n=3, at=NOON + timedelta(hours=2))
            c.commit()
        command.downgrade(_cfg(), "0118")
        command.upgrade(_cfg(), "0119")  # and again, with a review of the shadow written after the first return
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM ai.pick_reviews WHERE engine IN ('ma-v1', 'cs-v1')").fetchone() == (2,)


# ── the lock ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("direction", ["up", "down"])
def test_0119_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    """A script holding a lock on the last table the migration needs: it gives up after ten seconds and leaves nothing half done - the table is
    still there (down) or still not (up), and both lists are as they were."""
    before, after = ("0118", "0119") if direction == "up" else ("0119", "0118")
    held = "ai.cycles" if direction == "up" else "ai.pick_reviews"

    def move() -> None:
        (command.upgrade if direction == "up" else command.downgrade)(_cfg(), after)

    with scratch_at(before) as dsn:
        holder = psycopg.connect(dsn)  # the worker writing, with its transaction open
        holder.execute(f"LOCK TABLE {held} IN ROW EXCLUSIVE MODE")
        failure: list[BaseException] = []

        def migrate() -> None:
            try:
                move()
            except BaseException as exc:  # the thread reports, the test judges
                failure.append(exc)

        started = time.monotonic()
        worker = threading.Thread(target=migrate, daemon=True)  # a migration that waited for ever must fail the test, not hang the run
        worker.start()
        worker.join(60)
        assert not worker.is_alive(), "the migration must give up, not wait"
        assert failure and isinstance(failure[0], DBAPIError) and "lock timeout" in str(failure[0]).lower(), failure
        assert 8 < time.monotonic() - started < 40, "it waited for the lock, ten seconds, and then let go"
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            assert version(c) == before
            assert exists(c, TABLE) == (direction == "down"), "the table is exactly where it was"
            assert words_of(check(c, "ai.pick_reviews", ENGINE_CHECK)[0]) == ([*OLD_ENGINES, *NEW_ENGINES] if direction == "down" else list(OLD_ENGINES))
            assert words_of(check(c, "ai.cycles", KIND_CHECK)[0]) == ([*OLD_KINDS, "orchestrate"] if direction == "down" else list(OLD_KINDS))
            assert check(c, "ai.pick_reviews", ENGINE_CHECK)[1] and check(c, "ai.cycles", KIND_CHECK)[1], "and as validated as they were"
        move()  # with the lock free it applies whole
        with psycopg.connect(dsn) as c:
            assert version(c) == after
            assert exists(c, TABLE) == (direction == "up")


def test_the_chain_of_the_revisions_has_this_migration_after_0118() -> None:
    """0119 follows 0118 and nothing in the repository sits between them."""
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0119")
    assert revision is not None and revision.down_revision == "0118"
    heads = script.get_heads()
    assert "0119" in heads or all(h > "0119" for h in heads), heads
    assert re.fullmatch(r"\d{4}", revision.revision)

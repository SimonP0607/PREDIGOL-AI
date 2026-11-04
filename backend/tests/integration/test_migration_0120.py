"""Migration 0120 (Plan Maestro IA, phase 5): the attributions of the shadow and the agent a hypothesis or an experiment is about - and nothing else
changes.

The table is append-only, idempotent by its unique key, refuses what contradicts itself (a miss without a class, a refinement without the row it
refines), and holds in the database the words the code writes. The two old tables get two nullable columns that come in pairs, the rows written before
stay as they were, and nothing waits for a lock longer than ten seconds. The scratch database is named after the one of this run (``FBI_TEST_DB``).
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Jsonb
from sqlalchemy.exc import DBAPIError

from tests.integration.agent_tables import refuses
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg, _drop

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0120"
NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
TABLE = "intel.agent_attributions"
BOTH = ("analytics.research_hypotheses", "analytics.experiments")


def row(**over: Any) -> dict[str, Any]:
    """A MISS of the Council on a selection, as the rule of the code writes it."""
    values: dict[str, Any] = {
        "attribution_version": "attr-v1", "classified_by": "code", "fixture_id": 1, "market_key": "1X2", "selection": "HOME", "line": 0,
        "engine": "ma-v1", "agent": "council", "agent_version": "council-v1", "signal": "VERDICT", "stance": "APPROVE", "outcome": "MISS",
        "error_class": "UNKNOWN", "settled": "loss", "toward_close": False, "calibration": "MARKET_BETTER", "clv": -0.05, "review_id": 1,
        "run_id": 2, "postmortem_id": 3, "basis_id": None, "source": "live", "computed_at": NOON,
    }
    return values | over


def put(c: psycopg.Connection[Any], **over: Any) -> int:
    values = row(**over)
    cur = c.execute(f"INSERT INTO {TABLE} ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING id", list(values.values()))
    found = cur.fetchone()
    assert found is not None
    return int(found[0])


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


def columns(c: psycopg.Connection[Any], table: str) -> list[str]:
    schema, name = table.split(".")
    return [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                                    "ORDER BY ordinal_position", (schema, name)).fetchall()]


def exists(c: psycopg.Connection[Any], name: str) -> bool:
    found = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return found is not None and found[0] is not None


def hypothesis(c: psycopg.Connection[Any], **over: Any) -> int:
    values: dict[str, Any] = {"proposed_by": "ai", "title": "the Council over-trusts MARKET_MOVE", "hypothesis": "h", "rationale": "r",
                              "evidence": Jsonb({}), "created_at": NOON} | over
    found = c.execute(f"INSERT INTO analytics.research_hypotheses ({', '.join(values)}) VALUES ({', '.join(['%s'] * len(values))}) RETURNING id",
                      list(values.values())).fetchone()
    assert found is not None
    return int(found[0])


# -- the table ---------------------------------------------------------------------------------------------------------------------

def test_a_row_is_written_once_and_cannot_be_changed_or_removed(db: psycopg.Connection[Any]) -> None:
    first = put(db)
    with refuses(db, psycopg.errors.UniqueViolation, constraint="agent_attributions_once"):
        put(db, source="batch")  # the second computation of the same row writes nothing new
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute(f"UPDATE {TABLE} SET outcome = 'HIT', error_class = 'NONE' WHERE id = %s", (first,))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute(f"DELETE FROM {TABLE} WHERE id = %s", (first,))


def test_a_refinement_is_one_second_row_of_a_miss_the_code_left_unknown(db: psycopg.Connection[Any]) -> None:
    basis = put(db)
    put(db, classified_by="pmr-v1", basis_id=basis, error_class="CONTEXT_ERROR")
    with refuses(db, psycopg.errors.UniqueViolation, constraint="agent_attributions_one_refinement"):
        put(db, classified_by="pmr-v1", basis_id=basis, error_class="DATA_ERROR", attribution_version="attr-v2")


@pytest.mark.parametrize(("what", "over", "constraint"), [
    ("a miss without a class", {"outcome": "MISS", "error_class": "NONE"}, "agent_attributions_a_miss_has_a_class"),
    ("a hit with a class", {"outcome": "HIT", "error_class": "MODEL_ERROR"}, "agent_attributions_a_miss_has_a_class"),
    ("a refinement without its basis", {"classified_by": "pmr-v1"}, "agent_attributions_a_refinement_refines"),
    ("a basis on the code's row", {"basis_id": 4}, "agent_attributions_a_refinement_refines"),
    ("a refinement of a hit", {"classified_by": "pmr-v1", "basis_id": 4, "outcome": "HIT", "error_class": "NONE"},
     "agent_attributions_a_refinement_refines_a_miss"),
    ("an engine of production", {"engine": "rules"}, "agent_attributions_engine_check"),
    ("an agent nobody has", {"agent": "oracle"}, "agent_attributions_agent_check"),
    ("a version that is not a label", {"agent_version": "v1"}, "agent_attributions_agent_version_check"),
    ("a signal that is not one", {"signal": "VIBES"}, "agent_attributions_signal_check"),
    ("a stance that is not a code", {"stance": "MAYBE"}, "agent_attributions_stance_check"),
    ("an outcome that is not one", {"outcome": "DRAW", "error_class": "NONE"}, "agent_attributions_outcome_check"),
    ("a class that is not one", {"error_class": "BAD_LUCK"}, "agent_attributions_error_class_check"),
    ("a settlement that is not one", {"settled": "won"}, "agent_attributions_settled_check"),
    ("a source that is not one", {"source": "cron"}, "agent_attributions_source_check"),
    ("a calibration that is not one", {"calibration": "BOTH"}, "agent_attributions_calibration_check"),
    ("a fixture that is not one", {"fixture_id": 0}, "agent_attributions_fixture_id_check"),
])
def test_the_table_refuses_what_contradicts_itself(db: psycopg.Connection[Any], what: str, over: dict[str, Any], constraint: str) -> None:
    with refuses(db, psycopg.errors.CheckViolation, constraint=constraint):
        put(db, **over)


def test_the_table_points_to_no_other_table(db: psycopg.Connection[Any]) -> None:
    found = db.execute("SELECT count(*) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'", (TABLE,)).fetchone()
    assert found == (0,), "a row of evidence outlives a cleaned table"


# -- the two columns ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("table", BOTH)
def test_the_old_tables_gain_two_nullable_columns_and_nothing_else(db: psycopg.Connection[Any], table: str) -> None:
    assert columns(db, table)[-2:] == ["agent", "agent_version"]
    nullable = db.execute("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema || '.' || table_name = %s "
                          "AND column_name IN ('agent', 'agent_version') ORDER BY 1", (table,)).fetchall()
    assert nullable == [("agent", "YES", None), ("agent_version", "YES", None)]


def test_a_hypothesis_about_an_agent_names_the_agent_and_its_version_or_neither(db: psycopg.Connection[Any]) -> None:
    plain = hypothesis(db, dedup_key="plain")
    about = hypothesis(db, dedup_key="about", agent="council", agent_version="council-v1")
    assert db.execute("SELECT agent, agent_version FROM analytics.research_hypotheses WHERE id IN (%s, %s) ORDER BY id", (plain, about)).fetchall() == [
        (None, None), ("council", "council-v1")]
    with refuses(db, psycopg.errors.CheckViolation, constraint="research_hypotheses_agent_pair"):
        hypothesis(db, dedup_key="half", agent="council")
    with refuses(db, psycopg.errors.CheckViolation, constraint="research_hypotheses_agent_pair"):
        hypothesis(db, dedup_key="half2", agent_version="council-v1")
    with refuses(db, psycopg.errors.CheckViolation, constraint="research_hypotheses_agent_check"):
        hypothesis(db, dedup_key="who", agent="oracle", agent_version="oracle-v1")
    with refuses(db, psycopg.errors.CheckViolation, constraint="research_hypotheses_agent_version_check"):
        hypothesis(db, dedup_key="which", agent="council", agent_version="latest")
    hypothesis(db, dedup_key="reviewer", agent="reviewer", agent_version="ai-v1")


# -- the migration -----------------------------------------------------------------------------------------------------------------

def test_0120_goes_down_and_up_again_and_keeps_the_rows_written_before() -> None:
    with scratch_at("0119") as dsn:
        with psycopg.connect(dsn) as c:
            hid = hypothesis(c, dedup_key="old")
            c.commit()
        command.upgrade(_cfg(), "0120")
        with psycopg.connect(dsn) as c:
            assert exists(c, TABLE)
            assert c.execute("SELECT agent, agent_version FROM analytics.research_hypotheses WHERE id = %s", (hid,)).fetchone() == (None, None)
            c.execute("UPDATE analytics.research_hypotheses SET agent = 'match', agent_version = 'match-v1' WHERE id = %s", (hid,))
            put(c)
            c.commit()
        command.downgrade(_cfg(), "0119")
        with psycopg.connect(dsn) as c:
            assert not exists(c, TABLE)
            for table in BOTH:
                assert "agent" not in columns(c, table) and "agent_version" not in columns(c, table)
            assert c.execute("SELECT id FROM analytics.research_hypotheses").fetchall() == [(hid,)], "the hypothesis stays; only the columns go"
        command.upgrade(_cfg(), "0120")
        with psycopg.connect(dsn) as c:
            assert exists(c, TABLE)
            assert c.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,), "the attributions are recomputed from the shadow reviews, which stay"


@pytest.mark.parametrize("direction", ["up", "down"])
def test_0120_never_waits_for_a_lock_longer_than_it_can_afford(direction: str) -> None:
    before, after = ("0119", "0120") if direction == "up" else ("0120", "0119")

    def move() -> None:
        (command.upgrade if direction == "up" else command.downgrade)(_cfg(), after)

    with scratch_at(before) as dsn:
        holder = psycopg.connect(dsn)
        holder.execute("LOCK TABLE analytics.research_hypotheses IN ROW EXCLUSIVE MODE")
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
        assert 8 < time.monotonic() - started < 40
        holder.rollback()
        holder.close()
        with psycopg.connect(dsn) as c:
            found = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert found == (before,)
            assert exists(c, TABLE) == (direction == "down"), "the table is exactly where it was"
        move()
        with psycopg.connect(dsn) as c:
            assert exists(c, TABLE) == (direction == "up")

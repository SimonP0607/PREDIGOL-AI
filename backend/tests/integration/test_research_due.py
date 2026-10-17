"""When the weekly research-V2 run is due: the model code and the dataset version decide, not the repository commit.

On 5 Oct 2026 the Evolution page said "the weekly research would run now: the code changed" after a deploy that had
touched only the health checks - nothing a model learns from. A run now records its model code (and the MODEL_READY
dataset version it learned from) in ``environment``, and ``v2_due`` compares those."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from fbi.research.loop import latest_v2, v2_due, v2_due_reason

AT = datetime(2030, 3, 4, 12, 0, tzinfo=UTC)


def _run(conn: psycopg.Connection, *, commit: str, environment: dict[str, str], finished: datetime) -> int:
    row = conn.execute(
        "INSERT INTO analytics.experiments (name, kind, question, model_family, config, code_version, environment, "
        "metrics, status, finished_at, run_label, role) VALUES (%s, 'backtest', 'q', 'poisson', '{}'::jsonb, %s, %s, "
        "'{\"n\": 1}'::jsonb, 'completed', %s, 'RESEARCH_V2', 'RESEARCH') RETURNING id",
        (f"due-test-{commit}", commit, Jsonb(environment), finished)).fetchone()
    assert row is not None
    return int(row[0])


def test_a_deploy_that_did_not_touch_the_model_code_does_not_make_research_due(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        try:
            _run(conn, commit="aaaaaaaaaaaa", environment={"model_code": "mc0123456789"}, finished=AT - timedelta(days=1))
            assert latest_v2(conn)["model_code"] == "mc0123456789"  # type: ignore[index]
            assert v2_due(conn, at=AT, version="mc0123456789") is None, "same model code, a day old: not due"
            assert v2_due(conn, at=AT, version="mc9999999999") == (
                "the model code changed (mc0123456789 -> mc9999999999)")
            reason = v2_due_reason(conn, at=AT, version="mc9999999999")
            assert reason is not None and reason.code == "model_code_changed"
            assert reason.vars == {"before": "mc0123456789", "after": "mc9999999999"}
            assert v2_due(conn, at=AT + timedelta(days=30), version="mc0123456789") == "the last run is four weeks old"
        finally:
            conn.rollback()


def test_a_run_stored_before_fingerprints_says_its_model_code_is_unknown(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        try:
            _run(conn, commit="24f1dfb18310", environment={"python": "3.12"}, finished=AT - timedelta(days=1))
            why = v2_due(conn, at=AT, version="mc0123456789")
            assert why is not None and "predates model-code fingerprints" in why and "24f1dfb18310" in why
        finally:
            conn.rollback()


def test_a_newly_promoted_dataset_version_makes_research_due(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        try:
            _run(conn, commit="bbbbbbbbbbbb", environment={"model_code": "mc0123456789"}, finished=AT - timedelta(days=1))
            conn.execute("INSERT INTO audit.dataset_versions (name, status, model_ready, built_from, promoted_at) "
                         "VALUES ('DUE_TEST_V9', 'MODEL_READY', true, 'test', %s)", (AT,))
            assert v2_due(conn, at=AT, version="mc0123456789") == (
                "a new dataset version is MODEL_READY (none recorded -> DUE_TEST_V9)")
            _run(conn, commit="cccccccccccc", environment={"model_code": "mc0123456789",
                                                           "dataset_version": "DUE_TEST_V9"}, finished=AT)
            assert v2_due(conn, at=AT, version="mc0123456789") is None, "learned from that version already"
        finally:
            conn.rollback()


def test_environment_records_the_model_code_and_what_the_caller_adds() -> None:
    from fbi.core.version import model_code_version
    from fbi.research.experiments import environment

    env = environment(dataset_version="DATASET_V2")
    assert env["model_code"] == model_code_version() and env["dataset_version"] == "DATASET_V2"
    assert "dataset_version" not in environment()

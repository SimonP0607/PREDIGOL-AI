"""RP-1.5 against a real database: each stage with a reader is read from its table, a stopped one is told, and a missing store is not up to date."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ops import freshness

pytestmark = pytest.mark.integration

AT = datetime(2026, 12, 7, 12, 0, tzinfo=UTC)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[Any]:
    c = psycopg.connect(migrated_database)
    c.execute("DELETE FROM raw.ingestion_runs WHERE job_name IN ('research_v2_weekly', 'run_watchdog')")
    c.execute("DELETE FROM analytics.research_hypotheses")
    c.commit()
    try:
        yield c
    finally:
        c.rollback()
        c.execute("DELETE FROM raw.ingestion_runs WHERE job_name IN ('research_v2_weekly', 'run_watchdog')")
        c.execute("DELETE FROM analytics.research_hypotheses")
        c.commit()
        c.close()


def by_key(conn: Any) -> dict[str, freshness.Reading]:
    return {r.stage.key: r for r in freshness.read_all(conn, at=AT)}


def run(conn: Any, job: str, started: datetime, finished: datetime | None = None) -> None:
    conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at, finished_at, params) "
                 "VALUES (%s, %s, 'completed', %s, %s, '{}'::jsonb)", (job, job, started, finished or started))


def hypothesis(conn: Any, n: int, *, created: datetime, status: str = "PROPOSED", experiments: list[int] | None = None) -> None:
    for i in range(n):
        conn.execute(
            "INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, status, dedup_key, created_at, decided_at, experiment_ids) "
            "VALUES ('system', %s, 'h', 'r', %s, %s, %s, %s, %s)",
            (f"hipótesis de prueba {status} {i}", status, f"t-{status}-{i}-{created.isoformat()}", created,
             None if status == "PROPOSED" else created, experiments or []))


def test_an_empty_cycle_reads_twelve_stages_and_none_of_them_is_a_false_stop(conn: Any) -> None:
    got = by_key(conn)
    assert len(got) == 12
    assert got["patron"].status == "sin_registro"
    assert got["hipotesis"].status == "al_dia" and got["triage"].status == "al_dia" and got["experimento"].status == "al_dia"
    assert {k for k, r in got.items() if r.status == "sin_almacen"} == {
        "validacion_historica", "sombra_prospectiva", "comparacion", "veredicto", "propuesta_de_cambio", "seguimiento"}
    assert got["aprobacion"].status == "informativa"
    assert freshness.alarms(list(got.values())) == []


def test_the_weekly_research_that_did_not_run_in_eight_days_is_a_stop_once_the_book_is_older_than_that(conn: Any) -> None:
    run(conn, "run_watchdog", AT - timedelta(days=20))
    assert by_key(conn)["patron"].status == "parada"
    run(conn, "research_v2_weekly", AT - timedelta(days=7, hours=23))
    assert by_key(conn)["patron"].status == "al_dia"
    conn.execute("UPDATE raw.ingestion_runs SET finished_at = %s WHERE job_name = 'research_v2_weekly'", (AT - timedelta(days=8, minutes=1),))
    assert by_key(conn)["patron"].status == "parada"


def test_a_weekly_pass_that_skipped_does_not_count_as_a_run(conn: Any) -> None:
    run(conn, "run_watchdog", AT - timedelta(days=20))
    run(conn, "research_v2_weekly", AT - timedelta(hours=2))
    conn.execute("UPDATE raw.ingestion_runs SET params = '{\"skipped\": \"interruptor_apagado\"}'::jsonb WHERE job_name = 'research_v2_weekly'")
    assert by_key(conn)["patron"].status == "parada"


def test_a_weekly_pass_that_found_it_was_not_due_is_a_sign_of_life(conn: Any) -> None:
    run(conn, "run_watchdog", AT - timedelta(days=20))
    run(conn, "research_v2_weekly", AT - timedelta(hours=2))
    conn.execute("UPDATE raw.ingestion_runs SET params = '{\"skipped\": \"no_toca_aun\"}'::jsonb WHERE job_name = 'research_v2_weekly'")
    assert by_key(conn)["patron"].status == "al_dia"


def test_more_than_twenty_proposals_stop_the_hypothesis_stage_and_an_old_one_stops_the_triage(conn: Any) -> None:
    hypothesis(conn, 20, created=AT - timedelta(days=2))
    got = by_key(conn)
    assert got["hipotesis"].status == "al_dia" and got["triage"].status == "al_dia"
    hypothesis(conn, 1, created=AT - timedelta(days=32))
    got = by_key(conn)
    assert got["hipotesis"].status == "parada" and got["hipotesis"].value == 21.0
    assert got["triage"].status == "parada" and got["triage"].value is not None and got["triage"].value > 31


def test_an_accepted_hypothesis_without_an_experiment_is_a_stop_after_its_grace(conn: Any) -> None:
    hypothesis(conn, 1, created=AT - timedelta(hours=23), status="ACCEPTED")
    assert by_key(conn)["experimento"].status == "al_dia"
    hypothesis(conn, 1, created=AT - timedelta(hours=25), status="ACCEPTED")
    assert by_key(conn)["experimento"].status == "parada"


def test_the_last_postmortem_of_a_match_older_than_thirty_six_hours_stops_the_observation(conn: Any, seed: Any) -> None:
    """Post-mortems are append-only: the row stays in the transaction (rolled back at the end) and the clock is set far ahead of any other."""
    far = datetime(2090, 1, 1, tzinfo=UTC)
    conn.execute("INSERT INTO intel.match_postmortems (fixture_id, created_at, version, outcome, findings) "
                 "VALUES (%s, %s, 'rp15-test', '{}'::jsonb, '{}'::jsonb)", (seed.fixture_id, far))
    stage = freshness.STAGES[0]
    assert freshness.read_observation(conn, far + timedelta(hours=35), stage).status == "al_dia"
    assert freshness.read_observation(conn, far + timedelta(hours=37), stage).status == "parada"


def test_the_hourly_check_books_a_run_with_the_error_naming_the_stopped_stage_and_a_clean_one_otherwise(
        conn: Any, migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The simulated stop of the ficha: the scheduler's own job, the book of runs, and the alarm in it."""
    from apps.worker import scheduler

    from fbi.core.logging import configure

    configure("INFO")
    monkeypatch.setattr(scheduler, "_connect", lambda: psycopg.connect(migrated_database))
    now = datetime.now(UTC)
    ledger = psycopg.connect(migrated_database, autocommit=True)

    def last() -> tuple[Any, ...]:
        return ledger.execute("SELECT status, errors, last_error, rows_written FROM raw.ingestion_runs WHERE job_type = 'stall_check' "
                              "ORDER BY id DESC LIMIT 1").fetchone()

    ledger.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'stall_check'")
    try:
        hypothesis(conn, 21, created=now - timedelta(days=1))
        conn.commit()
        scheduler._stall_check_now()
        status, errors, last_error, written = last()
        assert (status, written) == ("partial", 12) and errors >= 1
        assert "ops.stage_stalled" in last_error and "hipotesis" in last_error
        conn.execute("DELETE FROM analytics.research_hypotheses")
        conn.commit()
        scheduler._stall_check_now()
        status, errors, _le, written = last()
        assert (status, errors, written) == ("completed", 0, 12)
    finally:
        ledger.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'stall_check'")
        ledger.close()

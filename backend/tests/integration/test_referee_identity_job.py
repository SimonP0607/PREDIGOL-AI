"""The ``referee_identity`` job as a run of the ledger (plan F3): a row only when it placed or changed something."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from fbi.ingestion import referee_identity as job
from tests.integration.test_referee_identity_store import World, small_world, world  # noqa: F401  (the fixture and the data)


@pytest.fixture()
def ledger_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []

    class FakeLedger:
        def __init__(self, conn: Any) -> None:
            self.conn = conn

        def open(self, job_type: str, *, params: dict[str, object] | None = None, **_: Any) -> int:
            runs.append({"job": job_type, "params": params, "counters": None, "notes": None})
            return len(runs)

        def close(self, run_id: int, counters: Any, *, notes: str | None = None) -> None:
            runs[run_id - 1].update(counters=counters, notes=notes)

    monkeypatch.setattr("fbi.ingestion.referee_identity.RunLedger", FakeLedger)
    return runs


def test_a_pass_that_places_leaves_one_ledger_row_and_a_quiet_one_leaves_none(world: World, ledger_runs: list[dict[str, Any]]) -> None:  # noqa: F811
    small_world(world)
    report = job.run_job(world.db, commit=False)
    assert report.changed and report.new_referees == 2
    assert len(ledger_runs) == 1 and ledger_runs[0]["job"] == job.JOB == "referee_identity"
    counters = ledger_runs[0]["counters"]
    assert counters.rows_inserted == 2 + 3 + 3 + 1 and counters.rows_normalized == 3 and counters.errors == []
    assert ledger_runs[0]["params"] == {"version": "refid-v1", "sweep": False}

    quiet = job.run_job(world.db, commit=False)
    assert not quiet.changed and len(ledger_runs) == 1, "a pass that changed nothing leaves no row in the ledger"


def test_the_sweep_audits_and_says_so(world: World, ledger_runs: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:  # noqa: F811
    small_world(world)
    job.run_job(world.db, commit=False)
    result = job._audit(world.db, commit=False)
    assert result["placed_share"] == 1.0 and not any(result["pass_would_write"].values())
    sweep = job.run_job(world.db, sweep=True, commit=False)
    assert not sweep.changed and len(ledger_runs) == 1


def test_a_pass_that_finds_the_lock_taken_leaves_nothing(world: World, ledger_runs: list[dict[str, Any]], migrated_database: str) -> None:  # noqa: F811
    small_world(world)
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext('fbi.referee_identity'))")
        report = job.run_job(world.db, commit=False)
        other.rollback()
    assert report.skipped_locked and not ledger_runs


def test_a_person_at_the_console_waits_for_the_lock_and_the_worker_does_not(world: World, ledger_runs: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from fbi.people import referees

    asked: list[bool] = []
    real = referees.build

    def spy(conn: Any, **kwargs: Any) -> referees.BuildReport:
        asked.append(kwargs.get("wait", False))
        return real(conn, **kwargs)

    monkeypatch.setattr("fbi.ingestion.referee_identity.referees.build", spy)
    small_world(world)
    job.run_job(world.db, commit=False)
    job.run_job(world.db, commit=False, wait=True)
    assert asked == [False, True]
